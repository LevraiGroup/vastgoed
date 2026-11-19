"""
VA-6: het dedup-register. Een pand dat in een werklijst is geleverd, komt nooit in een latere.

De eenheidstests werken op nep-panden en een register in een tijdelijke map. De Delft-tests
lezen de augustus-snapshot data/vbo_delft.json (overgeslagen als die ontbreekt) en draaien
run_proef.main() met output/, data/ en het register omgeleid naar een tijdelijke map; de echte
output/ en het echte register veranderen niet (laatste controle in elke Delft-test).

Alleen standaardbibliotheek plus de eigen modules van het project.
"""
from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import register  # noqa: E402
import selectie  # noqa: E402

def delft_basis(cfg: dict) -> dict:
    """De Delft-basis (VA-2) is de run zonder energielabels (VA-101 crit. 2): een Delft-snapshot heeft geen labelbestand."""
    cfg["bronnen"]["energielabel"]["actief"] = False
    cfg["bronnen"]["energielabel"]["telt_mee"] = False
    return cfg


VBO_DELFT = PROJECT / "data" / "vbo_delft.json"
ECHT_REGISTER = PROJECT / "register" / "geleverde_panden.csv"


def pid(i: int, gemeente: str = "0503") -> str:
    return f"{gemeente}100000{i:06d}"


def pand(i: int, score: int, gemeente: str = "0503") -> dict:
    return {"bag_pand_id": pid(i, gemeente), "leadscore": score, "categorieen": ["A"], "uitgesloten": False}


def cfg_met(**drempels) -> dict:
    cfg = copy.deepcopy(delft_basis(selectie.load_config()))
    cfg["drempels"].update(drempels)
    return cfg


