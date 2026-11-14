"""
VA-79: de CSV's zeggen 'ja'/'nee' in visuele_controle en eerder_geselecteerd, nooit Pythons
True/False (of 1/0). JSON houdt true/false. Wie de kolommen uit een CSV terugleest, leest het
nieuwe 'ja'/'nee' en het 'True'/'False' van de vastgelegde augustusbestanden hetzelfde.

Alleen standaardbibliotheek plus de eigen modules van het project; schrijft alleen in een
tijdelijke map.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import run_proef  # noqa: E402
import selectie  # noqa: E402

VASTGELEGD = PROJECT / "output" / "mastervoorraad_delft.csv"


def pand(**waarden) -> dict:
    p = {"bag_pand_id": "0503100000026198", "gekoppelde_adressen": ["a", "b"],
         "opp_per_functie": {"woon": 1.0}, "visuele_controle": False, "eerder_geselecteerd": False}
    p.update(waarden)
    return p


def schrijf_en_lees(panden: list[dict]) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        pad = Path(tmp) / "proef.csv"
        with open(pad, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=run_proef.KOLOMMEN + ["bag_viewer_url"], delimiter=";")
            w.writeheader()
            for p in panden:
                w.writerow(run_proef.csv_rij(p))
        with open(pad, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh, delimiter=";"))


class CsvSchrijftJaNee(unittest.TestCase):
    def test_beide_kolommen_ja_en_nee(self):
        rijen = schrijf_en_lees([pand(), pand(visuele_controle=True, eerder_geselecteerd=True),
                                 pand(visuele_controle=True)])
        self.assertEqual([(r["visuele_controle"], r["eerder_geselecteerd"]) for r in rijen],
                         [("nee", "nee"), ("ja", "ja"), ("ja", "nee")])

    def test_nooit_true_false_een_of_nul(self):
        for waarde in (False, True, "False", "True", "ja", "nee"):
            r = run_proef.csv_rij(pand(visuele_controle=waarde, eerder_geselecteerd=waarde))
            for kolom in selectie.JANEE_KOLOMMEN:
                self.assertIn(r[kolom], ("ja", "nee"), (waarde, kolom))

    def test_ontbrekende_waarde_is_nee(self):
        p = pand()
        del p["visuele_controle"], p["eerder_geselecteerd"]
        r = run_proef.csv_rij(p)
        self.assertEqual((r["visuele_controle"], r["eerder_geselecteerd"]), ("nee", "nee"))

    def test_andere_kolommen_zoals_voorheen(self):
        r = run_proef.csv_rij(pand())
        self.assertEqual(r["gekoppelde_adressen"], "a | b")
        self.assertEqual(r["opp_per_functie"], "woon=1.0")

    def test_verwerk_pand_houdt_bools_voor_json(self):
        p = selectie.verwerk_pand(selectie.aggregeer([{
            "identificatie": "1", "pandidentificatie": "0503100000000001", "gebruiksdoel": "woonfunctie",
            "oppervlakte": 80, "bouwjaar": 1900, "status": "Verblijfsobject in gebruik"}])[0],
            selectie.load_config(), {}, "DE", "2026-08-04")
        self.assertIs(p["visuele_controle"], False)
        self.assertIs(p["eerder_geselecteerd"], False)
        self.assertIn('"visuele_controle": false', json.dumps(p))


class CsvTerugLezen(unittest.TestCase):
    """VA-79 crit. 2: 'ja'/'nee' en het oude 'True'/'False' worden hetzelfde gelezen."""

    def test_nieuw_en_oud_gelijk(self):
        for nieuw, oud, waarde in (("ja", "True", True), ("nee", "False", False)):
            self.assertIs(selectie.lees_janee(nieuw), waarde)
            self.assertIs(selectie.lees_janee(oud), waarde)
        self.assertIs(selectie.lees_janee(" Nee "), False)
        self.assertIs(selectie.lees_janee(True), True)

    def test_onbekende_waarde_is_een_fout(self):
        for waarde in ("", "1", "0", "misschien", None):
            with self.assertRaises(ValueError):
                selectie.lees_janee(waarde)

    @unittest.skipUnless(VASTGELEGD.exists(), f"{VASTGELEGD.name} ontbreekt")
    def test_vastgelegde_augustusbestand_leest_als_nee(self):
        with open(VASTGELEGD, encoding="utf-8-sig", newline="") as fh:
            rijen = list(csv.DictReader(fh, delimiter=";"))
        for kolom in selectie.JANEE_KOLOMMEN:
            self.assertEqual({r[kolom] for r in rijen}, {"False"})  # van vóór VA-79
            self.assertEqual({selectie.lees_janee(r[kolom]) for r in rijen}, {False})

    def test_nieuwe_csv_leest_terug(self):
        rijen = schrijf_en_lees([pand(), pand(eerder_geselecteerd=True)])
        self.assertEqual([selectie.lees_janee(r["eerder_geselecteerd"]) for r in rijen], [False, True])


if __name__ == "__main__":
    unittest.main()
