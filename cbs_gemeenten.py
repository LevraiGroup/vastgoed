"""
De gemeenten van Nederland met hun inwonertal op 1 januari, uit CBS StatLine (VA-65).

Bron: CBS-tabel 03759ned "Bevolking op 1 januari en gemiddeld; geslacht, leeftijd en regio",
open data via https://opendata.cbs.nl/ODataApi/odata/03759ned, zonder sleutel. Het script neemt
de totalen van geslacht, leeftijd en burgerlijke staat, alle regio's die met GM beginnen, en de
nieuwste periode waarvoor gemeentecijfers bestaan.

Schrijft referentie/gemeenten_cbs_<peiljaar>.csv (';', UTF-8 met BOM, zoals output/) en
referentie/gemeenten_cbs_<peiljaar>.bron.json met tabel, titel, peiljaar en ophaaldatum.
Een bestaand bestand wordt nooit overschreven. run_proef.py haalt niets op: het leest het
nieuwste bestand dat er staat.

    python cbs_gemeenten.py        # eens per jaar, als CBS de cijfers van 1 januari heeft (Q2)
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
REFERENTIE = BASE / "referentie"
TABEL = "03759ned"
ODATA = f"https://opendata.cbs.nl/ODataApi/odata/{TABEL}"
TOTALEN = {"Geslacht": "T001038", "Leeftijd": "10000", "BurgerlijkeStaat": "T001019"}
ONDERWERP = "BevolkingOp1Januari_1"
KOLOMMEN = ["rang", "gemeentecode", "gemeente", "inwoners_1_januari"]
TIMEOUT = 60


class CbsFout(Exception):
    """CBS gaf geen bruikbaar antwoord; er is niets geschreven."""


def _haal(pad: str, query: dict | None = None) -> list[dict]:
    url = f"{ODATA}/{pad}?" + urllib.parse.urlencode({**(query or {}), "$format": "json"})
    verzoek = urllib.request.Request(url, headers={"User-Agent": "vastgoed-pandenselectie"})
    try:
        with urllib.request.urlopen(verzoek, timeout=TIMEOUT) as antwoord:
            return json.loads(antwoord.read().decode("utf-8"))["value"]
    except (OSError, ValueError, KeyError) as fout:
        raise CbsFout(f"CBS ({pad}) gaf geen bruikbaar antwoord: {fout}") from None


def rangschik(rijen: list[dict]) -> list[dict]:
    """Hoogste inwonertal eerst; bij gelijk inwonertal de laagste code eerst. Rang vanaf 1."""
    geordend = sorted(rijen, key=lambda r: (-r["inwoners_1_januari"], r["gemeentecode"]))
    return [{"rang": i, **r} for i, r in enumerate(geordend, start=1)]


def haal_gemeenten() -> tuple[str, str, list[dict]]:
    """(peiljaar, tabeltitel, gerangschikte gemeenten) voor de nieuwste periode met gemeentecijfers."""
    titel = _haal("TableInfos")[0]["Title"]
    namen = {r["Key"].strip(): r["Title"].strip() for r in _haal("RegioS")
             if r["Key"].startswith("GM")}
    perioden = sorted((p["Key"] for p in _haal("Perioden") if re.fullmatch(r"\d{4}JJ00", p["Key"])),
                      reverse=True)
    filter_basis = " and ".join(f"{k} eq '{v}'" for k, v in TOTALEN.items())
    for periode in perioden:
        rijen = _haal("TypedDataSet", {
            "$filter": f"{filter_basis} and Perioden eq '{periode}' and substringof('GM', RegioS)",
            "$select": f"RegioS,{ONDERWERP}"})
        gemeenten = [{"gemeentecode": r["RegioS"].strip()[2:], "gemeente": namen.get(r["RegioS"].strip(), ""),
                      "inwoners_1_januari": int(r[ONDERWERP])}
                     for r in rijen if r["RegioS"].strip().startswith("GM") and r[ONDERWERP] is not None]
        if gemeenten:
            return periode[:4], titel, rangschik(gemeenten)
    raise CbsFout("CBS heeft voor geen enkele periode gemeentecijfers in tabel " + TABEL)


def schrijf(peiljaar: str, titel: str, gemeenten: list[dict], map_: Path = REFERENTIE,
            vandaag: date | None = None) -> Path:
    """Schrijft CSV en bronbestand; een bestaand bestand blijft staan (exclusief aanmaken)."""
    map_.mkdir(exist_ok=True)
    pad = map_ / f"gemeenten_cbs_{peiljaar}.csv"
    with open(pad, "x", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=KOLOMMEN, delimiter=";")
        w.writeheader()
        w.writerows(gemeenten)
    bron = {"tabel": TABEL, "titel": titel, "peiljaar": int(peiljaar), "peildatum": f"{peiljaar}-01-01",
            "onderwerp": ONDERWERP, "totalen": TOTALEN, "url": ODATA,
            "opgehaald": (vandaag or date.today()).isoformat(), "aantal_gemeenten": len(gemeenten)}
    with open(pad.with_suffix(".bron.json"), "x", encoding="utf-8") as fh:
        json.dump(bron, fh, ensure_ascii=False, indent=2)
    return pad


def nieuwste(map_: Path = REFERENTIE) -> Path | None:
    """Het CSV-bestand met het hoogste peiljaar, of None."""
    paden = sorted(map_.glob("gemeenten_cbs_[0-9][0-9][0-9][0-9].csv"))
    return paden[-1] if paden else None


def lees(pad: Path | None = None) -> list[dict]:
    """De gemeenten uit een referentiebestand (standaard het nieuwste), in rangvolgorde."""
    pad = pad or nieuwste()
    if pad is None:
        raise FileNotFoundError(f"geen gemeenten_cbs_<jaar>.csv in {REFERENTIE}; draai cbs_gemeenten.py")
    with open(pad, newline="", encoding="utf-8-sig") as fh:
        return [{"rang": int(r["rang"]), "gemeentecode": r["gemeentecode"], "gemeente": r["gemeente"],
                 "inwoners_1_januari": int(r["inwoners_1_januari"])} for r in csv.DictReader(fh, delimiter=";")]


def grootste(n: int = 25, pad: Path | None = None) -> list[dict]:
    """De n gemeenten met de meeste inwoners."""
    return [g for g in lees(pad) if g["rang"] <= n]


def main() -> int:
    try:
        peiljaar, titel, gemeenten = haal_gemeenten()
    except CbsFout as fout:
        print(f"FOUT: {fout}. Er is niets geschreven.", file=sys.stderr)
        return 1
    try:
        pad = schrijf(peiljaar, titel, gemeenten)
    except FileExistsError:
        print(f"Niets geschreven: {REFERENTIE / f'gemeenten_cbs_{peiljaar}.csv'} bestaat al "
              f"(peiljaar {peiljaar} is binnen).", file=sys.stderr)
        return 1
    top = ", ".join(g["gemeente"] for g in gemeenten[:3])
    print(f"{len(gemeenten)} gemeenten, peildatum 1 januari {peiljaar} -> {pad.relative_to(BASE)} "
          f"(grootste: {top})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
