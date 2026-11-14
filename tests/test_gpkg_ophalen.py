"""
VA-72: de nachtelijke controle op een nieuwere BAG-GeoPackage, en de download die compleet of
helemaal niet binnenkomt.

Geen netwerk: de feed is een opgeslagen kopie van PDOK's echte Atom-feed (2026-11-13,
tests/fixtures), en de "GeoPackage" is een kleine SQLite met gpkg_contents, geserveerd door een
lokale testserver op 127.0.0.1. Alles wordt in een tijdelijke map geschreven.
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from collections import namedtuple
from contextlib import closing, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import gpkg_ophalen as go  # noqa: E402
import ingest_gpkg  # noqa: E402

ECHTE_FEED = Path(__file__).parent / "fixtures" / "pdok_bag_atom_2026-11-13.xml"
GPKG_UPDATED = "<updated>2026-11-01T00:00:00Z</updated>"  # alleen in de GeoPackage-entry
GPKG_HREF = "https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg"
GPKG_LENGTH = 'length="7827132416"'


def maak_gpkg(pad: Path, last_change: str) -> bytes:
    """Een kleine GeoPackage-achtige SQLite met de gpkg_contents-rij die ingest_gpkg.py leest."""
    with closing(sqlite3.connect(pad)) as conn:
        conn.execute("CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT, last_change TEXT)")
        conn.execute("INSERT INTO gpkg_contents VALUES ('verblijfsobject', 'features', ?)", (last_change,))
        conn.execute("CREATE TABLE verblijfsobject (feature_id INTEGER PRIMARY KEY, x TEXT)")
        conn.executemany("INSERT INTO verblijfsobject (x) VALUES (?)", [("v" * 200,)] * 200)
        conn.commit()
    return pad.read_bytes()


class Server:
    """Een lokale PDOK-nabootsing: /bag.xml (de feed), /bag-light.gpkg (met Range), /kapot.xml."""

    def __init__(self):
        self.feed = b""
        self.gpkg = b""
        self.modus = "normaal"   # 'kort': breekt halverwege af; 'lengte': verkeerde Content-Length
        self.verzoeken: list[tuple[str, str | None]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                bereik = self.headers.get("Range")
                server.verzoeken.append((self.path, bereik))
                if self.path == "/bag.xml":
                    return self.stuur(200, server.feed)
                if self.path == "/kapot.xml":
                    return self.stuur(200, b"<feed><entry>dit is geen xml")
                if self.path != "/bag-light.gpkg":
                    return self.stuur(404, b"")
                data, begin = server.gpkg, 0
                if bereik:
                    begin = int(bereik.split("=")[1].rstrip("-"))
                self.send_response(206 if begin else 200)
                deel = data[begin:]
                lengte = len(deel) + (7 if server.modus == "lengte" else 0)
                self.send_header("Content-Length", str(lengte))
                if begin:
                    self.send_header("Content-Range", f"bytes {begin}-{len(data) - 1}/{len(data)}")
                self.end_headers()
                self.wfile.write(deel[: len(deel) // 2] if server.modus == "kort" else deel)

            def stuur(self, status, body):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.draad = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.draad.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.draad.join()

    def zet_feed(self, updated: str, lengte: int | None = None, zonder_gpkg: bool = False):
        tekst = ECHTE_FEED.read_text(encoding="utf-8")
        tekst = tekst.replace(GPKG_UPDATED, f"<updated>{updated}</updated>")
        tekst = tekst.replace(GPKG_HREF, f"{self.url}/bag-light.gpkg")
        tekst = tekst.replace(GPKG_LENGTH, f'length="{len(self.gpkg) if lengte is None else lengte}"')
        if zonder_gpkg:
            tekst = tekst.replace('type="application/geopackage+sqlite3"', 'type="application/zip"')
            tekst = tekst.replace("bag-light.gpkg", "bag-light.zip")
        self.feed = tekst.encode("utf-8")

    def gpkg_verzoeken(self):
        return [v for v in self.verzoeken if v[0] == "/bag-light.gpkg"]


class EchteFeed(unittest.TestCase):
    def test_de_opgeslagen_feed_van_pdok(self):
        entry = go.lees_feed(ECHTE_FEED.read_bytes())
        self.assertEqual(entry.datum, "2026-11-01")
        self.assertEqual(entry.updated, "2026-11-01T00:00:00Z")  # niet de 2026-11-08 van de feed of de zip
        self.assertEqual(entry.lengte, 7_827_132_416)
        self.assertEqual(entry.href, GPKG_HREF)

    def test_datum_in_nederlandse_tijd(self):
        self.assertEqual(go.datum_nl("2026-10-31T23:00:12.563Z"), "2026-11-01")  # VA-34
        self.assertEqual(go.datum_nl("2026-11-30T22:59:00Z"), "2026-11-30")

    def test_tijdelijke_naam_valt_buiten_het_patroon_van_ingest_gpkg(self):
        with tempfile.TemporaryDirectory() as tmp:
            bron = Path(tmp)
            (bron / "bag-light.gpkg.2026-12-01.deel").write_bytes(b"x")
            self.assertIsNone(ingest_gpkg.nieuwste_gpkg(bron))
            self.assertIsNone(go.nieuwste_op_schijf(bron))

    def test_instellingen_uit_config(self):
        ins = go.instellingen(go.load_config())
        self.assertEqual(ins["atom_url"], "https://service.pdok.nl/kadaster/bag/atom/bag.xml")
        self.assertEqual(ins["min_vrij_gb"], 25)
        self.assertEqual(ins["bron_map"], go.BASE / "data" / "bron")
        with self.assertRaises(go.GpkgFout) as fout:  # geen stille standaardwaarde (VA-37-les)
            go.instellingen({"geopackage": {"atom_url": "x", "bron_map": "b", "resultaat": "r"}})
        self.assertEqual(str(fout.exception), "config.yaml mist geopackage.min_vrij_gb.")


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.map = Path(self.tmp.name)
        self.bron = self.map / "bron"
        self.bron.mkdir()
        self.oud = self.bron / "bag-light_2026-11-01.gpkg"
        self.oud_bytes = maak_gpkg(self.oud, "2026-10-31T23:00:12.563Z")
        self.server = Server()
        self.addCleanup(self.server.stop)
        self.server.gpkg = maak_gpkg(self.map / "nieuw.sqlite", "2026-11-30T23:00:05Z")

    def controleer(self, feed="/bag.xml", min_gb=0):
        return go.controleer(self.server.url + feed, self.bron, min_gb, timeout=10)

    def inhoud(self):
        return sorted(p.name for p in self.bron.iterdir())

    def test_niet_nieuwer(self):
        self.server.zet_feed("2026-11-01T00:00:00Z")
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (0, "geen_nieuwere"))
        self.assertIn("Geen nieuwere GeoPackage", r["melding"])
        self.assertEqual(self.server.gpkg_verzoeken(), [])
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg"])
        self.assertEqual(r["nieuwste_op_schijf"], "2026-11-01")

    def test_nieuwer_en_compleet(self):
        self.server.zet_feed("2026-12-01T00:00:00Z")
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (0, "gedownload"), r.get("melding"))
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg", "bag-light_2026-12-01.gpkg"])
        self.assertEqual((self.bron / "bag-light_2026-12-01.gpkg").read_bytes(), self.server.gpkg)
        self.assertEqual(self.oud.read_bytes(), self.oud_bytes)  # nooit overschreven
        self.assertEqual(ingest_gpkg.nieuwste_gpkg(self.bron).name, "bag-light_2026-12-01.gpkg")
        self.assertEqual(r["nieuwste_op_schijf"], "2026-12-01")
        self.assertEqual(r["bytes_overgedragen"], len(self.server.feed) + len(self.server.gpkg))

    def test_zonder_bestand_op_schijf_is_alles_nieuwer(self):
        self.oud.rename(self.map / "elders.gpkg")
        self.server.zet_feed("2026-12-01T00:00:00Z")
        r, code = self.controleer()
        self.assertEqual((code, self.inhoud()), (0, ["bag-light_2026-12-01.gpkg"]))

    def test_afgebroken_en_de_volgende_nacht_verder(self):
        self.server.zet_feed("2026-12-01T00:00:00Z")
        self.server.modus = "kort"
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "onvolledig"))
        self.assertIn("blijft staan voor de volgende nacht", r["melding"])
        deel = self.bron / "bag-light.gpkg.2026-12-01.deel"
        self.assertEqual(deel.stat().st_size, len(self.server.gpkg) // 2)
        self.assertEqual(self.inhoud(), ["bag-light.gpkg.2026-12-01.deel", "bag-light_2026-11-01.gpkg"])
        self.assertEqual(ingest_gpkg.nieuwste_gpkg(self.bron), self.oud)  # het deel telt nooit mee

        self.server.modus = "normaal"
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (0, "gedownload"), r.get("melding"))
        self.assertEqual(self.server.gpkg_verzoeken()[-1][1], f"bytes={len(self.server.gpkg) // 2}-")
        self.assertEqual((self.bron / "bag-light_2026-12-01.gpkg").read_bytes(), self.server.gpkg)
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg", "bag-light_2026-12-01.gpkg"])

    def test_content_length_past_niet_bij_de_feed(self):
        self.server.zet_feed("2026-12-01T00:00:00Z")
        self.server.modus = "lengte"
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "onvolledig"))
        self.assertIn("Content-Length", r["melding"])
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg"])  # niets geschreven

    def test_feed_length_klopt_niet(self):
        self.server.zet_feed("2026-12-01T00:00:00Z", lengte=len(self.server.gpkg) + 1)
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "onvolledig"))
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg"])

    def test_last_change_niet_nieuwer_dan_de_feed_beweerde(self):
        self.server.gpkg = maak_gpkg(self.map / "oud2.sqlite", "2026-10-31T23:00:12.563Z")
        self.server.zet_feed("2026-12-01T00:00:00Z")
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "niet_nieuwer"))
        self.assertIn("2026-11-01", r["melding"])
        self.assertEqual(self.inhoud(), ["bag-light.gpkg.2026-12-01.deel", "bag-light_2026-11-01.gpkg"])
        self.assertEqual(self.oud.read_bytes(), self.oud_bytes)

    def test_geen_geopackage(self):
        self.server.gpkg = b"geen sqlite " * 100
        self.server.zet_feed("2026-12-01T00:00:00Z")
        r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "ongeldig"))
        self.assertEqual(self.inhoud(), ["bag-light.gpkg.2026-12-01.deel", "bag-light_2026-11-01.gpkg"])

    def test_bestaand_doel_wordt_nooit_overschreven(self):
        # Iemand anders zette het bestand er tussendoor neer: het blijft zoals het is.
        self.server.zet_feed("2026-12-01T00:00:00Z")
        doel = self.bron / "bag-light_2026-12-01.gpkg"
        doel.write_bytes(b"van iemand anders")
        with mock.patch.object(go, "nieuwste_op_schijf", return_value="2026-11-01"):
            r, code = self.controleer()
        self.assertEqual((code, r["uitkomst"]), (1, "bestaat_al"))
        self.assertEqual(doel.read_bytes(), b"van iemand anders")
        self.assertTrue((self.bron / "bag-light.gpkg.2026-12-01.deel").exists())

    def test_te_weinig_vrije_ruimte(self):
        self.server.zet_feed("2026-12-01T00:00:00Z")
        Gebruik = namedtuple("Gebruik", "total used free")
        with mock.patch.object(go.shutil, "disk_usage", return_value=Gebruik(10**12, 10**12, 3 * 10**9)):
            r, code = self.controleer(min_gb=25)
        self.assertEqual((code, r["uitkomst"]), (1, "te_weinig_ruimte"))
        self.assertIn("3,0 GB vrij, 25,0 GB nodig", r["melding"])
        self.assertEqual(self.server.gpkg_verzoeken(), [])
        self.assertEqual(self.inhoud(), ["bag-light_2026-11-01.gpkg"])

    def test_onleesbare_feed(self):
        with self.assertRaises(go.GpkgFout) as fout:
            self.controleer("/kapot.xml")
        self.assertEqual(fout.exception.uitkomst, "feed_onleesbaar")

    def test_feed_zonder_geopackage(self):
        self.server.zet_feed("2026-12-01T00:00:00Z", zonder_gpkg=True)
        with self.assertRaises(go.GpkgFout) as fout:
            self.controleer()
        self.assertEqual(fout.exception.uitkomst, "feed_zonder_gpkg")
        self.assertEqual(self.server.gpkg_verzoeken(), [])

    def test_onbereikbare_feed(self):
        with self.assertRaises(go.GpkgFout) as fout:
            self.controleer("/bestaat-niet.xml")  # HTTP 404
        self.assertEqual(fout.exception.uitkomst, "feed_onbereikbaar")

    def main(self, *args):
        uit, fout = io.StringIO(), io.StringIO()
        with redirect_stdout(uit), redirect_stderr(fout):
            code = go.main(["--bron", str(self.bron), "--resultaat", str(self.map / "uitkomst.json"),
                            "--min-vrij-gb", "0", *args])
        return code, uit.getvalue(), fout.getvalue()

    def test_main_schrijft_de_uitkomst(self):
        self.server.zet_feed("2026-11-01T00:00:00Z")
        code, uit, _ = self.main("--feed", self.server.url + "/bag.xml")
        self.assertEqual(code, 0)
        self.assertIn("Geen nieuwere GeoPackage", uit)
        r = json.loads((self.map / "uitkomst.json").read_text(encoding="utf-8"))
        self.assertEqual((r["uitkomst"], r["feed_datum"], r["nieuwste_op_schijf"]),
                         ("geen_nieuwere", "2026-11-01", "2026-11-01"))
        self.assertIn("gecontroleerd_om", r)
        self.assertEqual(sorted(p.name for p in self.map.iterdir()), ["bron", "nieuw.sqlite", "uitkomst.json"])

    def test_main_bij_onleesbare_feed_schrijft_niets(self):
        voor = sorted(p.name for p in self.map.rglob("*"))
        code, _, fout = self.main("--feed", self.server.url + "/kapot.xml")
        self.assertEqual(code, 1)
        self.assertIn("FOUT: De Atom-feed is geen leesbare XML", fout)
        self.assertEqual(sorted(p.name for p in self.map.rglob("*")), voor)


if __name__ == "__main__":
    unittest.main()
