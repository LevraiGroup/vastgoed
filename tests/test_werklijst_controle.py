"""
VA-75: de nachtelijke controle van de werklijst tegen de PDOK BAG WFS.

Geen netwerk: de antwoorden zijn opgeslagen antwoorden van de echte WFS (2026-11-17, tests/fixtures),
voor elk geval aangepast en geserveerd door een lokale testserver op 127.0.0.1. De werklijst, de
snapshot en alle uitvoer staan in een tijdelijke map.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import werklijst_controle as wc  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
ECHT_PAND = "0503100000026198"
ECHT = (FIXTURES / f"wfs_pand_{ECHT_PAND}_2026-11-17.xml").read_bytes()
ONBEKEND = (FIXTURES / "wfs_pand_onbekend_2026-11-17.xml").read_bytes()
ZONDER_VBO = (FIXTURES / "wfs_pand_zonder_vbo_2026-11-17.xml").read_bytes()
WFS = "{http://www.opengis.net/wfs/2.0}"
BAG = "{http://bag.geonovum.nl}"
SNAPSHOT = "bag_nl_2026-11-01.sqlite"
NACHT_1 = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)   # 03:00 in Amsterdam
NACHT_2 = datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc)

# Het echte pand en zijn acht verblijfsobjecten zoals de WFS ze op 2026-11-17 gaf.
ECHTE_VBO = {
    "0503010000065779": "Verblijfsobject buiten gebruik",
    "0503010000065777": "Verblijfsobject in gebruik",
    "0503010000014138": "Verbouwing verblijfsobject",
    "0503010000014139": "Verbouwing verblijfsobject",
    "0503010000003207": "Verbouwing verblijfsobject",
    "0503010000003208": "Verbouwing verblijfsobject",
    "0503010000003209": "Verbouwing verblijfsobject",
    "0503010000003210": "Verbouwing verblijfsobject",
}


def variant(pand_id: str, pandstatus: str | None = None, vbo_status: dict | None = None,
            weg: tuple = (), erbij: dict | None = None) -> bytes:
    """Het echte antwoord, voor een ander pand-ID en met de gevraagde wijzigingen."""
    tekst = ECHT.decode("utf-8").replace(ECHT_PAND, pand_id)
    # De VBO-ID's krijgen het pand-ID als voorvoegsel, zodat elk testpand zijn eigen VBO's heeft.
    for vid in ECHTE_VBO:
        tekst = tekst.replace(vid, vbo(pand_id, vid))
    wortel = ET.fromstring(tekst)
    if pandstatus is not None:
        wortel.find(f".//{BAG}pand/{BAG}status").text = pandstatus
    leden = {el.find(f"{BAG}verblijfsobject/{BAG}identificatie").text: (verz, el)
             for verz in wortel.iter(f"{WFS}FeatureCollection") for el in verz.findall(f"{WFS}member")
             if el.find(f"{BAG}verblijfsobject") is not None}
    for vid, status in (vbo_status or {}).items():
        leden[vid][1].find(f"{BAG}verblijfsobject/{BAG}status").text = status
    for vid in weg:
        verz, el = leden[vid]
        verz.remove(el)
    for vid, status in (erbij or {}).items():
        verz, el = next(iter(leden.values()))
        nieuw = copy.deepcopy(el)
        nieuw.find(f"{BAG}verblijfsobject/{BAG}identificatie").text = vid
        nieuw.find(f"{BAG}verblijfsobject/{BAG}status").text = status
        verz.append(nieuw)
    return ET.tostring(wortel, encoding="utf-8", xml_declaration=True)


def vbo(pand_id: str, echt_vid: str) -> str:
    """Een VBO-ID per testpand: de laatste vier cijfers van het pand plus die van het echte VBO."""
    return pand_id[-4:] + echt_vid[4:]


def vbo_ids(pand_id: str) -> list[str]:
    return [vbo(pand_id, v) for v in ECHTE_VBO]


def basis(pand_id: str) -> dict[str, str]:
    return {vbo(pand_id, v): s for v, s in ECHTE_VBO.items()}


class Server:
    """Een PDOK-nabootsing: per pand-ID een antwoord (bytes) of een HTTP-status (int)."""

    def __init__(self):
        self.antwoorden: dict[str, bytes | int] = {}
        self.verzoeken: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                server.verzoeken.append(q)
                literal = q.get("filter", "").split("<fes:Literal>")[1].split("</fes:Literal>")[0]
                antwoord = server.antwoorden.get(literal, ONBEKEND)
                if isinstance(antwoord, int):
                    self.send_response(antwoord)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if "startIndex" in q:  # een pagina van alleen de VBO-laag
                    antwoord = pagina(antwoord, int(q["startIndex"]), int(q["count"]))
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; subtype=gml/3.2")
                self.send_header("Content-Length", str(len(antwoord)))
                self.end_headers()
                self.wfile.write(antwoord)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/wfs"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def pagina(antwoord: bytes, start: int, count: int) -> bytes:
    """De VBO's uit een antwoord als één platte FeatureCollection, van start tot start + count."""
    wortel = ET.fromstring(antwoord)
    leden = [el for el in wortel.iter(f"{WFS}member") if el.find(f"{BAG}verblijfsobject") is not None]
    uit = ET.Element(f"{WFS}FeatureCollection")
    for el in leden[start:start + count]:
        uit.append(copy.deepcopy(el))
    return ET.tostring(uit, encoding="utf-8", xml_declaration=True)


