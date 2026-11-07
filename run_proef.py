"""
Levrai Group - Pandenselectiesysteem
Stap 3: proefresultaat van 20 panden + totale technische voorraad per categorie
+ de maandelijkse werklijst (hoogstens drempels.werklijst_max panden).

Beantwoordt de controlevraag uit de briefing:
"Kun je eerst een proefresultaat van twintig panden laten zien, inclusief
BAG-koppelingen en selectiereden, voordat je het volledige systeem bouwt?"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from gebieden import resolve, slug
from selectie import (
    DATA, kies_snapshots, load_config, mastervolgorde, verwerk, werklijst,
    werklijst_maand, werklijst_waarschuwing,
)
from snapshots import SnapshotFout

BASE = Path(__file__).parent
UIT = BASE / "output"
UIT.mkdir(exist_ok=True)

BAG_VIEWER = "https://bagviewer.kadaster.nl/lvbag/bag-viewer/index.html#?searchQuery="


def main() -> int:
    parser = argparse.ArgumentParser(description="Proefresultaat en mastervoorraad.")
    parser.add_argument(
        "--snapshot", default=None,
        help="welke ingest: ophaaldatum JJJJ-MM-DD of bestandsnaam (standaard de nieuwste)",
    )
    args = parser.parse_args()
    cfg = load_config()
    label, woonplaatsen = resolve(cfg)
    sl = slug(label)
    try:
        gekozen = kies_snapshots(woonplaatsen, cfg, args.snapshot)
        # Stopt ook als een snapshot geen ophaaldatum heeft (VA-4): de datapeildatum
        # komt uit de snapshot, nooit uit de datum van vandaag.
        panden = verwerk(woonplaatsen, cfg, label, gekozen=gekozen)
    except SnapshotFout as fout:
        print(f"FOUT: {fout}", file=sys.stderr)
        return 1

    actief = [p for p in panden if not p["uitgesloten"]]
    in_cat = [p for p in actief if p["categorieen"]]

    print(f"\n{'=' * 78}")
    print(f"TECHNISCHE VOORRAAD - {label.upper()}")
    print(f"{'=' * 78}")
    print(f"Verblijfsobjecten ingelezen : {sum(p['aantal_vbo'] for p in panden):,}")
    print(f"Unieke BAG-panden           : {len(panden):,}")
    print(f"Uitgesloten                 : {len(panden) - len(actief):,}")
    print(f"Binnen categorie A-E        : {len(in_cat):,}")

    print(f"\n{'Categorie':<12} {'Aantal':>8}   Omschrijving")
    print("-" * 78)
    labels = {
        "A": "Winkel + wonen",
        "B": "Bedrijf/kantoor + wonen",
        "C": "Klein wooncomplex (3-15 woningen)",
        "D": "Groot oud pand (<1940, 1-2 eenheden)",
        "E": "Afwijkende combinatie",
    }
    for cat, label in labels.items():
        n = sum(1 for p in actief if cat in p["categorieen"])
        print(f"{cat:<12} {n:>8,}   {label}")

    print("\nUitsluitingen naar reden:")
    redenen: dict[str, int] = {}
    for p in panden:
        for r in p["uitsluitredenen"]:
            sleutel = r.split(":")[0].split("(")[0].strip()
            sleutel = " ".join(sleutel.split()[:4])
            redenen[sleutel] = redenen.get(sleutel, 0) + 1
    for r, n in sorted(redenen.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>7,}  {r}")

    # Proefresultaat: 20 hoogst scorende panden binnen een categorie.
    top = sorted(in_cat, key=mastervolgorde)[:20]

    print(f"\n{'=' * 78}")
    print("PROEFRESULTAAT - 20 PANDEN")
    print(f"{'=' * 78}")
    for i, p in enumerate(top, 1):
        print(f"\n{i:>2}. {p['hoofdadres']}   [score {p['leadscore']}, cat {'+'.join(p['categorieen'])}]")
        print(f"    BAG-pand-ID : {p['bag_pand_id']}   bouwjaar {p['bouwjaar']}   {p['pandstatus']}")
        print(f"    Omvang      : {p['aantal_vbo']} vbo, {p['aantal_adressen']} adressen, {p['totale_oppervlakte']:,.0f} m2")
        functies = ", ".join(
            f"{g}: {n}x {p['opp_per_functie'].get(g, 0):,.0f} m2"
            for g, n in sorted(p["aantal_per_functie"].items())
        )
        print(f"    Functies    : {functies}")
        print(f"    Selectiereden: {p['selectiereden']}")
        print(f"    BAG-viewer  : {BAG_VIEWER}{p['bag_pand_id']}")

    # CSV-export van het proefresultaat.
    kolommen = [
        "lead_id", "bag_pand_id", "hoofdadres", "gekoppelde_adressen", "woonplaats",
        "postcode", "bouwjaar", "pandstatus", "vbo_ids", "aantal_vbo", "aantal_adressen",
        "gebruiksdoelen", "opp_per_functie", "totale_oppervlakte", "pandcategorie",
        "categorieen", "leadscore", "selectiereden", "visuele_controle", "beoordeling",
        "eerder_geselecteerd", "laatst_beoordeeld", "bron", "datapeildatum",
    ]

    def _rij(p: dict) -> dict:
        r = {}
        for k in kolommen:
            v = p.get(k, "")
            if isinstance(v, list):
                v = " | ".join(str(x) for x in v)
            elif isinstance(v, dict):
                v = "; ".join(f"{a}={b}" for a, b in sorted(v.items()))
            r[k] = v
        r["bag_viewer_url"] = f"{BAG_VIEWER}{p['bag_pand_id']}"
        return r

    proef_csv = UIT / f"proefresultaat_20_{sl}.csv"
    with open(proef_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=kolommen + ["bag_viewer_url"], delimiter=";")
        w.writeheader()
        for p in top:
            w.writerow(_rij(p))

    master_csv = UIT / f"mastervoorraad_{sl}.csv"
    with open(master_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=kolommen + ["bag_viewer_url"], delimiter=";")
        w.writeheader()
        for p in sorted(in_cat, key=mastervolgorde):
            w.writerow(_rij(p))

    # Maandelijkse werklijst (VA-5): de hoogst scorende panden boven de werklijstdrempel,
    # hoogstens drempels.werklijst_max. De maand in de naam is die van de snapshot; bij
    # gelijke score bepaalt die maand ook de volgorde (VA-32).
    maand = werklijst_maand(gekozen)
    lijst, n_geschikt = werklijst(panden, cfg, maand)
    werklijst_csv = UIT / f"werklijst_{sl}_{maand}.csv"
    with open(werklijst_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=kolommen + ["bag_viewer_url"], delimiter=";")
        w.writeheader()
        for p in lijst:
            w.writerow(_rij(p))

    with open(DATA / f"panden_{sl}.json", "w", encoding="utf-8") as fh:
        json.dump(panden, fh, ensure_ascii=False)
    # Welke snapshots dit resultaat voeden, zodat het dashboard het kan tonen.
    with open(DATA / f"panden_{sl}.bron.json", "w", encoding="utf-8") as fh:
        json.dump(
            [
                {"woonplaats": s.woonplaats, "bestand": s.pad.name, "ophaaldatum": s.ophaaldatum}
                for s in gekozen
            ],
            fh, ensure_ascii=False, indent=2,
        )

    print(f"\n{'=' * 78}")
    print(f"Proefresultaat  -> {proef_csv.relative_to(BASE)}  (20 panden)")
    print(f"Mastervoorraad  -> {master_csv.relative_to(BASE)}  ({len(in_cat):,} panden)")
    print(
        f"Werklijst       -> {werklijst_csv.relative_to(BASE)}  ({len(lijst):,} van "
        f"{n_geschikt:,} panden met leadscore >= {cfg['drempels']['score_min_voor_werklijst']})"
    )
    for s in gekozen:
        print(f"Snapshot        -> {s.omschrijving()}")
    waarschuwing = werklijst_waarschuwing(n_geschikt, cfg)
    if waarschuwing:
        print(f"\n{waarschuwing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
