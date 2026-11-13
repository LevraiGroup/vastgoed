"""
VA-39 (eerste plak "alleen NL"): het dashboard toont Nederland uit data/panden_nederland.json.
De cijfers komen uit de totalen van VA-37, de werklijst staat er met een filter op gemeente, en
alle tekst komt uit Lumi's kopij (design/copy-va39.md) via Python. Geen data nodig, behalve de
groottetest op de echte pagina (die wordt overgeslagen zonder data/panden_nederland.json).
"""
import json
import os
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402

NL_PANDEN = bd.DATA / "panden_nederland.json"


def cfg(nederland=True):
    return {"doelgebied": {"steden": ["Delft"], "provincies": [], "nederland": nederland},
            "drempels": {"score_min_voor_werklijst": 8, "werklijst_min": 200, "werklijst_max": 500,
                         "aantal_grote_gemeenten": 25, "werklijst_aandeel_overig": 0.10},
            "score": {"schaal_max": 26}, "bronnen": {}}


def pand(i, gemeente, woonplaats=None, groot=True, score=10):
    return {"bag_pand_id": f"0363100000{i:06d}", "hoofdadres": f"Straat {i}, 1011AA {woonplaats or gemeente}",
            "gekoppelde_adressen": [], "aantal_adressen": 1, "woonplaats": woonplaats or gemeente,
            "postcode": "1011AA", "huisnummer": i, "huisletter": "", "bouwjaar": 1900 + i,
            "pandstatus": "Pand in gebruik", "vbo_ids": [], "aantal_vbo": 3, "gebruiksdoelen": [],
            "opp_per_functie": {"woon": 300.0}, "aantal_per_functie": {"woon": 3}, "totale_oppervlakte": 300.0,
            "x": 121000.0, "y": 487000.0, "vbo_statussen": [], "gemeentecode": "0363", "uitsluitredenen": [],
            "uitgesloten": False, "categorieen": ["C"], "pandcategorie": "C", "leadscore": score,
            "score100": round(score / 26 * 100), "score_opbouw": [
                {"label": "Bouwjaar vóór 1940", "punten": 3, "behaald": True, "detail": "bouwjaar 1900",
                 "status": "behaald"}],
            "selectiereden": "", "lead_id": f"LEV-NL-0363100000{i:06d}",
            "bron": "PDOK BAG GeoPackage (bag_nl_2026-11-01.sqlite)", "datapeildatum": "2026-11-01",
            "visuele_controle": False, "beoordeling": "", "eerder_geselecteerd": False, "laatst_beoordeeld": "",
            "gemeente": gemeente, "grote_gemeente": "ja" if groot else "nee"}


TOTALEN = {"vbo": 9998456, "panden": 6568913, "uitgesloten": 475372, "a_e": 441997,
           "categorieen": {"A": 45359, "B": 54325, "C": 175135, "D": 151174, "E": 135662},
           "geschikt": 263319, "geschikt_25": 139846, "geschikt_overig": 123473, "werklijst": 4,
           "werklijst_25": 3, "werklijst_overig": 1, "drempel": 8, "maand": "2026-11",
           "aantal_grote_gemeenten": 25}