class Basis(unittest.TestCase):
    PANDEN = ("0363100000000001", "0363100000000002")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="va75_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.server = Server()
        self.addCleanup(self.server.stop)
        sleep = mock.patch("ingest.time.sleep")  # de herhaling van ingest._wfs_get, zonder te wachten
        self.slaap = sleep.start()
        self.addCleanup(sleep.stop)
        self.output = self.tmp / "output"
        self.output.mkdir()
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.ins = {
            "wfs_url": self.server.url, "paginagrootte": 1000, "werklijst_map": self.output,
            "uitvoer_map": self.output / "controle", "resultaat": self.data / "controle_werklijst.json",
            "basis_map": self.data / "controle", "snapshot_map": self.data, "stop_na_mislukt": 10, "timeout_s": 5,
        }
        for pid in self.PANDEN:
            self.server.antwoorden[pid] = variant(pid)

    # -- hulp
    def werklijst(self, panden=None, maand="2026-11", pandstatus="Pand in gebruik", bron=SNAPSHOT) -> Path:
        pad = self.output / f"werklijst_nederland_{maand}.csv"
        with open(pad, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";", lineterminator="\r\n")
            w.writerow(["lead_id", "bag_pand_id", "pandstatus", "vbo_ids", "aantal_vbo", "leadscore", "bron"])
            for pid in panden or self.PANDEN:
                ids = vbo_ids(pid)
                w.writerow([f"LEV-NL-{pid}", pid, pandstatus, " | ".join(ids), len(ids), 20,
                            f"PDOK BAG GeoPackage ({bron})"])
        return pad

    def snapshot(self, panden=None, wijzig: dict | None = None) -> Path:
        """Een kleine landelijke snapshot met de kolomnamen van de GeoPackage (meta.kolommen)."""
        pad = self.data / SNAPSHOT
        with closing(sqlite3.connect(pad)) as conn:
            conn.execute("CREATE TABLE vbo (identificatie, status, pand_identificatie)")
            for pid in panden or self.PANDEN:
                for vid, status in basis(pid).items():
                    conn.execute("INSERT INTO vbo VALUES (?, ?, ?)", (vid, (wijzig or {}).get(vid, status), pid))
            conn.execute("INSERT INTO vbo VALUES ('9999010000000001', 'Verblijfsobject in gebruik', '9999')")
            conn.execute("CREATE TABLE meta (sleutel TEXT PRIMARY KEY, waarde TEXT NOT NULL)")
            conn.execute("INSERT INTO meta VALUES ('kolommen', ?)", (json.dumps(
                {"identificatie": "identificatie", "status": "status", "pandidentificatie": "pand_identificatie"}),))
            conn.commit()
        return pad

    def draai(self, nacht=NACHT_1, **kw):
        sessie = wc.TelSessie()
        sessie.trust_env = False  # geen proxy uit de omgeving voor 127.0.0.1
        with redirect_stdout(io.StringIO()):
            return wc.controleer({**self.ins, **kw}, session=sessie, nu=nacht)

    def rijen(self, maand="2026-11") -> list[dict]:
        with open(self.ins["uitvoer_map"] / f"wijzigingen_nederland_{maand}.csv", encoding="utf-8-sig",
                  newline="") as fh:
            return list(csv.DictReader(fh, delimiter=";"))


