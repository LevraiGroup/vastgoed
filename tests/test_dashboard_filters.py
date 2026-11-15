"""
VA-68 (werklijstfilters: categorie, signaal, gebied, met de gemeente), VA-69 (getalfilters: score,
bouwjaar, oppervlakte, VBO's, adressen), VA-70 (sorteren) en VA-71 (een kleine luchtfoto op elke
kaart). Het filteren en sorteren doet de pagina in de browser; deze test rekent met dezelfde regels
in Python na wat de pagina moet tonen (VA-68 crit. 14, VA-69 crit. 8, VA-70 crit. 8), en controleert
de kopij, de HTML van het paneel en het adres van de kaartfoto. Alleen standaardbibliotheek.
"""
import json
import re
import string
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_dashboard as bd  # noqa: E402
from test_dashboard_nederland import pand  # noqa: E402

NL_PANDEN = bd.DATA / "panden_nederland.json"
SIG = dict((w, k) for w, k, _ in bd.SIGNALEN)  # adreswaarde -> sig.k, zoals de pagina


def past(lead, gemeente="", cat=(), sig=(), geb=(), bereik=None):
    """
    Nova's regels (BACKLOG, VA-68 tot VA-70): tussen filters EN, binnen een filter OF. bereik:
    {veld: (van, tot en met)}, grenzen tellen mee, een pand zonder waarde valt weg (VA-69 crit. 4).
    """
    if gemeente and lead.get("g") != gemeente:
        return False
    if cat and not any(c in lead["cat"] for c in cat):
        return False
    if sig and not any(s["k"] == SIG[w] for w in sig for s in lead["sig"]):
        return False
    if geb and not any(lead["gg"] == (1 if w == "groot" else 0) for w in geb):
        return False
    for veld, (van, tm) in (bereik or {}).items():
        v = lead.get(veld)
        if v is None or (van is not None and v < van) or (tm is not None and v > tm):
            return False
    return True


def tel(leads, **f):
    return sum(1 for d in leads if past(d, **f))


# Adresparameter van een getalfilter -> (veld op de kaart, 0 = van / 1 = tot en met), uit build_dashboard.
ADRES_BEREIK = {u: (b["veld"], j) for b in bd.BEREIKEN for j, u in enumerate(b["url"])}


def uit_adres(zoek):
    """Lumi's adres (design/filters.html sectie 4) als filter voor past(); zo wordt haar tabel letterlijk getest."""
    f, bereik = {}, {}
    for k, (v,) in parse_qs(zoek.lstrip("?")).items():
        if k == "gemeente":
            f["gemeente"] = v
        elif k in ("categorie", "signaal", "gebied"):
            f[{"categorie": "cat", "signaal": "sig", "gebied": "geb"}[k]] = v.split(",")
        else:
            veld, j = ADRES_BEREIK[k]
            grens = list(bereik.get(veld, (None, None)))
            grens[j] = int(v)
            bereik[veld] = tuple(grens)
    return dict(f, bereik=bereik)


