"""
Ayman 11-17 ("het moet wel productieready zijn"): bewaarde en verborgen panden staan op de server, gedeeld door
iedereen met de Levrai-inlog. bewaard.py (de opslag) en /api/panden in serve.py. Alleen localhost.
"""
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bewaard  # noqa: E402
import serve  # noqa: E402
from test_serve import GEHEIM, Server  # noqa: E402

PAND = "0344100000047367"
WAARDE = {"stand": "bewaard", "sinds": "2026-11-17T09:00:00.000Z", "hoofdadres": "Amsterdamsestraatweg 305, 3551CH Utrecht",
          "woonplaats": "Utrecht", "score100": 77, "pandcategorie": "A",
          "bag_viewer_url": "https://bagviewer.kadaster.nl/lvbag/bag-viewer/?objectId=" + PAND, "datapeildatum": "2026-11-01"}


class Pad(unittest.TestCase):
    def test_volume_van_railway(self):
        with tempfile.TemporaryDirectory() as t:
            pad, reden = bewaard.opslag_pad({"RAILWAY_VOLUME_MOUNT_PATH": t}, Path(t) / "app")
            self.assertEqual(pad, (Path(t) / "bewaard.json").resolve())
            self.assertEqual(reden, "")

    def test_eigen_pad_wint(self):
        with tempfile.TemporaryDirectory() as t:
            pad, _ = bewaard.opslag_pad({"VASTGOED_BEWAARD": str(Path(t) / "x.json"),
                                         "RAILWAY_VOLUME_MOUNT_PATH": t}, Path(t) / "app")
            self.assertEqual(pad.name, "x.json")

    def test_niets_gezet_of_in_de_app_map_is_geen_opslag(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(bewaard.opslag_pad({}, Path(t))[0])
            self.assertIsNone(bewaard.opslag_pad({"VASTGOED_BEWAARD": str(Path(t) / "data" / "b.json")}, Path(t))[0])


class Opslag(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.pad = Path(t.name) / "bewaard.json"
        self.o = bewaard.Opslag(self.pad)

    def test_zetten_wissen_en_blijft_na_herstart(self):
        self.assertEqual(self.o.alles(), {})
        self.assertEqual(self.o.wijzig([{"id": PAND, "waarde": WAARDE}]), {PAND: WAARDE})
        self.assertEqual(bewaard.Opslag(self.pad).alles(), {PAND: WAARDE})   # een nieuwe server leest hetzelfde
        self.assertEqual(self.o.wijzig([{"id": PAND, "waarde": None}]), {})
        self.assertFalse(self.pad.with_name("bewaard.json.nieuw").exists())

    def test_een_fout_en_er_verandert_niets(self):
        self.o.wijzig([{"id": PAND, "waarde": WAARDE}])
        for fout in ([{"id": "123", "waarde": WAARDE}],
                     [{"id": PAND, "waarde": None}, {"id": "0344100000000001", "waarde": {**WAARDE, "stand": "x"}}],
                     [{"id": PAND, "waarde": {**WAARDE, "extra": 1}}],
                     [{"id": PAND, "waarde": {**WAARDE, "hoofdadres": "x" * 301}}],
                     [{"id": PAND, "waarde": {**WAARDE, "score100": True}}],
                     [], "geen lijst"):
            with self.subTest(fout=str(fout)[:60]):
                with self.assertRaises(bewaard.Ongeldig):
                    self.o.wijzig(fout)
                self.assertEqual(self.o.alles(), {PAND: WAARDE})

    def test_onleesbaar_bestand_wordt_niet_overschreven(self):
        self.pad.write_text("kapot", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.o.wijzig([{"id": PAND, "waarde": WAARDE}])
        self.assertEqual(self.pad.read_text(encoding="utf-8"), "kapot")


class Api(Server):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.volume = Path(t.name)
        self.omgeving = {**GEHEIM, "RAILWAY_VOLUME_MOUNT_PATH": str(self.volume)}
        super().setUp()
        _, koppen, _ = self.inloggen()
        self.sessie = self.cookie_uit(koppen)[0]

    def json(self, methode, data=None, cookie=True, koppen=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.poort, timeout=5)
        self.addCleanup(conn.close)
        k = {"Content-Type": "application/json", **(koppen or {})}
        if cookie:
            k["Cookie"] = f"{serve.COOKIE}={self.sessie}"
        conn.request(methode, "/api/panden", body=None if data is None else json.dumps(data), headers=k)
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b"null")

    def test_bewaren_en_terugzien_op_elk_apparaat(self):
        self.assertEqual(self.json("GET"), (200, {"panden": {}}))
        status, uit = self.json("POST", {"wijzigingen": [{"id": PAND, "waarde": WAARDE}]})
        self.assertEqual((status, uit), (200, {"panden": {PAND: WAARDE}}))
        self.assertEqual(self.json("GET"), (200, {"panden": {PAND: WAARDE}}))
        self.assertTrue((self.volume / "bewaard.json").is_file())

    def test_zonder_inlog_niets(self):
        self.assertEqual(self.json("GET", cookie=False)[0], 401)
        self.assertEqual(self.json("POST", {"wijzigingen": [{"id": PAND, "waarde": WAARDE}]}, cookie=False)[0], 401)
        self.assertFalse((self.volume / "bewaard.json").exists())

    def test_andere_site_mag_niet_schrijven(self):
        status, _ = self.json("POST", {"wijzigingen": [{"id": PAND, "waarde": WAARDE}]},
                              koppen={"Origin": "https://kwaad.example"})
        self.assertEqual(status, 403)
        self.assertFalse((self.volume / "bewaard.json").exists())

    def test_ongeldig_verzoek(self):
        for data in ({"wijzigingen": [{"id": "1", "waarde": None}]}, {"iets": 1}, [1]):
            with self.subTest(data=data):
                self.assertEqual(self.json("POST", data)[0], 400)


class ApiZonderOpslag(Server):
    def test_503_dan_blijft_het_in_de_browser(self):
        _, koppen, _ = self.inloggen()
        sessie = self.cookie_uit(koppen)[0]
        status, _, _ = self.vraag("GET", "/api/panden", cookie=sessie)
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()
