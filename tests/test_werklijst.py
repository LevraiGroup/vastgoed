"""
VA-5: de maandelijkse werklijst, hoogstens drempels.werklijst_max panden, op leadscore.

De eenheidstests werken op kleine nep-panden en een kopie van de config in het geheugen,
dus ze lezen en schrijven niets in data/ of output/. De Delft-tests lezen de
augustus-snapshot data/vbo_delft.json en worden overgeslagen als dat bestand ontbreekt.
De eind-tot-eindtest draait run_proef.main() met output/ en data/ omgeleid naar een
tijdelijke map, en controleert dat de echte output/ en data/ niet veranderen.

Alleen standaardbibliotheek plus de eigen modules van het project.
"""
from __future__ import annotations

import contextlib
import copy
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import selectie  # noqa: E402
from snapshots import Snapshot  # noqa: E402

AUGUSTUS_SNAPSHOT = "vbo_delft.json"
VBO_DELFT = PROJECT / "data" / AUGUSTUS_SNAPSHOT
MASTER_CSV = PROJECT / "output" / "mastervoorraad_delft.csv"


def pand(pand_id: str, score: int, cats=("A",), uitgesloten: bool = False) -> dict:
    return {
        "bag_pand_id": pand_id,
        "leadscore": score,
        "categorieen": list(cats),
        "uitgesloten": uitgesloten,
    }


def cfg_met(**drempels) -> dict:
    cfg = copy.deepcopy(selectie.load_config())
    cfg["drempels"].update(drempels)
    return cfg


def snap(datum: str | None, naam: str = "vbo_x.json", woonplaats: str = "X") -> Snapshot:
    return Snapshot(woonplaats, Path(naam), datum, 1, "meta" if datum else "onbekend")


class TestWerklijstKeuze(unittest.TestCase):

    def test_alleen_niet_uitgesloten_in_categorie_en_boven_de_drempel(self):
        panden = [
            pand("P01", 9),
            pand("P02", 8),                       # precies op de drempel: telt mee
            pand("P03", 7),                       # onder de drempel
            pand("P04", 12, cats=()),             # geen categorie
            pand("P05", 12, uitgesloten=True),    # uitgesloten
        ]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=10))
        self.assertEqual([p["bag_pand_id"] for p in lijst], ["P01", "P02"])
        self.assertEqual(n, 2)

    def test_volgorde_is_score_aflopend_dan_bag_pand_id(self):
        panden = [pand("P3", 9), pand("P1", 9), pand("P2", 11), pand("P0", 8)]
        lijst, _ = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=10))
        self.assertEqual([p["bag_pand_id"] for p in lijst], ["P2", "P1", "P3", "P0"])

    def test_hoogstens_werklijst_max_en_dan_de_hoogst_scorende(self):
        panden = [pand(f"P{i:02d}", 8 + i) for i in range(10)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=3))
        self.assertEqual([p["leadscore"] for p in lijst], [17, 16, 15])
        self.assertEqual(n, 10)

    def test_minder_geschikt_dan_max_geeft_alle_geschikte(self):
        panden = [pand("P1", 9), pand("P2", 10)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=500))
        self.assertEqual((len(lijst), n), (2, 2))

    def test_drempel_komt_uit_de_config(self):
        panden = [pand("P1", 9), pand("P2", 10), pand("P3", 11)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=10, werklijst_max=500))
        self.assertEqual([p["bag_pand_id"] for p in lijst], ["P3", "P2"])
        self.assertEqual(n, 2)


class TestWerklijstWaarschuwing(unittest.TestCase):

    def test_onder_het_minimum_een_nederlandse_waarschuwing_met_het_aantal(self):
        melding = selectie.werklijst_waarschuwing(
            1234, cfg_met(werklijst_min=2000, score_min_voor_werklijst=8))
        self.assertIsNotNone(melding)
        self.assertIn("WAARSCHUWING", melding)
        self.assertIn("slechts 1.234 panden", melding)
        self.assertIn("2.000", melding)
        self.assertIn("drempels.werklijst_min", melding)

    def test_op_of_boven_het_minimum_geen_waarschuwing(self):
        cfg = cfg_met(werklijst_min=200)
        self.assertIsNone(selectie.werklijst_waarschuwing(200, cfg))
        self.assertIsNone(selectie.werklijst_waarschuwing(1668, cfg))


