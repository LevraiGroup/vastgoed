"""
VA-78: postcode, huisnummer, huisletter, woonplaats, x,y en gemeentecode van een pand komen van
de VBO van zijn hoofdadres (het eerste adres in gesorteerde volgorde), niet van de eerste VBO in
invoervolgorde. Twee VBO's met hetzelfde adres: de laagste identificatie. Een pand zonder adres:
de eerste VBO, zoals voorheen. Bouwjaar en pandstatus blijven van de eerste VBO.

De JSON-route (verwerk()) en de SQLite-route (stroom_panden()) geven hetzelfde. Alleen
standaardbibliotheek; schrijft alleen in een tijdelijke map.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import selectie  # noqa: E402
import snapshots  # noqa: E402

PAND = "0503100000026198"
VELDEN = ("postcode", "huisnummer", "huisletter", "x", "y", "woonplaats", "gemeentecode")
KOLOMMEN = {**snapshots.KOLOMMEN_STANDAARD, "gemeentecode": "gemeentecode"}


def vbo(ident, straat, nr, letter, postcode, woonplaats, gemeente, x, bouwjaar=1900,
        pandstatus="Pand in gebruik"):
    return {"identificatie": ident, "rdf_seealso": "", "oppervlakte": 60, "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": "woonfunctie", "openbare_ruimte": straat, "huisnummer": nr, "huisletter": letter,
            "toevoeging": "", "postcode": postcode, "woonplaats": woonplaats, "bouwjaar": bouwjaar,
            "pandidentificatie": PAND, "pandstatus": pandstatus, "_x": x, "_y": 447000.0 + x,
            "gemeentecode": gemeente}


def verwacht(rij: dict) -> dict:
    return {"postcode": rij["postcode"], "huisnummer": rij["huisnummer"], "huisletter": rij["huisletter"],
            "x": rij["_x"], "y": rij["_y"], "woonplaats": rij["woonplaats"], "gemeentecode": rij["gemeentecode"]}


class HoofdadresVbo(unittest.TestCase):
    def beide_routes(self, rijen: list[dict]) -> dict:
        """Het pand langs de JSON-route en de SQLite-route; ze moeten gelijk zijn."""
        cfg = selectie.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            sq = snapshots.schrijf_sqlite("Delft", "delft", iter(rijen), map_, datetime(2026, 8, 4, 12),
                                          kolommen=KOLOMMEN)
            js_pad = map_ / "vbo_delft_2026-08-04.json"
            js_pad.write_text(json.dumps(rijen), encoding="utf-8")
            js = snapshots.Snapshot("Delft", js_pad, "2026-08-04", 1, "meta", "json")
            via_json = selectie.verwerk("Delft", cfg, gekozen=[js])
            via_stroom = list(selectie.stroom_panden([sq], cfg, "Delft"))
        self.assertEqual(len(via_json), 1)
        self.assertEqual(via_json, via_stroom)
        return via_json[0]

    def test_drie_vbos_buiten_gesorteerde_volgorde(self):
        # Zoals Hippolytusbuurt 1 / Nieuwstraat 38: de eerste VBO is niet die van het hoofdadres.
        rijen = [
            vbo("0503010000000003", "Nieuwstraat", 38, "", "2611HK", "Delft", "0503", 84010.0,
                bouwjaar=1650, pandstatus="Pand buiten gebruik"),
            vbo("0503010000000001", "Hippolytusbuurt", 1, "A", "2611HM", "Den Hoorn", "1621", 84020.0,
                bouwjaar=1700),
            vbo("0503010000000002", "Oude Delft", 5, "", "2611BA", "Delft", "0503", 84030.0),
        ]
        pand = self.beide_routes(rijen)
        self.assertEqual(pand["hoofdadres"], "Hippolytusbuurt 1A, 2611HM Den Hoorn")
        self.assertEqual({k: pand[k] for k in VELDEN}, verwacht(rijen[1]))
        self.assertIn(pand["postcode"], pand["hoofdadres"])
        # Bouwjaar en pandstatus blijven van de eerste VBO (crit. 1).
        self.assertEqual((pand["bouwjaar"], pand["pandstatus"]), (1650, "Pand buiten gebruik"))

    def test_zelfde_adres_laagste_identificatie(self):
        rijen = [
            vbo("0503010000000009", "Zuidwal", 2, "", "2611AA", "Delft", "0503", 84100.0),
            vbo("0503010000000005", "Achterom", 7, "", "2611PL", "Delft", "0503", 84200.0),
            vbo("0503010000000004", "Achterom", 7, "", "2611PL", "Delft", "0503", 84300.0),
        ]
        pand = self.beide_routes(rijen)
        self.assertEqual(pand["hoofdadres"], "Achterom 7, 2611PL Delft")
        self.assertEqual({k: pand[k] for k in VELDEN}, verwacht(rijen[2]))

    def test_zonder_adres_de_eerste_vbo(self):
        rijen = [
            vbo("0503010000000008", "", None, "", "", "", "0503", 84400.0),
            vbo("0503010000000007", "", None, "", "", "", "1621", 84500.0),
        ]
        pand = self.beide_routes(rijen)
        self.assertEqual((pand["hoofdadres"], pand["aantal_adressen"]), ("", 0))
        self.assertEqual({k: pand[k] for k in VELDEN}, verwacht(rijen[0]))


AUGUSTUS = selectie.DATA / "vbo_delft.json"


@unittest.skipUnless(AUGUSTUS.is_file(), f"{AUGUSTUS} ontbreekt; Delft-tests van VA-78 overgeslagen")
class DelftAugustus(unittest.TestCase):
    """VA-78 crit. 3 en 7 op de augustusdata van Delft, alleen in het geheugen en een tijdelijke map."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = selectie.load_config()
        cls.panden = selectie.verwerk(["Delft"], cls.cfg, "Delft", snapshot="vbo_delft.json")
        with open(AUGUSTUS, encoding="utf-8") as fh:
            cls.rijen = [r for r in json.load(fh) if r.get("pandidentificatie") == PAND]

    def test_hippolytusbuurt_1(self):
        pand = next(p for p in self.panden if p["bag_pand_id"] == PAND)
        vbo_1 = [r for r in self.rijen if r["openbare_ruimte"] == "Hippolytusbuurt" and r["huisnummer"] == 1
                 and not r.get("huisletter") and not r.get("toevoeging")]
        self.assertEqual(len(vbo_1), 1)
        self.assertEqual(pand["hoofdadres"], "Hippolytusbuurt 1, 2611HM Delft")
        self.assertEqual((pand["postcode"], pand["huisnummer"]), ("2611HM", 1))
        self.assertEqual((pand["x"], pand["y"]), (vbo_1[0]["_x"], vbo_1[0]["_y"]))

    def test_postcode_en_woonplaats_staan_in_het_hoofdadres(self):
        for p in self.panden:
            if p["postcode"] and p["hoofdadres"]:
                self.assertIn(p["postcode"], p["hoofdadres"], p["bag_pand_id"])
            if p["woonplaats"] and p["hoofdadres"]:
                self.assertIn(p["woonplaats"], p["hoofdadres"], p["bag_pand_id"])

    def test_dashboard_payload(self):
        # Crit. 7: in de gebouwde payload staat de postcode van elke kaart in zijn hoofdadres (de titel).
        import copy
        from unittest import mock
        import build_dashboard as bd
        delft = copy.deepcopy(self.cfg)
        delft["doelgebied"]["nederland"] = False
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            (map_ / "panden_delft.json").write_text(json.dumps(self.panden, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(bd, "DATA", map_), mock.patch.object(bd, "load_config", lambda: delft):
                payload = bd.bouw_payload()
        leads = payload["leads"]
        self.assertEqual(len(leads), 20)
        for lead in leads:
            titel = lead["detail"]["titel"]
            if lead["p"]:
                self.assertIn(lead["p"], titel, lead["id"])
            else:
                # Een adres zonder postcode in de BAG: dan staat er ook geen in de titel.
                self.assertNotRegex(titel, r"\b\d{4} ?[A-Z]{2}\b", lead["id"])


if __name__ == "__main__":
    unittest.main()
