"""
VA-36: de mastervoorraad uit een SQLite-snapshot, pand voor pand, zonder alle VBO's in het
geheugen. Op de augustusdata van Delft geeft die route per pand precies hetzelfde als de
JSON-route, en de VA-2-cijfers en kolomvolgordes blijven staan.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import selectie  # noqa: E402
import snapshots  # noqa: E402

AUGUSTUS = selectie.DATA / "vbo_delft.json"


def gegenereerd(n_panden=50):
    """Kleine VBO-rijen in WFS-vorm, met panden van meer VBO's en een VBO zonder pand."""
    rijen = []
    for p in range(n_panden):
        for v in range(1 + p % 4):
            rijen.append({"identificatie": f"0503010000{p:04d}{v:02d}", "rdf_seealso": "",
                          "oppervlakte": 40 + v, "status": "Verblijfsobject in gebruik",
                          "gebruiksdoel": "woonfunctie,winkelfunctie" if v == 0 and p % 3 == 0 else "woonfunctie",
                          "openbare_ruimte": "Straat", "huisnummer": p + 1, "huisletter": "" if v == 0 else "ABC"[v - 1],
                          "toevoeging": "", "postcode": "2611AA", "woonplaats": "Delft", "bouwjaar": 1890 + p,
                          "pandidentificatie": f"05031000000{(n_panden - p):05d}", "pandstatus": "Pand in gebruik",
                          "_x": 84000.0 + p, "_y": 447000.0})
    rijen.append(dict(rijen[0], identificatie="0503010000999999", pandidentificatie=""))
    return rijen


