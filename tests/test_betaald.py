"""
VA-54: de ene bewaker voor betaalde opzoekingen. Alleen standaardbibliotheek, geen netwerk naar
buiten, een nepbron die zijn calls telt en een klok die de test zet. Er wordt nooit een echte
betaalde bron aangeroepen, en niets schrijft naar output/ of data/.
"""
import hashlib
import http.client
import json
import re
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import betaald  # noqa: E402
import serve  # noqa: E402

BASIS = Path(__file__).resolve().parent.parent
GEHEIM = {"VASTGOED_GEBRUIKER": "levrai", "VASTGOED_WACHTWOORD": "juist-wachtwoord",
          "VASTGOED_SESSIESLEUTEL": "testsleutel-" + "x" * 40}
SLEUTEL = "NEPSLEUTEL-niet-echt-9f3c"  # de waarde mag nergens terugkomen
PAND_1 = "0503100000000001"
PAND_3 = "0503100000000999"  # drie adressen, twee met dezelfde postcode + huisnummer
WEEKREGEL = "Weeklimiet van €2 voor betaalde opzoekingen bereikt, weer beschikbaar vanaf maandag"


def utc(*delen) -> float:
    return datetime(*delen, tzinfo=timezone.utc).timestamp()


MAANDAG_W47 = utc(2026, 11, 16, 9, 0)  # maandag 16 november 2026, 10:00 Amsterdam


class Klok:
    def __init__(self, t=MAANDAG_W47):
        self.t = t

    def __call__(self):
        return self.t


class NepBron:
    """Telt calls en adressen zoals KVK: één call per verschillende postcode + huisnummer."""

    def __init__(self, wacht=0.0, gooi=None, controle=None):
        self.calls = 0
        self.panden = []
        self.wacht, self.gooi, self.controle = wacht, gooi, controle
        self._slot = threading.Lock()

    @staticmethod
    def aantal(pand):
        return len({(a.split(",")[1].strip(), re.match(r"\d+", a.split(",")[0].split()[-1]).group())
                    for a in pand["gekoppelde_adressen"]})

    def zoek(self, pand, sleutel):
        assert sleutel == SLEUTEL
        if self.controle:
            self.controle(pand)
        with self._slot:
            self.calls += 1
            self.panden.append(pand["bag_pand_id"])
        if self.wacht:
            time.sleep(self.wacht)
        if self.gooi:
            raise self.gooi
        return {"vestigingen": 0, "pand": pand["bag_pand_id"]}

    def bron(self):
        return betaald.Bron(aantal=self.aantal, zoek=self.zoek)


def schrijf_output(map_: Path, aantal=60):
    regels = ["bag_pand_id;hoofdadres;gekoppelde_adressen;woonplaats;postcode;datapeildatum"]
    for i in range(1, aantal + 1):
        pid = f"05031000000{i:05d}"
        regels.append(f"{pid};Teststraat {i}, 2611AA Delft;Teststraat {i}, 2611AA Delft;Delft;2611AA;2026-11-01")
    regels.append(f"{PAND_3};Proefweg 1, 2611BB Delft;Proefweg 1, 2611BB Delft | Proefweg 1A, 2611BB Delft | "
                  f"Proefweg 3, 2611BB Delft;Delft;2611BB;2026-11-01")
    (map_ / "werklijst_test.csv").write_text("﻿" + "\n".join(regels) + "\n", encoding="utf-8")


def schrijf_config(pad: Path, prijs="6", var="NEP_SLEUTEL"):
    pad.write_text(f"betaalde_bronnen:\n  nep:\n    naam: \"Nepbron\"\n    prijs_cent: {prijs}\n"
                   f"    sleutel_variabele: {var}\n", encoding="utf-8")


