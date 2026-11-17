"""
Nachtelijke controle van de werklijst tegen de PDOK BAG WFS (VA-75).

Leest de nieuwste output/werklijst_nederland_<JJJJ-MM>.csv en vraagt voor elk pand bij de PDOK BAG
WFS (config.yaml bron.wfs_url, zonder sleutel, nooit de BAG API Individuele Bevragingen) de huidige
pandstatus en de verblijfsobjecten met hun status op. Dat gebeurt met één verzoek per pand, met
twee OGC Filter XML-queries (nooit cql_filter: die negeert de WFS stilzwijgend), één voor bag:pand
en één voor bag:verblijfsobject. Alleen als dat antwoord is afgekapt komen er pagina's bij.

Wat als wijziging telt (Nova, VA-75): de pandstatus; het pand niet meer gevonden; een
verblijfsobject erbij of weg; de status van een verblijfsobject. Gebruiksdoel en oppervlakte niet.

Vergeleken wordt met de waarden waaruit de werklijst is gebouwd: pandstatus en vbo_ids uit de CSV,
en de status per verblijfsobject uit de landelijke snapshot die in de kolom 'bron' staat
(bag_nl_<datum>.sqlite). Die statussen worden één keer uit de snapshot gelezen en in de datamap
bewaard (nachtcontrole.basis_map), zodat volgende nachten de snapshot niet meer nodig hebben. Is er
geen snapshot en geen bewaarde basis, dan worden de statussen van verblijfsobjecten niet vergeleken
en zegt de uitkomst dat.

Per werklijstmaand schrijft hij één bestand (nachtcontrole.uitvoer_map, standaard output/controle):
wijzigingen_nederland_<JJJJ-MM>.csv, één rij per verschil, met een vaste soort per rij. Een verschil
dat een eerdere nacht al gezien is, houdt zijn datum eerst_gezien; een verschil dat weg is, verdwijnt
uit het bestand. Een pand waarvan het verzoek mislukt (na de herhaling met wachttijd van ingest.py)
krijgt die nacht een rij 'niet_gecontroleerd' en houdt zijn eerder geziene verschillen. Lukt geen
enkel pand, dan schrijft hij niets en eindigt met exitcode 1.

Hij wijzigt nooit een score, de werklijst, de mastervoorraad of panden_*.json.

    python werklijst_controle.py
    python werklijst_controle.py --werklijst <csv> --uitvoer <map> --resultaat <json> --basis <map>

Exitcode 0: gecontroleerd en geschreven (ook als enkele panden niet gecontroleerd konden worden).
Anders 1.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import requests

import ingest
import ingest_gpkg
from selectie import load_config, nl_tal

BASE = Path(__file__).parent
GEBIED = "nederland"
WERKLIJST_RE = re.compile(rf"werklijst_{GEBIED}_(\d{{4}}-\d{{2}})\.csv")
SNAPSHOT_RE = re.compile(r"\((bag_nl_\d{4}-\d{2}-\d{2}(?:_\d+)?\.sqlite)\)")
SLEUTELS = ("uitvoer_map", "resultaat", "basis_map", "snapshot_map", "stop_na_mislukt", "timeout_s")

WFS_NS = "{http://www.opengis.net/wfs/2.0}"
BAG_NS = "{http://bag.geonovum.nl}"
LAAG_PAND = "bag:pand"
LAAG_VBO = "bag:verblijfsobject"

# De vaste soorten (criterium 3): een lezer herkent ze zonder de vrije tekst te lezen.
PAND_GESLOOPT = "pand_gesloopt"
PAND_BUITEN_GEBRUIK = "pand_buiten_gebruik"
PAND_NIET_GEVONDEN = "pand_niet_gevonden"
PANDSTATUS = "pandstatus"
VBO_ERBIJ = "vbo_erbij"
VBO_WEG = "vbo_weg"
VBO_STATUS = "vbo_status"
NIET_GECONTROLEERD = "niet_gecontroleerd"
SOORTEN = (PAND_GESLOOPT, PAND_BUITEN_GEBRUIK, PAND_NIET_GEVONDEN, PANDSTATUS, VBO_ERBIJ, VBO_WEG, VBO_STATUS)

KOLOMMEN = ("bag_pand_id", "soort", "wijziging", "vbo_id", "waarde_werklijst", "waarde_nu", "eerst_gezien")

STATUS_GESLOOPT = "Pand gesloopt"
STATUS_BUITEN_GEBRUIK = "Pand buiten gebruik"
NIET_IN_WERKLIJST = "niet in de werklijst"
AANWEZIG = "aanwezig"
NIET_IN_BAG = "niet in de BAG"


class TelSessie(requests.Session):
    """Een requests-sessie die elk verzoek telt, herhalingen meegerekend (criterium 6)."""

    def __init__(self):
        super().__init__()
        self.verzoeken = 0

    def request(self, *args, **kwargs):
        self.verzoeken += 1
        return super().request(*args, **kwargs)


class ControleFout(RuntimeError):
    """De controle kan niet beginnen of leverde niets op; er is niets geschreven."""


class PandFout(RuntimeError):
    """Eén pand kon niet worden gecontroleerd."""


@dataclass
class Pand:
    bag_pand_id: str
    pandstatus: str
    vbo_ids: list[str]


@dataclass
class Nu:
    """Wat de WFS vandaag over één pand zegt."""
    gevonden: bool
    status: str = ""
    vbo: dict[str, str] = field(default_factory=dict)   # vbo-identificatie -> status


@dataclass(frozen=True)
class Rij:
    bag_pand_id: str
    soort: str
    wijziging: str
    vbo_id: str
    waarde_werklijst: str
    waarde_nu: str
    eerst_gezien: str

    @property
    def sleutel(self) -> tuple[str, str, str, str]:
        """Hetzelfde verschil = zelfde pand, soort, verblijfsobject en waarde nu."""
        return (self.bag_pand_id, self.soort, self.vbo_id, self.waarde_nu)


# ------------------------------------------------------------------------------ instellingen
def instellingen(cfg: dict) -> dict:
    """config.yaml nachtcontrole.* plus bron.wfs_url en bron.paginagrootte, zonder stille standaarden."""
    blok = cfg.get("nachtcontrole") if isinstance(cfg, dict) else None
    bron = cfg.get("bron") if isinstance(cfg, dict) else None
    ontbreekt = [f"nachtcontrole.{k}" for k in SLEUTELS if not isinstance(blok, dict) or blok.get(k) in (None, "")]
    ontbreekt += [f"bron.{k}" for k in ("wfs_url", "paginagrootte") if not isinstance(bron, dict) or not bron.get(k)]
    if ontbreekt:
        raise ControleFout(f"config.yaml mist {', '.join(ontbreekt)}.")
    ins = {k: blok[k] for k in SLEUTELS}
    ins["wfs_url"], ins["paginagrootte"] = bron["wfs_url"], int(bron["paginagrootte"])
    ins["werklijst_map"] = BASE / "output"
    for sleutel in ("uitvoer_map", "resultaat", "basis_map", "snapshot_map"):
        pad = Path(ins[sleutel])
        ins[sleutel] = pad if pad.is_absolute() else BASE / pad
    for sleutel in ("stop_na_mislukt", "timeout_s"):
        waarde = ins[sleutel]
        if isinstance(waarde, bool) or not isinstance(waarde, (int, float)) or waarde != waarde or waarde < 1:
            raise ControleFout(f"config.yaml nachtcontrole.{sleutel} moet een getal van minstens 1 zijn, "
                               f"niet {waarde!r}.")
    return ins


def vandaag_nl(moment: datetime | None = None) -> str:
    """De datum in Nederlandse tijd: de nacht waarin iets gezien is."""
    return ingest_gpkg.naar_amsterdam(moment or datetime.now(timezone.utc)).date().isoformat()


# ------------------------------------------------------------------------------ werklijst
def nieuwste_werklijst(map_: Path) -> tuple[Path, str]:
    """(pad, JJJJ-MM) van de nieuwste werklijst_nederland_<JJJJ-MM>.csv."""
    gevonden = sorted((m.group(1), p) for p in map_.glob(f"werklijst_{GEBIED}_*.csv")
                      if (m := WERKLIJST_RE.fullmatch(p.name)))
    if not gevonden:
        raise ControleFout(f"Geen werklijst_{GEBIED}_<JJJJ-MM>.csv in {map_}.")
    maand, pad = gevonden[-1]
    return pad, maand


def maand_van(pad: Path) -> str:
    m = WERKLIJST_RE.fullmatch(pad.name)
    if not m:
        raise ControleFout(f"{pad.name} heet niet werklijst_{GEBIED}_<JJJJ-MM>.csv.")
    return m.group(1)


def lees_werklijst(pad: Path) -> tuple[list[Pand], str | None]:
    """(panden, naam van de snapshot uit de kolom bron). Alleen lezen."""
    try:
        with open(pad, encoding="utf-8-sig", newline="") as fh:
            rijen = list(csv.DictReader(fh, delimiter=";"))
    except OSError as fout:
        raise ControleFout(f"De werklijst {pad} is niet te lezen: {fout}") from None
    if not rijen or not {"bag_pand_id", "pandstatus", "vbo_ids"} <= rijen[0].keys():
        raise ControleFout(f"{pad.name} heeft geen rijen met bag_pand_id, pandstatus en vbo_ids.")
    panden = [Pand(r["bag_pand_id"].strip(), (r["pandstatus"] or "").strip(),
                   [v.strip() for v in (r["vbo_ids"] or "").split("|") if v.strip()]) for r in rijen]
    namen = {m.group(1) for r in rijen if (m := SNAPSHOT_RE.search(r.get("bron") or ""))}
    return panden, (sorted(namen)[-1] if namen else None)


# ------------------------------------------------------------------------------ basis van de VBO-statussen
def basis_pad(basis_map: Path, maand: str) -> Path:
    return basis_map / f"basis_{GEBIED}_{maand}.json"


def lees_basis_uit_snapshot(snapshot: Path, panden: list[Pand]) -> dict[str, str]:
    """vbo-identificatie -> status in de snapshot, voor de verblijfsobjecten van de werklijst."""
    ids = sorted({v for p in panden for v in p.vbo_ids})
    try:
        with closing(sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            rij = conn.execute("SELECT waarde FROM meta WHERE sleutel = 'kolommen'").fetchone()
            kolommen = json.loads(rij[0]) if rij else {}
            id_kolom = kolommen.get("identificatie", "identificatie")
            status_kolom = kolommen.get("status", "status")
            conn.execute("CREATE TEMP TABLE gezocht (id TEXT PRIMARY KEY)")
            conn.executemany("INSERT INTO gezocht VALUES (?)", ((i,) for i in ids))
            uit = dict(conn.execute(
                f'SELECT v."{id_kolom}", v."{status_kolom}" FROM vbo v JOIN gezocht g ON g.id = v."{id_kolom}"'))
    except (sqlite3.Error, ValueError) as fout:
        raise ControleFout(f"De snapshot {snapshot.name} is niet te lezen: {fout}") from None
    return {k: (v or "") for k, v in uit.items()}


def basis_statussen(ins: dict, maand: str, snapshot_naam: str | None, panden: list[Pand]
                    ) -> tuple[dict[str, str] | None, str, bool]:
    """
    (vbo -> status of None, waar de basis vandaan komt, nieuw_te_bewaren).
    Eerst de bewaarde basis in de datamap, anders de snapshot uit de kolom bron, anders None.
    """
    bewaard = basis_pad(ins["basis_map"], maand)
    if bewaard.exists():
        try:
            inhoud = json.loads(bewaard.read_text(encoding="utf-8"))
            return dict(inhoud["vbo_status"]), f"{bewaard.name} (uit {inhoud.get('snapshot')})", False
        except (OSError, ValueError, KeyError, TypeError) as fout:
            raise ControleFout(f"De bewaarde basis {bewaard} is onleesbaar: {fout}") from None
    if snapshot_naam:
        snapshot = ins["snapshot_map"] / snapshot_naam
        if snapshot.exists():
            return lees_basis_uit_snapshot(snapshot, panden), snapshot_naam, True
    return None, "", False


def schrijf_basis(ins: dict, maand: str, snapshot_naam: str, statussen: dict[str, str]) -> None:
    pad = basis_pad(ins["basis_map"], maand)
    if pad.exists():
        return  # nooit overschrijven: de basis van een maand verandert niet
    _schrijf_atomair(pad, json.dumps({"snapshot": snapshot_naam, "vbo_status": dict(sorted(statussen.items()))},
                                     ensure_ascii=False, indent=0))


# ------------------------------------------------------------------------------ WFS
def _gelijk(veld: str, waarde: str) -> str:
    return ('<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:PropertyIsEqualTo>'
            f"<fes:ValueReference>{veld}</fes:ValueReference><fes:Literal>{escape(waarde)}</fes:Literal>"
            "</fes:PropertyIsEqualTo></fes:Filter>")


def params_pand(pand_id: str, count: int) -> dict:
    """Eén GetFeature met twee queries: het pand op identificatie, zijn VBO's op pandidentificatie."""
    return {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"{LAAG_PAND},{LAAG_VBO}",
        "filter": f"({_gelijk('identificatie', pand_id)})({_gelijk('pandidentificatie', pand_id)})",
        "propertyName": "(identificatie,status)(identificatie,status,pandidentificatie)",
        "count": count,
    }


