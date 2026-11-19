"""
VA-58: het EP-online-maandbestand ophalen (sleutel alleen uit EP_ONLINE_API_KEY), de kolommen
controleren (fail closed) en per snapshot aan de panden koppelen. Alleen standaardbibliotheek; een
nep-EP-online op localhost, een nepsleutel, en een handgemaakt bestand in het gedocumenteerde formaat
(RVO-handleiding januari 2025, bijlage 2). Schrijft alleen in tijdelijke mappen.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import energielabels  # noqa: E402
import ep_online  # noqa: E402
import selectie  # noqa: E402
import snapshots  # noqa: E402

NEPSLEUTEL = "NEPSLEUTEL-va58-QUQ3ODdFQTk2N1zz"  # nooit een echte sleutel
TOKEN = "tijdelijk-token-9f8e7d"
ZIPNAAM = "v20261101_v4_csv.zip"
VBO_DELFT = PROJECT / "data" / "vbo_delft.json"

# Pand 1: één VBO met label C. Pand 2: drie VBO's met F, B en een tweede registratie die B naar A
# brengt (nieuwer), plus één zonder label. Pand 3: geen enkel label. Pand 4: alleen een EI-certificaat
# zonder klasse. Plus een misvormde regel, een regel met een kapotte klasse, en een ligplaats.
P1, P2, P3, P4 = "0503100000000001", "0503100000000002", "0503100000000003", "0503100000000004"
REGELS = [
    {"vbo": "0503010000000011", "pand": P1, "klasse": "C", "datum": "20190115"},
    {"vbo": "0503010000000021", "pand": P2, "klasse": "F", "datum": "20200301"},
    {"vbo": "0503010000000022", "pand": P2, "klasse": "B", "datum": "20180610"},
    {"vbo": "0503010000000022", "pand": P2, "klasse": "A", "datum": "20230920"},  # nieuwer: telt
    {"vbo": "0503010000000041", "pand": P4, "klasse": "", "datum": "20220101"},
    {"vbo": "", "pand": "", "klasse": "D", "datum": "20210101", "ligplaats": "0503020000000001"},
    {"vbo": "0503010000000012", "pand": P1, "klasse": "Q", "datum": "20210101"},  # onbekende klasse
]


def csv_tekst(kolommen=ep_online.KOLOMMEN, regels=REGELS, extra: str = "", voorregel: str = "") -> str:
    def regel(r):
        w = {k: "" for k in kolommen}
        w.update({"BAGVerblijfsobjectID": r["vbo"], "BAGPandIDs": r["pand"],
                  "Energieklasse": r["klasse"], "Registratiedatum": r["datum"],
                  "BAGLigplaatsID": r.get("ligplaats", ""), "Gebouwklasse": "W"})
        return ";".join(w[k] for k in kolommen if k in w)
    rijen = ([voorregel] if voorregel else []) + [";".join(kolommen)] + [regel(r) for r in regels]
    return "\n".join(rijen) + "\n" + extra


def maak_zip(pad: Path, tekst: str) -> Path:
    with zipfile.ZipFile(pad, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pad.name.replace(".zip", ".csv"), tekst.encode("utf-8"))
    return pad


def rij(ident, pand):
    return {"identificatie": ident, "rdf_seealso": "", "oppervlakte": 120, "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": "woonfunctie", "openbare_ruimte": "Oude Delft", "huisnummer": 1, "huisletter": "",
            "toevoeging": "", "postcode": "2611BA", "woonplaats": "Delft", "bouwjaar": 1900,
            "pandidentificatie": pand, "pandstatus": "Pand in gebruik", "_x": 84000.0, "_y": 447000.0}


SNAPSHOTRIJEN = [rij("0503010000000011", P1), rij("0503010000000021", P2), rij("0503010000000022", P2),
                 rij("0503010000000023", P2), rij("0503010000000031", P3), rij("0503010000000041", P4)]


def alle_bestanden(*mappen: Path) -> list[Path]:
    return [p for m in mappen for p in Path(m).rglob("*") if p.is_file()]


def scan(sleutel: str, mappen: list[Path], *teksten: str) -> list[str]:
    """Waar de sleutel staat: bestandsnamen en inhoud, en de gegeven uitvoer."""
    raak = [str(p) for p in alle_bestanden(*mappen)
            if sleutel.encode() in p.read_bytes() or sleutel in str(p)]
    return raak + [f"uitvoer {i}" for i, t in enumerate(teksten) if sleutel in t]


class KolomControle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.map = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gedocumenteerd_formaat_slaagt(self):
        r = ep_online.controleer_zip(maak_zip(self.map / ZIPNAAM, csv_tekst()))
        self.assertEqual(r["kolommen"], len(ep_online.KOLOMMEN))
        self.assertEqual(r["scheiding"], ";")

    def test_regel_voor_de_kop_wordt_bewaard(self):
        r = ep_online.controleer_zip(maak_zip(self.map / ZIPNAAM, csv_tekst(voorregel="Mutatievolgnummer;123")))
        self.assertEqual(r["kopregel_vooraf"], "Mutatievolgnummer;123")

    def test_twee_regels_voor_de_kop_zoals_het_echte_bestand(self):
        # Het echte totaalbestand van 2026-11-01 (gelezen 2026-11-19) begint met deze twee regels.
        voor = "PublicatieDatum;01-11-2026\nLaatstVerwerkteMutatievolgnummer;20248879"
        r = ep_online.controleer_zip(maak_zip(self.map / ZIPNAAM, csv_tekst(voorregel=voor)))
        self.assertEqual(r["kolommen"], len(ep_online.KOLOMMEN))
        self.assertEqual(r["kopregel_vooraf"],
                         "PublicatieDatum;01-11-2026 | LaatstVerwerkteMutatievolgnummer;20248879")

    def test_ontbrekende_en_onbekende_kolom_stoppen(self):
        kolommen = [k for k in ep_online.KOLOMMEN if k != "Energieklasse"] + ["Pand_nieuw_veld"]
        with self.assertRaises(ep_online.EpFout) as ctx:
            ep_online.controleer_zip(maak_zip(self.map / ZIPNAAM, csv_tekst(kolommen)))
        melding = str(ctx.exception)
        self.assertIn("ontbrekende kolommen: Energieklasse", melding)
        self.assertIn("onbekende kolommen: Pand_nieuw_veld", melding)
        self.assertIn("niets gepubliceerd", melding)

    def test_afwijking_publiceert_geen_labels(self):
        kolommen = list(ep_online.KOLOMMEN[:-1])  # de laatste ontbreekt
        z = maak_zip(self.map / ZIPNAAM, csv_tekst(kolommen))
        snap = Snapshots.json_snapshot(self.map)
        with self.assertRaises(ep_online.EpFout):
            ep_online.koppel(z, snap, self.map / "labels")
        self.assertEqual(alle_bestanden(self.map / "labels") if (self.map / "labels").exists() else [], [])

    def test_hoofdletters_en_spaties_tellen_niet(self):
        kolommen = [k.upper() if k.startswith("Energie") else k for k in ep_online.KOLOMMEN]
        kolommen[-1] = "  BerekendeEnergieverbruik "
        ep_online.controleer_zip(maak_zip(self.map / ZIPNAAM, csv_tekst(kolommen)))

    def test_zip_met_twee_csvs_stopt(self):
        pad = self.map / ZIPNAAM
        with zipfile.ZipFile(pad, "w") as zf:
            zf.writestr("a.csv", csv_tekst())
            zf.writestr("b.csv", csv_tekst())
        with self.assertRaisesRegex(ep_online.EpFout, "precies één CSV"):
            ep_online.controleer_zip(pad)


class Snapshots(unittest.TestCase):
    @staticmethod
    def json_snapshot(map_: Path, datum="2026-11-01") -> snapshots.Snapshot:
        pad = map_ / f"vbo_delft_{datum}.json"
        pad.write_text(json.dumps(SNAPSHOTRIJEN), encoding="utf-8")
        return snapshots.Snapshot("Delft", pad, datum, 1, "meta", "json")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.map = Path(self.tmp.name)
        self.zip = maak_zip(self.map / ZIPNAAM, csv_tekst(extra="te;weinig;velden\n"))
        self.labels = self.map / "labels"

    def tearDown(self):
        self.tmp.cleanup()

    def lees(self, snap) -> dict:
        with contextlib.closing(sqlite3.connect(energielabels.bestand_voor(snap.pad, self.labels))) as c:
            return {r[0]: (r[1], r[2]) for r in c.execute("SELECT * FROM pand")}

    def controleer(self, snap):
        m = ep_online.koppel(self.zip, snap, self.labels)
        # crit. 6: één label; meerdere VBO's met verschillende labels (beste, nieuwste registratie); geen label.
        self.assertEqual(self.lees(snap), {P1: ("C", "2019-01-15"), P2: ("A", "2023-09-20")})
        self.assertEqual((m["panden"], m["panden_met_label"]), (4, 2))
        # Misvormd: te weinig velden en een onbekende klasse; geteld en gemeld, geen crash.
        self.assertEqual(m["misvormd"], 2)
        self.assertEqual((m["zonder_vbo"], m["zonder_klasse"]), (1, 1))
        self.assertTrue(any("onbekende energieklasse 'Q'" in v for v in m["voorbeelden"]))
        tekst = ep_online.rapport(m)
        self.assertIn("2 van 4 panden hebben een label (50,0%)", tekst)
        self.assertIn("Kolomcontrole geslaagd", tekst)
        meta = energielabels.meta(energielabels.bestand_voor(snap.pad, self.labels))
        self.assertEqual((meta["kolomcontrole"], meta["bronbestand"], meta["snapshot"]),
                         ("geslaagd", ZIPNAAM, snap.pad.name))
        # Niets achtergelaten behalve het labelbestand.
        self.assertEqual([p.name for p in alle_bestanden(self.labels)], [f"energielabel_{snap.pad.name}.sqlite"])

    def test_json_snapshot(self):
        self.controleer(self.json_snapshot(self.map))

    def test_sqlite_snapshot(self):
        snap = snapshots.schrijf_sqlite("Delft", "delft", iter(SNAPSHOTRIJEN), self.map, datetime(2026, 11, 1, 12))
        self.controleer(snap)

    def test_per_snapshot_en_nooit_overschreven(self):
        # crit. 4: een oudere maand houdt zijn labels; opnieuw koppelen overschrijft niets.
        oud = self.json_snapshot(self.map, "2026-10-01")
        ep_online.koppel(self.zip, oud, self.labels)
        voor = energielabels.bestand_voor(oud.pad, self.labels).read_bytes()
        with self.assertRaisesRegex(ep_online.EpFout, "niet overschreven"):
            ep_online.koppel(self.zip, oud, self.labels)
        self.assertEqual(energielabels.bestand_voor(oud.pad, self.labels).read_bytes(), voor)
        nieuw = self.json_snapshot(self.map, "2026-11-01")
        ep_online.koppel(self.zip, nieuw, self.labels)
        self.assertEqual(len(alle_bestanden(self.labels)), 2)


def cfg_met(actief: bool, telt_mee: bool, map_: Path) -> dict:
    cfg = selectie.load_config()
    cfg["bronnen"]["energielabel"].update(actief=actief, telt_mee=telt_mee, map=str(map_))
    return cfg


class InHetRecord(unittest.TestCase):
    """crit. 5 en 8: het pandrecord draagt het label; met telt_mee uit verschuift geen score."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.map = Path(self.tmp.name)
        self.snap = Snapshots.json_snapshot(self.map)
        ep_online.koppel(maak_zip(self.map / ZIPNAAM, csv_tekst()), self.snap, self.map / "labels")

    def tearDown(self):
        self.tmp.cleanup()

    def panden(self, actief, telt_mee=False):
        uit = selectie.verwerk("Delft", cfg_met(actief, telt_mee, self.map / "labels"), gekozen=[self.snap])
        return {p["bag_pand_id"]: p for p in uit}

    def test_label_en_datum_in_het_record(self):
        p = self.panden(True)
        self.assertEqual((p[P1]["energielabel"], p[P1]["energielabel_registratiedatum"]), ("C", "2019-01-15"))
        self.assertEqual((p[P3]["energielabel"], p[P3]["energielabel_registratiedatum"]), (None, None))

    def test_beide_routes_gelijk(self):
        sq = snapshots.schrijf_sqlite("Delft", "delft", iter(SNAPSHOTRIJEN), self.map, datetime(2026, 11, 1, 12))
        ep_online.koppel(self.map / ZIPNAAM, sq, self.map / "labels")
        cfg = cfg_met(True, False, self.map / "labels")
        via_json = selectie.verwerk("Delft", cfg, gekozen=[self.snap])
        via_stroom = list(selectie.stroom_panden([sq], cfg, "Delft"))
        for a, b in zip(via_json, via_stroom):
            self.assertEqual((a["energielabel"], a["energielabel_registratiedatum"]),
                             (b["energielabel"], b["energielabel_registratiedatum"]))

    def test_uit_geen_velden(self):
        p = self.panden(False)
        self.assertNotIn("energielabel", p[P1])

    def test_telt_mee_uit_verschuift_geen_score(self):
        uit, aan = self.panden(False), self.panden(True, telt_mee=False)
        self.assertEqual({k: (v["leadscore"], v["score100"]) for k, v in uit.items()},
                         {k: (v["leadscore"], v["score100"]) for k, v in aan.items()})
        regel = next(r for r in aan[P3]["score_opbouw"] if r["label"] == "Slecht of ontbrekend energielabel")
        self.assertEqual((regel["status"], regel["detail"]), ("inactief", "energielabel geen; telt nog niet mee in de score"))

    def test_ontbrekend_labelbestand_stopt_de_run(self):
        # crit. 1: zonder labels doorgaan alleen als het signaal uit staat.
        with self.assertRaisesRegex(snapshots.SnapshotFout, "ontbreekt"):
            selectie.verwerk("Delft", cfg_met(True, False, self.map / "leeg"), gekozen=[self.snap])


