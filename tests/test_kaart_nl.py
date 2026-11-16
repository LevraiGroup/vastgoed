"""
VA-85: kaart_nl.py maakt van de vier landsdelen van CBS één omtrek, en het kaartbestand in
referentie/ noemt zijn bron. Geen netwerk: de functies krijgen eigen vlakken.
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cbs_gemeenten  # noqa: E402
import kaart_nl  # noqa: E402


def vierkant(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


class Omtrek(unittest.TestCase):
    def test_twee_buren_worden_een_lus(self):
        # Twee landsdelen die elkaar raken: de grens ertussen verdwijnt.
        vol = kaart_nl.raster([[vierkant(0, 0, 4, 4)], [vierkant(4, 0, 8, 4)]], 0, 4, 1, 1, 8, 4)
        self.assertEqual(len(vol), 32)
        lussen = kaart_nl.randlussen(vol)
        self.assertEqual(len(lussen), 1)
        self.assertEqual(len(kaart_nl.vereenvoudig_lus(lussen[0], .1)), 4)

    def test_een_spleet_van_een_cel_gaat_dicht(self):
        vol = kaart_nl.raster([[vierkant(0, 0, 3.9, 4)], [vierkant(4.1, 0, 8, 4)]], 0, 4, 1, 1, 8, 4)
        self.assertEqual(len(kaart_nl.randlussen(vol)), 1)

    def test_een_meer_blijft_een_gat(self):
        vlak = [[vierkant(0, 0, 10, 10), vierkant(3, 3, 7, 7)]]
        vol = kaart_nl.raster(vlak, 0, 10, 1, 1, 10, 10)
        self.assertEqual(len(vol), 100 - 16)
        self.assertEqual(len(kaart_nl.randlussen(vol)), 2)

    def test_douglas_peucker(self):
        lijn = [(0, 0), (1, .01), (2, 0), (3, 5), (4, 0)]
        self.assertEqual(kaart_nl.douglas_peucker(lijn, .1), [(0, 0), (2, 0), (3, 5), (4, 0)])

    def test_gemeentepunten(self):
        f = [{"properties": {"statcode": "GM0363"}, "geometry": {"type": "Point", "coordinates": [4.8897, 52.37404]}}]
        self.assertEqual(kaart_nl.gemeentepunten(f), {"0363": [52.374, 4.89]})

    def test_schrijft_nooit_over(self):
        with tempfile.TemporaryDirectory() as d:
            pad = kaart_nl.schrijf(2030, [[[52.0, 4.0]]], {"0363": [52.0, 4.0]}, Path(d), date(2030, 1, 2))
            bron = json.loads(pad.read_text(encoding="utf-8"))["bron"]
            self.assertEqual((bron["licentie"], bron["opgehaald"], bron["peiljaar"]), ("CC BY 4.0", "2030-01-02", 2030))
            with self.assertRaises(FileExistsError):
                kaart_nl.schrijf(2030, [], {}, Path(d))


@unittest.skipUnless(kaart_nl.nieuwste(), "geen kaart_nl_<jaar>.json in referentie/")
class Referentiebestand(unittest.TestCase):
    def setUp(self):
        self.kaart = json.loads(kaart_nl.nieuwste().read_text(encoding="utf-8"))

    def test_bron_genoemd(self):
        b = self.kaart["bron"]
        self.assertEqual(b["licentie"], "CC BY 4.0")
        self.assertEqual(b["lagen"], ["landsdeel_gegeneraliseerd", "gemeente_labelpoint"])
        self.assertTrue(b["dienst"].startswith("https://service.pdok.nl/cbs/gebiedsindelingen/"))

    def test_zelfde_jaar_en_elke_gemeente(self):
        self.assertEqual(self.kaart["bron"]["peiljaar"], kaart_nl.peiljaar())
        codes = {g["gemeentecode"] for g in cbs_gemeenten.lees()}
        self.assertEqual(set(self.kaart["gemeenten"]), codes)

    def test_land_ligt_in_nederland(self):
        punten = [p for lus in self.kaart["land"] for p in lus]
        self.assertGreater(len(punten), 200)
        self.assertTrue(all(50.7 < b < 53.7 and 3.3 < l < 7.3 for b, l in punten))


if __name__ == "__main__":
    unittest.main()