class Woorden(unittest.TestCase):
    def test_maand_voluit(self):
        self.assertEqual(bd.maand_voluit("2026-11"), "november 2026")
        self.assertEqual(bd.maand_voluit("2027-01"), "januari 2027")
        for kapot in (None, "", "2026", "2026-13", "nov"):
            self.assertEqual(bd.maand_voluit(kapot), "onbekend", kapot)

    def test_gemeente_naam(self):
        self.assertEqual(bd.gemeente_naam("Utrecht (gemeente)"), "Utrecht")
        self.assertEqual(bd.gemeente_naam("'s-Gravenhage (gemeente)"), "'s-Gravenhage")
        self.assertEqual(bd.gemeente_naam("Krimpenerwaard"), "Krimpenerwaard")
        # Alleen het exacte achtervoegsel: andere haakjes onderscheiden gemeenten (Lumi, VA-39 sectie 3).
        self.assertEqual(bd.gemeente_naam("Bergen (L.)"), "Bergen (L.)")
        self.assertEqual(bd.gemeente_naam("Bergen (NH.)"), "Bergen (NH.)")
        self.assertEqual(bd.gemeente_naam("Hengelo (gemeente) (O.)"), "Hengelo (gemeente) (O.)")
        self.assertEqual(bd.gemeente_naam(None), "onbekend")

    def test_kaartregel(self):
        # Lumi: '{postcode} {woonplaats} · gemeente {gemeente}', en zonder gemeente als die gelijk is.
        self.assertEqual(bd.kaartregel(pand(1, "Utrecht (gemeente)", "Utrecht"), True), "1011AA Utrecht")
        self.assertEqual(bd.kaartregel(pand(1, "Krimpenerwaard", "Ouderkerk aan den IJssel"), True),
                         "1011AA Ouderkerk aan den IJssel · gemeente Krimpenerwaard")
        # Een gebied als Delft houdt de regel van vandaag.
        self.assertEqual(bd.kaartregel(pand(1, "Delft"), False), "1011AA Delft · BAG 0363100000000001")


