"""
De vorm van Nederland en de plek van elke gemeente, voor de landkaart op het dashboard (VA-85).

Bron: CBS Gebiedsindelingen <peiljaar> via de WFS van PDOK, zonder sleutel, licentie CC BY 4.0:
- laag landsdeel_gegeneraliseerd: de vier landsdelen, samen het land zonder de grote wateren;
- laag gemeente_labelpoint: per gemeente het punt waar CBS haar naam zet.
Het peiljaar is dat van het nieuwste referentie/gemeenten_cbs_<jaar>.csv (VA-65), zodat de
gemeentecodes van de kaart en van de 25 grootste uit hetzelfde jaar komen.

De vier landsdelen worden één omtrek: ze worden op een raster van ongeveer 550 m gevuld, de rand
van het gevulde raster wordt gevolgd en met Douglas-Peucker vereenvoudigd tot ongeveer 1 km. Zo
verdwijnen de grenzen tussen de landsdelen, en de spleetjes waar twee landsdelen elkaar net niet
raken. Eilandjes en meren kleiner dan MIN_OPP vallen weg.

Schrijft referentie/kaart_nl_<peiljaar>.json met de bron erin. Een bestaand bestand wordt nooit
overschreven. build_dashboard.py haalt niets op: het leest het nieuwste bestand dat er staat.

    python kaart_nl.py        # eens per jaar, na cbs_gemeenten.py
"""
from __future__ import annotations

import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import cbs_gemeenten

BASE = Path(__file__).parent
REFERENTIE = BASE / "referentie"
WFS = "https://service.pdok.nl/cbs/gebiedsindelingen/{jaar}/wfs/v1_0"
LAAG_LAND = "landsdeel_gegeneraliseerd"
LAAG_GEMEENTE = "gemeente_labelpoint"
LICENTIE = "CC BY 4.0"
STAP_BREEDTE = 0.005   # graden; ca. 556 m
STAP_LENGTE = 0.008    # graden; ca. 546 m op 52° NB
TOLERANTIE = 0.009     # graden breedte, ca. 1 km: de omtrek wijkt nergens meer af
MIN_OPP = 0.002        # graden² (lengte maal cos 52°): kleiner eiland of meer valt weg, ca. 25 km²
DECIMALEN = 3
TIMEOUT = 120


class KaartFout(Exception):
    """PDOK gaf geen bruikbaar antwoord; er is niets geschreven."""


def _haal(jaar: int, laag: str) -> list[dict]:
    query = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "count": "5000",
             "typeNames": f"gebiedsindelingen:{laag}", "outputFormat": "application/json",
             "srsName": "EPSG:4326"}
    url = WFS.format(jaar=jaar) + "?" + urllib.parse.urlencode(query)
    verzoek = urllib.request.Request(url, headers={"User-Agent": "vastgoed-pandenselectie"})
    try:
        with urllib.request.urlopen(verzoek, timeout=TIMEOUT) as antwoord:
            return json.loads(antwoord.read().decode("utf-8"))["features"]
    except (OSError, ValueError, KeyError) as fout:
        raise KaartFout(f"PDOK ({laag}, {jaar}) gaf geen bruikbaar antwoord: {fout}") from None


def veelhoeken(features: list[dict]) -> list[list[list[tuple[float, float]]]]:
    """Per veelhoek zijn ringen als (lengte, breedte); MultiPolygon wordt losse veelhoeken."""
    uit = []
    for f in features:
        g = f["geometry"]
        delen = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        uit.extend([[(float(x), float(y)) for x, y in ring] for ring in deel] for deel in delen)
    return uit


def raster(vlakken, x0: float, y0: float, dx: float, dy: float, kolommen: int, rijen: int) -> set:
    """
    De cellen (kolom, rij) waarvan het midden in een veelhoek ligt; elke veelhoek apart gevuld
    (even-oneven binnen zijn eigen ringen), zodat twee landsdelen die elkaar raken niets uitwissen.
    Rij 0 ligt aan de noordkant (y0 is de bovenrand).
    """
    vol = set()
    for ringen in vlakken:
        randen = [(a, b) for ring in ringen for a, b in zip(ring, ring[1:] + ring[:1]) if a != b]
        for r in range(rijen):
            y = y0 - (r + .5) * dy
            snij = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                          for a, b in randen if (a[1] > y) != (b[1] > y))
            for links, rechts in zip(snij[::2], snij[1::2]):
                k0 = max(0, math.ceil((links - x0) / dx - .5))
                k1 = min(kolommen - 1, math.floor((rechts - x0) / dx - .5))
                vol.update((k, r) for k in range(k0, k1 + 1))
    # Een spleet van één cel tussen twee landsdelen: links en rechts, of boven en onder, is land.
    for k in range(kolommen):
        for r in range(rijen):
            if (k, r) not in vol and (((k - 1, r) in vol and (k + 1, r) in vol)
                                      or ((k, r - 1) in vol and (k, r + 1) in vol)):
                vol.add((k, r))
    return vol


