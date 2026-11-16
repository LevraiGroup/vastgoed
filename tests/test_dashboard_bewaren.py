"""
VA-90: Bewaar en Verberg op elke kaart en in 'Open pand', alleen in deze browser. Het gedrag zelf vraagt
een browser (de close-out); hier staat wat in de bron en in de gebouwde pagina te controleren is:
criterium 2 (drie standen, dezelfde knop zet terug), 5 (de werklijst telt alleen wat getoond wordt,
het adres blijft van de filters) en 6 (wat er per pand wordt bewaard, en dat er niets de pagina uit gaat).
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
from test_dashboard_nederland import TOTALEN, cfg, pand  # noqa: E402


def blok(t=bd.TEMPLATE):
    """Het script van VA-90."""
    i = t.index("/* ============================ BEWAREN EN VERBERGEN (VA-90)")
    return t[i:t.index("/* ============================ einde BEWAREN EN VERBERGEN", i)]


def werklijst(t=bd.TEMPLATE):
    i = t.index("/* ============================ WERKLIJST (VA-39")
    return t[i:t.index("/* ============================ einde WERKLIJST", i)]


def payload_uit(html):
    return json.loads(re.search(r"const PAYLOAD = (\{.*?\});\r?\n", html, re.S).group(1))


class DrieStanden(unittest.TestCase):
    """Criterium 2: bewaard, verborgen of geen van beide; dezelfde knop nog eens zet het terug."""

    def test_een_stand_per_pand(self):
        js = blok()
        # Eén veld 'stand' per pand-ID: bewaren overschrijft verbergen en andersom.
        self.assertIn('nu = van(d.id) === s ? "" : s;', js)
        self.assertIn("if (nu) stand[d.id] = gegevens(d, nu); else delete stand[d.id];", js)
        self.assertIn("const van = id => (stand[id] && stand[id].stand) || \"\";", js)

    def test_stand_te_zien_met_meer_dan_kleur(self):
        js, css = blok(), bd.TEMPLATE
        self.assertIn('b.setAttribute("aria-pressed", String(aan));', js)
        self.assertIn('(aan ? "★" : "☆")', js)       # bewaard: een volle ster
        self.assertIn('.bw-knop.bw-weg[aria-pressed="true"]{background:var(--grid);border:1px dashed', css)
        self.assertIn('T["terug." + soort]', js)       # de knop zegt hoe je het terugzet
        for k in ("bewaar", "bewaard", "verberg", "verborgen", "terug.bewaard", "terug.verborgen", "ongedaan"):
            self.assertTrue(bd.BEWAAR_TEKST[k])

    def test_ongedaan_maken_zet_de_vorige_stand_terug(self):
        js = blok()
        self.assertIn("function herstel(d, oud) {", js)
        self.assertIn("if (oud) stand[d.id] = oud; else delete stand[d.id];", js)
        # Crit. 3: de statusregel is een status (beleefd voorgelezen), boven de werklijst en in 'Open pand'.
        self.assertIn('s.setAttribute("role", "status")', js)
        self.assertIn('<div class="bw-status" id="bwStatus" role="status"></div>', bd.TEMPLATE)
        self.assertNotIn('role="alert"', js)

    def test_drukken_opent_het_pand_niet(self):
        # VA-61 crit. 1: een klik op de kaart opent het pand, maar niet een klik op een knop.
        self.assertIn("b.addEventListener(\"click\", e => { e.stopPropagation(); druk(d, soort, b); });", blok())
        self.assertIn('if (e.target.closest("a, summary, details, button")) return;', bd.TEMPLATE)


class Werklijst(unittest.TestCase):
    """Criterium 5: filters en sorteren gelden voor wat getoond wordt; het adres blijft van de filters."""

    def test_verborgen_telt_nergens_mee(self):
        w = werklijst()
        past = w[w.index("function past(d, behalve) {"):]
        self.assertTrue(past.split("\n")[1].strip().startswith("if (!BW.zichtbaar(d.id)) return false;"))
        self.assertIn("LEADS.filter(d => past(d, null))", w)       # de telling is wat past()
        self.assertIn("teken(sorteer(treffers), houd);", w)        # en dat zijn de kaarten
        self.assertIn("telling.textContent = a || n !== LEADS.length ? vul(T.telling, n) : T.alle;", w)

    def test_het_adres_blijft_van_de_filters(self):
        w = werklijst()
        eigen = w[w.index("const EIGEN = "):w.index("\n", w.index("const EIGEN = "))]
        self.assertNotIn("bw", eigen.lower())
        self.assertIn("BW.op(() => werk(false, true));", w)          # na een druk: geen nieuw adres
        schrijf = w[w.index("function schrijfAdres() {"):w.index("// Het paneel")]
        self.assertNotIn("BW", schrijf)

    def test_alleen_verbergen_herschikt_de_lijst(self):
        js = blok()
        self.assertIn('overal(nu === "verborgen" || (oud && oud.stand === "verborgen"));', js)
        self.assertIn("if (lijst) luisteraars.forEach(f => f());", js)
        # Ter plekke herschikken: een kaart die blijft, wordt niet opnieuw opgehangen (geen tweede PDOK-verzoek).
        self.assertIn("[...lb.children].forEach(c => { if (!blijft.has(c)) c.remove(); });", werklijst())

    def test_stad_zonder_filterpaneel(self):
        self.assertIn("const alles = houd => teken(LEADS.filter(d => BW.zichtbaar(d.id)), houd);", werklijst())


class Opslag(unittest.TestCase):
    """Criterium 6 (wat er per pand staat, en niets gaat de pagina uit), 8 (opslag geweigerd) en 9."""

    def test_wat_va91_nodig_heeft(self):
        js = blok()
        g = js[js.index("const gegevens = "):js.index("function zet(")]
        for veld in ("hoofdadres", "woonplaats", "score100", "pandcategorie", "bag_viewer_url", "datapeildatum", "sinds"):
            self.assertIn(veld + ":", g)
        self.assertIn('SLEUTEL = "levrai-vastgoed-panden", VORM = 1', js)

    def test_niets_gaat_de_pagina_uit(self):
        js = blok()
        for weg in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "https://", "navigator.", "postMessage",
                    "document.cookie", "new Image"):
            self.assertNotIn(weg, js)
        self.assertEqual(js.count("localStorage.setItem("), 2)   # de proef en het opslaan
        self.assertEqual(js.count("localStorage.removeItem("), 1)  # alleen de proefsleutel

    def test_opslag_geweigerd_breekt_niets(self):
        js = blok()
        self.assertEqual(js.count("try {"), js.count("catch (e)"))
        # Elke aanraking van localStorage staat in een try op dezelfde regel of vlak erboven.
        for i in [m.start() for m in re.finditer(r"localStorage\.", js)]:
            self.assertIn("try {", js[max(0, i - 160):i], "localStorage buiten try")
        self.assertIn("werkt ? T.apparaat : T.geen_opslag", js)
        self.assertTrue(bd.BEWAAR_TEKST["geen_opslag"])

    def test_uitloggen_wist_niets(self):
        # Crit. 9: bewaard en verborgen horen bij het apparaat. Niets in de pagina wist de opslag.
        self.assertNotIn("localStorage.clear", bd.TEMPLATE)
        self.assertNotIn("removeItem(SLEUTEL)", bd.TEMPLATE)


class Gebouwd(unittest.TestCase):
    """De payload: elke lead draagt pandcategorie en datapeildatum alleen als die afwijken."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)
        for p in (mock.patch.object(bd, "DATA", self.map), mock.patch.object(bd, "load_config", cfg)):
            p.start()
            self.addCleanup(p.stop)

    def bouw(self, werklijst):
        (self.map / "panden_nederland.json").write_text(json.dumps(
            {"gebied": "Nederland", "totalen": TOTALEN, "werklijst": werklijst, "proef": werklijst[:20]}), encoding="utf-8")
        (self.map / "panden_nederland.bron.json").write_text(json.dumps(
            [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]), encoding="utf-8")
        html = bd.render(bd.bouw_payload())
        return html, payload_uit(html)

    def test_afwijking_gaat_mee(self):
        lijst = [pand(1, "Amsterdam"), pand(2, "Amsterdam"),
                 dict(pand(3, "Amsterdam"), pandcategorie="E", categorieen=["C", "E"], datapeildatum="2026-10-01")]
        _, p = self.bouw(lijst)
        self.assertEqual(p["bewaar"]["dp"], "2026-11-01")
        self.assertEqual(p["bewaar"]["tekst"], bd.BEWAAR_TEKST)
        self.assertEqual([("pc" in l, "dp" in l) for l in p["leads"]], [(False, False), (False, False), (True, True)])
        self.assertEqual((p["leads"][2]["pc"], p["leads"][2]["dp"]), ("E", "2026-10-01"))

    def test_geen_cijfer_verandert(self):
        # Crit. 10: de knoppen zitten alleen in het script; de cijfers, de werklijst-telling en de kaart komen uit dezelfde payload.
        html, p = self.bouw([pand(1, "Amsterdam"), pand(2, "Amsterdam")])
        self.assertEqual([k["v"] for k in p["kpi"]], ["9.998.456", "6.568.913", "441.997", "263.319"])
        t = bd.TEMPLATE
        # De kerncijfers, de categoriebalken, de feiten, de landkaart en het kantoor lezen niets van VA-90.
        cijfers = t[t.index('const kb=document.getElementById("kpis");'):t.index('const fb=document.getElementById("facts");')]
        kaart = t[t.index("/* ============================ LANDKAART (VA-85)"):t.index("/* ===================== einde LANDKAART")]
        kantoor = t[t.index("const PK = (() => {"):]
        for deel in (cijfers, kaart, kantoor):
            self.assertNotIn("BW.", deel)
        self.assertIn('"werklijst.meta"', json.dumps(p["koppen"]))  # de eigen telling van de werklijst
        self.assertTrue(p["koppen"]["werklijst.meta"].startswith("2 panden"))

    def test_stad_krijgt_de_knoppen_ook(self):
        html = bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                          "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})
        self.assertEqual(payload_uit(html)["bewaar"]["tekst"], bd.BEWAAR_TEKST)
        self.assertIn('id="bwBalk"', html)


class Kopij(unittest.TestCase):
    def test_nederlands_zonder_snapshot_of_engels(self):
        for t in bd.BEWAAR_TEKST.values():
            self.assertNotRegex(t.lower(), r"snapshot|\bsave\b|\bhide\b|\bundo\b|\bshow\b|\blive\b|\bonline\b")
        self.assertEqual(bd.BEWAAR_TEKST["bewaar"], "Bewaar")      # Aymans woorden
        self.assertEqual(bd.BEWAAR_TEKST["verberg"], "Verberg")
        self.assertEqual(bd.BEWAAR_TEKST["ongedaan"], "Ongedaan maken")   # de woorden van het verhaal
        self.assertIn("alleen op dit apparaat", bd.BEWAAR_TEKST["apparaat"])

    def test_script_maakt_geen_zinnen(self):
        # Alleen de code, niet het commentaar: elke zin komt uit PAYLOAD.bewaar.tekst.
        js = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", blok(), flags=re.S))
        for t in bd.BEWAAR_TEKST.values():
            if len(t) > 12:
                self.assertNotIn(t, js)


if __name__ == "__main__":
    unittest.main()
