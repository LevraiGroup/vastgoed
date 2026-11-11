"""
Doelgebied Nederland (VA-37): mastervoorraad en maandelijkse werklijst uit de landelijke
snapshot (VA-34), pand voor pand (VA-36), met de 25 grootste gemeenten van CBS (VA-65).

De werklijst telt drempels.werklijst_max panden (500). Een vast aandeel
(drempels.werklijst_aandeel_overig) komt van buiten de grootste gemeenten (drempels.aantal_grote_gemeenten),
de rest uit die 25; elk deel neemt de hoogste scores van heel Nederland, met de maandloting
(VA-32) bij gelijke score. Komt een deel tekort, dan vult het andere deel aan.

Het geheugen houdt nooit alle panden vast: tellingen, de 20 beste voor het proefresultaat,
per deel de beste werklijst_max panden, en de mastervoorraad in een tijdelijke SQLite op D:.
"""
from __future__ import annotations

import csv
import heapq
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path

import cbs_gemeenten
import selectie
import snapshots
from selectie import mastervolgorde, nl_tal, werklijstvolgorde

NAAM = "Nederland"
SLUG = "nederland"
IN_GROOT = "grote_gemeente"  # kolomnaam van Lumi (VA-37 crit. 5): ja/nee, het aantal staat in config.yaml


class NederlandFout(RuntimeError):
    """De landelijke run kan niet verder; er is niets geschreven."""


def is_nederland(cfg: dict) -> bool:
    """config.yaml: doelgebied.nederland: true kiest heel Nederland (VA-37)."""
    return bool((cfg.get("doelgebied") or {}).get("nederland"))


def aantallen(cfg: dict) -> tuple[int, int, int]:
    """(aantal grote gemeenten, plaatsen voor de 25, plaatsen voor de rest)."""
    d = cfg["drempels"]
    n_groot = d["aantal_grote_gemeenten"]        # beide verplicht in config.yaml (VA-37 crit. 6);
    aandeel = d["werklijst_aandeel_overig"]      # controleer_drempels() meldt een ontbrekende sleutel
    maximum = d["werklijst_max"]
    overig = round(aandeel * maximum)
    return n_groot, maximum - overig, overig


def verdeel(groot: list[dict], overig: list[dict], plaatsen_groot: int, plaatsen_overig: int,
            maand: str, n_groot: int) -> tuple[list[dict], list[str]]:
    """
    De werklijst uit twee gerangschikte delen (VA-37 crit. 4). Elk deel krijgt zijn plaatsen;
    komt een deel tekort, dan vult het andere deel aan met zijn volgende beste. Geeft de lijst
    (op leadscore en maandloting) en Nederlandse meldingen over een tekort.
    """
    sleutel = werklijstvolgorde(maand)
    groot, overig = sorted(groot, key=sleutel), sorted(overig, key=sleutel)
    uit_groot, uit_overig = min(plaatsen_groot, len(groot)), min(plaatsen_overig, len(overig))
    meldingen = []
    if uit_groot < plaatsen_groot:
        extra = min(plaatsen_groot - uit_groot, len(overig) - uit_overig)
        meldingen.append(f"De {n_groot} grootste gemeenten hebben {nl_tal(len(groot))} geschikte panden voor "
                         f"{nl_tal(plaatsen_groot)} plaatsen; de rest van Nederland vult {nl_tal(extra)} aan.")
        uit_overig += extra
    if uit_overig < plaatsen_overig:
        extra = min(plaatsen_overig - uit_overig, len(groot) - uit_groot)
        meldingen.append(f"De rest van Nederland heeft {nl_tal(len(overig))} geschikte panden voor "
                         f"{nl_tal(plaatsen_overig)} plaatsen; de {n_groot} grootste gemeenten vullen {nl_tal(extra)} aan.")
        uit_groot += extra
    return sorted(groot[:uit_groot] + overig[:uit_overig], key=sleutel), meldingen


class Beste:
    """De n beste panden volgens een sorteersleutel (laag = beter), zonder alles vast te houden."""

    def __init__(self, n: int, sleutel):
        self.n, self.sleutel, self.heap, self.teller = n, sleutel, [], 0

    def voeg_toe(self, pand: dict) -> None:
        if self.n <= 0:
            return
        k = self.sleutel(pand)
        self.teller += 1
        item = (tuple(_omgekeerd(x) for x in k), self.teller, pand)  # max-heap op de sleutel
        if len(self.heap) < self.n:
            heapq.heappush(self.heap, item)
        elif item[0] > self.heap[0][0]:
            heapq.heapreplace(self.heap, item)

    def lijst(self) -> list[dict]:
        return sorted((p for _, _, p in self.heap), key=self.sleutel)