def randlussen(vol: set) -> list[list[tuple[int, int]]]:
    """
    De rand van het gevulde raster als gesloten lussen van hoekpunten (kolom, rij), met het land
    steeds links. Waar twee cellen elkaar alleen in een hoek raken, buigt de lus naar het land toe.
    """
    volgende: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for k, r in vol:
        # Vier zijden van de cel; een zijde is rand als de buur leeg is. Volgorde houdt het land links.
        for buur, van, naar in (((k, r - 1), (k + 1, r), (k, r)),          # boven: oost naar west
                                ((k - 1, r), (k, r), (k, r + 1)),          # links: noord naar zuid
                                ((k, r + 1), (k, r + 1), (k + 1, r + 1)),  # onder: west naar oost
                                ((k + 1, r), (k + 1, r + 1), (k + 1, r))):  # rechts: zuid naar noord
            if buur not in vol:
                volgende.setdefault(van, []).append(naar)
    lussen = []
    while volgende:
        start = next(iter(volgende))
        lus, punt, richting = [start], start, None
        while True:
            opties = volgende[punt]
            if len(opties) == 1 or richting is None:
                naar = opties[0]
            else:  # hoekpunt met twee uitgangen: neem de linkerbocht
                links = (richting[1], -richting[0])
                naar = next((o for o in opties if (o[0] - punt[0], o[1] - punt[1]) == links), opties[0])
            opties.remove(naar)
            if not opties:
                del volgende[punt]
            richting = (naar[0] - punt[0], naar[1] - punt[1])
            punt = naar
            if punt == start:
                break
            lus.append(punt)
        lussen.append(lus)
    return lussen


def _afstand(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    lengte = math.hypot(dx, dy)
    if lengte == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / lengte


def douglas_peucker(punten: list, tol: float) -> list:
    """Een open lijn vereenvoudigd: geen weggelaten punt ligt verder dan tol van de nieuwe lijn."""
    houd = [False] * len(punten)
    houd[0] = houd[-1] = True
    stapel = [(0, len(punten) - 1)]
    while stapel:
        i, j = stapel.pop()
        if j <= i + 1:
            continue
        verst, beste = -1.0, i
        for m in range(i + 1, j):
            d = _afstand(punten[m], punten[i], punten[j])
            if d > verst:
                verst, beste = d, m
        if verst > tol:
            houd[beste] = True
            stapel += [(i, beste), (beste, j)]
    return [p for p, h in zip(punten, houd) if h]


def oppervlak(lus: list) -> float:
    """De oppervlakte van een gesloten lus (schoenveterformule), altijd positief."""
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(lus, lus[1:] + lus[:1]))) / 2


def vereenvoudig_lus(lus: list, tol: float) -> list:
    """
    Een gesloten lus, gesplitst in twee uiterste punten (het verste van het begin, en het verste
    daarvan), elke helft apart vereenvoudigd. Zo is geen van beide splitspunten een toevallig punt
    midden op een rechte rand.
    """
    def verste(van: int) -> int:
        return max(range(len(lus)), key=lambda i: math.hypot(lus[i][0] - lus[van][0], lus[i][1] - lus[van][1]))

    a = verste(0)
    lus = lus[a:] + lus[:a]
    ver = verste(0)
    heen = douglas_peucker(lus[:ver + 1], tol)
    terug = douglas_peucker(lus[ver:] + lus[:1], tol)
    return heen[:-1] + terug[:-1]


