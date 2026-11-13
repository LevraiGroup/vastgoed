"""
VA-68 (werklijstfilters: categorie, signaal, gebied, met de gemeente) en VA-71 (een kleine
luchtfoto op elke kaart). Het filteren zelf doet de pagina in de browser; deze test rekent met
dezelfde regels in Python na wat de pagina moet tonen (VA-68 crit. 14), en controleert de kopij,
de HTML van het paneel en het adres van de kaartfoto. Alleen standaardbibliotheek.
"""
import json
import re
import string
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_dashboard as bd  # noqa: E402
from test_dashboard_nederland import pand  # noqa: E402

NL_PANDEN = bd.DATA / "panden_nederland.json"
SIG = dict((w, k) for w, k, _ in bd.SIGNALEN)  # adreswaarde -> sig.k, zoals de pagina


def past(lead, gemeente="", cat=(), sig=(), geb=()):
    """Nova's regels (BACKLOG, VA-68 tot VA-70): tussen filters EN, binnen een filter OF."""
    if gemeente and lead.get("g") != gemeente:
        return False
    if cat and not any(c in lead["cat"] for c in cat):
        return False
    if sig and not any(s["k"] == SIG[w] for w in sig for s in lead["sig"]):
        return False
    if geb and not any(lead["gg"] == (1 if w == "groot" else 0) for w in geb):
        return False
    return True


def tel(leads, **f):
    return sum(1 for d in leads if past(d, **f))


def plaatshouders(tekst):
    return sorted(n for _, n, _, _ in string.Formatter().parse(tekst) if n)


class Kopij(unittest.TestCase):
    """Lumi's kopijtabel (design/filters.html sectie 3); het script vult alleen deze plaatshouders."""

    def test_elk_sjabloon_heeft_precies_zijn_plaatshouders(self):
        verwacht = {"actief": ["n"], "telling.alle": ["totaal"], "telling": ["n", "totaal"], "toon": ["n"],
                    "chip.gemeente": ["gemeente"], "chip.categorie": ["letter"], "chip.naam": ["chip"]}
        for sleutel, tekst in bd.LIJST_TEKST.items():
            self.assertEqual(plaatshouders(tekst), verwacht.get(sleutel, []), sleutel)
        self.assertEqual(plaatshouders(bd.KAARTFOTO_TEKST["alt"]), ["adres"])
        for sleutel in ("mislukt", "geen", "bron"):
            self.assertEqual(plaatshouders(bd.KAARTFOTO_TEKST[sleutel]), [], sleutel)

    def test_wat_het_script_krijgt(self):
        t = bd.lijst_tekst(1500)
        self.assertEqual(t["alle"], "Alle 1.500 panden")
        self.assertEqual(t["telling"], "{n} van 1.500 panden")
        self.assertEqual((t["toon"], t["toonEen"], t["toonNul"]), ("Toon {n} panden", "Toon 1 pand", "Sluit filters"))
        self.assertEqual(t["gemOptie"], "{gemeente} ({aantal})")
        self.assertEqual(t["chipNaam"], "Verwijder filter: {chip}")
        self.assertEqual(bd.kaartfoto_tekst(), {"alt": "Luchtfoto van {adres}", "mislukt": "Luchtfoto kon niet laden",
                                                "geen": "Locatie onbekend"})

    def test_een_jaartal_gaat_nooit_door_de_puntopmaak(self):
        # (1939).toLocaleString("nl-NL") geeft "1.939" (Lumi, bouwnotitie 2).
        self.assertNotRegex(bd.TEMPLATE, r"nl\(\s*d\.bj")
        self.assertIn("<div class=\"mv\">${d.bj}</div>", bd.TEMPLATE)


