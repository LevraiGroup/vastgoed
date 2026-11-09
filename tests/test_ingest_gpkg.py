"""
VA-34: ingest_gpkg.py op een kleine, zelfgemaakte GeoPackage (geen 7,8 GB nodig).
Alleen standaardbibliotheek: datum, geometrie, NULL -> "", gemeentecode, dekking, alleen-lezen.
"""
import sqlite3
import struct
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ingest_gpkg as ig  # noqa: E402
import snapshots  # noqa: E402


def geom(x, y, envelope=0, klein=True, srs=28992, soort=1):
    """GeoPackage-puntblob: GP, versie, flags, srs, envelope, WKB."""
    hoofd = "<" if klein else ">"
    flags = (1 if klein else 0) | (envelope << 1)
    env = struct.pack(hoofd + "dddd", x, x, y, y) if envelope == 1 else b""
    wkb = struct.pack("<BIdd", 1, soort, x, y)
    return b"GP" + bytes([0, flags]) + struct.pack(hoofd + "i", srs) + env + wkb


def maak_gpkg(pad: Path, rijen, last_change="2026-10-31T23:00:12.563Z"):
    with closing(sqlite3.connect(pad)) as c:
        c.execute("CREATE TABLE gpkg_contents (table_name TEXT, last_change TEXT)")
        c.execute("INSERT INTO gpkg_contents VALUES ('verblijfsobject', ?)", (last_change,))
        kol = ", ".join(ig.KOLOMMEN_GPKG_SELECT)
        c.execute(f"CREATE TABLE verblijfsobject (feature_id INTEGER PRIMARY KEY AUTOINCREMENT, {kol})")
        c.executemany(f"INSERT INTO verblijfsobject ({kol}) VALUES ({', '.join('?' * len(ig.KOLOMMEN_GPKG_SELECT))})",
                      rijen)
        c.commit()


def vbo(i, wp="Delft", wp_id="2138", gemeente="0503", pc="2611AA", letter=None, g=None):
    return (f"0503010000{i:06d}", f"http://bag/{i}", 80, "Verblijfsobject in gebruik", "woonfunctie",
            "Oude Delft", i, letter, None, pc, wp, 1900, f"0503100000{i:06d}", "Pand in gebruik",
            wp_id, gemeente, g if g is not None else geom(84000.0 + i, 447000.5))


class Datum(unittest.TestCase):
    def test_last_change_wordt_nederlandse_datum(self):
        lokaal = ig.naar_amsterdam(ig.lees_last_change("2026-10-31T23:00:12.563Z"))
        self.assertEqual(lokaal.date().isoformat(), "2026-11-01")  # wintertijd: +1

    def test_zomertijd_beide_kanten_van_de_datumgrens(self):
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 7, 31, 21, 59, tzinfo=timezone.utc)).date().isoformat(),
                         "2026-07-31")
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)).date().isoformat(),
                         "2026-08-01")

    def test_tijdwissels(self):
        # 2026: zomertijd van 29 maart 01:00 UTC tot 25 oktober 01:00 UTC.
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 3, 29, 0, 59, tzinfo=timezone.utc)).utcoffset().seconds, 3600)
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)).utcoffset().seconds, 7200)
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 10, 25, 0, 59, tzinfo=timezone.utc)).utcoffset().seconds, 7200)
        self.assertEqual(ig.naar_amsterdam(datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)).utcoffset().seconds, 3600)


class Geometrie(unittest.TestCase):
    def test_zonder_en_met_envelope_en_beide_byte_ordes(self):
        self.assertEqual(ig.punt_uit_geom(geom(84249.36, 447967.18)), (84249.36, 447967.18))
        self.assertEqual(ig.punt_uit_geom(geom(1.5, 2.5, envelope=1)), (1.5, 2.5))
        self.assertEqual(ig.punt_uit_geom(geom(1.5, 2.5, klein=False)), (1.5, 2.5))

    def test_onleesbaar_is_none(self):
        for blob in (None, b"", b"XX" + b"\0" * 30, geom(1, 2, srs=4326), geom(1, 2, soort=3)):
            with self.subTest(blob=blob[:4] if blob else blob):
                self.assertIsNone(ig.punt_uit_geom(blob))


