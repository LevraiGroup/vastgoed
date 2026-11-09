"""
VA-61 en VA-62: een pand openen. pand_detail() toont elk veld van het record als Nederlandse
tekst, en geeft de luchtfoto (PDOK) en kaartlinks op de juiste plek. Alleen standaardbibliotheek.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402

DELFT_PANDEN = bd.DATA / "panden_delft.json"
VERBODEN = re.compile(r"\b(None|null|undefined|NaN|nan|True|False|true|false)\b|^\[\]$|^\{\}$")


def pand(**extra):
    p = {"bag_pand_id": "0503100000021394", "lead_id": "LEV-DE-00021394",
         "hoofdadres": "Verwersdijk 144A, 2611NL Delft",
         "gekoppelde_adressen": ["Verwersdijk 144A, 2611NL Delft", "Verwersdijk 146, 2611NM Delft"],
         "aantal_adressen": 2, "woonplaats": "Delft", "postcode": "2611NL", "huisnummer": 144,
         "huisletter": "A", "bouwjaar": 1850, "pandstatus": "Pand in gebruik",
         "vbo_ids": ["0503010000002567", "0503010000026793"], "aantal_vbo": 2,
         "gebruiksdoelen": ["woonfunctie"], "opp_per_functie": {"woon": 1287.4, "winkel": 0},
         "aantal_per_functie": {"woon": 2}, "totale_oppervlakte": 1287.4,
         "x": 84249.364, "y": 447967.176, "vbo_statussen": ["Verblijfsobject in gebruik"],
         "uitsluitredenen": [], "uitgesloten": False, "categorieen": ["C"], "pandcategorie": "C",
         "leadscore": 11, "score100": 42, "score_opbouw": [], "selectiereden": "3 adressen",
         "bron": "PDOK BAG WFS v2_0", "datapeildatum": "2026-08-04", "visuele_controle": False,
         "beoordeling": "", "eerder_geselecteerd": False, "laatst_beoordeeld": ""}
    p.update(extra)
    return p


def waarden(det):
    uit = []
    for r in det["rijen"]:
        uit.extend(r["v"] if isinstance(r["v"], list) else [r["v"]])
    return uit


class ElkVeld(unittest.TestCase):
    def test_velden_dekken_het_record(self):
        # Een veld dat erbij komt zonder label laat deze test falen (VA-61 crit. 2).
        self.assertEqual({v for v, _, _ in bd.PAND_VELDEN}, set(pand()))

    def test_elke_rij_heeft_label_en_waarde(self):
        det = bd.pand_detail(pand())
        labels = [r["k"] for r in det["rijen"]]
        self.assertEqual(len(labels), len(bd.PAND_VELDEN) - 1)  # score-opbouw toont de pagina apart
        self.assertEqual(len(labels), len(set(labels)))

    @unittest.skipUnless(DELFT_PANDEN.is_file(), f"{DELFT_PANDEN} ontbreekt")
    def test_elk_veld_van_elk_lead_op_de_pagina(self):
        payload = bd.bouw_payload()
        velden = {v for v, _, _ in bd.PAND_VELDEN}
        panden = {p["bag_pand_id"]: p for p in json.loads(DELFT_PANDEN.read_text(encoding="utf-8"))}
        self.assertEqual(len(payload["leads"]), 20)
        for lead in payload["leads"]:
            record = panden[lead["id"]]
            self.assertLessEqual(set(record), velden, lead["id"])
            for w in waarden(lead["detail"]):
                self.assertNotRegex(w, VERBODEN, lead["id"])


class NederlandseWaarden(unittest.TestCase):
    def rij(self, label, **extra):
        return next(r["v"] for r in bd.pand_detail(pand(**extra))["rijen"] if r["k"] == label)

    def test_opmaak(self):
        self.assertEqual(self.rij("Totale oppervlakte"), "1.287 m²")
        self.assertEqual(self.rij("Oppervlakte per functie"), ["Wonen: 1.287 m²"])
        self.assertEqual(self.rij("X-coördinaat (RD)"), "84.249,36")
        self.assertEqual(self.rij("Peildatum van de gegevens"), "4 aug 2026")
        self.assertEqual(self.rij("Uitgesloten"), "nee")
        self.assertEqual(self.rij("Eerder geselecteerd", eerder_geselecteerd=True), "ja")
        self.assertEqual(self.rij("Bouwjaar"), "1850")

    def test_leeg_is_een_woord(self):
        self.assertEqual(self.rij("Beoordeling"), "niet ingevuld")
        self.assertEqual(self.rij("Laatst beoordeeld"), "niet ingevuld")
        self.assertEqual(self.rij("Redenen voor uitsluiting"), "geen")
        self.assertEqual(self.rij("Huisletter", huisletter=None), "geen")  # Lumi: de meeste panden hebben geen letter
        self.assertEqual(self.rij("Bouwjaar", bouwjaar=None), "onbekend")
        for w in waarden(bd.pand_detail(pand(huisletter=None, pandstatus=float("nan"), vbo_ids=[]))):
            self.assertNotRegex(w, VERBODEN)

    def test_lange_lijsten_volledig(self):
        ids = [f"05030100000{i:05d}" for i in range(803)]
        adressen = [f"Straat {i}, 2611AA Delft" for i in range(803)]
        det = bd.pand_detail(pand(vbo_ids=ids, gekoppelde_adressen=adressen))
        self.assertEqual(next(r["v"] for r in det["rijen"] if r["k"] == "Verblijfsobject-ID's"), ids)
        self.assertEqual(len(next(r["v"] for r in det["rijen"] if r["k"] == "Alle adressen")), 803)


class Locatie(unittest.TestCase):
    def test_amersfoort(self):
        self.assertEqual(bd.rd_naar_wgs84(155000, 463000), (52.155174, 5.387206))

    def test_delft(self):
        breedte, lengte = bd.rd_naar_wgs84(84249.364, 447967.176)
        self.assertAlmostEqual(breedte, 52.0155, places=3)
        self.assertAlmostEqual(lengte, 4.3566, places=3)

    def test_links_en_foto(self):
        loc = bd.pand_detail(pand())["locatie"]
        self.assertTrue(loc["foto"].startswith("https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0?"))
        self.assertIn("BBOX=84209.4,447927.2,84289.4,448007.2", loc["foto"])  # 80 m rond het pand
        self.assertNotRegex(loc["foto"].lower(), r"key|token")
        self.assertIn(f"{loc['lat']},{loc['lon']}", loc["maps"])
        self.assertIn("map_action=pano", loc["streetview"])

    def test_zonder_bruikbare_plek(self):
        for extra in ({"x": None}, {"y": 0}, {"x": "84249"}):
            with self.subTest(extra=extra):
                self.assertIsNone(bd.pand_detail(pand(**extra))["locatie"])

    @unittest.skipUnless(DELFT_PANDEN.is_file(), f"{DELFT_PANDEN} ontbreekt")
    def test_elk_lead_heeft_een_plek(self):
        for lead in bd.bouw_payload()["leads"]:
            loc = lead["detail"]["locatie"]
            self.assertTrue(51.9 < loc["lat"] < 52.1 and 4.2 < loc["lon"] < 4.5, lead["id"])


class Pagina(unittest.TestCase):
    def test_dialoog_en_geen_extra_bron(self):
        t = bd.TEMPLATE
        self.assertIn('<dialog class="pand" id="pand"', t)
        self.assertIn(">Sluiten</button>", t)
        self.assertNotIn("<script src", t)  # three.js laadt de pagina zelf (VA-60); de foto is een <img>
        self.assertNotIn("service.pdok.nl", t)  # de URL komt per pand uit de payload, pas bij openen


if __name__ == "__main__":
    unittest.main()