class GeenWijziging(Basis):
    def test_geen_verschil_geeft_een_leeg_bestand(self):
        self.werklijst()
        self.snapshot()
        r, code = self.draai()
        self.assertEqual(code, 0)
        self.assertEqual(self.rijen(), [])
        tekst = (self.ins["uitvoer_map"] / "wijzigingen_nederland_2026-11.csv").read_bytes()
        self.assertEqual(tekst, "﻿".encode() + b"bag_pand_id;soort;wijziging;vbo_id;waarde_werklijst;"
                         b"waarde_nu;eerst_gezien\n")
        self.assertEqual((r["panden"], r["gecontroleerd"], r["niet_gecontroleerd"]), (2, 2, 0))
        self.assertEqual(set(r["verschillen_per_soort"].values()), {0})
        self.assertTrue(r["vbo_status_vergeleken"])

    def test_een_verzoek_per_pand_met_ogc_filter_en_zonder_sleutel(self):
        self.werklijst()
        self.snapshot()
        r, _ = self.draai()
        self.assertEqual(r["verzoeken"], 2)
        self.assertEqual(len(self.server.verzoeken), 2)
        for q in self.server.verzoeken:
            self.assertNotIn("cql_filter", q)
            self.assertTrue(q["filter"].startswith("(<fes:Filter"))
            self.assertEqual(q["typeNames"], "bag:pand,bag:verblijfsobject")
            self.assertFalse({k.lower() for k in q} & {"key", "apikey", "api_key", "x-api-key"})

    def test_de_werklijst_en_de_snapshot_blijven_onaangeroerd(self):
        werklijst = self.werklijst()
        snap = self.snapshot()
        voor = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (werklijst, snap)}
        self.server.antwoorden[self.PANDEN[0]] = variant(self.PANDEN[0], pandstatus="Pand buiten gebruik")
        self.draai()
        self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in voor}, voor)
        geschreven = sorted(str(p.relative_to(self.tmp)).replace("\\", "/") for p in self.tmp.rglob("*") if p.is_file())
        self.assertEqual(geschreven, ["data/bag_nl_2026-11-01.sqlite", "data/controle/basis_nederland_2026-11.json",
                                      "data/controle_werklijst.json", "output/controle/wijzigingen_nederland_2026-11.csv",
                                      "output/werklijst_nederland_2026-11.csv"])