class Filter(unittest.TestCase):
    def setUp(self):
        self.lijst = [pand(1, "Utrecht (gemeente)", "Utrecht"), pand(2, "Amsterdam"), pand(3, "Amsterdam"),
                      pand(4, "'s-Gravenhage (gemeente)", "'s-Gravenhage"),
                      pand(5, "Baarn", groot=False), pand(6, "Alkmaar", groot=False), pand(7, "Alkmaar", groot=False)]
        self.f = bd.gemeente_filter(self.lijst, 25)

    def test_twee_groepen_op_alfabet_met_tellingen(self):
        self.assertEqual(self.f["label"], "Gemeente")
        self.assertEqual(self.f["alle"], "Alle gemeenten (7)")
        self.assertEqual([g["label"] for g in self.f["groepen"]],
                         ["De 25 grootste gemeenten", "Elders in Nederland"])
        self.assertEqual([o["tekst"] for o in self.f["groepen"][0]["opties"]],
                         ["Amsterdam (2)", "'s-Gravenhage (1)", "Utrecht (1)"])
        self.assertEqual([o["tekst"] for o in self.f["groepen"][1]["opties"]], ["Alkmaar (2)", "Baarn (1)"])
        self.assertEqual(sum(o["aantal"] for g in self.f["groepen"] for o in g["opties"]), len(self.lijst))

    def test_gebieden_en_teksten_voor_het_script(self):
        # VA-68: de uitkomstregel van VA-39 vervalt (de telling vervangt hem, Lumi bouwnotitie 1);
        # een onbekende gemeente in het adres valt weg (VA-68 crit. 9), dus geen eigen lege zin meer.
        self.assertEqual(self.f["gebied"], [["groot", "De 25 grootste gemeenten"], ["elders", "Elders in Nederland"]])
        self.assertEqual(self.f["tekst"]["alle"], "Alle 7 panden")
        self.assertEqual(self.f["tekst"]["telling"], "{n} van 7 panden")
        for weg in ("uitkomst", "leeg", "terug"):
            self.assertNotIn(weg, self.f)

    def test_namen_in_het_filter_zijn_uniek(self):
        f = bd.gemeente_filter(self.lijst + [pand(8, "Bergen (L.)", groot=False),
                                             pand(9, "Bergen (NH.)", groot=False)], 25)
        namen = [o["naam"] for g in f["groepen"] for o in g["opties"]]
        self.assertEqual(len(namen), len(set(namen)))
        self.assertIn("Bergen (L.)", namen)
        self.assertIn("Bergen (NH.)", namen)

    def test_een_lege_groep_valt_weg(self):
        f = bd.gemeente_filter([pand(1, "Amsterdam")], 25)
        self.assertEqual([g["label"] for g in f["groepen"]], ["De 25 grootste gemeenten"])

    def test_html_is_ontsnapt_en_volledig(self):
        html = bd.filter_html(bd.gemeente_filter([pand(1, 'A&B "x"')], 25))
        self.assertIn('value="A&amp;B &quot;x&quot;"', html)
        self.assertIn('<label for="gemeente">Gemeente</label>', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn(' hidden>', html)  # de lege toestand staat uit tot het script hem nodig heeft
        self.assertEqual(bd.filter_html(None), "")


class LeesLandelijk(unittest.TestCase):
    def test_vormfouten(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "panden_nederland.json"
            self.assertIn("ontbreekt", bd.lees_landelijk(pad)[1])
            for inhoud, reden in (("{kapot", "niet leesbaar"), ("[]", "geen totalen"),
                                  ('{"totalen": {}}', "geen totalen")):
                pad.write_text(inhoud, encoding="utf-8")
                gelezen, r = bd.lees_landelijk(pad)
                self.assertIsNone(gelezen)
                self.assertIn(reden, r)


class PayloadLandelijk(unittest.TestCase):
    """bouw_payload() met nederland: true, op een tijdelijke data-map."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)
        for p in (mock.patch.object(bd, "DATA", self.map), mock.patch.object(bd, "load_config", cfg)):
            p.start()
            self.addCleanup(p.stop)

    def schrijf(self, werklijst, totalen=TOTALEN):
        pad = self.map / "panden_nederland.json"
        pad.write_text(json.dumps({"gebied": "Nederland", "totalen": totalen, "werklijst": werklijst,
                                   "proef": werklijst[:20]}), encoding="utf-8")
        bron = self.map / "panden_nederland.bron.json"
        bron.write_text(json.dumps([{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite",
                                     "ophaaldatum": "2026-11-01"}]), encoding="utf-8")
        later = pad.stat().st_mtime + 1
        os.utime(bron, (later, later))

    def test_zonder_bestand_onbekend(self):
        payload = bd.bouw_payload()
        self.assertEqual(payload["gebied"], "Nederland")
        self.assertEqual([k["v"] for k in payload["kpi"]], ["onbekend"] * 4)
        self.assertIn("panden_nederland.json ontbreekt", payload["kpi"][0]["h"])
        self.assertEqual(payload["leads"], [])
        self.assertIsNone(payload["filter"])
        self.assertIsNone(payload["kantoor"]["ingest"]["vbo"])
        html = bd.render(payload)
        self.assertEqual(re.findall(r"__[A-Z][A-Z0-9_]*__", html), [])
        self.assertIn('href="#werklijst"', html)

    def test_cijfers_uit_de_totalen_niet_herteld(self):
        lijst = [pand(1, "Amsterdam"), pand(2, "Amsterdam"), pand(3, "Utrecht (gemeente)", "Utrecht"),
                 pand(4, "Baarn", groot=False)]
        self.schrijf(lijst)
        payload = bd.bouw_payload()
        self.assertEqual([k["v"] for k in payload["kpi"]], ["9.998.456", "6.568.913", "441.997", "263.319"])
        self.assertEqual(payload["kpi"][0]["h"], f"uit de BAG van 1{bd.NBSP}nov{bd.NBSP}2026")
        self.assertEqual(payload["cats"][2]["n"], 175135)
        feiten = {f["k"]: f["val"] for f in payload["facts"]}
        # Zonder snapshot op deze machine het bestand uit .bron.json, nooit een verzonnen naam.
        self.assertEqual(feiten["Bronbestand"], f"bag_nl_2026-11-01.sqlite · 1{bd.NBSP}nov{bd.NBSP}2026")
        self.assertEqual(feiten["Gem. oppervlakte"], "300 m²")
        self.assertEqual(payload["koppen"]["werklijst.titel"], "Werklijst november 2026")
        self.assertEqual(payload["koppen"]["voorraad.titel"], "Voorraad en werklijst")
        self.assertEqual(payload["koppen"]["voorraad.zin"], "Hoeveel van de 441.997 panden in elke categorie "
                         "A–E vallen, en wat de 4 panden op de werklijst van deze maand kenmerkt.")
        self.assertIn("In de 25 grootste gemeenten", payload["velden"])
        self.assertEqual(payload["pagina"]["feiten.titel"], "Werklijst in cijfers")
        self.assertEqual(payload["pagina"]["feiten.cap"], "De 4 panden van deze maand, verdeeld over het land")
        self.assertEqual([lead["id"] for lead in payload["leads"]], [p["bag_pand_id"] for p in lijst])  # volgorde van de run
        self.assertEqual([lead["g"] for lead in payload["leads"]], ["Amsterdam", "Amsterdam", "Utrecht", "Baarn"])
        html = bd.render(payload)
        self.assertEqual(re.findall(r"__[A-Z][A-Z0-9_]*__", html), [])
        self.assertIn("<title>Levrai · Pandenselectie — Nederland</title>", html)
        self.assertNotIn("Delft", re.sub(r"const PAYLOAD = [^\n]*", "", html))

    def test_bronbestand_uit_de_meta_van_de_snapshot(self):
        self.schrijf([pand(1, "Amsterdam")])
        with mock.patch.object(bd.snapshots, "_lees_meta", return_value={"bron": "bag-light_2026-11-01.gpkg"}):
            (self.map / "bag_nl_2026-11-01.sqlite").write_bytes(b"")
            feiten = {f["k"]: f for f in bd.bouw_payload()["facts"]}
        self.assertEqual(feiten["Bronbestand"]["val"], f"bag-light_2026-11-01.gpkg · 1{bd.NBSP}nov{bd.NBSP}2026")
        self.assertEqual(feiten["Bronbestand"]["tip"],
                         f"Heel Nederland: BAG-GeoPackage van PDOK, stand 1{bd.NBSP}nov{bd.NBSP}2026")


class Sjabloon(unittest.TestCase):
    """Wat het script van de pagina doet, en wat het niet doet."""

    def test_script_maakt_geen_filterzinnen(self):
        for weg in ("Alle gemeenten", "grootste gemeenten", "Elders in Nederland", "Toon alle gemeenten",
                    "pand in ", "op de werklijst van deze maand", "Wis alle filters", "Categorie", "Leegstaand",
                    "In verbouwing", "Luchtfoto kon niet laden", "Locatie onbekend"):
            self.assertNotIn(weg, bd.TEMPLATE)
        self.assertIn("const T = PAYLOAD.filter.tekst", bd.TEMPLATE)

    def test_kaarten_in_stappen_met_terugval(self):
        t = bd.TEMPLATE
        self.assertIn('"IntersectionObserver" in window', t)
        self.assertIn('<div class="schildwacht" aria-hidden="true"></div>', t)
        self.assertIn("LEADS.filter(d => past(d, null))", t)  # het filter werkt alleen op de lijst

    def test_geen_jaartal_of_verbergen_in_de_code(self):
        bron = Path(bd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("verberg", bron)
        self.assertEqual(re.findall(r"\b20[2-9]\d\b", bron), [])  # een datum komt uit de data


class Pagina(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.opties, self.groepen = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "option":
            self.opties.append(a)
        if tag == "optgroup":
            self.groepen.append(a["label"])


@unittest.skipUnless(NL_PANDEN.is_file(), f"{NL_PANDEN} ontbreekt; echte landelijke pagina overgeslagen")
class EchtePagina(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = bd.load_config()
        c["doelgebied"]["nederland"] = True
        with mock.patch.object(bd, "load_config", lambda: c):
            cls.payload = bd.bouw_payload()
        cls.html = bd.render(cls.payload)

    def test_licht_genoeg_voor_4g(self):
        # VA-39 crit. 5: onder 5 s op 'Fast 4G'. De server comprimeert niet (serve.py), dus de
        # pagina zelf blijft onder 1 MB; three.js komt apart en pas na het laden.
        self.assertLess(len(self.html.encode("utf-8")), 1_000_000)

    def test_filter_heeft_elke_gemeente_van_de_lijst(self):
        p = Pagina(self.html)
        namen = [o["value"] for o in p.opties if o["value"]]
        self.assertEqual(len(namen), len(set(namen)), "dubbele gemeentenaam in het filter")
        self.assertEqual(set(namen), {lead["g"] for lead in self.payload["leads"]})
        self.assertEqual(p.groepen, ["De 25 grootste gemeenten", "Elders in Nederland"])


if __name__ == "__main__":
    unittest.main()