class Opzet(unittest.TestCase):
    """Een echte server op 127.0.0.1 met tijdelijke design/, output/, config en grootboek."""

    prijs = "6"
    extra_omgeving: dict = {}
    met_grootboek = True

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "design").mkdir()
        (self.root / "design" / "index.html").write_text("dashboard", encoding="utf-8")
        (self.root / "output").mkdir()
        schrijf_output(self.root / "output")
        self.config = self.root / "config.yaml"
        schrijf_config(self.config, self.prijs)
        (self.root / "opslag").mkdir()
        self.grootboek = self.root / "opslag" / "grootboek.json"
        self.omgeving = {**GEHEIM, "NEP_SLEUTEL": SLEUTEL, **self.extra_omgeving}
        if self.met_grootboek:
            self.omgeving["VASTGOED_GROOTBOEK"] = str(self.grootboek)
        self.klok = Klok()
        self.nep = NepBron()
        self.log = []
        self.start()

    def start(self, bronnen=None):
        self.server = serve.maak_server(0, host="127.0.0.1", map_=self.root / "design", omgeving=self.omgeving,
                                        klok=self.klok, config=self.config, output=self.root / "output",
                                        bronnen={"nep": self.nep.bron()} if bronnen is None else bronnen,
                                        log=self.log.append)
        stil = mock.patch.object(serve.Handler, "log_message", lambda *a, **k: None)
        stil.start()
        self.addCleanup(stil.stop)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.poort = self.server.server_address[1]
        self.cookie = self.server.sessies.nieuw(30 * 86400)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def vraag(self, methode="POST", body=None, cookie=True, koppen=None, ruw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.poort, timeout=10)
        try:
            k = dict(koppen or {})
            if cookie:
                k["Cookie"] = f"{serve.COOKIE}={self.cookie}"
            data = ruw if ruw is not None else (json.dumps(body).encode() if body is not None else None)
            if data is not None:
                k["Content-Type"] = "application/json"
            conn.request(methode, serve.PAD_OPZOEKEN, body=data, headers=k)
            r = conn.getresponse()
            tekst = r.read()
            is_json = (r.getheader("Content-Type") or "").startswith("application/json")
            return r.status, json.loads(tekst) if tekst and is_json else None, dict(r.getheaders())
        finally:
            conn.close()

    def zoek(self, pand=PAND_1, bron="nep", **kw):
        return self.vraag(body={"bron": bron, "bag_pand_id": pand}, **kw)

    def week_totaal(self, week="2026-W47"):
        if not self.grootboek.exists():
            return 0
        return sum(p["cent"] for p in json.loads(self.grootboek.read_text("utf-8"))["weken"].get(week, []))


# --------------------------------------------------------------------- criterium 1 en 2
class Toegang(Opzet):
    def test_zonder_sessie_401_en_niets_aangeroepen(self):
        for cookie in (False,):
            status, antwoord, koppen = self.zoek(cookie=cookie)
            self.assertEqual(status, 401)
            self.assertEqual(antwoord["kosten_cent"], 0)
            self.assertIn("no-store", koppen["Cache-Control"])
        status, _, _ = self.zoek(koppen={"Cookie": f"{serve.COOKIE}=vervalst.abc"}, cookie=False)
        self.assertEqual(status, 401)
        self.assertEqual(self.nep.calls, 0)
        self.assertFalse(self.grootboek.exists())

    def test_alleen_post(self):
        for methode in ("GET", "HEAD", "PUT", "DELETE"):
            with self.subTest(methode=methode):
                status, _, koppen = self.vraag(methode, body=None)
                self.assertIn(status, (405, 501))
                if methode in ("GET", "HEAD"):
                    self.assertEqual(koppen["Allow"], "POST")
        self.assertEqual(self.nep.calls, 0)

    def test_andere_site_403(self):
        status, _, _ = self.zoek(koppen={"Origin": "https://kwaadaardig.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.nep.calls, 0)

    def test_alleen_bron_en_pand_geen_adressen(self):
        for body in ({"bron": "nep", "bag_pand_id": PAND_1, "adres": "Kerkstraat 1, 1234AB"},
                     {"bron": "nep"}, {"bag_pand_id": PAND_1}, {"bron": "nep", "bag_pand_id": "123"},
                     {"bron": "nep", "bag_pand_id": 503100000000001}, ["nep", PAND_1], "nep"):
            with self.subTest(body=body):
                status, antwoord, _ = self.vraag(body=body)
                self.assertEqual(status, 400)
                self.assertEqual(antwoord["kosten_cent"], 0)
        for ruw in (b"{niet json", b"\xff\xfe", b"", b"x" * 2000):
            with self.subTest(ruw=ruw[:10]):
                status, _, _ = self.vraag(ruw=ruw)
                self.assertEqual(status, 400)
        self.assertEqual(self.nep.calls, 0)
        self.assertFalse(self.grootboek.exists())

    def test_onbekend_pand_of_bron_kost_niets(self):
        status, antwoord, _ = self.zoek(pand="0503100000099999")
        self.assertEqual((status, antwoord["kosten_cent"]), (404, 0))
        self.assertIn("niet in de selectie", antwoord["fout"])
        status, antwoord, _ = self.zoek(bron="onbekend")
        self.assertEqual((status, antwoord["kosten_cent"]), (404, 0))
        self.assertEqual(self.nep.calls, 0)
        self.assertEqual(self.week_totaal(), 0)

    def test_server_zoekt_de_adressen_zelf(self):
        status, antwoord, _ = self.zoek(pand=PAND_3)
        self.assertEqual(status, 200)
        self.assertEqual(self.nep.panden, [PAND_3])
        self.assertEqual(antwoord["kosten_cent"], 2 * 6)  # 1 en 1A vallen samen: twee bevragingen


class EchteOutput(unittest.TestCase):
    """De panden komen uit de gecommitte output/*.csv; lezen schrijft er niets."""

    def test_pand_uit_de_gecommitte_csv(self):
        bestanden = sorted((BASIS / "output").glob("*.csv"))
        if not bestanden:
            self.skipTest("geen output/*.csv in deze map")
        voor = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bestanden}
        panden = betaald.lees_panden(BASIS / "output")
        pand = panden["0503100000026198"]  # de eerste Delftse lead, ook in de landelijke werklijst
        self.assertEqual(pand["hoofdadres"], "Hippolytusbuurt 1, 2611HM Delft")
        self.assertEqual(len(pand["gekoppelde_adressen"]), 8)
        self.assertEqual(pand["datapeildatum"], "2026-11-01")  # de nieuwste rij wint
        na = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((BASIS / "output").glob("*.csv"))}
        self.assertEqual(voor, na)