class Paneel(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.opties, self.ids, self.disabled, self.labels_for = [], [], 0, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if "disabled" in a:
            self.disabled += 1
        if tag == "label" and "wl-optie" in a.get("class", ""):
            self.opties.append((a["data-groep"], a["data-waarde"], a["data-chip"]))
        if tag == "label" and "for" in a:
            self.labels_for.append(a["for"])


class PaneelHTML(unittest.TestCase):
    def setUp(self):
        self.lijst = [pand(1, "Amsterdam"), pand(2, "Baarn", groot=False)]
        self.html = bd.filter_html(bd.gemeente_filter(self.lijst, 25), bd.KAARTFOTO_TEKST["bron"])
        self.p = Paneel(self.html)

    def test_alle_keuzes_ook_met_nul(self):
        # Categorie D staat er ook als geen pand hem heeft; een keuze is nooit uitgeschakeld (bouwnotitie 4).
        self.assertEqual(self.p.opties, [
            ("cat", "A", "Categorie A"), ("cat", "B", "Categorie B"), ("cat", "C", "Categorie C"),
            ("cat", "D", "Categorie D"), ("cat", "E", "Categorie E"),
            ("sig", "leeg", "Leegstaand"), ("sig", "verbouwing", "In verbouwing"),
            ("geb", "groot", "De 25 grootste gemeenten"), ("geb", "elders", "Elders in Nederland")])
        self.assertEqual(self.p.disabled, 0)
        for naam in bd.CATEGORIE_NAAM.values():
            self.assertIn(f'<span class="wl-naam">{bd.escape(naam)}</span>', self.html)

    def test_toegankelijk(self):
        self.assertIn('aria-expanded="false" aria-controls="wl-paneel"', self.html)
        self.assertIn('<p class="wl-telling" aria-live="polite">Alle 2 panden</p>', self.html)
        self.assertIn('role="group" aria-label="Actieve filters"', self.html)
        self.assertEqual(self.html.count("<legend>"), 3)
        self.assertIn("gemeente", self.p.labels_for)
        self.assertEqual(len(self.p.ids), len(set(self.p.ids)))

    def test_lege_lijst_en_bron_een_keer(self):
        self.assertIn('<div class="wl-leeg" hidden><p>Geen enkel pand op de werklijst van deze maand past bij deze '
                      'filters. Verwijder hierboven een filter, of wis ze allemaal.</p>', self.html)
        self.assertEqual(self.html.count('class="wl-bron"'), 1)
        self.assertIn("Beeldmateriaal.nl, via PDOK · open data (CC BY 4.0)", self.html)

    def test_zonder_filter_alleen_de_bronregel(self):
        self.assertEqual(bd.filter_html(None, "x"), '<p class="wl-bron">x</p>')
        self.assertEqual(bd.filter_html(None), "")


class Tellingen(unittest.TestCase):
    """VA-68 crit. 1-6 op een vaste lijst: elk filter alleen, en samen (EN tussen, OF binnen)."""

    def setUp(self):
        lijst = [pand(1, "Amsterdam"), pand(2, "Amsterdam"), pand(3, "Leiden"), pand(4, "Baarn", groot=False)]
        lijst[0]["categorieen"] = ["A", "C"]
        lijst[2]["categorieen"] = ["A"]
        lijst[1]["score_opbouw"] = lijst[3]["score_opbouw"] = [
            {"label": "Buiten gebruik / leegstaand", "punten": 4, "behaald": True, "detail": "", "status": "behaald"}]
        lijst[2]["score_opbouw"] = [
            {"label": "In verbouwing", "punten": 2, "behaald": True, "detail": "", "status": "behaald"}]
        self.leads = bd.maak_leads(lijst, landelijk=True)[0]

    def test_gebied_uit_grote_gemeente(self):
        self.assertEqual([d["gg"] for d in self.leads], [1, 1, 1, 0])
        self.assertNotIn("gg", bd.maak_leads([pand(1, "Delft")], landelijk=False)[0][0])

    def test_elk_filter_en_samen(self):
        L = self.leads
        self.assertEqual(tel(L, cat=["A"]), 2)
        self.assertEqual(tel(L, cat=["A", "C"]), 4)          # OF: een pand met A en C telt één keer
        self.assertEqual(tel(L, cat=["D"]), 0)
        self.assertEqual(tel(L, sig=["leeg"]), 2)
        self.assertEqual(tel(L, sig=["leeg", "verbouwing"]), 3)
        self.assertEqual(tel(L, geb=["elders"]), 1)
        self.assertEqual(tel(L, geb=["groot", "elders"]), 4)  # beide is hetzelfde als geen
        self.assertEqual(tel(L, gemeente="Amsterdam", cat=["C"], sig=["leeg"]), 1)  # EN
        self.assertEqual(tel(L, gemeente="Leiden", cat=["A"], sig=["leeg"]), 0)


class Kaartfoto(unittest.TestCase):
    """VA-71 crit. 2, 6, 10 en 11."""

    def test_zelfde_dienst_en_laag_klein(self):
        mini, groot = bd.PLEK_SJABLOON["mini"], bd.PLEK_SJABLOON["foto"]
        self.assertTrue(mini.startswith("https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0?"))
        self.assertEqual(re.sub(r"(WIDTH|HEIGHT)=\d+", "", mini), re.sub(r"(WIDTH|HEIGHT)=\d+", "", groot))
        self.assertIn("LAYERS=Actueel_orthoHR", mini)
        maten = [int(x) for x in re.findall(r"(?:WIDTH|HEIGHT)=(\d+)", mini)]
        self.assertEqual(len(maten), 2)
        self.assertTrue(all(m <= 240 for m in maten), maten)
        self.assertNotRegex(mini.lower(), r"key|token")

    def test_adres_per_pand_en_geen_zonder_plek(self):
        loc = bd.pand_locatie(pand(1, "Delft"))
        self.assertIn("BBOX=120960.0,486960.0,121040.0,487040.0&WIDTH=200&HEIGHT=200", loc["mini"])
        for extra in ({"x": None}, {"y": 0}):
            p = dict(pand(1, "Delft"), **extra)
            self.assertIsNone(bd.pand_locatie(p))
            self.assertIsNone(bd.maak_leads([p], landelijk=True)[0][0]["detail"]["loc"])  # het script vraagt niets

    def test_script_laadt_lui_en_alleen_met_plek(self):
        t = bd.TEMPLATE
        self.assertIn('img.loading = "lazy"', t)
        self.assertIn("if (!plek || !PLEK.mini)", t)
        self.assertIn("img.src = PLEK.mini.replace", t)
        self.assertIn(".card-foto{position:relative;width:100px;height:100px", t)  # vaste maat: niets verschuift
        self.assertIn("gebouwd.get(d.id)", t)  # een kaart wordt hergebruikt: geen tweede verzoek
        self.assertNotIn("service.pdok.nl", t)

    def test_bronregel_een_keer_ook_in_delft(self):
        html = bd.render(bd.bouw_payload_gebied(bd.load_config()))
        self.assertEqual(html.count('<p class="wl-bron">'), 1)
        self.assertNotIn('class="wl-knop"', html)  # Delft heeft geen filters


@unittest.skipUnless(NL_PANDEN.is_file(), f"{NL_PANDEN} ontbreekt; echte werklijst overgeslagen")
class EchteWerklijst(unittest.TestCase):
    """VA-68 crit. 14: de controlecijfers van Lumi (design/filters.html bouwnotitie 11), uit de payload."""

    @classmethod
    def setUpClass(cls):
        maand = (json.loads(NL_PANDEN.read_text(encoding="utf-8")).get("totalen") or {}).get("maand")
        if maand != "2026-11":
            raise unittest.SkipTest(f"de controlecijfers horen bij de werklijst van 2026-11, niet {maand}: tel opnieuw")
        c = bd.load_config()
        c["doelgebied"]["nederland"] = True
        with mock.patch.object(bd, "load_config", lambda: c):
            cls.leads = bd.bouw_payload()["leads"]

    def test_controlecijfers(self):
        L = self.leads
        self.assertEqual(len(L), 500)
        for f, n in [({"cat": ["D"]}, 0), ({"cat": ["A", "C"]}, 488), ({"sig": ["leeg"]}, 6),
                     ({"sig": ["verbouwing"]}, 220), ({"sig": ["leeg", "verbouwing"]}, 221),
                     ({"geb": ["groot"]}, 450), ({"geb": ["elders"]}, 50), ({"gemeente": "Amsterdam"}, 111),
                     ({"gemeente": "Leiden", "cat": ["A"], "sig": ["leeg"]}, 0),
                     ({"gemeente": "Amsterdam", "cat": ["C"], "sig": ["verbouwing"]}, 43)]:
            with self.subTest(**{k: str(v) for k, v in f.items()}):
                self.assertEqual(tel(L, **f), n)

    def test_aantal_per_keuze_bij_criterium_4(self):
        # Crit. 6: een keuze telt de panden die de andere filters halen. Leiden + A + leegstaand geeft 0,
        # en het paneel laat zien waarom: binnen Leiden en A is 'Leegstaand' 0.
        L = self.leads
        self.assertEqual(tel(L, gemeente="Leiden", cat=["A"], sig=["leeg"]), 0)
        self.assertEqual(tel(L, gemeente="Leiden", cat=["A"], sig=["verbouwing"]), 4)
        self.assertEqual(sum(1 for d in L if d["gg"] == 1), 450)


if __name__ == "__main__":
    unittest.main()
