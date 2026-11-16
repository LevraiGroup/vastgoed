"""
VA-91: de pagina Bewaarde panden in het menu links, met elk pand dat in deze browser bewaard is, ook als het
niet meer in de werklijst staat. Het gedrag zelf vraagt een browser (de close-out); hier staat wat in de bron
en in de gebouwde pagina te controleren is: criterium 1 (menu en deel), 2 (alleen bewaard, nieuwste eerst, met
adres, woonplaats, score, categorie en datum in het formaat van het dashboard), 3 (een pand in de data opent
'Open pand', een pand dat er niet meer in staat toont wat is opgeslagen), 6 (de telling in het menu) en de kopij.
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
from test_dashboard_bewaren import blok, payload_uit  # noqa: E402
from test_dashboard_menu import Pagina, kapotte_links  # noqa: E402
from test_dashboard_nederland import TOTALEN, cfg, pand  # noqa: E402

KOPIJ = HIER.parent / "design" / "copy-va91.md"


def pagina_js(t=bd.TEMPLATE):
    """Het script van VA-91."""
    i = t.index("/* ============================ BEWAARDE PANDEN (VA-91)")
    return t[i:t.index("/* ============================ einde BEWAARDE PANDEN", i)]


def goedgekeurd(tekst):
    """
    {sleutel: tekst} uit de kolom GOEDGEKEURD van Lumi's tabellen: de eerste `sleutel` in de eerste kolom,
    en de tweede kolom als die helemaal tussen backticks staat. Andere kolommen tellen niet mee.
    """
    uit = {}
    for regel in tekst.splitlines():
        if not regel.startswith("| `"):
            continue
        cellen = [c.strip() for c in regel.strip().strip("|").split(" | ")]
        sleutel = re.match(r"`([^`]+)`", cellen[0])
        waarde = re.fullmatch(r"`([^`]+)`", cellen[1]) if len(cellen) > 1 else None
        if sleutel and waarde:
            uit[sleutel.group(1)] = waarde.group(1)
    return uit


class Kopij(unittest.TestCase):
    """Criterium 8: alle tekst uit Lumi's tabel, kolom GOEDGEKEURD; Nederlands, geen 'snapshot', geen Engels."""

    def test_letterlijk_uit_de_kolom_goedgekeurd(self):
        tabel = goedgekeurd(KOPIJ.read_text(encoding="utf-8"))
        nieuw = [k for k in bd.BEWAAR_TEKST if k.startswith("pagina.")] + ["status.bewaard"]
        self.assertEqual(len(nieuw), 19)   # 18 pagina.* en status.bewaard (Lumi §8)
        for k in nieuw:
            self.assertIn(k, tabel, k)
            self.assertEqual(bd.BEWAAR_TEKST[k], tabel[k], k)

    def test_de_pin_vangt_een_afwijking(self):
        # Vera, VA-90: een pin die alleen 'staat ergens in het bestand' controleert, laat een oude zin door.
        # Deze vergelijkt per sleutel met de goedgekeurde kolom: de oude status.bewaard van VA-90 haalt het niet.
        tabel = goedgekeurd(KOPIJ.read_text(encoding="utf-8"))
        self.assertNotEqual("{adres} is bewaard.", tabel["status.bewaard"])
        self.assertIn("{adres} is bewaard.", KOPIJ.read_text(encoding="utf-8"))   # wel ergens in het bestand

    def test_menu_naam_uit_de_tabel(self):
        self.assertEqual(bd.BEWAARD, ("bewaard", "Bewaarde panden"))
        self.assertIn('`("bewaard", "Bewaarde panden")`', KOPIJ.read_text(encoding="utf-8"))

    def test_nederlands_zonder_snapshot_of_engels(self):
        for k, t in bd.BEWAAR_TEKST.items():
            self.assertNotRegex(t.lower(), r"snapshot|\bsave\b|\bsaved\b|\bundo\b|\bshow\b|\bpage\b", k)

    def test_script_maakt_geen_zinnen(self):
        js = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", pagina_js(), flags=re.S))
        for t in bd.BEWAAR_TEKST.values():
            if len(t) > 12:
                self.assertNotIn(t, js)
        for woord in ("Bewaarde panden", "Niet in deze werklijst", "Bewaard op"):
            self.assertNotIn(woord, js)