def params_vbo_pagina(pand_id: str, count: int, start: int) -> dict:
    return {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": LAAG_VBO,
        "filter": _gelijk("pandidentificatie", pand_id),
        "propertyName": "identificatie,status,pandidentificatie",
        "count": count, "startIndex": start,
    }


def _lees_xml(tekst: bytes) -> ET.Element:
    try:
        wortel = ET.fromstring(tekst)
    except ET.ParseError as fout:
        raise PandFout(f"onleesbaar antwoord van de WFS ({fout})") from None
    if wortel.tag != f"{WFS_NS}FeatureCollection":
        melding = " ".join(t.strip() for t in wortel.itertext() if t.strip())[:200]
        raise PandFout(f"de WFS gaf geen FeatureCollection: {melding}")
    return wortel


def _objecten(wortel: ET.Element, soort: str) -> list[dict[str, str]]:
    uit = []
    for el in wortel.iter(f"{BAG_NS}{soort}"):
        uit.append({kind.tag.removeprefix(BAG_NS): (kind.text or "").strip() for kind in el})
    return uit


def controleer_pand(session: requests.Session, ins: dict, pand_id: str) -> Nu:
    """Wat de WFS nu over het pand zegt. PandFout als het niet lukt."""
    count = ins["paginagrootte"]
    timeout = ins["timeout_s"]
    try:
        antwoord = ingest._wfs_get(session, ins["wfs_url"], params_pand(pand_id, count), timeout=timeout)
    except requests.RequestException as fout:
        raise PandFout(f"verzoek mislukt ({fout.__class__.__name__}: {str(fout)[:160]})") from None
    wortel = _lees_xml(antwoord.content)
    panden = _objecten(wortel, "pand")
    vbos = _objecten(wortel, "verblijfsobject")
    # Een genegeerd filter geeft andere panden terug (de cql_filter-valkuil): nooit stil accepteren.
    vreemd = [p.get("identificatie") for p in panden if p.get("identificatie") != pand_id]
    vreemd += [v.get("identificatie") for v in vbos if v.get("pandidentificatie") != pand_id]
    if vreemd or len(panden) > 1:
        raise PandFout(f"de WFS gaf objecten die niet bij dit pand horen ({len(vreemd)}); filter genegeerd?")
    if len(panden) + len(vbos) >= count:
        # Afgekapt: de VBO's opnieuw, alleen die laag, pagina voor pagina.
        vbos, start = [], 0
        while True:
            try:
                pagina = ingest._wfs_get(session, ins["wfs_url"], params_vbo_pagina(pand_id, count, start),
                                         timeout=timeout)
            except requests.RequestException as fout:
                raise PandFout(f"verzoek mislukt bij pagineren ({fout.__class__.__name__})") from None
            deel = _objecten(_lees_xml(pagina.content), "verblijfsobject")
            if any(v.get("pandidentificatie") != pand_id for v in deel):
                raise PandFout("de WFS gaf bij het pagineren objecten van een ander pand; filter genegeerd?")
            vbos += deel
            start += len(deel)
            if len(deel) < count:
                break
    if not panden:
        return Nu(gevonden=False, vbo={v["identificatie"]: v.get("status", "") for v in vbos})
    return Nu(True, panden[0].get("status", ""), {v["identificatie"]: v.get("status", "") for v in vbos})