# --------------------------------------------------------------------- criterium 3 en 11
class Prijzen(unittest.TestCase):
    def test_echte_config_heeft_kvk_en_kadaster(self):
        prijzen, afgekeurd, melding = betaald.lees_config(BASIS / "config.yaml")
        self.assertEqual((melding, afgekeurd), ("", {}))
        self.assertEqual(prijzen["kvk"], betaald.Prijs("KVK", 2, "KVK_API_KEY"))
        self.assertEqual(prijzen["kadaster_koopsom"], betaald.Prijs("Kadaster Koopsom", 45, "KADASTER_KOOPSOM_KEY"))
        for p in prijzen.values():
            self.assertIs(type(p.cent), int)

    def test_ongeldige_prijzen_worden_afgekeurd(self):
        for waarde in (2.0, "2", 0, -1, True, None, 0.5, float("nan")):
            with self.subTest(waarde=waarde):
                prijzen, afgekeurd = betaald.lees_prijzen(
                    {"x": {"naam": "X", "prijs_cent": waarde, "sleutel_variabele": "X_KEY"}})
                self.assertEqual(prijzen, {})
                self.assertIn("prijs_cent", afgekeurd["x"])

    def test_sleutel_variabele_is_een_naam_geen_waarde(self):
        for var in ("", "sk-live-abc", None, "kvk api key"):
            with self.subTest(var=var):
                prijzen, afgekeurd = betaald.lees_prijzen({"x": {"naam": "X", "prijs_cent": 2, "sleutel_variabele": var}})
                self.assertEqual(prijzen, {})

    def test_config_onleesbaar_geeft_geen_prijzen(self):
        with tempfile.TemporaryDirectory() as d:
            pad = Path(d) / "config.yaml"
            pad.write_text("betaalde_bronnen: [\n", encoding="utf-8")
            self.assertEqual(betaald.lees_config(pad)[0], {})
            self.assertEqual(betaald.lees_config(Path(d) / "weg.yaml")[0], {})


