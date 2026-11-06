"""
Levrai Group - Pandenselectiesysteem
Doelgebied-resolutie: vertaal de keuze in config.yaml (stad(en) OF provincie(s))
naar een concrete lijst woonplaatsen die de pijplijn verwerkt.

Provincie -> woonplaatsen gaat via de PDOK Locatieserver. LET OP: het veld
'provincienaam' tokeniseert op het koppelteken, dus `provincienaam:Zuid-Holland`
matcht óók Noord-Holland ("Holland"). Daarom exacte frase met quotes:
`provincienaam:"Zuid-Holland"`. Geverifieerd: ZH 185, NH 238, Utrecht 104.
"""
from __future__ import annotations

import requests

LOCATIESERVER = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"


def slug(naam: str) -> str:
    """Bestandsvriendelijke sleutel: 'Zuid-Holland' -> 'zuidholland'."""
    s = naam.lower()
    for teken in ("'", "-", " ", "(", ")", "."):
        s = s.replace(teken, "")
    return s


def woonplaatsen_in_provincie(provincie: str) -> list[str]:
    """Alle woonplaatsen van een provincie via de PDOK Locatieserver (exacte match).

    De Locatieserver limiteert 'rows' (~100), dus we pagineren met 'start'. Exacte
    frase met quotes voorkomt dat 'Zuid-Holland' ook 'Noord-Holland' matcht.
    """
    sess = requests.Session()
    sess.headers["User-Agent"] = "Levrai-Pandenselectie/1.0"
    plaatsen: set[str] = set()
    start, page, totaal = 0, 100, None
    while True:
        params = {
            "q": "*:*",
            "fq": ["type:woonplaats", f'provincienaam:"{provincie}"'],
            "rows": page, "start": start, "fl": "woonplaatsnaam",
        }
        resp = sess.get(LOCATIESERVER, params=params, timeout=90)
        resp.raise_for_status()
        respdata = resp.json()["response"]
        totaal = respdata["numFound"] if totaal is None else totaal
        docs = respdata["docs"]
        if not docs:
            break
        plaatsen.update(d["woonplaatsnaam"] for d in docs if d.get("woonplaatsnaam"))
        start += len(docs)
        if start >= totaal:
            break
    if not plaatsen:
        raise RuntimeError(f"Geen woonplaatsen gevonden voor provincie {provincie!r} "
                           "— controleer de exacte provincienaam.")
    return sorted(plaatsen)


def resolve(cfg: dict) -> tuple[str, list[str]]:
    """Geef (label, woonplaatsen) op basis van config.doelgebied.

    - steden      : woonplaatsen worden direct gebruikt.
    - provincies  : elke provincie wordt uitgebreid naar zijn woonplaatsen.
    Label is de leesbare naam van het doelgebied (voor titels en bestandsnamen).
    """
    dg = cfg.get("doelgebied") or {}
    steden = [s for s in (dg.get("steden") or []) if s]
    provincies = [p for p in (dg.get("provincies") or []) if p]

    if provincies:
        woonplaatsen: list[str] = list(steden)
        for prov in provincies:
            gevonden = woonplaatsen_in_provincie(prov)
            print(f"  provincie {prov}: {len(gevonden)} woonplaatsen opgehaald")
            woonplaatsen += gevonden
        label = provincies[0] if (len(provincies) == 1 and not steden) else " + ".join(provincies + steden)
        return label, sorted(set(woonplaatsen))

    if steden:
        label = steden[0] if len(steden) == 1 else " + ".join(steden)
        return label, steden

    # Terugval voor oude config met een platte 'gebieden'-lijst.
    oud = cfg.get("gebieden") or ["Delft"]
    return oud[0], list(oud)
