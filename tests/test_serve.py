"""
VA-46 en VA-50: serve.py serveert design/ op de poort uit PORT, en alleen na inloggen.
Alleen standaardbibliotheek, alleen localhost, geen netwerk naar buiten.
"""
import http.client
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serve  # noqa: E402

GEHEIM = {"VASTGOED_GEBRUIKER": "levrai", "VASTGOED_WACHTWOORD": "juist-wachtwoord",
          "VASTGOED_SESSIESLEUTEL": "testsleutel-" + "x" * 40}
FIGUUR = "1.668"  # een cijfer dat alleen op het dashboard staat


class Klok:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Poort(unittest.TestCase):
    def test_standaard_8000(self):
        self.assertEqual(serve.poort_uit_omgeving({}), 8000)
        self.assertEqual(serve.poort_uit_omgeving({"PORT": " "}), 8000)

    def test_uit_port(self):
        self.assertEqual(serve.poort_uit_omgeving({"PORT": "8080"}), 8080)

    def test_ongeldig_stopt(self):
        for waarde in ("$PORT", "abc", "0", "70000"):
            with self.subTest(waarde=waarde), self.assertRaises(SystemExit):
                serve.poort_uit_omgeving({"PORT": waarde})


class Instellingen(unittest.TestCase):
    def test_compleet(self):
        ins = serve.Instellingen(GEHEIM)
        self.assertTrue(ins.compleet)
        self.assertTrue(ins.klopt("levrai", "juist-wachtwoord"))
        self.assertFalse(ins.klopt("levrai", "fout"))
        self.assertFalse(ins.klopt("ander", "juist-wachtwoord"))

    def test_ontbrekende_variabele_weigert_alles(self):
        for weg in GEHEIM:
            with self.subTest(weg=weg):
                omg = {k: v for k, v in GEHEIM.items() if k != weg}
                ins = serve.Instellingen(omg)
                self.assertEqual(ins.ontbreekt, [weg])
                self.assertFalse(ins.klopt("levrai", "juist-wachtwoord"))
                self.assertFalse(ins.klopt("", ""))

    def test_blijven_dagen(self):
        self.assertEqual(serve.Instellingen(GEHEIM).blijven_dagen, 30)
        self.assertEqual(serve.Instellingen({**GEHEIM, "VASTGOED_BLIJVEN_DAGEN": "7"}).blijven_dagen, 7)
        for fout in ("0", "-3", "drie", "1.5"):
            with self.subTest(fout=fout):
                ins = serve.Instellingen({**GEHEIM, "VASTGOED_BLIJVEN_DAGEN": fout})
                self.assertEqual(ins.blijven_dagen, 30)
                self.assertIn("VASTGOED_BLIJVEN_DAGEN", ins.blijven_melding)


class Sessies(unittest.TestCase):
    def test_vervalt_en_wordt_vervalst_geweigerd(self):
        klok = Klok()
        s = serve.Sessies(b"sleutel", klok=klok)
        c = s.nieuw(60)
        self.assertTrue(s.geldig(c))
        sid, teken = c.split(".")
        self.assertFalse(s.geldig(f"{sid}.{'0' * len(teken)}"))
        self.assertFalse(s.geldig(f"{sid}x.{teken}"))
        self.assertFalse(s.geldig(sid))
        self.assertFalse(s.geldig(None))
        klok.t += 61
        self.assertFalse(s.geldig(c))

    def test_andere_sleutel_kent_de_cookie_niet(self):
        a = serve.Sessies(b"sleutel-a")
        self.assertFalse(serve.Sessies(b"sleutel-b").geldig(a.nieuw(60)))

    def test_uitloggen_is_definitief(self):
        s = serve.Sessies(b"sleutel")
        c = s.nieuw(60)
        s.beeindig(c)
        self.assertFalse(s.geldig(c))