# ------------------------------------------------------------------------------ vergelijken
def verschillen(pand: Pand, nu: Nu, basis: dict[str, str] | None) -> list[tuple[str, str, str, str, str]]:
    """(soort, wijziging, vbo_id, waarde_werklijst, waarde_nu) per verschil, zonder datum."""
    if not nu.gevonden:
        return [(PAND_NIET_GEVONDEN, "Pand niet meer gevonden in de BAG", "", pand.pandstatus, NIET_IN_BAG)]
    uit = []
    if nu.status != pand.pandstatus:
        if nu.status == STATUS_GESLOOPT:
            uit.append((PAND_GESLOOPT, "Pand gesloopt", "", pand.pandstatus, nu.status))
        elif nu.status == STATUS_BUITEN_GEBRUIK:
            uit.append((PAND_BUITEN_GEBRUIK, "Pand buiten gebruik", "", pand.pandstatus, nu.status))
        else:
            uit.append((PANDSTATUS, "Pandstatus gewijzigd", "", pand.pandstatus, nu.status))
    werklijst = set(pand.vbo_ids)
    for vid in sorted(set(nu.vbo) - werklijst):
        uit.append((VBO_ERBIJ, f"Verblijfsobject {vid} erbij", vid, NIET_IN_WERKLIJST, nu.vbo[vid]))
    for vid in sorted(werklijst - set(nu.vbo)):
        was = (basis or {}).get(vid) or AANWEZIG
        uit.append((VBO_WEG, f"Verblijfsobject {vid} niet meer in de BAG", vid, was, NIET_IN_BAG))
    if basis is not None:
        for vid in sorted(werklijst & set(nu.vbo)):
            if vid in basis and basis[vid] != nu.vbo[vid]:
                uit.append((VBO_STATUS, f"Status van verblijfsobject {vid} gewijzigd", vid, basis[vid], nu.vbo[vid]))
    return uit


