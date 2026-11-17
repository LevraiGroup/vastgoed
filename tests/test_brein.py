"""
VA-98 en VA-99: de Brein-pagina (design/brein.html). Wat zonder browser te controleren is: de menu-items op
beide pagina's, dat elk getal uit de bouw komt en elke regelwaarde uit config.yaml of uit SCORE_GRENZEN (en
dat die tabel klopt met selectie.scoor() en categoriseer()), dat de werklijst geen zichtbaar totaal heeft, de
grootte, en dat de server de pagina alleen met een sessie geeft. Beweging, toetsenbord en 375/1280 px zijn in
de browser gecontroleerd (close-out). Tests op de echte data worden overgeslagen als die ontbreekt.
"""
import copy
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_dashboard as bd  # noqa: E402
import selectie  # noqa: E402
import test_serve as ts  # noqa: E402

DELFT = bd.DATA / "panden_delft.json"
NL = bd.DATA / "panden_nederland.json"
GEBOUWD = bd.OUT.with_name(bd.BREIN_NAAM)


class Pagina(HTMLParser):
    """
    De zichtbare tekst (zonder .vh), wat een schermlezer leest (zonder aria-hidden), alle tekst, de links van het
    menu en de stappen.
    """

    def __init__(self, html):
        super().__init__()
        self.zichtbaar, self.sr, self.alles, self.menu, self.stappen, self.ids = [], [], [], [], [], []
        self._stapel, self._in_nav, self._script = [], False, False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        verborgen = ("vh" in (a.get("class") or "").split(), a.get("aria-hidden") == "true")
        if tag not in ("br", "i", "meta", "link", "input"):
            self._stapel.append(verborgen)
        if tag == "nav":
            self._in_nav = True
        if tag in ("script", "style"):
            self._script = True
        if tag == "a" and self._in_nav:
            self.menu.append(a)
        if tag == "button" and "stap" in (a.get("class") or "").split():
            self.stappen.append(a)

    def handle_endtag(self, tag):
        if tag == "nav":
            self._in_nav = False
        if tag in ("script", "style"):
            self._script = False
        if tag not in ("br", "i", "meta", "link", "input") and self._stapel:
            self._stapel.pop()

    def handle_data(self, data):
        if self._script:
            return
        self.alles.append(data)
        if not any(v[0] for v in self._stapel):
            self.zichtbaar.append(data)
        if not any(v[1] for v in self._stapel):
            self.sr.append(data)


def tekst(delen):
    return re.sub(r"\s+", " ", "".join(delen).replace(bd.NBSP, " "))


def cfg_basis():
    return copy.deepcopy(selectie.load_config())


def payload_nl(cfg, t):
    """Een landelijke payload zoals bouw_payload_landelijk() hem maakt, zonder data/: alleen het kantoorblok."""
    bron = [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]
    return {"gebied": "Nederland", "bron": bron, "kantoor": bd.kantoor_landelijk(bron, t, t["werklijst"], cfg),
            "pagina": bd.pagina("werklijst", "x", "x", "x", "x")}


# Opvallende getallen die nergens anders staan, zodat een vondst op de pagina alleen uit de bouw kan komen.
T = {"vbo": 9876543, "panden": 6543219, "uitgesloten": 471113, "a_e": 432109,
     "categorieen": {"A": 41231, "B": 52341, "C": 173451, "D": 154561, "E": 131671},
     "geschikt": 261113, "werklijst": 437, "werklijst_25": 391, "werklijst_overig": 46, "drempel": 9,
     "maand": "2026-12", "aantal_grote_gemeenten": 23}


def bouw(cfg, t=T):
    html = bd.brein_html(bd.brein_blok(payload_nl(cfg, t), cfg, t["maand"], t), "werklijst")
    return html, Pagina(html)


