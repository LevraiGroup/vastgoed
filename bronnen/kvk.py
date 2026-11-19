"""
KVK Handelsregister — welke vestigingen staan op de adressen van een pand (VA-55).

Opnieuw geschreven uit het contract in TOEKOMSTVERBETERINGEN.md (item 1, getest in
augustus 2026 met 605 calls op de testomgeving); niet uit een oud .pyc-bestand.

Contract (Zoeken v2):
  GET {basis}/zoeken?postcode=<1234AB>&huisnummer=<n>
  Header : apikey: <sleutel>
  200    : {"totaal": n, "resultaten": [{"kvkNummer", "naam", "adres": {...}, "type"}, ...]}
  404    : niets gevonden op dit adres  -> 0 vestigingen (geen fout)
  anders : fout; nooit "geen vestiging"

Omgevingsvariabelen (op Railway, nooit in een bestand):
  KVK_API_KEY   de sleutel
  KVK_BASIS     basis-URL; leeg = de gratis testomgeving (fictieve data, kost niets)

Kosten: productie rekent per bevraging. Daarom: één call per verschillend adres, nooit
een tweede poging, en `aantal_bevragingen()` geeft vóóraf hoeveel calls een pand kost
(VA-54 reserveert daarmee het budget). Het score-signaal (_sig_kvk, +4) zit hier bewust
niet in: dat is een scorewijziging en Ayman's besluit.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

NAAM = "kvk"
TEST_BASIS = "https://api.kvk.nl/test/api/v2"
PRODUCTIE_BASIS = "https://api.kvk.nl/api/v2"
VAR_SLEUTEL = "KVK_API_KEY"
VAR_BASIS = "KVK_BASIS"
TIMEOUT_SECONDEN = 10
PER_PAGINA = 100  # KVK's maximum per call; een call kost hetzelfde, dus zo min mogelijk "onvolledig"

# "Verwersdijk 144A, 2611NL Delft" -> huisnummer 144, postcode 2611NL
_ADRES = re.compile(r"\s(?P<nr>\d{1,5})\s*[A-Za-z]?[\w-]*\s*,\s*(?P<pc>\d{4}\s?[A-Za-z]{2})\b")


@dataclass(frozen=True)
class Adres:
    postcode: str
    huisnummer: int

    def tekst(self) -> str:
        return f"{self.postcode} {self.huisnummer}"


@dataclass
class Uitkomst:
    """Het antwoord voor één adres. `fout` gevuld betekent: onbekend, níet 0 vestigingen."""
    adres: Adres
    vestigingen: list[dict] = field(default_factory=list)
    fout: str = ""
    totaal: int | None = None  # KVK's eigen telling; kan groter zijn dan één pagina resultaten

    @property
    def gelukt(self) -> bool:
        return not self.fout

    @property
    def aantal(self) -> int | None:
        if self.fout:
            return None
        return self.totaal if self.totaal is not None else len(self.vestigingen)

    @property
    def onvolledig(self) -> bool:
        """KVK meldt meer vestigingen dan in dit antwoord staan (paginering)."""
        return self.totaal is not None and self.totaal > len(self.vestigingen)


class KvkFout(Exception):
    """Configuratie ontbreekt; er is niets aangeroepen."""


def instellingen(omgeving: dict[str, str] | None = None) -> tuple[str, str]:
    """(basis-URL, sleutel). Zonder KVK_BASIS de testomgeving. Zonder sleutel: KvkFout."""
    omg = omgeving if omgeving is not None else os.environ
    basis = (omg.get(VAR_BASIS) or "").strip().rstrip("/") or TEST_BASIS
    sleutel = (omg.get(VAR_SLEUTEL) or "").strip()
    if not sleutel:
        raise KvkFout(f"{VAR_SLEUTEL} ontbreekt; er is niets bij KVK opgevraagd")
    return basis, sleutel


def normaliseer_postcode(pc: str) -> str:
    return re.sub(r"\s", "", pc or "").upper()


def adres_uit_tekst(tekst: str) -> Adres | None:
    """Uit een BAG-adresregel als 'Verwersdijk 144A, 2611NL Delft'; onleesbaar -> None."""
    m = _ADRES.search(" " + (tekst or ""))
    if not m:
        return None
    return Adres(normaliseer_postcode(m.group("pc")), int(m.group("nr")))


def adressen(pand: dict) -> list[Adres]:
    """
    De verschillende postcode+huisnummer-combinaties van een pand, in vaste volgorde.
    Huisletters en toevoegingen vallen samen: KVK zoekt op postcode en huisnummer.
    """
    regels = pand.get("gekoppelde_adressen") or []
    gezien: dict[Adres, None] = {}
    for regel in regels:
        a = adres_uit_tekst(regel)
        if a:
            gezien.setdefault(a, None)
    if not gezien and pand.get("hoofdadres"):
        a = adres_uit_tekst(pand["hoofdadres"])
        if a:
            gezien[a] = None
    if not gezien and pand.get("postcode") and pand.get("huisnummer") is not None:
        gezien[Adres(normaliseer_postcode(pand["postcode"]), int(pand["huisnummer"]))] = None
    return list(gezien)


def aantal_bevragingen(pand: dict) -> int:
    """Hoeveel KVK-calls dit pand kost, vóór er iets wordt aangeroepen (VA-54)."""
    return len(adressen(pand))


def _http_get(url: str, koppen: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """Eén GET. Geeft (status, body); een netwerkfout of timeout gaat als exceptie door."""
    verzoek = urllib.request.Request(url, headers=koppen, method="GET")
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            return antwoord.status, antwoord.read()
    except urllib.error.HTTPError as fout:
        try:
            return fout.code, fout.read()
        finally:
            fout.close()


def zoek_adres(adres: Adres, basis: str, sleutel: str, http_get=_http_get,
               timeout: float = TIMEOUT_SECONDEN) -> Uitkomst:
    """Eén bevraging, nooit opnieuw geprobeerd: een tweede poging is een tweede betaalde call."""
    query = urllib.parse.urlencode({"postcode": adres.postcode, "huisnummer": adres.huisnummer,
                                    "resultatenPerPagina": PER_PAGINA})
    url = f"{basis}/zoeken?{query}"
    try:
        status, body = http_get(url, {"apikey": sleutel, "Accept": "application/json"}, timeout)
    except (TimeoutError, OSError, http.client.HTTPException) as fout:  # URLError is een OSError
        return Uitkomst(adres, fout=f"KVK gaf geen antwoord ({type(fout).__name__})")
    if status == 404:
        return Uitkomst(adres)  # bevestigd: niets geregistreerd op dit adres
    if status != 200:
        return Uitkomst(adres, fout=f"KVK antwoordde met HTTP {status}")
    try:
        data = json.loads(body.decode("utf-8"))
        resultaten = data.get("resultaten")
        if not isinstance(resultaten, list):
            raise ValueError("geen lijst 'resultaten'")
        vestigingen = [{"kvkNummer": str(r["kvkNummer"]), "naam": str(r.get("naam", "")),
                        "type": str(r.get("type", ""))} for r in resultaten]
        totaal = data.get("totaal")
        if totaal is not None and (not isinstance(totaal, int) or totaal < len(vestigingen)):
            raise ValueError(f"'totaal' {totaal!r} past niet bij {len(vestigingen)} resultaten")
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError) as fout:
        return Uitkomst(adres, fout=f"KVK-antwoord onleesbaar ({fout})")
    return Uitkomst(adres, vestigingen, totaal=totaal)


def zoek_pand(pand: dict, omgeving: dict[str, str] | None = None, http_get=_http_get,
              timeout: float = TIMEOUT_SECONDEN) -> list[Uitkomst]:
    """Per adres van het pand de vestigingen. Precies aantal_bevragingen(pand) calls."""
    basis, sleutel = instellingen(omgeving)
    return [zoek_adres(a, basis, sleutel, http_get, timeout) for a in adressen(pand)]


def zoek_voor_bewaker(pand: dict, sleutel: str, omgeving: dict[str, str] | None = None,
                      http_get=_http_get) -> dict:
    """
    De KVK-bron voor betaald.py (VA-56): de sleutel komt van de bewaker, de basis-URL uit KVK_BASIS.
    Precies aantal_bevragingen(pand) calls. Geeft een JSON-baar antwoord voor het dashboard.
    """
    omg = dict(os.environ if omgeving is None else omgeving)
    omg[VAR_SLEUTEL] = sleutel
    basis, sleutel = instellingen(omg)
    uitkomsten = [zoek_adres(a, basis, sleutel, http_get) for a in adressen(pand)]
    return {
        "omgeving": "productie" if basis == PRODUCTIE_BASIS else ("test" if basis == TEST_BASIS else "anders"),
        "adressen": [{"adres": u.adres.tekst(), "aantal": u.aantal, "vestigingen": u.vestigingen,
                      "onvolledig": u.onvolledig, "fout": u.fout} for u in uitkomsten],
    }


if __name__ == "__main__":
    # Live controle tegen de testomgeving, alleen met KVK_API_KEY in de eigen shell:
    #   python -m bronnen.kvk 1234AB 1
    import sys
    if len(sys.argv) != 3:
        sys.exit("gebruik: python -m bronnen.kvk <postcode> <huisnummer>")
    b, s = instellingen()
    u = zoek_adres(Adres(normaliseer_postcode(sys.argv[1]), int(sys.argv[2])), b, s)
    print(f"{b}: {u.adres.tekst()} -> " + (f"FOUT: {u.fout}" if u.fout else
          f"{u.aantal} vestiging(en) " + json.dumps(u.vestigingen, ensure_ascii=False)))
