"""
VA-106: één knop "Uitloggen" onderaan de navy zijbalk, een formulier dat POST naar /uitloggen (VA-50).
Criterium 1 en 2: de opmaak in de gebouwde pagina, en dat precies dat formulier, gestuurd naar serve.py,
uitlogt: daarna de inlogpagina, en dezelfde cookie krijgt opnieuw de inlogpagina.
"""
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
sys.path.insert(0, str(HIER))

import build_dashboard as bd  # noqa: E402
from test_serve import Server  # noqa: E402

KNOP = '<form class="uitlog" method="post" action="/uitloggen"><button class="toggle" type="submit">Uitloggen</button></form>'


def gebouwd():
    return bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                      "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})


class Formulieren(HTMLParser):
    """Elk formulier in de zijbalk: method, action en de tekst van zijn knop."""

    def __init__(self, html):
        super().__init__()
        self.zijbalk = self.voet = False
        self.formulieren, self._knop = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "aside" and "side" in (a.get("class") or "").split():
            self.zijbalk = True
        if self.zijbalk and tag == "div" and a.get("class") == "side-voet":
            self.voet = True
        if self.voet and tag == "form":
            self.formulieren.append({"method": a.get("method"), "action": a.get("action"), "knop": ""})
        if self.voet and tag == "button" and self.formulieren:
            self._knop = a

    def handle_endtag(self, tag):
        if tag == "aside":
            self.zijbalk = self.voet = False
        if tag == "button":
            self._knop = None

    def handle_data(self, data):
        if self._knop is not None and self.formulieren:
            self.formulieren[-1]["knop"] += data
            self.formulieren[-1]["type"] = self._knop.get("type")


class Opmaak(unittest.TestCase):
    def test_een_knop_onderaan_de_zijbalk(self):
        f = Formulieren(gebouwd()).formulieren
        self.assertEqual(f, [{"method": "post", "action": "/uitloggen", "knop": "Uitloggen", "type": "submit"}])
        self.assertEqual(bd.TEMPLATE.count(KNOP), 1)

    def test_lumis_woord(self):
        # Lumi, design/copy-va61-62.md: "Uitloggen", onderaan de zijbalk.
        tabel = (HIER.parent / "design" / "copy-va61-62.md").read_text(encoding="utf-8")
        self.assertIn("| Uitloggen | Uitloggen |", tabel)

    def test_zelfde_stijl_als_thema(self):
        # Dezelfde knopstijl als Thema: wit op navy, met een zichtbare focusrand.
        self.assertIn(".toggle:focus-visible{outline:2px solid #fff;outline-offset:2px}", bd.TEMPLATE)
        self.assertIn(".uitlog{margin:0}", bd.TEMPLATE)


class UitloggenMetHetFormulier(Server):
    """Het formulier van de pagina, zoals een browser het stuurt, logt uit bij serve.py."""

    def test_formulier_logt_uit(self):
        f = Formulieren(gebouwd()).formulieren[0]
        waarde, _ = self.cookie_uit(self.inloggen()[1])
        self.assertEqual(self.vraag("GET", "/", cookie=waarde)[0], 200)
        status, koppen, _ = self.vraag(f["method"].upper(), f["action"], body={}, cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/login"))
        self.assertIn("Max-Age=0", koppen["Set-Cookie"])
        status, koppen, body = self.vraag("GET", "/", cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/login"))
        self.assertNotIn(b"Dashboard", body)


if __name__ == "__main__":
    unittest.main()
