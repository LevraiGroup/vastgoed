"""
VA-64: het menu van het dashboard (ontwerp VA-63, Lumi). Wat zonder browser te controleren is:
elk menu-item wijst naar een deel dat op de gebouwde pagina staat (criterium 4), het kantoor
is het eerste deel, de werkbalk heeft vijf knoppen met de Kantoormanager als laatste
(criterium 14), de koppen komen uit Python, en de lade, de hoogte en de overgangen volgen
Lumi's bouwnotities. Geen data nodig, behalve de ene test op de echte pagina (die wordt
overgeslagen zonder data/panden_delft.json).
"""
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402

DELFT_PANDEN = bd.DATA / "panden_delft.json"
CFG = {"drempels": {"score_min_voor_werklijst": 8, "werklijst_min": 1, "werklijst_max": 500},
       "bronnen": {}}


class Pagina(HTMLParser):
    """Verzamelt ids, links naar '#...', de menu-items, de delen en de werkbalkknoppen."""

    def __init__(self, html):
        super().__init__()
        self.ids, self.hrefs, self.menu, self.delen, self.knoppen = [], [], [], [], []
        self._in_nav = self._in_main = False
        self._knop = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "nav":
            self._in_nav = True
        if tag == "main":
            self._in_main = True
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.hrefs.append(a["href"])
            if self._in_nav:
                self.menu.append(a)
        if tag == "section" and "deel" in (a.get("class") or "").split() and self._in_main:
            self.delen.append(a)
        if tag == "button" and "pk-knop" in (a.get("class") or "").split():
            self._knop = dict(a, tekst=[])
            self.knoppen.append(self._knop)

    def handle_endtag(self, tag):
        if tag == "nav":
            self._in_nav = False
        if tag == "button":
            self._knop = None

    def handle_data(self, data):
        if self._knop is not None:
            self._knop["tekst"].append(data)


def kapotte_links(html):
    """Elke href="#x" op de pagina waarvoor geen element met id x bestaat."""
    p = Pagina(html)
    return [h for h in p.hrefs if h[1:] not in p.ids]


def gebouwd(panden=None, n_leads=20):
    """Een pagina zoals render() hem maakt, zonder data/ (het kleinste geldige payload)."""
    bron = [{"woonplaats": "Delft", "bestand": "vbo_delft.json", "ophaaldatum": "2026-08-04"}]
    panden = panden if panden is not None else [
        {"uitgesloten": False, "categorieen": ["A"], "leadscore": 12, "aantal_vbo": 3}]
    return bd.render({"gebied": "Delft", "bron": bron, "peildatum": bd.peildatum(bron),
                      "peildatum_tip": bd.peildatum_tip(bron),
                      "kantoor": bd.kantoor("Delft", bron, panden, n_leads, CFG),
                      "koppen": bd.koppen("Delft", 8, n_leads), "leads": []})


class MenuWijstNaarDelen(unittest.TestCase):
    """Criterium 4 (en 2): geen item voor een deel dat de pagina niet heeft."""

    def test_elk_menu_item_wijst_naar_een_id_op_de_pagina(self):
        html = gebouwd()
        p = Pagina(html)
        self.assertEqual([a["href"] for a in p.menu],
                         ["#kantoor", "#kerncijfers", "#voorraad", "#proefresultaat"])
        self.assertEqual(kapotte_links(html), [])  # ook "Sla het menu over" -> #inhoud

    def test_menu_en_delen_zijn_dezelfde(self):
        p = Pagina(gebouwd())
        self.assertEqual([a["href"][1:] for a in p.menu], [d["id"] for d in p.delen])
        for a in p.menu:
            self.assertEqual(a["href"], "#" + a["data-doel"])

    def test_de_test_wordt_rood_bij_een_item_zonder_deel(self):
        # Een item dat er nog niet is (Werklijst komt met VA-17) moet de controle laten falen.
        extra = [dict(bd.MENU[0]), dict(bd.MENU[1], items=bd.MENU[1]["items"] + [("werklijst", "Werklijst")])]
        with mock.patch.object(bd, "MENU", extra):
            self.assertEqual(kapotte_links(gebouwd()), ["#werklijst"])

    def test_precies_een_item_actief_bij_het_laden(self):
        p = Pagina(gebouwd())
        actief = [a["href"] for a in p.menu if a.get("aria-current") == "location"]
        self.assertEqual(actief, ["#kantoor"])

    def test_groepen_en_namen_uit_de_kopijtabel(self):
        self.assertEqual([(g["groep"], [n for _, n in g["items"]]) for g in bd.MENU],
                         [("Overzicht", ["Kantoor", "Kerncijfers"]),
                          ("Panden", ["Voorraad", "Proefresultaat"])])


