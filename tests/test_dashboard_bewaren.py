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
        # Bewaard: een volle ster; Verborgen: een gestippeld oog (Lumi, knoppen-spec.md).
        self.assertIn('const naam = soort === "bewaard" ? (aan ? "ster_vol" : "ster") : (aan ? "oog_uit" : "oog")', js)
        self.assertIn('.bw-knop.bw-weg[aria-pressed="true"]{border:1px dashed var(--ink-2);', css)
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
        past = w[w.index("function past(d, behalve, alle) {"):]
        self.assertTrue(past.split("\n")[1].strip().startswith("if (!alle && !BW.zichtbaar(d.id)) return false;"))
        # Alleen het lege vak telt de verborgen panden mee ('alle'); de telling en de kaarten nooit.
        self.assertEqual(w.count("past(d, null, true)"), 1)
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
        w = werklijst()
        self.assertIn("const alles = houd => { const r = LEADS.filter(d => BW.zichtbaar(d.id));", w)
        self.assertIn("lb.hidden = !r.length; teken(r, houd); };", w)
        self.assertIn("BW.leeg(vak, r.length ? 0 : LEADS.length, false)", w)   # een stad heeft geen filters


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


class LegeWerklijst(unittest.TestCase):
    """Lumi §7: een lege werklijst zegt of de filters of Verberg de oorzaak zijn, met de goede knop."""

    def test_drie_gevallen(self):
        js, w = blok(), werklijst()
        # m: de panden die de filters halen, verborgen meegeteld; 0 als de lijst niet door Verberg leeg is.
        self.assertIn("BW.leeg(leeg, n ? 0 : LEADS.filter(d => past(d, null, true)).length, a > 0);", w)
        lg = js[js.index("function leeg(vak, m, filters) {"):js.index("const ongedaanVoor")]
        # 1. de filters zelf vinden niets: de zin van de filters blijft (LIJST_TEKST['leeg']) en Wis alle filters
        self.assertIn("if (!m) { p.textContent = vak.dataset.zin; if (b) b.remove(); return; }", lg)
        # 2. filters actief, alles verborgen: enkelvoud bij 1; 3. geen filter: alle panden verborgen, geen Wis
        self.assertIn('p.textContent = !filters ? T["leeg.alles_verborgen"].replace("{totaal}", nl(m))', lg)
        self.assertIn(': m === 1 ? T["leeg.verborgen.een"] : T["leeg.verborgen"].replace("{m}", nl(m));', lg)
        self.assertIn("if (wis) wis.hidden = !!m && !filters;", lg)
        # De knop in het vak doet wat de balkknop doet, met dezelfde sleutels; daarna de focus op de balkknop.
        self.assertIn('b.textContent = T[m === 1 ? "toon.een" : "toon"];', lg)
        self.assertIn('tonen = true; overal(true); el("bwToon").focus();', lg)

    def test_teksten(self):
        t = bd.BEWAAR_TEKST
        self.assertEqual(t["leeg.verborgen"], "Je hebt alle {m} panden verborgen die bij deze filters passen.")
        self.assertEqual(t["leeg.verborgen.een"], "Het enige pand dat bij deze filters past, heb je verborgen.")
        self.assertEqual(t["leeg.alles_verborgen"],
                         "Je hebt alle {totaal} panden van de werklijst van deze maand verborgen.")
        # De zin van de filters zelf is niet veranderd (geval 1).
        self.assertTrue(bd.LIJST_TEKST["leeg"].startswith("Geen enkel pand op de werklijst van deze maand past"))


