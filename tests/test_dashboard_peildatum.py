"""
VA-12: de peildatum in de kop van het dashboard komt uit de bron-snapshot(s), niet uit
het sjabloon. Geen data nodig.
"""
import re
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402

N = bd.NBSP


def snap(woonplaats, datum):
    return {"woonplaats": woonplaats, "bestand": f"vbo_{woonplaats.lower()}.json",
            "ophaaldatum": datum}


def pill(html: str) -> str:
    """De tekst van de peildatum-pil in de kop."""
    m = re.search(r'<div class="pill"[^>]*>(Peildatum[^<]*)</div>', html)
    assert m, "geen peildatum-pil in de kop"
    return m.group(1)


def payload(bron, reden=""):
    """Het kleinste payload waarmee render() de kop vult."""
    return {"gebied": "Delft", "bron": bron,
            "peildatum": bd.peildatum(bron), "peildatum_tip": bd.peildatum_tip(bron, reden)}


class Peildatum(unittest.TestCase):
    def test_augustus_delft(self):
        # Criterium 1: Delfts augustus-data blijft 4 aug 2026 tonen.
        self.assertEqual(bd.peildatum([snap("Delft", "2026-08-04")]),
                         f"Peildatum 4{N}aug{N}2026")

    def test_nieuwere_snapshot(self):
        # Criterium 2: een andere ophaaldatum verschijnt, in hetzelfde formaat.
        self.assertEqual(bd.peildatum([snap("Delft", "2026-11-06")]),
                         f"Peildatum 6{N}nov{N}2026")

    def test_meerdere_woonplaatsen_zelfde_datum(self):
        bron = [snap("Delft", "2026-11-06"), snap("Rijswijk", "2026-11-06")]
        self.assertEqual(bd.peildatum(bron), f"Peildatum 6{N}nov{N}2026")
        # De datum geldt voor allemaal; de tip noemt de woonplaatsen waarvoor hij geldt.
        self.assertIn("Rijswijk", bd.peildatum_tip(bron))

    def test_meerdere_woonplaatsen_verschillende_datums(self):
        # Criterium 5: nooit één datum alsof die voor allemaal geldt.
        bron = [snap("Delft", "2026-08-04"), snap("Den Haag", "2026-11-06"),
                snap("Rijswijk", "2026-09-15")]
        tekst = bd.peildatum(bron)
        self.assertEqual(tekst, f"Peildatum 4{N}aug – 6{N}nov{N}2026")
        tip = bd.peildatum_tip(bron)
        for d in ("4 aug 2026", "6 nov 2026", "15 sep 2026"):
            self.assertIn(d.replace(" ", N), tip)
        for w in ("Delft", "Den Haag", "Rijswijk"):
            self.assertIn(w, tip)

    def test_verschillende_jaren(self):
        bron = [snap("Delft", "2026-12-30"), snap("Den Haag", "2027-01-05")]
        self.assertEqual(bd.peildatum(bron),
                         f"Peildatum 30{N}dec{N}2026 – 5{N}jan{N}2027")

    def test_bron_onbekend(self):
        # Criterium 4: geen datum, ook niet die van vandaag.
        vandaag = date.today()
        gevallen = [None, [], [snap("Delft", None)], [snap("Delft", "kapot")],
                    [snap("Delft", "2026-08-04"), snap("Rijswijk", None)]]
        for bron in gevallen:
            tekst = bd.peildatum(bron)
            self.assertEqual(tekst, bd.PEILDATUM_ONBEKEND, bron)
            self.assertNotRegex(tekst, r"\d", bron)
            self.assertNotIn(bd._nl(vandaag), tekst)
        tip = bd.peildatum_tip(None, "panden_delft.bron.json ontbreekt")
        self.assertIn("bron onbekend", tip)
        self.assertIn("ontbreekt", tip)

    def test_een_datum_heeft_geen_tooltip(self):
        self.assertEqual(bd.peildatum_tip([snap("Delft", "2026-08-04")]), "")


class Render(unittest.TestCase):
    def test_kop_volgt_de_bron(self):
        gevallen = [
            ([snap("Delft", "2026-08-04")], f"Peildatum 4{N}aug{N}2026"),
            ([snap("Delft", "2026-11-06")], f"Peildatum 6{N}nov{N}2026"),
            ([snap("Delft", "2026-08-04"), snap("Den Haag", "2026-11-06")],
             f"Peildatum 4{N}aug – 6{N}nov{N}2026"),
            (None, "Peildatum onbekend"),
        ]
        for bron, verwacht in gevallen:
            html = bd.render(payload(bron, "panden_delft.bron.json ontbreekt"))
            self.assertEqual(pill(html), verwacht, bron)
            self.assertNotIn("__PEIL", html)

    def test_tooltip_alleen_als_nodig(self):
        een = bd.render(payload([snap("Delft", "2026-08-04")]))
        self.assertNotRegex(een, r'class="pill" data-tip=')
        twee = bd.render(payload([snap("Delft", "2026-08-04"), snap("Den Haag", "2026-11-06")]))
        self.assertRegex(twee, r'<div class="pill" data-tip="Delft: [^"]*Den Haag: [^"]*">')

    def test_sjabloon_bevat_geen_vaste_datum(self):
        # Criterium 3: geen letterlijke datum in build_dashboard.py.
        bron = Path(bd.__file__).read_text(encoding="utf-8")
        maand = "|".join(bd.MAANDEN)
        self.assertNotRegex(bron, r"\d{4}-\d{2}-\d{2}")
        self.assertNotRegex(bron, rf"\b\d{{1,2}}\s+({maand})\b")
        self.assertNotRegex(bron, r"\b20\d\d\b")


if __name__ == "__main__":
    unittest.main()