class Menu(unittest.TestCase):
    """Criterium 1: één nieuw item in de groep Panden, met zijn eigen deel; alleen in de landelijke bouw."""

    def test_volgorde_in_de_groep(self):
        panden = bd.menu_voor("werklijst")[1]
        self.assertEqual(panden["items"], [("voorraad", "Voorraad"), ("bewaard", "Bewaarde panden"),
                                           ("werklijst", "Werklijst")])
        self.assertIs(bd.menu_voor("proefresultaat"), bd.MENU)   # de stadsbouw: geen woorden van Lumi voor dat deel

    def test_telling_in_het_menu(self):
        html = bd.menu_html("werklijst")
        item = re.search(r'<a href="#bewaard" data-doel="bewaard">(.*?)</a>', html).group(1)
        self.assertEqual(item, 'Bewaarde panden<span class="vh" id="bwpMenuSr"></span>'
                               '<span class="nav-n" id="bwpMenuN" aria-hidden="true" hidden></span>')
        self.assertNotIn("bwpMenu", bd.menu_html("proefresultaat"))
        js = pagina_js()
        # Criterium 6: de telling volgt elke verandering, zonder herladen; bij 0 geen pil.
        self.assertIn("BW.opAlles(ververs);", js)
        self.assertIn('menuN.hidden = !n; menuN.textContent = n ? vul(T["pagina.menu.n"], {n: nl(n)}) : "";', js)
        self.assertIn('menuSr.textContent = n ? vul(T["pagina.menu.n.sr"], {n: nl(n)}) : "";', js)
        self.assertIn("alleLuisteraars.forEach(f => f()); }", blok())   # na elke bewaar, verberg, ongedaan en storage
        self.assertIn(".nav a .nav-n{margin-left:auto;", bd.TEMPLATE)

    def test_deel_tussen_voorraad_en_werklijst(self):
        html = bd.bewaard_html("werklijst")
        self.assertIn('<section class="deel" id="bewaard" aria-labelledby="t-bewaard" tabindex="-1">', html)
        self.assertIn('<h2 class="titel" id="t-bewaard">Bewaarde panden</h2>', html)
        self.assertIn('<div class="bw-status" id="bwBewaardStatus" role="status"></div>', html)
        self.assertEqual(bd.bewaard_html("proefresultaat"), "")
        t = bd.TEMPLATE
        self.assertLess(t.index('id="voorraad"'), t.index("__BEWAARD__"))
        self.assertLess(t.index("__BEWAARD__"), t.index('id="__LIJST__"'))