class PrijsWijzigt(Opzet):
    prijs = "6"

    def test_andere_prijs_in_config_andere_reservering(self):
        status, antwoord, _ = self.zoek(pand=PAND_3)
        self.assertEqual((status, antwoord["kosten_cent"]), (200, 12))
        self.stop()
        schrijf_config(self.config, prijs="7")  # alleen config.yaml verandert, geen code
        self.start()
        status, antwoord, _ = self.zoek(pand=PAND_3)
        self.assertEqual((status, antwoord["kosten_cent"]), (200, 14))
        self.assertEqual(self.week_totaal(), 26)

    def test_ongeldige_prijs_weigert_en_logt_welke(self):
        self.stop()
        schrijf_config(self.config, prijs="2.5")
        self.start()
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["kosten_cent"]), (503, 0))
        self.assertIn("geen geldige prijs", antwoord["fout"])
        self.assertTrue(any("nep afgekeurd" in r and "prijs_cent" in r for r in self.server.bewaker.meldingen))
        self.assertEqual(self.nep.calls, 0)

    def test_antwoord_geeft_resultaat_kosten_en_rest(self):
        status, antwoord, koppen = self.zoek()
        self.assertEqual(status, 200)
        self.assertEqual(antwoord, {"bron": "nep", "bag_pand_id": PAND_1,
                                    "resultaat": {"vestigingen": 0, "pand": PAND_1},
                                    "kosten_cent": 6, "resterend_cent": 194, "week": "2026-W47"})
        self.assertTrue(koppen["Content-Type"].startswith("application/json"))


# --------------------------------------------------------------------- criterium 4 en 7
class EerstReserveren(Opzet):
    def test_reservering_staat_op_schijf_voor_de_call(self):
        gezien = []
        self.nep.controle = lambda pand: gezien.append(self.week_totaal())
        self.zoek()
        self.zoek(pand="0503100000000002")
        self.assertEqual(gezien, [6, 12])

    def test_boven_het_plafond_429_met_aymans_regel(self):
        for i in range(1, 34):
            self.assertEqual(self.zoek(pand=f"05031000000{i:05d}")[0], 200)
        self.assertEqual(self.week_totaal(), 198)
        status, antwoord, _ = self.zoek(pand="0503100000000034")
        self.assertEqual(status, 429)
        self.assertEqual(antwoord["fout"], WEEKREGEL)
        self.assertEqual(antwoord["resterend_cent"], 2)
        self.assertEqual(antwoord["kosten_cent"], 0)
        self.assertEqual(self.nep.calls, 33)
        self.assertEqual(self.week_totaal(), 198)

    def test_rest_kleiner_dan_dit_pand_kost_ook_429(self):
        for i in range(1, 32):
            self.zoek(pand=f"05031000000{i:05d}")
        self.assertEqual(self.week_totaal(), 186)  # 14 over; PAND_3 kost 12, daarna 2 over
        self.assertEqual(self.zoek(pand=PAND_3)[0], 200)
        status, antwoord, _ = self.zoek(pand="0503100000000040")
        self.assertEqual((status, antwoord["resterend_cent"]), (429, 2))

    def test_fout_na_versturen_blijft_geteld(self):
        for fout in (TimeoutError("traag"), RuntimeError("HTTP 500")):
            with self.subTest(fout=type(fout).__name__):
                self.nep.gooi = fout
                voor = self.week_totaal()
                status, antwoord, _ = self.zoek(pand=f"05031000000{10 + len(self.nep.panden):05d}")
                self.assertEqual(status, 502)
                self.assertEqual(antwoord["kosten_cent"], 6)
                self.assertEqual(self.week_totaal(), voor + 6)

    def test_niet_verstuurd_wordt_vrijgegeven(self):
        self.nep.gooi = betaald.NietVerstuurd()
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["kosten_cent"], antwoord["resterend_cent"]), (502, 0, 200))
        self.assertEqual(self.week_totaal(), 0)


