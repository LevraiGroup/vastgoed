"""
VA-5: de maandelijkse werklijst, hoogstens drempels.werklijst_max panden, op leadscore.
VA-32: bij gelijke score een volgorde die vastligt per maand (maandloting).

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
import hashlib
import io
import json
import os
import subprocess
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
PROEF_CSV = PROJECT / "output" / "proefresultaat_20_delft.csv"
WERKLIJST_CSV = PROJECT / "output" / "werklijst_delft_2026-08.csv"
MAAND = "2026-08"


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


def ids(lijst: list[dict]) -> list[str]:
    return [p["bag_pand_id"] for p in lijst]


def zonder_cr(pad: Path) -> bytes:
    """Bestandsinhoud met CRLF als LF: de checkout (core.autocrlf) mag beide hebben."""
    return pad.read_bytes().replace(b"\r\n", b"\n")


def gelijkspel(aantal: int = 40) -> list[dict]:
    """Drie panden boven de grens, `aantal` op de grensscore 11, en twee eronder."""
    boven = [pand("0503100000000901", 14), pand("0503100000000902", 13),
             pand("0503100000000903", 12)]
    grens = [pand(f"05031000000{i:05d}", 11) for i in range(aantal)]
    onder = [pand("0503100000000801", 7), pand("0503100000000802", 6)]
    return boven + grens + onder


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
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=10), MAAND)
        self.assertEqual([p["bag_pand_id"] for p in lijst], ["P01", "P02"])
        self.assertEqual(n, 2)

    def test_volgorde_is_score_aflopend_dan_maandloting(self):
        # VA-32 vervangt VA-5's laagste-BAG-ID-eerst bij gelijke score.
        panden = [pand("P3", 9), pand("P1", 9), pand("P2", 11), pand("P0", 8)]
        lijst, _ = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=10), MAAND)
        negen = sorted(["P1", "P3"], key=lambda i: selectie.maandloting(MAAND, i))
        self.assertEqual(ids(lijst), ["P2", *negen, "P0"])

    def test_hoogstens_werklijst_max_en_dan_de_hoogst_scorende(self):
        panden = [pand(f"P{i:02d}", 8 + i) for i in range(10)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=3), MAAND)
        self.assertEqual([p["leadscore"] for p in lijst], [17, 16, 15])
        self.assertEqual(n, 10)

    def test_minder_geschikt_dan_max_geeft_alle_geschikte(self):
        panden = [pand("P1", 9), pand("P2", 10)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=8, werklijst_max=500), MAAND)
        self.assertEqual((len(lijst), n), (2, 2))

    def test_drempel_komt_uit_de_config(self):
        panden = [pand("P1", 9), pand("P2", 10), pand("P3", 11)]
        lijst, n = selectie.werklijst(panden, cfg_met(score_min_voor_werklijst=10, werklijst_max=500), MAAND)
        self.assertEqual([p["bag_pand_id"] for p in lijst], ["P3", "P2"])
        self.assertEqual(n, 2)


class TestWerklijstMaandvolgorde(unittest.TestCase):
    """VA-32: bij gelijke score beslist een volgorde die vastligt voor de maand."""

    def setUp(self):
        # 3 boven de grens + 10 van de 40 op de grensscore 11.
        self.cfg = cfg_met(score_min_voor_werklijst=8, werklijst_max=13)

    def test_dezelfde_maand_geeft_dezelfde_lijst(self):
        a, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-08")
        b, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-08")
        self.assertEqual(ids(a), ids(b))

    def test_omgekeerde_invoervolgorde_geeft_dezelfde_lijst(self):
        a, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-08")
        b, _ = selectie.werklijst(list(reversed(gelijkspel())), self.cfg, "2026-08")
        self.assertEqual(ids(a), ids(b))

    def test_een_andere_maand_geeft_een_andere_volgorde_binnen_de_gelijke_score(self):
        cfg = cfg_met(score_min_voor_werklijst=8, werklijst_max=500)       # iedereen past
        a, _ = selectie.werklijst(gelijkspel(), cfg, "2026-08")
        b, _ = selectie.werklijst(gelijkspel(), cfg, "2026-09")
        elf_a = [p["bag_pand_id"] for p in a if p["leadscore"] == 11]
        elf_b = [p["bag_pand_id"] for p in b if p["leadscore"] == 11]
        self.assertEqual(sorted(elf_a), sorted(elf_b))
        self.assertNotEqual(elf_a, elf_b)

    def test_een_andere_maand_kiest_andere_panden_op_de_grensscore(self):
        a, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-08")
        b, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-09")
        elf_a = {p["bag_pand_id"] for p in a if p["leadscore"] == 11}
        elf_b = {p["bag_pand_id"] for p in b if p["leadscore"] == 11}
        self.assertEqual((len(elf_a), len(elf_b)), (10, 10))
        self.assertNotEqual(elf_a, elf_b)

    def test_scores_boven_de_grens_veranderen_niet(self):
        for maand in ("2026-08", "2026-09", "2027-01"):
            lijst, _ = selectie.werklijst(gelijkspel(), self.cfg, maand)
            self.assertEqual(
                ids(lijst[:3]), ["0503100000000901", "0503100000000902", "0503100000000903"],
                maand)
            self.assertEqual([p["leadscore"] for p in lijst], [14, 13, 12] + [11] * 10, maand)

    def test_buiten_de_snede_verandert_niets(self):
        # Wie niet in aanmerking komt, komt er in geen maand in; de panden zelf wijzigen niet.
        panden = gelijkspel() + [
            pand("0503100000000701", 15, cats=()),
            pand("0503100000000702", 15, uitgesloten=True),
        ]
        voor = copy.deepcopy(panden)
        nooit = {"0503100000000701", "0503100000000702", "0503100000000801", "0503100000000802"}
        for maand in ("2026-08", "2026-09"):
            lijst, n = selectie.werklijst(panden, self.cfg, maand)
            self.assertEqual((len(lijst), n), (13, 43), maand)
            self.assertFalse(nooit & set(ids(lijst)), maand)
        self.assertEqual(panden, voor, "werklijst() mag de panden niet wijzigen")

    def test_de_mastervolgorde_blijft_score_dan_bag_pand_id(self):
        panden = [pand("P3", 9), pand("P1", 9), pand("P2", 11)]
        self.assertEqual(ids(sorted(panden, key=selectie.mastervolgorde)), ["P2", "P1", "P3"])

    def test_lotnummer_is_sha256_van_maand_dubbelepunt_pand_id(self):
        self.assertEqual(
            selectie.maandloting("2026-08", "0503100000000001"),
            hashlib.sha256(b"2026-08:0503100000000001").hexdigest(),
        )

    def test_onafhankelijk_van_pythonhashseed(self):
        code = (
            "import json, sys; sys.path.insert(0, sys.argv[1]); import selectie; "
            "cfg = selectie.load_config(); "
            "cfg['drempels'].update(score_min_voor_werklijst=8, werklijst_max=13); "
            "lijst, _ = selectie.werklijst(json.loads(sys.argv[2]), cfg, '2026-08'); "
            "print(json.dumps([p['bag_pand_id'] for p in lijst]))"
        )
        uitkomsten = []
        for seed in ("0", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r = subprocess.run(
                [sys.executable, "-c", code, str(PROJECT), json.dumps(gelijkspel())],
                cwd=PROJECT, env=env, capture_output=True, text=True, check=True,
            )
            uitkomsten.append(json.loads(r.stdout))
        lijst, _ = selectie.werklijst(gelijkspel(), self.cfg, "2026-08")
        self.assertEqual(uitkomsten, [ids(lijst), ids(lijst)])

    def test_een_maand_die_geen_jjjj_mm_is_stopt(self):
        for fout in ("2026-08-04", "2026-13", "augustus", "", None):
            with self.assertRaises(ValueError, msg=repr(fout)):
                selectie.werklijst(gelijkspel(), self.cfg, fout)


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

    def test_500_van_1668_met_243_boven_en_257_op_de_grensscore(self):
        lijst, n = selectie.werklijst(self.panden, self.cfg, MAAND)
        self.assertEqual(n, 1_668)
        self.assertEqual(len(lijst), 500)
        self.assertEqual(sum(p["leadscore"] >= 12 for p in lijst), 243)
        self.assertEqual(sum(p["leadscore"] == 11 for p in lijst), 257)
        self.assertEqual(min(p["leadscore"] for p in lijst), 11)

    def test_augustus_en_september_delen_de_243_en_verschillen_op_score_11(self):
        aug, _ = selectie.werklijst(self.panden, self.cfg, "2026-08")
        sep, _ = selectie.werklijst(self.panden, self.cfg, "2026-09")
        with open(MASTER_CSV, encoding="utf-8-sig", newline="") as fh:
            boven = {r["bag_pand_id"] for r in csv.DictReader(fh, delimiter=";")
                     if int(r["leadscore"]) >= 12}
        self.assertEqual(len(boven), 243)
        for lijst in (aug, sep):
            self.assertEqual({p["bag_pand_id"] for p in lijst if p["leadscore"] >= 12}, boven)
        elf_aug = {p["bag_pand_id"] for p in aug if p["leadscore"] == 11}
        elf_sep = {p["bag_pand_id"] for p in sep if p["leadscore"] == 11}
        self.assertEqual((len(elf_aug), len(elf_sep)), (257, 257))
        self.assertNotEqual(elf_aug, elf_sep)

    def test_omgekeerde_invoer_geeft_dezelfde_delft_werklijst(self):
        a, _ = selectie.werklijst(self.panden, self.cfg, MAAND)
        b, _ = selectie.werklijst(list(reversed(self.panden)), self.cfg, MAAND)
        self.assertEqual(ids(a), ids(b))

    def test_de_vastgelegde_werklijst_van_augustus(self):
        # Vastgelegd in VA-32: 500 rijen, 243 boven de grensscore 11 en 257 erop, in de
        # volgorde van de maandloting van 2026-08.
        lijst, _ = selectie.werklijst(self.panden, self.cfg, MAAND)
        with open(WERKLIJST_CSV, encoding="utf-8-sig", newline="") as fh:
            rijen = list(csv.DictReader(fh, delimiter=";"))
        self.assertEqual(len(rijen), 500)
        self.assertEqual(sum(int(r["leadscore"]) >= 12 for r in rijen), 243)
        self.assertEqual(sum(int(r["leadscore"]) == 11 for r in rijen), 257)
        self.assertEqual([r["bag_pand_id"] for r in rijen], ids(lijst))

    def test_werklijst_max_uit_de_config_verandert_de_lijst(self):
        lijst, n = selectie.werklijst(self.panden, cfg_met(werklijst_max=50), MAAND)
        self.assertEqual((len(lijst), n), (50, 1_668))
        lijst, n = selectie.werklijst(self.panden, cfg_met(werklijst_max=5_000), MAAND)
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
            # De gecommitte config kiest Nederland (VA-39); deze test draait Delft, zoals in augustus.
            delft = copy.deepcopy(self.cfg)
            delft["doelgebied"]["nederland"] = False
            with mock.patch.object(run_proef, "load_config", return_value=delft), \
                    mock.patch.object(run_proef, "UIT", uit), \
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
            # Elke werklijstrij is letterlijk een rij uit de mastervoorraad.
            master_rijen = {tuple(r.items()) for r in master}
            for r in rijen:
                self.assertIn(tuple(r.items()), master_rijen)
            # Byte voor byte de vastgelegde bestanden (op de regeleinden na, die
            # core.autocrlf bepaalt): de werklijst sinds VA-32, de mastervoorraad en het
            # proefresultaat ongewijzigd.
            for naam, vastgelegd in (("werklijst_delft_2026-08.csv", WERKLIJST_CSV),
                                     ("mastervoorraad_delft.csv", MASTER_CSV),
                                     ("proefresultaat_20_delft.csv", PROEF_CSV)):
                self.assertEqual(zonder_cr(uit / naam), zonder_cr(vastgelegd), naam)

        self.assertEqual(sorted(p.name for p in (PROJECT / "output").iterdir()), echte_output)


if __name__ == "__main__":
    unittest.main()