class ScoreGrenzenKloptMetDeCode(unittest.TestCase):
    """VA-99 crit. 3 (Nova Q4): elke waarde van SCORE_GRENZEN tegen scoor() en categoriseer(), op de grens."""

    def setUp(self):
        self.cfg = cfg_basis()
        self.g = bd.SCORE_GRENZEN

    def pand(self, **w):
        p = {"totale_oppervlakte": 150, "bouwjaar": 1990, "aantal_vbo": 1, "aantal_adressen": 1,
             "aantal_per_functie": {"woon": 1}, "pandstatus": "Pand in gebruik", "vbo_statussen": []}
        p.update(w)
        return p

    def punten(self, p, sleutel):
        """Of het signaal 'sleutel' meetelt: het verschil met de score als zijn gewicht 0 is."""
        nul = copy.deepcopy(self.cfg)
        nul["score"][sleutel] = 0
        return selectie.scoor(p, [], self.cfg)[0] - selectie.scoor(p, [], nul)[0]

    def test_vbo_3_tot_10(self):
        s, g = "vbo_3_tot_10", self.g
        self.assertTrue(self.punten(self.pand(aantal_vbo=g["vbo_min"]), s))
        self.assertFalse(self.punten(self.pand(aantal_vbo=g["vbo_min"] - 1), s))
        self.assertTrue(self.punten(self.pand(aantal_vbo=g["vbo_max"]), s))
        self.assertFalse(self.punten(self.pand(aantal_vbo=g["vbo_max"] + 1), s))

    def test_bouwjaar_voor_1940(self):
        s, j = "bouwjaar_voor_1940", self.g["bouwjaar_voor"]
        self.assertTrue(self.punten(self.pand(bouwjaar=j - 1), s))
        self.assertFalse(self.punten(self.pand(bouwjaar=j), s))

    def test_opp_200_800(self):
        s, g = "opp_200_800", self.g
        self.assertTrue(self.punten(self.pand(totale_oppervlakte=g["opp_min"]), s))
        self.assertFalse(self.punten(self.pand(totale_oppervlakte=g["opp_min"] - 1), s))
        self.assertTrue(self.punten(self.pand(totale_oppervlakte=g["opp_max"]), s))
        self.assertFalse(self.punten(self.pand(totale_oppervlakte=g["opp_max"] + 1), s))

    def test_min_3_adressen(self):
        s, n = "min_3_adressen", self.g["adressen_min"]
        self.assertTrue(self.punten(self.pand(aantal_adressen=n), s))
        self.assertFalse(self.punten(self.pand(aantal_adressen=n - 1), s))

    def test_groot_opp_weinig_eenheden(self):
        s, g = "groot_opp_1_2_eenheden", self.g
        self.assertTrue(self.punten(self.pand(totale_oppervlakte=g["groot_opp"], aantal_vbo=g["groot_vbo_max"]), s))
        self.assertFalse(self.punten(self.pand(totale_oppervlakte=g["groot_opp"] - 1, aantal_vbo=1), s))
        self.assertFalse(self.punten(self.pand(totale_oppervlakte=g["groot_opp"], aantal_vbo=g["groot_vbo_max"] + 1), s))

    def functies(self, n):
        groepen = ["woon", "winkel", "kantoor", "bedrijf", "overig"][:n]
        return {g: 1 for g in groepen}

    def test_functiegroepen_in_score(self):
        s, n = "opvallende_functiecombinatie", self.g["functiegroepen_min"]
        self.assertTrue(self.punten(self.pand(aantal_per_functie=self.functies(n)), s))
        self.assertFalse(self.punten(self.pand(aantal_per_functie=self.functies(n - 1)), s))

    def test_functiegroepen_in_categorie_e(self):
        n, e = self.g["functiegroepen_min"], self.cfg["categorieen"]["E_afwijkend"]
        basis = dict(totale_oppervlakte=100, aantal_vbo=n, aantal_adressen=e["min_adressen"], bouwjaar=2010)
        self.assertIn("E", selectie.categoriseer(self.pand(aantal_per_functie=self.functies(n), **basis), self.cfg))
        self.assertNotIn("E", selectie.categoriseer(self.pand(aantal_per_functie=self.functies(n - 1), **basis),
                                                    self.cfg))