class _Omgekeerd:
    """Draait de volgorde van een waarde om, zodat heapq (min-heap) de slechtste bovenaan houdt."""
    __slots__ = ("w",)

    def __init__(self, w):
        self.w = w

    def __lt__(self, ander):
        return self.w > ander.w

    def __gt__(self, ander):
        return self.w < ander.w

    def __eq__(self, ander):
        return self.w == ander.w


def _omgekeerd(w):
    return _Omgekeerd(w)


def nieuwste_snapshot(cfg: dict, keuze: str | None) -> snapshots.Snapshot:
    snap = snapshots.kies(NAAM, SLUG, selectie.DATA, cfg, keuze, landelijk=True)
    if not snap.landelijk:
        raise NederlandFout(f"{snap.pad.name} is geen landelijke snapshot (verwacht bag_nl_<datum>.sqlite).")
    return snap


def draai(cfg: dict, keuze: str | None, kolommen: list[str], rij, uit: Path, data: Path) -> int:
    """De landelijke run. 'kolommen' en 'rij' komen uit run_proef.py, zodat de CSV's gelijk lopen."""
    snap = nieuwste_snapshot(cfg, keuze)
    print(f"Snapshot {NAAM}: {snap.omschrijving()}")
    gemeenten = cbs_gemeenten.lees()
    naam_van = {g["gemeentecode"]: g["gemeente"] for g in gemeenten}
    n_groot, plaatsen_groot, plaatsen_overig = aantallen(cfg)
    groot = {g["gemeentecode"] for g in gemeenten if g["rang"] <= n_groot}
    maand = snap.ophaaldatum[:7]
    score_min = cfg["drempels"]["score_min_voor_werklijst"]
    bron = f"PDOK BAG GeoPackage ({snap.pad.name})"

    def rij_nl(p: dict) -> dict:
        r = rij(p)
        r.update({"gemeentecode": p.get("gemeentecode", ""), "gemeente": p.get("gemeente", ""),
                  IN_GROOT: p[IN_GROOT]})
        return r

    tel = Counter()
    per_cat = Counter()
    codes_gezien: set[str] = set()
    proef = Beste(20, mastervolgorde)
    beste_groot = Beste(plaatsen_groot + plaatsen_overig, werklijstvolgorde(maand))
    beste_overig = Beste(plaatsen_groot + plaatsen_overig, werklijstvolgorde(maand))
    tmp = Path(os.environ.get(snapshots.VAR_TMP) or snap.pad.parent)
    with tempfile.TemporaryDirectory(dir=tmp) as werkmap, \
            closing(sqlite3.connect(Path(werkmap) / "master.sqlite")) as master:
        master.execute("CREATE TABLE m (score INTEGER, id TEXT, rij TEXT)")
        for p in selectie.stroom_panden([snap], cfg, NAAM, kort="NL"):
            code = p.get("gemeentecode") or ""
            codes_gezien.add(code)
            p["lead_id"] = f"LEV-NL-{p['bag_pand_id']}"  # VA-37 crit. 7: uniek in heel Nederland
            p["bron"] = bron
            p["gemeente"] = naam_van.get(code, "")
            p[IN_GROOT] = "ja" if code in groot else "nee"
            tel["panden"] += 1
            tel["vbo"] += p["aantal_vbo"]
            if p["uitgesloten"]:
                tel["uitgesloten"] += 1
                continue
            for c in p["categorieen"]:
                per_cat[c] += 1
            if not p["categorieen"]:
                continue
            tel["a_e"] += 1
            master.execute("INSERT INTO m VALUES (?, ?, ?)",
                           (p["leadscore"], p["bag_pand_id"], json.dumps(rij_nl(p), ensure_ascii=False)))
            proef.voeg_toe(p)
            if p["leadscore"] >= score_min:
                if code in groot:
                    tel["geschikt_groot"] += 1
                    beste_groot.voeg_toe(p)
                else:
                    tel["geschikt_overig"] += 1
                    beste_overig.voeg_toe(p)

        ontbreekt = sorted(groot - codes_gezien)
        if ontbreekt:  # VA-37 crit. 3: nooit stil een kortere lijst
            namen = ", ".join(f"{c} ({naam_van.get(c, '?')})" for c in ontbreekt)
            raise NederlandFout(f"Deze grote gemeenten ontbreken in {snap.pad.name}: {namen}. "
                                "Er is niets geschreven.")

        lijst, meldingen = verdeel(beste_groot.lijst(), beste_overig.lijst(), plaatsen_groot,
                                   plaatsen_overig, maand, n_groot)
        velden = kolommen + ["gemeentecode", "gemeente", IN_GROOT, "bag_viewer_url"]
        master_csv = uit / f"mastervoorraad_{SLUG}.csv"
        with open(master_csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=velden, delimiter=";")
            w.writeheader()
            for (tekst,) in master.execute("SELECT rij FROM m ORDER BY score DESC, id"):
                w.writerow(json.loads(tekst))
    proef_csv = uit / f"proefresultaat_20_{SLUG}.csv"
    werklijst_csv = uit / f"werklijst_{SLUG}_{maand}.csv"
    for pad, panden in ((proef_csv, proef.lijst()), (werklijst_csv, lijst)):
        with open(pad, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=velden, delimiter=";")
            w.writeheader()
            for p in panden:
                w.writerow(rij_nl(p))

    uit_groot = sum(1 for p in lijst if p[IN_GROOT] == "ja")
    totalen = {"vbo": tel["vbo"], "panden": tel["panden"], "uitgesloten": tel["uitgesloten"],
               "a_e": tel["a_e"], "categorieen": {c: per_cat[c] for c in "ABCDE"},
               "geschikt": tel["geschikt_groot"] + tel["geschikt_overig"],
               "geschikt_25": tel["geschikt_groot"], "geschikt_overig": tel["geschikt_overig"],
               "werklijst": len(lijst), "werklijst_25": uit_groot, "werklijst_overig": len(lijst) - uit_groot,
               "drempel": score_min, "maand": maand, "aantal_grote_gemeenten": n_groot}
    with open(data / f"panden_{SLUG}.json", "w", encoding="utf-8") as fh:
        json.dump({"gebied": NAAM, "totalen": totalen, "werklijst": lijst, "proef": proef.lijst()},
                  fh, ensure_ascii=False)
    with open(data / f"panden_{SLUG}.bron.json", "w", encoding="utf-8") as fh:
        json.dump([{"woonplaats": NAAM, "bestand": snap.pad.name, "ophaaldatum": snap.ophaaldatum}],
                  fh, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 78}\nTECHNISCHE VOORRAAD - NEDERLAND\n{'=' * 78}")
    print(f"Verblijfsobjecten ingelezen : {nl_tal(tel['vbo'])}")
    print(f"Unieke BAG-panden           : {nl_tal(tel['panden'])}")
    print(f"Uitgesloten                 : {nl_tal(tel['uitgesloten'])}")
    print(f"Binnen categorie A-E        : {nl_tal(tel['a_e'])}")
    for c in "ABCDE":
        print(f"  {c} {nl_tal(per_cat[c]):>10}")
    print(f"Geschikt (score >= {score_min})     : {nl_tal(totalen['geschikt'])} "
          f"({n_groot} grootste: {nl_tal(tel['geschikt_groot'])}, elders: {nl_tal(tel['geschikt_overig'])})")
    print(f"\nWerklijst       -> {werklijst_csv.name}  ({nl_tal(len(lijst))} panden: "
          f"{nl_tal(uit_groot)} uit de {n_groot} grootste gemeenten, {nl_tal(len(lijst) - uit_groot)} elders)")
    print(f"Mastervoorraad  -> {master_csv.name}  ({nl_tal(tel['a_e'])} panden, "
          f"{nl_tal(master_csv.stat().st_size)} bytes)")
    print(f"Proefresultaat  -> {proef_csv.name}  (20 panden)")
    for m in meldingen:
        print(f"LET OP: {m}", file=sys.stderr)
    waarschuwing = selectie.werklijst_waarschuwing(totalen["geschikt"], cfg)
    if waarschuwing:
        print(f"\n{waarschuwing}", file=sys.stderr)
    return 0