def sorteer(leads, sort="score", richting=None):
    """VA-70 crit. 3: gelijk blijft in werklijstvolgorde; zonder waarde achteraan, in beide richtingen."""
    veld, std = {w: (v, s) for w, v, _, s, _ in bd.SORTEREN}[sort]
    op, plek = (richting or std) == "op", {id(d): i for i, d in enumerate(leads)}
    met = sorted((d for d in leads if d.get(veld) is not None),
                 key=lambda d: (d[veld] if op else -d[veld], plek[id(d)]))
    return met + [d for d in leads if d.get(veld) is None]


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
        # In de chips van een getalfilter blijft alleen het bouwjaar ('jaar') onbewerkt.
        self.assertIn("const grens = (b, v) => b.jaar ? String(v) : nl(v);", bd.TEMPLATE)
        self.assertEqual([b["k"] for b in bd.BEREIKEN if b.get("jaar")], ["bj"])
        self.assertEqual(bd.bereik_getal(bd.BEREIKEN[1], 1939), "1939")
        self.assertEqual(bd.bereik_getal(bd.BEREIKEN[2], 1200), "1.200")

    def test_bereik_en_sorteer_kopij(self):
        t = bd.BEREIK_TEKST
        self.assertEqual(plaatshouders(t["hint"]), ["max", "min"])
        self.assertEqual(plaatshouders(t["chip.van.tm"]), ["eenheid", "naam", "tm", "van"])
        self.assertEqual(plaatshouders(t["chip.van"]), ["eenheid", "naam", "van"])
        self.assertEqual(plaatshouders(t["chip.tm"]), ["eenheid", "naam", "tm"])
        for b in bd.BEREIKEN:
            self.assertEqual(plaatshouders(b["fout"]), [], b["k"])
            self.assertEqual(plaatshouders(b.get("chip", "")), ["van"] if "chip" in b else [], b["k"])
        self.assertEqual([b["label"] for b in bd.BEREIKEN],
                         ["Score-index (/100)", "Bouwjaar", "Oppervlakte (m²)", "Aantal VBO's", "Aantal adressen"])
        # Geen eenheid 'jaar' achter het bouwjaar (Lumi: "1939 jaar" is een leeftijd, geen bouwjaar).
        bj = bd.BEREIKEN[1]
        self.assertEqual((bj["label"], bj["eenheid"]), ("Bouwjaar", ""))
        self.assertEqual(bd.lijst_tekst(5)["omgekeerd"], "Van is hoger dan tot en met. Dit filter telt nu niet mee.")
        self.assertEqual([(w, std, list(n.values())) for w, _, _, std, n in bd.SORTEREN], [
            ("score", "af", ["Hoogste eerst", "Laagste eerst"]),
            ("bouwjaar", "op", ["Oudste eerst", "Nieuwste eerst"]),
            ("oppervlakte", "af", ["Grootste eerst", "Kleinste eerst"])])

    def test_adresnamen_uit_lumis_tabel(self):
        self.assertEqual([u for b in bd.BEREIKEN for u in b["url"]],
                         ["min_score", "bouwjaar_van", "bouwjaar_tm", "m2_van", "m2_tm", "vbo_van", "vbo_tm",
                          "adressen_van", "adressen_tm"])
        self.assertIn('"sorteer", "richting"]', bd.TEMPLATE)


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

    def test_getalvelden_en_sorteren(self):
        leads = bd.maak_leads(self.lijst, landelijk=True)[0]
        html = bd.filter_html({**bd.gemeente_filter(self.lijst, 25), **bd.bereik_filter(leads)})
        p = Paneel(html)
        velden = re.findall(r'<input id="(wl-[a-z0-9]+-(?:van|tm))"', html)
        self.assertEqual(velden, ["wl-score-van", "wl-bj-van", "wl-bj-tm", "wl-m2-van", "wl-m2-tm", "wl-vbo-van",
                                  "wl-vbo-tm", "wl-adr-van", "wl-adr-tm"])
        for v in velden:
            self.assertIn(v, p.labels_for)
            self.assertRegex(html, f'id="{v}"[^>]*type="text" inputmode="numeric" autocomplete="off" '
                                   'enterkeyhint="done"')
        self.assertIn('<label for="wl-bj-tm">tot en met</label>', html)
        self.assertIn('<label for="wl-score-van">vanaf</label>', html)
        self.assertEqual(html.count("<legend>"), 3 + 5)
        self.assertEqual(len(p.ids), len(set(p.ids)))
        # Sorteren in de balk, voor het paneel (tabvolgorde: Filters, Sorteer op, Volgorde, het paneel).
        self.assertLess(html.index('id="wl-knop"'), html.index('id="wl-sorteer"'))
        self.assertLess(html.index('id="wl-volgorde"'), html.index('id="wl-paneel"'))
        self.assertIn('<label for="wl-sorteer">Sorteer op</label><select id="wl-sorteer"><option value="score">'
                      'Score-index</option><option value="bouwjaar">Bouwjaar</option><option value="oppervlakte">'
                      'Oppervlakte</option></select>', html)
        self.assertIn('<label for="wl-volgorde">Volgorde</label><select id="wl-volgorde"><option value="af">'
                      'Hoogste eerst</option><option value="op">Laagste eerst</option></select>', html)

    def test_zonder_filter_alleen_de_bronregel(self):
        self.assertEqual(bd.filter_html(None, "x"), '<p class="wl-bron">x</p>')
        self.assertEqual(bd.filter_html(None), "")