@unittest.skipUnless(VBO_DELFT.is_file(), f"{VBO_DELFT} ontbreekt")
class DelftVerschuiftNiet(unittest.TestCase):
    """crit. 8 op de augustus-data: labels gekoppeld, telt_mee uit -> elke Delftse score gelijk."""

    def test_delft(self):
        snap = snapshots.kies("Delft", "delft", selectie.DATA, selectie.load_config(), "vbo_delft.json")
        rijen = json.loads(VBO_DELFT.read_text(encoding="utf-8"))
        klassen = energielabels.LABELS
        regels = [{"vbo": r["identificatie"], "pand": r["pandidentificatie"], "klasse": klassen[i % len(klassen)],
                   "datum": "20200101"} for i, r in enumerate(rijen[::3]) if r.get("identificatie")]
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            m = ep_online.koppel(maak_zip(map_ / ZIPNAAM, csv_tekst(regels=regels)), snap, map_)
            self.assertGreater(m["panden_met_label"], 5_000)
            uit = selectie.verwerk("Delft", cfg_met(False, False, map_), gekozen=[snap])
            aan = selectie.verwerk("Delft", cfg_met(True, False, map_), gekozen=[snap])
        self.assertEqual([(p["bag_pand_id"], p["leadscore"]) for p in uit], [(p["bag_pand_id"], p["leadscore"]) for p in aan])
        self.assertTrue(any(p.get("energielabel") for p in aan))


