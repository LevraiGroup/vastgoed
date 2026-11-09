"""
VA-65: de 25 grootste gemeenten komen uit het vastgelegde CBS-bestand (tabel 03759ned).
Zonder netwerk: de test leest alleen referentie/; het ophalen wordt met een vervanging getest.
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cbs_gemeenten as cbs  # noqa: E402

BESTAND_2026 = cbs.REFERENTIE / "gemeenten_cbs_2026.csv"
DE_25 = ["0363", "0599", "0518", "0344", "0772", "0014", "0034", "0855", "0758", "0268", "0202",
         "0200", "0392", "0394", "0479", "0307", "0153", "0796", "0193", "0637", "0546", "0080",
         "0935", "0228", "0505"]


@unittest.skipUnless(BESTAND_2026.is_file(), f"{BESTAND_2026} ontbreekt")
class Peiljaar2026(unittest.TestCase):
    def setUp(self):
        self.g = cbs.lees(BESTAND_2026)

    def test_alle_gemeenten(self):
        self.assertEqual(len(self.g), 342)
        self.assertEqual(len({x["gemeentecode"] for x in self.g}), 342)
        self.assertTrue(all(len(x["gemeentecode"]) == 4 and x["gemeentecode"].isdigit() for x in self.g))
        self.assertEqual([x["rang"] for x in self.g], list(range(1, 343)))

    def test_de_25_grootste(self):
        self.assertEqual([x["gemeentecode"] for x in cbs.grootste(25, BESTAND_2026)], DE_25)
        self.assertEqual(self.g[24]["gemeente"], "Dordrecht")
        self.assertEqual(self.g[24]["inwoners_1_januari"], 122991)

    def test_net_erbuiten(self):
        rang = {x["gemeente"]: x["rang"] for x in self.g}
        self.assertEqual(rang["Westland"], 26)
        self.assertEqual(rang["Delft"], 29)

    def test_bronbestand(self):
        bron = json.loads(BESTAND_2026.with_suffix(".bron.json").read_text(encoding="utf-8"))
        self.assertEqual(bron["tabel"], "03759ned")
        self.assertEqual(bron["peiljaar"], 2026)
        self.assertEqual(bron["titel"], "Bevolking op 1 januari en gemiddeld; geslacht, leeftijd en regio")
        self.assertRegex(bron["opgehaald"], r"^\d{4}-\d{2}-\d{2}$")


class Rangschikken(unittest.TestCase):
    def test_gelijk_inwonertal_laagste_code_eerst(self):
        uit = cbs.rangschik([{"gemeentecode": "0200", "gemeente": "B", "inwoners_1_januari": 5},
                             {"gemeentecode": "0100", "gemeente": "A", "inwoners_1_januari": 5},
                             {"gemeentecode": "0300", "gemeente": "C", "inwoners_1_januari": 9}])
        self.assertEqual([(x["rang"], x["gemeentecode"]) for x in uit], [(1, "0300"), (2, "0100"), (3, "0200")])


class Schrijven(unittest.TestCase):
    def test_nooit_overschrijven_en_nieuwste(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            rij = [{"rang": 1, "gemeentecode": "0363", "gemeente": "Amsterdam", "inwoners_1_januari": 1}]
            cbs.schrijf("2026", "T", rij, map_, vandaag=date(2026, 11, 9))
            with self.assertRaises(FileExistsError):
                cbs.schrijf("2026", "T", rij, map_)
            cbs.schrijf("2027", "T", rij, map_)
            self.assertEqual(cbs.nieuwste(map_).name, "gemeenten_cbs_2027.csv")
            self.assertEqual(cbs.lees(map_ / "gemeenten_cbs_2026.csv"), rij)

    def test_cbs_onbereikbaar_schrijft_niets(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cbs, "REFERENTIE", Path(tmp)), \
                mock.patch.object(cbs, "_haal", side_effect=cbs.CbsFout("geen verbinding")):
            self.assertNotEqual(cbs.main(), 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_geen_gemeentecijfers_schrijft_niets(self):
        def nep(pad, query=None):
            return {"TableInfos": [{"Title": "T"}], "RegioS": [{"Key": "GM0363", "Title": "Amsterdam"}],
                    "Perioden": [{"Key": "2026JJ00"}], "TypedDataSet": []}[pad]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cbs, "REFERENTIE", Path(tmp)), \
                mock.patch.object(cbs, "_haal", side_effect=nep):
            self.assertNotEqual(cbs.main(), 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