# --------------------------------------------------------------------- criterium 5
class Week(unittest.TestCase):
    GEVALLEN = [
        # (UTC-moment, Amsterdamse tijd in woorden, ISO-week)
        (utc(2026, 11, 22, 22, 59), "zondag 22 nov 23:59 CET", "2026-W47"),
        (utc(2026, 11, 22, 23, 0), "maandag 23 nov 00:00 CET", "2026-W48"),
        (utc(2026, 11, 29, 23, 0), "maandag 30 nov 00:00 (maand loopt door)", "2026-W49"),
        (utc(2026, 12, 6, 22, 59), "zondag 6 dec 23:59", "2026-W49"),
        (utc(2026, 12, 31, 12, 0), "donderdag 31 dec 2026", "2026-W53"),
        (utc(2027, 1, 1, 12, 0), "vrijdag 1 jan 2027, nog week 53 van 2026", "2026-W53"),
        (utc(2027, 1, 3, 22, 59), "zondag 3 jan 2027 23:59", "2026-W53"),
        (utc(2027, 1, 3, 23, 0), "maandag 4 jan 2027 00:00", "2027-W01"),
        # Wintertijd 25 okt 2026: 22:30 UTC is zondag 23:30 CET (met zomertijd was het maandag 00:30)
        (utc(2026, 10, 25, 0, 59), "zondag 25 okt 02:59 CEST, vlak voor de klok terug", "2026-W43"),
        (utc(2026, 10, 25, 22, 30), "zondag 25 okt 23:30 CET, na de wisseling", "2026-W43"),
        (utc(2026, 10, 25, 23, 0), "maandag 26 okt 00:00 CET", "2026-W44"),
        # Zomertijd: maandag begint om 22:00 UTC
        (utc(2026, 6, 28, 21, 59), "zondag 28 jun 23:59 CEST", "2026-W26"),
        (utc(2026, 6, 28, 22, 0), "maandag 29 jun 00:00 CEST", "2026-W27"),
    ]

    def test_grenzen(self):
        for moment, uitleg, week in self.GEVALLEN:
            with self.subTest(uitleg):
                self.assertEqual(betaald.iso_week(moment), week)

    def test_gelijk_aan_zoneinfo_elk_uur(self):
        try:
            from zoneinfo import ZoneInfo
            ams = ZoneInfo("Europe/Amsterdam")
        except Exception:  # noqa: BLE001
            self.skipTest("geen tijdzonedatabase op deze machine")
        t = datetime(2025, 12, 1, tzinfo=timezone.utc)
        eind = datetime(2028, 1, 1, tzinfo=timezone.utc)
        while t < eind:
            for m in (0, 30):
                moment = (t + timedelta(minutes=m)).timestamp()
                self.assertEqual(betaald.amsterdam(moment).utcoffset(),
                                 datetime.fromtimestamp(moment, ams).utcoffset(), t)
            t += timedelta(hours=1)

    def test_onbruikbare_tijd(self):
        for moment in (float("nan"), float("inf"), 1e20, "nu", None, True):
            with self.subTest(moment=moment), self.assertRaises(ValueError):
                betaald.iso_week(moment)

    def test_plafond_uit_omgeving(self):
        self.assertEqual(betaald.weeklimiet({}), (200, ""))
        self.assertEqual(betaald.weeklimiet({"VASTGOED_WEEKLIMIET_CENT": "50"}), (50, ""))
        self.assertEqual(betaald.weeklimiet({"VASTGOED_WEEKLIMIET_CENT": "0"}), (0, ""))
        for waarde in ("201", "100000", "-5", "twee", "1.5"):
            with self.subTest(waarde=waarde):
                plafond, melding = betaald.weeklimiet({"VASTGOED_WEEKLIMIET_CENT": waarde})
                self.assertEqual(plafond, 200)
                self.assertIn("VASTGOED_WEEKLIMIET_CENT", melding)


class LagerPlafond(Opzet):
    extra_omgeving = {"VASTGOED_WEEKLIMIET_CENT": "10"}

    def test_lager_plafond_geldt(self):
        self.assertEqual(self.zoek()[0], 200)
        status, antwoord, _ = self.zoek(pand="0503100000000002")
        self.assertEqual((status, antwoord["resterend_cent"]), (429, 4))


class HogerPlafond(Opzet):
    extra_omgeving = {"VASTGOED_WEEKLIMIET_CENT": "5000"}

    def test_hoger_plafond_genegeerd(self):
        self.assertEqual(self.server.bewaker.plafond, 200)
        self.assertTrue(any("hoger dan Ayman's plafond" in r for r in self.server.bewaker.meldingen))