class Menu(unittest.TestCase):
    """VA-98 crit. 1: een item naar de Brein-pagina op het dashboard, en terug op de Brein-pagina."""

    def test_dashboard_heeft_brein_na_kerncijfers(self):
        from test_dashboard_menu import gebouwd
        p = Pagina(gebouwd())
        hrefs = [a["href"] for a in p.menu]
        self.assertEqual(hrefs, ["#kantoor", "#kerncijfers", "brein.html", "#voorraad", "#proefresultaat"])
        brein = p.menu[2]
        self.assertNotIn("data-doel", brein)       # het menuscript laat dit item met rust
        self.assertNotIn("aria-current", brein)

    def test_brein_pagina_wijst_terug_naar_elk_deel_van_het_dashboard(self):
        html, p = bouw(cfg_basis())
        self.assertEqual([a["href"] for a in p.menu],
                         ["index.html#kantoor", "index.html#kerncijfers", "brein.html", "index.html#voorraad",
                          "index.html#bewaard", "index.html#werklijst"])
        self.assertEqual([a.get("aria-current") for a in p.menu], [None, None, "page", None, None, None])
        # elk anker bestaat op het dashboard van dezelfde lijst
        from test_dashboard_menu import Pagina as DashPagina, gebouwd
        # gebouwd() is Delft; 'werklijst' en 'bewaard' (VA-91) staan alleen op de landelijke pagina
        ids = DashPagina(gebouwd()).ids + ["werklijst", "bewaard"]
        for a in p.menu:
            if "#" in a["href"]:
                self.assertIn(a["href"].split("#")[1], ids)
        self.assertIn("inhoud", p.ids)   # "Sla het menu over"