class Toegankelijk(unittest.TestCase):
    """Lumi §1 t/m §4: namen in aria-label, tekens verborgen voor de schermlezer, een lege status in de boom."""

    def test_namen_per_stand(self):
        js = blok()
        self.assertNotIn(" · ", js)   # geen middenpunt meer in de naam
        self.assertIn('b.setAttribute("aria-label", T["naam." + (aan ? soort : soort === "bewaard" ? "bewaar" : "verberg")]'
                      '.replace("{adres}", () => adres(d)));', js)
        self.assertIn('b.setAttribute("aria-pressed", String(aan));', js)   # de knoppen per pand houden aria-pressed
        for k in ("bewaar", "bewaard", "verberg", "verborgen"):   # de naam begint met de zichtbare tekst (WCAG 2.5.3)
            zichtbaar = bd.BEWAAR_TEKST[k if k in ("bewaar", "verberg") else "label." + k]
            self.assertTrue(bd.BEWAAR_TEKST["naam." + k].startswith(zichtbaar), k)

    def test_tekens_niet_voorgelezen(self):
        js = blok()
        self.assertIn('const i = icoon(s === "bewaard" ? "ster_vol" : "oog_uit", "bw-label-ico");'
                      '   // dezelfde iconen als de knop\n'
                      '        l.append(i, s === "verborgen" ? D["label.verborgen"].replace("{datum}", () => datum(stand[d.id]))'
                      ' : T["label." + s]);', js)
        self.assertNotIn('"★ "', js)
        self.assertIn('const ico = icoon(soort === "bewaard" ? "ster" : "oog", "bw-ico");', js)
        # Elk icoon is een SVG die de schermlezer overslaat en die geen focus krijgt.
        self.assertIn('s.setAttribute("aria-hidden", "true");', js)
        self.assertIn('s.setAttribute("focusable", "false");', js)
        for teken in ("★", "☆", "◌", "⊘"):
            self.assertNotIn(teken, js)

    def test_toon_knop_zonder_aria_pressed(self):
        js = blok()
        self.assertIn('<button class="bw-toon" id="bwToon" type="button" hidden></button>', bd.TEMPLATE)
        balk = js[js.index("function werkBalk() {"):js.index("function leeg(")]
        self.assertNotIn("aria-pressed", re.sub(r"//[^\n]*", "", balk))   # alleen de code, niet het commentaar
        self.assertIn('T[(tonen ? "toon.uit" : "toon") + (n === 1 ? ".een" : "")]', balk)
        self.assertIn('toon.classList.toggle("aan", tonen);', balk)
        self.assertIn(".bw-toon.aan{", bd.TEMPLATE)
        self.assertNotIn(".bw-toon[aria-pressed", bd.TEMPLATE)

    def test_ongedaan_maken_beschreven_door_zijn_zin(self):
        js = blok()
        self.assertIn('const zin = maak("span", null, tekst); zin.id = doel.id + "-zin";', js)
        self.assertIn('b.setAttribute("aria-describedby", zin.id);', js)
        self.assertIn('s.id = "pandBwStatus";', js)   # de statusregel in 'Open pand' heeft ook een id

    def test_lege_status_blijft_in_de_boom(self):
        self.assertNotIn(".bw-status:empty{display:none}", bd.TEMPLATE)
        self.assertNotRegex(bd.TEMPLATE, r"\.bw-status[^{]*\{[^}]*display:\s*none")


class FocusNaSluiten(unittest.TestCase):
    """Criterium 13, VA-61 en Lumi §8: sluit 'Open pand' en is de kaart weg, dan nooit de focus op <body>."""

    def sluit(self):
        t = bd.TEMPLATE
        i = t.index('pandDlg.addEventListener("close", () => {')
        return t[i:t.index("});", i)]

    def test_volgorde(self):
        s = self.sluit()
        kaart = s.index("if (pandOpener && pandOpener.isConnected) { pandOpener.focus(); return; }")
        ongedaan = s.index("if (pandId != null) BW.naSluiten(pandId).focus();")
        self.assertLess(kaart, ongedaan)   # eerst de kaart (VA-61), dan Ongedaan maken, dan de werklijst
        self.assertIn("pandOpener = opener; pandId = d.id;", bd.TEMPLATE)

    def test_ongedaan_maken_alleen_van_dit_pand(self):
        js = blok()
        self.assertIn('const b = el("bwStatus") && el("bwStatus").querySelector(".bw-ongedaan");', js)
        self.assertIn("return b && b.dataset.pand === String(id) ? b : null; };", js)
        self.assertIn("b.dataset.pand = id;", js)
        self.assertIn('const ongedaan = status(el("bwStatus"), tekst, terug, d.id);', js)
        self.assertIn("if (inPand) status(dlg.s, tekst, terug, d.id);", js)

    def test_ongedaan_maken_na_sluiten(self):
        # Na het sluiten staan de knoppen van 'Open pand' nog in de pagina (isConnected), maar ze kunnen geen
        # focus krijgen. Ongedaan maken boven de werklijst kiest dan de kaart, en anders de werklijst.
        js = blok()
        self.assertIn('const ziet = x => x && x.isConnected && (!x.closest("dialog") || x.closest("dialog").open);', js)
        self.assertIn("const k = [inPand ? dlg.r : null, rijen.get(d.id)].find(ziet);", js)
        self.assertIn('(f || lijstDeel()).focus(); };', js)

    def test_terugval_is_de_werklijst(self):
        js = blok()
        self.assertIn('const lijstDeel = () => (balk && balk.closest("section")) || el("inhoud");', js)
        # De sectie van de werklijst en de inhoud kunnen focus krijgen.
        self.assertIn('<section class="deel" id="__LIJST__" aria-labelledby="t-__LIJST__" tabindex="-1">', bd.TEMPLATE)
        self.assertIn('<main class="inhoud" id="inhoud" tabindex="-1">', bd.TEMPLATE)
        self.assertIn("return {rij, ververs: werkRij, zichtbaar, aantalWeg, op: f => luisteraars.push(f), van, leeg, "
                      "ongedaanVoor, lijstDeel,", js)
        # VA-91: na het sluiten eerst Ongedaan maken van dit pand, dan de werklijst (of, vanaf Bewaarde panden, dat deel).
        self.assertIn("if (!vanB) return ongedaanVoor(id) || lijstDeel();", js)