def lees_vorige(pad: Path) -> list[Rij]:
    if not pad.exists():
        return []
    try:
        with open(pad, encoding="utf-8-sig", newline="") as fh:
            return [Rij(**{k: (r.get(k) or "") for k in KOLOMMEN}) for r in csv.DictReader(fh, delimiter=";")]
    except (OSError, TypeError, csv.Error) as fout:
        raise ControleFout(f"Het vorige bestand {pad} is niet te lezen: {fout}") from None


def voeg_samen(vorige: list[Rij], gezien: dict[str, list[tuple]], mislukt: dict[str, str], vandaag: str) -> list[Rij]:
    """
    De nieuwe rijen. Gezien verschil: datum van de eerste keer, als het er toen al was. Verschil dat
    weg is: weg. Niet gecontroleerd pand: zijn eerdere verschillen blijven, plus een rij voor vannacht.
    """
    eerder = {r.sleutel: r.eerst_gezien for r in vorige if r.soort != NIET_GECONTROLEERD}
    uit: list[Rij] = []
    for pid, lijst in gezien.items():
        for soort, wijziging, vid, was, nu in lijst:
            uit.append(Rij(pid, soort, wijziging, vid, was, nu, eerder.get((pid, soort, vid, nu), vandaag)))
    for pid, reden in mislukt.items():
        uit += [r for r in vorige if r.bag_pand_id == pid and r.soort != NIET_GECONTROLEERD]
        uit.append(Rij(pid, NIET_GECONTROLEERD, f"Niet gecontroleerd: {reden}", "", "", "", vandaag))
    return sorted(uit, key=lambda r: (r.bag_pand_id, r.soort, r.vbo_id, r.waarde_nu))


