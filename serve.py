"""
Serveert het dashboard (design/) op Railway, alleen met de standaardbibliotheek.

Zonder geldige sessie geeft de server alleen de inlogpagina (VA-50). Er is één gedeeld
Levrai-account; gebruikersnaam, wachtwoord en de sleutel waarmee sessies worden
ondertekend komen uit omgevingsvariabelen (Railway), nooit uit een bestand in git:

    VASTGOED_GEBRUIKER       gebruikersnaam van het gedeelde account
    VASTGOED_WACHTWOORD      wachtwoord van het gedeelde account
    VASTGOED_SESSIESLEUTEL   lange willekeurige tekst om sessies te ondertekenen
    VASTGOED_BLIJVEN_DAGEN   dagen dat "Ingelogd blijven" geldt (standaard 30)
    VASTGOED_POGINGEN        mislukte inlogs per adres voordat het dichtgaat (standaard 5)
    VASTGOED_VENSTER_MIN     binnen hoeveel minuten die tellen (standaard 15)
    VASTGOED_BLOKKADE_MIN    hoeveel minuten het adres daarna dicht is (standaard 15)

Ontbreekt een van de eerste drie, is de sleutel korter dan 32 tekens of is het wachtwoord
leeg na het weghalen van spaties, dan lukt geen enkele inlog en blijft het dashboard dicht.
De poort komt uit PORT (Railway zet die); lokaal is het 8000. De pipeline draait hier nooit.

    python serve.py            # http://localhost:8000/
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import html
import ipaddress
import os
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BASIS = Path(__file__).resolve().parent
DESIGN = BASIS / "design"
LOGIN_SJABLOON = BASIS / "web" / "login.html"
STANDAARD_POORT = 8000

VAR_GEBRUIKER = "VASTGOED_GEBRUIKER"
VAR_WACHTWOORD = "VASTGOED_WACHTWOORD"
VAR_SLEUTEL = "VASTGOED_SESSIESLEUTEL"
VAR_BLIJVEN = "VASTGOED_BLIJVEN_DAGEN"
STANDAARD_BLIJVEN_DAGEN = 30  # Nova's lezing (VA-50), niet Ayman's besluit; de variabele wint
VAR_POGINGEN = "VASTGOED_POGINGEN"
VAR_VENSTER = "VASTGOED_VENSTER_MIN"
VAR_BLOKKADE = "VASTGOED_BLOKKADE_MIN"
# Nova's lezing (VA-51), niet Ayman's besluit; de variabelen winnen.
STANDAARD_POGINGEN, STANDAARD_VENSTER_MIN, STANDAARD_BLOKKADE_MIN = 5, 15, 15
# Een sessie zonder "Ingelogd blijven" heeft een cookie zonder vervaldatum (eindigt met de
# browser); de server laat hem na deze tijd ook zelf vervallen.
BROWSERSESSIE_SECONDEN = 24 * 3600
COOKIE = "vastgoed_sessie"
MAX_FORMULIER = 4096  # bytes; een inlogformulier is nooit groter
MIN_SLEUTEL_TEKENS = 32
SOCKET_TIMEOUT_SECONDEN = 30  # een verbinding die blijft hangen, houdt geen thread vast
HSTS_SECONDEN = 365 * 86400


def poort_uit_omgeving(omgeving: dict[str, str] | None = None) -> int:
    """De poort uit PORT, of 8000. Een ongeldige waarde stopt met een duidelijke fout."""
    waarde = (omgeving if omgeving is not None else os.environ).get("PORT", "").strip()
    if not waarde:
        return STANDAARD_POORT
    try:
        poort = int(waarde)
    except ValueError:
        raise SystemExit(f"FOUT: PORT moet een getal zijn, niet {waarde!r}") from None
    if not 0 < poort < 65536:
        raise SystemExit(f"FOUT: PORT {poort} ligt buiten 1-65535")
    return poort


def _als_bytes(tekst: str) -> bytes:
    """UTF-8 voor elke Python-tekst, ook met losse surrogaten uit een omgevingsvariabele."""
    return tekst.encode("utf-8", "surrogatepass")


class Instellingen:
    """Account en sessieduur uit de omgeving. Wat ontbreekt of te zwak is, sluit de inlog af."""

    def __init__(self, omgeving: dict[str, str]):
        self.gebruiker = omgeving.get(VAR_GEBRUIKER, "")
        self.wachtwoord = omgeving.get(VAR_WACHTWOORD, "")
        sleutel = omgeving.get(VAR_SLEUTEL, "")
        self.sleutel = _als_bytes(sleutel)
        self.ontbreekt = [naam for naam, waarde in ((VAR_GEBRUIKER, self.gebruiker),
                                                    (VAR_WACHTWOORD, self.wachtwoord),
                                                    (VAR_SLEUTEL, sleutel)) if not waarde]
        self.zwak = []
        if sleutel and len(sleutel.strip()) < MIN_SLEUTEL_TEKENS:
            self.zwak.append(f"{VAR_SLEUTEL} is korter dan {MIN_SLEUTEL_TEKENS} tekens")
        if self.wachtwoord and not self.wachtwoord.strip():
            self.zwak.append(f"{VAR_WACHTWOORD} bestaat alleen uit spaties")
        ruw = omgeving.get(VAR_BLIJVEN, "").strip()
        self.blijven_melding = ""
        try:
            dagen = int(ruw) if ruw else STANDAARD_BLIJVEN_DAGEN
            if dagen < 1:
                raise ValueError
        except ValueError:
            dagen = STANDAARD_BLIJVEN_DAGEN
            self.blijven_melding = f"{VAR_BLIJVEN} is geen heel getal van minstens 1"
        self.blijven_dagen = dagen

    @property
    def compleet(self) -> bool:
        return not self.ontbreekt and not self.zwak

    def waarschuwingen(self) -> list[str]:
        """Regels voor het log bij het starten: alleen namen van variabelen, nooit waarden."""
        regels = []
        if self.ontbreekt:
            regels.append(f"{', '.join(self.ontbreekt)} ontbreekt")
        regels.extend(self.zwak)
        return [f"LET OP: {regel}; elke inlog wordt geweigerd en het dashboard blijft dicht."
                for regel in regels]

    def klopt(self, gebruiker: str, wachtwoord: str) -> bool:
        """Beide vergelijkingen altijd uitvoeren, in constante tijd; nooit zeggen welke faalde."""
        if not self.compleet:
            return False
        g = hmac.compare_digest(_als_bytes(gebruiker), _als_bytes(self.gebruiker))
        w = hmac.compare_digest(_als_bytes(wachtwoord), _als_bytes(self.wachtwoord))
        return g and w


class Sessies:
    """
    Sessies in het geheugen van de server, met een ondertekende cookie.

    De cookie is '<id>.<handtekening>'. Alleen een id die de server zelf heeft uitgegeven,
    die niet is uitgelogd en niet verlopen is, geldt. Uitloggen haalt het id hier weg, dus
    dezelfde cookie werkt daarna nooit meer. Een herstart wist alle sessies (VA-50 crit. 6).
    """

    def __init__(self, sleutel: bytes, klok=time.time):
        self._sleutel = sleutel
        self._klok = klok
        self._geldig: dict[str, float] = {}
        self._slot = threading.Lock()

    def _teken(self, sid: str) -> str:
        return hmac.new(self._sleutel, sid.encode("ascii"), hashlib.sha256).hexdigest()

    def nieuw(self, seconden: float) -> str:
        sid = secrets.token_urlsafe(32)
        with self._slot:
            self._geldig[sid] = self._klok() + seconden
        return f"{sid}.{self._teken(sid)}"

    def _id(self, cookie: str | None) -> str | None:
        # De server geeft alleen ASCII uit; al het andere is geen sessie.
        if not cookie or not self._sleutel or not cookie.isascii() or cookie.count(".") != 1:
            return None
        sid, teken = cookie.split(".")
        if not hmac.compare_digest(teken.encode("ascii"), self._teken(sid).encode("ascii")):
            return None
        return sid

    def geldig(self, cookie: str | None) -> bool:
        sid = self._id(cookie)
        if sid is None:
            return False
        with self._slot:
            tot = self._geldig.get(sid)
            if tot is None:
                return False
            if self._klok() >= tot:
                del self._geldig[sid]
                return False
            return True

    def beeindig(self, cookie: str | None) -> None:
        sid = self._id(cookie)
        if sid is not None:
            with self._slot:
                self._geldig.pop(sid, None)


def _getal(omgeving: dict[str, str], naam: str, standaard: int) -> int:
    """Een heel getal van minstens 1 uit de omgeving; anders de standaardwaarde."""
    try:
        waarde = int(omgeving.get(naam, "").strip() or standaard)
    except ValueError:
        return standaard
    return waarde if waarde >= 1 else standaard


class Pogingen:
    """
    Mislukte inlogpogingen per clientadres (VA-51). Na `limiet` mislukkingen binnen
    `venster` seconden weigert de server dat adres `blokkade` seconden lang, ook met het
    goede wachtwoord. Het account zelf wordt nooit geblokkeerd: met één gedeeld account
    zou iedereen met de URL anders heel Levrai buiten kunnen sluiten.
    """

    def __init__(self, limiet: int, venster: float, blokkade: float, klok=time.time):
        self.limiet, self.venster, self.blokkade = limiet, venster, blokkade
        self._klok = klok
        self._fouten: dict[str, list[float]] = {}
        self._dicht_tot: dict[str, float] = {}
        self._slot = threading.Lock()

    def wacht(self, adres: str) -> float:
        """Seconden dat dit adres nog geweigerd wordt; 0 als het mag proberen."""
        with self._slot:
            tot = self._dicht_tot.get(adres)
            if tot is None:
                return 0.0
            rest = tot - self._klok()
            if rest <= 0:
                del self._dicht_tot[adres]
                return 0.0
            return rest

    def mislukt(self, adres: str) -> None:
        with self._slot:
            nu = self._klok()
            recent = [t for t in self._fouten.get(adres, []) if nu - t < self.venster]
            recent.append(nu)
            if len(recent) >= self.limiet:
                self._dicht_tot[adres] = nu + self.blokkade
                self._fouten.pop(adres, None)
            else:
                self._fouten[adres] = recent

    def gelukt(self, adres: str) -> None:
        with self._slot:
            self._fouten.pop(adres, None)


def client_adres(real_ip: list[str] | None, socket_adres: str) -> str:
    """
    Het adres van de bezoeker: de laatste X-Real-IP-regel, de kop die Railway documenteert
    voor het echte clientadres (docs.railway.com/networking/public-networking/specs-and-limits).
    X-Forwarded-For wordt niet gelezen: Railway's eigen antwoorden spreken elkaar tegen over
    welke positie daarin te vertrouwen is. Zonder geldig IP-adres (lokaal) telt de verbinding.
    """
    try:
        # Een regel kan een lijst zijn ("a, b"); dan telt het laatste adres, net als de laatste regel.
        return str(ipaddress.ip_address((real_ip or [""])[-1].rsplit(",", 1)[-1].strip()))
    except ValueError:
        return socket_adres


def lees_cookie(kop: str | None, naam: str = COOKIE) -> str | None:
    for deel in (kop or "").split(";"):
        k, _, v = deel.strip().partition("=")
        if k == naam:
            return v
    return None


# Copy uit Lumi's copytabel (design/login.html, VA-49).
TITEL = "Inloggen · Levrai Vastgoed"
TITEL_FOUT = "Inloggen mislukt · Levrai Vastgoed"
FOUTMELDING = "Gebruikersnaam of wachtwoord klopt niet. Probeer het opnieuw."
# VA-51; nog niet in Lumi's copytabel, ter controle aan haar voorgelegd.
TE_VAAK = "Te veel mislukte pogingen. Probeer het over {minuten} opnieuw."


def te_vaak_melding(seconden: float) -> str:
    minuten = max(1, -(-int(seconden) // 60))
    return TE_VAAK.format(minuten="1 minuut" if minuten == 1 else f"{minuten} minuten")


def login_pagina(fout: bool = False, gebruiker: str = "", melding: str = FOUTMELDING) -> bytes:
    """
    De inlogpagina. Na een mislukte login: titel en foutblok gevuld, beide velden gemarkeerd
    (niet te zien welke fout was), de getypte gebruikersnaam terug, het wachtwoord leeg en
    met de focus, zodat een schermlezer de fout via aria-describedby hoort.
    """
    invullen = {
        "{{titel}}": TITEL_FOUT if fout else TITEL,
        "{{fout}}": ('<span class="ic" aria-hidden="true">!</span>' + html.escape(melding)) if fout else "",
        "{{veld_fout}}": ' aria-invalid="true" aria-describedby="fout"' if fout else "",
        "{{focus_gebruiker}}": "" if fout else " autofocus",
        "{{focus_wachtwoord}}": " autofocus" if fout else "",
        # Als laatste: wat iemand typt, wordt daarna nergens meer vervangen.
        "{{gebruiker}}": html.escape(gebruiker, quote=True),
    }
    pagina = LOGIN_SJABLOON.read_text(encoding="utf-8")
    for plek, waarde in invullen.items():
        pagina = pagina.replace(plek, waarde)
    return pagina.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    """Statisch uit design/, maar alleen met een geldige sessie; anders de inlogpagina."""

    server_version = "Vastgoed"
    sys_version = ""
    timeout = SOCKET_TIMEOUT_SECONDEN

    def __init__(self, *args, instellingen: Instellingen, sessies: Sessies, pogingen: Pogingen,
                 **kwargs):
        self.instellingen = instellingen
        self.sessies = sessies
        self.pogingen = pogingen
        super().__init__(*args, **kwargs)

    # ---------------------------------------------------------------- hulpjes
    def _pad(self) -> str:
        return urlsplit(self.path).path

    def _ingelogd(self) -> bool:
        return self.sessies.geldig(lees_cookie(self.headers.get("Cookie")))

    def _laatste_kop(self, naam: str) -> str:
        """
        Het laatste item van een kop, want wat de proxy toevoegt staat achteraan. Een verzoek
        dat niet te lezen was, heeft nog geen `headers`, maar krijgt wel een foutantwoord.
        """
        koppen = getattr(self, "headers", None)
        waarden = koppen.get_all(naam) if koppen is not None else None
        return waarden[-1].rsplit(",", 1)[-1].strip() if waarden else ""

    def _via_https(self) -> bool:
        return self._laatste_kop("X-Forwarded-Proto").lower() == "https"

    def _zelfde_herkomst(self) -> bool:
        """
        Weigert een POST vanaf een andere site (afgedwongen lockout of uitloggen). Browsers
        sturen Origin bij elke POST, ook zonder JavaScript en vanaf dezelfde site. Geen Origin
        betekent dus: geen browser (curl en dergelijke), en die kan elke kop zelf invullen, dus
        weigeren levert niets op. 'null' (sandbox, data:-pagina) wordt geweigerd.
        """
        waarden = self.headers.get_all("Origin")
        if waarden is None:
            return True
        schema = self._laatste_kop("X-Forwarded-Proto").lower() or "http"
        standaard = {"https": ":443", "http": ":80"}.get(schema, "")

        def zonder_standaardpoort(url: str) -> str:
            return url.strip().lower().removesuffix(standaard) if standaard else url.strip().lower()

        # Railway geeft de oorspronkelijke host ook door in X-Forwarded-Host.
        eigen = {zonder_standaardpoort(f"{schema}://{host}")
                 for host in (self._laatste_kop("Host"), self._laatste_kop("X-Forwarded-Host")) if host}
        return len(waarden) == 1 and zonder_standaardpoort(waarden[0]) in eigen

    def _naar_https(self) -> bool:
        """Railway zet X-Forwarded-Proto; gewone http stuurt de server door naar https."""
        if self._laatste_kop("X-Forwarded-Proto").lower() == "http":
            host = self.headers.get("Host", "")
            self._doorsturen(f"https://{host}{self.path}", HTTPStatus.MOVED_PERMANENTLY)
            return True
        return False

    def _doorsturen(self, waarheen: str, status=HTTPStatus.SEE_OTHER, cookie: str | None = None):
        self.send_response(status)
        self.send_header("Location", waarheen)
        self.send_header("Content-Length", "0")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _stuur_login(self, fout=False, gebruiker="", status=HTTPStatus.OK, kop_alleen=False,
                     melding=FOUTMELDING, wacht=0.0):
        body = login_pagina(fout, gebruiker, melding)
        self.send_response(status)
        if wacht:
            self.send_header("Retry-After", str(int(wacht) + 1))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not kop_alleen:
            self.wfile.write(body)

    def _cookie(self, waarde: str, max_age: int | None) -> str:
        delen = [f"{COOKIE}={waarde}", "Path=/", "HttpOnly", "Secure", "SameSite=Lax"]
        if max_age is not None:
            delen.append(f"Max-Age={max_age}")
        return "; ".join(delen)

    def send_header(self, keyword, value):
        # Zonder Last-Modified kan een browser een beschermde pagina nooit hergebruiken.
        if keyword.lower() != "last-modified":
            super().send_header(keyword, value)

    def end_headers(self):
        """Elk antwoord gaat hierlangs, ook redirects en foutpagina's van http.server."""
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # Alleen frame-ancestors: de inline scripts en het cdnjs-script blijven werken.
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        # Niet no-referrer: dan sturen browsers Origin: null en faalt elke eigen POST.
        self.send_header("Referrer-Policy", "same-origin")
        if self._via_https():
            self.send_header("Strict-Transport-Security", f"max-age={HSTS_SECONDEN}")
        super().end_headers()

    def send_head(self):
        """Een pad met een NUL-byte laat open() een ValueError geven: dat bestand bestaat niet."""
        try:
            return super().send_head()
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None

    def list_directory(self, path):
        """Nooit een mappenlijst tonen, ook niet na inloggen."""
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    # ---------------------------------------------------------------- verzoeken
    def do_GET(self):
        self._get(kop_alleen=False)

    def do_HEAD(self):
        self._get(kop_alleen=True)

    def _get(self, kop_alleen: bool):
        if self._naar_https():
            return
        pad = self._pad()
        if pad == "/uitloggen":  # alleen POST logt uit; een link of prefetch doet niets
            return self._doorsturen("/")
        if pad == "/login":
            if self._ingelogd():
                return self._doorsturen("/")
            return self._stuur_login(kop_alleen=kop_alleen)
        if not self._ingelogd():
            return self._doorsturen("/login")
        del self.headers["If-Modified-Since"]  # nooit een 304 voor een beschermde pagina
        if kop_alleen:
            return super().do_HEAD()
        return super().do_GET()

    def do_POST(self):
        if self._naar_https():
            return
        pad = self._pad()
        if pad not in ("/login", "/uitloggen"):
            return self._doorsturen("/login")
        if not self._zelfde_herkomst():
            return self.send_error(HTTPStatus.FORBIDDEN)
        if pad == "/uitloggen":
            return self._uitloggen()
        try:
            lengte = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            lengte = -1
        if not 0 <= lengte <= MAX_FORMULIER:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        velden = parse_qs(self.rfile.read(lengte).decode("utf-8", "replace"), keep_blank_values=True)
        gebruiker = velden.get("gebruiker", [""])[0]
        wachtwoord = velden.get("wachtwoord", [""])[0]
        blijven = velden.get("blijven", [""])[0] != ""
        adres = client_adres(self.headers.get_all("X-Real-IP"), self.client_address[0])
        wacht = self.pogingen.wacht(adres)
        if wacht:
            return self._stuur_login(fout=True, gebruiker=gebruiker, status=HTTPStatus.TOO_MANY_REQUESTS,
                                     melding=te_vaak_melding(wacht), wacht=wacht)
        if not self.instellingen.klopt(gebruiker, wachtwoord):
            self.pogingen.mislukt(adres)
            return self._stuur_login(fout=True, gebruiker=gebruiker, status=HTTPStatus.UNAUTHORIZED)
        self.pogingen.gelukt(adres)
        if blijven:
            seconden = self.instellingen.blijven_dagen * 86400
            cookie = self._cookie(self.sessies.nieuw(seconden), seconden)
        else:
            cookie = self._cookie(self.sessies.nieuw(BROWSERSESSIE_SECONDEN), None)
        self._doorsturen("/", cookie=cookie)

    def _uitloggen(self):
        self.sessies.beeindig(lees_cookie(self.headers.get("Cookie")))
        self._doorsturen("/login", cookie=self._cookie("", 0))


