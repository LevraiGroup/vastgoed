"""
Levrai Group - Pandenselectiesysteem
Stap 2b (optioneel): verrijk panden met externe bronnen.

Draai NA ingest en VOOR run_proef.py, en alleen als je minstens één bron in
config.yaml op 'actief: true' hebt gezet (met de bijbehorende sleutel). Het
resultaat komt in data/verrijking_<woonplaats>.json; run_proef.py leest dat
automatisch in en activeert de bijbehorende scoresignalen.

    python verrijk.py            # alle gebieden uit config
    python verrijk.py Delft      # specifiek gebied

Bronnen die uit staan of geen sleutel hebben, worden netjes overgeslagen — de
scoring blijft dan werken met de gratis signalen (BAG-status telt altijd mee).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bronnen
from gebieden import resolve, slug
from selectie import DATA, aggregeer, categoriseer, load_config, scoor, uitsluiten

BASE = Path(__file__).parent


def _kandidaten(woonplaatsen: list[str], cfg: dict) -> list[dict]:
    rows: list[dict] = []
    for w in woonplaatsen:
        rows += json.load(open(DATA / f"vbo_{slug(w)}.json", encoding="utf-8"))
    panden = aggregeer(rows)
    # Basisscore zonder verrijking, alleen om te bepalen wie kandidaat is.
    kand = []
    for p in panden:
        if uitsluiten(p, cfg):
            continue
        p["categorieen"] = categoriseer(p, cfg)
        if not p["categorieen"]:
            continue
        p["leadscore"], _ = scoor(p, p["categorieen"], cfg)
        kand.append(p)
    return kand


def verrijk_gebied(label: str, woonplaatsen: list[str], cfg: dict) -> None:
    kand = _kandidaten(woonplaatsen, cfg)
    print(f"[{label}] {len(kand):,} kandidaten voor verrijking")

    samen: dict[str, dict] = {}
    for naam, module in bronnen.MODULES.items():
        ok, uitleg = module.beschikbaar(cfg)
        if not ok:
            print(f"  - {naam}: overgeslagen ({uitleg})")
            continue
        print(f"  + {naam}: {uitleg}")
        resultaat = module.verrijk(kand, cfg)
        for pand_id, velden in resultaat.items():
            samen.setdefault(pand_id, {}).update(velden)

    uit = DATA / f"verrijking_{slug(label)}.json"
    with open(uit, "w", encoding="utf-8") as fh:
        json.dump(samen, fh, ensure_ascii=False)
    print(f"[{label}] verrijking van {len(samen):,} panden -> {uit.name}")


def main() -> int:
    cfg = load_config()
    label, woonplaatsen = resolve(cfg)
    verrijk_gebied(label, woonplaatsen, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