class KantoorBovenaan(unittest.TestCase):
    """Criterium 3: het kantoor is het eerste deel en niets in de pagina verbergt het."""

    def test_eerste_deel_is_het_kantoor(self):
        p = Pagina(gebouwd())
        self.assertEqual(p.delen[0]["id"], "kantoor")
        self.assertNotIn("hidden", p.delen[0])

    def test_het_menu_raakt_het_kantoor_niet_aan(self):
        t = bd.TEMPLATE
        menu = t[t.index("/* ============================ MENU (VA-63, VA-64)"):
                 t.index("/* ============================ einde MENU")]
        for weg in ('getElementById("pk")', "#pk", ".pk", '"kantoor"', ".hidden", "display",
                    "removeChild", "replaceWith"):
            self.assertNotIn(weg, menu)


class Werkbalk(unittest.TestCase):
    """Criteria 5 en 14: vier genummerde medewerkers, de Kantoormanager zonder nummer als laatste."""

    def test_vijf_knoppen_in_volgorde(self):
        p = Pagina(gebouwd())
        self.assertEqual([k["data-wie"] for k in p.knoppen],
                         ["ingest", "selectie", "verrijking", "controle", "chef"])
        namen = [k["tekst"][1] if k["data-wie"] != "chef" else k["tekst"][0] for k in p.knoppen]
        self.assertEqual(namen, ["Ingest", "Selectie", "Verrijking", "Controle", "Kantoormanager"])
        self.assertEqual([k["tekst"][0] for k in p.knoppen[:4]], ["1", "2", "3", "4"])

    def test_elke_knop_opent_de_uitleg(self):
        p = Pagina(gebouwd())
        self.assertIn("pk-uitleg", p.ids)
        for k in p.knoppen:
            self.assertEqual(k["aria-controls"], "pk-uitleg")
            self.assertEqual(k["aria-expanded"], "false")
            self.assertEqual(k["type"], "button")

    def test_toestand_en_regel_uit_kantoor_teksten(self):
        bron = [{"woonplaats": "Delft", "bestand": "vbo_delft.json", "ophaaldatum": "2026-08-04"}]
        tekst = bd.kantoor("Delft", bron, [{"uitgesloten": False, "categorieen": ["A"],
                                            "leadscore": 12, "aantal_vbo": 3}], 20, CFG)["tekst"]
        knoppen = bd.werkbalk_knoppen(tekst)
        for k in knoppen[:4]:
            self.assertEqual((k["s"], k["bel"]), (tekst[k["wie"]]["s"], tekst[k["wie"]]["bel"]))
        self.assertEqual(knoppen[-1], {"wie": "chef", "nr": "", "naam": "Kantoormanager", "s": "chef",
                                       "bel": tekst["chef"]["zin"]})

    def test_zonder_tekstblok_onbekend(self):
        knoppen = bd.werkbalk_knoppen(None)
        self.assertEqual({k["s"] for k in knoppen[:4]}, {"leeg"})
        self.assertEqual({k["bel"] for k in knoppen}, {"onbekend"})
        self.assertNotIn("__WERKBALK__", bd.render({"gebied": "Delft", "bron": None,
                                                    "peildatum": "Peildatum onbekend",
                                                    "peildatum_tip": ""}))

    def test_beide_kantoren_haken_aan_op_de_balk(self):
        t = bd.TEMPLATE
        self.assertNotIn('className = "pk-lijst"', t)  # de oude lijst wordt niet meer gebouwd
        self.assertNotIn(".pk-lijst{", t)
        self.assertIn('balk.querySelector(`.pk-knop[data-wie="${a.id}"]`)', t)  # 3D, met de chef
        self.assertIn('root.querySelectorAll(".pk-balk .pk-knop")', t)        # 2D, zonder chef


class Koppen(unittest.TestCase):
    """De titels met {gebied}, {drempel} en {n} komen uit Python (LESSONS, VA-31)."""

    def test_teksten(self):
        k = bd.koppen("Delft", 8, 20)
        self.assertEqual(k["kerncijfers.titel"], "Delft in vier cijfers")
        self.assertEqual(k["kerncijfers.zin"],
                         "Van de ingelezen verblijfsobjecten tot de werklijst met score 8 of hoger.")
        self.assertEqual(k["proefresultaat.titel"], "De 20 hoogst scorende panden")
        self.assertEqual(k["proefresultaat.meta"], "20 panden · Delft · gesorteerd op score-index")
        self.assertIn("wat de 20 panden van de proef", k["voorraad.zin"])

    def test_onbekend_blijft_onbekend(self):
        k = bd.koppen("Delft", None, None)
        self.assertIn("score onbekend of hoger", k["kerncijfers.zin"])
        self.assertEqual(k["proefresultaat.titel"], "De onbekend hoogst scorende panden")

    def test_geen_sjabloonplek_blijft_over(self):
        html = gebouwd()
        self.assertEqual(re.findall(r"__[A-Z][A-Z0-9_]*__", html), [])
        self.assertIn('<h1 id="t-kantoor">Zo loopt de pandenselectie</h1>', html)
        self.assertIn('id="secmeta">20 panden · Delft · gesorteerd op score-index</span>', html)

    def test_het_script_maakt_de_meta_niet_meer(self):
        self.assertNotIn("gesorteerd op score-index", bd.TEMPLATE)

    def test_nederlands_zonder_snapshot(self):
        teksten = list(bd.KOP_TEKST.values()) + [g["groep"] for g in bd.MENU] + \
            [n for g in bd.MENU for _, n in g["items"]]
        for vast in ("Sla het menu over", "Sluit menu", "Onderdelen van het dashboard",
                     "Uitleg per medewerker", "Levrai Vastgoed"):
            self.assertIn(vast, bd.TEMPLATE)
            teksten.append(vast)
        for t in teksten:
            self.assertNotRegex(t.lower(), r"snapshot|\bmenu item\b|\boverview\b|\bclose\b")


