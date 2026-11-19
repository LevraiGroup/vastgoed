"""
VA-55: bronnen/kvk.py, offline. Fictieve antwoorden in de vorm van het contract
(TOEKOMSTVERBETERINGEN.md item 1); geen sleutel, geen netwerk.
"""
import http.client
import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bronnen import kvk  # noqa: E402

OMG = {"KVK_API_KEY": "fictieve-testsleutel"}
PAND = {"bag_pand_id": "0503100000021394", "postcode": "2611NL", "huisnummer": 144,
        "gekoppelde_adressen": ["Verwersdijk 144A, 2611NL Delft", "Verwersdijk 146, 2611NM Delft",
                                "Verwersdijk 148, 2611NM Delft", "Verwersdijk 144B, 2611NL Delft"]}


def antwoord(*vestigingen):
    return json.dumps({"totaal": len(vestigingen), "resultaten": [
        {"kvkNummer": nr, "naam": naam, "type": typ,
         "adres": {"binnenlandsAdres": {"straatnaam": "Fictiefstraat"}}}
        for nr, naam, typ in vestigingen]}).encode("utf-8")


class Nep:
    """Vervangt de HTTP-call; onthoudt elke aanroep."""

    def __init__(self, *reacties):
        self.reacties = list(reacties)
        self.aanroepen = []

    def __call__(self, url, koppen, timeout):
        self.aanroepen.append((url, koppen, timeout))
        r = self.reacties.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


class Adressen(unittest.TestCase):
    def test_uit_tekst(self):
        self.assertEqual(kvk.adres_uit_tekst("Verwersdijk 144A, 2611NL Delft"), kvk.Adres("2611NL", 144))
        self.assertEqual(kvk.adres_uit_tekst("Lange Geer 2-4, 2611 PW Delft"), kvk.Adres("2611PW", 2))
        self.assertEqual(kvk.adres_uit_tekst("Oude Delft 9 bis, 2611ab Delft"), kvk.Adres("2611AB", 9))
        self.assertIsNone(kvk.adres_uit_tekst("onleesbaar"))

    def test_verschillende_adressen_een_keer(self):
        # 144A en 144B delen postcode en huisnummer: één call.
        self.assertEqual(kvk.adressen(PAND), [kvk.Adres("2611NL", 144), kvk.Adres("2611NM", 146),
                                              kvk.Adres("2611NM", 148)])
        self.assertEqual(kvk.aantal_bevragingen(PAND), 3)

    def test_terugval_op_hoofdadres(self):
        self.assertEqual(kvk.adressen({"postcode": "2611 nl", "huisnummer": 7}), [kvk.Adres("2611NL", 7)])
        self.assertEqual(kvk.aantal_bevragingen({}), 0)


class Instellingen(unittest.TestCase):
    def test_standaard_testomgeving(self):
        self.assertEqual(kvk.instellingen(OMG), (kvk.TEST_BASIS, "fictieve-testsleutel"))

    def test_productie_alleen_als_gezet(self):
        basis, _ = kvk.instellingen({**OMG, "KVK_BASIS": kvk.PRODUCTIE_BASIS + "/"})
        self.assertEqual(basis, kvk.PRODUCTIE_BASIS)

    def test_zonder_sleutel_geen_call(self):
        nep = Nep()
        with self.assertRaises(kvk.KvkFout):
            kvk.zoek_pand(PAND, {}, http_get=nep)
        self.assertEqual(nep.aanroepen, [])


class Zoeken(unittest.TestCase):
    def test_gevonden(self):
        nep = Nep((200, antwoord(("12345678", "Fictief Bedrijf BV", "hoofdvestiging"),
                                 ("87654321", "Ander Fictief", "nevenvestiging"))))
        u = kvk.zoek_adres(kvk.Adres("2611NL", 144), kvk.TEST_BASIS, "s", http_get=nep)
        self.assertTrue(u.gelukt)
        self.assertEqual(u.aantal, 2)
        self.assertEqual(u.vestigingen[0], {"kvkNummer": "12345678", "naam": "Fictief Bedrijf BV",
                                            "type": "hoofdvestiging"})
        url, koppen, timeout = nep.aanroepen[0]
        self.assertEqual(url, kvk.TEST_BASIS + "/zoeken?postcode=2611NL&huisnummer=144&resultatenPerPagina=100")
        self.assertEqual(koppen["apikey"], "s")
        self.assertGreater(timeout, 0)

    def test_meer_dan_een_pagina(self):
        body = json.dumps({"totaal": 14, "resultaten": [{"kvkNummer": str(n), "naam": "F", "type": "t"}
                                                         for n in range(10)]}).encode()
        u = kvk.zoek_adres(kvk.Adres("2611NL", 144), kvk.TEST_BASIS, "s", http_get=Nep((200, body)))
        self.assertEqual(u.aantal, 14)  # KVK's telling, niet de tien op deze pagina
        self.assertTrue(u.onvolledig)

    def test_404_is_nul_vestigingen(self):
        u = kvk.zoek_adres(kvk.Adres("2611NL", 144), kvk.TEST_BASIS, "s", http_get=Nep((404, b"")))
        self.assertTrue(u.gelukt)
        self.assertEqual(u.aantal, 0)

    def test_fouten_zijn_nooit_nul(self):
        for reactie in [(500, b"oeps"), (401, b""), (429, b""), socket.timeout("te traag"),
                        ConnectionRefusedError(), (200, b"geen json"), (200, b'{"totaal": 1}'),
                        (200, b'{"resultaten": [{"naam": "zonder nummer"}]}'), (200, b"\xff\xfe"),
                        http.client.IncompleteRead(b""), http.client.BadStatusLine("x"),
                        (200, b'{"totaal": 0, "resultaten": [{"kvkNummer": "1"}]}')]:
            with self.subTest(reactie=reactie):
                u = kvk.zoek_adres(kvk.Adres("2611NL", 144), kvk.TEST_BASIS, "s", http_get=Nep(reactie))
                self.assertFalse(u.gelukt)
                self.assertIsNone(u.aantal)
                self.assertTrue(u.fout)

    def test_pand_precies_een_call_per_adres_en_geen_herhaling(self):
        nep = Nep((200, antwoord(("12345678", "Fictief", "hoofdvestiging"))), (500, b""), (404, b""))
        uit = kvk.zoek_pand(PAND, OMG, http_get=nep)
        self.assertEqual(len(nep.aanroepen), kvk.aantal_bevragingen(PAND))
        self.assertEqual([u.aantal for u in uit], [1, None, 0])


class GeenSleutelInDeCode(unittest.TestCase):
    def test_bronbestand(self):
        # Geen sleutelachtige reeks (30+ letters/cijfers aaneen) in de module: de sleutel
        # komt alleen uit KVK_API_KEY.
        tekst = Path(kvk.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(tekst, r"[A-Za-z0-9]{30,}")


if __name__ == "__main__":
    unittest.main()