class Ingest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.map = Path(tmp.name)
        self.gpkg = self.map / "bag-light_2026-11-01.gpkg"
        maak_gpkg(self.gpkg, [vbo(1), vbo(2, letter="A"), vbo(3, pc=None),
                              vbo(4, wp="Rotterdam", wp_id="3086", gemeente="0599", g=b"kapot")])
        self.data = self.map / "data"
        self.data.mkdir()

    def lees(self, snap):
        with closing(sqlite3.connect(snap.pad)) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM vbo ORDER BY rowid")]

    def test_snapshot(self):
        voor = self.gpkg.stat()
        snap, r = ig.ingest(self.gpkg, self.data)
        self.assertEqual(snap.pad.name, "bag_nl_2026-11-01.sqlite")
        self.assertEqual(snap.ophaaldatum, "2026-11-01")
        self.assertEqual((r["verwacht"], r["geschreven"], r["uniek"], r["zonder_postcode"]), (4, 4, 4, 1))
        self.assertEqual(r["niet_gedecodeerd"], ["0503010000000004"])  # geteld en genoemd, niet weg
        self.assertTrue(r["gpkg_ongewijzigd"])
        self.assertEqual((self.gpkg.stat().st_size, self.gpkg.stat().st_mtime_ns), (voor.st_size, voor.st_mtime_ns))
        rijen = self.lees(snap)
        self.assertEqual([x["gemeentecode"] for x in rijen], ["0503", "0503", "0503", "0599"])
        self.assertEqual(rijen[0]["huisletter"], "")      # NULL -> "" (WFS-vorm)
        self.assertEqual(rijen[1]["huisletter"], "A")
        self.assertEqual(rijen[2]["postcode"], "")
        self.assertEqual(rijen[0]["pand_identificatie"], "0503100000000001")
        self.assertEqual(rijen[0]["woonplaats_naam"], "Delft")
        self.assertEqual(rijen[0]["woonplaats_identificatie"], "2138")
        self.assertEqual((rijen[0]["_x"], rijen[0]["_y"]), (84001.0, 447000.5))
        self.assertIsNone(rijen[3]["_x"])

    def test_tweede_run_zelfde_dag_laat_beide_staan(self):
        a, _ = ig.ingest(self.gpkg, self.data)
        b, _ = ig.ingest(self.gpkg, self.data)
        self.assertEqual(b.pad.name, "bag_nl_2026-11-01_2.sqlite")
        self.assertTrue(a.pad.is_file() and b.pad.is_file())

    def test_pijplijn_ziet_de_landelijke_snapshot(self):
        ig.ingest(self.gpkg, self.data)
        gevonden = [s for s in snapshots.lijst("Delft", "delft", self.data, {}, landelijk=True) if s.soort == "sqlite"]
        self.assertTrue(gevonden and gevonden[0].landelijk)
        delft = list(snapshots.stroom(gevonden[0], woonplaats_id="2138"))
        self.assertEqual(len(delft), 3)
        self.assertEqual({r["gemeentecode"] for r in delft}, {"0503"})


ECHT = sorted((Path(__file__).resolve().parent.parent / "data").glob("bag_nl_*.sqlite"))


@unittest.skipUnless(ECHT, "geen data/bag_nl_*.sqlite; de echte landelijke snapshot overgeslagen")
class EchteSnapshot(unittest.TestCase):
    """Op de echte landelijke snapshot: woonplaats -> één gemeente (via de woonplaats-index)."""

    def test_woonplaatsen_bij_hun_gemeente(self):
        with closing(sqlite3.connect(f"{ECHT[-1].resolve().as_uri()}?mode=ro", uri=True)) as c:
            for wid, code in (("2138", "0503"), ("3086", "0599"), ("1245", "0518")):
                with self.subTest(woonplaats=wid):
                    codes = c.execute("SELECT DISTINCT gemeentecode FROM vbo "
                                      "WHERE woonplaats_identificatie = ?", (wid,)).fetchall()
                    self.assertEqual(codes, [(code,)])


if __name__ == "__main__":
    unittest.main()