class Server(unittest.TestCase):
    """Een echte server op 127.0.0.1 met een tijdelijke design/-map."""

    omgeving = GEHEIM

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.design = root / "design"
        self.design.mkdir()
        self.index = f"<!doctype html><title>Dashboard</title>{FIGUUR}".encode("utf-8")
        (self.design / "index.html").write_bytes(self.index)
        (self.design / "werklijst.csv").write_text(f"score;{FIGUUR}", encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "vbo_delft.json").write_text("{}", encoding="utf-8")

        self.klok = Klok()
        self.server = serve.maak_server(0, host="127.0.0.1", map_=self.design,
                                        omgeving=dict(self.omgeving), klok=self.klok)
        stil = mock.patch.object(serve.Handler, "log_message", lambda *a, **k: None)
        stil.start()
        self.addCleanup(stil.stop)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.poort = self.server.server_address[1]

    def vraag(self, methode, pad, body=None, cookie=None, koppen=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.poort, timeout=5)
        self.addCleanup(conn.close)
        k = dict(koppen or {})
        if cookie:
            k["Cookie"] = f"{serve.COOKIE}={cookie}"
        if body is not None:
            body = urlencode(body)
            k["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(methode, pad, body=body, headers=k)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def inloggen(self, blijven=False, wachtwoord="juist-wachtwoord"):
        velden = {"gebruiker": "levrai", "wachtwoord": wachtwoord}
        if blijven:
            velden["blijven"] = "1"
        return self.vraag("POST", "/login", velden)

    def cookie_uit(self, koppen):
        set_cookie = koppen.get("Set-Cookie", "")
        return set_cookie.split(";")[0].partition("=")[2], set_cookie


class ZonderSessie(Server):
    def test_alles_gaat_naar_de_inlogpagina(self):
        for pad in ("/", "/index.html", "/design/index.html", "/werklijst.csv",
                    "/output/mastervoorraad_delft.csv", "/data/vbo_delft.json", "/../data/vbo_delft.json"):
            with self.subTest(pad=pad):
                status, koppen, body = self.vraag("GET", pad)
                self.assertEqual(status, 303)
                self.assertEqual(koppen["Location"], "/login")
                self.assertNotIn(FIGUUR.encode(), body)

    def test_inlogpagina(self):
        status, koppen, body = self.vraag("GET", "/login")
        self.assertEqual(status, 200)
        self.assertNotIn(FIGUUR.encode(), body)
        tekst = body.decode("utf-8")
        self.assertIn("<title>Inloggen · Levrai Vastgoed</title>", tekst)
        self.assertIn('action="/login"', tekst)
        self.assertNotIn("{{", tekst)
        self.assertIn("no-store", koppen["Cache-Control"])

    def test_head_lekt_niets(self):
        status, koppen, body = self.vraag("HEAD", "/")
        self.assertEqual(status, 303)
        self.assertEqual(body, b"")


class Inloggen(Server):
    def test_fout_wachtwoord(self):
        status, koppen, body = self.inloggen(wachtwoord="fout")
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", koppen)
        tekst = body.decode("utf-8")
        self.assertIn("<title>Inloggen mislukt · Levrai Vastgoed</title>", tekst)
        self.assertIn("Gebruikersnaam of wachtwoord klopt niet. Probeer het opnieuw.", tekst)
        self.assertIn('value="levrai"', tekst)  # getypte gebruikersnaam blijft staan
        wachtwoordveld = tekst.split('name="wachtwoord"')[1].split(">")[0]
        self.assertNotIn("value=", wachtwoordveld)  # het wachtwoord komt nooit terug
        self.assertIn("autofocus", wachtwoordveld)
        self.assertEqual(tekst.split("<body>")[1].count('aria-invalid="true"'), 2)  # niet te zien welk veld fout was
        self.assertNotIn(FIGUUR, tekst)

    def test_gebruikersnaam_wordt_geescaped(self):
        status, _, body = self.vraag("POST", "/login", {"gebruiker": '"><script>x</script>{{fout}}',
                                                       "wachtwoord": "x"})
        tekst = body.decode("utf-8")
        self.assertNotIn("<script>x", tekst)
        self.assertIn("&quot;&gt;&lt;script&gt;x&lt;/script&gt;{{fout}}", tekst)

    def test_geslaagd_zonder_blijven(self):
        status, koppen, _ = self.inloggen()
        self.assertEqual(status, 303)
        self.assertEqual(koppen["Location"], "/")
        waarde, set_cookie = self.cookie_uit(koppen)
        for vlag in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"):
            self.assertIn(vlag, set_cookie)
        self.assertNotIn("Max-Age", set_cookie)  # eindigt als de browser sluit
        self.assertNotIn("Expires", set_cookie)
        status, _, body = self.vraag("GET", "/", cookie=waarde)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.index)

    def test_geslaagd_met_blijven(self):
        _, koppen, _ = self.inloggen(blijven=True)
        waarde, set_cookie = self.cookie_uit(koppen)
        self.assertIn(f"Max-Age={30 * 86400}", set_cookie)
        self.klok.t += 29 * 86400
        self.assertEqual(self.vraag("GET", "/", cookie=waarde)[0], 200)
        self.klok.t += 2 * 86400
        status, koppen, _ = self.vraag("GET", "/", cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/login"))

    def test_vervalste_cookie(self):
        _, koppen, _ = self.inloggen()
        waarde, _ = self.cookie_uit(koppen)
        sid, teken = waarde.split(".")
        for slecht in (f"{sid}.{teken[:-1]}0" if teken[-1] != "0" else f"{sid}.{teken[:-1]}1",
                       f"a{sid}.{teken}", "", "x.y"):
            with self.subTest(slecht=slecht):
                self.assertEqual(self.vraag("GET", "/", cookie=slecht)[0], 303)

    def test_ingelogd_naar_login_gaat_naar_dashboard(self):
        waarde, _ = self.cookie_uit(self.inloggen()[1])
        status, koppen, _ = self.vraag("GET", "/login", cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/"))

    def test_buiten_design_ook_ingelogd_niet(self):
        waarde, _ = self.cookie_uit(self.inloggen()[1])
        for pad in ("/data/vbo_delft.json", "/../data/vbo_delft.json", "/%2e%2e/data/vbo_delft.json"):
            with self.subTest(pad=pad):
                self.assertEqual(self.vraag("GET", pad, cookie=waarde)[0], 404)

    def test_uitloggen_aan_de_serverkant(self):
        waarde, _ = self.cookie_uit(self.inloggen(blijven=True)[1])
        status, koppen, _ = self.vraag("POST", "/uitloggen", body={}, cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/login"))
        self.assertIn("Max-Age=0", koppen["Set-Cookie"])
        # Dezelfde cookie, opnieuw gestuurd: geweigerd.
        status, koppen, body = self.vraag("GET", "/", cookie=waarde)
        self.assertEqual((status, koppen["Location"]), (303, "/login"))
        self.assertNotIn(FIGUUR.encode(), body)

    def test_https_doorsturen(self):
        status, koppen, _ = self.vraag("GET", "/", koppen={"X-Forwarded-Proto": "http",
                                                          "Host": "vastgoed.example"})
        self.assertEqual(status, 301)
        self.assertEqual(koppen["Location"], "https://vastgoed.example/")
        status, _, _ = self.vraag("POST", "/login", {"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"},
                                  koppen={"X-Forwarded-Proto": "http", "Host": "vastgoed.example"})
        self.assertEqual(status, 301)

    def test_te_groot_formulier(self):
        status, _, _ = self.vraag("POST", "/login", {"gebruiker": "x" * 5000, "wachtwoord": "y"})
        self.assertEqual(status, 413)


class ZonderInstellingen(Server):
    omgeving = {"VASTGOED_GEBRUIKER": "levrai", "VASTGOED_WACHTWOORD": "juist-wachtwoord"}

    def test_dashboard_blijft_dicht(self):
        status, koppen, _ = self.inloggen()
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", koppen)
        self.assertEqual(self.vraag("GET", "/")[0], 303)


class Pogingen(unittest.TestCase):
    """VA-51: per adres, met een vervangende klok."""

    def test_limiet_reset_en_wissen(self):
        klok = Klok()
        pg = serve.Pogingen(3, 900, 600, klok=klok)
        for _ in range(2):
            pg.mislukt("1.1.1.1")
        self.assertEqual(pg.wacht("1.1.1.1"), 0)
        pg.mislukt("1.1.1.1")
        self.assertEqual(pg.wacht("1.1.1.1"), 600)
        self.assertEqual(pg.wacht("2.2.2.2"), 0)  # een ander adres kan nog
        klok.t += 601
        self.assertEqual(pg.wacht("1.1.1.1"), 0)

    def test_buiten_het_venster_telt_niet(self):
        klok = Klok()
        pg = serve.Pogingen(3, 900, 600, klok=klok)
        pg.mislukt("a")
        pg.mislukt("a")
        klok.t += 901
        pg.mislukt("a")
        self.assertEqual(pg.wacht("a"), 0)

    def test_goede_login_wist_de_telling(self):
        pg = serve.Pogingen(3, 900, 600, klok=Klok())
        pg.mislukt("a")
        pg.mislukt("a")
        pg.gelukt("a")
        pg.mislukt("a")
        pg.mislukt("a")
        self.assertEqual(pg.wacht("a"), 0)

    def test_client_adres(self):
        self.assertEqual(serve.client_adres(None, "10.0.0.1"), "10.0.0.1")
        self.assertEqual(serve.client_adres([], "10.0.0.1"), "10.0.0.1")
        self.assertEqual(serve.client_adres(["203.0.113.9"], "10.0.0.1"), "203.0.113.9")
        self.assertEqual(serve.client_adres(["2001:db8::1"], "10.0.0.1"), "2001:db8::1")
        # De laatste regel telt: wat de bezoeker zelf meestuurt, staat ervoor.
        self.assertEqual(serve.client_adres(["1.2.3.4", "203.0.113.9"], "10.0.0.1"), "203.0.113.9")
        # Vera: een kommalijst in één regel telt ook het laatste adres, niet de proxy.
        self.assertEqual(serve.client_adres(["1.2.3.4, 203.0.113.9"], "10.0.0.1"), "203.0.113.9")
        # Geen IP-adres: de verbinding telt, zodat rommel nooit een eigen teller krijgt.
        for rommel in (["onzin"], [""], ["1.2.3.4", "onzin"]):
            with self.subTest(rommel=rommel):
                self.assertEqual(serve.client_adres(rommel, "10.0.0.1"), "10.0.0.1")

    def test_melding(self):
        self.assertEqual(serve.te_vaak_melding(30), "Te veel mislukte pogingen. Probeer het over 1 minuut opnieuw.")
        self.assertEqual(serve.te_vaak_melding(14 * 60 + 1), "Te veel mislukte pogingen. Probeer het over 15 minuten opnieuw.")


class TeVaakOverHttp(Server):
    omgeving = {**GEHEIM, "VASTGOED_POGINGEN": "3", "VASTGOED_VENSTER_MIN": "15", "VASTGOED_BLOKKADE_MIN": "10"}

    def via(self, echt, vervalst=None):
        koppen = {"X-Real-IP": echt}
        if vervalst:
            koppen["X-Forwarded-For"] = vervalst
        return koppen

    def test_dicht_na_limiet_en_vervalste_kop_helpt_niet(self):
        for i in range(3):
            status, _, _ = self.vraag("POST", "/login", {"gebruiker": "levrai", "wachtwoord": "fout"},
                                      koppen=self.via("203.0.113.9", vervalst=f"9.9.9.{i}"))
            self.assertEqual(status, 401)
        status, koppen, body = self.vraag("POST", "/login", {"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"},
                                          koppen=self.via("203.0.113.9", vervalst="8.8.8.8"))
        self.assertEqual(status, 429)
        self.assertNotIn("Set-Cookie", koppen)
        self.assertIn("Retry-After", koppen)
        tekst = body.decode("utf-8")
        self.assertIn("Te veel mislukte pogingen. Probeer het over 10 minuten opnieuw.", tekst)
        self.assertNotIn("Gebruikersnaam of wachtwoord klopt niet", tekst)
        # Een ander adres logt gewoon in.
        self.assertEqual(self.vraag("POST", "/login", {"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"},
                                    koppen=self.via("198.51.100.7"))[0], 303)
        # Na de blokkade weer open.
        self.klok.t += 601
        self.assertEqual(self.vraag("POST", "/login", {"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"},
                                    koppen=self.via("203.0.113.9"))[0], 303)


class Rauw(Server):
    """Verzoeken als losse bytes: dubbele koppen, kapotte regels, en de echte kopvolgorde."""

    def rauw(self, regels, body=b""):
        with socket.create_connection(("127.0.0.1", self.poort), timeout=5) as s:
            s.sendall("\r\n".join(regels).encode("latin-1") + b"\r\n\r\n" + body)
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        kop, _, inhoud = data.partition(b"\r\n\r\n")
        regels_terug = kop.decode("latin-1").split("\r\n")
        status = int(regels_terug[0].split()[1])
        koppen = [tuple(r.split(": ", 1)) for r in regels_terug[1:]]
        return status, koppen, inhoud

    def post_rauw(self, koppen, wachtwoord="fout", pad="/login"):
        body = urlencode({"gebruiker": "levrai", "wachtwoord": wachtwoord}).encode("ascii")
        return self.rauw([f"POST {pad} HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(body)}",
                          "Content-Type: application/x-www-form-urlencoded", *koppen], body)

    def sessie(self):
        return self.cookie_uit(self.inloggen()[1])[0]

    def waarden(self, koppen, naam):
        return [v for k, v in koppen if k.lower() == naam.lower()]


class Cache(Rauw):
    """D1: geen enkel antwoord mag in een browsercache belanden."""

    def alle_antwoorden(self):
        sessie = self.sessie()
        cookie = f"Cookie: {serve.COOKIE}={sessie}"
        host = "Host: 127.0.0.1"
        return {
            "statisch 200": self.rauw(["GET / HTTP/1.1", host, cookie]),
            "statisch HEAD": self.rauw(["HEAD /werklijst.csv HTTP/1.1", host, cookie]),
            "statisch 404": self.rauw(["GET /bestaat-niet HTTP/1.1", host, cookie]),
            "login 200": self.rauw(["GET /login HTTP/1.1", host]),
            "zonder sessie 303": self.rauw(["GET / HTTP/1.1", host]),
            "login 401": self.post_rauw([]),
            "https 301": self.rauw(["GET / HTTP/1.1", host, "X-Forwarded-Proto: http"]),
            "501": self.rauw(["DELETE / HTTP/1.1", host]),
            "te veel koppen 431": self.rauw(["GET / HTTP/1.1", host, *[f"X-K{i}: 1" for i in range(150)]]),
        }

    def test_no_store_op_elk_antwoord(self):
        for naam, (status, koppen, _) in self.alle_antwoorden().items():
            with self.subTest(naam=naam, status=status):
                self.assertEqual(self.waarden(koppen, "Cache-Control"), ["no-store"])

    def test_verwachte_statussen(self):
        verwacht = {"statisch 200": 200, "statisch HEAD": 200, "statisch 404": 404, "login 200": 200,
                    "zonder sessie 303": 303, "login 401": 401, "https 301": 301, "501": 501,
                    "te veel koppen 431": 431}
        self.assertEqual({n: a[0] for n, a in self.alle_antwoorden().items()}, verwacht)

    def test_geen_last_modified(self):
        for naam, (status, koppen, _) in self.alle_antwoorden().items():
            with self.subTest(naam=naam, status=status):
                self.assertEqual(self.waarden(koppen, "Last-Modified"), [])

    def test_if_modified_since_geeft_nooit_304(self):
        sessie = self.sessie()
        for methode in ("GET", "HEAD"):
            with self.subTest(methode=methode):
                status, koppen, body = self.vraag(methode, "/", cookie=sessie, koppen={
                    "If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"})
                self.assertEqual(status, 200)
                if methode == "GET":
                    self.assertEqual(body, self.index)


class Uitloggen(Server):
    """D2: alleen POST beëindigt een sessie."""

    def test_get_en_head_loggen_niet_uit(self):
        waarde, _ = self.cookie_uit(self.inloggen()[1])
        for methode in ("GET", "HEAD"):
            with self.subTest(methode=methode):
                status, koppen, _ = self.vraag(methode, "/uitloggen", cookie=waarde)
                self.assertEqual((status, koppen["Location"]), (303, "/"))
                self.assertNotIn("Set-Cookie", koppen)
                self.assertEqual(self.vraag("GET", "/", cookie=waarde)[0], 200)


class VreemdeInvoer(Rauw):
    """D3 en L1: vreemde invoer is geen sessie en geen crash."""

    def test_niet_ascii_handtekening_is_geen_sessie(self):
        sid = self.sessie().split(".")[0]
        for slecht in (f"{sid}.é", f"é.{'0' * 64}", "é", f"{sid}.{'é' * 64}", ".", "..", "=;=", f"{sid}."):
            with self.subTest(slecht=slecht):
                status, koppen, _ = self.rauw(["GET / HTTP/1.1", "Host: 127.0.0.1",
                                               f"Cookie: {serve.COOKIE}={slecht}"])
                self.assertEqual(status, 303)
                self.assertEqual(self.waarden(koppen, "Location"), ["/login"])

    def test_niet_ascii_cookie_bij_uitloggen(self):
        status, _, _ = self.rauw(["POST /uitloggen HTTP/1.1", "Host: 127.0.0.1", "Content-Length: 0",
                                  f"Cookie: {serve.COOKIE}=é.é"])
        self.assertEqual(status, 303)

    def test_sessies_rechtstreeks(self):
        s = serve.Sessies(b"sleutel")
        sid = s.nieuw(60).split(".")[0]
        self.assertFalse(s.geldig(f"{sid}.é"))
        s.beeindig(f"{sid}.é")  # geen uitzondering

    def test_nul_byte_in_pad(self):
        sessie = self.sessie()
        for pad in ("/index%00.html", "/%00", "/design%00/x.csv"):
            for methode in ("GET", "HEAD"):
                with self.subTest(pad=pad, methode=methode):
                    self.assertEqual(self.vraag(methode, pad, cookie=sessie)[0], 404)

    def test_niet_ascii_wachtwoord_over_http(self):
        status, _, _ = self.vraag("POST", "/login", {"gebruiker": "gébruiker€", "wachtwoord": "wachtwoörd€"})
        self.assertEqual(status, 401)
        status, koppen, _ = self.post_rauw([])  # teller staat los van de tekens
        self.assertEqual(status, 401)
        body = b"gebruiker=%FF%FE&wachtwoord=%ED%A0%80"
        status, _, _ = self.rauw(["POST /login HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(body)}"], body)
        self.assertEqual(status, 401)

    def test_utf8_bytes_in_elke_gelezen_kop(self):
        """D3: een browser stuurt UTF-8-bytes, geen losse latin-1-tekens. Nooit een crash of 500."""
        u = "é€".encode("utf-8").decode("latin-1")  # rauw() stuurt dit als de UTF-8-bytes
        sessie = f"Cookie: {serve.COOKIE}={self.sessie()}"
        body = urlencode({"gebruiker": "levrai", "wachtwoord": "fout"}).encode("ascii")
        lengte = f"Content-Length: {len(body)}"
        gevallen = {
            "cookie": (["GET / HTTP/1.1", "Host: x", f"Cookie: {serve.COOKIE}={u}.{u}"], b"", 303),
            "cookienaam": (["GET / HTTP/1.1", "Host: x", f"Cookie: {u}={u}; {serve.COOKIE}={u}"], b"", 303),
            "pad zonder sessie": ([f"GET /{u} HTTP/1.1", "Host: x"], b"", 303),
            "pad met sessie": ([f"GET /{u} HTTP/1.1", "Host: x", sessie], b"", 404),
            "host bij doorsturen": (["GET / HTTP/1.1", f"Host: {u}", "X-Forwarded-Proto: http"], b"", 301),
            "proto": (["GET /login HTTP/1.1", "Host: x", f"X-Forwarded-Proto: {u}"], b"", 200),
            "origin": (["POST /login HTTP/1.1", "Host: x", f"Origin: {u}", lengte], body, 403),
            "real-ip": (["POST /login HTTP/1.1", "Host: x", f"X-Real-IP: {u}", lengte], body, 401),
            "content-length": (["POST /login HTTP/1.1", "Host: x", f"Content-Length: {u}"], b"", 413),
            "uitloggen": (["POST /uitloggen HTTP/1.1", "Host: x", "Content-Length: 0",
                           f"Cookie: {serve.COOKIE}={u}"], b"", 303),
        }
        for naam, (regels, inhoud, verwacht) in gevallen.items():
            with self.subTest(naam=naam):
                self.assertEqual(self.rauw(regels, inhoud)[0], verwacht)


class NietAsciiAccount(Server):
    omgeving = {**GEHEIM, "VASTGOED_GEBRUIKER": "gébruiker€", "VASTGOED_WACHTWOORD": "wachtwoörd€"}

    def test_inloggen_met_niet_ascii(self):
        status, koppen, _ = self.vraag("POST", "/login", {"gebruiker": "gébruiker€", "wachtwoord": "wachtwoörd€"})
        self.assertEqual(status, 303)
        self.assertIn("Set-Cookie", koppen)


class ZwakkeInstellingen(unittest.TestCase):
    def test_korte_sleutel_sluit_af(self):
        ins = serve.Instellingen({**GEHEIM, "VASTGOED_SESSIESLEUTEL": "k" * 31})
        self.assertFalse(ins.compleet)
        self.assertFalse(ins.klopt("levrai", "juist-wachtwoord"))

    def test_sleutel_van_32_tekens_mag(self):
        ins = serve.Instellingen({**GEHEIM, "VASTGOED_SESSIESLEUTEL": "k" * 32})
        self.assertTrue(ins.klopt("levrai", "juist-wachtwoord"))

    def test_sleutel_van_alleen_spaties_sluit_af(self):
        self.assertFalse(serve.Instellingen({**GEHEIM, "VASTGOED_SESSIESLEUTEL": " " * 40}).compleet)

    def test_wachtwoord_van_spaties_sluit_af(self):
        ins = serve.Instellingen({**GEHEIM, "VASTGOED_WACHTWOORD": " \t "})
        self.assertFalse(ins.klopt("levrai", " \t "))

    def test_waarschuwing_noemt_de_naam_en_nooit_de_waarde(self):
        ins = serve.Instellingen({"VASTGOED_GEBRUIKER": "geheime-naam", "VASTGOED_WACHTWOORD": "   ",
                                  "VASTGOED_SESSIESLEUTEL": "geheime-korte-sleutel"})
        tekst = "\n".join(ins.waarschuwingen())
        self.assertIn("VASTGOED_SESSIESLEUTEL", tekst)
        self.assertIn("VASTGOED_WACHTWOORD", tekst)
        self.assertNotIn("geheime", tekst)

    def test_waarschuwing_bij_ontbreken(self):
        ins = serve.Instellingen({k: v for k, v in GEHEIM.items() if k != "VASTGOED_WACHTWOORD"})
        self.assertIn("VASTGOED_WACHTWOORD", "\n".join(ins.waarschuwingen()))

    def test_goede_instellingen_geven_geen_waarschuwing(self):
        self.assertEqual(serve.Instellingen(GEHEIM).waarschuwingen(), [])

    def test_blijven_melding_noemt_de_waarde_niet(self):
        ins = serve.Instellingen({**GEHEIM, "VASTGOED_BLIJVEN_DAGEN": "geheime-plakfout"})
        self.assertNotIn("geheime", ins.blijven_melding)

    def test_surrogaten_in_de_omgeving_crashen_niet(self):
        ins = serve.Instellingen({**GEHEIM, "VASTGOED_WACHTWOORD": "a\udcffb"})
        self.assertTrue(ins.klopt("levrai", "a\udcffb"))
        self.assertFalse(ins.klopt("levrai", "x"))


class ZwakkeSleutelOverHttp(Server):
    omgeving = {**GEHEIM, "VASTGOED_SESSIESLEUTEL": "te-kort"}

    def test_dashboard_blijft_dicht(self):
        status, koppen, _ = self.inloggen()
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", koppen)


class Beveiligingskoppen(Rauw):
    """D5: op elk antwoord, zonder de scripts van de pagina's te raken."""

    def test_op_elk_antwoord(self):
        sessie = self.sessie()
        host = "Host: 127.0.0.1"
        for naam, (status, koppen, _) in {
            "200": self.rauw(["GET / HTTP/1.1", host, f"Cookie: {serve.COOKIE}={sessie}"]),
            "login": self.rauw(["GET /login HTTP/1.1", host]),
            "303": self.rauw(["GET / HTTP/1.1", host]),
            "401": self.post_rauw([]),
            "431": self.rauw(["GET / HTTP/1.1", host, *[f"X-K{i}: 1" for i in range(150)]]),
        }.items():
            with self.subTest(naam=naam, status=status):
                self.assertEqual(self.waarden(koppen, "X-Frame-Options"), ["DENY"])
                self.assertEqual(self.waarden(koppen, "Content-Security-Policy"), ["frame-ancestors 'none'"])
                self.assertEqual(self.waarden(koppen, "Referrer-Policy"), ["same-origin"])

    def test_hsts_alleen_via_https(self):
        self.assertEqual(self.waarden(self.rauw(["GET /login HTTP/1.1", "Host: x"])[1],
                                      "Strict-Transport-Security"), [])
        self.assertEqual(self.waarden(self.rauw(["GET / HTTP/1.1", "Host: x", "X-Forwarded-Proto: http"])[1],
                                      "Strict-Transport-Security"), [])
        hsts = self.waarden(self.rauw(["GET /login HTTP/1.1", "Host: x", "X-Forwarded-Proto: https"])[1],
                            "Strict-Transport-Security")
        self.assertEqual(len(hsts), 1)
        self.assertRegex(hsts[0], r"^max-age=\d{7,}$")

    def test_laatste_proto_telt(self):
        status, koppen, _ = self.rauw(["GET /login HTTP/1.1", "Host: x", "X-Forwarded-Proto: http",
                                       "X-Forwarded-Proto: https"])
        self.assertEqual(status, 200)
        self.assertEqual(len(self.waarden(koppen, "Strict-Transport-Security")), 1)


class Herkomst(Rauw):
    """D6: een POST van een andere site telt niet mee en doet niets."""

    omgeving = {**GEHEIM, "VASTGOED_POGINGEN": "2"}

    def goed(self):
        return f"Origin: http://127.0.0.1:{self.poort}"

    def host(self):
        return f"Host: 127.0.0.1:{self.poort}"

    def post(self, pad, koppen, body=b""):
        return self.rauw([f"POST {pad} HTTP/1.1", self.host(), f"Content-Length: {len(body)}", *koppen], body)

    def test_vreemde_origin_geweigerd_en_telt_niet(self):
        body = urlencode({"gebruiker": "levrai", "wachtwoord": "fout"}).encode("ascii")
        vreemd = ("Origin: https://evil.example", "Origin: null", f"Origin: https://127.0.0.1:{self.poort}",
                  f"Origin: http://127.0.0.1:{self.poort}.evil.example", f"Origin: http://127.0.0.1:{self.poort + 1}")
        for origin in vreemd:
            with self.subTest(origin=origin):
                self.assertEqual(self.post("/login", [origin], body)[0], 403)
        # Niets daarvan telde als mislukte poging: het goede wachtwoord werkt nog.
        self.assertEqual(self.inloggen()[0], 303)

    def test_dubbele_origin_geweigerd(self):
        self.assertEqual(self.post("/login", [self.goed(), "Origin: https://evil.example"])[0], 403)

    def test_eigen_origin_en_geen_origin_werken(self):
        goed = urlencode({"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"}).encode("ascii")
        self.assertEqual(self.post("/login", [self.goed()], goed)[0], 303)
        self.assertEqual(self.post("/login", [], goed)[0], 303)

    def test_achter_railway(self):
        goed = urlencode({"gebruiker": "levrai", "wachtwoord": "juist-wachtwoord"}).encode("ascii")
        for koppen in (["Origin: https://vastgoed.example", "X-Forwarded-Proto: https", "X-Forwarded-Host: vastgoed.example"],
                       ["Origin: https://VASTGOED.example", "X-Forwarded-Proto: https", "X-Forwarded-Host: vastgoed.example:443"]):
            with self.subTest(koppen=koppen):
                status, _, _ = self.rauw(["POST /login HTTP/1.1", "Host: intern.railway", f"Content-Length: {len(goed)}", *koppen], goed)
                self.assertEqual(status, 303)
        status, _, _ = self.rauw(["POST /login HTTP/1.1", "Host: vastgoed.example", f"Content-Length: {len(goed)}",
                                  "Origin: https://vastgoed.example", "X-Forwarded-Proto: https"], goed)
        self.assertEqual(status, 303)

    def test_uitloggen_van_andere_site_laat_de_sessie_staan(self):
        sessie = self.sessie()
        cookie = f"Cookie: {serve.COOKIE}={sessie}"
        self.assertEqual(self.post("/uitloggen", ["Origin: https://evil.example", cookie])[0], 403)
        self.assertEqual(self.vraag("GET", "/", cookie=sessie)[0], 200)
        self.assertEqual(self.post("/uitloggen", [self.goed(), cookie])[0], 303)
        self.assertEqual(self.vraag("GET", "/", cookie=sessie)[0], 303)


class Timeout(Rauw):
    """L4: een verbinding die niets stuurt, wordt gesloten."""

    def test_timeout_staat_aan(self):
        self.assertIsNotNone(serve.Handler.timeout)
        self.assertLessEqual(serve.Handler.timeout, 60)

    def test_hangende_verbinding_wordt_gesloten(self):
        with mock.patch.object(serve.Handler, "timeout", 0.2), \
                socket.create_connection(("127.0.0.1", self.poort), timeout=3) as s:
            s.sendall(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\ngebruiker=")
            self.assertEqual(s.recv(1024), b"")


class AdresOverHttp(Rauw):
    """D4: X-Real-IP is het adres; X-Forwarded-For doet er niets toe."""

    omgeving = {**GEHEIM, "VASTGOED_POGINGEN": "5"}

    def test_roulerende_forwarded_for_ontwijkt_de_lockout_niet(self):
        for i in range(5):
            self.assertEqual(self.post_rauw(["X-Real-IP: 203.0.113.9", f"X-Forwarded-For: 9.9.9.{i}"])[0], 401)
        self.assertEqual(self.post_rauw(["X-Real-IP: 203.0.113.9", "X-Forwarded-For: 9.9.9.99"],
                                        wachtwoord="juist-wachtwoord")[0], 429)
        self.assertEqual(self.post_rauw(["X-Real-IP: 198.51.100.7"], wachtwoord="juist-wachtwoord")[0], 303)

    def test_zonder_real_ip_telt_de_verbinding(self):
        for i in range(5):
            self.assertEqual(self.post_rauw([f"X-Forwarded-For: 9.9.9.{i}"])[0], 401)
        self.assertEqual(self.post_rauw(["X-Forwarded-For: 9.9.9.99"], wachtwoord="juist-wachtwoord")[0], 429)

    def test_vervalste_forwarded_for_sluit_een_ander_niet_buiten(self):
        slachtoffer = "198.51.100.7"
        for _ in range(5):
            self.post_rauw(["X-Real-IP: 203.0.113.9", f"X-Forwarded-For: {slachtoffer}"])
        self.assertEqual(self.post_rauw([f"X-Real-IP: {slachtoffer}", f"X-Forwarded-For: {slachtoffer}"],
                                        wachtwoord="juist-wachtwoord")[0], 303)

    def test_laatste_real_ip_regel_telt(self):
        for i in range(5):
            self.assertEqual(self.post_rauw([f"X-Real-IP: 9.9.9.{i}", "X-Real-IP: 203.0.113.9"])[0], 401)
        self.assertEqual(self.post_rauw(["X-Real-IP: 9.9.9.99", "X-Real-IP: 203.0.113.9"],
                                        wachtwoord="juist-wachtwoord")[0], 429)

    def test_de_blokkade_staat_op_het_real_ip(self):
        for _ in range(5):
            self.post_rauw(["X-Real-IP: 203.0.113.9"])
        self.assertGreater(self.server.pogingen.wacht("203.0.113.9"), 0)
        self.assertEqual(self.server.pogingen.wacht("127.0.0.1"), 0)


if __name__ == "__main__":
    unittest.main()
