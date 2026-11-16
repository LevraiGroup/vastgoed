"""
VA-85: de navy band boven het kantoor met de landkaart, het brein en de stroom (Lumi's concepten
A, B en C samen). De stippen komen uit de werklijst, de 25 grootste uit het CBS-bestand van VA-65,
de vijf cijfers uit de totalen, en elke tekst uit Python. Geen data nodig: de pagina wordt gebouwd
op een tijdelijke data-map, net als in test_dashboard_nederland.py.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
sys.path.insert(0, str(HIER))

import build_dashboard as bd  # noqa: E402
import cbs_gemeenten  # noqa: E402
from test_dashboard_nederland import TOTALEN, cfg, pand  # noqa: E402


def script(t=bd.TEMPLATE):
    i = t.index("/* ============================ LANDKAART (VA-85)")
    return t[i:t.index("/* ===================== einde LANDKAART", i)]


def payload_uit(html):
    return json.loads(re.search(r"const PAYLOAD = (\{.*?\});\r?\n", html, re.S).group(1))


class Gebouwd(unittest.TestCase):
    """De hele pagina, gebouwd met bouw_payload() en render() op een tijdelijke data-map."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)
        for p in (mock.patch.object(bd, "DATA", self.map), mock.patch.object(bd, "load_config", cfg)):
            p.start()
            self.addCleanup(p.stop)

    def bouw(self, werklijst, totalen=TOTALEN):
        (self.map / "panden_nederland.json").write_text(json.dumps(
            {"gebied": "Nederland", "totalen": totalen, "werklijst": werklijst, "proef": werklijst[:20]}),
            encoding="utf-8")
        (self.map / "panden_nederland.bron.json").write_text(json.dumps(
            [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]),
            encoding="utf-8")
        html = bd.render(bd.bouw_payload())
        return html, payload_uit(html)["kaart"]

    def lijst(self):
        a = pand(1, "Amsterdam")
        u = dict(pand(2, "Utrecht (gemeente)", "Utrecht"), gemeentecode="0344", x=136000.0, y=456000.0,
                 pandcategorie="A", categorieen=["A", "C"])
        e = dict(pand(3, "Delft", groot=False), gemeentecode="0503", x=84300.0, y=447500.0, pandcategorie="E")
        return [a, u, e]

    def test_de_stippen_volgen_de_invoer(self):
        lijst = self.lijst()
        _, k = self.bouw(lijst)
        pt = [k["pt"][i:i + 4] for i in range(0, len(k["pt"]), 4)]
        self.assertEqual(len(pt), 3)
        verwacht = []
        for p in lijst:
            breedte, lengte = bd.rd_naar_wgs84(p["x"], p["y"])
            verwacht.append(bd._kort(breedte, lengte))
        self.assertEqual([s[:2] for s in pt], verwacht)
        # kleur: categorie (A=0 … E=4), +5 = ring voor score ≥ 8 (alle drie scoren 10)
        self.assertEqual([s[2] for s in pt], [2 + 5, 0 + 5, 4 + 5])
        # Een andere invoer geeft andere stippen: een pand verhuist, een ander valt weg en krijgt score 7.
        lijst[0] = dict(lijst[0], x=233000.0, y=582000.0)   # Groningen
        lijst[2] = dict(lijst[2], leadscore=7)
        _, k2 = self.bouw(lijst[:1] + lijst[2:])
        pt2 = [k2["pt"][i:i + 4] for i in range(0, len(k2["pt"]), 4)]
        self.assertEqual(len(pt2), 2)
        self.assertNotEqual(pt2[0][:2], pt[0][:2])
        self.assertEqual(pt2[0][:2], bd._kort(*bd.rd_naar_wgs84(233000.0, 582000.0)))
        self.assertEqual(pt2[1][2], 4)   # E zonder ring: score 7 < 8

    def test_ongeveer_een_kilometer(self):
        self.assertEqual(bd._kort(52.37404, 4.88969), [237, 189])
        self.assertEqual(bd.KAART_STAP, 100)   # honderdste graad: 1,1 km breedte, 0,7 km lengte

    def test_gemeenten_uit_het_cbs_bestand(self):
        _, k = self.bouw(self.lijst())
        grote = cbs_gemeenten.grootste(25)
        self.assertEqual([g["naam"] for g in k["gm"]], [bd.gemeente_naam(g["gemeente"]) for g in grote])
        pt = [k["pt"][i:i + 4] for i in range(0, len(k["pt"]), 4)]
        namen = [k["gm"][s[3]]["naam"] if s[3] >= 0 else "elders" for s in pt]
        self.assertEqual(namen, ["Amsterdam", "Utrecht", "elders"])
        tel = {g["naam"]: g["n"] for g in k["gm"]}
        self.assertEqual((tel["Amsterdam"], tel["Utrecht"], tel["Rotterdam"]), (1, 1, 0))
        self.assertTrue(all(g["ll"] for g in k["gm"]), "elke grote gemeente heeft een punt uit kaart_nl")

    def test_vijf_cijfers_gelijk_aan_de_rest_van_de_pagina(self):
        html, k = self.bouw(self.lijst())
        p = payload_uit(html)
        self.assertEqual(list(k["trap"].values()), ["9.998.456", "6.568.913", "441.997", "263.319", "4"])
        self.assertEqual([x["v"] for x in p["kpi"]], list(k["trap"].values())[:4])
        self.assertEqual(next(f["val"] for f in p["facts"] if f["k"] == "Panden op de werklijst"), k["trap"]["werklijst"])
        trap = html[html.index('<ol class="trap"'):html.index("</ol>", html.index('<ol class="trap"'))]
        # Ayman: de band noemt het aantal op de werklijst niet; het vijfde cijfer heet alleen "Werklijst".
        self.assertEqual(re.findall(r"<b>([^<]*)</b>", trap), list(k["trap"].values())[:4] + ["Werklijst"])
        self.assertNotIn("op je werklijst", trap)
        self.assertEqual((k["kern"]["label"], "getal" in k["kern"]), ("Werklijst", False))
        self.assertNotRegex(k["kern"]["tip"], r"\b4 panden")

    def test_tekstalternatief_van_lumi(self):
        html, k = self.bouw(self.lijst())
        aria = k["tekst"]["aria"]
        self.assertTrue(aria.startswith(f"Selectie op de BAG van 1{bd.NBSP}november{bd.NBSP}2026: 9.998.456 "
                                        "verblijfsobjecten, 6.568.913 panden, 441.997 in categorie A tot en met E, "
                                        "263.319 met score 8 of hoger, 4 op je werklijst: 3 uit de 25 grootste "
                                        "gemeenten en 1 elders."), aria)
        self.assertTrue(aria.endswith("Amsterdam 1, Utrecht 1."), aria)
        self.assertIn('<canvas class="band-doek" id="landkaart" role="img" aria-label="Selectie op de BAG', html)

    def test_bron_van_de_landvorm_in_de_pagina(self):
        html, _ = self.bouw(self.lijst())
        commentaar = re.search(r"<!-- Landkaart \(VA-85\)\. Landvorm en gemeentepunten: (.*?) -->", html).group(1)
        self.assertIn("CBS Gebiedsindelingen", commentaar)
        self.assertIn("CC BY 4.0", commentaar)
        self.assertIn("landsdeel_gegeneraliseerd", commentaar)

    def test_geen_live_online_of_snapshot(self):
        html, k = self.bouw(self.lijst())
        band = html[html.index('<div class="kantoor-kop band">'):html.index('<div class="pk" id="pk">')]
        for tekst in [band, script(), *k["tekst"].values(), *bd.KAART_TEKST.values()]:
            self.assertNotRegex(tekst.lower(), r"\blive\b|\bonline\b|snapshot")