class Gebouwd(unittest.TestCase):
    """De landelijke pagina zoals render() hem maakt, op een kleine werklijst."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)
        for p in (mock.patch.object(bd, "DATA", self.map), mock.patch.object(bd, "load_config", cfg)):
            p.start()
            self.addCleanup(p.stop)
        lijst = [pand(1, "Amsterdam"), pand(2, "Utrecht")]
        (self.map / "panden_nederland.json").write_text(json.dumps(
            {"gebied": "Nederland", "totalen": TOTALEN, "werklijst": lijst, "proef": lijst}), encoding="utf-8")
        (self.map / "panden_nederland.bron.json").write_text(json.dumps(
            [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]),
            encoding="utf-8")
        self.html = bd.render(bd.bouw_payload())

    def test_menu_en_delen_kloppen(self):
        p = Pagina(self.html)
        self.assertEqual(kapotte_links(self.html), [])
        self.assertEqual([a["href"][1:] for a in p.menu], [d["id"] for d in p.delen])
        self.assertEqual([d["id"] for d in p.delen], ["kantoor", "kerncijfers", "voorraad", "bewaard", "werklijst"])
        self.assertEqual(len(set(p.ids)), len(p.ids), "dubbele ids")
        self.assertEqual(re.findall(r"__[A-Z][A-Z0-9_]*__", self.html), [])

    def test_maanden_van_het_dashboard_in_de_payload(self):
        # Criterium 2: de datum in het formaat van nl_datum(); het script heeft geen eigen maandnamen.
        self.assertEqual(payload_uit(self.html)["bewaar"]["maanden"], list(bd.MAANDEN))
        self.assertNotRegex(pagina_js(), r'"(jan|feb|mrt|nov|dec)"')

    def test_geen_cijfer_verandert(self):
        p = payload_uit(self.html)
        self.assertEqual([k["v"] for k in p["kpi"]], ["9.998.456", "6.568.913", "441.997", "263.319"])
        self.assertTrue(p["koppen"]["werklijst.meta"].startswith("2 panden"))
        t = bd.TEMPLATE
        kantoor = t[t.index("const PK = (() => {"):]
        kaart = t[t.index("/* ============================ LANDKAART (VA-85)"):t.index("/* ===================== einde LANDKAART")]
        for deel in (kantoor, kaart):
            self.assertNotIn("BWP", deel)

    def test_stad_zonder_het_deel(self):
        html = bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                          "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})
        self.assertNotIn('id="bewaard"', html)
        self.assertIn('if (!sec) return null;', html)   # het script stopt zonder het deel


class Lijst(unittest.TestCase):
    """Criterium 2: alleen bewaard, nieuwste eerst, en per pand wat er staat."""

    def test_alleen_bewaard(self):
        self.assertIn('Object.keys(stand).filter(id => stand[id] && stand[id].stand === "bewaard")', blok())
        self.assertIn("r = werkt ? R.volgorde(BW.bewaarde()) : [];", pagina_js())

    def test_nieuwste_eerst(self):
        js = pagina_js()
        self.assertIn("if (ta !== tb) { if (ta === null) return 1; if (tb === null) return -1; return tb - ta; }", js)
        self.assertIn('return String(a[1].hoofdadres || "").localeCompare(String(b[1].hoofdadres || ""), "nl"); });', js)

    def test_datums_zoals_het_dashboard(self):
        js = pagina_js()
        # sinds: lokale kalenderdag; datapeildatum: als kalenderdatum gelezen, en een niet-bestaande dag is onleesbaar.
        self.assertIn("return d.getDate() + NB + M[d.getMonth()] + NB + d.getFullYear(); };", js)
        self.assertIn("return dd + NB + M[mm - 1] + NB + j; };", js)
        self.assertIn("dd > new Date(Date.UTC(j, mm, 0)).getUTCDate()", js)
        self.assertNotIn("new Date(s)", js)
        self.assertEqual(bd.nl_datum("2026-11-16"), "16 nov 2026")   # het formaat dat het script nadoet

    def test_wat_een_rij_toont(self):
        js = pagina_js()
        self.assertIn('kern.append(maak("div", "addr", R.adres(v)));', js)   # adres, met de woonplaats één keer
        self.assertIn('return !w || a.endsWith(w) ? a : a ? a + ", " + w : w; };', js)
        self.assertIn('sc.append(maak("b", null, "onbekend"))', js)              # geen score: onbekend
        self.assertIn('ch.append(maak("span", "chip c" + c, c))', js)            # categorie, chip cA..cE
        self.assertIn('vul(T["pagina.sinds"], {datum: sinds})', js)
        self.assertIn("const EERST = +sec.querySelector(\".bwp\").dataset.eerst || 10;", js)
        self.assertIn(f'data-eerst="{bd.BEWAARD_EERST}"', bd.bewaard_html("werklijst"))
        self.assertEqual(bd.BEWAARD_EERST, 10)

    def test_alles_als_tekst(self):
        # Wat uit de opslag komt, gaat als tekst de pagina in, nooit als HTML.
        self.assertNotIn("innerHTML", pagina_js())


class OpenOfNietMeerInDeData(unittest.TestCase):
    """Criterium 3."""

    def test_in_de_data_opent_het_pand(self):
        js = pagina_js()
        self.assertIn("const PER = new Map(LEADS.map(d => [String(d.id), d]));", js)
        self.assertIn('o.addEventListener("click", () => openPand(d, o));', js)
        self.assertIn('o.setAttribute("aria-label", PAND_TEKST.openLabel(d.detail.titel));', js)
        self.assertIn('pandVanBewaard = !!(opener && opener.closest && opener.closest("#bewaard"));', bd.TEMPLATE)

    def test_niet_in_de_data(self):
        js = pagina_js()
        self.assertIn('li = maak("li", "card bwp-rij" + (d ? "" : " weg"))', js)
        self.assertIn('if (!d) kern.append(maak("span", "bw-label weg", T["pagina.weg.label"]));', js)
        self.assertIn('p ? vul(T["pagina.weg.zin"], {datum: p}) : T["pagina.weg.zin.onbekend"]', js)
        # De opgeslagen link naar de BAG-viewer, alleen als hij naar de BAG-viewer wijst.
        self.assertIn("v.bag_viewer_url.startsWith(BAG) ? v.bag_viewer_url : null", js)
        self.assertIn("a.target = \"_blank\"; a.rel = \"noopener\";", js)
        self.assertIn(".card.bwp-rij.weg{border-style:dashed;border-color:var(--baseline)}", bd.TEMPLATE)

    def test_weghalen_werkt_op_het_opgeslagen_object(self):
        js, bw = pagina_js(), blok()
        self.assertIn("function weg(id) {", bw)
        self.assertIn("if (!schrijf()) { stand[id] = oud; werkt = false; overal(false); return null; }", bw)
        self.assertIn("herstelId: (id, oud) => herstel({id}, oud)", bw)
        self.assertIn('const b = BW.status(regel, vul(T["status.niet_bewaard"], {adres: naam}), terug, id);', js)
        self.assertIn("(b || sec).focus();", js)   # naar Ongedaan maken, ook als de lijst leeg is
        self.assertIn('BW.status(regel, vul(T["pagina.status.terug"], {adres: naam}));', js)


class LeegEnOpslag(unittest.TestCase):
    """Criterium 5."""

    def test_leeg_en_geen_opslag(self):
        js = pagina_js()
        self.assertIn('leeg.querySelector("p").textContent = werkt ? T["pagina.leeg"] : T["pagina.geen_opslag"];', js)
        self.assertIn("app.hidden = !werkt;", js)
        html = bd.bewaard_html("werklijst")
        self.assertIn("alleen op dit apparaat", html)
        self.assertNotIn("localStorage", js)   # alleen VA-90's opslag raakt de browseropslag aan


if __name__ == "__main__":
    unittest.main()