class NieuweWeek(Opzet):
    def test_maandag_begint_op_nul_en_oude_weken_blijven(self):
        self.klok.t = utc(2026, 11, 22, 22, 59)  # zondag 23:59
        for i in range(1, 34):
            self.zoek(pand=f"05031000000{i:05d}")
        self.assertEqual(self.zoek(pand="0503100000000050")[0], 429)
        self.klok.t = utc(2026, 11, 22, 23, 0)  # maandag 00:00
        status, antwoord, _ = self.zoek(pand="0503100000000050")
        self.assertEqual((status, antwoord["week"], antwoord["resterend_cent"]), (200, "2026-W48", 194))
        weken = json.loads(self.grootboek.read_text("utf-8"))["weken"]
        self.assertEqual(sum(p["cent"] for p in weken["2026-W47"]), 198)
        self.assertEqual(sum(p["cent"] for p in weken["2026-W48"]), 6)


# --------------------------------------------------------------------- criterium 6
class ZonderGrootboek(Opzet):
    met_grootboek = False

    def test_geen_pad_weigert_alles(self):
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["kosten_cent"]), (503, 0))
        self.assertEqual(antwoord["fout"], betaald.GEEN_OPSLAG)
        self.assertEqual(self.nep.calls, 0)
        self.assertTrue(any("VASTGOED_GROOTBOEK niet gezet" in r for r in self.server.bewaker.meldingen))


class DichtBijTwijfel(Opzet):
    def weiger(self, melding):
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["kosten_cent"], antwoord["fout"]), (503, 0, melding))
        self.assertEqual(self.nep.calls, 0)

    def test_onleesbaar_grootboek(self):
        for inhoud in ("{kapot", "[]", '{"versie": 2, "weken": {}}', '{"versie": 1}',
                       '{"versie": 1, "weken": {"2026-W47": [{"cent": 2.5}]}}',
                       '{"versie": 1, "weken": {"2026-W47": [{"cent": -6}]}}',
                       '{"versie": 1, "weken": {"2026-W47": {"cent": 6}}}'):
            with self.subTest(inhoud=inhoud):
                self.grootboek.write_text(inhoud, encoding="utf-8")
                self.weiger(betaald.TELLER_ONLEESBAAR)
                self.assertEqual(self.grootboek.read_text("utf-8"), inhoud)  # niet overschreven

    def test_grootboek_is_een_map(self):
        self.grootboek.mkdir()
        self.weiger(betaald.TELLER_ONLEESBAAR)

    def test_map_van_het_grootboek_bestaat_niet(self):
        self.omgeving["VASTGOED_GROOTBOEK"] = str(self.root / "geen-volume" / "grootboek.json")
        self.stop()
        self.start()
        self.weiger(betaald.TELLER_ONLEESBAAR)
        self.assertFalse((self.root / "geen-volume").exists())

    def test_niet_te_schrijven(self):
        (self.root / "opslag" / "grootboek.json.nieuw").mkdir()  # het tijdelijke bestand kan niet worden aangemaakt
        self.weiger(betaald.TELLER_NIET_BIJGEWERKT)

    def test_week_niet_te_bepalen(self):
        for klok in (lambda: float("nan"), lambda: 1e20, mock.Mock(side_effect=OSError("klok weg"))):
            with self.subTest(klok=klok):
                self.server.bewaker.grootboek._klok = klok
                self.weiger(betaald.WEEK_ONBEKEND)

    def test_pad_in_de_app_map_telt_niet(self):
        for pad in (BASIS / "grootboek.json", BASIS / "output" / "grootboek.json", BASIS / "data" / "g.json"):
            with self.subTest(pad=pad):
                gevonden, melding = betaald.grootboek_pad({"VASTGOED_GROOTBOEK": str(pad)}, BASIS)
                self.assertIsNone(gevonden)
                self.assertIn("deploy", melding)