class BereikEnSorteer(unittest.TestCase):
    """VA-69 en VA-70 op een vaste lijst: wat Python het script geeft, en de regels die het script volgt."""

    def setUp(self):
        lijst = [pand(i, "Amsterdam") for i in range(1, 6)]
        for p, (bj, m2, s) in zip(lijst, [(1939, 1200.4, 80), (1940, 300.0, 75), (1850, 300.0, 80),
                                          (None, 950.0, 70), (1900, 450.0, 75)]):
            p.update(bouwjaar=bj, totale_oppervlakte=m2, score100=s)
        self.leads = bd.maak_leads(lijst, landelijk=True)[0]
        self.f = bd.bereik_filter(self.leads)

    def test_hints_en_chips_uit_python(self):
        b = {x["k"]: x for x in self.f["bereik"]}
        self.assertEqual(b["bj"]["hint"], "Op de werklijst: 1850–1940")   # een pand zonder bouwjaar telt niet mee
        self.assertEqual(b["m2"]["hint"], "Op de werklijst: 300–1.200")
        self.assertEqual(b["score"]["chips"], {"van": "Score vanaf {van}"})
        self.assertEqual(b["m2"]["chips"], {"vanTm": "Oppervlakte {van}–{tm} m²", "van": "Oppervlakte vanaf {van} m²",
                                            "tm": "Oppervlakte tot en met {tm} m²"})
        self.assertEqual(b["bj"]["chips"]["tm"], "Bouwjaar tot en met {tm}")
        self.assertEqual((b["bj"]["jaar"], b["m2"]["jaar"], b["score"]["max"]), (True, False, 100))
        self.assertEqual(b["vbo"]["fout"], "Vul een heel getal in, bijvoorbeeld 4. Dit filter telt nu niet mee.")
        self.assertEqual(list(self.f["sorteer"]), ["score", "bouwjaar", "oppervlakte"])
        self.assertEqual(self.f["sorteer"]["bouwjaar"], {"veld": "bj", "label": "Bouwjaar", "std": "op",
                                                          "opties": [["op", "Oudste eerst"], ["af", "Nieuwste eerst"]]})

    def test_grenzen_tellen_mee_en_zonder_waarde_valt_weg(self):
        L = self.leads
        self.assertEqual(tel(L, **uit_adres("bouwjaar_tm=1939")), 3)          # 1939 telt mee; 1940 en onbekend niet
        self.assertEqual(tel(L, **uit_adres("bouwjaar_van=1850&bouwjaar_tm=1900")), 2)
        self.assertEqual(tel(L), 5)                                            # zonder grens is hij er weer
        self.assertEqual(tel(L, **uit_adres("min_score=80")), 2)
        self.assertEqual(tel(L, **uit_adres("min_score=75&m2_van=450")), 2)   # 1.200 en 450 m²
        self.assertEqual(tel(L, **uit_adres("m2_tm=300")), 2)

    def test_sorteren(self):
        L = self.leads
        ids = lambda lijst: [d["id"][-1] for d in lijst]  # noqa: E731
        # Standaard: score hoogste eerst, gelijk in lijstvolgorde. Deze vaste lijst staat niet op score; dat
        # de standaard op de echte werklijst precies de volgorde van vandaag is, toetst EchteWerklijst.
        self.assertEqual(ids(sorteer(L)), ["1", "3", "2", "5", "4"])
        self.assertEqual(ids(sorteer(L, "score", "op")), ["4", "2", "5", "1", "3"])     # gelijk: werklijstvolgorde
        self.assertEqual(ids(sorteer(L, "bouwjaar")), ["3", "5", "1", "2", "4"])        # zonder bouwjaar achteraan
        self.assertEqual(ids(sorteer(L, "bouwjaar", "af")), ["2", "1", "5", "3", "4"])  # ook bij nieuwste eerst
        self.assertEqual(ids(sorteer(L, "oppervlakte")), ["1", "4", "5", "2", "3"])

    def test_script_volgt_dezelfde_regels(self):
        t = bd.TEMPLATE
        self.assertIn("if (v == null || (x.van !== null && v < x.van) || (x.tm !== null && v > x.tm)) return false;", t)
        self.assertIn("if (x == null || y == null) return x == null && y == null ? na(a, b) : x == null ? 1 : -1;", t)
        self.assertIn("teken(sorteer(treffers));", t)       # dezelfde kaarten uit 'gebouwd', in een andere volgorde
        self.assertIn("st.ruw = leegRuw(); werk(true);", t)  # wis alle filters laat de sortering staan
        self.assertNotIn('type="number"', t)


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

    def test_controlecijfers_met_getalfilters(self):
        # VA-69 crit. 8: Lumi's adressen letterlijk, met "tot en met 1939" en score + oppervlakte samen.
        for zoek, n in [("min_score=80", 3), ("bouwjaar_tm=1939", 499), ("bouwjaar_van=1850&bouwjaar_tm=1900", 133),
                        ("min_score=75&m2_van=500", 52), ("categorie=A,C&signaal=verbouwing&bouwjaar_tm=1939", 207)]:
            with self.subTest(zoek):
                self.assertEqual(tel(self.leads, **uit_adres(zoek)), n)

    def test_geen_pand_mist_een_getalveld(self):
        # VA-69 crit. 4, voor de close-out: hoeveel van de 500 een veld missen.
        for b in bd.BEREIKEN:
            self.assertEqual(sum(1 for d in self.leads if d.get(b["veld"]) is None), 0, b["veld"])

    def test_eerste_vijf_per_sortering(self):
        # VA-70 crit. 8, vastgezet op de werklijst van november; de pagina toont dezelfde volgorde.
        verwacht = {
            ("score", "af"): ["0503100000026198", "0796100000279071", "0986100000489031", "0644100002060945",
                              "0225100000000446"],
            ("score", "op"): ["0344100000059553", "0344100000022665", "0363100012236146", "0363100012120378",
                              "0518100000273627"],
            ("bouwjaar", "op"): ["0344100000017472", "0344100000011132", "0796100000279807", "0344100000036831",
                                 "0344100000061759"],
            ("bouwjaar", "af"): ["0637100000154254", "0399100000004031", "0363100012176176", "0014100010920597",
                                 "0228100000024900"],
            ("oppervlakte", "af"): ["0986100000489031", "0363100012177482", "0228100000013941", "0518100000299070",
                                    "0518100000336915"],
            ("oppervlakte", "op"): ["0363100012179274", "0268100000009949", "0518100000317816", "0599100000631919",
                                    "0344100000044974"],
        }
        for (s, r), ids in verwacht.items():
            with self.subTest(sorteer=s, richting=r):
                self.assertEqual([d["id"] for d in sorteer(self.leads, s, r)[:5]], ids)
        self.assertEqual(sorteer(self.leads), self.leads)  # crit. 1: de standaard is precies de volgorde van vandaag

    def test_aantal_per_keuze_bij_criterium_4(self):
        # Crit. 6: een keuze telt de panden die de andere filters halen. Leiden + A + leegstaand geeft 0,
        # en het paneel laat zien waarom: binnen Leiden en A is 'Leegstaand' 0.
        L = self.leads
        self.assertEqual(tel(L, gemeente="Leiden", cat=["A"], sig=["leeg"]), 0)
        self.assertEqual(tel(L, gemeente="Leiden", cat=["A"], sig=["verbouwing"]), 4)
        self.assertEqual(sum(1 for d in L if d["gg"] == 1), 450)


if __name__ == "__main__":
    unittest.main()