class GetallenEnRegelsUitDeBouw(unittest.TestCase):
    """VA-98 crit. 3 en 4, VA-99 crit. 2 tot 5: niets getypt in de pagina; alles uit de bouw en config.yaml."""

    def test_stappen_en_volgorde(self):
        _, p = bouw(cfg_basis())
        self.assertEqual([s["id"] for s in p.stappen],
                         ["stap-vbo", "stap-panden", "stap-a_e", "stap-geschikt", "stap-register", "stap-loting",
                          "stap-verdeling", "stap-werklijst"])
        for s in p.stappen:
            self.assertEqual(s["aria-expanded"], "false")
            self.assertEqual(s["aria-controls"], "regel-" + s["id"][5:])

    def test_de_aantallen_zijn_die_van_de_bouw(self):
        _, p = bouw(cfg_basis())
        z = tekst(p.zichtbaar)
        for n in ("9.876.543", "6.543.219", "432.109", "261.113", "A 41.231", "B 52.341", "C 173.451",
                  "D 154.561", "E 131.671", "391 + 46", "uit de 23 grootste gemeenten", "Score 9 of hoger",
                  "december 2026", "471.113 panden vallen hierdoor af"):
            self.assertIn(n, z)
        sr = tekst(p.alles)
        self.assertIn("391 uit de 23 grootste gemeenten en 46 elders", sr)
        self.assertIn("A, Winkel + wonen: 41.231", sr)

    def test_werklijst_zonder_zichtbaar_totaal_wel_voor_de_schermlezer(self):
        _, p = bouw(cfg_basis())
        self.assertNotIn("437", tekst(p.zichtbaar))
        self.assertIn("Werklijst — 437 panden", tekst(p.alles))
        # ook de plaatsen staan als twee delen, nooit als totaal (Nova Q1): 500 = 450 + 50
        self.assertNotRegex(tekst(p.zichtbaar), r"(?<![\d.])500(?![\d.])")
        self.assertIn("450 plaatsen", tekst(p.zichtbaar))

    def test_register_zonder_getal_tot_va103(self):
        html, p = bouw(cfg_basis())
        self.assertIn("Een geleverd pand komt niet terug", tekst(p.zichtbaar))
        mit = bd.brein_blok(payload_nl(cfg_basis(), T), cfg_basis(), T["maand"], {**T, "al_geleverd": 1234})
        self.assertEqual(next(s for s in mit["stappen"] if s["id"] == "register")["getal"], "1.234")
        self.assertTrue(mit["bots"])

    def test_een_andere_config_staat_op_de_pagina(self):
        cfg = cfg_basis()
        cfg["drempels"]["score_min_voor_werklijst"] = 11
        cfg["drempels"]["werklijst_max"] = 700
        cfg["drempels"]["werklijst_aandeel_overig"] = 0.2
        cfg["score"]["winkel_plus_wonen"] = 7
        cfg["score"]["recent_gebouwd_of_vernieuwd"] = -6
        cfg["score"]["schaal_max"] = 30
        cfg["categorieen"]["C_klein_wooncomplex"]["woon_vbo_max"] = 17
        cfg["categorieen"]["A_winkel_wonen"]["opp_max"] = 1200
        cfg["uitsluitingen"]["opp_groter_dan"] = 2500
        cfg["uitsluitingen"]["status_uitsluiten"] = ["Pand gesloopt", "Nep status"]
        _, p = bouw(cfg)
        z = tekst(p.zichtbaar)
        for verwacht in ("bij 11 punten of meer", "Winkel en woning in één pand+7", "Gebouwd in 2000 of later−6",
                         "30 punten is 100, 11 punten is 37", "3 tot en met 17 woningen", "150–1.200 m²",
                         "groter dan 2.500 m²", "‘Pand gesloopt’ of ‘Nep status’",
                         "560 plaatsen voor panden in de 23 gemeenten", "en 140 voor panden daarbuiten"):
            self.assertIn(verwacht, z)

    def test_energielabel_staat_uit_tot_de_bron_aan_staat(self):
        cfg = cfg_basis()
        cfg["bronnen"]["energielabel"]["actief"] = False
        z = tekst(bouw(cfg)[1].zichtbaar)
        self.assertIn("Slecht of geen energielabel (E, F of G)Staat uit: telt nu niet mee.uit", z)
        cfg["bronnen"]["energielabel"]["actief"] = True
        z = tekst(bouw(cfg)[1].zichtbaar)
        self.assertIn("Slecht of geen energielabel (E, F of G)+2", z)
        self.assertNotIn("Staat uit", z)

    def test_bouwjaar_vanaf_is_aftrek_geen_uitsluiting(self):
        cfg = cfg_basis()
        cfg["uitsluitingen"]["bouwjaar_vanaf"] = 2003
        html, p = bouw(cfg)
        regel = html[html.index('id="regel-a_e"'):html.index('id="stap-geschikt"')]
        self.assertNotIn("2003", regel)
        self.assertIn("Gebouwd in 2003 of later", tekst(p.zichtbaar))

    def test_jaren_zonder_punt_getallen_met_punt(self):
        z = tekst(bouw(cfg_basis())[1].zichtbaar)
        self.assertIn("gebouwd vóór 2000", z)
        self.assertNotIn("2.000 m² met", z)
        self.assertIn("150–1.000 m²", z)

    def test_het_sjabloon_heeft_geen_getal_en_geen_regel(self):
        t = bd.BREIN_TEMPLATE
        sjabloon_tekst = tekst(Pagina(t).alles)
        self.assertFalse(re.search(r"\d", sjabloon_tekst), sjabloon_tekst)
        for woord in ("Werklijst", "Verblijfsobjecten", "Score", "november", "punten"):
            self.assertNotIn(woord, t)

    def test_geen_engels_en_geen_snapshot(self):
        z = tekst(bouw(cfg_basis())[1].alles).lower()
        for woord in ("snapshot", "live", "realtime", "algoritme"):
            self.assertNotIn(woord, z)

    def test_gebied_heeft_geen_verdeling(self):
        cfg = cfg_basis()
        bron = [{"woonplaats": "Delft", "bestand": "vbo_delft.json", "ophaaldatum": "2026-08-04"}]
        panden = [{"uitgesloten": False, "categorieen": ["A", "C"], "leadscore": 12, "aantal_vbo": 3},
                  {"uitgesloten": False, "categorieen": ["C"], "leadscore": 4, "aantal_vbo": 5},
                  {"uitgesloten": True, "categorieen": [], "leadscore": 0, "aantal_vbo": 2}]
        payload = {"gebied": "Delft", "bron": bron, "kantoor": bd.kantoor("Delft", bron, panden, 1, cfg)}
        html = bd.brein_html(bd.brein_blok(payload, cfg, "2026-08"))
        p = Pagina(html)
        self.assertNotIn("stap-verdeling", [s["id"] for s in p.stappen])
        z = tekst(p.zichtbaar)
        self.assertIn("Verblijfsobjecten10", z)
        self.assertIn("in Delft, uit de BAG van 4 augustus 2026", z)
        self.assertIn("Score 8 of hoger1", z)
        self.assertIn("hoogst scorende panden van Delft", z)
        self.assertNotIn("—", tekst(p.alles).split("Werklijst")[-1][:3])


