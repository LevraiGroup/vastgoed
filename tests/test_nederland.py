"""
VA-37: de landelijke werklijst. De verdeling over de 25 grootste gemeenten en de rest
(450/50 bij een aandeel van 0,10), de aanvulling als een deel tekortkomt, en de 'beste N'
zonder alles vast te houden. Alleen standaardbibliotheek, geen data nodig.
"""
import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nederland  # noqa: E402
import selectie  # noqa: E402

MAAND = "2026-11"


def pand(i, score, groot=True):
    return {"bag_pand_id": f"{i:016d}", "leadscore": score,
            nederland.IN_GROOT: "ja" if groot else "nee"}


def cfg(aandeel=0.10, maximum=500, groot=25):
    return {"drempels": {"werklijst_max": maximum, "werklijst_aandeel_overig": aandeel,
                         "aantal_grote_gemeenten": groot, "score_min_voor_werklijst": 8,
                         "werklijst_min": 200}}


class Aantallen(unittest.TestCase):
    def test_standaard(self):
        self.assertEqual(nederland.aantallen(cfg()), (25, 450, 50))

    def test_randen(self):
        self.assertEqual(nederland.aantallen(cfg(aandeel=0)), (25, 500, 0))
        self.assertEqual(nederland.aantallen(cfg(aandeel=1)), (25, 0, 500))
        self.assertEqual(nederland.aantallen(cfg(aandeel=0.25, maximum=10)), (25, 8, 2))  # 2,5 -> 2

    def test_config_controle(self):
        for sleutel, waarde in (("werklijst_aandeel_overig", 1.5), ("werklijst_aandeel_overig", -0.1),
                                ("werklijst_aandeel_overig", "tien"), ("werklijst_aandeel_overig", float("nan")),
                                ("aantal_grote_gemeenten", 0), ("aantal_grote_gemeenten", 2.5)):
            with self.subTest(sleutel=sleutel, waarde=waarde):
                c = cfg()
                c["drempels"][sleutel] = waarde
                c["score"] = {"schaal_max": 26}
                fouten = selectie.controleer_drempels(c)
                self.assertEqual(len(fouten), 1, fouten)
                self.assertIn(f"drempels.{sleutel} = {waarde!r}", fouten[0])


class Verdelen(unittest.TestCase):
    def setUp(self):
        self.groot = [pand(i, 8 + i % 7) for i in range(2000)]
        self.overig = [pand(10_000 + i, 8 + i % 9, groot=False) for i in range(800)]

    def test_450_en_50(self):
        lijst, meldingen = nederland.verdeel(self.groot, self.overig, 450, 50, MAAND, 25)
        self.assertEqual(len(lijst), 500)
        self.assertEqual(sum(p[nederland.IN_GROOT] == "ja" for p in lijst), 450)
        self.assertEqual(meldingen, [])
        # Eén lijst op leadscore en maandloting (VA-37 crit. 5).
        self.assertEqual(lijst, sorted(lijst, key=selectie.werklijstvolgorde(MAAND)))
        # Elk deel neemt zijn beste: niemand buiten de lijst scoort hoger dan de zwakste van zijn deel.
        gekozen = {p["bag_pand_id"] for p in lijst}
        for deel in (self.groot, self.overig):
            binnen = [p for p in deel if p["bag_pand_id"] in gekozen]
            buiten = [p for p in deel if p["bag_pand_id"] not in gekozen]
            sl = selectie.werklijstvolgorde(MAAND)
            self.assertLess(max(sl(p) for p in binnen), min(sl(p) for p in buiten))

    def test_aandeel_nul_en_een(self):
        self.assertTrue(all(p[nederland.IN_GROOT] == "ja"
                            for p in nederland.verdeel(self.groot, self.overig, 500, 0, MAAND, 25)[0]))
        self.assertTrue(all(p[nederland.IN_GROOT] == "nee"
                            for p in nederland.verdeel(self.groot, self.overig, 0, 500, MAAND, 25)[0]))

    def test_deel_komt_tekort(self):
        lijst, meldingen = nederland.verdeel(self.groot, self.overig[:20], 450, 50, MAAND, 25)
        self.assertEqual(len(lijst), 500)
        self.assertEqual(sum(p[nederland.IN_GROOT] == "nee" for p in lijst), 20)
        self.assertEqual(len(meldingen), 1)
        self.assertIn("de 25 grootste gemeenten vullen 30 aan", meldingen[0])
        lijst, meldingen = nederland.verdeel(self.groot[:100], self.overig, 450, 50, MAAND, 25)
        self.assertEqual(len(lijst), 500)
        self.assertIn("de rest van Nederland vult 350 aan", meldingen[0])

    def test_samen_te_weinig(self):
        lijst, _ = nederland.verdeel(self.groot[:30], self.overig[:10], 450, 50, MAAND, 25)
        self.assertEqual(len(lijst), 40)