def omtrek(vlakken, cos_breedte: float | None = None) -> list[list[list[float]]]:
    """De vlakken als één vereenvoudigde omtrek: lussen van [breedte, lengte], land links."""
    xs = [x for v in vlakken for ring in v for x, _ in ring]
    ys = [y for v in vlakken for ring in v for _, y in ring]
    x0, y0 = min(xs) - STAP_LENGTE, max(ys) + STAP_BREEDTE
    kolommen = math.ceil((max(xs) - x0) / STAP_LENGTE) + 2
    rijen = math.ceil((y0 - min(ys)) / STAP_BREEDTE) + 2
    cos_b = cos_breedte or math.cos(math.radians((max(ys) + min(ys)) / 2))
    uit = []
    for lus in randlussen(raster(vlakken, x0, y0, STAP_LENGTE, STAP_BREEDTE, kolommen, rijen)):
        # Naar graden, met de lengte op schaal (maal cos breedte), zodat de tolerantie overal 1 km is.
        vlak = [((x0 + k * STAP_LENGTE) * cos_b, y0 - r * STAP_BREEDTE) for k, r in lus]
        if oppervlak(vlak) < MIN_OPP:
            continue
        kort = vereenvoudig_lus(vlak, TOLERANTIE)
        if len(kort) >= 4:
            uit.append([[round(y, DECIMALEN), round(x / cos_b, DECIMALEN)] for x, y in kort])
    return uit


def gemeentepunten(features: list[dict]) -> dict[str, list[float]]:
    """Per gemeentecode zonder 'GM' (zoals in de CBS-lijst van VA-65) het labelpunt [breedte, lengte]."""
    uit = {}
    for f in features:
        code = f["properties"]["statcode"]
        x, y = f["geometry"]["coordinates"][:2]
        uit[code[2:] if code.startswith("GM") else code] = [round(y, DECIMALEN), round(x, DECIMALEN)]
    return dict(sorted(uit.items()))


def peiljaar(pad: Path | None = None) -> int:
    """Het jaar van het nieuwste gemeenten_cbs_<jaar>.csv (VA-65)."""
    pad = pad or cbs_gemeenten.nieuwste()
    if pad is None:
        raise KaartFout(f"geen gemeenten_cbs_<jaar>.csv in {REFERENTIE}; draai eerst cbs_gemeenten.py")
    return int(re.search(r"(\d{4})", pad.stem).group(1))


def schrijf(jaar: int, land: list, gemeenten: dict, map_: Path = REFERENTIE, vandaag: date | None = None) -> Path:
    """Schrijft referentie/kaart_nl_<jaar>.json; een bestaand bestand blijft staan (exclusief aanmaken)."""
    map_.mkdir(exist_ok=True)
    pad = map_ / f"kaart_nl_{jaar}.json"
    inhoud = {
        "bron": {"titel": f"CBS Gebiedsindelingen {jaar}", "dienst": WFS.format(jaar=jaar),
                 "lagen": [LAAG_LAND, LAAG_GEMEENTE], "licentie": LICENTIE, "peiljaar": jaar,
                 "opgehaald": (vandaag or date.today()).isoformat(),
                 "bewerking": (f"landsdelen samengevoegd op een raster van {STAP_BREEDTE}° × {STAP_LENGTE}°, "
                               f"rand vereenvoudigd (Douglas-Peucker, {TOLERANTIE}°), "
                               f"eilanden en meren onder {MIN_OPP} graden² weggelaten")},
        "land": land,
        "gemeenten": gemeenten,
    }
    with open(pad, "x", encoding="utf-8", newline="\n") as fh:
        json.dump(inhoud, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    return pad


def nieuwste(map_: Path = REFERENTIE) -> Path | None:
    """Het kaartbestand met het hoogste peiljaar, of None."""
    paden = sorted(map_.glob("kaart_nl_[0-9][0-9][0-9][0-9].json"))
    return paden[-1] if paden else None


def main() -> int:
    try:
        jaar = peiljaar()
        land = omtrek(veelhoeken(_haal(jaar, LAAG_LAND)))
        gemeenten = gemeentepunten(_haal(jaar, LAAG_GEMEENTE))
    except KaartFout as fout:
        print(f"FOUT: {fout}. Er is niets geschreven.", file=sys.stderr)
        return 1
    try:
        pad = schrijf(jaar, land, gemeenten)
    except FileExistsError:
        print(f"Niets geschreven: {REFERENTIE / f'kaart_nl_{jaar}.json'} bestaat al.", file=sys.stderr)
        return 1
    print(f"{len(land)} lussen, {sum(len(l) for l in land)} punten, {len(gemeenten)} gemeenten "
          f"-> {pad.relative_to(BASE)} ({pad.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