def lees_csv(pad: Path) -> list[dict]:
    with open(pad, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def ids(lijst) -> list[str]:
    return [p["bag_pand_id"] for p in lijst]


class TijdelijkeMap(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.map = Path(tmp.name)
        self.pad = self.map / "register" / "geleverde_panden.csv"


class TestRegisterBestand(TijdelijkeMap):

    def test_zonder_bestand_is_het_register_leeg(self):
        reg = register.Register(self.pad)
        self.assertEqual((reg.regels, reg.alle()), ([], set()))
        self.assertFalse(self.pad.exists())

    def test_leg_vast_schrijft_id_maand_en_werklijst_buiten_output(self):
        # crit. 1: per pand bag_pand_id, maand en de bestandsnaam van de werklijst.
        reg = register.Register(self.pad)
        self.assertEqual(reg.leg_vast("werklijst_delft_2026-08.csv", "2026-08", [pid(1), pid(2)]), 2)
        ruw = self.pad.read_bytes()
        self.assertTrue(ruw.startswith(b"\xef\xbb\xbf"), "geen UTF-8 BOM, zoals de andere CSV's")
        self.assertEqual(ruw.decode("utf-8-sig").splitlines(),
                         ["bag_pand_id;maand;werklijst",
                          f"{pid(1)};2026-08;werklijst_delft_2026-08.csv",
                          f"{pid(2)};2026-08;werklijst_delft_2026-08.csv"])
        self.assertEqual(register.Register(self.pad).regels, reg.regels)

    def test_het_echte_register_ligt_buiten_output_en_data(self):
        # crit. 1 en de VA-8-noot: opnieuw maken van output/ of data/panden_* wist het nooit.
        rel = register.STANDAARD.relative_to(register.BASE)
        self.assertNotIn(rel.parts[0], ("output", "data"))
        self.assertEqual(register.pad(self.map), self.map / rel)

    def test_dezelfde_werklijst_twee_keer_registreert_niets_dubbel(self):
        # crit. 3
        reg = register.Register(self.pad)
        reg.leg_vast("werklijst_delft_2026-08.csv", "2026-08", [pid(1), pid(2)])
        voor = self.pad.read_bytes()
        reg2 = register.Register(self.pad)
        self.assertEqual(reg2.leg_vast("werklijst_delft_2026-08.csv", "2026-08", [pid(1), pid(2)]), 0)
        self.assertEqual(self.pad.read_bytes(), voor)

    def test_een_andere_lijst_voor_een_geleverde_werklijst_stopt_en_schrijft_niets(self):
        # crit. 8
        reg = register.Register(self.pad)
        reg.leg_vast("werklijst_delft_2026-08.csv", "2026-08", [pid(1), pid(2)])
        voor = self.pad.read_bytes()
        for anders in ([pid(1)], [pid(1), pid(3)], [pid(2), pid(1)]):
            with self.assertRaises(register.RegisterFout) as fout:
                register.Register(self.pad).leg_vast("werklijst_delft_2026-08.csv", "2026-08", anders)
            tekst = str(fout.exception)
            self.assertIn("2026-08", tekst)
            self.assertIn("werklijst_delft_2026-08.csv", tekst)
            self.assertEqual(self.pad.read_bytes(), voor)

    def test_elders_is_alles_behalve_deze_werklijst(self):
        reg = register.Register(self.pad)
        reg.leg_vast("werklijst_delft_2026-08.csv", "2026-08", [pid(1)])
        reg.leg_vast("werklijst_nederland_2026-11.csv", "2026-11", [pid(2, "0363")])
        self.assertEqual(reg.elders("werklijst_delft_2026-08.csv"), {pid(2, "0363")})
        self.assertEqual(reg.elders("werklijst_delft_2026-09.csv"), {pid(1), pid(2, "0363")})

    def test_met_de_hand_bewerkt(self):
        # crit. 6: een regel weghalen maakt de levering ongedaan; een lege regel, een extra kolom
        # en een ontbrekend regeleinde aan het eind mogen; toevoegen houdt de handregels.
        self.pad.parent.mkdir(parents=True)
        self.pad.write_bytes(("﻿bag_pand_id;maand;werklijst;opmerking\r\n"
                              f"{pid(1)};2026-08;werklijst_delft_2026-08.csv;\r\n"
                              "\r\n"
                              f"{pid(3)};2026-08;werklijst_delft_2026-08.csv;per ongeluk").encode("utf-8"))
        reg = register.Register(self.pad)
        self.assertEqual(reg.alle(), {pid(1), pid(3)})
        reg.leg_vast("werklijst_delft_2026-09.csv", "2026-09", [pid(4)])
        ruw = self.pad.read_bytes()
        self.assertIn(b"per ongeluk\r\n" + pid(4).encode() + b";2026-09;", ruw)
        self.assertEqual(ruw.count(b"\xef\xbb\xbf"), 1)
        self.assertEqual(register.Register(self.pad).alle(), {pid(1), pid(3), pid(4)})

    def test_een_kapotte_regel_stopt_met_het_regelnummer(self):
        # Fail closed: een register dat niet te lezen is, wordt nooit stil een leeg register.
        self.pad.parent.mkdir(parents=True)
        for inhoud, verwacht in (
            ("bag_pand_id;maand;werklijst\n503100000000001;2026-08;w.csv\n", "regel 2"),  # Excel: 0 weg
            ("bag_pand_id;maand;werklijst\n5,031E+14;2026-08;w.csv\n", "Kladblok"),
            (f"bag_pand_id;maand;werklijst\n{pid(1)};augustus;w.csv\n", "JJJJ-MM"),
            (f"bag_pand_id;maand;werklijst\n{pid(1)};2026-08;w.csv\n{pid(2)};2026-08;\n", "regel 3"),
            (f"pand;maand;werklijst\n{pid(1)};2026-08;w.csv\n", "eerste regel"),
            (f"bag_pand_id,maand,werklijst\n{pid(1)},2026-08,w.csv\n", "eerste regel"),
        ):
            self.pad.write_text(inhoud, encoding="utf-8")
            with self.assertRaises(register.RegisterFout, msg=inhoud) as fout:
                register.Register(self.pad)
            self.assertIn(verwacht, str(fout.exception))

    def test_omgevingsvariabele_wijst_een_ander_register_aan(self):
        with mock.patch.dict("os.environ", {register.VAR_REGISTER: str(self.pad)}):
            self.assertEqual(register.pad(), self.pad)
            self.assertEqual(register.pad(PROJECT), self.pad)


class TestWerklijstZonderGeleverd(unittest.TestCase):

    def test_geleverde_panden_doen_niet_mee_en_de_volgende_vullen_aan(self):
        # crit. 2
        cfg = cfg_met(werklijst_max=3, score_min_voor_werklijst=8)
        panden = [pand(i, 20 - i) for i in range(1, 8)]
        eerst, n = selectie.werklijst(panden, cfg, "2026-08")
        self.assertEqual((ids(eerst), n), ([pid(1), pid(2), pid(3)], 7))
        daarna, n = selectie.werklijst(panden, cfg, "2026-09", set(ids(eerst)))
        self.assertEqual((ids(daarna), n), ([pid(4), pid(5), pid(6)], 4))

    def test_zonder_geleverd_verandert_er_niets(self):
        cfg = cfg_met(werklijst_max=3)
        panden = [pand(i, 10 + i % 3) for i in range(20)]
        self.assertEqual(selectie.werklijst(panden, cfg, "2026-08"),
                         selectie.werklijst(panden, cfg, "2026-08", frozenset()))


class TestLandelijk(TijdelijkeMap):
    """crit. 7 en 8 op de landelijke route: draai() op een nagemaakte stroom."""

    def setUp(self):
        super().setUp()
        import cbs_gemeenten
        import nederland
        import run_proef
        self.nederland, self.run_proef = nederland, run_proef
        (self.map / "uit").mkdir()
        (self.map / "data").mkdir()
        snap = types.SimpleNamespace(pad=self.map / "snap.sqlite", ophaaldatum="2026-11-01", landelijk=True,
                                     omschrijving=lambda: "stub")
        groot = [g["gemeentecode"] for g in cbs_gemeenten.lees() if g["rang"] <= 25]
        # Elke grote gemeente een pand met score 9, en Delft (0503, niet bij de 25) tien met score 9-18.
        self.panden = [dict(pand(1, 9, code), gemeentecode=code) for code in groot]
        self.panden += [dict(pand(i, 8 + i, "0503"), gemeentecode="0503") for i in range(1, 11)]
        for p in self.panden:
            p.update({"aantal_vbo": 1, "uitsluitredenen": [], "hoofdadres": "", "woonplaats": "",
                      "opp_per_functie": {}, "aantal_per_functie": {}})
        mock.patch.object(nederland, "nieuwste_snapshot", lambda cfg, keuze: snap).start()
        mock.patch.object(selectie, "stroom_panden",
                          lambda *a, **k: (copy.deepcopy(p) for p in self.panden)).start()
        self.addCleanup(mock.patch.stopall)
        self.cfg = cfg_met(werklijst_max=6, werklijst_min=1, werklijst_aandeel_overig=0.5)
        self.cfg["doelgebied"]["nederland"] = True

    def draai(self, cfg=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.nederland.draai(cfg or self.cfg, None, self.run_proef.KOLOMMEN, self.run_proef.csv_rij,
                                        self.map / "uit", self.map / "data", register_bestand=self.pad)

    def werklijst_ids(self) -> list[str]:
        return [r["bag_pand_id"] for r in lees_csv(self.map / "uit" / "werklijst_nederland_2026-11.csv")]

    def test_een_in_delft_geleverd_pand_komt_niet_in_de_landelijke_werklijst(self):
        self.assertEqual(self.draai(), 0)
        zonder = self.werklijst_ids()
        totalen = json.loads((self.map / "data" / "panden_nederland.json").read_text(encoding="utf-8"))["totalen"]
        delft_in_lijst = [i for i in zonder if i.startswith("0503")]
        self.assertEqual(len(delft_in_lijst), 3)
        self.pad.unlink()
        register.Register(self.pad).leg_vast("werklijst_delft_2026-08.csv", "2026-08", delft_in_lijst[:2])
        self.assertEqual(self.draai(), 0)
        met = self.werklijst_ids()
        self.assertEqual(len(met), 6)
        self.assertFalse(set(delft_in_lijst[:2]) & set(met))
        self.assertEqual(len([i for i in met if i.startswith("0503")]), 3)  # aangevuld met de volgende
        # De landelijke tellingen op het dashboard blijven alle geschikte panden tellen.
        na = json.loads((self.map / "data" / "panden_nederland.json").read_text(encoding="utf-8"))["totalen"]
        self.assertEqual({k: na[k] for k in ("geschikt", "geschikt_25", "geschikt_overig")},
                         {k: totalen[k] for k in ("geschikt", "geschikt_25", "geschikt_overig")})
        # crit. 4 (landelijk): in de mastervoorraad zegt eerder_geselecteerd 'ja' bij precies die twee.
        master = lees_csv(self.map / "uit" / "mastervoorraad_nederland.csv")
        self.assertEqual({r["bag_pand_id"] for r in master if r["eerder_geselecteerd"] == "ja"},
                         set(delft_in_lijst[:2]))
        self.assertEqual({r["eerder_geselecteerd"] for r in lees_csv(self.map / "uit" /
                                                                    "werklijst_nederland_2026-11.csv")}, {"nee"})

    def test_dezelfde_maand_opnieuw_geeft_hetzelfde_en_een_andere_lijst_stopt(self):
        self.assertEqual(self.draai(), 0)
        werklijst = self.map / "uit" / "werklijst_nederland_2026-11.csv"
        bytes_lijst, bytes_reg = werklijst.read_bytes(), self.pad.read_bytes()
        self.assertEqual(self.draai(), 0)  # crit. 3
        self.assertEqual((werklijst.read_bytes(), self.pad.read_bytes()), (bytes_lijst, bytes_reg))
        andere = copy.deepcopy(self.cfg)
        andere["drempels"]["werklijst_max"] = 4
        with self.assertRaises(register.RegisterFout) as fout:  # crit. 8
            self.draai(andere)
        self.assertIn("werklijst_nederland_2026-11.csv", str(fout.exception))
        self.assertEqual((werklijst.read_bytes(), self.pad.read_bytes()), (bytes_lijst, bytes_reg))


@unittest.skipUnless(
    VBO_DELFT.exists(),
    f"{VBO_DELFT.relative_to(PROJECT)} ontbreekt: de Delft-registertests hebben de augustusdata nodig (niet in git)",
)
class TestDelftMaanden(unittest.TestCase):
    """crit. 2 tot en met 8 op Delft, via run_proef.main() in een tijdelijke map."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = delft_basis(selectie.load_config())
        cls.cfg["doelgebied"]["nederland"] = False
        with contextlib.redirect_stdout(io.StringIO()):
            cls.panden = selectie.verwerk(["Delft"], cls.cfg, "Delft", snapshot="vbo_delft.json")

    def setUp(self):
        import run_proef
        self.run_proef = run_proef
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.map = Path(tmp.name)
        for sub in ("output", "data"):
            (self.map / sub).mkdir()
        self.register = self.map / "register" / "geleverde_panden.csv"
        self.echt_register = ECHT_REGISTER.read_bytes() if ECHT_REGISTER.exists() else None
        self.echte_output = {p.name: p.stat().st_mtime_ns for p in (PROJECT / "output").iterdir()}

    def tearDown(self):
        self.assertEqual(ECHT_REGISTER.read_bytes() if ECHT_REGISTER.exists() else None, self.echt_register)
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in (PROJECT / "output").iterdir()},
                         self.echte_output)

    def draai(self, maand: str, cfg=None, label=("Delft", ["Delft"]), extra=()) -> tuple[int, str]:
        """Eén run voor een gesimuleerde maand: de maand van de snapshot wordt 'maand'."""
        panden = copy.deepcopy(self.panden) + copy.deepcopy(list(extra))
        fout = io.StringIO()
        with mock.patch.object(self.run_proef, "load_config", return_value=cfg or self.cfg), \
                mock.patch.object(self.run_proef, "resolve", return_value=label), \
                mock.patch.object(self.run_proef, "kies_snapshots", return_value=[]), \
                mock.patch.object(self.run_proef, "verwerk", return_value=panden), \
                mock.patch.object(self.run_proef, "werklijst_maand", return_value=maand), \
                mock.patch.object(self.run_proef, "UIT", self.map / "output"), \
                mock.patch.object(self.run_proef, "BASE", self.map), \
                mock.patch.object(self.run_proef, "DATA", self.map / "data"), \
                mock.patch.object(sys, "argv", ["run_proef.py"]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(fout):
            return self.run_proef.main(), fout.getvalue()

    def lijst(self, naam: str) -> list[str]:
        return [r["bag_pand_id"] for r in lees_csv(self.map / "output" / naam)]

    def test_drie_maanden_geven_1500_verschillende_panden(self):
        # crit. 5, en crit. 2 en 4 onderweg.
        maanden = ("2026-08", "2026-09", "2026-10")
        per_maand = []
        for maand in maanden:
            code, fout = self.draai(maand)
            self.assertEqual(code, 0, fout)
            per_maand.append(self.lijst(f"werklijst_delft_{maand}.csv"))
        self.assertEqual([len(x) for x in per_maand], [500, 500, 500])
        alle = [i for x in per_maand for i in x]
        self.assertEqual(len(set(alle)), 1_500)
        reg = register.Register(self.register)
        self.assertEqual([r["bag_pand_id"] for r in reg.regels], alle)
        self.assertEqual([r["maand"] for r in reg.regels], [m for m in maanden for _ in range(500)])
        # crit. 2: elke maand vult aan met de hoogst scorende nog niet geleverde panden.
        geschikt = sorted((p for p in self.panden if not p["uitgesloten"] and p["categorieen"]
                           and p["leadscore"] >= self.cfg["drempels"]["score_min_voor_werklijst"]),
                          key=lambda p: -p["leadscore"])
        for i, x in enumerate(per_maand):
            over = [p for p in geschikt if p["bag_pand_id"] not in set(alle[:500 * i])]
            ondergrens = over[499]["leadscore"]
            scores = {p["bag_pand_id"]: p["leadscore"] for p in self.panden}
            self.assertTrue(all(scores[j] >= ondergrens for j in x))
            self.assertEqual(sum(scores[j] > ondergrens for j in x),
                             sum(p["leadscore"] > ondergrens for p in over))
        # crit. 4: de mastervoorraad van oktober zegt 'ja' bij precies de 1.000 van augustus en september.
        master = lees_csv(self.map / "output" / "mastervoorraad_delft.csv")
        self.assertEqual({r["bag_pand_id"] for r in master if r["eerder_geselecteerd"] == "ja"},
                         set(alle[:1_000]))
        self.assertEqual({r["eerder_geselecteerd"] for r in master} , {"ja", "nee"})
        self.assertEqual({r["eerder_geselecteerd"] for r in lees_csv(self.map / "output" /
                                                                    "werklijst_delft_2026-10.csv")}, {"nee"})

    def test_dezelfde_maand_opnieuw_geeft_hetzelfde_bestand(self):
        # crit. 3
        self.assertEqual(self.draai("2026-08")[0], 0)
        pad = self.map / "output" / "werklijst_delft_2026-08.csv"
        lijst, reg = pad.read_bytes(), self.register.read_bytes()
        self.assertEqual(self.draai("2026-08")[0], 0)
        self.assertEqual((pad.read_bytes(), self.register.read_bytes()), (lijst, reg))
        self.assertEqual(len(register.Register(self.register).regels), 500)

    def test_werklijst_max_veranderd_na_levering_stopt_en_verandert_niets(self):
        # crit. 8
        self.assertEqual(self.draai("2026-08")[0], 0)
        uit = self.map / "output"
        voor = {p.name: p.read_bytes() for p in uit.iterdir()}
        reg = self.register.read_bytes()
        minder = copy.deepcopy(self.cfg)
        minder["drempels"]["werklijst_max"] = 400
        code, fout = self.draai("2026-08", minder)
        self.assertNotEqual(code, 0)
        self.assertIn("2026-08", fout)
        self.assertIn("werklijst_delft_2026-08.csv", fout)
        self.assertEqual({p.name: p.read_bytes() for p in uit.iterdir()}, voor)
        self.assertEqual(self.register.read_bytes(), reg)

    def test_een_geleverd_pand_met_de_hand_terug_komt_in_de_volgende_maand_terug(self):
        # crit. 6: de handcorrectie uit de README (regel weghalen) maakt een pand weer beschikbaar.
        self.assertEqual(self.draai("2026-08")[0], 0)
        eerste = self.lijst("werklijst_delft_2026-08.csv")[0]
        regels = self.register.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        self.register.write_text("".join(r for r in regels if not r.startswith(eerste)), encoding="utf-8-sig")
        self.assertEqual(self.draai("2026-09")[0], 0)
        self.assertEqual(self.lijst("werklijst_delft_2026-09.csv")[0], eerste)
        # En de geleverde augustuslijst wordt niet meer stil opnieuw gemaakt (crit. 8).
        self.assertNotEqual(self.draai("2026-08")[0], 0)

    def test_een_register_voor_alle_gebieden(self):
        # crit. 7: Delft, dan een gebied met Delft en een tweede woonplaats; en andersom.
        testdorp = []
        for p in self.panden[:300]:
            q = copy.deepcopy(p)
            q["bag_pand_id"] = "9999" + q["bag_pand_id"][4:]
            q["woonplaats"] = "Testdorp"
            testdorp.append(q)
        twee = ("Delft + Testdorp", ["Delft", "Testdorp"])
        naam_twee = "werklijst_delft+testdorp_2026-08.csv"

        self.assertEqual(self.draai("2026-08")[0], 0)
        delft = set(self.lijst("werklijst_delft_2026-08.csv"))
        self.assertEqual(self.draai("2026-08", label=twee, extra=testdorp)[0], 0)
        beide = self.lijst(naam_twee)
        self.assertEqual(len(beide), 500)
        self.assertFalse(delft & set(beide))
        self.assertTrue(any(i.startswith("0503") for i in beide))

        self.register.unlink()
        self.assertEqual(self.draai("2026-08", label=twee, extra=testdorp)[0], 0)
        beide = set(i for i in self.lijst(naam_twee) if i.startswith("0503"))
        self.assertTrue(beide)
        self.assertEqual(self.draai("2026-09")[0], 0)
        self.assertFalse(beide & set(self.lijst("werklijst_delft_2026-09.csv")))


if __name__ == "__main__":
    unittest.main()