class Gelijk(unittest.TestCase):
    def snapshots_van(self, rijen, map_):
        snap = snapshots.schrijf_sqlite("Delft", "delft", iter(rijen), map_, datetime(2026, 8, 4, 12))
        js = map_ / "vbo_delft_2026-08-04.json"
        js.write_text(json.dumps(rijen), encoding="utf-8")
        return snap, snapshots.Snapshot("Delft", js, "2026-08-04", 1, "meta", "json")

    def vergelijk(self, rijen):
        cfg = selectie.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            sq, js = self.snapshots_van(rijen, Path(tmp))
            via_json = selectie.verwerk("Delft", cfg, gekozen=[js])
            via_sqlite = selectie.verwerk("Delft", cfg, gekozen=[sq])
        sleutel = lambda p: p["bag_pand_id"]  # noqa: E731
        self.assertEqual(sorted(via_json, key=sleutel), sorted(via_sqlite, key=sleutel))
        return via_sqlite

    def test_gegenereerd(self):
        panden = self.vergelijk(gegenereerd())
        self.assertEqual(len(panden), 50)  # de VBO zonder pand telt niet mee
        self.assertEqual([p["bag_pand_id"] for p in panden], sorted(p["bag_pand_id"] for p in panden))

    def test_hoofdadres_vbo_wint_ook_in_sqlite(self):
        # VA-78: woonplaats, postcode, x,y komen van de VBO van het hoofdadres, niet van de eerste VBO.
        rijen = gegenereerd(3)
        rijen[1]["huisletter"] = "B"     # eerste VBO van pand 1: Straat 2B, niet meer het hoofdadres
        rijen[2]["postcode"] = "9999ZZ"  # tweede VBO van pand 1: Straat 2A, nu het hoofdadres
        panden = {p["bag_pand_id"]: p for p in self.vergelijk(rijen)}
        pand_1 = panden.pop("0503100000000002")
        self.assertEqual(pand_1["hoofdadres"], "Straat 2A, 9999ZZ Delft")
        self.assertEqual((pand_1["postcode"], pand_1["huisletter"], pand_1["x"]), ("9999ZZ", "A", 84001.0))
        self.assertTrue(all(p["postcode"] == "2611AA" for p in panden.values()))

    def test_meer_snapshots_met_hetzelfde_pand(self):
        # Vera, VA-36: een pand met VBO's in twee snapshots wordt samengevoegd, zoals op JSON.
        delft, rijswijk = gegenereerd(6), gegenereerd(6)
        for r in rijswijk:
            r["identificatie"] = "06" + r["identificatie"][2:]
            r["woonplaats"] = "Rijswijk"
            r["gebruiksdoel"] = "winkelfunctie"
        rijswijk = [r for r in rijswijk if r["pandidentificatie"]][:4] + [
            dict(rijswijk[0], identificatie="0603010000777777", pandidentificatie="05031000000999999")]
        cfg = selectie.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            sq_d = snapshots.schrijf_sqlite("Delft", "delft", iter(delft), map_, datetime(2026, 8, 4, 12))
            sq_r = snapshots.schrijf_sqlite("Rijswijk", "rijswijk", iter(rijswijk), map_, datetime(2026, 9, 1, 12))
            js_d, js_r = map_ / "d.json", map_ / "r.json"
            js_d.write_text(json.dumps(delft), encoding="utf-8")
            js_r.write_text(json.dumps(rijswijk), encoding="utf-8")
            js = [snapshots.Snapshot("Delft", js_d, "2026-08-04", 1, "meta", "json"),
                  snapshots.Snapshot("Rijswijk", js_r, "2026-09-01", 1, "meta", "json")]
            via_json = selectie.verwerk(["Delft", "Rijswijk"], cfg, gekozen=js)
            via_sqlite = selectie.verwerk(["Delft", "Rijswijk"], cfg, gekozen=[sq_d, sq_r])
        sleutel = lambda p: p["bag_pand_id"]  # noqa: E731
        self.assertEqual(sorted(via_json, key=sleutel), sorted(via_sqlite, key=sleutel))
        gedeeld = [p for p in via_sqlite if p["woonplaats"] == "Delft" and "winkelfunctie" in p["gebruiksdoelen"]
                   and p["aantal_vbo"] > 1 + int(p["bag_pand_id"][-5:]) % 4 - 1]
        self.assertTrue(gedeeld)  # er zijn panden met VBO's uit beide snapshots
        self.assertTrue(all(p["datapeildatum"] == "2026-08-04" for p in gedeeld))  # eerste snapshot wint

    def test_json_snapshot_kan_niet_per_pand(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, js = self.snapshots_van(gegenereerd(2), Path(tmp))
            with self.assertRaises(snapshots.SnapshotFout):
                next(snapshots.stroom_per_pand(js))


@unittest.skipUnless(AUGUSTUS.is_file(), f"{AUGUSTUS} ontbreekt; Delft via SQLite overgeslagen")
class DelftAugustusViaSqlite(unittest.TestCase):
    """VA-36 criteria 2 en 3: dezelfde Delft-uitkomst langs beide routes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = selectie.load_config()
        with open(AUGUSTUS, encoding="utf-8") as fh:
            rijen = json.load(fh)
        sq = snapshots.schrijf_sqlite("Delft", "delft", iter(rijen), Path(cls.tmp.name),
                                      datetime(2026, 8, 4, 12))
        js = snapshots.Snapshot("Delft", AUGUSTUS, "2026-08-04", 0, "config", "json")
        cls.json = selectie.verwerk("Delft", cfg, gekozen=[js])
        cls.sqlite = selectie.verwerk("Delft", cfg, gekozen=[sq])
        cls.cfg = cfg

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_per_pand_gelijk(self):
        self.assertEqual(len(self.sqlite), 24008)
        sleutel = lambda p: p["bag_pand_id"]  # noqa: E731
        self.assertEqual(sorted(self.json, key=sleutel), sorted(self.sqlite, key=sleutel))

    def test_va2_cijfers(self):
        actief = [p for p in self.sqlite if not p["uitgesloten"]]
        in_cat = [p for p in actief if p["categorieen"]]
        self.assertEqual(sum(p["aantal_vbo"] for p in self.sqlite), 61993)
        self.assertEqual(len(self.sqlite) - len(actief), 1314)
        self.assertEqual(len(in_cat), 2346)
        drempel = self.cfg["drempels"]["score_min_voor_werklijst"]
        self.assertEqual(sum(1 for p in in_cat if p["leadscore"] >= drempel), 1668)

    def test_mastervolgorde_gelijk(self):
        def master(panden):
            act = sorted((p for p in panden if not p["uitgesloten"] and p["categorieen"]),
                         key=selectie.mastervolgorde)
            return [(p["bag_pand_id"], p["leadscore"], p["categorieen"]) for p in act]
        self.assertEqual(master(self.json), master(self.sqlite))


if __name__ == "__main__":
    unittest.main()
