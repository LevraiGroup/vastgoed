"""
Eenheidstests voor selectie.py die geen data nodig hebben.

Alleen standaardbibliotheek plus de eigen modules van het project; draait onder
`python -m unittest discover tests` en onder `python -m pytest tests`.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from selectie import split_gebruiksdoel  # noqa: E402


class TestSplitGebruiksdoel(unittest.TestCase):
    """Huisregel: 'gebruiksdoel' is meerwaardig, altijd splitsen op komma."""

    def test_winkel_en_woon_worden_beide_teruggegeven(self):
        self.assertEqual(
            split_gebruiksdoel("winkelfunctie,woonfunctie"),
            ["winkelfunctie", "woonfunctie"],
        )

    def test_enkele_waarde(self):
        self.assertEqual(split_gebruiksdoel("woonfunctie"), ["woonfunctie"])

    def test_leeg_of_none_geeft_lege_lijst(self):
        self.assertEqual(split_gebruiksdoel(""), [])
        self.assertEqual(split_gebruiksdoel(None), [])

    def test_spaties_en_lege_delen_vallen_weg(self):
        self.assertEqual(
            split_gebruiksdoel(" winkelfunctie , ,woonfunctie "),
            ["winkelfunctie", "woonfunctie"],
        )


if __name__ == "__main__":
    unittest.main()
