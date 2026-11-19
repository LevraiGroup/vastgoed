"""
VA-56: de KVK-knop per pand, door de weekbewaker (betaald.py) heen. Offline: nep-HTTP, een tijdelijk grootboek.
Ayman 11-19: "bij elke pand een knop ... als je erop klikt gaat er een bevraging uit"; de €2 per week telt
alleen bevragingen.
"""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIS))

import betaald  # noqa: E402
import build_dashboard  # noqa: E402
from bronnen import kvk  # noqa: E402

PAND = "0503100000026198"  # Hippolytusbuurt 1, Delft: staat in output/


def antwoord(*namen):
    return 200, json.dumps({"totaal": len(namen), "resultaten": [
        {"kvkNummer": str(10000000 + i), "naam": n, "type": "hoofdvestiging"} for i, n in enumerate(namen)]}).encode()


def payload_uit(html):
    return json.loads(re.search(r"const PAYLOAD = (\{.*?\});\r?\n", html, re.S).group(1))


class Nep:
    def __init__(self, reactie):
        self.reactie, self.aanroepen = reactie, []

    def __call__(self, url, koppen, timeout):
        self.aanroepen.append(url)
        return self.reactie(url) if callable(self.reactie) else self.reactie


class KnopDoorDeBewaker(unittest.TestCase):
    def setUp(self):
        self.map = Path(tempfile.mkdtemp())
        self.omg = {"VASTGOED_GROOTBOEK": str(self.map / "grootboek.json"), "KVK_API_KEY": "fictief"}

    def bewaker(self, nep, omg=None):
        bron = betaald.Bron(aantal=kvk.aantal_bevragingen,
                            zoek=lambda pand, s: kvk.zoek_voor_bewaker(pand, s, {}, http_get=nep))
        return betaald.Bewaker(omg or self.omg, BASIS / "config.yaml", BASIS / "output", BASIS, time.time,
                               bronnen={"kvk": bron}, log=lambda *_: None)

    def adressen(self):
        return kvk.aantal_bevragingen(betaald.lees_panden(BASIS / "output")[PAND])

    def test_klik_kost_twee_cent_per_adres_en_tweede_klik_niets(self):
        nep = Nep(antwoord("Fictief BV"))
        bw = self.bewaker(nep)
        n = self.adressen()
        status, j = bw.zoek("kvk", PAND)
        self.assertEqual(status, 200)
        self.assertEqual(j["kosten_cent"], 2 * n)
        self.assertEqual(j["resterend_cent"], 200 - 2 * n)
        self.assertEqual(len(nep.aanroepen), n)
        self.assertEqual(len(j["resultaat"]["adressen"]), n)
        self.assertEqual(j["resultaat"]["omgeving"], "test")  # zonder KVK_BASIS: de gratis testomgeving
        status, j2 = bw.zoek("kvk", PAND)
        self.assertEqual((status, j2["kosten_cent"], j2.get("onthouden")), (200, 0, True))
        self.assertEqual(j2["resterend_cent"], 200 - 2 * n)
        self.assertEqual(len(nep.aanroepen), n)  # geen nieuwe call

    def test_fout_wordt_niet_onthouden_en_blijft_geteld(self):
        nep = Nep((500, b""))
        bw = self.bewaker(nep)
        n = self.adressen()
        status, j = bw.zoek("kvk", PAND)
        self.assertEqual(status, 200)
        self.assertTrue(all(a["fout"] for a in j["resultaat"]["adressen"]))
        status, j2 = bw.zoek("kvk", PAND)
        self.assertEqual(j2["kosten_cent"], 2 * n)  # opnieuw gevraagd, opnieuw geteld
        self.assertEqual(len(nep.aanroepen), 2 * n)

    def test_weeklimiet_stopt_voor_de_call(self):
        nep = Nep(antwoord("Fictief BV"))
        bw = self.bewaker(nep, {**self.omg, "VASTGOED_WEEKLIMIET_CENT": "1"})
        status, j = bw.zoek("kvk", PAND)
        self.assertEqual(status, 429)
        self.assertEqual(j["kosten_cent"], 0)
        self.assertEqual(nep.aanroepen, [])

    def test_productie_als_kvk_basis_dat_zegt(self):
        nep = Nep(antwoord())
        uit = kvk.zoek_voor_bewaker({"hoofdadres": "Markt 1, 2611GP Delft"}, "fictief",
                                    {"KVK_BASIS": kvk.PRODUCTIE_BASIS}, http_get=nep)
        self.assertEqual(uit["omgeving"], "productie")
        self.assertTrue(nep.aanroepen[0].startswith(kvk.PRODUCTIE_BASIS + "/zoeken?"))


class GrootboekOpHetVolume(unittest.TestCase):
    """Zonder VASTGOED_GROOTBOEK staat de weekteller in het Railway-volume, net als bewaard.json."""

    def test_volume(self):
        t = Path(tempfile.mkdtemp())
        pad, reden = betaald.grootboek_pad({"RAILWAY_VOLUME_MOUNT_PATH": str(t)}, t / "app")
        self.assertEqual((pad, reden), ((t / "grootboek_betaald.json").resolve(), ""))

    def test_eigen_pad_gaat_voor(self):
        t = Path(tempfile.mkdtemp())
        pad, _ = betaald.grootboek_pad({"RAILWAY_VOLUME_MOUNT_PATH": str(t), "VASTGOED_GROOTBOEK": str(t / "x.json")},
                                       t / "app")
        self.assertEqual(pad, (t / "x.json").resolve())

    def test_zonder_beide_dicht(self):
        pad, reden = betaald.grootboek_pad({}, BASIS)
        self.assertIsNone(pad)
        self.assertIn("geweigerd", reden)

    def test_volume_in_de_app_map_telt_niet(self):
        pad, _ = betaald.grootboek_pad({"RAILWAY_VOLUME_MOUNT_PATH": str(BASIS / "design")}, BASIS)
        self.assertIsNone(pad)


class KnopOpHetDashboard(unittest.TestCase):
    def test_prijs_uit_config(self):
        self.assertEqual(build_dashboard.kvk_blok()["prijs"], 2)

    def test_pagina_heeft_de_knop(self):
        html = (BASIS / "design" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function kvkSectie", html)
        self.assertIn('"/api/opzoeken"', html)
        self.assertEqual(payload_uit(html)["kvk"]["prijs"], 2)

    def test_elk_pand_dezelfde_telling_als_de_server(self):
        html = (BASIS / "design" / "index.html").read_text(encoding="utf-8")
        payload = payload_uit(html)
        server = betaald.lees_panden(BASIS / "output")
        self.assertTrue(payload["leads"])
        for lead in payload["leads"]:
            with self.subTest(pand=lead["id"]):
                self.assertGreaterEqual(lead["kvk"], 1)
                self.assertIn(lead["id"], server)
                self.assertEqual(lead["kvk"], kvk.aantal_bevragingen(server[lead["id"]]))


if __name__ == "__main__":
    unittest.main()