class Beste(unittest.TestCase):
    def test_gelijk_aan_sorteren(self):
        rng = random.Random(7)
        panden = [pand(i, rng.randint(0, 20)) for i in range(3000)]
        for sleutel in (selectie.mastervolgorde, selectie.werklijstvolgorde(MAAND)):
            with self.subTest(sleutel=sleutel):
                b = nederland.Beste(25, sleutel)
                for p in panden:
                    b.voeg_toe(copy.copy(p))
                self.assertEqual([p["bag_pand_id"] for p in b.lijst()],
                                 [p["bag_pand_id"] for p in sorted(panden, key=sleutel)[:25]])

    def test_nul(self):
        b = nederland.Beste(0, selectie.mastervolgorde)
        b.voeg_toe(pand(1, 9))
        self.assertEqual(b.lijst(), [])


class Kiezen(unittest.TestCase):
    def test_nederland_uit_config(self):
        self.assertTrue(nederland.is_nederland({"doelgebied": {"nederland": True}}))
        self.assertFalse(nederland.is_nederland({"doelgebied": {"steden": ["Delft"]}}))
        self.assertFalse(nederland.is_nederland(selectie.load_config()))  # Delft blijft de standaard


class DraaiMetStub(unittest.TestCase):
    """VA-37 crit. 3 en 7: draai() op een nagemaakte stroom, uitvoer in een tijdelijke map."""

    def setUp(self):
        import tempfile, types
        from unittest import mock
        import cbs_gemeenten, run_proef
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.map = Path(self.tmp.name)
        (self.map / "uit").mkdir()
        (self.map / "data").mkdir()
        snap = types.SimpleNamespace(pad=self.map / "snap.sqlite", ophaaldatum="2026-11-01", landelijk=True,
                                     omschrijving=lambda: "stub")
        self.groot = [g["gemeentecode"] for g in cbs_gemeenten.lees() if g["rang"] <= 25]
        self.run_proef = run_proef
        mock.patch.object(nederland, "nieuwste_snapshot", lambda cfg, keuze: snap).start()
        self.addCleanup(mock.patch.stopall)
        self.cfg = selectie.load_config()
        self.cfg["doelgebied"]["nederland"] = True

    def stroom(self, codes):
        def maak(*a, **k):
            for i, code in enumerate(codes):
                # Elke gemeente krijgt een pand met dezelfde laatste 8 cijfers: LEV-DE-… zou botsen.
                yield {"bag_pand_id": f"{code}100000{i % 7:06d}", "gemeentecode": code, "aantal_vbo": 1,
                       "uitsluitredenen": [], "uitgesloten": False, "categorieen": ["A"], "leadscore": 10,
                       "hoofdadres": "", "woonplaats": "", "opp_per_functie": {}, "aantal_per_functie": {}}
        return maak

    def draai(self, codes):
        from unittest import mock
        with mock.patch.object(selectie, "stroom_panden", self.stroom(codes)):
            return nederland.draai(self.cfg, None, self.run_proef.KOLOMMEN, self.run_proef.csv_rij,
                                   self.map / "uit", self.map / "data")

    def test_lead_ids_uniek_en_verdeling(self):
        import csv
        self.assertEqual(self.draai(self.groot + ["0503", "0599"] * 3 + ["9999"] * 4), 0)
        with open(self.map / "uit" / "mastervoorraad_nederland.csv", encoding="utf-8-sig") as fh:
            rijen = list(csv.DictReader(fh, delimiter=";"))
        ids = [r["lead_id"] for r in rijen]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("LEV-NL-") and len(i) == 7 + 16 for i in ids))
        self.assertEqual({r[nederland.IN_GROOT] for r in rijen}, {"ja", "nee"})

    def test_ontbrekende_grote_gemeente_schrijft_niets(self):
        with self.assertRaises(nederland.NederlandFout) as fout:
            self.draai(self.groot[1:] + ["9999"] * 3)
        self.assertIn(self.groot[0], str(fout.exception))
        self.assertEqual(list((self.map / "uit").iterdir()) + list((self.map / "data").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