def maak_server(poort: int, host: str = "0.0.0.0", map_: Path = DESIGN,
                omgeving: dict[str, str] | None = None, klok=time.time) -> ThreadingHTTPServer:
    """Een server die `map_` alleen na inloggen serveert."""
    omgeving = omgeving if omgeving is not None else dict(os.environ)
    instellingen = Instellingen(omgeving)
    sessies = Sessies(instellingen.sleutel, klok=klok)
    pogingen = Pogingen(_getal(omgeving, VAR_POGINGEN, STANDAARD_POGINGEN),
                        _getal(omgeving, VAR_VENSTER, STANDAARD_VENSTER_MIN) * 60,
                        _getal(omgeving, VAR_BLOKKADE, STANDAARD_BLOKKADE_MIN) * 60, klok=klok)
    handler = functools.partial(Handler, directory=str(map_), instellingen=instellingen,
                                sessies=sessies, pogingen=pogingen)
    server = ThreadingHTTPServer((host, poort), handler)
    server.instellingen = instellingen
    server.sessies = sessies
    server.pogingen = pogingen
    return server


def main() -> int:
    if not (DESIGN / "index.html").is_file():
        print(f"FOUT: {DESIGN / 'index.html'} ontbreekt", file=sys.stderr)
        return 1
    if not LOGIN_SJABLOON.is_file():
        print(f"FOUT: {LOGIN_SJABLOON} ontbreekt", file=sys.stderr)
        return 1
    poort = poort_uit_omgeving()
    server = maak_server(poort)
    ins = server.instellingen
    for regel in ins.waarschuwingen():
        print(regel, flush=True)
    if ins.blijven_melding:
        print(f"LET OP: {ins.blijven_melding}; {STANDAARD_BLIJVEN_DAGEN} dagen gebruikt.", flush=True)
    pg = server.pogingen
    print(f"Dashboard op poort {poort}, map {DESIGN}; 'Ingelogd blijven' geldt "
          f"{ins.blijven_dagen} dagen; na {pg.limiet} mislukte inlogs binnen "
          f"{int(pg.venster // 60)} min is een adres {int(pg.blokkade // 60)} min dicht.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