class ElkeSoort(Basis):
    PANDEN = tuple(f"03631000000000{n:02d}" for n in range(1, 9))

    def test_elke_soort_wijziging_heeft_een_vaste_soort(self):
        p = self.PANDEN
        self.werklijst()
        self.snapshot()
        eerste = vbo_ids(p[4])[0]
        nieuw = p[3][-4:] + "010000999999"
        self.server.antwoorden.update({
            p[0]: variant(p[0], pandstatus="Pand gesloopt"),
            p[1]: variant(p[1], pandstatus="Pand buiten gebruik"),
            p[2]: ONBEKEND,
            p[3]: variant(p[3], erbij={nieuw: "Verblijfsobject gevormd"}),
            p[4]: variant(p[4], weg=(eerste,)),
            p[5]: variant(p[5], vbo_status={vbo_ids(p[5])[1]: "Verblijfsobject buiten gebruik"}),
            p[6]: variant(p[6], pandstatus="Verbouwing pand"),
        })
        r, code = self.draai()
        self.assertEqual(code, 0)
        gevonden = {(x["bag_pand_id"], x["soort"], x["vbo_id"], x["waarde_werklijst"], x["waarde_nu"])
                    for x in self.rijen()}
        self.assertEqual(gevonden, {
            (p[0], "pand_gesloopt", "", "Pand in gebruik", "Pand gesloopt"),
            (p[1], "pand_buiten_gebruik", "", "Pand in gebruik", "Pand buiten gebruik"),
            (p[2], "pand_niet_gevonden", "", "Pand in gebruik", "niet in de BAG"),
            (p[3], "vbo_erbij", nieuw, "niet in de werklijst", "Verblijfsobject gevormd"),
            (p[4], "vbo_weg", eerste, "Verblijfsobject buiten gebruik", "niet in de BAG"),
            (p[5], "vbo_status", vbo_ids(p[5])[1], "Verblijfsobject in gebruik", "Verblijfsobject buiten gebruik"),
            (p[6], "pandstatus", "", "Pand in gebruik", "Verbouwing pand"),
        })
        self.assertTrue(all(x["eerst_gezien"] == "2026-11-17" for x in self.rijen()))
        self.assertTrue(all(x["wijziging"] for x in self.rijen()))
        self.assertEqual(r["verschillen_per_soort"], {s: 1 for s in wc.SOORTEN})
        self.assertEqual((r["gecontroleerd"], r["panden_met_verschil"]), (8, 7))
        uitkomst = json.loads(self.ins["resultaat"].read_text(encoding="utf-8"))
        self.assertEqual(uitkomst["verschillen_per_soort"]["pand_niet_gevonden"], 1)

    def test_pand_zonder_verblijfsobjecten_meer(self):
        self.server.antwoorden[ECHT_PAND] = ZONDER_VBO
        # ZONDER_VBO is het echte pand, maar de VBO-query vond niets: alle acht zijn weg.
        with open(self.output / "werklijst_nederland_2026-11.csv", "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("bag_pand_id;pandstatus;vbo_ids;bron\n")
            fh.write(f"{ECHT_PAND};Pand in gebruik;{' | '.join(ECHTE_VBO)};PDOK BAG GeoPackage ({SNAPSHOT})\n")
        r, _ = self.draai()
        self.assertEqual({x["soort"] for x in self.rijen()}, {"vbo_weg"})
        self.assertEqual(len(self.rijen()), 8)
        self.assertFalse(r["vbo_status_vergeleken"])  # geen snapshot in deze test
        self.assertIn("niet vergeleken", r["waarschuwing"])


class OverNachten(Basis):
    def test_eerst_gezien_blijft_staan_en_een_nieuw_verschil_krijgt_de_nieuwe_datum(self):
        a, b = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        self.server.antwoorden[b] = variant(b, weg=(vbo_ids(b)[0],))
        self.draai(NACHT_2)
        datums = {(x["bag_pand_id"], x["soort"]): x["eerst_gezien"] for x in self.rijen()}
        self.assertEqual(datums, {(a, "pand_buiten_gebruik"): "2026-11-17", (b, "vbo_weg"): "2026-11-18"})

    def test_een_teruggedraaid_verschil_verdwijnt(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        self.assertEqual(len(self.rijen()), 1)
        self.server.antwoorden[a] = variant(a)
        self.draai(NACHT_2)
        self.assertEqual(self.rijen(), [])

    def test_een_andere_waarde_nu_is_een_nieuw_verschil(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        self.server.antwoorden[a] = variant(a, pandstatus="Pand gesloopt")
        self.draai(NACHT_2)
        self.assertEqual([(x["soort"], x["eerst_gezien"]) for x in self.rijen()], [("pand_gesloopt", "2026-11-18")])

    def test_een_vbo_erbij_houdt_zijn_datum_als_zijn_status_verandert(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot()
        nieuw = a[-4:] + "010000999999"
        self.server.antwoorden[a] = variant(a, erbij={nieuw: "Verblijfsobject gevormd"})
        self.draai(NACHT_1)
        self.server.antwoorden[a] = variant(a, erbij={nieuw: "Verblijfsobject in gebruik"})
        self.draai(NACHT_2)
        self.assertEqual([(x["soort"], x["vbo_id"], x["waarde_nu"], x["eerst_gezien"]) for x in self.rijen()],
                         [("vbo_erbij", nieuw, "Verblijfsobject in gebruik", "2026-11-17")])

    def test_een_vbo_status_met_een_andere_waarde_is_een_nieuw_verschil(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot()
        vid = vbo_ids(a)[1]
        self.server.antwoorden[a] = variant(a, vbo_status={vid: "Verblijfsobject buiten gebruik"})
        self.draai(NACHT_1)
        self.server.antwoorden[a] = variant(a, vbo_status={vid: "Verbouwing verblijfsobject"})
        self.draai(NACHT_2)
        self.assertEqual([(x["soort"], x["waarde_nu"], x["eerst_gezien"]) for x in self.rijen()],
                         [("vbo_status", "Verbouwing verblijfsobject", "2026-11-18")])

    def test_gecontroleerd_om_staat_in_nederlandse_tijd(self):
        self.werklijst()
        r, _ = self.draai(datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(r["gecontroleerd_om"], "2026-11-17T03:00:00+01:00")
        r, _ = self.draai(datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc))
        self.assertEqual((r["gecontroleerd_om"], r["datum"]), ("2026-07-02T01:30:00+02:00", "2026-07-02"))

    def test_een_nieuwe_maand_begint_leeg(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        self.werklijst(maand="2026-12", bron="bag_nl_2026-12-01.sqlite")
        self.server.antwoorden[a] = variant(a)
        r, _ = self.draai(NACHT_2)
        self.assertEqual(r["maand"], "2026-12")
        self.assertEqual(self.rijen("2026-12"), [])
        self.assertEqual(len(self.rijen("2026-11")), 1)  # de vorige maand blijft zoals hij was

    def test_de_bewaarde_basis_maakt_de_snapshot_overbodig(self):
        a, _ = self.PANDEN
        self.werklijst()
        snap = self.snapshot()
        self.draai(NACHT_1)
        snap.unlink()
        self.server.antwoorden[a] = variant(a, vbo_status={vbo_ids(a)[1]: "Verblijfsobject buiten gebruik"})
        r, _ = self.draai(NACHT_2)
        self.assertTrue(r["vbo_status_vergeleken"])
        self.assertEqual([x["soort"] for x in self.rijen()], ["vbo_status"])

    def test_basis_komt_uit_de_snapshot_niet_uit_de_wfs(self):
        a, _ = self.PANDEN
        self.werklijst()
        self.snapshot(wijzig={vbo_ids(a)[0]: "Verblijfsobject in gebruik"})  # op 11-01 nog in gebruik
        self.draai()
        self.assertEqual([(x["vbo_id"], x["waarde_werklijst"], x["waarde_nu"]) for x in self.rijen()],
                         [(vbo_ids(a)[0], "Verblijfsobject in gebruik", "Verblijfsobject buiten gebruik")])


class Mislukt(Basis):
    def test_een_mislukt_pand_is_niet_gecontroleerd_en_de_rest_wordt_geschreven(self):
        a, b = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.server.antwoorden[b] = variant(b, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        self.server.antwoorden[b] = 503
        r, code = self.draai(NACHT_2)
        self.assertEqual(code, 0)
        self.assertEqual((r["gecontroleerd"], r["niet_gecontroleerd"], r["uitkomst"]), (1, 1, "deels"))
        soorten = {(x["bag_pand_id"], x["soort"]): x["eerst_gezien"] for x in self.rijen()}
        # b's verschil van nacht 1 blijft staan: het is niet gecontroleerd, dus niet weg
        self.assertEqual(soorten, {(a, "pand_buiten_gebruik"): "2026-11-17", (b, "pand_buiten_gebruik"): "2026-11-17",
                                   (b, "niet_gecontroleerd"): "2026-11-18"})
        self.assertEqual(self.slaap.call_count, 3)  # de bestaande herhaling: 4 pogingen, 3 keer wachten
        self.assertEqual(r["verzoeken"], 1 + 4)
        self.assertEqual(r["verschillen_per_soort"]["pand_buiten_gebruik"], 2)

    def test_een_genegeerd_filter_telt_als_mislukt(self):
        a, b = self.PANDEN
        self.werklijst()
        self.server.antwoorden[a] = variant(b)  # antwoord over een ander pand
        r, _ = self.draai()
        rij = [x for x in self.rijen() if x["bag_pand_id"] == a]
        self.assertEqual([x["soort"] for x in rij], ["niet_gecontroleerd"])
        self.assertIn("filter genegeerd", rij[0]["wijziging"])

    def test_geen_enkel_pand_gecontroleerd_schrijft_niets(self):
        a, b = self.PANDEN
        self.werklijst()
        self.snapshot()
        self.server.antwoorden[a] = variant(a, pandstatus="Pand buiten gebruik")
        self.draai(NACHT_1)
        bestand = self.ins["uitvoer_map"] / "wijzigingen_nederland_2026-11.csv"
        voor = (bestand.read_bytes(), self.ins["resultaat"].read_bytes())
        self.server.antwoorden.update({a: 503, b: 503})
        with self.assertRaises(wc.ControleFout) as fout:
            self.draai(NACHT_2)
        self.assertIn("Geen enkel pand kon worden gecontroleerd", str(fout.exception))
        self.assertEqual((bestand.read_bytes(), self.ins["resultaat"].read_bytes()), voor)
        self.assertEqual(sorted(p.name for p in self.ins["uitvoer_map"].iterdir()), [bestand.name])

    def test_na_te_veel_mislukte_panden_achter_elkaar_wordt_de_rest_niet_gevraagd(self):
        panden = tuple(f"03631000000001{n:02d}" for n in range(6))
        self.werklijst(panden=panden)
        for pid in panden:
            self.server.antwoorden[pid] = 503
        with self.assertRaises(wc.ControleFout):
            self.draai(stop_na_mislukt=2)
        self.assertEqual(len(self.server.verzoeken), 2 * 4)

    def test_main_geeft_exit_1_en_een_nederlandse_melding_als_pdok_plat_ligt(self):
        a, b = self.PANDEN
        werklijst = self.werklijst()
        self.server.antwoorden.update({a: 503, b: 503})
        cfg = {"bron": {"wfs_url": self.server.url, "paginagrootte": 1000},
               "nachtcontrole": {k: str(v) if isinstance(v, Path) else v for k, v in self.ins.items()
                                 if k in wc.SLEUTELS}}
        err = io.StringIO()
        with mock.patch.object(wc, "load_config", return_value=cfg), mock.patch.dict("os.environ", {"NO_PROXY": "*"}), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = wc.main(["--werklijst", str(werklijst)])
        self.assertEqual(code, 1)
        self.assertIn("FOUT: Geen enkel pand kon worden gecontroleerd", err.getvalue())
        self.assertIn("Niets geschreven", err.getvalue())
        self.assertFalse(self.ins["resultaat"].exists())
        self.assertFalse(self.ins["uitvoer_map"].exists())


class Schrijven(Basis):
    def test_een_bestand_dat_niet_vervangen_kan_worden_geeft_een_fout_en_geen_tmp(self):
        werklijst = self.werklijst()
        cfg = {"bron": {"wfs_url": self.server.url, "paginagrootte": 1000},
               "nachtcontrole": {k: str(v) if isinstance(v, Path) else v for k, v in self.ins.items()
                                 if k in wc.SLEUTELS}}
        err = io.StringIO()
        weigering = PermissionError(13, "Toegang geweigerd")
        with mock.patch.object(wc, "load_config", return_value=cfg), \
                mock.patch.object(wc.os, "replace", side_effect=weigering), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = wc.main(["--werklijst", str(werklijst)])
        self.assertEqual(code, 1)
        self.assertIn("FOUT: ", err.getvalue())
        self.assertIn("kon niet worden geschreven (Toegang geweigerd)", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual([p for p in self.tmp.rglob("*.tmp")], [])


class Pagineren(Basis):
    def test_een_afgekapt_antwoord_wordt_aangevuld_met_paginas(self):
        a, _ = self.PANDEN
        self.werklijst(panden=(a,))
        self.snapshot(panden=(a,))
        r, _ = self.draai(paginagrootte=3)
        # 1 verzoek voor het pand (afgekapt: 3 objecten), dan de 8 VBO's in pagina's van 3: 3 + 3 + 2
        self.assertEqual(r["verzoeken"], 1 + 3)
        self.assertEqual(self.rijen(), [])
        self.assertEqual([q.get("startIndex") for q in self.server.verzoeken], [None, "0", "3", "6"])


class Instellingen(unittest.TestCase):
    def test_config_yaml_heeft_alle_sleutels(self):
        ins = wc.instellingen(wc.load_config())
        self.assertEqual(ins["wfs_url"], "https://service.pdok.nl/lv/bag/wfs/v2_0")
        self.assertTrue(str(ins["uitvoer_map"]).replace("\\", "/").endswith("output/controle"))
        self.assertTrue(str(ins["resultaat"]).replace("\\", "/").startswith(str(wc.BASE).replace("\\", "/")))

    def test_een_ontbrekende_sleutel_wordt_genoemd(self):
        cfg = wc.load_config()
        del cfg["nachtcontrole"]["stop_na_mislukt"]
        with self.assertRaises(wc.ControleFout) as fout:
            wc.instellingen(cfg)
        self.assertIn("nachtcontrole.stop_na_mislukt", str(fout.exception))

    def test_nan_als_getal_wordt_geweigerd(self):
        cfg = wc.load_config()
        cfg["nachtcontrole"]["timeout_s"] = float("nan")
        with self.assertRaises(wc.ControleFout):
            wc.instellingen(cfg)

    def test_de_nieuwste_werklijst_wordt_gekozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            for naam in ("werklijst_nederland_2026-11.csv", "werklijst_nederland_2026-12.csv",
                         "werklijst_delft_2027-01.csv", "werklijst_nederland_2026-12_kopie.csv"):
                (Path(tmp) / naam).write_text("x", encoding="utf-8")
            pad, maand = wc.nieuwste_werklijst(Path(tmp))
            self.assertEqual((pad.name, maand), ("werklijst_nederland_2026-12.csv", "2026-12"))

    def test_de_echte_werklijst_is_leesbaar_en_noemt_zijn_snapshot(self):
        pad, maand = wc.nieuwste_werklijst(PROJECT / "output")
        panden, snapshot = wc.lees_werklijst(pad)
        self.assertGreaterEqual(len(panden), 1)
        self.assertLessEqual(len(panden), wc.load_config()["drempels"]["werklijst_max"])
        self.assertRegex(snapshot, r"^bag_nl_\d{4}-\d{2}-\d{2}(_\d+)?\.sqlite$")
        self.assertTrue(all(p.vbo_ids and p.pandstatus for p in panden))


if __name__ == "__main__":
    unittest.main()