# ------------------------------------------------------------------------------ schrijven
def _schrijf_atomair(pad: Path, tekst: str, bom: bool = False) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    tijdelijk = pad.with_name(pad.name + ".tmp")
    with open(tijdelijk, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write(tekst)
    os.replace(tijdelijk, pad)


def csv_tekst(rijen: list[Rij]) -> str:
    buf = io.StringIO()
    schrijver = csv.writer(buf, delimiter=";", lineterminator="\n")
    schrijver.writerow(KOLOMMEN)
    for r in rijen:
        schrijver.writerow([getattr(r, k) for k in KOLOMMEN])
    return buf.getvalue()


def uitvoer_pad(uitvoer_map: Path, maand: str) -> Path:
    return uitvoer_map / f"wijzigingen_{GEBIED}_{maand}.csv"


# ------------------------------------------------------------------------------ de controle
def controleer(ins: dict, werklijst: Path | None = None, session: TelSessie | None = None,
               nu: datetime | None = None) -> tuple[dict, int]:
    """
    De hele controle. Geeft (resultaat, exitcode) nadat het bestand en de uitkomst geschreven zijn.
    ControleFout als er niets te controleren viel of geen pand lukte: dan is er niets geschreven.
    """
    moment = (nu or datetime.now(timezone.utc)).astimezone()
    vandaag = vandaag_nl(moment)
    werklijst, maand = (werklijst, maand_van(werklijst)) if werklijst else nieuwste_werklijst(ins["werklijst_map"])
    panden, snapshot_naam = lees_werklijst(werklijst)
    begin = time.monotonic()
    basis, basis_bron, basis_nieuw = basis_statussen(ins, maand, snapshot_naam, panden)
    seconden_basis = time.monotonic() - begin
    session = session or TelSessie()
    al_geteld = session.verzoeken

    gezien: dict[str, list[tuple]] = {}
    mislukt: dict[str, str] = {}
    achtereen = 0
    for i, pand in enumerate(panden, 1):
        if achtereen >= ins["stop_na_mislukt"]:
            mislukt[pand.bag_pand_id] = (f"niet gevraagd: de {nl_tal(achtereen)} panden ervoor mislukten "
                                         "achter elkaar (PDOK onbereikbaar?)")
            continue
        try:
            stand = controleer_pand(session, ins, pand.bag_pand_id)
        except PandFout as fout:
            # ingest._wfs_get heeft al herhaald met wachttijd (VA-75 criterium 4)
            mislukt[pand.bag_pand_id] = str(fout)
            achtereen += 1
            continue
        achtereen = 0
        gezien[pand.bag_pand_id] = verschillen(pand, stand, basis)
        if i % 50 == 0:
            print(f"  {nl_tal(i)}/{nl_tal(len(panden))} panden", flush=True)

    if not gezien:
        raise ControleFout(f"Geen enkel pand kon worden gecontroleerd ({nl_tal(len(mislukt))} mislukt). "
                           "Is PDOK bereikbaar?")

    doel = uitvoer_pad(ins["uitvoer_map"], maand)
    rijen = voeg_samen(lees_vorige(doel), gezien, mislukt, vandaag)
    _schrijf_atomair(doel, csv_tekst(rijen), bom=True)
    if basis_nieuw and basis is not None and snapshot_naam:
        schrijf_basis(ins, maand, snapshot_naam, basis)

    per_soort = Counter(r.soort for r in rijen if r.soort != NIET_GECONTROLEERD)
    r = {
        "gecontroleerd_om": moment.isoformat(timespec="seconds"),
        "datum": vandaag,
        "werklijst": werklijst.name,
        "maand": maand,
        "bestand": str(doel),
        "panden": len(panden),
        "gecontroleerd": len(gezien),
        "niet_gecontroleerd": len(mislukt),
        "verschillen_per_soort": {s: per_soort.get(s, 0) for s in SOORTEN},
        "panden_met_verschil": len({r.bag_pand_id for r in rijen if r.soort != NIET_GECONTROLEERD}),
        "vbo_status_vergeleken": basis is not None,
        "basis": basis_bron or None,
        "verzoeken": session.verzoeken - al_geteld,
        "seconden": round(time.monotonic() - begin, 1),     # alles, ook het lezen van de basis
        "seconden_basis": round(seconden_basis, 1),
    }
    if mislukt:
        r["uitkomst"] = "deels"
        r["melding"] = (f"{nl_tal(len(gezien))} van {nl_tal(len(panden))} panden gecontroleerd; "
                        f"{nl_tal(len(mislukt))} niet gecontroleerd (staan in het bestand).")
    else:
        r["uitkomst"] = "gecontroleerd"
        r["melding"] = f"Alle {nl_tal(len(panden))} panden gecontroleerd."
    if basis is None:
        r["waarschuwing"] = (f"Statussen van verblijfsobjecten niet vergeleken: geen bewaarde basis en geen "
                             f"snapshot {snapshot_naam or '(onbekend)'} in {ins['snapshot_map']}.")
    _schrijf_atomair(ins["resultaat"], json.dumps(r, ensure_ascii=False, indent=2))
    return r, 0


def main(argv: list[str] | None = None) -> int:
    try:
        ins = instellingen(load_config())
    except ControleFout as fout:
        print(f"FOUT: {fout} Niets geschreven.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description="Controleer de werklijst 's nachts tegen de PDOK BAG WFS (VA-75).")
    parser.add_argument("--werklijst", type=Path, help="werklijst_nederland_<JJJJ-MM>.csv (standaard de nieuwste)")
    parser.add_argument("--uitvoer", type=Path, default=ins["uitvoer_map"], help="map voor wijzigingen_*.csv")
    parser.add_argument("--resultaat", type=Path, default=ins["resultaat"], help="JSON met de uitkomst")
    parser.add_argument("--basis", type=Path, default=ins["basis_map"], help="map met de bewaarde basis")
    parser.add_argument("--snapshots", type=Path, default=ins["snapshot_map"], help="map met bag_nl_<datum>.sqlite")
    args = parser.parse_args(argv)
    ins.update(uitvoer_map=args.uitvoer, resultaat=args.resultaat, basis_map=args.basis, snapshot_map=args.snapshots)
    try:
        r, code = controleer(ins, args.werklijst)
    except ControleFout as fout:
        print(f"FOUT: {fout} Niets geschreven; het vorige bestand blijft staan.", file=sys.stderr)
        return 1
    print(r["melding"])
    if "waarschuwing" in r:
        print(f"LET OP: {r['waarschuwing']}", file=sys.stderr)
    soorten = ", ".join(f"{s} {n}" for s, n in r["verschillen_per_soort"].items())
    print(f"Verschillen: {soorten}.")
    seconden = f"{r['seconden']:.1f}".replace(".", ",")
    print(f"{nl_tal(r['verzoeken'])} verzoeken in {seconden} s. Bestand -> {r['bestand']}; uitkomst -> {args.resultaat}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
