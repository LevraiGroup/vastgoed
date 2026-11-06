"""
VA-3, dashboard: build_dashboard.py leest panden_<gebied>.bron.json en zegt welke
snapshot(s) het gebruikte, of dat de bron onbekend is. Geen data nodig: alles draait
in een tijdelijke map.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402


def hard(datum: str) -> str:
    """'4 aug 2026' zoals nl_datum hem geeft: met harde spaties (VA-12)."""
    return datum.replace(" ", bd.NBSP)


class NlDatum(unittest.TestCase):
    def test_iso_naar_nederlands(self):
        self.assertEqual(bd.nl_datum("2026-08-04"), hard("4 aug 2026"))
        self.assertEqual(bd.nl_datum("2026-03-15"), hard("15 mrt 2026"))
        self.assertEqual(bd.nl_datum("2026-10-01"), hard("1 okt 2026"))
        self.assertNotIn(" ", bd.nl_datum("2026-08-04"))

    def test_onbekend(self):
        for waarde in (None, "", "augustus", "2026-13-01", "2026-02-31"):
            self.assertEqual(bd.nl_datum(waarde), "ophaaldatum onbekend", waarde)


class LeesBron(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.map = Path(self._tmp.name)
        self.panden = self.map / "panden_delft.json"
        self.panden.write_text("[]", encoding="utf-8")
        self.bron = self.map / "panden_delft.bron.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _schrijf_bron(self, inhoud):
        self.bron.write_text(json.dumps(inhoud), encoding="utf-8")
        # De .bron.json hoort na panden_*.json geschreven te zijn.
        later = self.panden.stat().st_mtime + 1
        os.utime(self.bron, (later, later))

    def test_ontbreekt(self):
        bron, reden = bd.lees_bron(self.panden)
        self.assertIsNone(bron)
        self.assertIn("ontbreekt", reden)
        self.assertEqual(bd.bron_regels(bron), [bd.BRON_ONBEKEND])

    def test_geldig(self):
        inhoud = [{"woonplaats": "Delft", "bestand": "vbo_delft.json", "ophaaldatum": "2026-08-04"}]
        self._schrijf_bron(inhoud)
        bron, reden = bd.lees_bron(self.panden)
        self.assertEqual(bron, inhoud)
        self.assertEqual(reden, "")
        self.assertEqual(bd.bron_regels(bron), [f"Delft: vbo_delft.json (opgehaald {hard('4 aug 2026')})"])

    def test_meerdere_woonplaatsen_en_onbekende_datum(self):
        inhoud = [
            {"woonplaats": "Delft", "bestand": "vbo_delft.json", "ophaaldatum": "2026-08-04"},
            {"woonplaats": "Rijswijk", "bestand": "vbo_rijswijk.json", "ophaaldatum": None},
        ]
        self._schrijf_bron(inhoud)
        bron, _ = bd.lees_bron(self.panden)
        self.assertEqual(bd.bron_regels(bron), [
            f"Delft: vbo_delft.json (opgehaald {hard('4 aug 2026')})",
            "Rijswijk: vbo_rijswijk.json (opgehaald ophaaldatum onbekend)",
        ])

    def test_ouder_dan_panden_telt_als_onbekend(self):
        self._schrijf_bron([{"woonplaats": "Delft", "bestand": "vbo_delft.json",
                             "ophaaldatum": "2026-08-04"}])
        nu = time.time() + 10
        os.utime(self.panden, (nu, nu))
        bron, reden = bd.lees_bron(self.panden)
        self.assertIsNone(bron)
        self.assertIn("ouder dan", reden)

    def test_ongeldige_inhoud(self):
        for inhoud in ({"x": 1}, [], [{"woonplaats": "Delft"}]):
            self._schrijf_bron(inhoud)
            bron, reden = bd.lees_bron(self.panden)
            self.assertIsNone(bron, inhoud)
            self.assertIn("geen geldige", reden)

    def test_onleesbaar(self):
        self.bron.write_text("{kapot", encoding="utf-8")
        later = self.panden.stat().st_mtime + 1
        os.utime(self.bron, (later, later))
        bron, reden = bd.lees_bron(self.panden)
        self.assertIsNone(bron)
        self.assertIn("niet leesbaar", reden)


if __name__ == "__main__":
    unittest.main()