class NepEpOnline(BaseHTTPRequestHandler):
    """DownloadInfo met sleutel, en een download met token. Onthoudt de headers van elk verzoek."""
    verzoeken: list = []
    zip_bytes = b""
    info_status = 200

    def log_message(self, *a):
        pass

    def do_GET(self):
        NepEpOnline.verzoeken.append((self.path, dict(self.headers)))
        if self.path.startswith("/api/v5/Mutatiebestand/DownloadInfo"):
            if self.headers.get("Authorization") != NEPSLEUTEL or NepEpOnline.info_status != 200:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"bestandsnaam": ZIPNAAM, "geldigTotEnMet": "2026-11-17T12:00:00+01:00",
                               "downloadUrl": f"http://127.0.0.1:{self.server.server_port}/Download?token={TOKEN}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
        elif self.path == f"/Download?token={TOKEN}":
            self.send_response(200)
            self.send_header("Content-Length", str(len(NepEpOnline.zip_bytes)))
            self.end_headers()
            self.wfile.write(NepEpOnline.zip_bytes)
        else:
            self.send_response(404)
            self.end_headers()


class Ophalen(unittest.TestCase):
    """crit. 1 en 2: de sleutel uit de omgeving, nergens geschreven; compleet of niet."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.map = Path(self.tmp.name) / "ep"
        bron = maak_zip(Path(self.tmp.name) / "bron.zip", csv_tekst())
        NepEpOnline.zip_bytes, NepEpOnline.verzoeken, NepEpOnline.info_status = bron.read_bytes(), [], 200
        bron.unlink()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), NepEpOnline)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = f"http://127.0.0.1:{self.server.server_port}/api/v5"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def draai(self, sleutel: str | None) -> tuple[int, str, str]:
        cfg = selectie.load_config()
        cfg["bronnen"]["energielabel"]["api_url"] = self.api
        omgeving = {k: v for k, v in os.environ.items() if k != ep_online.SLEUTEL_VAR}
        if sleutel is not None:
            omgeving[ep_online.SLEUTEL_VAR] = sleutel
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, omgeving, clear=True), mock.patch.object(ep_online, "load_config", lambda: cfg), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ep_online.main(["ophalen", "--map", str(self.map)])
        return code, out.getvalue(), err.getvalue()

    def test_met_sleutel_compleet_en_sleutel_nergens(self):
        code, out, err = self.draai(NEPSLEUTEL)
        self.assertEqual(code, 0, err)
        self.assertIn("kolomcontrole geslaagd", out)
        self.assertEqual([p.name for p in alle_bestanden(self.map)], [ZIPNAAM])
        info, download = NepEpOnline.verzoeken
        self.assertEqual(info[1].get("Authorization"), NEPSLEUTEL)
        self.assertNotIn("Authorization", download[1])  # de download krijgt de sleutel niet
        self.assertEqual(scan(NEPSLEUTEL, [Path(self.tmp.name)], out, err), [])
        self.assertEqual(scan(TOKEN, [Path(self.tmp.name)], out, err), [])  # ook de downloadlink niet
        # Een tweede keer: al binnen, niets gedownload.
        code, out, _ = self.draai(NEPSLEUTEL)
        self.assertEqual(code, 0)
        self.assertIn("niets gedownload", out)
        self.assertEqual(len(NepEpOnline.verzoeken), 3)

    def test_zonder_sleutel_stopt(self):
        for sleutel in (None, "  "):
            code, out, err = self.draai(sleutel)
            self.assertEqual(code, 1)
            self.assertIn("EP_ONLINE_API_KEY ontbreekt", err)
            self.assertFalse(self.map.exists())
        self.assertEqual(NepEpOnline.verzoeken, [])

    def test_geweigerde_sleutel_lekt_niet(self):
        NepEpOnline.info_status = 401
        code, out, err = self.draai(NEPSLEUTEL)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 401", err)
        self.assertEqual(scan(NEPSLEUTEL, [Path(self.tmp.name)], out, err), [])

    def test_afwijkende_kolommen_publiceren_niets(self):
        z = maak_zip(Path(self.tmp.name) / "x.zip", csv_tekst(list(ep_online.KOLOMMEN) + ["Pand_extra"]))
        NepEpOnline.zip_bytes = z.read_bytes()
        z.unlink()
        code, out, err = self.draai(NEPSLEUTEL)
        self.assertEqual(code, 1)
        self.assertIn("onbekende kolommen: Pand_extra", err)
        self.assertEqual(alle_bestanden(self.map), [])  # geen zip, geen .deel
        self.assertEqual(scan(NEPSLEUTEL, [Path(self.tmp.name)], out, err), [])
        self.assertEqual(scan(TOKEN, [Path(self.tmp.name)], out, err), [])


class Datums(unittest.TestCase):
    def test_formaten(self):
        for tekst, iso in (("20210304", "2021-03-04"), ("2021-03-04", "2021-03-04"),
                           ("2021-03-04T00:00:00", "2021-03-04"), ("4-3-2021", "2021-03-04"),
                           ("20211304", None), ("gisteren", None)):
            self.assertEqual(ep_online.lees_datum(tekst), iso, tekst)


if __name__ == "__main__":
    unittest.main()