class GlazenDuo(unittest.TestCase):
    """Lumi's variant A (knoppen-spec.md): één glazen strook, 44px doelen, iconen in SVG, --glans per thema."""

    def css(self):
        t = bd.TEMPLATE
        i = t.index("/* ===================== BEWAREN EN VERBERGEN (VA-90)")
        return t[i:t.index("/* ===================== einde BEWAREN EN VERBERGEN", i)]

    def test_strook_en_doelen(self):
        css = self.css()
        self.assertIn(".bw-rij{display:flex;gap:0;", css)
        self.assertIn("box-shadow:inset 0 1px 0 var(--glans)}", css)
        self.assertRegex(css, r"\.bw-knop\{flex:1 1 0;[^}]*min-height:44px")   # gelijke helften, minstens 44px hoog
        self.assertIn(".bw-knop:focus-visible{outline:2px solid var(--s1);outline-offset:2px;z-index:1}", css)
        self.assertIn(".pand-bw .bw-rij{max-width:420px}", css)

    def test_bewaard_is_het_glas_van_de_band(self):
        css = self.css()
        self.assertIn('.bw-knop.bw-bewaar[aria-pressed="true"]{background:var(--held);color:#fff;', css)
        self.assertIn('.bw-knop.bw-bewaar[aria-pressed="true"] .bw-ico{color:var(--s4);', css)

    def test_glans_per_thema(self):
        t = bd.TEMPLATE
        self.assertIn("--glans:rgba(255,255,255,.75);", t)
        self.assertEqual(t.count("--glans:rgba(255,255,255,.06)"), 2)   # donker: systeem en de themaknop

    def test_minder_beweging(self):
        self.assertIn("@media (prefers-reduced-motion: reduce){ .bw-knop{transition:none} .bw-knop:active{transform:none} }",
                      self.css())

    def test_vier_iconen_en_niets_van_buiten(self):
        js = blok()
        self.assertIn('const SVG = "http://www.w3.org/2000/svg"', js)
        for naam in ("ster:", "ster_vol:", "oog:", "oog_uit:"):
            self.assertIn(naam, js)
        self.assertEqual(re.findall(r"https?://[^\s\"']+", js), ["http://www.w3.org/2000/svg"])   # alleen de naamruimte
        self.assertNotRegex(js, r"<use|xlink|url\(")


class Kopij(unittest.TestCase):
    def test_alles_uit_lumis_tabel(self):
        # Elke zin staat letterlijk in Lumi's kopijtabel (design/copy-va90.md). De pagina Bewaarde panden en het
        # vervolg op status.bewaard zijn van VA-91 (design/copy-va91.md), en die pint test_dashboard_bewaard.py
        # op de kolom GOEDGEKEURD.
        tabel = (HIER.parent / "design" / "copy-va90.md").read_text(encoding="utf-8")
        for k, t in bd.BEWAAR_TEKST.items():
            if k.startswith("pagina.") or k == "status.bewaard":
                continue
            self.assertIn(t, tabel, k)
        t = bd.BEWAAR_TEKST
        self.assertEqual(t["terug.bewaard"], "Druk om niet meer te bewaren")
        self.assertEqual(t["terug.verborgen"], "Druk om weer te tonen")
        self.assertEqual(t["naam.bewaard"], "Bewaard, druk om niet meer te bewaren: {adres}")
        self.assertEqual(t["naam.verborgen"], "Verborgen, druk om weer te tonen: {adres}")
        self.assertEqual(t["toon.een"], "Toon het verborgen pand")
        self.assertEqual(t["toon.uit.een"], "Verberg het weer")
        self.assertEqual(t["apparaat.kort"], "Alleen op dit apparaat, in deze browser. Een ander apparaat ziet het niet.")
        self.assertNotIn("Collega's zien het niet", t["apparaat"])

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
