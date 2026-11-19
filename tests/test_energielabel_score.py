"""VA-101: het energielabel in de score (+2 voor E, F, G of geen label), en telt_mee_vanaf (Ayman 2026-11-19)."""
import copy
import unittest

import selectie


def cfg(telt_mee=True, vanaf=""):
    c = copy.deepcopy(selectie.load_config())
    c["bronnen"]["energielabel"]["telt_mee"] = telt_mee
    c["bronnen"]["energielabel"]["telt_mee_vanaf"] = vanaf
    return c


def pand(label, peil="2026-12-01"):
    return {"energielabel": label, "datapeildatum": peil}


class EnergielabelPunten(unittest.TestCase):
    def test_e_f_g_en_geen_label_krijgen_de_punten(self):
        for label in ("E", "F", "G", None):
            status, behaald, _, punten = selectie._sig_energielabel(pand(label), cfg())
            self.assertEqual((status, behaald), ("behaald", True), label)
            self.assertEqual(punten, 2)

    def test_a_tot_d_krijgen_niets(self):
        for label in ("A+++", "A", "B", "C", "D"):
            status, behaald, _, _ = selectie._sig_energielabel(pand(label), cfg())
            self.assertEqual((status, behaald), ("niet", False), label)

    def test_onbekend_blijft_inactief(self):
        status, behaald, _, _ = selectie._sig_energielabel({"datapeildatum": "2026-12-01"}, cfg())
        self.assertEqual((status, behaald), ("inactief", False))

    def test_telt_mee_uit_verschuift_niets(self):
        status, behaald, uitleg, _ = selectie._sig_energielabel(pand("G"), cfg(telt_mee=False))
        self.assertEqual((status, behaald), ("inactief", False))
        self.assertIn("telt nog niet mee", uitleg)

    def test_schaal_max_blijft_26(self):
        self.assertEqual(selectie.load_config()["score"]["schaal_max"], 26)


class TeltMeeVanaf(unittest.TestCase):
    def test_voor_de_ingangsmaand_telt_het_niet(self):
        status, behaald, uitleg, _ = selectie._sig_energielabel(pand("G", "2026-11-01"), cfg(vanaf="2026-12"))
        self.assertEqual((status, behaald), ("inactief", False))
        self.assertIn("telt mee vanaf december 2026", uitleg)

    def test_vanaf_de_ingangsmaand_telt_het(self):
        for peil in ("2026-12-01", "2027-01-01"):
            status, behaald, _, _ = selectie._sig_energielabel(pand("G", peil), cfg(vanaf="2026-12"))
            self.assertEqual((status, behaald), ("behaald", True), peil)

    def test_leeg_telt_meteen(self):
        status, _, _, _ = selectie._sig_energielabel(pand("F", "2026-11-01"), cfg(vanaf=""))
        self.assertEqual(status, "behaald")

    def test_verkeerde_maand_stopt(self):
        with self.assertRaises(ValueError):
            selectie._sig_energielabel(pand("F"), cfg(vanaf="december"))

    def test_de_gecommitte_config_begint_in_december(self):
        self.assertEqual(selectie.telt_mee_vanaf(selectie.load_config()), "2026-12")


if __name__ == "__main__":
    unittest.main()