# --------------------------------------------------------------------- criterium 8
class Gelijktijdig(Opzet):
    def test_vijftig_tegelijk_hooguit_33_calls(self):
        self.nep.wacht = 0.05
        start = threading.Barrier(50)
        uitkomsten = []

        def een(i):
            start.wait()
            uitkomsten.append(self.zoek(pand=f"05031000000{i:05d}")[0])

        draden = [threading.Thread(target=een, args=(i,)) for i in range(1, 51)]
        for d in draden:
            d.start()
        for d in draden:
            d.join(30)
        self.assertEqual(len(uitkomsten), 50)
        self.assertLessEqual(self.nep.calls, 33)
        self.assertEqual(uitkomsten.count(200), self.nep.calls)
        self.assertEqual(uitkomsten.count(429), 50 - self.nep.calls)
        self.assertLessEqual(self.week_totaal(), 200)
        self.assertEqual(self.week_totaal(), 6 * self.nep.calls)

    def test_zelfde_pand_tegelijk_wordt_niet_twee_keer_betaald(self):
        binnen, verder = threading.Event(), threading.Event()

        def houd_vast(pand):
            binnen.set()
            verder.wait(10)

        self.nep.controle = houd_vast
        eerste = []
        t = threading.Thread(target=lambda: eerste.append(self.zoek()))
        t.start()
        self.assertTrue(binnen.wait(10))
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["kosten_cent"]), (409, 0))
        self.assertIn("wordt al opgezocht", antwoord["fout"])
        verder.set()
        t.join(10)
        self.assertEqual(eerste[0][0], 200)
        self.assertEqual(self.nep.calls, 1)
        self.assertEqual(self.week_totaal(), 6)


# --------------------------------------------------------------------- criterium 9
class Herstart(Opzet):
    def test_zelfde_bestand_zelfde_totaal(self):
        for i in range(1, 6):
            self.zoek(pand=f"05031000000{i:05d}")
        self.assertEqual(self.week_totaal(), 30)
        self.stop()
        self.start()
        status, antwoord, _ = self.zoek(pand="0503100000000006")
        self.assertEqual((status, antwoord["resterend_cent"]), (200, 200 - 36))


# --------------------------------------------------------------------- criterium 10
class Sleutels(Opzet):
    def test_zonder_sleutel_niet_ingesteld(self):
        for waarde in (None, "", "   "):
            with self.subTest(waarde=waarde):
                if waarde is None:
                    self.omgeving.pop("NEP_SLEUTEL", None)
                else:
                    self.omgeving["NEP_SLEUTEL"] = waarde
                status, antwoord, _ = self.zoek()
                self.assertEqual((status, antwoord["kosten_cent"]), (503, 0))
                self.assertEqual(antwoord["fout"], "Nepbron is niet ingesteld. Er is niets opgevraagd.")
        self.assertEqual(self.nep.calls, 0)
        self.assertEqual(self.week_totaal(), 0)

    def test_sleutel_komt_nergens_terug(self):
        antwoorden = [self.zoek()]
        self.nep.gooi = RuntimeError(f"apikey {SLEUTEL} geweigerd")
        antwoorden.append(self.zoek(pand="0503100000000002"))
        for status, antwoord, koppen in antwoorden:
            self.assertNotIn(SLEUTEL, json.dumps(antwoord))
            self.assertNotIn(SLEUTEL, json.dumps(koppen))
        self.assertNotIn(SLEUTEL, "\n".join(self.log))
        self.assertNotIn(SLEUTEL, self.grootboek.read_text("utf-8"))

    def test_niet_gekoppelde_bron(self):
        self.stop()
        self.start(bronnen={})
        status, antwoord, _ = self.zoek()
        self.assertEqual((status, antwoord["fout"]), (503, "Nepbron is nog niet gekoppeld. Er is niets opgevraagd."))

    def test_in_deze_story_is_niets_gekoppeld(self):
        self.assertEqual(betaald.GEKOPPELD, {})


# --------------------------------------------------------------------- de deploy van vandaag
class ZoalsRailwayNu(unittest.TestCase):
    """Echte config.yaml en output/, geen VASTGOED_GROOTBOEK, geen sleutels: alles dicht."""

    def test_weigert_met_geen_opslag(self):
        log = []
        bewaker = betaald.Bewaker(dict(GEHEIM), BASIS / "config.yaml", BASIS / "output", BASIS, time.time, log=log.append)
        for bron in ("kvk", "kadaster_koopsom"):
            with self.subTest(bron=bron):
                self.assertEqual(bewaker.zoek(bron, "0503100000026198"),
                                 (503, {"fout": betaald.GEEN_OPSLAG, "kosten_cent": 0}))


if __name__ == "__main__":
    unittest.main()