class TestWerklijstMaand(unittest.TestCase):

    def test_maand_van_de_snapshot_niet_van_vandaag(self):
        self.assertEqual(selectie.werklijst_maand([snap("2026-08-04")]), "2026-08")

    def test_meerdere_woonplaatsen_geven_de_nieuwste_maand(self):
        gekozen = [snap("2026-08-04", "a.json", "A"), snap("2026-10-01", "b.json", "B")]
        self.assertEqual(selectie.werklijst_maand(gekozen), "2026-10")

    def test_zonder_ophaaldatum_stopt_het(self):
        with self.assertRaises(selectie.snapshots.SnapshotFout):
            selectie.werklijst_maand([snap(None, "vbo_rijswijk.json", "Rijswijk")])


@unittest.skipUnless(
    VBO_DELFT.exists(),
    f"{VBO_DELFT.relative_to(PROJECT)} ontbreekt: de Delft-werklijsttests hebben de "
    "augustusdata nodig (niet in git)",
)
class TestWerklijstDelft(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cfg = selectie.load_config()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.panden = selectie.verwerk(["Delft"], cls.cfg, "Delft", snapshot=AUGUSTUS_SNAPSHOT)

    def test_500_van_1668_en_gelijk_aan_het_begin_van_de_mastervoorraad(self):
        lijst, n = selectie.werklijst(self.panden, self.cfg)
        self.assertEqual(n, 1_668)
        self.assertEqual(len(lijst), 500)
        drempel = self.cfg["drempels"]["score_min_voor_werklijst"]
        with open(MASTER_CSV, encoding="utf-8-sig", newline="") as fh:
            master = [r for r in csv.DictReader(fh, delimiter=";") if int(r["leadscore"]) >= drempel]
        self.assertEqual(
            [p["bag_pand_id"] for p in lijst],
            [r["bag_pand_id"] for r in master[:500]],
        )

    def test_werklijst_max_uit_de_config_verandert_de_lijst(self):
        lijst, n = selectie.werklijst(self.panden, cfg_met(werklijst_max=50))
        self.assertEqual((len(lijst), n), (50, 1_668))
        lijst, n = selectie.werklijst(self.panden, cfg_met(werklijst_max=5_000))
        self.assertEqual((len(lijst), n), (1_668, 1_668))

    def test_geen_waarschuwing_bij_1668_geschikte_panden(self):
        self.assertIsNone(selectie.werklijst_waarschuwing(1_668, self.cfg))

    def test_run_proef_schrijft_de_werklijst_van_augustus(self):
        import run_proef  # noqa: E402  (hier, zodat de eenheidstests run_proef niet laden)

        echte_output = sorted(p.name for p in (PROJECT / "output").iterdir())
        with tempfile.TemporaryDirectory() as tmp:
            uit = Path(tmp) / "output"
            data = Path(tmp) / "data"
            uit.mkdir()
            data.mkdir()
            argv = ["run_proef.py", "--snapshot", AUGUSTUS_SNAPSHOT]
            fout = io.StringIO()
            with mock.patch.object(run_proef, "UIT", uit), \
                    mock.patch.object(run_proef, "BASE", Path(tmp)), \
                    mock.patch.object(run_proef, "DATA", data), \
                    mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(fout):
                self.assertEqual(run_proef.main(), 0)
            self.assertNotIn("WAARSCHUWING", fout.getvalue())

            pad = uit / "werklijst_delft_2026-08.csv"
            self.assertTrue(pad.exists(), sorted(p.name for p in uit.iterdir()))
            self.assertTrue(pad.read_bytes().startswith(b"\xef\xbb\xbf"), "geen UTF-8 BOM")
            with open(pad, encoding="utf-8-sig", newline="") as fh:
                lezer = csv.DictReader(fh, delimiter=";")
                rijen = list(lezer)
                kolommen = lezer.fieldnames
            with open(uit / "mastervoorraad_delft.csv", encoding="utf-8-sig", newline="") as fh:
                lezer = csv.DictReader(fh, delimiter=";")
                master = list(lezer)
                self.assertEqual(kolommen, lezer.fieldnames)
            self.assertEqual(len(rijen), 500)
            self.assertEqual({r["datapeildatum"] for r in rijen}, {"2026-08-04"})
            # Elke werklijstrij is letterlijk de rij uit de mastervoorraad.
            drempel = self.cfg["drempels"]["score_min_voor_werklijst"]
            self.assertEqual(rijen, [r for r in master if int(r["leadscore"]) >= drempel][:500])

        self.assertEqual(sorted(p.name for p in (PROJECT / "output").iterdir()), echte_output)


if __name__ == "__main__":
    unittest.main()
