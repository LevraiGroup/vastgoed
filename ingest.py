"""
Levrai Group - Pandenselectiesysteem
Stap 1: ingest van BAG-verblijfsobjecten uit de PDOK BAG WFS.

Waarom WFS en niet de BAG API Individuele Bevragingen:
Kadaster stelt expliciet dat de Individuele Bevragingen API niet bedoeld is voor
bulkbevragingen die in een database worden verwerkt. Deze opdracht is per definitie
bulk (mastervoorraad + maandelijkse cyclus). PDOK WFS/GeoPackage zijn de aangewezen
producten en vereisen geen API-key.

Kritieke les uit de verkenning:
Deze WFS negeert de parameter 'cql_filter' STILZWIJGEND. Een query met cql_filter
levert numberMatched=9.978.773 (heel Nederland) in plaats van een foutmelding.
Alleen OGC Filter XML via de parameter 'filter' wordt daadwerkelijk toegepast.
Daarom valideert dit script de hit-count altijd voor het pagineren begint.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

import snapshots
from gebieden import resolve, slug

BASE = Path(__file__).parent
CACHE = BASE / "data"
CACHE.mkdir(exist_ok=True)

FILTER_TMPL = (
    '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0">'
    "<fes:PropertyIsEqualTo>"
    "<fes:ValueReference>woonplaats</fes:ValueReference>"
    "<fes:Literal>{woonplaats}</fes:Literal>"
    "</fes:PropertyIsEqualTo>"
    "</fes:Filter>"
)

# Woonplaats + postcodeprefix, nodig om onder de paginatielimiet te blijven.
FILTER_PC_TMPL = (
    '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:And>'
    "<fes:PropertyIsEqualTo>"
    "<fes:ValueReference>woonplaats</fes:ValueReference>"
    "<fes:Literal>{woonplaats}</fes:Literal>"
    "</fes:PropertyIsEqualTo>"
    '<fes:PropertyIsLike wildCard="*" singleChar="?" escapeChar="\\">'
    "<fes:ValueReference>postcode</fes:ValueReference>"
    "<fes:Literal>{prefix}*</fes:Literal>"
    "</fes:PropertyIsLike>"
    "</fes:And></fes:Filter>"
)

# Objecten zonder postcode vallen buiten elke prefixpartitie; apart ophalen.
FILTER_GEEN_PC_TMPL = (
    '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:And>'
    "<fes:PropertyIsEqualTo>"
    "<fes:ValueReference>woonplaats</fes:ValueReference>"
    "<fes:Literal>{woonplaats}</fes:Literal>"
    "</fes:PropertyIsEqualTo>"
    # PropertyIsNull, niet Not+PropertyIsLike: die laatste matcht deze objecten niet.
    "<fes:PropertyIsNull>"
    "<fes:ValueReference>postcode</fes:ValueReference>"
    "</fes:PropertyIsNull>"
    "</fes:And></fes:Filter>"
)

# Landelijk totaal aantal VBO's; als een 'gefilterde' query dit teruggeeft,
# is het filter genegeerd en zouden we heel NL binnenhalen.
NL_TOTAAL_INDICATIE = 9_000_000

# PDOK weigert startIndex + count > 51.000 met een HTTP 400.
# Vandaar partitionering per postcodeprefix.
PAGINATIE_PLAFOND = 51_000


def _load_config() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _wfs_get(session: requests.Session, url: str, params: dict, timeout: int = 300):
    """WFS-call met exponentiele backoff op tijdelijke fouten."""
    for poging in range(4):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            # 400 is structureel (bv. paginatieplafond): niet opnieuw proberen.
            if status == 400 or poging == 3:
                raise
            wacht = 2 ** poging
            print(f"  ! {exc.__class__.__name__} ({status}), retry over {wacht}s")
            time.sleep(wacht)
    raise RuntimeError("onbereikbaar")


def hit_count(session: requests.Session, wfs_url: str, laag: str, filter_xml: str) -> int:
    """Vraag alleen het aantal treffers op (resultType=hits)."""
    resp = _wfs_get(
        session,
        wfs_url,
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": laag,
            "resultType": "hits",
            "filter": filter_xml,
        },
        timeout=180,
    )
    marker = 'numberMatched="'
    idx = resp.text.find(marker)
    if idx == -1:
        raise RuntimeError(f"Geen numberMatched in WFS-antwoord: {resp.text[:400]}")
    return int(resp.text[idx + len(marker) :].split('"', 1)[0])


def _pagineer(
    session: requests.Session, cfg: dict, filter_xml: str, total: int, label: str
) -> list[dict]:
    """Haal alle features van een partitie op. Partitie moet onder het plafond passen."""
    wfs_url = cfg["bron"]["wfs_url"]
    laag = cfg["bron"]["laag_vbo"]
    page_size = cfg["bron"]["paginagrootte"]

    features: list[dict] = []
    start = 0
    while start < total:
        resp = _wfs_get(
            session,
            wfs_url,
            {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": laag,
                "outputFormat": "application/json",
                "srsName": "EPSG:28992",
                "count": page_size,
                "startIndex": start,
                "filter": filter_xml,
            },
        )
        batch = resp.json().get("features", [])
        if not batch:
            break

        for feat in batch:
            props = dict(feat.get("properties", {}))
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
                props["_x"], props["_y"] = coords[0], coords[1]
            features.append(props)

        start += len(batch)
        print(f"    {label}: {start:,}/{total:,}", end="\r", flush=True)

    return features


def _partitioneer(
    session: requests.Session, cfg: dict, woonplaats: str, prefix: str, diepte: int = 0
) -> list[dict]:
    """
    Haal een postcodepartitie op; splits recursief zolang deze het paginatieplafond
    overschrijdt. Postcodes zijn 4 cijfers, dus prefixen gaan tot maximaal 4 diep.
    """
    laag = cfg["bron"]["laag_vbo"]
    filter_xml = FILTER_PC_TMPL.format(woonplaats=woonplaats, prefix=prefix)
    aantal = hit_count(session, cfg["bron"]["wfs_url"], laag, filter_xml)

    if aantal == 0:
        return []

    if aantal >= PAGINATIE_PLAFOND:
        if len(prefix) >= 4:
            raise RuntimeError(
                f"Postcode {prefix} heeft {aantal:,} objecten en kan niet verder "
                "worden gesplitst. Gebruik de BAG GeoPackage voor dit gebied."
            )
        print(f"  {'  ' * diepte}postcode {prefix}* = {aantal:,} -> splitsen")
        uit: list[dict] = []
        for cijfer in "0123456789":
            uit += _partitioneer(session, cfg, woonplaats, prefix + cijfer, diepte + 1)
        return uit

    print(f"  {'  ' * diepte}postcode {prefix}* = {aantal:,}")
    return _pagineer(session, cfg, filter_xml, aantal, f"{prefix}*")


def fetch_woonplaats(woonplaats: str, cfg: dict) -> list[dict]:
    """
    Haal alle verblijfsobjecten van een woonplaats op.

    PDOK weigert startIndex+count > 51.000, dus we partitioneren per postcodeprefix
    in plaats van diep te pagineren over de hele woonplaats.
    """
    wfs_url = cfg["bron"]["wfs_url"]
    laag = cfg["bron"]["laag_vbo"]

    session = requests.Session()
    session.headers["User-Agent"] = "Levrai-Pandenselectie/1.0"

    verwacht = hit_count(session, wfs_url, laag, FILTER_TMPL.format(woonplaats=woonplaats))
    print(f"[{woonplaats}] WFS meldt {verwacht:,} verblijfsobjecten")

    # Veiligheidscontrole: filter genegeerd -> heel NL.
    if verwacht > NL_TOTAAL_INDICATIE:
        raise RuntimeError(
            f"Filter lijkt genegeerd ({verwacht:,} treffers = heel NL). Ingest afgebroken."
        )

    features: list[dict] = []
    for cijfer in "0123456789":
        features += _partitioneer(session, cfg, woonplaats, cijfer)

    # Objecten zonder postcode vallen buiten iedere prefixpartitie.
    geen_pc_filter = FILTER_GEEN_PC_TMPL.format(woonplaats=woonplaats)
    try:
        n_geen_pc = hit_count(session, wfs_url, laag, geen_pc_filter)
        if n_geen_pc:
            print(f"  zonder postcode = {n_geen_pc:,}")
            features += _pagineer(session, cfg, geen_pc_filter, n_geen_pc, "geen-pc")
    except requests.RequestException as exc:
        print(f"  ! partitie zonder postcode overgeslagen ({exc.__class__.__name__})")

    # Deduplicatie: partitiegrenzen mogen nooit dubbele VBO's opleveren.
    uniek: dict[str, dict] = {}
    for rij in features:
        vbo_id = rij.get("identificatie")
        if vbo_id:
            uniek[vbo_id] = rij
    features = list(uniek.values())

    dekking = len(features) / verwacht * 100 if verwacht else 0.0
    print(f"\n[{woonplaats}] {len(features):,} unieke VBO's ({dekking:.1f}% van {verwacht:,})")
    if dekking < 95.0:
        print(f"  ! LET OP: dekking onder 95%, controleer partitionering")

    return features


def main() -> int:
    cfg = _load_config()
    if sys.argv[1:]:
        label, woonplaatsen = sys.argv[1], sys.argv[1:]
    else:
        label, woonplaatsen = resolve(cfg)
    print(f"Doelgebied: {label} ({len(woonplaatsen)} woonplaats(en))")

    for woonplaats in woonplaatsen:
        opgehaald_vanaf = datetime.now().astimezone()
        rows = fetch_woonplaats(woonplaats, cfg)
        # Elke ingest krijgt een eigen, gedateerde snapshot; eerdere bestanden
        # (ook het oude vbo_<plaats>.json) blijven onaangeroerd. Zie snapshots.py.
        snap = snapshots.schrijf(
            woonplaats, slug(woonplaats), rows, CACHE, opgehaald_vanaf,
            {"bron": cfg["bron"]["wfs_url"], "laag": cfg["bron"]["laag_vbo"]},
        )
        mb = snap.pad.stat().st_size / 1e6
        print(f"[{woonplaats}] opgeslagen -> {snap.omschrijving()} ({mb:.1f} MB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