@unittest.skipUnless(DELFT.is_file(), f"{DELFT} ontbreekt")
class DelftMetAndereConfig(unittest.TestCase):
    """VA-98 crit. 4: een bouw van Delft met een andere drempel; de aantallen zijn die van panden_delft.json."""

    def test_drempel_en_aantallen(self):
        cfg = cfg_basis()
        cfg["doelgebied"] = {"steden": ["Delft"], "provincies": [], "nederland": False}
        cfg["drempels"]["score_min_voor_werklijst"] = 11
        cfg["score"]["min_3_adressen"] = 6
        with mock.patch.object(bd, "load_config", return_value=cfg):
            payload = bd.bouw_payload()
            html = bd.bouw_brein(payload, cfg)
        panden = json.loads(DELFT.read_text(encoding="utf-8"))
        act = [p for p in panden if not p["uitgesloten"] and p["categorieen"]]
        z = tekst(Pagina(html).zichtbaar)
        self.assertIn(f"Verblijfsobjecten{bd.nl_getal(sum(p['aantal_vbo'] for p in panden))}", z)
        self.assertIn(f"Panden{bd.nl_getal(len(panden))}", z)
        self.assertIn(f"Categorie A–E{bd.nl_getal(len(act))}", z)
        self.assertIn(f"Score 11 of hoger{bd.nl_getal(sum(1 for p in act if p['leadscore'] >= 11))}", z)
        self.assertIn("3 of meer adressen+6", z)
        # en gelijk aan de kerncijfers van het dashboard voor dezelfde bouw
        self.assertEqual(payload["kpi"][3]["v"], bd.nl_getal(sum(1 for p in act if p["leadscore"] >= 11)))


@unittest.skipUnless(NL.is_file(), f"{NL} ontbreekt")
class NederlandGelijkAanHetDashboard(unittest.TestCase):
    """VA-98 crit. 4: de aantallen op deze pagina zijn die van het dashboard voor dezelfde bouw."""

    def test_kerncijfers_en_voorraad(self):
        cfg = cfg_basis()
        cfg["doelgebied"]["nederland"] = True
        with mock.patch.object(bd, "load_config", return_value=cfg):
            payload = bd.bouw_payload()
        z = tekst(Pagina(bd.bouw_brein(payload, cfg)).zichtbaar)
        kpi = [k["v"] for k in payload["kpi"]]
        for naam, v in zip(("Verblijfsobjecten", "Panden", "Categorie A–E", "of hoger"), kpi):
            self.assertIn(naam + v, z)
        for c in payload["cats"]:
            self.assertIn(f"{c['k']} {bd.nl_getal(c['n'])}", z)


class Grootte(unittest.TestCase):
    """VA-98 crit. 6: een eigen bestand, onder 1.000.000 bytes, zonder externe bron."""

    @unittest.skipUnless(GEBOUWD.is_file(), f"{GEBOUWD} ontbreekt")
    def test_gebouwde_pagina(self):
        b = GEBOUWD.read_bytes()
        self.assertLess(len(b), 1_000_000)
        self.assertNotRegex(b.decode("utf-8"), r'(src|href)="(https?:)?//')
        self.assertNotIn("<link", b.decode("utf-8"))

    def test_sjabloon(self):
        html, _ = bouw(cfg_basis())
        self.assertLess(len(html.encode("utf-8")), 1_000_000)
        self.assertNotRegex(html, r"https?://")


class BreinAchterDeLogin(ts.Server):
    """VA-98 crit. 1: brein.html alleen met een sessie, net als het dashboard."""

    def setUp(self):
        super().setUp()
        self.brein = "<!doctype html><title>Brein</title>geheim-brein".encode("utf-8")
        (self.design / "brein.html").write_bytes(self.brein)

    def test_uitgelogd_de_inlogpagina(self):
        status, koppen, body = self.vraag("GET", "/brein.html")
        self.assertEqual(status, 303)
        self.assertEqual(koppen["Location"], "/login")
        self.assertNotIn(b"geheim-brein", body)

    def test_ingelogd_de_pagina(self):
        _, koppen, _ = self.inloggen()
        waarde, _ = self.cookie_uit(koppen)
        status, _, body = self.vraag("GET", "/brein.html", cookie=waarde)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.brein)


if __name__ == "__main__":
    unittest.main()
