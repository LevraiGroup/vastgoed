"""
VA-66: het dashboard opent altijd licht, ook als de computer op donkere modus staat
(Ayman 2026-11-09: "Altijd licht openen"). De knop Thema wisselt daarna gewoon.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402


class AltijdLicht(unittest.TestCase):
    def test_pagina_start_licht(self):
        # Met data-theme="light" op <html> kan prefers-color-scheme het begin niet kiezen:
        # het donkere @media-blok geldt alleen voor :root:not([data-theme="light"]).
        html = re.search(r"<html[^>]*>", bd.TEMPLATE).group(0)
        self.assertIn('data-theme="light"', html)
        self.assertIn(':root:where(:not([data-theme="light"]))', bd.TEMPLATE)

    def test_niets_zet_het_thema_bij_het_laden_op_het_systeem(self):
        # Alleen de knop Thema schrijft data-theme; geen code leest het systeem om te starten.
        schrijvers = re.findall(r'setAttribute\(\s*"data-theme"', bd.TEMPLATE)
        self.assertEqual(len(schrijvers), 1)
        self.assertNotRegex(bd.TEMPLATE, r"localStorage")

    def test_knop_wisselt(self):
        self.assertIn('root.setAttribute("data-theme",dark?"light":"dark")', bd.TEMPLATE)


if __name__ == "__main__":
    unittest.main()