class LadeEnMaat(unittest.TestCase):
    """Lumi's bouwnotities die in de bron te controleren zijn; het gedrag zelf vraagt een browser."""

    def test_hoogte_van_het_kantoor_begrensd(self):
        t = bd.TEMPLATE
        self.assertIn("@media (min-width:801px){ .pk-scene.pk-start,.pk-scene.pk-3d{max-height:calc(100vh - 270px)} }", t)
        # width:100%: anders geeft aspect-ratio de max-height door aan de breedte (headless Chrome
        # mat bij 1262 x 704 een scène van 629 px breed in een kantoor van 958 px).
        self.assertIn(".pk-scene.pk-start,.pk-scene.pk-3d{width:100%;aspect-ratio:1.45/1;min-height:240px;", t)

    def test_overgangen_pas_na_klaar_en_nooit_all(self):
        t = bd.TEMPLATE
        self.assertNotRegex(t.replace(" ", ""), r"transition:all")
        css = t[t.index("<style>"):t.index("</style>")]
        for regel in re.findall(r"[^{}]*\{[^{}]*transition:[^}]*\}", css):
            kiezer = regel.split("{")[0]
            if ".side" in kiezer or ".scrim" in kiezer or ".nav a" in kiezer:
                self.assertIn(".klaar", kiezer, regel.strip())
        self.assertIn('requestAnimationFrame(() => requestAnimationFrame(() => vg.classList.add("klaar")))', t)

    def test_lade_breekpunt_en_toetsen(self):
        t = bd.TEMPLATE
        self.assertIn("@media (max-width:800px){", t)
        self.assertIn('matchMedia("(max-width: 800px)")', t)
        self.assertIn("main.inert = true", t)
        self.assertIn('if (e.key !== "Tab" || !isOpen()) return;', t)
        self.assertIn("if (terug) knop.focus();", t)
        self.assertIn('if (e.key !== "Escape" || !isOpen()) return;', t)

    def test_rustige_beweging(self):
        t = bd.TEMPLATE
        blok = t[t.index("@media (prefers-reduced-motion: reduce){\n    .vg.klaar"):]
        blok = blok[:blok.index("}\n  }") + 1]
        for kiezer in (".vg.klaar .nav a", ".vg.klaar .side", ".vg.klaar .scrim", ".pk-knop"):
            self.assertIn(kiezer, blok)
        self.assertIn("@media (prefers-reduced-motion: no-preference){ html{scroll-behavior:smooth} }", t)

    def test_navy_zijbalk_in_licht(self):
        # Criterium 11: de zijbalk (en op smal de bovenbalk en lade) is --brand, in licht #12233b.
        t = bd.TEMPLATE
        licht = t[t.index(":root{"):t.index("}", t.index(":root{"))]
        self.assertIn("--brand:#12233b", licht)
        self.assertRegex(t, r"\.side\{[^}]*background:var\(--brand\)")
        self.assertRegex(t, r"\.topbalk\{[^}]*background:var\(--brand\)")

    def test_de_foto_markering_van_een_pand_blijft_los_van_het_merk(self):
        # .merk bestaat ook in de pandweergave (VA-62, de rode stip op de luchtfoto).
        self.assertNotRegex(bd.TEMPLATE, r"\n\s*\.merk\{")


@unittest.skipUnless(DELFT_PANDEN.is_file(), f"{DELFT_PANDEN} ontbreekt; echte pagina overgeslagen")
class EchtePagina(unittest.TestCase):
    def test_gebouwde_pagina(self):
        html = bd.render(bd.bouw_payload())
        p = Pagina(html)
        self.assertEqual(kapotte_links(html), [])
        self.assertEqual([a["href"][1:] for a in p.menu], [d["id"] for d in p.delen])
        self.assertEqual(len(p.knoppen), 5)
        self.assertEqual(len(set(p.ids)), len(p.ids), "dubbele ids")


if __name__ == "__main__":
    unittest.main()
