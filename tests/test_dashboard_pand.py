"""
VA-61 en VA-62: een pand openen. pand_detail() toont elk veld van het record als Nederlandse
tekst, en geeft de luchtfoto (PDOK) en kaartlinks op de juiste plek. Alleen standaardbibliotheek.
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402

DELFT_PANDEN = bd.DATA / "panden_delft.json"
NL_PANDEN = bd.DATA / "panden_nederland.json"
LANDELIJK = {"gemeentecode": "0503", "gemeente": "Delft", "grote_gemeente": "nee"}  # VA-37 crit. 2
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
    p.update(LANDELIJK)  # een landelijk record: de 34 velden van Delft plus de drie van VA-37
    p.update(extra)
    return p


def delfts(**extra):
    """Een record zoals panden_delft.json het heeft: zonder de landelijke velden."""
    return {k: v for k, v in pand(**extra).items() if k not in LANDELIJK}


def payload_met(nederland):
    c = bd.load_config()
    c["doelgebied"]["nederland"] = nederland
    with mock.patch.object(bd, "load_config", lambda: c):
        return bd.bouw_payload()


def uitgevouwen(lead, payload):
    """Wat de pagina bij openen toont: pand_kort() uit de payload, terug naar pand_detail()."""
    det = lead["detail"]
    rijen = [{"k": k, "v": payload["waarden"][n]} for k, n in zip(payload["velden"], det["w"])
             if payload["waarden"][n] is not None]
    loc = None
    if det["loc"]:
        b, ll = det["loc"]["b"], det["loc"]["ll"]
        breedte, lengte = (float(x) for x in ll.split(","))
        loc = {"lat": breedte, "lon": lengte,
               **{k: s.replace("{b}", b).replace("{ll}", ll) for k, s in payload["plek"].items()}}
    return {"titel": det["titel"], "rijen": rijen, "locatie": loc}


def waarden(det):
    uit = []
    for r in det["rijen"]:
        uit.extend(r["v"] if isinstance(r["v"], list) else [r["v"]])
    return uit


class ElkVeld(unittest.TestCase):
    def test_velden_dekken_het_record(self):
        # Een veld dat erbij komt zonder label laat deze test falen (VA-61 crit. 2).
        self.assertEqual({v for v, _, _ in bd.PAND_VELDEN}, set(pand()))
        self.assertEqual(bd.ALLEEN_LANDELIJK, set(LANDELIJK))

    def test_elke_rij_heeft_label_en_waarde(self):
        det = bd.pand_detail(pand(), 25)
        labels = [r["k"] for r in det["rijen"]]
        self.assertEqual(len(labels), len(bd.PAND_VELDEN) - 1)  # score-opbouw toont de pagina apart
        self.assertEqual(len(labels), len(set(labels)))
        rij = {r["k"]: r["v"] for r in det["rijen"]}
        self.assertEqual((rij["Gemeente"], rij["Gemeentecode"], rij["In de 25 grootste gemeenten"]),
                         ("Delft", "0503", "nee"))
        # Direct na Woonplaats (Lumi, VA-39 sectie 3).
        labels = [r["k"] for r in det["rijen"]]
        i = labels.index("Woonplaats")
        self.assertEqual(labels[i + 1:i + 4], ["Gemeente", "Gemeentecode", "In de 25 grootste gemeenten"])

    def test_gemeente_ingekort_zoals_op_de_kaart(self):
        rij = {r["k"]: r["v"] for r in bd.pand_detail(pand(gemeente="Utrecht (gemeente)"), 25)["rijen"]}
        self.assertEqual(rij["Gemeente"], "Utrecht")
        rij = {r["k"]: r["v"] for r in bd.pand_detail(pand(gemeente=None), 25)["rijen"]}
        self.assertEqual(rij["Gemeente"], "onbekend")

    def test_delfts_record_zonder_landelijke_rijen(self):
        # Geen drie keer 'onbekend' bij een Delfts pand: die velden heeft het record niet.
        labels = [r["k"] for r in bd.pand_detail(delfts(), 25)["rijen"]]
        self.assertEqual(len(labels), len(bd.PAND_VELDEN) - 1 - len(LANDELIJK))
        self.assertNotIn("Gemeente", labels)

    def echte_leads(self, payload, records):
        velden = {v for v, _, _ in bd.PAND_VELDEN}
        groot = (payload["kantoor"].get("selectie") or {}).get("aantal_groot")
        for lead in payload["leads"]:
            record = records[lead["id"]]
            self.assertLessEqual(set(record), velden, lead["id"])
            det = uitgevouwen(lead, payload)
            self.assertEqual(det, bd.pand_detail(record, groot if groot is not None else 25), lead["id"])
            # De score-opbouw uit PAYLOAD.criteria is regel voor regel die van het record.
            self.assertEqual([payload["criteria"][i] for i in lead["ob"]],
                             [[it["label"], it["punten"], it["status"], it["detail"]] for it in record["score_opbouw"]])
            for w in waarden(det):
                self.assertNotRegex(w, VERBODEN, lead["id"])

    @unittest.skipUnless(DELFT_PANDEN.is_file(), f"{DELFT_PANDEN} ontbreekt")
    def test_elk_veld_van_elk_lead_op_de_pagina_delft(self):
        payload = payload_met(False)
        records = {p["bag_pand_id"]: p for p in json.loads(DELFT_PANDEN.read_text(encoding="utf-8"))}
        self.assertEqual(len(payload["leads"]), 20)
        self.echte_leads(payload, records)

    @unittest.skipUnless(NL_PANDEN.is_file(), f"{NL_PANDEN} ontbreekt")
    def test_elk_veld_van_elk_lead_op_de_pagina_nederland(self):
        # VA-39 crit. 6: 'Open pand' werkt op een landelijk pand, met elk veld van het record.
        payload = payload_met(True)
        lijst = json.loads(NL_PANDEN.read_text(encoding="utf-8"))["werklijst"]
        records = {p["bag_pand_id"]: p for p in lijst}
        self.assertEqual(len(payload["leads"]), len(lijst))
        for record in lijst:
            self.assertEqual(set(record), {v for v, _, _ in bd.PAND_VELDEN}, record["bag_pand_id"])
        self.echte_leads(payload, records)


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
        for lead in payload_met(False)["leads"]:
            breedte, lengte = (float(x) for x in lead["detail"]["loc"]["ll"].split(","))
            self.assertTrue(51.9 < breedte < 52.1 and 4.2 < lengte < 4.5, lead["id"])

    @unittest.skipUnless(NL_PANDEN.is_file(), f"{NL_PANDEN} ontbreekt")
    def test_elk_landelijk_lead_ligt_in_nederland(self):
        for lead in payload_met(True)["leads"]:
            breedte, lengte = (float(x) for x in lead["detail"]["loc"]["ll"].split(","))
            self.assertTrue(50.7 < breedte < 53.6 and 3.3 < lengte < 7.3, lead["id"])


class Pagina(unittest.TestCase):
    def test_dialoog_en_geen_extra_bron(self):
        t = bd.TEMPLATE
        self.assertIn('<dialog class="pand" id="pand"', t)
        self.assertIn(">Sluiten</button>", t)
        self.assertNotIn("<script src", t)  # three.js laadt de pagina zelf (VA-60); de foto is een <img>
        self.assertNotIn("service.pdok.nl", t)  # de URL komt per pand uit de payload, pas bij openen


if __name__ == "__main__":
    unittest.main()