class Sjabloon(unittest.TestCase):
    def test_delft_zonder_band(self):
        html = bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                          "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})
        self.assertIn('<div class="kantoor-kop">', html)
        self.assertNotIn('id="landkaart"', html)
        self.assertNotIn('class="trap"', html)

    def test_script_tekent_alleen(self):
        js = script()
        # Geen tweede getal- of datumnotatie (VA-31), niets van buiten, geen bibliotheek.
        for weg in ("toLocaleString", "Intl.", "toFixed", "new Date", "fetch(", "XMLHttpRequest", "https://",
                    "import(", "THREE", "<script", "<li>"):
            self.assertNotIn(weg, js)
        for tekst in ("K.kern.label", "g.tip", "c.tip", "K.kern.tip"):
            self.assertIn(tekst, js)

    def test_stil_beeld_en_pauze(self):
        js = script()
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', js)
        self.assertIn("const loopt = () => !rm.matches && zicht && !D.hidden;", js)
        self.assertIn("new IntersectionObserver(", js)
        self.assertIn('D.addEventListener("visibilitychange", speel);', js)

    def test_tokens_zijn_mengsels(self):
        t = bd.TEMPLATE
        blok = t[t.index("/* Landkaart (VA-85, Lumi #h-tokens)"):t.index("*{box-sizing")]
        self.assertIn("--brand-2:color-mix(in srgb,var(--brand) 78%,var(--s1));", blok)
        self.assertIn("--held:linear-gradient(155deg,var(--brand) 0%,var(--brand) 35%,var(--brand-2) 100%);", blok)
        self.assertIn("--gloed:color-mix(in srgb,var(--s1) 40%,transparent);", blok)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,6}\b", blok), [], "geen nieuwe basiskleur")

    def test_kantoor_niet_kleiner(self):
        # VA-64/VA-85: de band duwt het kantoor omlaag, maar de scène houdt haar maat.
        t = bd.TEMPLATE
        self.assertIn("@media (min-width:801px){ .pk-scene.pk-start,.pk-scene.pk-3d{max-height:calc(100vh - 270px)} }", t)
        css = t[t.index("     LANDKAART (VA-85)"):t.index("/* ===================== einde LANDKAART")]
        self.assertNotIn(".pk-scene", css)
        self.assertNotRegex(css, r"\.pk[^{]*\{[^}]*(display:none|visibility:hidden|height:)")


if __name__ == "__main__":
    unittest.main()
