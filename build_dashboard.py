"""
Levrai Group - Pandenselectiesysteem
Bouwt het dashboard (design/index.html) data-gedreven uit panden_<gebied>.json.

Welk gebied, kiest config.yaml: doelgebied.nederland: true leest data/panden_nederland.json
(VA-37: de landelijke totalen en de werklijst van de maand, VA-39); anders panden_<stad>.json
met alle panden van dat gebied, zoals voor Delft.

Draai na run_proef.py. Genereert een zelfstandige HTML met ingesloten payload,
zodat de pagina ook als statische snapshot (Claude Design) werkt zonder fetch.

Welke BAG-snapshot(s) het resultaat voeden staat in data/panden_<gebied>.bron.json,
geschreven door run_proef.py. Het dashboard meldt die op scherm en in de pagina; ontbreekt
het bestand, dan staat er dat de bron onbekend is.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from html import escape
from pathlib import Path

import cbs_gemeenten
import kaart_nl
import nederland
import snapshots
from gebieden import resolve, slug
from selectie import load_config

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT = BASE / "design" / "index.html"

MAANDEN = ("jan", "feb", "mrt", "apr", "mei", "jun",
           "jul", "aug", "sep", "okt", "nov", "dec")
MAANDEN_VOL = ("januari", "februari", "maart", "april", "mei", "juni",
               "juli", "augustus", "september", "oktober", "november", "december")
BRON_ONBEKEND = "bron onbekend — draai run_proef.py opnieuw"
PEILDATUM_ONBEKEND = "Peildatum onbekend"
NBSP = "\u00a0"  # harde spatie: een datum breekt nooit over twee regels


def lees_datum(iso: str | None) -> date | None:
    """'JJJJ-MM-DD' -> date; None, leeg of onleesbaar (ook een niet-bestaande dag) -> None."""
    try:
        j, m, d = (int(x) for x in str(iso).split("-"))
        return date(j, m, d)
    except (ValueError, TypeError):
        return None


def _nl(dag: date, met_jaar: bool = True) -> str:
    tekst = f"{dag.day}{NBSP}{MAANDEN[dag.month - 1]}"
    return f"{tekst}{NBSP}{dag.year}" if met_jaar else tekst


def nl_datum(iso: str | None) -> str:
    """'JJJJ-MM-DD' -> 'D mmm JJJJ' (harde spaties); onleesbaar -> 'ophaaldatum onbekend'."""
    dag = lees_datum(iso)
    return _nl(dag) if dag else "ophaaldatum onbekend"


def peildatum(bron: list[dict] | None) -> str:
    """
    De peildatum in de kop, uit de ophaaldatum van de bron-snapshot(s) (VA-12).

    Eén datum voor alle woonplaatsen -> 'Peildatum D mmm JJJJ'.
    Verschillende datums -> 'Peildatum <vroegste> – <laatste>', zodat geen enkele datum
    lijkt te gelden voor het hele gebied.
    Bron onbekend, of een snapshot zonder leesbare datum -> 'Peildatum onbekend';
    nooit een vaste datum of die van vandaag.
    """
    if not bron:
        return PEILDATUM_ONBEKEND
    datums = [lees_datum(b.get("ophaaldatum")) for b in bron]
    if any(d is None for d in datums):
        return PEILDATUM_ONBEKEND
    vroegst, laatst = min(datums), max(datums)
    if vroegst == laatst:
        return f"Peildatum {_nl(vroegst)}"
    if vroegst.year == laatst.year:
        return f"Peildatum {_nl(vroegst, met_jaar=False)} – {_nl(laatst)}"
    return f"Peildatum {_nl(vroegst)} – {_nl(laatst)}"


def peildatum_tip(bron: list[dict] | None, reden: str = "") -> str:
    """Tooltip bij de peildatum: per woonplaats, als één datum niet alles zegt."""
    if bron is None:
        return f"{BRON_ONBEKEND} ({reden})" if reden else BRON_ONBEKEND
    if len(bron) == 1 and peildatum(bron) != PEILDATUM_ONBEKEND:
        return ""
    return " · ".join(bron_regels(bron))


def lees_bron(panden_pad: Path) -> tuple[list[dict] | None, str]:
    """
    Lees panden_<gebied>.bron.json naast panden_<gebied>.json.

    Geeft (snapshots, reden): snapshots is een lijst van
    {'woonplaats', 'bestand', 'ophaaldatum'}, of None als de bron niet vaststaat;
    reden zegt dan waarom.
    """
    bron_pad = panden_pad.with_name(panden_pad.stem + ".bron.json")
    if not bron_pad.is_file():
        return None, f"{bron_pad.name} ontbreekt"
    # run_proef.py schrijft eerst panden_*.json en daarna de .bron.json; is panden
    # nieuwer, dan komt de .bron.json van een eerdere run en klopt hij niet meer.
    if panden_pad.stat().st_mtime > bron_pad.stat().st_mtime:
        return None, f"{bron_pad.name} is ouder dan {panden_pad.name}"
    try:
        bron = json.loads(bron_pad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fout:
        return None, f"{bron_pad.name} is niet leesbaar ({fout})"
    if (not isinstance(bron, list) or not bron
            or not all(isinstance(b, dict) and b.get("bestand") for b in bron)):
        return None, f"{bron_pad.name} heeft geen geldige snapshotlijst"
    return bron, ""


def bron_regels(bron: list[dict] | None) -> list[str]:
    """Eén regel per woonplaats, voor scherm en pagina."""
    if bron is None:
        return [BRON_ONBEKEND]
    return [f"{b.get('woonplaats', '?')}: {b['bestand']} (opgehaald {nl_datum(b.get('ophaaldatum'))})"
            for b in bron]


def maand_voluit(jjjj_mm: str | None) -> str:
    """'JJJJ-MM' -> 'november JJJJ' (maand voluit, kleine letter); onleesbaar -> 'onbekend'."""
    try:
        j, m = (int(x) for x in str(jjjj_mm).split("-"))
        return f"{MAANDEN_VOL[m - 1]} {j}" if 1 <= m <= 12 else "onbekend"
    except (ValueError, TypeError):
        return "onbekend"


def lees_landelijk(pad: Path) -> tuple[dict | None, str]:
    """
    Lees panden_nederland.json (VA-37): {'gebied', 'totalen', 'werklijst', 'proef'}.
    Ontbreekt het bestand of klopt de vorm niet, dan (None, reden), net als lees_panden().
    """
    if not pad.is_file():
        return None, f"{pad.name} ontbreekt"
    try:
        inhoud = json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fout:
        return None, f"{pad.name} is niet leesbaar ({fout})"
    if (not isinstance(inhoud, dict) or not isinstance(inhoud.get("totalen"), dict)
            or not isinstance(inhoud.get("werklijst"), list)):
        return None, f"{pad.name} heeft geen totalen en werklijst"
    return inhoud, ""


def lees_panden(panden_pad: Path) -> tuple[list[dict] | None, str]:
    """
    Lees panden_<gebied>.json. Ontbreekt het bestand of is het onleesbaar, dan
    (None, reden): het dashboard toont dan 'onbekend' in plaats van te stoppen.
    """
    if not panden_pad.is_file():
        return None, f"{panden_pad.name} ontbreekt"
    try:
        panden = json.loads(panden_pad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fout:
        return None, f"{panden_pad.name} is niet leesbaar ({fout})"
    if not isinstance(panden, list):
        return None, f"{panden_pad.name} is geen lijst van panden"
    return panden, ""


def binnen_a_e(panden: list[dict]) -> list[dict]:
    """De mastervoorraad: niet uitgesloten en in minstens één categorie A–E."""
    return [p for p in panden if not p["uitgesloten"] and p["categorieen"]]


def werklijst_aantal(act: list[dict], drempel: int) -> int:
    """Panden met leadscore ≥ drempel: één telling voor de KPI en het kantoor."""
    return sum(1 for p in act if p["leadscore"] >= drempel)


# Per verrijkingsbron het veld dat verrijk.py aan een pand toevoegt (bronnen/*.py).
VERRIJKT_VELD = {"energielabel": "energielabel_status"}


def actieve_bronnen(cfg: dict) -> list[str]:
    """Bronnen met 'actief: true' in config.yaml, met hoofdletter ('Energielabel')."""
    return [naam[:1].upper() + naam[1:]
            for naam, b in (cfg.get("bronnen") or {}).items()
            if isinstance(b, dict) and b.get("actief") is True]


def kantoor(gebied: str, bron: list[dict] | None, panden: list[dict] | None,
            aantal_leads: int | None, cfg: dict) -> dict:
    """
    Het blok PAYLOAD.kantoor (VA-31): de cijfers per medewerker, en onder 'tekst' de
    toestand en zinnen die de pagina toont (kantoor_teksten()). Het script kiest niets.
    Onbekend is None (null), nooit een verzonnen of vast getal.
    """
    drempels = cfg.get("drempels") or {}
    drempel = drempels.get("score_min_voor_werklijst")
    actief = actieve_bronnen(cfg)
    act = binnen_a_e(panden) if panden is not None else None
    werklijst = werklijst_aantal(act, drempel) if act is not None and drempel is not None else None

    verrijkt = None
    velden = [VERRIJKT_VELD.get(n.lower()) for n in actief]
    if act is not None and actief and all(velden):
        verrijkt = sum(1 for p in act if any(v in p for v in velden))

    blok = {
        "gebied": gebied,
        "ingest": {"bron": bron,
                   "vbo": sum(p["aantal_vbo"] for p in panden) if panden is not None else None,
                   # Wanneer een ophaling verouderd is, is nog niet vastgesteld.
                   "verouderd": False},
        "selectie": {"panden": len(panden) if panden is not None else None,
                     "a_e": len(act) if act is not None else None,
                     "werklijst": werklijst,
                     "drempel": drempel,
                     "werklijst_min": drempels.get("werklijst_min"),
                     "werklijst_max": drempels.get("werklijst_max"),
                     # Voor het bord in de 3D-taxatiekamer (VA-60); dezelfde telling als het dashboard.
                     "categorieen": ({k: sum(1 for p in act if k in p["categorieen"]) for k in "ABCDE"}
                                     if act is not None else None)},
        "verrijking": {"panden": len(act) if act is not None else None,
                       "actief": actief,
                       "verrijkt": verrijkt},
        # Een controlestatus per pand bestaat nog niet: gecontroleerd is onbekend.
        "controle": {"totaal": aantal_leads,
                     "te_controleren": aantal_leads,
                     "gecontroleerd": None},
    }
    blok["tekst"] = kantoor_teksten(blok)
    return blok


def kantoor_landelijk(bron: list[dict] | None, totalen: dict | None, aantal_leads: int | None,
                      cfg: dict) -> dict:
    """
    PAYLOAD.kantoor voor heel Nederland (VA-39 crit. 6): dezelfde vorm als kantoor(), maar de
    cijfers komen uit de totalen die VA-37 schreef; panden_nederland.json heeft niet elk pand.
    'landelijk' kiest in kantoor_teksten() Lumi's landelijke zinnen. Onbekend blijft None.
    """
    t = totalen or {}
    drempels = cfg.get("drempels") or {}
    blok = {
        "gebied": nederland.NAAM,
        "ingest": {"bron": bron, "vbo": t.get("vbo"), "verouderd": False, "landelijk": True},
        "selectie": {"panden": t.get("panden"), "a_e": t.get("a_e"), "werklijst": t.get("werklijst"),
                     "drempel": t.get("drempel"),
                     "werklijst_min": drempels.get("werklijst_min"),
                     "werklijst_max": drempels.get("werklijst_max"),
                     "categorieen": t.get("categorieen"),
                     "geschikt": t.get("geschikt"),
                     "werklijst_groot": t.get("werklijst_25"),
                     "werklijst_elders": t.get("werklijst_overig"),
                     "aantal_groot": t.get("aantal_grote_gemeenten"),
                     "landelijk": True},
        # Verrijking draait (nog) niet landelijk: hoeveel panden verrijkt zijn, is onbekend.
        "verrijking": {"panden": t.get("a_e"), "actief": actieve_bronnen(cfg), "verrijkt": None},
        "controle": {"totaal": aantal_leads, "te_controleren": aantal_leads, "gecontroleerd": None,
                     "landelijk": True},
    }
    blok["tekst"] = kantoor_teksten(blok)
    return blok


# --------------------------------------------------------------- kantoorteksten
# Wat elke medewerker zegt (VA-30-copytabel; VA-31 criteria 2, 4 en 11). Toestand en
# zinnen worden hier gemaakt en getest; het script in de pagina toont ze alleen.
WJ = "⁠"  # woordverbinder: geen regelbreuk direct na het streepje in een datumbereik


def nl_getal(n: int | float | None) -> str:
    """Duizendtallen met een punt (1.234.567); onbekend blijft 'onbekend'."""
    return "onbekend" if n is None else f"{round(n):,}".replace(",", ".")


def opgehaald(bron: list[dict] | None) -> dict | None:
    """Ophaaldatum(s) in woorden, met dezelfde regels als peildatum(); onleesbaar -> None."""
    if not bron:
        return None
    datums = [lees_datum(b.get("ophaaldatum")) for b in bron]
    if any(d is None for d in datums):
        return None
    van, tot = min(datums), max(datums)
    if van == tot:
        return {"kort": _nl(van), "zin": f"op {_nl(van)}", "laatst": _nl(tot)}
    v = _nl(van, met_jaar=van.year != tot.year)
    return {"kort": f"{v}{NBSP}–{WJ}{NBSP}{_nl(tot)}", "zin": f"tussen {v} en {_nl(tot)}",
            "laatst": _nl(tot)}


def toestand(wie: str, d: dict | None) -> str:
    """werkt, aandacht, slaapt of leeg, alleen uit de cijfers (VA-30-toestandstabel)."""
    if wie == "ingest":
        if not d or not d.get("vbo"):
            return "leeg"
        if not opgehaald(d.get("bron")):
            return "aandacht"
        return "slaapt" if d.get("verouderd") else "werkt"
    if wie == "selectie":
        if not d or not d.get("panden"):
            return "leeg"
        # werklijst_min is een waarschuwingsgrens, geen stop (VA-5 criterium 4).
        return "aandacht" if (d.get("werklijst") or 0) < (d.get("werklijst_min") or 0) else "werkt"
    if wie == "verrijking":
        if not d or not d.get("panden"):
            return "leeg"
        if not d.get("actief"):
            return "slaapt"
        return "werkt" if (d.get("verrijkt") or 0) > 0 else "aandacht"
    if wie == "controle":
        if not d or (not d.get("te_controleren") and d.get("gecontroleerd") is None):
            return "leeg"
        gec = d.get("gecontroleerd")
        if gec is None:
            return "aandacht"
        if gec >= (d.get("totaal") or 0):
            return "slaapt"
        return "werkt" if gec > 0 else "aandacht"
    raise ValueError(wie)


def _ingest(s: str, d: dict, g: str) -> tuple[str, str, str]:
    # Landelijk: Lumi's kopij VA-39 (uit het GeoPackage-bestand, niet via de WFS).
    uitleg = (f"Ingest leest de BAG van heel {g} in uit het GeoPackage-bestand van PDOK, de open "
              "dataset van het Kadaster." if d.get("landelijk") else
              f"Ingest haalt alle verblijfsobjecten van {g} op uit de BAG, via de open PDOK-dienst.")
    uitleg += (" Elke ophaling blijft bewaard als eigen, gedateerde momentopname, zodat je altijd ziet "
               "uit welke ophaling een cijfer komt.")
    if s == "werkt":
        o = opgehaald(d["bron"])
        zin = (f"Ingest heeft de BAG van heel {g} ingelezen uit het bestand van {o['kort']}: "
               if d.get("landelijk") else f"Ingest heeft de BAG van {g} opgehaald {o['zin']}: ")
        return (f"BAG opgehaald {o['kort']}", zin + f"{nl_getal(d.get('vbo'))} verblijfsobjecten.", uitleg)
    if s == "aandacht":
        if not d.get("bron"):
            return ("Bron onbekend", "Ingest weet niet uit welke BAG-ophaling deze cijfers komen. "
                    "Draai run_proef.py opnieuw, dan legt het de bron vast.", uitleg)
        return ("Ophaaldatum onbekend", "Ingest kent de BAG-ophaling achter deze cijfers, maar niet de "
                "datum waarop die is opgehaald.", uitleg)
    if s == "slaapt":
        o = opgehaald(d["bron"])
        return (f"Laatste ophaling {o['laatst']}",
                f"Ingest heeft sinds {o['laatst']} niet opnieuw opgehaald.", uitleg)
    return ("Nog geen BAG opgehaald", f"Ingest heeft voor {g} nog geen BAG-gegevens opgehaald.",
            "Ingest haalt alle verblijfsobjecten van een gebied op uit de BAG, via de open PDOK-dienst. "
            "Voor dit gebied is nog niets opgehaald; daarom staan hier nog geen cijfers.")


def _selectie(s: str, d: dict, g: str) -> tuple[str, str, str]:
    w, dr = nl_getal(d.get("werklijst")), d.get("drempel")
    mn, mx = nl_getal(d.get("werklijst_min")), nl_getal(d.get("werklijst_max"))
    landelijk = d.get("landelijk")
    # Landelijk is de werklijst de beste {w} uit de geschikte panden (VA-37), niet alle geschikte.
    geschikt = nl_getal(d.get("geschikt")) if landelijk else w
    uitleg = (f"Selectie groepeert de verblijfsobjecten per BAG-pand, sluit panden uit die buiten de "
              f"briefing vallen, deelt de rest in categorie A–E in en geeft elk pand een leadscore. Van de "
              f"{nl_getal(d.get('panden'))} panden in {g} vallen er {nl_getal(d.get('a_e'))} in A–E; {geschikt} "
              f"halen score {dr} of hoger.")
    if landelijk:
        uitleg += (f" Daaruit komen de {w} hoogst scorende op de werklijst: {nl_getal(d.get('werklijst_groot'))} "
                   f"uit de {nl_getal(d.get('aantal_groot'))} gemeenten met de meeste inwoners (CBS) en "
                   f"{nl_getal(d.get('werklijst_elders'))} elders in {g}. Bij gelijke score beslist een loting "
                   "die de hele maand gelijk blijft.")
    if s == "werkt":
        zin = (f"Selectie heeft {nl_getal(d.get('a_e'))} panden in categorie A–E gescoord. {geschikt} halen "
               f"score {dr} of hoger; de {w} beste staan op de werklijst." if landelijk else
               f"Selectie heeft {nl_getal(d.get('a_e'))} panden in categorie A–E gescoord. {w} halen score "
               f"{dr} of hoger en staan op de werklijst.")
        return (f"{w} panden op de werklijst", zin, uitleg)
    if s == "aandacht":
        # Nova, VA-30 Q5: de maand blijft onder de gebruikelijke 200–500; nooit "ondergrens" of
        # "geen levering".
        return (f"{w} op de werklijst: onder de gebruikelijke {mn}–{mx}",
                f"Selectie vindt {w} panden met score {dr} of hoger. Deze maand blijft daarmee onder de "
                f"gebruikelijke {mn}–{mx} panden. De werklijst wordt wel gemaakt, met deze {w} panden.",
                uitleg)
    return ("Geen panden om te scoren",
            "Selectie heeft nog geen panden om te scoren: Ingest heeft niets aangeleverd.",
            "Selectie groepeert de verblijfsobjecten per BAG-pand, deelt ze in categorie A–E in en geeft "
            "elk pand een leadscore. Zodra Ingest gegevens heeft opgehaald, zie je hier hoeveel panden op "
            "de werklijst staan.")


def _verrijking(s: str, d: dict, g: str) -> tuple[str, str, str]:
    actief = d.get("actief") or []
    uitleg = (f"Verrijking vult panden aan met gegevens die de BAG niet heeft. Nu actief: "
              f"{', '.join(actief).lower()}." if actief else
              "Verrijking vult panden aan met gegevens die de BAG niet heeft. Het energielabel van RVO "
              "EP-online staat klaar, maar staat uit. Zolang het uit staat, levert het criterium ‘Slecht "
              "of ontbrekend energielabel’ (+2) geen punten op; in de score-opbouw staat het grijs.")
    if s == "werkt":
        return (f"{actief[0]} bij {nl_getal(d.get('verrijkt'))} panden",
                f"Verrijking heeft het {actief[0].lower()} toegevoegd aan {nl_getal(d.get('verrijkt'))} panden.",
                uitleg)
    if s == "aandacht":
        return (f"{actief[0]} nog niet opgehaald",
                f"Het {actief[0].lower()} staat aan, maar Verrijking heeft nog niets opgehaald. Draai "
                "verrijk.py en daarna run_proef.py.", uitleg)
    if s == "slaapt":
        return ("Geen extra bron actief", "Verrijking staat uit: er is geen extra bron actief. Het "
                "energielabel telt daardoor nog niet mee in de score.", uitleg)
    return ("Geen panden om aan te vullen", "Verrijking heeft nog geen panden om aan te vullen.",
            "Verrijking vult panden aan met gegevens die de BAG niet heeft, zoals het energielabel. Er "
            "zijn nog geen panden om aan te vullen.")


def _controle(s: str, d: dict, g: str) -> tuple[str, str, str]:
    tot, gec = nl_getal(d.get("totaal")), nl_getal(d.get("gecontroleerd"))
    wat = f"de {tot} panden van de werklijst" if d.get("landelijk") else f"de {tot} hoogst scorende panden"
    uitleg = (f"Controle zet {wat} klaar voor je visuele controle. Bekijk elk "
              "pand op de kaart, de luchtfoto en Street View voordat het een lead wordt. Bij elk pand "
              "hieronder staat een link naar de BAG-viewer.")
    if s == "werkt":
        return (f"{gec} van {tot} gecontroleerd", f"Je hebt {gec} van de {tot} panden gecontroleerd.",
                uitleg)
    if s == "aandacht":
        te = nl_getal(d.get("te_controleren"))
        return (f"{te} panden wachten op visuele controle",
                f"{te} panden wachten op je visuele controle: bekijk ze op de kaart, de luchtfoto en "
                "Street View.", uitleg)
    if s == "slaapt":
        return ("Alles gecontroleerd", f"Je hebt alle {tot} panden gecontroleerd.", uitleg)
    return ("Geen panden om te controleren", "Er staan nog geen panden klaar voor controle.",
            "Controle zet de hoogst scorende panden klaar voor je visuele controle op kaart, luchtfoto "
            "en Street View. Er staan nog geen panden klaar.")


_TEKST = {"ingest": _ingest, "selectie": _selectie, "verrijking": _verrijking, "controle": _controle}


NAMEN = {"ingest": "Ingest", "selectie": "Selectie", "verrijking": "Verrijking", "controle": "Controle"}


def chef_teksten(toestanden: dict[str, str]) -> dict:
    """
    Wat de kantoormanager in het 3D-kantoor zegt (VA-60, copy van VA-48): naar wie die
    loopt, en per medewerker de ballon als die daar aankomt.
    """
    ns = [NAMEN[w] for w in _TEKST if toestanden.get(w) == "aandacht"]
    if not ns:
        zin = "Niemand vraagt nu je aandacht. De kantoormanager loopt een ronde door het kantoor."
    elif len(ns) == 1:
        zin = f"Loopt naar {ns[0]}, die je aandacht vraagt."
    else:
        zin = f"Loopt langs {', '.join(ns[:-1])} en {ns[-1]}, die je aandacht vragen."
    return {"zin": zin, "bel": {w: f"Kijk even bij {NAMEN[w]}" for w in _TEKST}}


def kantoor_teksten(k: dict) -> dict:
    """
    Per medewerker de toestand en de zinnen die de pagina toont:
    {'s': toestand, 'bel': tekstballon, 'zin': statusregel, 'uitleg': uitleg bij klikken}.
    """
    g = k.get("gebied") or "dit gebied"
    uit = {}
    for wie, maak in _TEKST.items():
        d = k.get(wie)
        s = toestand(wie, d)
        bel, zin, uitleg = maak(s, d or {}, g)
        uit[wie] = {"s": s, "bel": bel, "zin": zin, "uitleg": uitleg}
    uit["chef"] = chef_teksten({w: r["s"] for w, r in uit.items()})
    return uit


# --------------------------------------------------------------- pand openen (VA-61, VA-62)
# Elk veld van een pand uit panden_<gebied>.json, met een Nederlands label. Een veld dat hier
# ontbreekt laat tests/test_dashboard_pand.py falen: een nieuw veld kan niet ongemerkt wegvallen.
# Labels en lege-waardewoorden: concept van de hoofdsessie, ter goedkeuring bij Lumi (VA-61 crit. 9).
FUNCTIENAMEN = {"woon": "Wonen", "winkel": "Winkel", "kantoor": "Kantoor", "overig": "Overig",
                "bedrijf": "Bedrijf"}
LEEG = "onbekend"
NIET_INGEVULD = "niet ingevuld"
GEEN = "geen"

PAND_VELDEN = [  # (veld, label, soort)
    ("hoofdadres", "Hoofdadres", "tekst"),
    ("woonplaats", "Woonplaats", "tekst"),
    # Alleen landelijke records (VA-37 crit. 2); labels van Lumi (kopij VA-39, sectie 3).
    ("gemeente", "Gemeente", "gemeente"),
    ("gemeentecode", "Gemeentecode", "tekst"),
    ("grote_gemeente", "In de {aantal} grootste gemeenten", "tekst"),  # 'ja'/'nee' in de data
    ("postcode", "Postcode", "tekst"),
    ("huisnummer", "Huisnummer", "tekst"),
    ("huisletter", "Huisletter", "geen_tekst"),
    ("aantal_adressen", "Aantal adressen", "getal"),
    ("gekoppelde_adressen", "Alle adressen", "lijst"),
    ("bag_pand_id", "BAG-pand-ID", "tekst"),
    ("lead_id", "Lead-ID", "tekst"),
    ("bouwjaar", "Bouwjaar", "jaar"),
    ("pandstatus", "Pandstatus", "tekst"),
    ("totale_oppervlakte", "Totale oppervlakte", "m2"),
    ("opp_per_functie", "Oppervlakte per functie", "functie_m2"),
    ("aantal_per_functie", "Verblijfsobjecten per functie", "functie_aantal"),
    ("gebruiksdoelen", "Gebruiksdoelen", "lijst"),
    ("aantal_vbo", "Aantal verblijfsobjecten", "getal"),
    ("vbo_ids", "Verblijfsobject-ID's", "lijst"),
    ("vbo_statussen", "Status verblijfsobjecten", "lijst"),
    ("categorieen", "Categorieën", "lijst"),
    ("pandcategorie", "Hoofdcategorie", "tekst"),
    ("leadscore", "Leadscore (punten)", "getal"),
    ("score100", "Score-index (/100)", "getal"),
    ("score_opbouw", "Score-opbouw", "opbouw"),
    ("selectiereden", "Selectiereden", "tekst"),
    ("uitgesloten", "Uitgesloten", "janee"),
    ("uitsluitredenen", "Redenen voor uitsluiting", "lijst"),
    ("x", "X-coördinaat (RD)", "rd"),
    ("y", "Y-coördinaat (RD)", "rd"),
    ("bron", "Bron", "tekst"),
    ("datapeildatum", "Peildatum van de gegevens", "datum"),
    ("visuele_controle", "Visueel gecontroleerd", "janee"),
    ("beoordeling", "Beoordeling", "invul"),
    ("eerder_geselecteerd", "Eerder geselecteerd", "janee"),
    ("laatst_beoordeeld", "Laatst beoordeeld", "invuldatum"),
]
# Velden die een Delfts record niet heeft: daar geen rij, in plaats van drie keer 'onbekend'.
ALLEEN_LANDELIJK = {"gemeente", "gemeentecode", "grote_gemeente"}
# De rijen van de detailweergave: alles behalve de score-opbouw, die de pagina apart toont.
DETAIL_VELDEN = [(v, label, soort) for v, label, soort in PAND_VELDEN if soort != "opbouw"]


def _decimaal(n: float, decimalen: int) -> str:
    """1234.5 -> '1.234,5': punt voor duizendtallen, komma voor decimalen."""
    tekst = f"{n:,.{decimalen}f}"
    return tekst.replace(",", "§").replace(".", ",").replace("§", ".")


def _leeg(v) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def pand_waarde(soort: str, v):
    """Een veldwaarde als Nederlandse tekst, of als lijst teksten. Nooit None/true/[]/NaN."""
    if soort == "opbouw":
        return None  # de score-opbouw toont de pagina met dezelfde rijen als op de kaart
    if soort == "lijst":
        items = [str(x) for x in (v or []) if not _leeg(x)]
        return items if items else GEEN
    if soort in ("functie_m2", "functie_aantal"):
        rijen = [(k, x) for k, x in (v or {}).items() if x]
        if not rijen:
            return GEEN
        if soort == "functie_m2":
            return [f"{FUNCTIENAMEN.get(k, k)}: {_decimaal(x, 0)} m²" for k, x in rijen]
        return [f"{FUNCTIENAMEN.get(k, k)}: {nl_getal(x)}" for k, x in rijen]
    if soort == "geen_tekst":
        return GEEN if _leeg(v) else str(v)
    if soort == "invul":
        return NIET_INGEVULD if _leeg(v) else str(v)
    if soort == "invuldatum":
        return NIET_INGEVULD if _leeg(v) else (nl_datum(v) if lees_datum(v) else str(v))
    if _leeg(v):
        return LEEG
    if soort == "janee":
        return "ja" if v else "nee"
    if soort in ("getal", "jaar", "m2", "rd") and (isinstance(v, bool) or not isinstance(v, (int, float))):
        return str(v)  # geen getal in de data: toon wat er staat, verzin niets
    if soort == "getal":
        return nl_getal(v)
    if soort == "jaar":
        return str(int(v))
    if soort == "m2":
        return f"{_decimaal(v, 0)} m²"
    if soort == "rd":
        return _decimaal(v, 2)
    if soort == "datum":
        return nl_datum(v) if lees_datum(v) else str(v)
    if soort == "gemeente":
        return gemeente_naam(v)
    return str(v)


# RD New (EPSG:28992) -> WGS84, de bekende reeksbenadering; geen nieuwe afhankelijkheid (VA-62).
_RD_X0, _RD_Y0, _PHI0, _LAM0 = 155000.0, 463000.0, 52.15517440, 5.38720621
_RD_K = [(0, 1, 3235.65389), (2, 0, -32.58297), (0, 2, -0.24750), (2, 1, -0.84978), (0, 3, -0.06550),
         (2, 2, -0.01709), (1, 0, -0.00738), (4, 0, 0.00530), (2, 3, -0.00039), (4, 1, 0.00033),
         (1, 1, -0.00012)]
_RD_L = [(1, 0, 5260.52916), (1, 1, 105.94684), (1, 2, 2.45656), (3, 0, -0.81885), (1, 3, 0.05594),
         (3, 1, -0.05607), (0, 1, 0.01199), (3, 2, -0.00256), (1, 4, 0.00128), (0, 2, 0.00022),
         (2, 0, -0.00022), (5, 0, 0.00026)]


def rd_naar_wgs84(x: float, y: float) -> tuple[float, float]:
    """(breedte, lengte) in graden, op 6 decimalen (ca. 10 cm)."""
    dx, dy = (x - _RD_X0) * 1e-5, (y - _RD_Y0) * 1e-5
    phi = _PHI0 + sum(c * dx ** p * dy ** q for p, q, c in _RD_K) / 3600
    lam = _LAM0 + sum(c * dx ** p * dy ** q for p, q, c in _RD_L) / 3600
    return round(phi, 6), round(lam, 6)


LUCHTFOTO_WMS = "https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0"
LUCHTFOTO_LAAG = "Actueel_orthoHR"
LUCHTFOTO_HALF_M = 40  # 80 m breed: pand en straat zichtbaar (VA-62 crit. 1: 50-150 m)
LUCHTFOTO_PX = 640  # de grote foto in 'Open pand' (VA-62)
KAARTFOTO_PX = 200  # de kleine foto op elke kaart (VA-71 crit. 2: hooguit 240 px; Nova mat 9-11 KB)


def luchtfoto_sjabloon(px: int) -> str:
    """Het GetMap-adres van PDOK voor een vierkante foto van px pixels, met {b} voor de BBOX."""
    return (f"{LUCHTFOTO_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS={LUCHTFOTO_LAAG}"
            f"&STYLES=&CRS=EPSG:28992&BBOX={{b}}&WIDTH={px}&HEIGHT={px}&FORMAT=image/jpeg")


# De adressen per pand, met {b} (BBOX in RD) en {ll} (breedte,lengte). Ze staan één keer in de
# payload; per pand gaan alleen {b} en {ll} mee (VA-39 crit. 5: 500 panden houden de pagina licht).
# 'mini' is de kaartfoto (VA-71): dezelfde dienst, laag en BBOX als 'foto', alleen kleiner.
PLEK_SJABLOON = {
    "foto": luchtfoto_sjabloon(LUCHTFOTO_PX),
    "mini": luchtfoto_sjabloon(KAARTFOTO_PX),
    "maps": "https://www.google.com/maps/search/?api=1&query={ll}",
    "streetview": "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={ll}",
}


def pand_plek(p: dict) -> dict | None:
    """{'b': BBOX van 80 m rond het pand, 'll': 'breedte,lengte'}, of None zonder bruikbare x,y."""
    x, y = p.get("x"), p.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not x or not y:
        return None
    breedte, lengte = rd_naar_wgs84(x, y)
    h = LUCHTFOTO_HALF_M
    return {"b": f"{x - h:.1f},{y - h:.1f},{x + h:.1f},{y + h:.1f}", "ll": f"{breedte},{lengte}"}


def pand_locatie(p: dict) -> dict | None:
    """Luchtfoto-URL en links voor een pand met bruikbare x,y; anders None (VA-62 crit. 7)."""
    plek = pand_plek(p)
    if plek is None:
        return None
    breedte, lengte = (float(t) for t in plek["ll"].split(","))
    return {"lat": breedte, "lon": lengte,
            **{k: s.replace("{b}", plek["b"]).replace("{ll}", plek["ll"]) for k, s in PLEK_SJABLOON.items()}}


def detail_labels(aantal_groot: int | None = None) -> list[str]:
    """De labels van DETAIL_VELDEN, met het aantal grote gemeenten uit de data of config.yaml."""
    return [label.replace("{aantal}", nl_getal(aantal_groot)) for _, label, _ in DETAIL_VELDEN]


def pand_waarden(p: dict) -> list:
    """Per DETAIL_VELDEN de waarde als Nederlandse tekst; None = geen rij voor dit pand."""
    return [None if veld in ALLEEN_LANDELIJK and veld not in p else pand_waarde(soort, p.get(veld))
            for veld, _, soort in DETAIL_VELDEN]


def pand_detail(p: dict, aantal_groot: int | None = None) -> dict:
    """Alles voor de detailweergave van één pand: elk veld als Nederlandse tekst, plus locatie."""
    rijen = [{"k": k, "v": v} for k, v in zip(detail_labels(aantal_groot), pand_waarden(p)) if v is not None]
    return {"titel": p.get("hoofdadres") or LEEG, "rijen": rijen, "locatie": pand_locatie(p)}


class Tabel:
    """Elke waarde één keer, per pand alleen haar nummer (VA-39 crit. 5: 500 panden houden de pagina licht)."""

    def __init__(self) -> None:
        self.lijst: list = []
        self._nr: dict[str, int] = {}

    def nr(self, waarde) -> int:
        sleutel = json.dumps(waarde, ensure_ascii=False, sort_keys=True)
        if sleutel not in self._nr:
            self._nr[sleutel] = len(self.lijst)
            self.lijst.append(waarde)
        return self._nr[sleutel]


def pand_kort(p: dict, waarden: Tabel) -> dict:
    """
    pand_detail() zoals hij in de payload gaat: per label van PAYLOAD.velden het nummer van de
    waarde in PAYLOAD.waarden (null = geen rij), en de plek voor PAYLOAD.plek. De pagina vouwt
    hem bij openen uit tot precies pand_detail(); tests/test_dashboard_pand.py houdt die gelijk.
    """
    return {"titel": p.get("hoofdadres") or LEEG, "w": [waarden.nr(v) for v in pand_waarden(p)],
            "loc": pand_plek(p)}


# CBS: 'Utrecht (gemeente)' naast de provincie Utrecht. Alleen dit exacte achtervoegsel gaat weg;
# andere haakjes onderscheiden twee gemeenten met dezelfde naam en blijven staan (Lumi, VA-39).
GEMEENTE_TOEVOEGING = " (gemeente)"


def gemeente_naam(cbs: str | None) -> str:
    """De CBS-naam zoals de kaart en het filter hem tonen: 'Utrecht (gemeente)' -> 'Utrecht'."""
    if _leeg(cbs):
        return LEEG
    naam = str(cbs)
    return naam[: -len(GEMEENTE_TOEVOEGING)] if naam.endswith(GEMEENTE_TOEVOEGING) else naam


def kaartregel(p: dict, landelijk: bool) -> str:
    """De regel onder het adres op een kaart (VA-39: met de gemeente als die anders is)."""
    if not landelijk:
        return f"{p.get('postcode', '')} {p.get('woonplaats', '')} · BAG {p.get('bag_pand_id', '')}"
    plaats = f"{p.get('postcode', '')} {p.get('woonplaats', '')}"
    g = gemeente_naam(p.get("gemeente"))
    return plaats if g == p.get("woonplaats") else f"{plaats} · gemeente {g}"


# Korte tags voor de kwalificatie-signalen die de gebruiker belangrijk vindt.
# 'kind' stuurt de kleur: leeg = opvallend (amber), rest = groen.
QUAL_TAG = {
    "Buiten gebruik / leegstaand": ("🏚 leegstaand", "leeg"),
    "In verbouwing": ("🔧 in verbouwing", "bouw"),
    "Slecht of ontbrekend energielabel": ("⚡ slechte staat", "ok"),
}


def maak_leads(top: list[dict], landelijk: bool) -> tuple[list[dict], list[list], list]:
    """
    De kaarten van de pagina, met twee tabellen die elke waarde één keer bevatten: de regels van
    de score-opbouw ([label, punten, status, detail]; per pand in 'ob' hun nummers) en de
    waarden van de detailweergave (per pand in detail.w hun nummers).
    """
    criteria, waarden = Tabel(), Tabel()
    leads = []
    dp0 = gangbare_peildatum(top)
    for p in top:
        f = {k: round(v) for k, v in p["opp_per_functie"].items() if v}
        sig = [{"t": QUAL_TAG[it["label"]][0], "k": QUAL_TAG[it["label"]][1], "d": it["detail"]}
               for it in p["score_opbouw"] if it["label"] in QUAL_TAG and it["behaald"]]
        ob = [criteria.nr([it["label"], it["punten"], it["status"], it["detail"]]) for it in p["score_opbouw"]]
        lead = {
            "a": p["hoofdadres"].split(",")[0],
            "p": p["postcode"],
            "id": p["bag_pand_id"],
            "r": kaartregel(p, landelijk),
            "bj": p["bouwjaar"],
            "m2": round(p["totale_oppervlakte"]),
            "vbo": p["aantal_vbo"],
            "adr": p["aantal_adressen"],
            "cat": p["categorieen"],
            "f": f,
            "wp": p.get("woonplaats", ""),
            "s100": p["score100"],
            "raw": p["leadscore"],
            "sig": sig,
            "ob": ob,
            "detail": pand_kort(p, waarden),  # VA-61/62: alle velden, luchtfoto en kaartlinks
        }
        if landelijk:
            lead["g"] = gemeente_naam(p.get("gemeente"))  # waarop het gemeentefilter kiest
            lead["gg"] = 1 if p.get(nederland.IN_GROOT) == "ja" else 0  # filter Gebied (VA-68 crit. 3)
        # VA-90 bewaart per pand ook zijn pandcategorie en datapeildatum. Meestal is dat de eerste
        # categorie en de peildatum van de hele lijst (PAYLOAD.bewaar.dp); alleen een afwijking gaat mee.
        if p.get("pandcategorie") and p["pandcategorie"] != (p["categorieen"] or [None])[0]:
            lead["pc"] = p["pandcategorie"]
        if p.get("datapeildatum") != dp0:
            lead["dp"] = p.get("datapeildatum")
        leads.append(lead)
    return leads, criteria.lijst, waarden.lijst


# --------------------------------------------------------------- bewaren en verbergen (VA-90)
# Ayman: "every pand needs to have a bewaar or verberg button". Bewaard en verborgen staan alleen in
# de browser (localStorage), op dit apparaat, tot Q35 zegt waar het anders moet (VA-92). Er gaat
# niets de pagina uit, en niets in de pijplijn leest het: verbergen is geen leveren (VA-6), het
# verandert geen cijfer. Kopij: Lumi, design/copy-va90.md. Het script vult alleen {adres},
# {n}, {m} en {totaal} in; het maakt zelf geen zinnen.
BEWAAR_TEKST = {
    "bewaar": "Bewaar",
    "bewaard": "Bewaard",
    "verberg": "Verberg",
    "verborgen": "Verborgen",
    "terug.bewaard": "Druk om niet meer te bewaren",
    "terug.verborgen": "Druk om weer te tonen",
    "label.bewaard": "Bewaard",
    "label.verborgen": "Verborgen",
    # De toegankelijke naam van de knoppen (aria-label), per stand; aria-pressed blijft.
    "naam.bewaar": "Bewaar {adres}",
    "naam.bewaard": "Bewaard, druk om niet meer te bewaren: {adres}",
    "naam.verberg": "Verberg {adres}",
    "naam.verborgen": "Verborgen, druk om weer te tonen: {adres}",
    "apparaat": "Wat je bewaart of verbergt, staat alleen op dit apparaat, in deze browser. Op een ander apparaat "
                "zie je het niet, ook niet met dezelfde inlog. Wis je de browsergegevens, dan ben je het kwijt.",
    "apparaat.kort": "Alleen op dit apparaat, in deze browser. Een ander apparaat ziet het niet.",
    "status.bewaard": "{adres} is bewaard. Je vindt het terug bij Bewaarde panden.",   # VA-91, copy-va91.md §4
    "status.niet_bewaard": "{adres} is niet meer bewaard.",
    "status.verborgen": "{adres} is verborgen.",
    "status.terug": "{adres} staat weer op de werklijst.",
    "ongedaan": "Ongedaan maken",
    "aantal": "{n} panden verborgen",
    "aantal.een": "1 pand verborgen",
    "toon": "Toon verborgen panden",
    "toon.een": "Toon het verborgen pand",
    "toon.uit": "Verberg ze weer",
    "toon.uit.een": "Verberg het weer",
    "geen_opslag": "Deze browser laat het dashboard niets opslaan, dus Bewaar en Verberg werken hier niet. Dat "
                   "gebeurt bijvoorbeeld in een privévenster, of als opslag voor websites uit staat. Open het "
                   "dashboard in een gewoon venster om panden te bewaren. De rest van het dashboard werkt gewoon.",
    # Een lege werklijst omdat alles verborgen is (Lumi §7). m: de panden die de filters halen, verborgen meegeteld.
    "leeg.verborgen": "Je hebt alle {m} panden verborgen die bij deze filters passen.",
    "leeg.verborgen.een": "Het enige pand dat bij deze filters past, heb je verborgen.",
    "leeg.alles_verborgen": "Je hebt alle {totaal} panden van de werklijst van deze maand verborgen.",
    # De pagina Bewaarde panden (VA-91, Lumi, design/copy-va91.md, kolom GOEDGEKEURD). Het script vult alleen
    # {adres}, {n}, {m} en {datum} in.
    "pagina.titel": "Bewaarde panden",
    "pagina.zin": "De panden die je hebt bewaard, het laatst bewaarde bovenaan. Een pand blijft hier staan, "
                  "ook als het niet meer in de werklijst staat.",
    "pagina.meta": "{n} panden",
    "pagina.meta.een": "1 pand",
    "pagina.meta.weg": "{n} panden · {m} niet in deze werklijst",
    "pagina.meta.weg.een": "1 pand · niet in deze werklijst",
    "pagina.menu.n": "{n}",
    "pagina.menu.n.sr": ", {n} bewaard",
    "pagina.apparaat": "Deze lijst staat alleen op dit apparaat, in deze browser. Op een ander apparaat zie je hem "
                       "niet, ook niet met dezelfde inlog. Wis je de browsergegevens, dan ben je hem kwijt.",
    "pagina.sinds": "Bewaard op {datum}",
    "pagina.weg.label": "Niet in deze werklijst",
    "pagina.weg.zin": "Dit pand staat niet in de werklijst van deze maand. Score en categorie komen uit de "
                      "gegevens van {datum}.",
    "pagina.weg.zin.onbekend": "Dit pand staat niet in de werklijst van deze maand. Van wanneer de score en "
                               "categorie zijn, is onbekend.",
    "pagina.status.terug": "{adres} staat weer bij je bewaarde panden.",
    "pagina.leeg": "Je hebt nog geen panden bewaard. Druk bij een pand in de werklijst op Bewaar, dan staat het hier.",
    "pagina.geen_opslag": "Deze browser laat het dashboard niets opslaan, dus hier staan geen bewaarde panden. Dat "
                          "gebeurt bijvoorbeeld in een privévenster, of als opslag voor websites uit staat. Open het "
                          "dashboard in een gewoon venster om je bewaarde panden te zien.",
    "pagina.meer": "Toon alle {n} bewaarde panden",
    "pagina.minder": "Toon alleen de laatste 10",
}


def gangbare_peildatum(top: list[dict]) -> str | None:
    """De datapeildatum die de meeste panden van de lijst hebben (bij gelijk: de eerste in de lijst)."""
    tellen: dict = {}
    for p in top:
        tellen[p.get("datapeildatum")] = tellen.get(p.get("datapeildatum"), 0) + 1
    return max(tellen, key=tellen.get) if tellen else None


# VA-97, Ayman: "verborgen betekent alleen verborgen voor een maand". Een verborgen pand komt na
# werklijst.verberg_dagen dagen (config.yaml; 30 als het er niet staat) vanzelf terug op de werklijst,
# gerekend vanaf het moment van verbergen ('sinds'). Kopij: Lumi, copy-va97.md. Het script vult
# alleen {adres} en {datum} in. {datum} is de korte datum van _nl() (dag, korte maand, jaar; harde spaties): Python geeft
# MAANDEN en NBSP mee in PAYLOAD.bewaar, het script zet alleen dag, maand en jaar achter elkaar (VA-31).
VERBERG_DAGEN = 30
VERBERG_DUUR_TEKST = {
    # VA-6: een nieuwe maandrun kan de werklijst vervangen, dus geen belofte dat het terugkomt (Lumi).
    "status.verborgen": "{adres} is verborgen tot {datum}. Staat het dan nog op je werklijst, dan zie je het weer.",
    "label.verborgen": "Verborgen tot {datum}",
}


def lees_verberg_dagen(cfg: dict) -> tuple[int, list[str]]:
    """Hoeveel dagen een verborgen pand verborgen blijft, en een waarschuwing bij een onleesbare waarde."""
    w = cfg.get("werklijst") if isinstance(cfg.get("werklijst"), dict) else {}
    n = w.get("verberg_dagen")
    if n is None:
        return VERBERG_DAGEN, []
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return VERBERG_DAGEN, [f"werklijst.verberg_dagen: {n!r} is geen positief geheel getal; "
                               f"het dashboard neemt {VERBERG_DAGEN} dagen"]
    return n, []


def bewaar_blok(top: list[dict], dagen: int = VERBERG_DAGEN) -> dict:
    """PAYLOAD.bewaar: de teksten, de peildatum die een lead zonder eigen 'dp' heeft, en de verbergduur (VA-97)."""
    return {"tekst": BEWAAR_TEKST, "dp": gangbare_peildatum(top), "dagen": dagen, "duur": VERBERG_DUUR_TEKST,
            "maanden": list(MAANDEN), "nbsp": NBSP}


def met_duur_verborgen(payload: dict, cfg: dict) -> dict:
    """De verbergduur uit config.yaml in PAYLOAD.bewaar (VA-97); een onleesbare waarde wordt een waarschuwing."""
    dagen, let = lees_verberg_dagen(cfg)
    if let:   # de build drukt het af, net als de waarschuwingen van de planning
        payload = {**payload, "planning_waarschuwingen": (payload.get("planning_waarschuwingen") or []) + let}
    bw = payload.get("bewaar") or bewaar_blok([])
    return {**payload, "bewaar": {**bw, "dagen": dagen, "duur": VERBERG_DUUR_TEKST,
                                  "maanden": list(MAANDEN), "nbsp": NBSP}}


# De pagina Bewaarde panden (VA-91). Alleen in de landelijke bouw: Lumi's 'Niet in deze werklijst' is voor
# die bouw geschreven; de stadsbouw krijgt het deel pas met haar woorden ervoor (copy-va91.md §9).
BEWAARD = ("bewaard", BEWAAR_TEKST["pagina.titel"])
BEWAARD_EERST = 10   # zoveel nieuwste bewaarde panden staan er eerst; de rest achter 'Toon alle' (Lumi §6)
# Ayman 11-17: "bewaarde panden op een aparte speciale, coole, hightech pagina". De kop van die pagina is een
# navy paneel met de tellingen; de woorden hieronder zijn van de main session en wachten op Lumi.
BEWAARD_HELD_TEKST = {
    "sys": "Jouw selectie · alleen op dit apparaat",
    "tel.n": "Bewaard",
    "tel.in": "In de werklijst",
    "tel.weg": "Niet meer in de werklijst",
    "tel.score": "Gemiddelde score",
    "cat": "Verdeling over categorie A–E",
    "terug": "Terug naar de werklijst",
}
STER_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 2.6l2.9 '
            '5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z"/></svg>')


def bewaard_html(lijst: str) -> str:
    """De eigen pagina #bewaard (geen deel van de lange scroll); leeg voor een bouw zonder deze pagina."""
    if lijst != LIJST_LANDELIJK[0]:
        return ""
    t = {k: escape(v) for k, v in BEWAAR_TEKST.items()}
    h = {k: escape(v) for k, v in BEWAARD_HELD_TEKST.items()}
    tegels = "".join(f'<div class="bwp-tegel{" eerste" if i == 0 else ""}"><b id="bwpTel{k}">–</b><span>{h["tel." + s]}</span></div>'
                     for i, (k, s) in enumerate((("N", "n"), ("In", "in"), ("Weg", "weg"), ("Score", "score"))))
    return f'''
    <!-- BEWAARDE PANDEN (VA-91) -->
    <section class="deel pagina bwp-pagina" id="bewaard" aria-labelledby="t-bewaard" tabindex="-1">
      <header class="kop bwp-held">
        <span class="bwp-scan" aria-hidden="true"></span>
        <div class="kop-rij">
          <p class="kruimel">Levrai Vastgoed<span aria-hidden="true">/</span><b>{t["pagina.titel"]}</b></p>
          <span class="kop-meta" id="bwpMeta"></span>
        </div>
        <p class="bwp-sys"><i class="bwp-puls" aria-hidden="true"></i>{h["sys"]}</p>
        <div class="bwp-kopkern">
          <div class="bwp-embleem" aria-hidden="true"><span class="bwp-ring"></span>{STER_SVG}</div>
          <div>
            <h2 class="titel" id="t-bewaard">{t["pagina.titel"]}</h2>
            <p class="kop-zin">{t["pagina.zin"]}</p>
          </div>
        </div>
        <div class="bwp-tel">{tegels}</div>
        <div class="bwp-cat" id="bwpCat" hidden>
          <p>{h["cat"]}</p>
          <div class="bwp-staaf" id="bwpStaaf" aria-hidden="true"></div>
          <ul class="bwp-leg" id="bwpLeg"></ul>
        </div>
        <a class="bwp-terug" href="#{LIJST_LANDELIJK[0]}"><span aria-hidden="true">←</span>{h["terug"]}</a>
      </header>
      <div class="bwp" data-eerst="{BEWAARD_EERST}">
        <div class="bw-balk">
          <p class="bw-apparaat" id="bwpApparaat" hidden>{t["pagina.apparaat"]}</p>
          <div class="bw-status" id="bwBewaardStatus" role="status"></div>
        </div>
        <div class="wl-leeg" id="bwpLeeg" hidden><p></p></div>
        <ul class="bwp-lijst" id="bwpLijst"></ul>
        <button class="bw-toon" id="bwpMeer" type="button" hidden></button>
      </div>
    </section>
    <!-- einde BEWAARDE PANDEN -->'''
# --------------------------------------------------------------- einde bewaren en verbergen (VA-90)

# --------------------------------------------------------------- planning (VA-86)
# Ayman: "wanneer de nieuwe run weer is" en "bovenaan ... wanneer de volgende scrape plaatsvindt". Bovenaan
# het Kantoor, naast Bron en Peildatum: van welke maand de werklijst is, wanneer de volgende maandrun is
# en of er een dagelijkse controle draait. De maand komt uit de naam van het nieuwste werklijstbestand,
# het schema uit config.yaml (planning). Hier staat geen datum, dag of tijd: alles komt uit die twee.
# Zolang de run met de hand gaat, zegt de pagina dat; het woord 'automatisch' verschijnt alleen bij
# wijze: automatisch (dat zet pas het verhaal dat de run echt inplant, VA-77). Kopij: Ada, wacht op Lumi.
OUTPUT = BASE / "output"
# Sinds Aymans "maak het wel weer fancy, high tech, cool": een glazen paneel in de band, met een zacht
# kloppende stip en een dunne lijn door de maand. Die lijn staat op de dag dat de pagina gebouwd is (Python,
# date.today()), niet op een klok in de browser; bij de volgende build schuift hij op.
PLANNING_TEKST = {
    "paneel": "Planning van de datarun",
    "laatste": "Laatste run",
    "volgende": "Volgende run",
    "laatste.geen": "nog geen werklijst",
    "volgende.begin": "begin {maand}",
    "volgende.rond": "rond {dag} {maand}",
    "volgende.op": "{dag} {maand}",
    "volgende.dag": "op dag {dag} van de maand",
    "volgende.geen": "nog niet bekend",
    "wijze.handmatig": "handmatig",
    "wijze.automatisch": "automatisch",
    "controle.uit": "Dagelijkse controle nog niet actief",
    "controle.aan": "Dagelijkse controle: elke nacht om {tijd}",
    "lijn": "{pct} % van {maand} voorbij bij het bouwen van deze pagina",
    "zin": "Volgende run: {volgende}, {wijze}. {controle}.",
}
PLANNING_WIJZEN = ("handmatig", "automatisch")
PLANNING_DAG = range(1, 29)   # dag 1 tot en met 28: die bestaat in elke maand
WERKLIJST_NAAM = re.compile(r"werklijst_(?P<gebied>[a-z0-9]+)_(?P<maand>\d{4}-\d{2})\.csv")
TIJD = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def werklijst_maand(gebied_slug: str, map_: Path | None = None) -> str | None:
    """'JJJJ-MM' van het nieuwste output/werklijst_<gebied>_<JJJJ-MM>.csv, of None als er geen is."""
    maanden = sorted(m.group("maand") for pad in (map_ or OUTPUT).glob(f"werklijst_{gebied_slug}_*.csv")
                     if (m := WERKLIJST_NAAM.fullmatch(pad.name)) and m.group("gebied") == gebied_slug)
    return maanden[-1] if maanden else None


def volgende_maand(jjjj_mm: str) -> str:
    """'JJJJ-MM' -> de maand erna, als 'JJJJ-MM'."""
    j, m = (int(x) for x in jjjj_mm.split("-"))
    return f"{j + m // 12:04d}-{m % 12 + 1:02d}"


def lees_planning(cfg: dict) -> tuple[dict, list[str]]:
    """
    {'wijze', 'dag', 'controle', 'tijd'} uit config.yaml (planning), en de waarschuwingen. Een fout schema
    breekt de build niet (VA-86 crit. 7): dan geldt handmatig, zonder dag, en geen dagelijkse controle, en
    de waarschuwing noemt de sleutel.
    """
    let = []
    p = cfg.get("planning")
    if not isinstance(p, dict):
        let.append("planning ontbreekt in config.yaml; het dashboard toont: handmatig, geen dagelijkse controle")
        p = {}
    mr = p.get("maandrun") if isinstance(p.get("maandrun"), dict) else {}
    dc = p.get("dagcontrole") if isinstance(p.get("dagcontrole"), dict) else {}
    wijze, dag = mr.get("wijze"), mr.get("dag")
    if wijze not in PLANNING_WIJZEN:
        let.append(f"planning.maandrun.wijze: onbekende waarde {wijze!r} (kies {' of '.join(PLANNING_WIJZEN)}); "
                   "het dashboard toont handmatig")
        wijze, dag = PLANNING_WIJZEN[0], None
    if dag is not None and (isinstance(dag, bool) or not isinstance(dag, int) or dag not in PLANNING_DAG):
        let.append(f"planning.maandrun.dag: {dag!r} is geen dag van {PLANNING_DAG.start} tot en met "
                   f"{PLANNING_DAG.stop - 1}; het dashboard toont handmatig, zonder dag")
        wijze, dag = PLANNING_WIJZEN[0], None
    if wijze == "automatisch" and dag is None:
        let.append("planning.maandrun.dag ontbreekt: bij wijze automatisch hoort een dag; het dashboard toont handmatig")
        wijze = PLANNING_WIJZEN[0]
    actief, tijd = dc.get("actief"), dc.get("tijd")
    if actief not in (True, False, None):
        let.append(f"planning.dagcontrole.actief: {actief!r} is geen true of false; het dashboard toont: nog niet actief")
        actief = False
    if tijd is not None and not (isinstance(tijd, str) and TIJD.fullmatch(tijd.strip())):
        let.append(f"planning.dagcontrole.tijd: {tijd!r} is geen tijd als \"UU:MM\" (zet hem tussen aanhalingstekens); "
                   "het dashboard toont: nog niet actief")
        tijd = None
    controle = bool(actief) and tijd is not None
    return {"wijze": wijze, "dag": dag, "controle": controle, "tijd": tijd.strip() if controle else None}, let


def maand_voortgang(jjjj_mm: str, dag: date) -> int:
    """Hoeveel procent van de maand 'JJJJ-MM' voorbij is op 'dag' (0 tot en met 100)."""
    j, m = (int(x) for x in jjjj_mm.split("-"))
    vj, vm = (int(x) for x in volgende_maand(jjjj_mm).split("-"))
    begin, eind = date(j, m, 1), date(vj, vm, 1)
    return max(0, min(100, round(100 * (dag - begin).days / (eind - begin).days)))


def planning_teksten(cfg: dict, gebied_slug: str, map_: Path | None = None,
                     vandaag: date | None = None) -> tuple[dict, list[str]]:
    """
    Wat het runpaneel toont en de zin van de kantoormanager (VA-86 crit. 2, 3, 5, 6): {'laatste', 'volgende',
    'wijze', 'controle', 'voortgang', 'lijn', 'zin'}, plus de waarschuwingen voor de build. 'automatisch' staat er
    alleen bij wijze: automatisch.
    """
    plan, let = lees_planning(cfg)
    maand = werklijst_maand(gebied_slug, map_)
    T = PLANNING_TEKST
    na = maand_voluit(volgende_maand(maand)) if maand else None
    if plan["wijze"] == "automatisch":
        volgende = T["volgende.op"].format(dag=plan["dag"], maand=na) if na else T["volgende.dag"].format(dag=plan["dag"])
    elif not na:
        volgende = T["volgende.geen"]
    elif plan["dag"] is not None:
        volgende = T["volgende.rond"].format(dag=plan["dag"], maand=na)
    else:
        volgende = T["volgende.begin"].format(maand=na)
    wijze = T["wijze." + plan["wijze"]]
    controle = T["controle.aan"].format(tijd=plan["tijd"]) if plan["controle"] else T["controle.uit"]
    voortgang = maand_voortgang(maand, vandaag or date.today()) if maand else None
    return {"laatste": maand_voluit(maand) if maand else T["laatste.geen"], "volgende": volgende, "wijze": wijze,
            "automatisch": plan["wijze"] == "automatisch", "controle": controle, "voortgang": voortgang,
            "lijn": T["lijn"].format(pct=voortgang, maand=maand_voluit(maand)) if maand else "",
            "zin": T["zin"].format(volgende=volgende, wijze=wijze, controle=controle)}, let


def planning_paneel(pl: dict | None) -> str:
    """Het glazen runpaneel bovenaan de band (onder Bron en Peildatum); zonder planning niets."""
    if not pl:
        return ""
    T = PLANNING_TEKST
    stip = "run-stip automatisch" if pl["automatisch"] else "run-stip"
    lijn = (f'<div class="run-lijn" role="img" aria-label="{escape(pl["lijn"])}"><i style="width:{pl["voortgang"]}%">'
            '</i></div>') if pl["voortgang"] is not None else ""
    return (f'\n        <div class="run-paneel" role="group" aria-label="{escape(T["paneel"])}">'
            f'<div class="run-rij"><span class="run-item"><span class="{stip}" aria-hidden="true"></span>'
            f'<span class="run-lab">{escape(T["laatste"])}</span> <b>{escape(pl["laatste"])}</b></span>'
            f'<span class="run-item"><span class="run-lab">{escape(T["volgende"])}</span> <b>{escape(pl["volgende"])}</b> '
            f'<span class="run-wijze">{escape(pl["wijze"])}</span></span></div>'
            f'{lijn}<p class="run-noot">{escape(pl["controle"])}</p></div>')


def met_planning(payload: dict, cfg: dict, vandaag: date | None = None) -> dict:
    """De planning in de payload, en de zin erachter bij wat de kantoormanager zegt (crit. 6)."""
    pl, let = planning_teksten(cfg, slug(payload["gebied"]), vandaag=vandaag)
    tekst = (payload.get("kantoor") or {}).get("tekst") or {}
    if tekst.get("chef"):
        tekst["chef"] = {**tekst["chef"], "zin": f"{tekst['chef']['zin']} {pl['zin']}"}
    return {**payload, "planning": pl, "planning_waarschuwingen": let}
# --------------------------------------------------------------- einde planning (VA-86)

# --------------------------------------------------------------- slot op de werklijst (VA-96)
# Ayman: "een lock ... dat er maar 5 panden getoond worden en die andere achter de verborgen slot scherm met
# text (data link aan zetten)", omdat hij eerst betaling wil. Een visueel slot, op zijn besluit ("statisch
# afschermen is genoeg"): de gegevens van alle panden blijven in de broncode van de pagina staan. Met
# werklijst.vrij_zichtbaar in config.yaml zijn alleen de eerste n panden van de werklijst te zien (in de
# volgorde van de run); de rest staat achter één slotblok. Uit of afwezig: de pagina is precies als zonder
# dit verhaal. Geen cijfer verandert: de kerncijfers, de band en zijn 500 stippen blijven hetzelfde.
# Kopij: Ada, wacht op Lumi.
SLOT_TEKST = {
    # Ayman: geen aantal naast de werklijst in beeld. De kop noemt het aantal niet; de schermlezer hoort het
    # echte aantal wel (een visueel verborgen tekst), net als bij de band.
    "titel": "De rest van je werklijst staat achter het slot",
    "sr": "{n} panden staan achter het slot",
    "sr.een": "1 pand staat achter het slot",
    "regel": "Zet de datakoppeling aan om alle panden van de werklijst te zien.",
    "telling.alle": "De {n} zichtbare panden",
    "telling": "{n} van de {totaal} zichtbare panden",
}


def lees_slot(cfg: dict) -> tuple[int | None, list[str]]:
    """Hoeveel panden vrij zichtbaar zijn (None = geen slot), en een waarschuwing bij een onleesbare waarde."""
    w = (cfg.get("werklijst") or {}) if isinstance(cfg.get("werklijst"), (dict, type(None))) else {}
    n = w.get("vrij_zichtbaar")
    if n is None or n is False:
        return None, []
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return None, [f"werklijst.vrij_zichtbaar: {n!r} is geen positief geheel getal; het slot staat uit"]
    return n, []


def met_slot(payload: dict, cfg: dict) -> dict:
    """
    Met het slot op: PAYLOAD.slot {'n', 'op_slot', 'tekst'} en de telling van het filterpaneel over de n
    zichtbare panden (crit. 4). Zonder slot, of als de werklijst er niet meer heeft: de payload ongewijzigd.
    """
    n, let = lees_slot(cfg)
    if let:   # de build drukt het af, net als de waarschuwingen van de planning
        payload = {**payload, "planning_waarschuwingen": (payload.get("planning_waarschuwingen") or []) + let}
    totaal = len(payload.get("leads") or [])
    if n is None or totaal <= n:
        return payload
    op_slot = totaal - n
    tekst = {"titel": SLOT_TEKST["titel"],
             "sr": (SLOT_TEKST["sr.een"] if op_slot == 1 else SLOT_TEKST["sr"].format(n=nl_getal(op_slot))),
             "regel": SLOT_TEKST["regel"]}
    filt = payload.get("filter")
    if filt and filt.get("tekst"):
        filt = {**filt, "tekst": {**filt["tekst"], "alle": SLOT_TEKST["telling.alle"].format(n=nl_getal(n)),
                                  "telling": SLOT_TEKST["telling"].replace("{totaal}", nl_getal(n))}}
    return {**payload, "filter": filt, "slot": {"n": n, "op_slot": op_slot, "tekst": tekst}}


SLOT_SCHIM = 3   # zoveel lege kaarten achter het slot (vorm, geen inhoud)


def slot_html(s: dict | None) -> str:
    """Het slotblok na de vrije kaarten: lege kaarten, een slot en één tekst. Geen knop, niets om op te tabben."""
    if not s:
        return ""
    schim = "".join('<div class="slot-kaart"><i></i><i></i><i></i><i></i></div>' for _ in range(SLOT_SCHIM))
    slot = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">'
            '<rect x="5" y="10.5" width="14" height="10" rx="2.2" fill="currentColor"/>'
            '<path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>')
    return ('\n        <!-- SLOT (VA-96) -->\n'
            f'        <div class="slot-blok" id="slotBlok"><div class="grid slot-schim" aria-hidden="true">{schim}</div>'
            f'<div class="slot-paneel"><span class="slot-icoon">{slot}</span>'
            f'<p class="slot-tekst"><b><span aria-hidden="true">{escape(s["tekst"]["titel"])}.</span>'
            f'<span class="vh">{escape(s["tekst"]["sr"])}.</span></b> {escape(s["tekst"]["regel"])}</p></div></div>'
            '\n        <!-- einde SLOT -->')
# --------------------------------------------------------------- einde slot op de werklijst (VA-96)


def lijst_feiten(top: list[dict]) -> list[dict]:
    """Bereik van score en bouwjaar en de gemiddelde oppervlakte van de panden op de pagina."""
    scores = [p["score100"] for p in top]
    bjs = [p["bouwjaar"] for p in top]
    return [
        {"k": "Score-index (/100)", "val": f"{min(scores)}–{max(scores)}" if top else "onbekend"},
        {"k": "Bouwjaren", "val": f"{min(bjs)}–{max(bjs)}" if top else "onbekend"},
        {"k": "Gem. oppervlakte",
         "val": f"{nl_getal(sum(p['totale_oppervlakte'] for p in top) / len(top))} m²" if top else "onbekend"},
    ]


# --------------------------------------------------------------- werklijstfilters (VA-39, VA-68)
# Lumi's kopij VA-39 en design/filters.html (VA-68). Alleen gemeenten die op de werklijst staan;
# per groep op alfabet.
FILTER_TEKST = {
    "label": "Gemeente",
    "alle": "Alle gemeenten ({n})",
    "optie": "{gemeente} ({aantal})",
    "groep.groot": "De {aantal_groot} grootste gemeenten",
    "groep.elders": "Elders in Nederland",
}
# De zinnen van het filterpaneel. Hoeveel panden een combinatie geeft, weet Python niet vooraf:
# het script vult alleen {n} (en {aantal} bij een gemeente) in, met nl(), en kiest de vorm voor
# 1 en 0 uit wat hier staat (Lumi, bouwnotitie 2). {totaal} vult lijst_tekst() hier al in.
LIJST_TEKST = {
    "knop": "Filters",
    "actief": " ({n} actief)",
    "telling.alle": "Alle {totaal} panden",
    "telling": "{n} van {totaal} panden",
    "toon": "Toon {n} panden",
    "toon.een": "Toon 1 pand",
    "toon.nul": "Sluit filters",
    "categorie": "Categorie",
    "signaal": "Signaal",
    "gebied": "Gebied",
    "optie.aantal": " panden",
    "chips": "Actieve filters",
    "chip.gemeente": "Gemeente {gemeente}",
    "chip.categorie": "Categorie {letter}",
    "chip.naam": "Verwijder filter: {chip}",
    "wis": "Wis alle filters",
    "leeg": "Geen enkel pand op de werklijst van deze maand past bij deze filters. Verwijder hierboven "
            "een filter, of wis ze allemaal.",
}
# Signaal: (waarde in het adres, sig.k van de kaart, label). Gefilterd op de sleutel, nooit op de tekst.
SIGNALEN = [("leeg", "leeg", "Leegstaand"), ("verbouwing", "bouw", "In verbouwing")]
GEBIEDEN = ("groot", "elders")  # waarde in het adres; label uit FILTER_TEKST['groep.*']

# De getalfilters (VA-69) en het sorteren (VA-70), Lumi's kopij uit design/filters.html. Grenzen tellen
# mee. Een jaartal gaat nooit door de puntopmaak: 1939, niet 1.939 ('jaar': het script laat het onbewerkt),
# en er staat geen 'jaar' achter het veld (Lumi: "1939 jaar" is een leeftijd).
BEREIK_TEKST = {
    "hint": "Op de werklijst: {min}–{max}",
    "van": "van",
    "vanaf": "vanaf",
    "tm": "tot en met",
    "uit": " Dit filter telt nu niet mee.",
    "omgekeerd": "Van is hoger dan tot en met.",
    "chip.van.tm": "{naam} {van}–{tm}{eenheid}",
    "chip.van": "{naam} vanaf {van}{eenheid}",
    "chip.tm": "{naam} tot en met {tm}{eenheid}",
}
# k: sleutel in het paneel; veld: op de kaart (LEADS); url: adresparameters (van, tot en met).
# Score heeft alleen 'vanaf' en een bovengrens van de index (/100).
BEREIKEN = [
    {"k": "score", "veld": "s100", "label": "Score-index (/100)", "url": ["min_score"], "max": 100,
     "chip": "Score vanaf {van}", "fout": "Vul een score van 0 tot en met 100 in."},
    {"k": "bj", "veld": "bj", "label": "Bouwjaar", "url": ["bouwjaar_van", "bouwjaar_tm"], "jaar": True,
     "naam": "Bouwjaar", "eenheid": "", "fout": "Vul een jaartal in, bijvoorbeeld 1939."},
    {"k": "m2", "veld": "m2", "label": "Oppervlakte (m²)", "url": ["m2_van", "m2_tm"],
     "naam": "Oppervlakte", "eenheid": " m²", "fout": "Vul een heel getal in, bijvoorbeeld 250."},
    {"k": "vbo", "veld": "vbo", "label": "Aantal VBO's", "url": ["vbo_van", "vbo_tm"],
     "naam": "Aantal VBO's", "eenheid": "", "fout": "Vul een heel getal in, bijvoorbeeld 4."},
    {"k": "adr", "veld": "adr", "label": "Aantal adressen", "url": ["adressen_van", "adressen_tm"],
     "naam": "Aantal adressen", "eenheid": "", "fout": "Vul een heel getal in, bijvoorbeeld 4."},
]
SORTEER_TEKST = {"sorteer": "Sorteer op", "volgorde": "Volgorde"}
# (waarde in het adres, veld op de kaart, label, standaardrichting, {richting: label}). De standaard
# staat eerst; zonder 'sorteer' in het adres is het score, hoogste eerst: de volgorde van de werklijst.
SORTEREN = [
    ("score", "s100", "Score-index", "af", {"af": "Hoogste eerst", "op": "Laagste eerst"}),
    ("bouwjaar", "bj", "Bouwjaar", "op", {"op": "Oudste eerst", "af": "Nieuwste eerst"}),
    ("oppervlakte", "m2", "Oppervlakte", "af", {"af": "Grootste eerst", "op": "Kleinste eerst"}),
]


def lijst_tekst(totaal: int) -> dict:
    """Wat het script van het paneel invult, met het totaal van de werklijst al ingevuld."""
    t, tot = LIJST_TEKST, nl_getal(totaal)
    return {"actief": t["actief"], "alle": t["telling.alle"].format(totaal=tot),
            "telling": t["telling"].replace("{totaal}", tot), "toon": t["toon"], "toonEen": t["toon.een"],
            "toonNul": t["toon.nul"], "gemAlle": FILTER_TEKST["alle"], "gemOptie": FILTER_TEKST["optie"],
            "chipGemeente": t["chip.gemeente"], "chipNaam": t["chip.naam"], "wis": t["wis"],
            "omgekeerd": BEREIK_TEKST["omgekeerd"] + BEREIK_TEKST["uit"]}


def bereik_getal(b: dict, v) -> str:
    """Een grens zoals de pagina hem toont: een jaartal onbewerkt, de rest met de duizendtallenpunt."""
    return str(v) if b.get("jaar") else nl_getal(v)


def bereik_filter(leads: list[dict]) -> dict:
    """
    De getalvelden en het sorteren voor het script (VA-69, VA-70): per veld de hint met wat er op de
    lijst van deze maand staat, de foutmelding en de chipzinnen met naam en eenheid al ingevuld. Het
    script vult alleen {van} en {tm} in, een jaartal onbewerkt ('jaar').
    """
    t, bereik = BEREIK_TEKST, []
    for b in BEREIKEN:
        waarden = [d[b["veld"]] for d in leads if d.get(b["veld"]) is not None]
        hint = (t["hint"].format(min=bereik_getal(b, min(waarden)), max=bereik_getal(b, max(waarden)))
                if waarden else "")
        if "chip" in b:
            chips = {"van": b["chip"]}
        else:
            vul = lambda s: s.replace("{naam}", b["naam"]).replace("{eenheid}", b["eenheid"])  # noqa: E731
            chips = {"vanTm": vul(t["chip.van.tm"]), "van": vul(t["chip.van"]), "tm": vul(t["chip.tm"])}
        bereik.append({"k": b["k"], "veld": b["veld"], "url": b["url"], "jaar": bool(b.get("jaar")),
                       "max": b.get("max"), "label": b["label"], "hint": hint, "chips": chips,
                       "fout": b["fout"] + t["uit"]})
    sorteer = {w: {"veld": veld, "label": label, "std": std, "opties": [[r, namen[r]] for r in namen]}
               for w, veld, label, std, namen in SORTEREN}
    return {"bereik": bereik, "sorteer": sorteer}


def _alfabet(naam: str) -> str:
    """'s-Gravenhage staat bij de s, niet vóór de A."""
    return naam.lstrip("'").casefold()


def gemeente_filter(werklijst: list[dict], aantal_groot: int | None) -> dict:
    """
    De keuzes van de filters: per groep (de grote gemeenten, de rest) elke gemeente op de lijst met
    hoeveel panden, de twee gebieden en de teksten voor het script. De tellingen hier gelden voor de
    hele lijst; zodra een ander filter aan staat, telt het script opnieuw (VA-68 crit. 6).
    """
    n = len(werklijst)
    tellen: dict[tuple[str, bool], int] = {}
    for p in werklijst:
        sleutel = (gemeente_naam(p.get("gemeente")), p.get(nederland.IN_GROOT) == "ja")
        tellen[sleutel] = tellen.get(sleutel, 0) + 1
    gebied = {"groot": FILTER_TEKST["groep.groot"].format(aantal_groot=nl_getal(aantal_groot)),
              "elders": FILTER_TEKST["groep.elders"]}
    groepen = []
    for groot, label in ((True, gebied["groot"]), (False, gebied["elders"])):
        namen = sorted((g for g, gr in tellen if gr == groot), key=_alfabet)
        if not namen:
            continue
        opties = [{"naam": g, "aantal": tellen[(g, groot)],
                   "tekst": FILTER_TEKST["optie"].format(gemeente=g, aantal=nl_getal(tellen[(g, groot)]))}
                  for g in namen]
        groepen.append({"label": label, "opties": opties})
    return {"label": FILTER_TEKST["label"], "alle": FILTER_TEKST["alle"].format(n=nl_getal(n)),
            "groepen": groepen, "gebied": [[w, gebied[w]] for w in GEBIEDEN], "tekst": lijst_tekst(n)}


def filter_html(f: dict | None, fotobron: str | None = None) -> str:
    """
    Wat boven de kaarten staat (Lumi, design/filters.html bouwnotitie 1): de balk met de knop
    Filters, de telling en het sorteren (VA-70), het paneel met de getalvelden (VA-69), de actieve
    filters, de bronregel van de kaartfoto's en de lege lijst. Zonder filter (Delft) alleen de bronregel.
    """
    e = lambda t: escape(str(t), quote=True)  # noqa: E731
    bron = f'<p class="wl-bron">{e(fotobron)}</p>' if fotobron else ""
    if not f:
        return bron
    t = LIJST_TEKST

    def optie(groep: str, waarde: str, naam: str, chip: str, kleur: str | None = None) -> str:
        merk = (f'<i class="wl-kleur" style="background:{kleur}" aria-hidden="true"></i>'
                f'<b class="wl-letter">{waarde}</b>') if kleur else ""
        return (f'<label class="wl-optie" data-groep="{groep}" data-waarde="{waarde}" data-chip="{e(chip)}">'
                f'<input type="checkbox" name="wl-{groep}" value="{waarde}">{merk}'
                f'<span class="wl-naam">{e(naam)}</span><span class="wl-n"><span class="wl-getal"></span>'
                f'<span class="vh">{e(t["optie.aantal"])}</span></span></label>')

    def groep(naam: str, opties: str, heel: bool = False) -> str:
        return (f'<fieldset class="wl-groep{" wl-heel" if heel else ""}"><legend>{e(naam)}</legend>'
                f'<div class="wl-opties">{opties}</div></fieldset>')

    cats = "".join(optie("cat", k, CATEGORIE_NAAM[k], t["chip.categorie"].format(letter=k), CATEGORIE_KLEUR[k])
                   for k in "ABCDE")
    sigs = "".join(optie("sig", w, label, label) for w, _, label in SIGNALEN)
    gebs = "".join(optie("geb", w, label, label) for w, label in f["gebied"])
    gemeenten = "".join(
        f'<optgroup label="{e(g["label"])}">' + "".join(
            f'<option value="{e(o["naam"])}">{e(o["tekst"])}</option>' for o in g["opties"]) + "</optgroup>"
        for g in f["groepen"])

    def bereik(b: dict) -> str:
        # type="text" en geen type="number": "abc" moet een melding kunnen geven (VA-69 crit. 5).
        i, bt = f'wl-{b["k"]}', BEREIK_TEKST
        veld = lambda x, label: (  # noqa: E731
            f'<div><label for="{i}-{x}">{e(label)}</label><input id="{i}-{x}" data-k="{b["k"]}" data-x="{x}" '
            'type="text" inputmode="numeric" autocomplete="off" enterkeyhint="done" maxlength="7" '
            f'aria-describedby="{i}-hint {i}-fout"></div>')
        enkel = len(b["url"]) == 1
        velden = veld("van", bt["vanaf"]) if enkel else veld("van", bt["van"]) + veld("tm", bt["tm"])
        return (f'<fieldset class="wl-bereik{" enkel" if enkel else ""}" data-k="{b["k"]}"><legend>{e(b["label"])}'
                f'</legend><p class="wl-hint" id="{i}-hint">{e(b["hint"])}</p><div class="wl-invoer">{velden}</div>'
                f'<p class="wl-fout" id="{i}-fout" hidden></p></fieldset>')

    bereiken = "".join(bereik(b) for b in f.get("bereik") or [])
    bereiken = f'<div class="wl-bereiken">{bereiken}</div>' if bereiken else ""
    s = f.get("sorteer")
    sorteer = ('<div class="wl-sorteer"><div class="wl-veld"><label for="wl-sorteer">'
               f'{e(SORTEER_TEKST["sorteer"])}</label><select id="wl-sorteer">'
               + "".join(f'<option value="{w}">{e(x["label"])}</option>' for w, x in s.items())
               + f'</select></div><div class="wl-veld"><label for="wl-volgorde">{e(SORTEER_TEKST["volgorde"])}'
               '</label><select id="wl-volgorde">'
               + "".join(f'<option value="{r}">{e(n)}</option>' for r, n in next(iter(s.values()))["opties"])
               + '</select></div></div>') if s else ""
    return ('<div class="wl-balk"><button type="button" class="wl-knop" id="wl-knop" aria-expanded="false" '
            'aria-controls="wl-paneel"><span class="wl-ico" aria-hidden="true"></span>'
            f'<span>{e(t["knop"])}</span><span class="wl-aantal" aria-hidden="true" hidden></span>'
            '<span class="vh wl-actief"></span><span class="wl-pijl" aria-hidden="true"></span></button>'
            f'<p class="wl-telling" aria-live="polite">{e(f["tekst"]["alle"])}</p>{sorteer}</div>'
            '<div class="wl-paneel" id="wl-paneel" role="group" aria-labelledby="wl-knop" hidden>'
            f'<div class="wl-keuzes">{groep(t["categorie"], cats, heel=True)}{groep(t["signaal"], sigs)}'
            f'<div class="wl-veld wl-gem"><label for="gemeente">{e(f["label"])}</label>'
            f'<select id="gemeente"><option value="">{e(f["alle"])}</option>{gemeenten}</select></div>'
            f'{groep(t["gebied"], gebs)}</div>{bereiken}'
            '<div class="wl-paneelvoet"><button type="button" class="wl-toon"></button></div></div>'
            f'<div class="wl-chips" role="group" aria-label="{e(t["chips"])}" hidden></div>{bron}'
            f'<div class="wl-leeg" hidden><p>{e(t["leeg"])}</p>'
            f'<button type="button" class="wl-wis">{e(t["wis"])}</button></div>')


# De kleine luchtfoto op elke kaart (VA-71, Lumi's kopij). De bronregel staat één keer boven de lijst.
KAARTFOTO_TEKST = {
    "alt": "Luchtfoto van {adres}",
    "mislukt": "Luchtfoto kon niet laden",
    "geen": "Locatie onbekend",
    "bron": "Luchtfoto's: Beeldmateriaal.nl, via PDOK · open data (CC BY 4.0).",
}


def kaartfoto_tekst() -> dict:
    """De teksten die het script op een kaart zet; de bronregel staat al in de HTML."""
    return {k: v for k, v in KAARTFOTO_TEKST.items() if k != "bron"}


CATEGORIE_NAAM = {"A": "Winkel + wonen", "B": "Bedrijf/kantoor + wonen",
                  "C": "Klein wooncomplex", "D": "Groot oud pand", "E": "Afwijkende combinatie"}
CATEGORIE_KLEUR = {"A": "var(--s1)", "B": "var(--s2)", "C": "var(--s3)", "D": "var(--s4)", "E": "var(--s5)"}
BRON_PIL = "Bron: PDOK BAG WFS v2_0"  # tot VA-39 vast in de kop; nu uit het veld 'bron' van de panden


def bron_pil(panden: list[dict], standaard: str = BRON_PIL) -> str:
    """'Bron: <veld bron van de panden>' zonder het bestand tussen haakjes (Lumi, VA-39)."""
    for p in panden:
        b = str(p.get("bron") or "").split(" (")[0].strip()
        if b:
            return f"Bron: {b}"
    return standaard


def pagina(lijst: str, titel: str, feiten_titel: str, feiten_cap: str, bronpil: str) -> dict:
    """De vaste teksten van de pagina die per gebied verschillen; render() plaatst ze."""
    return {"lijst": lijst, "titel": titel, "feiten.titel": feiten_titel, "feiten.cap": feiten_cap,
            "bronpil": bronpil}


def bouw_payload() -> dict:
    cfg = load_config()
    if nederland.is_nederland(cfg):
        return met_duur_verborgen(met_slot(met_planning(bouw_payload_landelijk(cfg), cfg), cfg), cfg)
    return met_duur_verborgen(met_slot(met_planning(bouw_payload_gebied(cfg), cfg), cfg), cfg)


def bouw_payload_gebied(cfg: dict) -> dict:
    """Een stad of provincie met al zijn panden in panden_<gebied>.json (Delft, de regressiebasis)."""
    label, _ = resolve(cfg)
    panden_pad = DATA / f"panden_{slug(label)}.json"
    gelezen, panden_reden = lees_panden(panden_pad)
    panden = gelezen or []
    if gelezen is None:
        bron, bron_reden = None, panden_reden
    else:
        bron, bron_reden = lees_bron(panden_pad)
    act = binnen_a_e(panden)
    # Binnen gelijke score een zinnige volgorde: meer woningen, dan ouder, dan groter.
    top = sorted(act, key=lambda p: (
        -p["score100"],
        -p["aantal_per_functie"].get("woon", 0),
        p["bouwjaar"],
        -p["totale_oppervlakte"],
        p["bag_pand_id"],
    ))[:20]

    tot_vbo = sum(p["aantal_vbo"] for p in panden)
    uitgesloten = sum(1 for p in panden if p["uitgesloten"])
    # Drempel uit config.yaml (briefing sectie 4): geen magisch getal in de code.
    drempel = cfg["drempels"]["score_min_voor_werklijst"]
    werklijst = werklijst_aantal(act, drempel)

    def tal(n: int) -> str:
        """Duizendtallen met een punt; zonder panden-bestand 'onbekend', geen 0."""
        return nl_getal(n) if gelezen is not None else "onbekend"

    kpi = [
        {"v": tal(tot_vbo), "l": "Verblijfsobjecten ingelezen",
         "h": f"100,0% dekking van {label}" if gelezen is not None else escape(panden_reden),
         "c": "var(--s1)"},
        {"v": tal(len(panden)), "l": "Unieke BAG-panden",
         "h": tal(uitgesloten) + " uitgesloten", "c": "var(--s3)"},
        {"v": tal(len(act)), "l": "Binnen categorie A–E",
         "h": "de mastervoorraad", "c": "var(--s2)"},
        {"v": tal(werklijst), "l": f"Werklijst · score ≥ {drempel}",
         "h": "ruim meerdere maanden voorraad", "c": "var(--s5)"},
    ]
    cats = [{"k": k, "name": CATEGORIE_NAAM[k], "n": sum(1 for p in act if k in p["categorieen"]),
             "c": CATEGORIE_KLEUR[k]} for k in "ABCDE"]

    # Zonder panden in de proefselectie bestaat geen bereik of gemiddelde: 'onbekend'.
    bereik = lijst_feiten(top)
    facts = [
        {"k": "Panden in proefselectie", "val": str(len(top)) if gelezen is not None else "onbekend"},
        *bereik[:2],
        {"k": "Oudste pand", "val": str(min(p["bouwjaar"] for p in top)) if top else "onbekend"},
        *bereik[2:],
        {"k": "Doelgebied", "val": label},
    ]
    # Welke ingest dit resultaat voedt (VA-3): bestand en ophaaldatum per woonplaats.
    if bron is None:
        facts.append({"k": "Bron-snapshot", "val": "onbekend",
                      "tip": escape(bron_reden)})
    else:
        for b in bron:
            k = "Bron-snapshot" if len(bron) == 1 else f"Bron-snapshot {b.get('woonplaats', '')}"
            facts.append({"k": escape(k),
                          "val": escape(f"{b['bestand']} · {nl_datum(b.get('ophaaldatum'))}"),
                          "tip": escape(bron_regels([b])[0])})

    leads, criteria, waarden = maak_leads(top, landelijk=False)
    aantal_groot = (cfg.get("drempels") or {}).get("aantal_grote_gemeenten")
    budget = cfg["score"].get("schaal_max", 26)
    return {"kpi": kpi, "cats": cats, "facts": facts, "leads": leads,
            "velden": detail_labels(aantal_groot), "criteria": criteria, "waarden": waarden, "plek": PLEK_SJABLOON,
            "filter": None, "kaartfoto": kaartfoto_tekst(), "bewaar": bewaar_blok(top),
            "budget": budget, "gebied": label, "koppen": koppen(label, drempel, len(leads)),
            "pagina": pagina("proefresultaat", f"Levrai · Pandenselectie Dashboard — {label}",
                             "Proefselectie in cijfers",
                             "De 20 hoogst scorende panden — de controlevraag uit de briefing",
                             bron_pil(top or panden[:1])),
            "bron": bron, "bron_regels": bron_regels(bron), "bron_reden": bron_reden,
            "peildatum": peildatum(bron), "peildatum_tip": peildatum_tip(bron, bron_reden),
            "kantoor": kantoor(label, bron, gelezen, len(leads) if gelezen is not None else None,
                               cfg)}


def bronbestand(bron: list[dict], data: Path) -> str:
    """
    Het bestand van PDOK achter een snapshot: de GeoPackage die ingest_gpkg.py las (VA-34 zet
    die als 'bron' in de meta-tabel; alleen-lezen geopend). Zonder snapshot op deze machine
    het bestand uit .bron.json, zodat er nooit een verzonnen naam staat.
    """
    b = bron[0]
    pad = data / b["bestand"]
    if pad.suffix == ".sqlite" and pad.is_file():
        meta = snapshots._lees_meta(pad) or {}
        if meta.get("bron"):
            return meta["bron"]
    return b["bestand"]


def bouw_payload_landelijk(cfg: dict) -> dict:
    """
    Heel Nederland uit panden_nederland.json (VA-37, VA-39): de cijfers uit 'totalen', de kaarten
    uit 'werklijst' in de volgorde van de run (leadscore, dan de maandloting). Wat de run telde,
    wordt hier niet opnieuw geteld; alleen wat op de pagina staat, telt de pagina zelf.
    """
    label = nederland.NAAM
    pad = DATA / f"panden_{nederland.SLUG}.json"
    gelezen, reden = lees_landelijk(pad)
    if gelezen is None:
        bron, bron_reden = None, reden
    else:
        bron, bron_reden = lees_bron(pad)
    t = (gelezen or {}).get("totalen") or {}
    lijst = (gelezen or {}).get("werklijst") or []
    groot = t.get("aantal_grote_gemeenten")
    drempel = t.get("drempel")
    ophaal = nl_datum(bron[0].get("ophaaldatum")) if bron else None

    def tal(sleutel: str) -> str:
        return nl_getal(t.get(sleutel)) if gelezen is not None else "onbekend"

    # Lumi, VA-39: geen dekkingspercentage (de WFS-telling komt uit een andere bron en datum), en
    # kaart 4 toont de pool waaruit de werklijst kiest; de werklijst zelf staat in zijn eigen kop.
    kpi = [
        {"v": tal("vbo"), "l": "Verblijfsobjecten ingelezen",
         "h": escape(f"uit de BAG van {ophaal}" if ophaal else (bron_reden or reden)), "c": "var(--s1)"},
        {"v": tal("panden"), "l": "Unieke BAG-panden", "h": tal("uitgesloten") + " uitgesloten",
         "c": "var(--s3)"},
        {"v": tal("a_e"), "l": "Binnen categorie A–E", "h": "de mastervoorraad", "c": "var(--s2)"},
        {"v": tal("geschikt"), "l": f"Geschikt · score ≥ {nl_getal(drempel)}",
         "h": f"{tal('geschikt_25')} in de {nl_getal(groot)} grootste gemeenten · {tal('geschikt_overig')} elders",
         "c": "var(--s5)"},
    ]
    per_cat = t.get("categorieen") or {}
    cats = [{"k": k, "name": CATEGORIE_NAAM[k], "n": per_cat.get(k, 0), "c": CATEGORIE_KLEUR[k]}
            for k in "ABCDE"]

    facts = [
        {"k": "Panden op de werklijst", "val": tal("werklijst")},
        {"k": f"Uit de {nl_getal(groot)} grootste gemeenten", "val": tal("werklijst_25")},
        {"k": f"Elders in {label}", "val": tal("werklijst_overig")},
        *lijst_feiten(lijst),
        {"k": "Doelgebied", "val": label},
    ]
    if bron is None:
        facts.append({"k": "Bronbestand", "val": "onbekend", "tip": escape(bron_reden)})
    else:
        facts.append({"k": "Bronbestand", "val": escape(f"{bronbestand(bron, DATA)} · {ophaal}"),
                      "tip": escape(f"Heel {label}: BAG-GeoPackage van PDOK, stand {ophaal}")})

    leads, criteria, waarden = maak_leads(lijst, landelijk=True)
    n_groot = sum(1 for p in lijst if p.get(nederland.IN_GROOT) == "ja")
    n = len(leads)
    return {"kpi": kpi, "cats": cats, "facts": facts, "leads": leads,
            "velden": detail_labels((cfg.get("drempels") or {}).get("aantal_grote_gemeenten")),
            "criteria": criteria, "waarden": waarden, "plek": PLEK_SJABLOON,
            "filter": {**gemeente_filter(lijst, groot), **bereik_filter(leads)} if lijst else None,
            "kaartfoto": kaartfoto_tekst(), "bewaar": bewaar_blok(lijst),
            "budget": cfg["score"].get("schaal_max", 26), "gebied": label,
            "koppen": koppen(label, drempel, n if gelezen is not None else None,
                             {"maand": maand_voluit(t.get("maand")), "n_groot": nl_getal(n_groot),
                              "n_rest": nl_getal(n - n_groot), "aantal": nl_getal(groot),
                              "n_ae": tal("a_e")}),
            "pagina": pagina("werklijst", f"Levrai · Pandenselectie — {label}", "Werklijst in cijfers",
                             f"De {nl_getal(n)} panden van deze maand, verdeeld over het land",
                             bron_pil(lijst, "Bron: PDOK BAG GeoPackage")),
            "bron": bron, "bron_regels": bron_regels(bron), "bron_reden": bron_reden,
            "peildatum": peildatum(bron), "peildatum_tip": peildatum_tip(bron, bron_reden),
            "kantoor": kantoor_landelijk(bron, t if gelezen is not None else None,
                                         n if gelezen is not None else None, cfg),
            # VA-85: de landkaart boven het kantoor; de 25 grootste uit het CBS-bestand van VA-65.
            "kaart": (landkaart(lijst, t, bron, cbs_gemeenten.grootste(groot), lees_kaart())
                      if gelezen is not None and groot else None)}


# --------------------------------------------------------------- menu en koppen (VA-63, VA-64)
# Lumi's kopijtabel uit design/menu.html, als data. Elk menu-item wijst naar een section.deel op
# de pagina; tests/test_dashboard_menu.py faalt als een href nergens naar wijst (VA-64 crit. 4).
# Alleen wat de pagina nu heeft: voor heel Nederland staat Werklijst op de plek van Proefresultaat
# (VA-39, menu_voor()); Koppelingen (VA-56/58) komt er pas bij als zijn verhaal Done is.
MENU = [
    {"groep": "Overzicht", "id": "g-overzicht",
     "items": [("kantoor", "Kantoor"), ("kerncijfers", "Kerncijfers")]},
    {"groep": "Panden", "id": "g-panden",
     "items": [("voorraad", "Voorraad"), ("proefresultaat", "Proefresultaat")]},
]
KANTOORMANAGER = "Kantoormanager"
# {gebied}, {drempel} en {n} vult koppen() in; het script plaatst niets.
KOP_TEKST = {
    # Op Ayman's verzoek geen zichtbare kop of uitlegzin boven de band; de kop is er voor schermlezers.
    "kantoor.titel": "Kantoor",
    "kerncijfers.titel": "{gebied} in vier cijfers",
    "kerncijfers.zin": "Van de ingelezen verblijfsobjecten tot de werklijst met score {drempel} of hoger.",
    "voorraad.titel": "Voorraad en proefselectie",
    "voorraad.zin": "Hoeveel panden in elke categorie A–E vallen, en wat de {n} panden van de proef "
                    "kenmerkt.",
    "proefresultaat.titel": "De {n} hoogst scorende panden",
    "proefresultaat.zin": "De controlevraag uit de briefing. Open een pand voor de score-opbouw per "
                          "criterium.",
    "proefresultaat.meta": "{n} panden · {gebied} · gesorteerd op score-index",
}
# Heel Nederland (Lumi, kopij VA-39): het proefresultaat van Delft wordt de werklijst van de maand.
# Waar haar tabel niets zegt, blijft de tekst van vandaag staan.
LIJST_LANDELIJK = ("werklijst", "Werklijst")
KOP_TEKST_LANDELIJK = {
    **{k: t for k, t in KOP_TEKST.items() if not k.startswith("proefresultaat.")},
    "voorraad.titel": "Voorraad en werklijst",
    "voorraad.zin": "Hoeveel van de {n_ae} panden in elke categorie A–E vallen, en wat de {n} panden op de "
                    "werklijst van deze maand kenmerkt.",
    "werklijst.titel": "Werklijst {maand}",
    "werklijst.zin": "De {n} hoogst scorende panden van {gebied}, klaar voor je visuele controle. Open een "
                     "pand voor alle gegevens.",
    # Lumi, VA-70: "· gesorteerd op score-index" vervalt; het sorteerveld zegt het nu zelf.
    "werklijst.meta": "{n} panden · {n_groot} uit de {aantal} grootste gemeenten · {n_rest} elders",
}


def koppen(gebied: str, drempel: int | None, n: int | None, landelijk: dict | None = None) -> dict:
    """
    De titel, de uitlegregel en de meta boven elk deel; onbekend blijft 'onbekend'.
    landelijk: {'maand', 'n_groot', 'n_rest', 'aantal', 'n_ae'} als tekst, voor de werklijst van Nederland.
    """
    waarden = {"gebied": gebied, "drempel": nl_getal(drempel), "n": nl_getal(n), **(landelijk or {})}
    tekst = KOP_TEKST_LANDELIJK if landelijk is not None else KOP_TEKST
    return {k: t.format(**waarden) for k, t in tekst.items()}


def menu_voor(lijst: str) -> list[dict]:
    """MENU, met voor heel Nederland 'Werklijst' op de plek van 'Proefresultaat'."""
    if lijst != LIJST_LANDELIJK[0]:
        return MENU
    # Bewaarde panden is een eigen pagina (Ayman 11-17), dus een eigen groep onder Panden, niet tussen de delen
    # van de lange scroll. Op de pagina staat het deel ook als laatste, zodat menu en delen dezelfde volgorde houden.
    return [dict(g, items=[LIJST_LANDELIJK if doel == "proefresultaat" else (doel, naam) for doel, naam in g["items"]])
            for g in MENU] + [{"groep": "Mijn selectie", "id": "g-selectie", "items": [BEWAARD]}]


def menu_html(lijst: str = "proefresultaat") -> str:
    """De groepen en items van de zijbalk. Het eerste item is actief tot het script het zet."""
    menu = menu_voor(lijst)
    eerste = menu[0]["items"][0][0]
    uit = []
    for g in menu:
        uit.append(f'<p class="groep" id="{g["id"]}">{escape(g["groep"])}</p>')
        items = []
        for doel, naam in g["items"]:
            actief = ' aria-current="location"' if doel == eerste else ""
            # VA-91: de telling van de bewaarde panden, een pil (aria-hidden) en een zin voor de schermlezer;
            # het script vult ze, en laat ze leeg bij 0 of zonder opslag.
            n = ('<span class="vh" id="bwpMenuSr"></span><span class="nav-n" id="bwpMenuN" aria-hidden="true" hidden>'
                 '</span>') if doel == BEWAARD[0] else ""
            items.append(f'<li><a href="#{doel}" data-doel="{doel}"{actief}>{escape(naam)}{n}</a></li>')
        uit.append(f'<ul aria-labelledby="{g["id"]}">{"".join(items)}</ul>')
    return "".join(uit)


def werkbalk_knoppen(tekst: dict | None) -> list[dict]:
    """
    De knoppen onder het kantoor (VA-63 crit. 4 en 14): 1 Ingest, 2 Selectie, 3 Verrijking,
    4 Controle, en als laatste de Kantoormanager zonder nummer. Toestand en regel uit
    kantoor_teksten(); zonder tekstblok 'leeg' en 'onbekend'.
    """
    tekst = tekst or {}
    knoppen = []
    for nr, wie in enumerate(_TEKST, 1):
        r = tekst.get(wie) or {}
        knoppen.append({"wie": wie, "nr": str(nr), "naam": NAMEN[wie],
                        "s": r.get("s", "leeg"), "bel": r.get("bel", LEEG)})
    knoppen.append({"wie": "chef", "nr": "", "naam": KANTOORMANAGER, "s": "chef",
                    "bel": (tekst.get("chef") or {}).get("zin", LEEG)})
    return knoppen


def werkbalk_html(tekst: dict | None) -> str:
    """De werkbalk als HTML; de Kantoormanager staat na de tussenruimte, als laatste."""
    uit = []
    for k in werkbalk_knoppen(tekst):
        if k["wie"] == "chef":
            uit.append('<span class="tussen"></span>')
        nr = f'<span class="nr">{k["nr"]}</span>' if k["nr"] else '<span class="nr" aria-hidden="true"></span>'
        uit.append(f'<button class="pk-knop {k["s"]}" type="button" data-wie="{k["wie"]}" '
                   f'aria-expanded="false" aria-controls="pk-uitleg">{nr}<span class="tk">'
                   f'<span class="nm">{escape(k["naam"])}</span><span class="bel">{escape(k["bel"])}</span>'
                   '</span></button>')
    return "".join(uit)


# --------------------------------------------------------------- landkaart (VA-85)
# Lumi's drie richtingen uit design/richting.html samen in één navy band, alleen voor heel Nederland
# (Ayman: "combineer ze", spectaculairder): C's landkaart, B's brein rond de kern in de
# Noordzee, en A's stroom die langs de vijf glazen cijfers dunner wordt. Haar kopij staat hier als data; Python
# maakt elk getal en elke zin, het script tekent alleen (les van VA-31). De vorm van het land en de
# gemeentepunten komen uit referentie/kaart_nl_<jaar>.json (kaart_nl.py); de panden uit de werklijst.
KAART_TEKST = {
    "trap.label": "Van BAG naar werklijst",
    "trap.vbo": "verblijfsobjecten",
    "trap.panden": "panden",
    "trap.a_e": "in A–E",
    "trap.geschikt": "score ≥ {drempel}",
    "trap.werklijst": "op je werklijst",
    "legenda.cat": "in A–E",
    "legenda.ring": "score ≥ {drempel}",
    "legenda.wl": "op je werklijst",
    "aria": "Selectie op de BAG van {datum}: {vbo} verblijfsobjecten, {panden} panden, {a_e} in categorie A "
            "tot en met E, {geschikt} met score {drempel} of hoger, {werklijst} op je werklijst: {n_groot} uit de "
            "{aantal} grootste gemeenten en {n_rest} elders. {grootste}.",
    # Ayman: "500 on werklijst dont sound like a lot ... replace that with just stating werklijst". De band noemt
    # het aantal niet; het vijfde glazen cijfer en de kern heten alleen "Werklijst". De schermlezertekst ('aria')
    # houdt het echte aantal, want die vertelt wat er is.
    "trap.werklijst.naam": "Werklijst",
    "kern.tip": "Je werklijst: {n_groot} uit de {aantal} grootste gemeenten, {n_rest} elders",
    "kern.label": "Werklijst",
    "gemeente.tip": "{naam} · {n} {panden} op je werklijst",
    "cat.tip": "Categorie {k} · {naam} · {n} panden",   # Lumi, concept B
    "stroom.noot": "De stroom is niet op schaal, de cijfers wel.",   # Lumi, concept A
}
TRAP = ("vbo", "panden", "a_e", "geschikt", "werklijst")  # de vijf glazen cijfers, in deze volgorde
KAART_KERN = (53.02, 3.74)  # breedte, lengte: de kern in de Noordzee, waar Lumi hem zette
KAART_LABELS = 4            # zoveel gemeenten krijgen naam en aantal op de kaart (Lumi: de vier grootste)
KAART_STAP = 100            # coördinaten in honderdsten van een graad: ongeveer 1 km


def nl_datum_voluit(iso: str | None) -> str:
    """'JJJJ-MM-DD' -> 'D maand JJJJ', maand voluit (harde spaties); onleesbaar -> 'ophaaldatum onbekend'."""
    dag = lees_datum(iso)
    if dag is None:
        return "ophaaldatum onbekend"
    return f"{dag.day}{NBSP}{MAANDEN_VOL[dag.month - 1]}{NBSP}{dag.year}"


def _kort(breedte: float, lengte: float) -> list[int]:
    """[breedte, lengte] in honderdsten van een graad vanaf 50° N, 3° O (zo staan ze in de payload)."""
    return [round((breedte - 50) * KAART_STAP), round((lengte - 3) * KAART_STAP)]


def lees_kaart(pad: Path | None = None) -> dict | None:
    """Het nieuwste kaartbestand van kaart_nl.py, of None (dan tekent de kaart geen land en geen gemeenten)."""
    pad = pad or kaart_nl.nieuwste()
    if pad is None or not pad.is_file():
        return None
    return json.loads(pad.read_text(encoding="utf-8"))


def kaart_bron(kaart: dict | None) -> str:
    """De bron van de landvorm, zoals hij als commentaar in de pagina staat."""
    b = (kaart or {}).get("bron")
    if not b:
        return "geen kaartbestand in referentie/, dus geen landvorm en geen gemeenten"
    return f"{b['titel']} ({b['dienst']}, lagen {', '.join(b['lagen'])}), {b['licentie']}, opgehaald {b['opgehaald']}"


def landkaart(lijst: list[dict], t: dict, bron: list[dict] | None, grote: list[dict],
              kaart: dict | None) -> dict:
    """
    PAYLOAD.kaart: het land, de grootste gemeenten, één stip per werklijstpand (afgerond op
    ongeveer 1 km) en alle teksten. 'pt' is plat, vier getallen per pand: breedte, lengte, kleur
    (0-4 = categorie A-E, +5 = ring voor score ≥ drempel) en gemeente (index in 'gm', -1 = elders).
    """
    drempel = t.get("drempel")
    codes = {g["gemeentecode"]: i for i, g in enumerate(grote)}
    punten = (kaart or {}).get("gemeenten") or {}
    tellen = [0] * len(grote)
    pt = []
    for p in lijst:
        i = codes.get(p.get("gemeentecode"), -1)
        if i >= 0:
            tellen[i] += 1
        plek = pand_plek(p)
        if plek is None:
            continue  # geen bruikbare x,y: geen stip, wel geteld
        breedte, lengte = (float(v) for v in plek["ll"].split(","))
        kleur = "ABCDE".index(p["pandcategorie"]) + (5 if drempel is not None and p["leadscore"] >= drempel else 0)
        pt += _kort(breedte, lengte) + [kleur, i]
    gm = []
    for g, n in zip(grote, tellen):
        naam = gemeente_naam(g["gemeente"])
        plek = punten.get(g["gemeentecode"])
        gm.append({"ll": _kort(*plek) if plek else None, "n": n, "naam": naam, "v": nl_getal(n), "lab": 0,
                   "tip": KAART_TEKST["gemeente.tip"].format(naam=naam, n=nl_getal(n),
                                                             panden="pand" if n == 1 else "panden")})
    grootste = sorted((g for g in gm if g["n"]), key=lambda g: -g["n"])[:KAART_LABELS]
    for g in grootste:
        g["lab"] = 1
    trap = {k: nl_getal(t.get(k)) for k in TRAP}
    woorden = {**trap, "drempel": nl_getal(drempel), "n_groot": nl_getal(t.get("werklijst_25")),
               "n_rest": nl_getal(t.get("werklijst_overig")), "aantal": nl_getal(len(grote)),
               "datum": nl_datum_voluit(bron[0].get("ophaaldatum")) if bron else nl_datum_voluit(None),
               "grootste": ", ".join(f"{g['naam']} {g['v']}" for g in grootste)}
    tekst = {k: v.format(**woorden) for k, v in KAART_TEKST.items()
             if k not in ("gemeente.tip", "cat.tip")}  # die twee vullen gm en cats per stuk
    per_cat = t.get("categorieen") or {}
    cats = [{"k": c, "n": per_cat.get(c) or 0,
             "tip": KAART_TEKST["cat.tip"].format(k=c, naam=CATEGORIE_NAAM[c], n=nl_getal(per_cat.get(c)))}
            for c in "ABCDE"]
    # De stroom (A): de ruwe aantallen voor hoe dun hij wordt, en per cijfer de lengte van zijn balk
    # op een logaritmische schaal (9.998.456 is 100 %, 1 zou 0 % zijn). Getoond worden alleen de teksten.
    ruw = [t.get(c) or 0 for c in TRAP]
    top = math.log10(max(ruw[0], 10))
    breed = [round(100 * math.log10(max(n, 1)) / top) for n in ruw]
    land = [[c for la, lo in ring for c in _kort(la, lo)] for ring in (kaart or {}).get("land") or []]
    return {"land": land, "gm": gm, "pt": pt, "trap": trap, "tekst": tekst, "bron": kaart_bron(kaart),
            "cats": cats, "ruw": ruw, "breed": breed,
            "kern": {"ll": _kort(*KAART_KERN), "label": tekst["kern.label"], "tip": tekst["kern.tip"]}}


def band_html(k: dict | None) -> tuple[str, str, str]:
    """
    (klasse, trap, kaart): wat de band in het kantoordeel zet, na de kop. Zonder PAYLOAD.kaart (een
    gebied als Delft) drie keer niets, en blijft de kop van het kantoor zoals hij was.
    Eén canvas ligt onder de hele band; .kaart-vlak houdt alleen de plek voor de kaart vrij.
    """
    if not k:
        return "", "", ""
    t = k["tekst"]
    items = []
    for s, w in zip(TRAP, k["breed"]):
        if s == "werklijst":   # zonder aantal, alleen de naam (Ayman)
            items.append(f'<li class="trap-wl" style="--w:{w}%"><b>{escape(t["trap.werklijst.naam"])}</b></li>')
            continue
        items.append(f'<li style="--w:{w}%"><b>{escape(k["trap"][s])}</b><span>{escape(t["trap." + s])}</span></li>')
    legenda = "".join(f'<span><i class="lg-{s}"></i>{escape(t["legenda." + s])}</span>' for s in ("cat", "ring", "wl"))
    trap = (f'\n      <div class="trap-blok"><ol class="trap" aria-label="{escape(t["trap.label"])}">{"".join(items)}</ol>'
            f'<p class="stroom-noot">{escape(t["stroom.noot"])}</p></div>')
    kaart = (f'\n      <!-- Landkaart (VA-85). Landvorm en gemeentepunten: {escape(k["bron"])}. '
             'De stippen: de panden van de werklijst, afgerond op ongeveer 1 km. -->\n'
             f'      <canvas class="band-doek" id="landkaart" role="img" aria-label="{escape(t["aria"])}"></canvas>'
             '<div class="kaart-tip" id="kaartTip" hidden></div>\n'
             f'      <figure class="kaart"><div class="kaart-vlak"></div><figcaption class="legenda">{legenda}</figcaption></figure>')
    return " band", trap, kaart


TEMPLATE = r"""<!-- @dsCard group="Levrai VASTGOED" name="Pandenselectie dashboard" subtitle="__LABEL__ · 20-pand proefresultaat met score-opbouw" -->
<!doctype html>
<html lang="nl" data-theme="light"><!-- VA-66: altijd licht openen (Ayman); Thema wisselt -->
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITEL__</title>
<style>
  :root{
    color-scheme: light;
    --plane:#f9f9f7; --surface:#fcfcfb; --surface-2:#ffffff;
    --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --ring:rgba(11,11,11,.10);
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
    --good:#0ca30c; --crit:#d03b3b;
    --shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px -12px rgba(11,11,11,.12);
    --brand:#12233b;
  }
  @media (prefers-color-scheme: dark){
    :root:where(:not([data-theme="light"])){
      color-scheme: dark;
      --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#201f1e;
      --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,.10);
      --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
      --good:#0ca30c; --crit:#e06666;
      --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px -14px rgba(0,0,0,.6);
      --brand:#0a1524;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#201f1e;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --ring:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
    --good:#0ca30c; --crit:#e06666;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px -14px rgba(0,0,0,.6);
    --brand:#0a1524;
  }

  /* Menu-tinten: bestaande kleuren uit de vroegere kop (VA-63). */
  :root{
    --nav-tekst:#c6d3e4; --nav-label:#9fb3cc;
    --nav-hover:rgba(255,255,255,.08); --nav-actief:rgba(255,255,255,.14); --nav-lijn:rgba(255,255,255,.10);
  }
  /* Landkaart (VA-85, Lumi #h-tokens): alleen mengsels van tokens die er al zijn, geen nieuwe kleur.
     Ze volgen --brand en --s1, dus de band wordt donker met het thema. */
  :root{
    --brand-2:color-mix(in srgb,var(--brand) 78%,var(--s1));
    --held:linear-gradient(155deg,var(--brand) 0%,var(--brand) 35%,var(--brand-2) 100%);
    --gloed:color-mix(in srgb,var(--s1) 40%,transparent);
    --schaduw-hoog:0 1px 2px rgba(11,11,11,.05),0 28px 56px -28px color-mix(in srgb,var(--brand) 60%,transparent);
    --glans:rgba(255,255,255,.75);   /* het glimlicht bovenin een glazen strook (Bewaar en Verberg, Lumi) */
  }
  @media (prefers-color-scheme: dark){
    :root:where(:not([data-theme="light"])){--schaduw-hoog:0 1px 2px rgba(0,0,0,.5),0 30px 60px -30px rgba(0,0,0,.9);
      --glans:rgba(255,255,255,.06)}
  }
  :root[data-theme="dark"]{--schaduw-hoog:0 1px 2px rgba(0,0,0,.5),0 30px 60px -30px rgba(0,0,0,.9);--glans:rgba(255,255,255,.06)}

  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  @media (prefers-reduced-motion: no-preference){ html{scroll-behavior:smooth} }
  body{margin:0;background:var(--plane);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.45}
  a{color:inherit}

  /* =====================================================================
     MENU (VA-63, Lumi; gebouwd in VA-64)
     ===================================================================== */
  .skip{position:absolute;left:12px;top:-60px;z-index:100;background:var(--brand);color:#fff;
    padding:10px 14px;border-radius:10px;font-size:14px;font-weight:650;text-decoration:none}
  .skip:focus{top:12px;outline:2px solid #fff;outline-offset:2px}

  .vg{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh;background:var(--plane);color:var(--ink)}

  .side{grid-column:1;grid-row:1 / span 2;position:sticky;top:0;align-self:start;height:100vh;overflow:auto;
    background:var(--brand);color:#fff;border-right:1px solid var(--nav-lijn);
    display:flex;flex-direction:column;padding:22px 12px 16px;scrollbar-width:thin}
  .side-kop{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
  .side .merk{padding:2px 10px 18px}
  .mark{font-weight:800;letter-spacing:.16em;font-size:15px;color:#fff;white-space:nowrap}
  .mark small{display:block;letter-spacing:.28em;font-weight:600;font-size:10px;color:var(--nav-label);margin-top:3px}
  .merk-sub{margin:12px 0 0;font-size:12.5px;color:var(--nav-tekst)}

  .nav ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:2px}
  .nav .groep{margin:0;padding:16px 12px 6px;font-size:10px;font-weight:700;letter-spacing:.16em;
    text-transform:uppercase;color:var(--nav-label)}
  .nav .groep:first-child{padding-top:4px}
  .nav a{position:relative;display:flex;align-items:center;min-height:40px;padding:8px 12px 8px 14px;
    border-radius:10px;color:var(--nav-tekst);font-size:14px;font-weight:500;text-decoration:none}
  .vg.klaar .nav a{transition:background-color .15s ease,color .15s ease}
  @media (hover:hover){ .nav a:hover{background:var(--nav-hover);color:#fff} }
  .nav a:focus-visible{outline:2px solid #fff;outline-offset:-2px}
  /* actief: meer dan kleur alleen — streep links, vet, lichter vlak, aria-current */
  .nav a[aria-current]{background:var(--nav-actief);color:#fff;font-weight:700}
  .nav a[aria-current]::before{content:"";position:absolute;left:0;top:9px;bottom:9px;width:3px;
    border-radius:0 3px 3px 0;background:#fff}

  .side-voet{margin-top:auto;padding:16px 10px 0;border-top:1px solid var(--nav-lijn);
    display:flex;flex-wrap:wrap;gap:8px}
  .toggle{cursor:pointer;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);
    color:#fff;font:inherit;font-size:12px;padding:7px 12px;border-radius:999px;min-height:32px}
  @media (hover:hover){ .toggle:hover{background:rgba(255,255,255,.18)} }
  .toggle:focus-visible{outline:2px solid #fff;outline-offset:2px}
  .uitlog{margin:0}   /* VA-106: het formulier om de knop neemt geen eigen ruimte */

  .sluit-menu{display:none;align-items:center;gap:6px;cursor:pointer;flex:none;
    background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);color:#fff;
    font:inherit;font-size:13px;font-weight:650;min-height:40px;padding:0 12px;border-radius:10px}
  .sluit-menu span{font-size:18px;line-height:1}
  .sluit-menu:focus-visible{outline:2px solid #fff;outline-offset:2px}

  .topbalk{display:none}
  .menuknop{display:inline-flex;align-items:center;gap:10px;cursor:pointer;min-height:44px;padding:0 14px;
    background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);color:#fff;
    font:inherit;font-size:14px;font-weight:650;border-radius:10px}
  .menuknop .streep{width:18px;height:12px;flex:none;
    background:linear-gradient(#fff 0 0) top/100% 2px no-repeat,
               linear-gradient(#fff 0 0) center/100% 2px no-repeat,
               linear-gradient(#fff 0 0) bottom/100% 2px no-repeat}
  .menuknop:focus-visible{outline:2px solid #fff;outline-offset:2px}
  .scrim{display:none}

  .inhoud{grid-column:2;min-width:0;padding:26px 28px 64px}
  .inhoud:focus{outline:none}
  .deel{scroll-margin-top:16px}
  .deel:focus{outline:none}
  .deel + .deel{margin-top:44px}
  .kop{display:flex;flex-direction:column;gap:6px;margin:0 2px 16px}
  .kop-rij{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 14px;min-height:28px}
  .kruimel{margin:0;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-2)}
  .kruimel b{color:var(--ink);font-weight:800}
  .kruimel span{margin:0 .35em}
  .kop h1,.kop .titel{margin:0;font-weight:750;letter-spacing:-.02em;line-height:1.15}
  .kop h1{font-size:30px}
  .kop .titel{font-size:22px}
  .kop-zin{margin:0;font-size:14.5px;color:var(--ink-2);max-width:78ch}
  .spills{display:flex;flex-wrap:wrap;gap:6px}
  .pill{font-size:12px;color:var(--ink-2);background:var(--surface);border:1px solid var(--ring);
    padding:4px 11px;border-radius:999px;white-space:nowrap}
  .kop-meta{font-size:12px;color:var(--ink-2)}
  /* ===================== einde MENU-blok (smal: zie @media (max-width:800px) onderaan) ===================== */

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
  .kpi{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow)}
  .kpi .v{font-size:30px;font-weight:750;letter-spacing:-.02em;line-height:1}
  .kpi .v.onb{font-size:22px;letter-spacing:0}
  .kpi .l{font-size:12.5px;color:var(--ink-2);margin-top:8px}
  .kpi .h{font-size:11px;color:var(--muted);margin-top:3px}
  .kpi .accent{width:26px;height:3px;border-radius:2px;margin-bottom:12px;background:var(--s1)}

  .cols{display:grid;grid-template-columns:1.35fr 1fr;gap:14px}
  .panel{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}
  .panel h3{margin:0 0 4px;font-size:14px;font-weight:700}
  .panel .cap{margin:0 0 16px;font-size:12px;color:var(--muted)}

  .bar{display:grid;grid-template-columns:150px 1fr;align-items:center;gap:12px;margin:11px 0}
  .bar .name{font-size:12.5px;color:var(--ink-2)}
  .bar .name b{color:var(--ink);font-weight:650}
  .track{position:relative;height:22px;background:var(--grid);border-radius:6px;overflow:hidden}
  .fill{height:100%;border-radius:6px;display:flex;align-items:center;justify-content:flex-end;
    padding-right:8px;color:#fff;font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums;
    min-width:34px;transition:width .6s cubic-bezier(.2,.7,.2,1)}

  .facts{display:grid;gap:12px}
  .fact{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px dashed var(--grid);padding-bottom:9px}
  .fact:last-child{border-bottom:0;padding-bottom:0}
  .fact .k{font-size:12.5px;color:var(--ink-2)}
  .fact .val{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
  .note{margin-top:14px;font-size:11.5px;color:var(--muted);line-height:1.5}

  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
  .card{container:kaart / inline-size;background:var(--surface);border:1px solid var(--ring);border-radius:14px;
    padding:16px 17px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:11px;min-width:0}
  .card-top{display:grid;grid-template-columns:100px minmax(0,1fr) auto;gap:12px;align-items:start}
  .card-kern{display:flex;flex-direction:column;gap:6px;min-width:0}
  .card .addr{font-size:14.5px;font-weight:700;letter-spacing:-.01em;overflow-wrap:anywhere}
  .card .lid{font-size:11.5px;color:var(--ink-2);font-variant-numeric:tabular-nums}
  .score{flex:none;display:flex;flex-direction:column;align-items:center;justify-content:center;
    width:56px;height:56px;border-radius:14px;background:var(--brand);color:#fff}
  .score b{font-size:22px;font-weight:800;line-height:1}
  .score small{font-size:8px;letter-spacing:.08em;color:#9fb3cc;margin-top:2px}
  .meter{height:6px;border-radius:4px;background:var(--grid);overflow:hidden}
  .meter i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,var(--s1),var(--s3));
    transition:width .6s cubic-bezier(.2,.7,.2,1)}
  .chips{display:flex;flex-wrap:wrap;gap:5px}
  .chip{font-size:10.5px;font-weight:700;color:#fff;padding:2px 8px;border-radius:999px}
  .cA{background:var(--s1)} .cB{background:var(--s2)} .cC{background:var(--s3)}
  .cD{background:var(--s4);color:#3a2a00} .cE{background:var(--s5);color:#3a1220}
  .sigtags{display:flex;flex-wrap:wrap;gap:5px}
  .sigtag{font-size:10.5px;font-weight:650;padding:3px 9px;border-radius:999px;
    background:color-mix(in srgb,var(--good) 13%,transparent);color:var(--good);
    border:1px solid color-mix(in srgb,var(--good) 35%,transparent)}
  .sigtag.leeg{background:color-mix(in srgb,var(--s4) 18%,transparent);
    color:var(--s2);border-color:color-mix(in srgb,var(--s2) 40%,transparent)}
  .meta{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
  .meta div{background:var(--surface-2);border:1px solid var(--ring);border-radius:9px;padding:7px 8px;text-align:center}
  .meta .mv{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}
  .meta .ml{font-size:9.5px;color:var(--muted);letter-spacing:.03em;margin-top:1px}
  .fnbar{display:flex;height:9px;border-radius:5px;overflow:hidden;gap:2px;background:transparent}
  .fnbar i{display:block}
  .fnleg{display:flex;flex-wrap:wrap;gap:10px;font-size:10.5px;color:var(--ink-2)}
  .fnleg span{display:flex;align-items:center;gap:5px}
  .dot{width:8px;height:8px;border-radius:2px;flex:none}

  /* ---- score-opbouw ---- */
  details.brk{border-top:1px solid var(--grid);padding-top:9px}
  details.brk summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;
    font-size:12px;font-weight:650;color:var(--ink)}
  details.brk summary::-webkit-details-marker{display:none}
  details.brk summary .caret{margin-left:auto;color:var(--muted);transition:transform .2s}
  details.brk[open] summary .caret{transform:rotate(180deg)}
  details.brk summary em{font-style:normal;color:var(--muted);font-weight:500}
  .brk ul{list-style:none;margin:11px 0 0;padding:0;display:grid;gap:2px}
  .brk li{display:flex;align-items:center;gap:9px;padding:5px 7px;border-radius:8px;font-size:11.5px}
  .brk li.ok{background:color-mix(in srgb,var(--good) 9%,transparent)}
  .brk li .ci{flex:none;width:15px;height:15px;border-radius:50%;display:flex;align-items:center;
    justify-content:center;font-size:9px;font-weight:800;color:#fff}
  .brk li.ok .ci{background:var(--good)}
  .brk li.miss .ci{background:var(--grid);color:var(--muted)}
  .brk li.neg .ci{background:var(--crit)}
  .brk li.off .ci{background:transparent;border:1.5px dashed var(--baseline);color:var(--muted)}
  .brk li .cl{flex:1;color:var(--ink)}
  .brk li.miss .cl,.brk li.off .cl{color:var(--ink-2)}
  .brk li .cl em{display:block;font-style:normal;font-size:10px;color:var(--muted);margin-top:1px}
  .brk li .cp{flex:none;font-weight:800;font-variant-numeric:tabular-nums;font-size:11.5px}
  .brk li.ok .cp{color:var(--good)} .brk li.neg .cp{color:var(--crit)}
  .brk li.miss .cp{color:var(--muted)} .brk li.off .cp{color:var(--muted);font-weight:600;font-size:9.5px}
  .brkfoot{margin-top:9px;font-size:10.5px;color:var(--muted);line-height:1.5}
  .brkfoot b{color:var(--ink)}

  .card .foot{display:flex;justify-content:space-between;align-items:center;margin-top:2px;padding-top:2px}
  .baglink{font-size:11.5px;font-weight:650;color:var(--s1);text-decoration:none}
  .baglink:hover{text-decoration:underline}
  .status{font-size:10.5px;color:var(--good);display:flex;align-items:center;gap:5px}
  .status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--good)}
  .foothint{margin-top:26px;font-size:11.5px;color:var(--muted);text-align:center;line-height:1.6}

  #tt{position:fixed;pointer-events:none;opacity:0;transform:translate(-50%,-8px);
    background:var(--brand);color:#fff;font-size:11.5px;padding:6px 9px;border-radius:8px;
    box-shadow:var(--shadow);white-space:nowrap;transition:opacity .12s;z-index:50}

  /* =====================================================================
     PIXELKANTOOR — dit blok gaat mee naar build_dashboard.py
     ===================================================================== */
  .pk{background:var(--surface);border:1px solid var(--ring);border-radius:14px;
    box-shadow:var(--shadow);overflow:hidden;container-type:inline-size}
  .pk-scene{position:relative}
  .pk-scene canvas{display:block;width:100%;height:auto;image-rendering:pixelated}
  .pk-ov{position:absolute;inset:0;pointer-events:none}
  .pk-ov>*{position:absolute}
  .pk-bel{transform:translate(-50%,-100%);pointer-events:auto;cursor:pointer;
    max-width:var(--pk-bel-max,240px);width:max-content;text-align:center;
    background:var(--surface-2);color:var(--ink);border:2px solid var(--ink-2);border-radius:3px;
    padding:3px 7px;font-size:12px;font-weight:650;line-height:1.25;
    box-shadow:2px 2px 0 var(--ring);animation:pk-pop .25s ease-out}
  .pk-bel::after{content:"";position:absolute;left:50%;bottom:-8px;margin-left:-4px;
    border:4px solid transparent;border-top-color:var(--pk-rand,var(--ink-2))}
  .pk-bel.werkt{--pk-rand:var(--s1);border-color:var(--s1)}
  .pk-bel.aandacht{--pk-rand:var(--s4);border-color:var(--s4);
    background:color-mix(in srgb,var(--s4) 16%,var(--surface-2));animation:pk-pop .25s ease-out,pk-hup .6s .25s infinite alternate}
  .pk-bel.slaapt{--pk-rand:var(--baseline);border-color:var(--baseline);border-style:dashed;color:var(--ink-2)}
  .pk-bel.leeg{--pk-rand:var(--muted);border-color:var(--muted);border-style:dashed;
    background:var(--grid);color:var(--ink-2)}
  .pk-bel.aandacht::before{content:"! ";color:var(--s2);font-weight:800}
  .pk-naam{transform:translate(-50%,0);font-size:11px;font-weight:650;color:var(--ink-2);white-space:nowrap;
    background:var(--surface);border:1px solid var(--ring);border-radius:999px;padding:1px 8px}
  .pk-naam b{color:var(--muted);font-weight:650;margin-right:3px}
  .pk-bord{font-size:9px;font-weight:800;letter-spacing:.16em;color:#fff;background:var(--brand);
    padding:2px 6px;border-radius:2px;white-space:nowrap}
  .pk-bord span{color:#9fb3cc}
  .pk-hit{transform:translate(-50%,-50%);pointer-events:auto;cursor:pointer;background:transparent;
    border:0;border-radius:8px;padding:0}
  .pk-hit:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  .pk-voet{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 16px 12px;
    border-top:1px solid var(--grid);font-size:11.5px;color:var(--ink-2)}
  .pk-uitleg{border-top:1px solid var(--grid);padding:14px 16px 16px;background:var(--surface-2)}
  .pk-uitleg[hidden]{display:none}
  .pk-uitleg h3{margin:0;font-size:13.5px;font-weight:700}
  .pk-uitleg h3 em{font-style:normal;color:var(--muted);font-weight:500}
  .pk-uitleg .pk-status{margin:8px 0 0;font-size:12.5px;font-weight:650;display:flex;gap:7px;align-items:baseline}
  .pk-uitleg .pk-status::before{content:"";flex:none;width:8px;height:8px;border-radius:50%;background:var(--muted);transform:translateY(-1px)}
  .pk-uitleg .pk-status.werkt::before{background:var(--s1)}
  .pk-uitleg .pk-status.aandacht::before{background:var(--s4)}
  .pk-uitleg .pk-status.slaapt::before{background:var(--baseline)}
  .pk-uitleg p.pk-tekst{margin:6px 0 0;font-size:12px;color:var(--ink-2);max-width:72ch}
  .pk-sluit{margin-top:10px;cursor:pointer;font:inherit;font-size:11.5px;font-weight:650;color:var(--s1);
    background:none;border:0;padding:0}
  .pk-smal .pk-bel{font-size:11px;padding:2px 5px}
  .pk-smal .pk-naam{font-size:10.5px;padding:1px 6px}
  .pk-smal .pk-bord{font-size:8px}
  @keyframes pk-pop{from{transform:translate(-50%,-100%) scale(.85);opacity:0}}
  @keyframes pk-hup{to{transform:translate(-50%,calc(-100% - 2px))}}
  .pk-stil .pk-bel{animation:none}
  @media (prefers-reduced-motion: reduce){ .pk-bel{animation:none} }
  /* ===================== einde PIXELKANTOOR-blok ===================== */
  /* =====================================================================
     KANTOOR3D — dit blok gaat mee naar build_dashboard.py (na het PIXELKANTOOR-blok)
     ===================================================================== */
  /* .pk-start: dezelfde maat al voordat three.js er is, zodat niets onder het kantoor verschuift
     als het laadt (een adres als #proefresultaat blijft kloppen). Het 2D-kantoor haalt hem weg.
     width:100% houdt de breedte vast: zonder die regel geeft aspect-ratio de max-height door aan de
     breedte en wordt de scène smaller dan het kantoor. */
  .pk-scene.pk-start,.pk-scene.pk-3d{width:100%;aspect-ratio:1.45/1;min-height:240px;overflow:hidden;background:var(--surface-2)}
  .pk-smal .pk-scene.pk-3d{aspect-ratio:1/1}
  @container (max-width:559.98px){ .pk-scene.pk-start{aspect-ratio:1/1} }   /* = .pk-smal: scène smaller dan 560 px */
  /* VA-63/64 crit. 13: breed past het hele kantoor met de werkbalk op een scherm van 1280 × 800.
     270 px = bovenmarge, kop, werkbalk, voettekst en randen (Lumi, gemeten). */
  @media (min-width:801px){ .pk-scene.pk-start,.pk-scene.pk-3d{max-height:calc(100vh - 270px)} }
  .pk-scene.pk-3d canvas{display:block;width:100%;height:100%;image-rendering:auto}
  .pk-3d .pk-ov{overflow:hidden}
  .pk-3d .pk-bel{z-index:2;animation:none}
  .pk-3d .pk-bel.aandacht{animation:pk-hup .6s infinite alternate}
  .pk-stil .pk-3d .pk-bel.aandacht{animation:none}
  @media (prefers-reduced-motion: reduce){ .pk-3d .pk-bel.aandacht{animation:none} }
  .pk-3d .pk-naam{z-index:1}
  .pk-3d .pk-hit{z-index:3}
  .pk-3d .pk-bord{transform:translate(0,-100%);z-index:0;box-shadow:0 1px 0 rgba(0,0,0,.25)}
  .pk-3d .pk-bord.voor{transform:translate(0,-50%);z-index:0;box-shadow:0 1px 0 rgba(0,0,0,.25)}
  .pk-3d .pk-bel.chef{transform:translate(-8px,-100%);--pk-rand:var(--brand);border-color:var(--brand);white-space:nowrap;max-width:none}
  .pk-3d .pk-bel.chef::after{left:8px;margin-left:0}
  .pk-naam.chef{border-color:var(--brand)}
  .pk-z{transform:translate(-50%,-100%);white-space:nowrap;font-size:12px;font-weight:800;letter-spacing:.12em;color:var(--muted);
    pointer-events:none;text-shadow:0 1px 0 var(--surface-2)}
  .pk-smal .pk-3d .pk-bel,.pk-smal .pk-3d .pk-z{display:none}
  .pk-smal .pk-3d .pk-naam{font-size:0;padding:0 5px}   /* smal: alleen het nummer; de namen staan in de werkbalk eronder */
  .pk-smal .pk-3d .pk-naam b{font-size:10px;margin:0}
  .pk-smal .pk-3d .pk-naam.chef{display:none}
  .pk-smal .pk-3d .pk-naam.aandacht{background:color-mix(in srgb,var(--s4) 30%,var(--surface));border-color:var(--s4);color:var(--ink)}
  .pk-smal .pk-3d .pk-bord{font-size:7px;letter-spacing:.06em;padding:1px 4px}
  /* WERKBALK VAN HET KANTOOR (VA-63, vervangt .pk-lijst): vier genummerde medewerkers, dan de Kantoormanager. */
  .pk-balk{display:flex;flex-wrap:wrap;gap:8px;padding:10px 12px;border-top:1px solid var(--grid);background:var(--surface)}
  .pk-knop{display:inline-flex;align-items:center;gap:9px;cursor:pointer;min-height:42px;padding:6px 14px 6px 6px;
    border-radius:10px;border:1px solid var(--ring);background:var(--surface-2);color:var(--ink);
    font:inherit;font-size:13px;font-weight:650;text-align:left;transition:background-color .15s ease}
  .pk-knop[hidden]{display:none}
  .pk-knop .nr{flex:none;width:28px;height:28px;border-radius:7px;background:var(--brand);color:#fff;
    font-size:13px;font-weight:800;display:grid;place-items:center;font-variant-numeric:tabular-nums}
  .pk-knop.chef .nr{background:transparent;border:1.5px dashed var(--baseline)}
  .pk-knop .tk{display:flex;flex-direction:column;min-width:0}
  .pk-knop .nm{display:flex;align-items:center;gap:6px}
  .pk-knop .nm::before{content:"";flex:none;width:8px;height:8px;border-radius:50%;background:var(--muted)}
  .pk-knop.werkt .nm::before{background:var(--s1)}
  .pk-knop.aandacht .nm::before{background:var(--s4)}
  .pk-knop.slaapt .nm::before{background:var(--baseline)}
  .pk-knop.chef .nm::before{background:var(--brand);box-shadow:0 0 0 1px var(--baseline)}
  .pk-knop .bel{display:none;font-size:12px;font-weight:500;color:var(--ink-2);margin-top:1px}
  .pk-knop.aandacht .bel::before{content:"! ";color:var(--s2);font-weight:800}
  .pk-smal .pk-knop .bel{display:block}   /* zonder ballonnen in de scène staat de regel in de knop */
  @media (hover:hover){ .pk-knop:hover{background:var(--grid)} }
  .pk-knop:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  /* open: lichtblauw vlak + dubbele rand (vorm, niet alleen kleur) + aria-expanded */
  .pk-knop[aria-expanded="true"]{background:color-mix(in srgb,var(--s1) 12%,var(--surface-2));
    border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1)}
  .pk-balk .tussen{flex:1}
  .pk-noot{flex-basis:100%;color:var(--ink-2)}
  /* ===================== einde KANTOOR3D-blok ===================== */

  /* =====================================================================
     LANDKAART (VA-85): Lumi's concepten A, B en C samen in één navy band boven het kantoor.
     Eén canvas onder de hele band tekent het raster, de stroom langs de cijfers (A), het brein rond
     de kern (B) en de kaart (C); de kop, de glazen cijfers en de legenda zijn gewone HTML erboven.
     Let op VA-64 crit. 13: met deze band staat de werkbalk van het kantoor op 1280 × 800 niet meer
     bij het laden in beeld. Het kantoor zelf blijft even groot en altijd zichtbaar.
     ===================================================================== */
  .band{position:relative;isolation:isolate;overflow:hidden;margin:-26px -28px 0;padding:24px 28px 64px;
    background:var(--held);color:#fff;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,46%);
    grid-template-rows:auto 1fr;grid-template-areas:"kop kaart" "trap kaart";gap:18px 28px}
  .band::before{content:"";position:absolute;inset:0;z-index:0;pointer-events:none;opacity:.6;
    background:radial-gradient(42% 70% at 74% 40%,var(--gloed),transparent 70%),
      radial-gradient(32% 55% at 8% 100%,color-mix(in srgb,var(--s3) 16%,transparent),transparent 70%)}
  .band>*{position:relative;z-index:1;min-width:0}
  .band>canvas.band-doek{position:absolute;inset:0;z-index:0;width:100%;height:100%;display:block;color:var(--brand-2)}
  .band .kop{grid-area:kop;margin:0;gap:6px}
  .band .kruimel{color:var(--nav-label)}
  .band .kruimel b{color:#fff}
  .band h1{color:#fff;font-size:32px}
  .band .kop-zin{color:var(--nav-tekst)}
  .band .pill{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.14);color:var(--nav-tekst)}
  .band + .pk{position:relative;z-index:2;margin-top:-40px;box-shadow:var(--schaduw-hoog)}
  /* De vijf glazen cijfers (A): onder elkaar, links een kanaal waar de stroom langs loopt. */
  .trap-blok{grid-area:trap;align-self:end}
  .trap{list-style:none;margin:0;padding:0 0 0 26px;display:flex;flex-direction:column;gap:7px;max-width:440px}
  .trap li{position:relative;overflow:hidden;display:flex;align-items:baseline;gap:12px;padding:9px 14px 11px;
    border-radius:12px;font-size:12.5px;color:var(--nav-tekst);background:rgba(255,255,255,.06);
    border:1px solid rgba(255,255,255,.13);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);
    -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
  .trap li::after{content:"";position:absolute;left:0;bottom:0;height:2px;width:var(--w);border-radius:0 2px 2px 0;
    background:linear-gradient(90deg,var(--s1),var(--s3));opacity:.85}
  .trap b{min-width:7.2ch;color:#fff;font-size:21px;font-weight:750;letter-spacing:-.01em;font-variant-numeric:tabular-nums;text-align:right}
  .trap li.trap-wl{background:color-mix(in srgb,var(--s3) 20%,transparent);border-color:color-mix(in srgb,var(--s3) 58%,transparent)}
  .stroom-noot{margin:8px 0 0 26px;font-size:11.5px;color:var(--nav-label)}
  /* De kaart (C): het vlak houdt alleen plek vrij; het canvas eronder tekent erin. */
  .kaart{grid-area:kaart;margin:0;display:flex;flex-direction:column;justify-content:flex-end;gap:6px}
  .kaart-vlak{height:clamp(380px,58vh,560px);pointer-events:none}
  .kaart-tip{position:absolute;z-index:3;pointer-events:none;transform:translate(-50%,calc(-100% - 8px));
    background:var(--brand);color:#fff;font-size:12px;font-weight:600;padding:5px 8px;border-radius:8px;
    border:1px solid rgba(255,255,255,.18);white-space:nowrap}
  .kaart-tip[hidden]{display:none}
  .legenda{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px 14px;font-size:11.5px;color:var(--nav-tekst)}
  .legenda span{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
  .legenda i{flex:none;display:inline-block;width:9px;height:9px;border-radius:50%}
  .lg-cat{background:conic-gradient(var(--s1) 0 20%,var(--s2) 0 40%,var(--s3) 0 60%,var(--s4) 0 80%,var(--s5) 0)}
  .lg-ring{border:1.5px solid #fff}
  .lg-wl{background:var(--s1);box-shadow:0 0 6px 2px var(--gloed)}
  @media (max-width:1100px) and (min-width:801px){ .band{grid-template-columns:minmax(0,1fr) minmax(0,50%)} .trap b{font-size:18px} }
  @media (max-width:800px){
    .band{margin:-18px -14px 0;padding:20px 14px 56px;grid-template-columns:minmax(0,1fr);
      grid-template-rows:auto auto auto;grid-template-areas:"kop" "kaart" "trap";gap:14px}
    .band h1{font-size:24px}
    .kaart-vlak{height:400px}
    .legenda{justify-content:center}
    .trap{padding-left:22px;max-width:none}
    .trap li{padding:7px 12px 9px}
    .trap b{font-size:18px}
    .stroom-noot{margin-left:22px}
  }
  /* ===================== einde LANDKAART ===================== */
  /* ===================== RUNPANEEL (VA-86): wanneer de laatste en de volgende run zijn, in glas ===================== */
  .run-paneel{display:flex;flex-direction:column;gap:8px;width:fit-content;max-width:100%;margin-top:4px;padding:10px 14px 11px;
    border-radius:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.13);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 0 24px -8px var(--gloed);
    -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);font-size:13px;color:var(--nav-tekst)}
  .run-rij{display:flex;flex-direction:column;gap:5px}
  .run-item{position:relative;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 8px;padding-left:19px}
  .run-lab{min-width:9.5em;font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--nav-tekst)}
  .run-item b{color:#fff;font-weight:700}
  .run-wijze{padding:1px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.22);font-size:11.5px;color:var(--nav-tekst)}
  .run-stip{position:absolute;left:1px;top:.45em;width:9px;height:9px;border-radius:50%;background:var(--s4);
    box-shadow:0 0 0 0 color-mix(in srgb,var(--s4) 55%,transparent)}
  .run-stip.automatisch{background:var(--s3);box-shadow:0 0 0 0 color-mix(in srgb,var(--s3) 55%,transparent)}
  @media (prefers-reduced-motion: no-preference){
    .run-stip{animation:run-klop 2.6s ease-out infinite}
    .run-stip.automatisch{animation-name:run-klop-aan}
  }
  @keyframes run-klop{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--s4) 55%,transparent)}
    70%,100%{box-shadow:0 0 0 7px color-mix(in srgb,var(--s4) 0%,transparent)}}
  @keyframes run-klop-aan{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--s3) 55%,transparent)}
    70%,100%{box-shadow:0 0 0 7px color-mix(in srgb,var(--s3) 0%,transparent)}}
  .run-lijn{position:relative;margin-left:19px;height:3px;border-radius:2px;background:rgba(255,255,255,.12);overflow:hidden}
  .run-lijn i{position:absolute;left:0;top:0;bottom:0;border-radius:2px;
    background:linear-gradient(90deg,var(--s1),var(--s3));box-shadow:0 0 10px var(--gloed)}
  .run-noot{margin:0 0 0 19px;font-size:12px;color:var(--nav-tekst)}
  /* ===================== einde RUNPANEEL ===================== */

  @media(max-width:900px){
    .kpis{grid-template-columns:repeat(2,1fr)}
    .cols{grid-template-columns:1fr}
    .grid{grid-template-columns:1fr}
    .bar{grid-template-columns:120px 1fr}
  }
  /* ---- MENU smal (≤ 800 px, VA-63): bovenbalk met menuknop, de zijbalk wordt een lade ---- */
  @media (max-width:800px){
    .vg{grid-template-columns:minmax(0,1fr);grid-template-rows:auto 1fr}
    .topbalk{grid-column:1;grid-row:1;display:flex;position:sticky;top:0;z-index:20;align-items:center;
      justify-content:space-between;gap:12px;height:56px;padding:0 10px 0 16px;background:var(--brand);color:#fff;
      box-shadow:0 1px 0 var(--nav-lijn)}
    .topbalk .mark{font-size:13px}
    .topbalk .mark small{font-size:9px;margin-top:2px}
    .inhoud{grid-column:1;grid-row:2;padding:18px 14px 48px}
    .deel{scroll-margin-top:72px}
    .kop h1{font-size:24px}
    .kop .titel{font-size:19px}
    .kop-zin{font-size:14px}
    .side{position:fixed;top:0;bottom:0;left:0;width:min(304px,86%);height:auto;z-index:40;
      transform:translateX(-100%);visibility:hidden;box-shadow:0 0 40px rgba(0,0,0,.35);padding-top:14px}
    .vg.open .side{transform:none;visibility:visible}
    /* Overgangen pas na de eerste frames (.klaar), anders schuift de lade bij elke laadbeurt zichtbaar weg. */
    .vg.klaar .side{transition:transform .22s ease,visibility 0s linear .22s}
    .vg.klaar.open .side{transition:transform .22s ease}
    .sluit-menu{display:inline-flex}
    .side .merk{padding-top:8px}
    .scrim{display:block;position:fixed;inset:0;z-index:30;background:rgba(11,11,11,.55);opacity:0;visibility:hidden}
    .vg.open .scrim{opacity:1;visibility:visible}
    .vg.klaar .scrim{transition:opacity .22s ease,visibility 0s linear .22s}
    .vg.klaar.open .scrim{transition:opacity .22s ease}
    .kpi .v{font-size:26px}
    .pk-balk{display:grid;grid-template-columns:minmax(0,1fr);gap:6px;padding:8px}
    .pk-balk .tussen{display:none}
    .pk-knop{width:100%;align-items:flex-start;padding:8px 10px 8px 8px}
    .pk-knop .bel{display:block}
  }
  @media (prefers-reduced-motion: reduce){
    .vg.klaar .nav a,.vg.klaar .side,.vg.klaar.open .side,.vg.klaar .scrim,.vg.klaar.open .scrim,.pk-knop{transition:none}
  }
  /* ===================== PAND OPENEN (VA-61, VA-62) ===================== */
  .card.open-baar{cursor:pointer}
  .pand-open{font:inherit;font-size:13px;font-weight:600;color:var(--s1);background:none;border:0;padding:0;cursor:pointer}
  .pand-open:hover{text-decoration:underline}
  .pand-open:focus-visible{outline:2px solid var(--s1);outline-offset:3px;border-radius:4px}
  dialog.pand{width:min(880px,calc(100vw - 24px));max-height:calc(100dvh - 24px);padding:0;
    border:1px solid var(--ring);border-radius:16px;background:var(--surface);color:var(--ink);
    box-shadow:var(--shadow);overflow:hidden}
  dialog.pand::backdrop{background:rgba(11,11,11,.55)}
  dialog.pand[open]{display:flex;flex-direction:column}
  .pand-kop{flex:none;display:flex;align-items:flex-start;gap:12px;padding:16px 18px;border-bottom:1px solid var(--grid)}
  .pand-kop h2{margin:0;font-size:19px;line-height:1.25;overflow-wrap:anywhere}
  .pand-kop p{margin:4px 0 0;font-size:12.5px;color:var(--muted)}
  .pand-kop .score{margin-left:auto;flex:none}
  .pand-sluit{flex:none;font:inherit;font-size:13px;font-weight:600;color:var(--ink);background:var(--surface-2);
    border:1px solid var(--ring);border-radius:9px;padding:7px 12px;cursor:pointer}
  .pand-sluit:focus-visible,.pand-links a:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  .pand-romp{flex:1 1 auto;min-height:0;overflow-y:auto;padding:16px 18px 20px}
  .pand-foto{margin:0 0 14px}
  .pand-foto .kader{position:relative;aspect-ratio:1/1;max-height:360px;width:100%;border-radius:12px;
    overflow:hidden;background:var(--grid)}
  .pand-foto img{display:block;width:100%;height:100%;object-fit:cover}
  .pand-foto .merk{position:absolute;left:50%;top:50%;width:22px;height:22px;margin:-11px 0 0 -11px;
    border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 2px var(--crit);pointer-events:none}
  .pand-foto .melding{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
    padding:16px;text-align:center;font-size:13.5px;color:var(--ink-2)}
  .pand-foto figcaption{margin-top:6px;font-size:11.5px;color:var(--muted)}
  .pand-links{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
  .pand-links a{font-size:13px;font-weight:600;color:var(--s1);text-decoration:none;border:1px solid var(--ring);
    border-radius:9px;padding:7px 11px;background:var(--surface-2)}
  .pand-links a:hover{text-decoration:underline}
  .pand-geenlocatie{margin:0 0 16px;font-size:13px;color:var(--ink-2)}
  .pand-velden{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:0;margin:0}
  .pand-velden dt,.pand-velden dd{padding:8px 0;border-bottom:1px solid var(--grid);font-size:13.5px;margin:0}
  .pand-velden dt{color:var(--ink-2);padding-right:12px}
  .pand-velden dd{overflow-wrap:anywhere}
  .pand-velden dd ul{margin:0;padding:0;list-style:none;max-height:220px;overflow-y:auto}
  .pand-velden dd li{padding:1px 0}
  .pand-opbouw{margin-top:16px}
  .pand-opbouw details.brk{border-top:0}
  @media (max-width:560px){
    .pand-velden{grid-template-columns:minmax(0,1fr)}
    .pand-velden dt{border-bottom:0;padding-bottom:0;font-weight:600}
    .pand-kop{flex-wrap:wrap}
  }
  @media (prefers-reduced-motion: no-preference){
    dialog.pand[open]{animation:pandIn .16s ease-out}
    @keyframes pandIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  }
  /* ===================== einde PAND OPENEN ===================== */
  /* =====================================================================
     WERKLIJSTFILTERS (VA-68, VA-69, VA-70; Lumi: design/filters.html). Breed of smal hangt af van de breedte
     van de werklijst zelf (container), niet van het scherm.
     ===================================================================== */
  :root{--knop:#12233b;--knop-rand:transparent}
  @media (prefers-color-scheme: dark){ :root:where(:not([data-theme="light"])){--knop-rand:rgba(255,255,255,.18)} }
  :root[data-theme="dark"]{--knop-rand:rgba(255,255,255,.18)}
  .vh{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
  .wl{container:wl / inline-size}
  .wl-balk{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 14px;margin:0 2px 12px}
  .wl-knop{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:0 12px 0 14px;font:inherit;font-size:13.5px;
    font-weight:650;color:var(--ink);background:var(--surface);border:1px solid var(--muted);border-radius:10px;cursor:pointer;box-shadow:var(--shadow)}
  .wl-knop[aria-expanded="true"]{border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1)}
  .wl-ico{width:16px;height:12px;flex:none;
    background:linear-gradient(currentColor 0 0) 0 0/100% 2px no-repeat,
               linear-gradient(currentColor 0 0) 50% 50%/66% 2px no-repeat,
               linear-gradient(currentColor 0 0) 50% 100%/34% 2px no-repeat}
  .wl-aantal{display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 6px;border-radius:999px;
    background:var(--ink);color:var(--surface);font-size:11.5px;font-weight:800;font-variant-numeric:tabular-nums}
  .wl-aantal[hidden]{display:none}
  .wl-pijl{width:8px;height:8px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:translateY(-2px) rotate(45deg);margin-left:2px}
  .wl-knop[aria-expanded="true"] .wl-pijl{transform:translateY(2px) rotate(-135deg)}
  .wl-telling{margin:0 0 10px;font-size:13px;font-weight:650;color:var(--ink-2);font-variant-numeric:tabular-nums}
  .wl-sorteer{margin-left:auto;display:flex;gap:10px;align-items:flex-end}
  .wl-veld{display:flex;flex-direction:column;gap:4px;min-width:0}
  .wl-veld label,.wl legend{font-size:12px;font-weight:700;color:var(--ink-2)}
  .wl select{font:inherit;font-size:13.5px;color:var(--ink);background:var(--surface-2);border:1px solid var(--muted);
    border-radius:10px;min-height:40px;padding:6px 10px;max-width:100%;cursor:pointer}
  .wl-paneel{background:var(--surface);border:1px solid var(--ring);border-radius:14px;box-shadow:var(--shadow);
    padding:16px 18px;margin:0 0 12px}
  .wl-paneel[hidden]{display:none}
  .wl-keuzes{display:flex;flex-wrap:wrap;gap:16px 28px}
  .wl-heel{flex-basis:100%}
  .wl fieldset{border:0;margin:0;padding:0;min-width:0}
  .wl legend{padding:0;margin:0 0 6px}
  .wl-opties{display:flex;flex-wrap:wrap;gap:6px}
  .wl-optie{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:6px 12px 6px 10px;border:1px solid var(--ring);
    border-radius:10px;background:var(--surface-2);font-size:13px;color:var(--ink);cursor:pointer;user-select:none}
  .wl-optie input{margin:0;width:16px;height:16px;flex:none;accent-color:var(--s1);cursor:pointer}
  .wl-kleur{width:10px;height:10px;border-radius:3px;flex:none}
  .wl-letter{font-weight:800}
  .wl-n{margin-left:2px;font-size:12px;font-weight:650;color:var(--ink-2);font-variant-numeric:tabular-nums}
  .wl-optie.nul{border-style:dashed;border-color:var(--baseline)}
  .wl-optie.nul .wl-naam,.wl-optie.nul .wl-letter{color:var(--ink-2)}
  @supports selector(:has(a)){
    .wl-optie:has(input:checked){border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1);
      background:color-mix(in srgb,var(--s1) 9%,var(--surface-2))}
    .wl-optie:has(input:checked) .wl-naam{font-weight:650}
    .wl-optie:has(input:focus-visible){outline:2px solid var(--s1);outline-offset:2px}
    .wl-optie input:focus-visible{outline:none}
  }
  /* getalvelden (VA-69): type="text" met 16 px, anders zoomt iOS in */
  .wl-bereiken{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:16px 20px;align-items:start;
    margin-top:16px;padding-top:14px;border-top:1px solid var(--grid)}
  .wl-hint{margin:-2px 0 6px;font-size:11.5px;color:var(--ink-2);font-variant-numeric:tabular-nums}
  .wl-invoer{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px}
  .wl-invoer label{display:block;font-size:11.5px;color:var(--ink-2);margin-bottom:3px}
  .wl-invoer input{width:100%;min-width:0;font:inherit;font-size:16px;min-height:40px;padding:6px 10px;color:var(--ink);
    background:var(--surface-2);border:1px solid var(--muted);border-radius:9px;font-variant-numeric:tabular-nums}
  .wl-invoer input[aria-invalid="true"]{border:2px solid var(--crit);padding:5px 9px}
  .wl-fout{margin:6px 0 0;font-size:12px;line-height:1.35;font-weight:600;color:var(--crit)}
  .wl-fout[hidden]{display:none}
  .wl-paneelvoet{display:none}
  .wl-toon{flex:1;min-height:44px;font:inherit;font-size:14px;font-weight:700;color:#fff;background:var(--knop);
    border:1px solid var(--knop-rand);border-radius:10px;cursor:pointer}
  .wl-chips{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 2px 10px}
  .wl-chips[hidden]{display:none}
  .wl-chip{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:4px 8px 4px 12px;border-radius:999px;
    border:1px solid var(--muted);background:var(--surface);color:var(--ink);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
  .wl-chip .x{font-size:16px;line-height:1;color:var(--ink-2)}
  @media (hover:hover){ .wl-chip:hover{background:var(--grid)} .wl-wis:hover{color:var(--ink-2)} }
  .wl-wis{font:inherit;font-size:12.5px;font-weight:650;color:var(--ink);background:none;border:0;padding:6px 6px;min-height:32px;
    text-decoration:underline;text-underline-offset:3px;cursor:pointer}
  .wl-bron{margin:0 2px 12px;font-size:11.5px;color:var(--ink-2)}
  .wl-leeg{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:0 0 14px;padding:16px 18px;
    background:var(--surface);border:1px solid var(--ring);border-radius:14px;box-shadow:var(--shadow)}
  .wl-leeg[hidden]{display:none}
  .wl-leeg p{margin:0;font-size:13.5px;color:var(--ink-2);flex:1 1 260px}
  .wl-leeg .wl-wis{text-decoration:none;background:var(--surface-2);border:1px solid var(--muted);border-radius:9px;padding:7px 12px;min-height:40px}
  .wl :is(button,select,input,a):focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  .wl .grid{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
  .wl .grid[hidden]{display:none}
  @container wl (min-width:720px){ .wl .grid{grid-template-columns:repeat(2,minmax(0,1fr))} }
  @container wl (max-width:599.98px){
    .wl-sorteer{margin-left:0;flex-basis:100%;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
    .wl-sorteer select{width:100%}
    .wl-telling{flex:1}
    .wl-paneel{padding:14px 14px 0}
    .wl-keuzes > *{flex-basis:100%}
    .wl-gem select{width:100%}
    .wl-optie{min-height:44px}
    .wl-bereiken{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px 14px}
    .wl-paneelvoet{display:flex;position:sticky;bottom:0;margin:14px -14px 0;padding:12px 14px;background:var(--surface);
      border-top:1px solid var(--grid);border-radius:0 0 14px 14px}
  }
  .schildwacht{height:1px}
  /* ---- KAART MET LUCHTFOTO (VA-71): een vast vlak, dus niets verschuift als de foto komt of faalt ---- */
  .card-foto{position:relative;width:100px;height:100px;border-radius:10px;overflow:hidden;background:var(--grid)}
  .card-foto.laadt{background:repeating-linear-gradient(135deg,var(--grid) 0 7px,color-mix(in srgb,var(--grid) 55%,var(--surface)) 7px 14px)}
  .card-foto img{display:block;width:100%;height:100%;object-fit:cover;opacity:0}
  .card-foto.geladen img{opacity:1}
  @media (prefers-reduced-motion: no-preference){ .card-foto.geladen img{transition:opacity .15s ease} }
  .card-foto .merk{display:none;position:absolute;left:50%;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;
    border:2px solid #fff;box-shadow:0 0 0 1.5px var(--crit);pointer-events:none}
  .card-foto.geladen .merk{display:block}
  .card-foto .melding{display:none;position:absolute;inset:0;align-items:center;justify-content:center;padding:6px;text-align:center;
    font-size:11px;line-height:1.25;font-weight:600;color:var(--ink-2)}
  .card-foto.mislukt,.card-foto.geen{background:var(--grid);box-shadow:inset 0 0 0 1px var(--baseline)}
  .card-foto.mislukt .melding,.card-foto.geen .melding{display:flex}
  @container kaart (max-width:380px){
    .card-top{grid-template-columns:84px minmax(0,1fr) auto;gap:10px}
    .card-foto{width:84px;height:84px}
  }
  /* ===================== BEWAREN EN VERBERGEN (VA-90) =====================
     Op elke kaart en in 'Open pand': Bewaar en Verberg. De stand staat in de knop met meer dan kleur:
     het woord, een icoon (ster leeg/vol, oog/gestippeld oog), de tweede regel, en aria-pressed.
     Vorm: Lumi's "Glazen duo" (knoppen-spec.md, variant A): één glazen strook met twee gelijke helften.
     Bewaard wordt het navy glas van de band met een gouden ster; Verborgen is gearceerd en gestippeld. */
  .bw-rij{display:flex;gap:0;margin-top:4px;padding:3px;border-radius:13px;
    background:linear-gradient(180deg,var(--surface-2),color-mix(in srgb,var(--s1) 5%,var(--surface-2)));
    border:1px solid color-mix(in srgb,var(--ink) 14%,transparent);box-shadow:inset 0 1px 0 var(--glans)}
  .bw-knop{flex:1 1 0;min-width:0;display:inline-flex;align-items:center;justify-content:center;gap:8px;
    min-height:44px;padding:6px 12px;border-radius:10px;border:1px solid transparent;background:transparent;
    color:var(--ink);font:inherit;font-size:13px;font-weight:650;cursor:pointer;position:relative;
    transition:background-color .15s,border-color .15s,box-shadow .15s,transform .08s}
  .bw-knop .bw-ico{flex:none;width:18px;height:18px;color:var(--ink-2)}
  .bw-knop .bw-tk{display:flex;flex-direction:column;line-height:1.2;min-width:0;text-align:left}
  .bw-knop .bw-terug{font-size:11px;font-weight:500;color:var(--ink-2)}
  .bw-knop .bw-terug:empty{display:none}
  .bw-knop+.bw-knop::before{content:"";position:absolute;left:-1px;top:10px;bottom:10px;width:1px;
    background:color-mix(in srgb,var(--ink) 12%,transparent)}
  .bw-knop[aria-pressed="true"]::before,.bw-knop[aria-pressed="true"]+.bw-knop::before{display:none}
  @media (hover:hover){
    .bw-knop:not([aria-disabled="true"]):hover{background:color-mix(in srgb,var(--s1) 9%,transparent)}
    .bw-knop:not([aria-disabled="true"]):hover .bw-ico{color:var(--s1)} }
  .bw-knop:focus-visible{outline:2px solid var(--s1);outline-offset:2px;z-index:1}
  .bw-knop:not([aria-disabled="true"]):active{transform:translateY(1px);
    background:color-mix(in srgb,var(--s1) 14%,transparent);
    box-shadow:inset 0 1px 3px color-mix(in srgb,var(--ink) 18%,transparent)}
  .bw-knop.bw-bewaar[aria-pressed="true"]{background:var(--held);color:#fff;
    border-color:color-mix(in srgb,var(--s1) 70%,transparent);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.14),0 6px 16px -8px var(--gloed)}
  .bw-knop.bw-bewaar[aria-pressed="true"] .bw-ico{color:var(--s4);
    filter:drop-shadow(0 0 5px color-mix(in srgb,var(--s4) 55%,transparent))}
  .bw-knop.bw-bewaar[aria-pressed="true"] .bw-terug{color:var(--nav-tekst)}
  @media (hover:hover){ .bw-knop.bw-bewaar[aria-pressed="true"]:hover{background:var(--held);filter:brightness(1.12)} }
  .bw-knop.bw-weg[aria-pressed="true"]{border:1px dashed var(--ink-2);color:var(--ink);
    background:repeating-linear-gradient(135deg,var(--grid) 0 6px,
      color-mix(in srgb,var(--grid) 55%,var(--surface-2)) 6px 12px)}
  .bw-knop.bw-weg[aria-pressed="true"] .bw-ico{color:var(--ink)}
  .bw-knop[aria-disabled="true"]{cursor:not-allowed;opacity:.55}
  @media (prefers-reduced-motion: reduce){ .bw-knop{transition:none} .bw-knop:active{transform:none} }
  .pand-bw .bw-rij{max-width:420px}
  .bw-label .bw-label-ico{flex:none;width:12px;height:12px}
  .bw-label{display:inline-flex;align-self:flex-start;width:max-content;max-width:100%;align-items:center;gap:4px;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;
    color:var(--ink);background:color-mix(in srgb,var(--s1) 12%,var(--surface-2));border:1px solid var(--s1)}
  .bw-label.weg{background:var(--grid);border:1px dashed var(--ink-2)}
  .bw-label[hidden]{display:none}
  .card.bw-is-weg{border-style:dashed;background:color-mix(in srgb,var(--grid) 35%,var(--surface))}
  .card.bw-is-weg .card-foto{opacity:.6}
  .bw-balk{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:0 0 12px;font-size:12.5px;color:var(--ink-2)}
  .bw-apparaat{margin:0;flex:1 1 280px}
  .bw-aantal{font-weight:650;color:var(--ink)}
  .bw-aantal[hidden],.bw-toon[hidden]{display:none}
  .bw-toon,.bw-ongedaan{font:inherit;font-size:12.5px;font-weight:650;min-height:34px;padding:4px 12px;border-radius:9px;
    border:1px solid var(--ring);background:var(--surface-2);color:var(--ink);cursor:pointer}
  .bw-toon.aan{border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1)}
  .bw-toon:focus-visible,.bw-ongedaan:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  .bw-status{flex-basis:100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;color:var(--ink)}
  /* Leeg blijft de statusregel in de toegankelijkheidsboom (Lumi §3): geen display:none, alleen geen hoogte.
     De -6px heft de rijafstand van de balk op, zodat een lege regel geen ruimte inneemt. */
  .bw-balk .bw-status:empty{margin-top:-6px}
  .pand-bw{margin:0 0 14px;padding:0 0 12px;border-bottom:1px solid var(--grid)}
  .pand-bw .bw-apparaat{margin:8px 0 0;font-size:12px;color:var(--ink-2)}
  .pand-bw .bw-status{font-size:12.5px}
  .pand-bw .bw-status:not(:empty){margin-top:6px}
  .wl-leeg .bw-leeg-toon{font:inherit;font-size:13px;font-weight:650;background:var(--surface-2);border:1px solid var(--ring);
    border-radius:9px;padding:7px 12px;min-height:40px;color:var(--ink);cursor:pointer}
  .wl-leeg .bw-leeg-toon:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
  /* ===================== einde BEWAREN EN VERBERGEN ===================== */
  /* ===================== BEWAARDE PANDEN (VA-91) =====================
     Een eigen deel tussen Voorraad en de werklijst. Een korte rij per pand, in de vorm van een kaart; geen
     luchtfoto. Alleen bestaande tokens; licht en donker komen daaruit. */
  .nav a .nav-n{margin-left:auto;font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.4;
    background:var(--nav-actief);color:#fff;border-radius:999px;padding:1px 8px}
  .nav a[aria-current] .nav-n{background:rgba(255,255,255,.22)}
  .nav a .nav-n[hidden]{display:none}
  .bwp-lijst{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
  .bwp-lijst[hidden]{display:none}
  .card.bwp-rij{flex-direction:row;flex-wrap:wrap;align-items:center;gap:10px 14px;padding:12px 14px}
  .card.bwp-rij.weg{border-style:dashed;border-color:var(--baseline)}
  .bwp-rij .score{width:44px;height:44px;border-radius:11px}
  .bwp-rij .score b{font-size:17px}
  .bwp-rij .score.onb b{font-size:10px;font-weight:700}
  .bwp-kern{flex:1 1 240px;min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:4px}
  .bwp-kern .addr{max-width:100%}
  .bwp-kern .lid{max-width:62ch}
  .bwp-rij > .bw-rij{flex:0 1 auto;margin-top:0;align-items:center;gap:8px 12px}
  /* VA-105: hier geen glazen strook (er staat een link naast één knop); de knop zelf is het glas van Bewaard. */
  .bwp-rij > .bw-rij{padding:0;background:none;border:0;box-shadow:none;border-radius:0}
  .bwp-rij > .bw-rij > .bw-knop{flex:0 1 auto}
  .bwp-rij .pand-open{display:inline-flex;align-items:center;min-height:38px}
  .bwp-rij .baglink{display:inline-block;padding:10px 0;line-height:18px}
  .bwp-rij .baglink:focus-visible{outline:2px solid var(--s1);outline-offset:2px;border-radius:4px}
  .bwp .wl-leeg{margin-bottom:0}
  .bwp .bw-toon{margin-top:12px}
  @container kaart (max-width:520px){ .bwp-rij > .bw-rij{flex-basis:100%} }

  /* ---- Een eigen pagina (Ayman 11-17: "op een aparte speciale, coole, hightech pagina") ----
     Een deel met .pagina staat niet in de lange scroll: het menu zet .op-pagina op .vg en .nu op dat deel,
     en dan is alleen dat deel te zien. Zonder .op-pagina is het er niet. */
  .vg:not(.op-pagina) .inhoud > .deel.pagina{display:none}
  .vg.op-pagina .inhoud > .deel:not(.nu){display:none}
  .vg.op-pagina .inhoud > .deel.nu{margin-top:0}
  .bwp-pagina{--mono:ui-monospace,"Cascadia Code","SF Mono",Consolas,monospace}
  .kop.bwp-held{position:relative;isolation:isolate;overflow:hidden;margin:0 0 22px;padding:26px 28px 24px;gap:8px;
    border-radius:22px;background:var(--held);color:#fff;box-shadow:var(--schaduw-hoog);
    border:1px solid color-mix(in srgb,var(--s1) 30%,transparent)}
  .bwp-held::before{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;
    background-image:linear-gradient(rgba(255,255,255,.07) 1px,transparent 1px),
                     linear-gradient(90deg,rgba(255,255,255,.07) 1px,transparent 1px);
    background-size:30px 30px;background-position:-1px -1px;
    -webkit-mask-image:radial-gradient(120% 90% at 85% 0%,#000 25%,transparent 80%);
            mask-image:radial-gradient(120% 90% at 85% 0%,#000 25%,transparent 80%)}
  .bwp-held::after{content:"";position:absolute;z-index:-1;pointer-events:none;width:520px;height:520px;right:-160px;top:-260px;
    border-radius:50%;background:radial-gradient(closest-side,var(--gloed),transparent)}
  .bwp-scan{position:absolute;left:0;right:0;top:0;height:90px;z-index:-1;pointer-events:none;opacity:0;
    background:linear-gradient(180deg,transparent,color-mix(in srgb,var(--s1) 22%,transparent) 85%,
               color-mix(in srgb,#9fd0ff 70%,transparent) 99%,transparent)}
  @media (prefers-reduced-motion: no-preference){
    .bwp-scan{animation:bwp-scan 7s cubic-bezier(.45,0,.55,1) infinite}
    .bwp-ring{animation:bwp-draai 14s linear infinite}
    .bwp-puls{animation:bwp-puls 2.4s ease-in-out infinite}
  }
  @keyframes bwp-scan{0%{transform:translateY(-100%);opacity:0}12%{opacity:1}70%{opacity:.8}100%{transform:translateY(420%);opacity:0}}
  @keyframes bwp-draai{to{transform:rotate(1turn)}}
  @keyframes bwp-puls{0%,100%{opacity:.35;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}
  .bwp-held .kop-rij{position:relative}
  .bwp-held .kruimel{color:var(--nav-label)}
  .bwp-held .kruimel b{color:#fff}
  .bwp-held .kop-meta{color:var(--nav-tekst);font-family:var(--mono);font-size:11.5px;letter-spacing:.04em}
  .bwp-sys{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;
    text-transform:uppercase;color:#9fd0ff}
  .bwp-sys i{width:7px;height:7px;border-radius:50%;background:#5fe3b0;box-shadow:0 0 0 3px rgba(95,227,176,.18),0 0 12px #5fe3b0}
  .bwp-kopkern{display:flex;align-items:center;gap:20px;margin-top:6px}
  .bwp-embleem{position:relative;flex:none;width:84px;height:84px;display:grid;place-items:center}
  .bwp-ring{position:absolute;inset:0;border-radius:50%;
    background:conic-gradient(from 0deg,transparent 0 55%,color-mix(in srgb,var(--s1) 80%,#fff) 80%,#fff 86%,transparent 87%);
    -webkit-mask:radial-gradient(closest-side,transparent calc(100% - 3px),#000 calc(100% - 2px));
            mask:radial-gradient(closest-side,transparent calc(100% - 3px),#000 calc(100% - 2px))}
  .bwp-embleem::before{content:"";position:absolute;inset:9px;border-radius:50%;border:1px dashed rgba(255,255,255,.22)}
  .bwp-embleem::after{content:"";position:absolute;inset:18px;border-radius:50%;
    background:radial-gradient(closest-side,color-mix(in srgb,var(--s4) 45%,transparent),transparent)}
  .bwp-embleem svg{position:relative;z-index:1;width:34px;height:34px;color:var(--s4);filter:drop-shadow(0 0 10px color-mix(in srgb,var(--s4) 70%,transparent))}
  .bwp-held .titel{color:#fff;font-size:34px;letter-spacing:-.03em}
  .bwp-held .kop-zin{color:var(--nav-tekst);max-width:70ch}
  .bwp-tel{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:18px}
  .bwp-tegel{position:relative;padding:13px 14px 12px;border-radius:14px;min-width:0;
    background:linear-gradient(180deg,rgba(255,255,255,.09),rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.13);
    -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
  .bwp-tegel::before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;
    background:linear-gradient(90deg,transparent,rgba(159,208,255,.8),transparent)}
  .bwp-tegel b{display:block;font-family:var(--mono);font-size:28px;font-weight:700;line-height:1.05;letter-spacing:-.02em;
    font-variant-numeric:tabular-nums;color:#fff}
  .bwp-tegel b small{font-size:13px;font-weight:600;color:var(--nav-label);margin-left:2px}
  .bwp-tegel span{display:block;margin-top:5px;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
    color:var(--nav-label);overflow-wrap:anywhere}
  .bwp-tegel.eerste b{color:#ffd46b;text-shadow:0 0 18px color-mix(in srgb,var(--s4) 60%,transparent)}
  .bwp-cat{position:relative;margin-top:14px}
  .bwp-cat > p{margin:0 0 7px;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--nav-label)}
  .bwp-staaf{display:flex;height:10px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.08);
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}
  .bwp-staaf i{display:block;height:100%;transition:flex-grow .5s cubic-bezier(.2,.7,.2,1)}
  .bwp-staaf i + i{box-shadow:-2px 0 0 #0b1a2e}
  .bwp-leg{display:flex;flex-wrap:wrap;gap:6px 14px;margin:8px 0 0;padding:0;list-style:none;font-family:var(--mono);
    font-size:11.5px;color:var(--nav-tekst)}
  .bwp-leg li{display:inline-flex;align-items:center;gap:6px}
  .bwp-leg li i{width:9px;height:9px;border-radius:3px}
  .bwp-terug{position:relative;align-self:flex-start;display:inline-flex;align-items:center;gap:8px;margin-top:16px;
    padding:9px 14px;border-radius:999px;font-size:13px;font-weight:700;color:#fff;text-decoration:none;
    background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18)}
  @media (hover:hover){ .bwp-terug:hover{background:rgba(255,255,255,.16)} }
  .bwp-terug:focus-visible{outline:2px solid #fff;outline-offset:2px}
  /* de lijst op de pagina: kaarten in een raster, met een scorering en een lichtlijn */
  .bwp-pagina .bwp-lijst{grid-template-columns:repeat(auto-fill,minmax(min(100%,400px),1fr));gap:12px}
  .bwp-pagina .card.bwp-rij{position:relative;overflow:hidden;padding:16px;align-items:flex-start;
    transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
  .bwp-pagina .card.bwp-rij::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;
    background:linear-gradient(90deg,var(--s1),var(--s3) 60%,transparent)}
  .bwp-pagina .card.bwp-rij.weg::before{background:repeating-linear-gradient(90deg,var(--baseline) 0 8px,transparent 8px 14px)}
  @media (hover:hover){ .bwp-pagina .card.bwp-rij:hover{transform:translateY(-2px);box-shadow:var(--schaduw-hoog);
    border-color:color-mix(in srgb,var(--s1) 35%,var(--ring))} }
  .bwp-pagina .bwp-rij .score{width:54px;height:54px;border-radius:50%;position:relative;
    background:conic-gradient(var(--s1) calc(var(--p,0) * 1%),color-mix(in srgb,var(--brand) 18%,var(--grid)) 0)}
  .bwp-pagina .bwp-rij .score::before{content:"";position:absolute;inset:4px;border-radius:50%;background:var(--brand)}
  .bwp-pagina .bwp-rij .score > *{position:relative}
  .bwp-pagina .bwp-rij .score b{font-family:var(--mono);font-size:17px}
  .bwp-pagina .bwp-rij .score small{font-size:7.5px}
  .bwp-pagina .bwp-rij > .bw-rij{flex-basis:100%;padding-top:12px;border-top:1px solid var(--ring)}
  .bwp-pagina .bwp-rij .lid{font-family:var(--mono);font-size:11px}
  @media (max-width:800px){
    .kop.bwp-held{padding:20px 18px 18px;border-radius:18px}
    .bwp-held .titel{font-size:27px}
    .bwp-embleem{width:62px;height:62px}
    .bwp-embleem svg{width:26px;height:26px}
    .bwp-kopkern{gap:14px}
    .bwp-tel{grid-template-columns:repeat(2,minmax(0,1fr))}
    .bwp-tegel b{font-size:24px}
  }
  /* ===================== einde BEWAARDE PANDEN ===================== */
  /* ===================== SLOT (VA-96): de panden na de eerste n, achter één blok ===================== */
  .slot-blok{position:relative;margin-top:14px;border-radius:14px;overflow:hidden;border:1px solid var(--ring);
    background:var(--surface)}
  .slot-schim{padding:14px;filter:blur(2px);opacity:.6;pointer-events:none;user-select:none}
  .slot-kaart{display:flex;flex-direction:column;gap:10px;min-height:190px;padding:16px;border-radius:14px;
    border:1px solid var(--ring);background:var(--surface-2)}
  .slot-kaart i{display:block;height:12px;border-radius:6px;background:var(--grid)}
  .slot-kaart i:nth-child(1){width:55%;height:16px}
  .slot-kaart i:nth-child(2){width:35%}
  .slot-kaart i:nth-child(3){width:100%;height:8px;margin-top:auto}
  .slot-kaart i:nth-child(4){width:80%}
  .slot-kaart:nth-child(n+3){display:none}
  .slot-paneel{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:12px;padding:20px;text-align:center;background:color-mix(in srgb,var(--surface) 62%,transparent)}
  .slot-icoon{display:grid;place-items:center;width:46px;height:46px;border-radius:50%;background:var(--brand);color:#fff;
    box-shadow:0 0 0 6px color-mix(in srgb,var(--brand) 12%,transparent)}
  .slot-tekst{margin:0;max-width:46ch;font-size:14px;line-height:1.5;color:var(--ink-2)}
  .slot-tekst b{display:block;margin-bottom:2px;font-size:16px;color:var(--ink)}
  @media (max-width:900px){ .slot-kaart:nth-child(n+2){display:none} }
  /* ===================== einde SLOT ===================== */
  /* ===================== einde WERKLIJST ===================== */
</style>
</head>
<body>
<a class="skip" href="#inhoud">Sla het menu over</a>
<div class="vg" id="vg">
  <header class="topbalk">
    <div class="mark">LEVRAI GROUP<small>VASTGOED</small></div>
    <button class="menuknop" type="button" aria-expanded="false" aria-controls="menu"><span class="streep" aria-hidden="true"></span>Menu</button>
  </header>
  <div class="scrim" aria-hidden="true"></div>

  <aside class="side" id="menu" aria-label="Menu">
    <div class="side-kop">
      <div class="merk">
        <div class="mark">LEVRAI GROUP<small>VASTGOED</small></div>
        <p class="merk-sub">Pandenselectie&nbsp;·&nbsp;__LABEL__</p>
      </div>
      <button class="sluit-menu" type="button"><span aria-hidden="true">×</span>Sluit menu</button>
    </div>
    <nav class="nav" aria-label="Onderdelen van het dashboard">__MENU__</nav>
    <div class="side-voet">
      <button class="toggle" id="themeBtn" type="button">◐ Thema</button>
      <!-- VA-106: uitloggen via serve.py (VA-50), alleen met POST; een gewoon formulier, werkt zonder JavaScript -->
      <form class="uitlog" method="post" action="/uitloggen"><button class="toggle" type="submit">Uitloggen</button></form>
    </div>
  </aside>

  <main class="inhoud" id="inhoud" tabindex="-1">

    <section class="deel" id="kantoor" aria-labelledby="t-kantoor" tabindex="-1">
      <div class="kantoor-kop__BAND__">
      <header class="kop">
        <div class="kop-rij">
          <p class="kruimel">Levrai Vastgoed<span aria-hidden="true">/</span><b>Kantoor</b></p>
          <div class="spills">
            <div class="pill">__BRONPIL__</div>
            <div class="pill"__PEILTIP__>__PEILDATUM__</div>
          </div>
        </div>__PLANNING__
        <h1 id="t-kantoor" class="vh">__KOP_KANTOOR_TITEL__</h1>
      </header>__TRAP____KAART__
      </div>
      <div class="pk" id="pk">
        <div class="pk-scene pk-start">
          <canvas aria-hidden="true"></canvas>
          <div class="pk-ov"></div>
        </div>
        <div class="pk-balk" role="group" aria-label="Uitleg per medewerker">__WERKBALK__</div>
        <div class="pk-uitleg" id="pk-uitleg" hidden aria-live="polite">
          <h3></h3>
          <p class="pk-status"></p>
          <p class="pk-tekst"></p>
          <button class="pk-sluit" type="button">Sluit uitleg</button>
        </div>
        <div class="pk-voet">De kantoormanager loopt naar wie je aandacht vraagt. Klik op iemand in het kantoor of op een naam hierboven voor uitleg.</div>
      </div>
    </section>

    <section class="deel" id="kerncijfers" aria-labelledby="t-kerncijfers" tabindex="-1">
      <header class="kop">
        <div class="kop-rij"><p class="kruimel">Levrai Vastgoed<span aria-hidden="true">/</span><b>Kerncijfers</b></p></div>
        <h2 class="titel" id="t-kerncijfers">__KOP_KERNCIJFERS_TITEL__</h2>
        <p class="kop-zin">__KOP_KERNCIJFERS_ZIN__</p>
      </header>
      <div class="kpis" id="kpis"></div>
    </section>

    <section class="deel" id="voorraad" aria-labelledby="t-voorraad" tabindex="-1">
      <header class="kop">
        <div class="kop-rij"><p class="kruimel">Levrai Vastgoed<span aria-hidden="true">/</span><b>Voorraad</b></p></div>
        <h2 class="titel" id="t-voorraad">__KOP_VOORRAAD_TITEL__</h2>
        <p class="kop-zin">__KOP_VOORRAAD_ZIN__</p>
      </header>
      <div class="cols">
        <div class="panel">
          <h3>Technische voorraad naar categorie</h3>
          <p class="cap">__LABEL__ · panden binnen categorie A–E · een pand kan in meerdere vallen</p>
          <div id="cats"></div>
        </div>
        <div class="panel">
          <h3>__FEITEN_TITEL__</h3>
          <p class="cap">__FEITEN_CAP__</p>
          <div class="facts" id="facts"></div>
          <p class="note">Score is een <b>index van 1–100</b> tegen het volledige modelbudget.
            Open een pand voor de volledige score-opbouw per criterium.</p>
        </div>
      </div>
    </section>
    <section class="deel" id="__LIJST__" aria-labelledby="t-__LIJST__" tabindex="-1">
      <header class="kop">
        <div class="kop-rij">
          <p class="kruimel">Levrai Vastgoed<span aria-hidden="true">/</span><b>__LIJST_NAAM__</b></p>
          <span class="kop-meta" id="secmeta">__KOP_LIJST_META__</span>
        </div>
        <h2 class="titel" id="t-__LIJST__">__KOP_LIJST_TITEL__</h2>
        <p class="kop-zin">__KOP_LIJST_ZIN__</p>
      </header>
      <div class="wl">
        __FILTER__
        <!-- BEWAREN EN VERBERGEN (VA-90) -->
        <div class="bw-balk" id="bwBalk">
          <p class="bw-apparaat" id="bwApparaat"></p>
          <span class="bw-aantal" id="bwAantal" hidden></span>
          <button class="bw-toon" id="bwToon" type="button" hidden></button>
          <div class="bw-status" id="bwStatus" role="status"></div>
        </div>
        <!-- einde BEWAREN EN VERBERGEN -->
        <div class="grid" id="leads"></div>__SLOT__
        <div class="schildwacht" aria-hidden="true"></div>
      </div>

      <p class="foothint">
        Klik op <b>Score-opbouw</b> in een pand om te zien waar elk punt vandaan komt ·
        grijze criteria wachten op een extra databron (energielabel, verkoophistorie, leegstand).
      </p>
    </section>
__BEWAARD__
  </main>
</div>
<div id="tt"></div>

<dialog class="pand" id="pand" aria-labelledby="pandTitel">
  <div class="pand-kop">
    <div><h2 id="pandTitel"></h2><p id="pandSub"></p></div>
    <div class="score" id="pandScore"></div>
    <button class="pand-sluit" type="button" id="pandSluit">Sluiten</button>
  </div>
  <div class="pand-romp" id="pandRomp"></div>
</dialog>
<script>
const PAYLOAD = __PAYLOAD__;
/* ============================ LANDKAART (VA-85) ============================
   Eén 2D-canvas onder de hele band, geen bibliotheek, niets van buiten. Lumi's drie richtingen samen:
   A de stroom die langs de vijf cijfers dunner wordt, B het brein (categorie A–E rond de kern),
   C de kaart met de werklijstpanden die via hun gemeente naar de kern vuren. Alles wat er staat komt
   kant-en-klaar uit PAYLOAD.kaart (Python); het script tekent alleen. Beweging verminderen: één stil
   beeld met alles erop. Buiten beeld of in een verborgen tabblad: pauze. */
(() => {
  const K = PAYLOAD.kaart, cv = document.getElementById("landkaart");
  if (!K || !cv) return;
  const D = document, R = D.documentElement, M = Math, TAU = M.PI * 2, band = cv.parentNode;
  const vlak = band.querySelector(".kaart-vlak"), cijfers = [...band.querySelectorAll(".trap li")];
  const ctx = cv.getContext("2d"), tip = D.getElementById("kaartTip"), bg = D.createElement("canvas"), bx = bg.getContext("2d");
  const rm = matchMedia("(prefers-reduced-motion: reduce)");
  const X0 = 3.3, Y0 = 53.62, CL = .613, EW = 2.45, EH = 2.92;   // kader van de kaart in graden; CL = cos 52°
  let W = 0, H = 0, dpr = 1, zicht = true, raf = 0, last = 0, klok = 0, acc1 = 0, acc2 = 0, rt = 0;
  let kl = {}, gloed = {}, vk = null, kern = null, rr = 40, G = [], S = [], C = [], poort = [], ring = [], P = [], A = [], V = [], T = [];
  const F = (w, s) => w + " " + s + "px system-ui,-apple-system,Segoe UI,sans-serif";
  const rgba = (h, a) => { const n = parseInt(h.slice(1), 16); return "rgba(" + (n >> 16) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")"; };
  const rond = (x, k, px, py, r, a) => { x.globalAlpha = a; x.fillStyle = k; x.beginPath(); x.arc(px, py, r, 0, TAU); x.fill(); };
  const cirkel = (x, k, px, py, r, a, w) => { x.globalAlpha = a; x.strokeStyle = k; x.lineWidth = w; x.beginPath(); x.arc(px, py, r, 0, TAU); x.stroke(); };
  const lijn = (x, k, a, w, p, q) => { x.globalAlpha = a; x.strokeStyle = k; x.lineWidth = w; x.beginPath(); x.moveTo(p[0], p[1]); x.lineTo(q[0], q[1]); x.stroke(); };
  const tekst = (x, s, px, py, f, k, al) => { x.globalAlpha = 1; x.font = f; x.fillStyle = k; x.textAlign = al; x.fillText(s, px, py); };
  const kies = w => { let s = 0; for (const x of w) s += x; let r = M.random() * s; for (let i = 0; i < w.length; i++) if ((r -= w[i]) <= 0) return i; return w.length - 1; };
  function spriet(c) {   // zachte gloed per kleur, één keer gemaakt
    if (gloed[c]) return gloed[c];
    const s = D.createElement("canvas"); s.width = s.height = 64;
    const x = s.getContext("2d"), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, rgba(c, 1)); g.addColorStop(.25, rgba(c, .45)); g.addColorStop(1, rgba(c, 0));
    x.fillStyle = g; x.fillRect(0, 0, 64, 64); return gloed[c] = s;
  }
  const blob = (x, c, px, py, r, a) => { if (a <= 0) return; x.globalAlpha = M.min(1, a); x.drawImage(spriet(c), px - r, py - r, 2 * r, 2 * r); };
  // Een boog van p naar q (kwadratisch, als kubisch bewaard), en het punt op t; h = 0 is een rechte lijn.
  const boog = (p, q, h, v) => { const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2 - M.abs(q[0] - p[0]) * h];
    return {p, q, a: [p[0] + (m[0] - p[0]) * 2 / 3, p[1] + (m[1] - p[1]) * 2 / 3], b: [q[0] + (m[0] - q[0]) * 2 / 3, q[1] + (m[1] - q[1]) * 2 / 3],
      d: M.max(.2, M.hypot(q[0] - p[0], q[1] - p[1]) / (v || 70))}; };
  const op = (s, t) => { const u = 1 - t, f = i => u * u * u * s.p[i] + 3 * u * u * t * s.a[i] + 3 * u * t * t * s.b[i] + t * t * t * s.q[i]; return [f(0), f(1)]; };
  const trek = (x, s) => { x.moveTo(s.p[0], s.p[1]); x.bezierCurveTo(s.a[0], s.a[1], s.b[0], s.b[1], s.q[0], s.q[1]); };
  const plek = el => { const r = el.getBoundingClientRect(), b = band.getBoundingClientRect(); return {x: r.left - b.left, y: r.top - b.top, w: r.width, h: r.height}; };

  function kleuren() {   // uit de tokens, dus mee met het thema; de kern is --brand-2 (CSS: color van het canvas)
    const cs = getComputedStyle(R), v = n => cs.getPropertyValue(n).trim();
    kl = {s: ["--s1", "--s2", "--s3", "--s4", "--s5"].map(v), t2: v("--nav-tekst"), t3: v("--nav-label"), kern: getComputedStyle(cv).color};
    gloed = {};
  }
  function bouw() {
    const x = bx;
    // Het raster van de commandokamer.
    x.strokeStyle = "#ffffff"; x.lineWidth = 1; x.globalAlpha = .04; x.beginPath();
    for (let i = 28; i < W; i += 28) { x.moveTo(i + .5, 0); x.lineTo(i + .5, H); }
    for (let j = 28; j < H; j += 28) { x.moveTo(0, j + .5); x.lineTo(W, j + .5); }
    x.stroke(); x.globalAlpha = .16; x.beginPath();
    for (let i = 112; i < W; i += 112) for (let j = 112; j < H; j += 112) { x.moveTo(i - 3, j + .5); x.lineTo(i + 4, j + .5); x.moveTo(i + .5, j - 3); x.lineTo(i + .5, j + 4); }
    x.stroke();
    // De kaart (C), in het vrijgehouden vlak.
    vk = plek(vlak);
    // Het brein steekt links buiten de kaart uit (ring plus letters, ca. 0,03 × schaal + 22 px); smal is daar geen ruimte, dan schuift de kaart in.
    const ruim = vk.x > 60, sc = ruim ? M.min(vk.w / EW, vk.h / EH) : M.min((vk.w - 22) / (EW + .03), vk.h / EH);
    const extra = ruim ? 0 : .03 * sc + 22, ox = vk.x + extra + (vk.w - extra - EW * sc) / 2, oy = vk.y + (vk.h - EH * sc) / 2;
    const pr = ll => [ox + ((ll[1] / 100 + 3) - X0) * CL * sc, oy + (Y0 - (ll[0] / 100 + 50)) * sc];
    const k = pr(K.kern.ll);
    // De kern is groot genoeg voor het woord "Werklijst"; de ring van A–E blijft er ruim omheen.
    x.font = F(750, 10.5);
    kern = {x: k[0], y: k[1], r: M.max(13, sc * .095, x.measureText(K.kern.label).width / 2 + 6), f: 0, tip: K.kern.tip};
    rr = M.max(30, sc * .3, kern.r + 18);
    x.beginPath();
    for (const r of K.land) for (let i = 0; i < r.length; i += 2) { const p = pr([r[i], r[i + 1]]); i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1]); }
    x.closePath();
    const vul = x.createLinearGradient(0, oy, 0, oy + EH * sc); vul.addColorStop(0, "rgba(255,255,255,.11)"); vul.addColorStop(1, "rgba(255,255,255,.04)");
    x.globalAlpha = 1; x.fillStyle = vul; x.fill("evenodd");
    x.shadowColor = kl.s[0]; x.shadowBlur = 14; x.strokeStyle = rgba(kl.t2, .7); x.lineWidth = 1.2; x.stroke(); x.shadowBlur = 0;
    // Gemeenten en hun lijnen naar de kern.
    G = K.gm.map(g => { if (!g.ll) return null; const p = pr(g.ll);
      return {x: p[0], y: p[1], n: g.n, r: g.n ? 1.8 + M.sqrt(g.n) * .5 : 2, f: 0, tip: g.tip, naam: g.naam, v: g.v, lab: g.lab, weg: g.n ? boog(p, k, .28) : null}; });
    const meeste = M.max(1, ...G.map(g => g ? g.n : 0));
    for (const g of G) if (g && g.weg) { x.globalAlpha = .07 + .3 * M.sqrt(g.n / meeste); x.strokeStyle = kl.s[0]; x.lineWidth = 1; x.beginPath(); trek(x, g.weg); x.stroke(); }
    // Het brein (B): categorie A–E in een ring om de kern.
    const cmax = M.max(1, ...K.cats.map(c => c.n));
    C = K.cats.map((c, i) => { const h = -M.PI / 2 - i * TAU / 5;
      return {x: k[0] + M.cos(h) * rr, y: k[1] + M.sin(h) * rr, h, r: 3.5 + M.sqrt(c.n / cmax) * 5, c: kl.s[i], k: c.k, n: c.n, f: 0, tip: c.tip}; });
    cirkel(x, "#ffffff", k[0], k[1], rr, .12, 1);
    for (const c of C) { lijn(x, c.c, .35, 1.2, [c.x, c.y], k);
      blob(x, c.c, c.x, c.y, c.r * 3, .35); rond(x, c.c, c.x, c.y, c.r, 1);
      tekst(x, c.k, c.x + M.cos(c.h) * (c.r + 9), c.y + M.sin(c.h) * (c.r + 9) + 4, F(800, 11), kl.t2, "center"); }
    // De 500 werklijstpanden: gloed, stip en een ring voor score ≥ drempel.
    S = []; x.globalCompositeOperation = "lighter";
    for (let i = 0; i < K.pt.length; i += 4) {
      const p = pr([K.pt[i], K.pt[i + 1]]), c = K.pt[i + 2], s = {x: p[0], y: p[1], c: kl.s[c % 5], g: K.pt[i + 3]};
      S.push(s); blob(x, s.c, s.x, s.y, 6, .4); rond(x, s.c, s.x, s.y, 1.5, 1);
      if (c >= 5) cirkel(x, s.c, s.x, s.y, 3.2, .45, .8);
    }
    x.globalCompositeOperation = "source-over";
    for (const g of G) if (g) { x.setLineDash(g.n ? [] : [2, 2]); cirkel(x, "#ffffff", g.x, g.y, g.r + 1.5, g.n ? .6 : .35, 1); x.setLineDash([]); }
    // Naam en aantal bij de grootste: de westelijke helft links van het punt, de rest rechts; per kant de zuidelijkste lager.
    const lab = G.filter(g => g && g.lab).sort((a, b) => a.x - b.x), helft = lab.length / 2;
    lab.forEach((g, i) => { const links = i < helft, kant = lab.filter((h, j) => (j < helft) === links);
      const omlaag = kant.length > 1 && g.y === M.max(...kant.map(h => h.y)), px = g.x + (links ? -1 : 1) * (g.r + 6), py = g.y + (omlaag ? 13 : 4);
      x.font = F(500, 11.5); const wv = x.measureText(" " + g.v).width; x.font = F(700, 11.5); const wn = x.measureText(g.naam).width;
      const start = M.max(2, M.min(W - 2 - wn - wv, links ? px - wn - wv : px));
      tekst(x, g.naam, start, py, F(700, 11.5), "#ffffff", "left"); tekst(x, " " + g.v, start + wn, py, F(500, 11.5), kl.t2, "left"); });
    // De stroom (A): een kanaal links van de cijfers, dat na elk cijfer smaller wordt, en dan naar het brein.
    poort = cijfers.map((li, i) => { const r = plek(li); return {x: r.x - 13, y: r.y + r.h / 2, tx: r.x, w: 1 + 4 * K.breed[i] / 100, f: 0}; });
    if (poort.length) {
      const begin = [poort[0].x, poort[0].y - 34];
      ring = [boog(begin, [poort[0].x, poort[0].y], 0, 90)];
      for (let i = 1; i < poort.length; i++) ring.push(boog([poort[i - 1].x, poort[i - 1].y], [poort[i].x, poort[i].y], 0, 90));
      lijn(x, "#ffffff", .1, poort[0].w, begin, [poort[0].x, poort[0].y]);
      poort.forEach((q, i) => { if (i) lijn(x, "#ffffff", .12, q.w, [poort[i - 1].x, poort[i - 1].y], [q.x, q.y]);
        lijn(x, kl.s[0], .4, 1, [q.x, q.y], [q.tx, q.y]); rond(x, kl.s[0], q.x, q.y, 2.6, .9); });
      const e = poort[poort.length - 1];
      for (const c of C) { const s = boog([e.x, e.y], [c.x, c.y], -.22, 140); x.globalAlpha = .2; x.strokeStyle = c.c; x.lineWidth = 1.2; x.beginPath(); trek(x, s); x.stroke(); c.weg = s; }
    }
    x.globalAlpha = 1;
  }
  // Een werklijstpand licht op en vuurt via zijn gemeente (of van elders rechtstreeks) naar de kern (C).
  function puls() {
    const s = S[M.random() * S.length | 0]; if (!s) return;
    T.push({x: s.x, y: s.y, c: s.c, t: 0});
    const g = s.g >= 0 ? G[s.g] : null, p = [s.x, s.y];
    const weg = g && g.weg ? [Object.assign(boog(p, [g.x, g.y], 0), {d: .5, eind: g}), Object.assign({}, g.weg, {eind: kern})]
      : [Object.assign(boog(p, [kern.x, kern.y], .28), {eind: kern})];
    P.push({weg, i: 0, t: 0, c: s.c, r: 1.6});
  }
  // Een deeltje in de stroom (A): grijs tot 'in A–E', dan de kleur van zijn categorie; na het laatste cijfer naar het brein.
  function deeltje() { if (ring.length) A.push({i: 0, t: 0, c: kl.t3, cat: -1}); }
  function stap(dt) {
    klok += dt; acc1 += dt * 12; acc2 += dt * 26;
    while (acc1 >= 1) { acc1--; if (P.length < 110) puls(); }
    while (acc2 >= 1) { acc2--; if (A.length < 140) deeltje(); }
    for (let i = P.length - 1; i >= 0; i--) { const p = P[i]; p.t += dt / p.weg[p.i].d;
      if (p.t >= 1) { p.weg[p.i].eind.f = 1; p.i++; p.t = 0; if (p.i >= p.weg.length) P.splice(i, 1); } }
    for (let i = A.length - 1; i >= 0; i--) { const a = A[i], w = a.weg ? a.weg[0] : ring[a.i]; a.t += dt / w.d;
      if (a.t < 1) continue;
      if (a.weg) { a.weg[0].eind.f = 1; a.weg.shift(); a.t = 0; if (!a.weg.length) A.splice(i, 1); continue; }
      const q = poort[a.i]; q.f = M.max(q.f, .6); a.t = 0;
      // Wie bij dit cijfer afvalt, zakt grijs weg; de rest gaat door. Niet op schaal: (volgende / dit) ^ 0,3.
      const blijft = a.i + 1 >= poort.length ? 1 : M.pow((K.ruw[a.i + 1] || 0) / M.max(1, K.ruw[a.i]), .3);
      if (M.random() > blijft) { V.push({x: q.x, y: q.y, vx: -14 - M.random() * 18, vy: 6 + M.random() * 16, c: a.c, t: 0}); A.splice(i, 1); continue; }
      if (a.i === 2) { a.cat = kies(C.map(c => c.n)); a.c = C[a.cat].c; }
      if (a.i + 1 < poort.length) { a.i++; continue; }
      const c = C[a.cat < 0 ? 0 : a.cat];
      a.weg = [Object.assign({}, c.weg, {eind: c}), Object.assign(boog([c.x, c.y], [kern.x, kern.y], 0), {eind: kern})];
    }
    for (let i = V.length - 1; i >= 0; i--) { const v = V[i]; v.t += dt; v.x += v.vx * dt; v.y += v.vy * dt; if (v.t >= 1) V.splice(i, 1); }
    for (let i = T.length - 1; i >= 0; i--) if ((T[i].t += dt) >= 1) T.splice(i, 1);
    for (const n of G.concat(C, poort, kern)) if (n && n.f) n.f = M.max(0, n.f - dt * 1.6);
  }
  const kop = (p, s, t, c, r) => { const h = op(s, t), b = op(s, M.max(0, t - .16));
    lijn(ctx, c, .45, r * 1.3, b, h); blob(ctx, c, h[0], h[1], r * 4, .6); rond(ctx, c, h[0], h[1], r, 1); };
  function teken() {
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, cv.width, cv.height); ctx.drawImage(bg, 0, 0); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalCompositeOperation = "lighter"; ctx.lineCap = "round";
    if (!rm.matches) {   // de scanlijn: langzaam van boven naar beneden over de kaart
      const y = vk.y + (klok / 7 % 1) * vk.h, g = ctx.createLinearGradient(0, y - 46, 0, y);
      g.addColorStop(0, rgba(kl.s[0], 0)); g.addColorStop(1, rgba(kl.s[0], .16));
      ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(vk.x, y - 46, vk.w, 46); lijn(ctx, kl.t2, .35, 1, [vk.x, y], [vk.x + vk.w, y]);
    }
    ctx.setLineDash([3, 5]); ctx.lineDashOffset = -klok * 9; cirkel(ctx, kl.s[0], kern.x, kern.y, M.max(rr * .62, kern.r + 5), .55, 1.2); ctx.setLineDash([]); ctx.lineDashOffset = 0;
    ctx.fillStyle = "#ffffff";
    for (let i = 0; i < 72; i++) { const h = i * 2.39996 + klok * .05 * (i % 2 ? 1 : -1), r = rr * (1.3 + (i * 37 % 30) / 100);
      ctx.globalAlpha = .28; ctx.fillRect(kern.x + M.cos(h) * r - .7, kern.y + M.sin(h) * r - .7, 1.4, 1.4); }
    blob(ctx, kl.s[0], kern.x, kern.y, kern.r * 2.8 + (rm.matches ? 0 : 3 + 3 * M.sin(klok * 1.6)), .5 + kern.f * .3);
    for (const g of G) if (g && g.f) blob(ctx, kl.s[0], g.x, g.y, g.r * 4, g.f * .6);
    for (const c of C) if (c.f) blob(ctx, c.c, c.x, c.y, c.r * 3.5, c.f * .7);
    for (const q of poort) if (q.f) blob(ctx, kl.s[0], q.x, q.y, 9, q.f * .8);
    for (const w of T) { const a = M.sin(M.PI * w.t); blob(ctx, w.c, w.x, w.y, 9, a * .7); cirkel(ctx, w.c, w.x, w.y, 2 + w.t * 8, a * .7, 1); }
    for (const p of P) kop(p, p.weg[p.i], p.t, p.c, p.r);
    for (const a of A) kop(a, a.weg ? a.weg[0] : ring[a.i], a.t, a.c, 1.5);
    for (const v of V) rond(ctx, v.c, v.x, v.y, 1.3, (1 - v.t) * .6);
    ctx.globalCompositeOperation = "source-over";
    rond(ctx, kl.kern, kern.x, kern.y, kern.r, 1); cirkel(ctx, "#ffffff", kern.x, kern.y, kern.r, .6, 1);
    tekst(ctx, K.kern.label, kern.x, kern.y + 3.7, F(750, 10.5), "#ffffff", "center");
  }
  const loopt = () => !rm.matches && zicht && !D.hidden;
  function beeld(ts) { raf = 0; if (!loopt()) return; const dt = last ? M.min(.05, (ts - last) / 1000) : 1 / 60; last = ts; stap(dt); teken(); raf = requestAnimationFrame(beeld); }
  function speel() { if (loopt() && !raf) { last = 0; raf = requestAnimationFrame(beeld); } }
  function opnieuw() {
    const r = band.getBoundingClientRect(); W = M.max(1, M.round(r.width)); H = M.max(1, M.round(r.height)); dpr = M.min(devicePixelRatio || 1, 2);
    cv.width = bg.width = M.round(W * dpr); cv.height = bg.height = M.round(H * dpr);
    kleuren(); P = []; A = []; V = []; T = []; acc1 = acc2 = 0; klok = 0;
    bx.setTransform(dpr, 0, 0, dpr, 0, 0); bx.clearRect(0, 0, W, H); bouw();
    if (rm.matches) { for (let i = 0; i < 240; i++) stap(1 / 30); for (const n of G.concat(C, poort, kern)) if (n) n.f = 0; }   // stil beeld, met alles erop
    teken(); speel();
  }
  band.addEventListener("pointermove", e => { const b = band.getBoundingClientRect(), px = e.clientX - b.left, py = e.clientY - b.top;
    let best = null, bd = 10; for (const n of G.concat(C, kern)) { if (!n) continue; const d = M.hypot(n.x - px, n.y - py) - n.r; if (d < bd) { bd = d; best = n; } }
    if (!best) { tip.hidden = true; return; } tip.textContent = best.tip; tip.hidden = false;
    tip.style.left = M.max(tip.offsetWidth / 2 + 4, M.min(W - tip.offsetWidth / 2 - 4, best.x)) + "px"; tip.style.top = M.max(28, best.y - best.r) + "px"; });
  band.addEventListener("pointerleave", () => { tip.hidden = true; });
  new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(opnieuw, 60); }).observe(band);
  new IntersectionObserver(e => { zicht = e[e.length - 1].isIntersecting; speel(); }).observe(band);
  D.addEventListener("visibilitychange", speel);
  rm.addEventListener("change", opnieuw);
  new MutationObserver(opnieuw).observe(R, {attributes: true, attributeFilter: ["data-theme"]});
  opnieuw();
})();
/* ===================== einde LANDKAART ===================== */
const {kpi:KPI, cats:CATS, facts:FACTS, leads:ALLE_LEADS, budget:BUDGET} = PAYLOAD;
// VA-96: met het slot op zijn alleen de eerste n panden van de werklijst te zien; filters, sorteren, Bewaar
// en Verberg werken op die n. De rest staat achter het slotblok, dat Python al in de HTML zette.
const LEADS = PAYLOAD.slot ? ALLE_LEADS.slice(0, PAYLOAD.slot.n) : ALLE_LEADS;
const FN = {woon:"var(--s1)", winkel:"var(--s2)", kantoor:"var(--s3)", overig:"var(--s4)", bedrijf:"var(--s5)"};
const FNL = {woon:"Wonen", winkel:"Winkel", kantoor:"Kantoor", overig:"Overig", bedrijf:"Bedrijf"};
const BAG="https://bagviewer.kadaster.nl/lvbag/bag-viewer/index.html#?searchQuery=";
const nl = n => n.toLocaleString("nl-NL");
const el = (t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};

const kb=document.getElementById("kpis");
KPI.forEach(k=>{
  const c=el("div","kpi");
  c.innerHTML=`<div class="accent" style="background:${k.c}"></div>
    <div class="v${k.v==="onbekend"?" onb":""}">${k.v}</div><div class="l">${k.l}</div><div class="h">${k.h}</div>`;
  kb.appendChild(c);
});

const max=Math.max(1,...CATS.map(c=>c.n));
const cb=document.getElementById("cats");
CATS.forEach(c=>{
  const row=el("div","bar");
  row.innerHTML=`<div class="name"><b>${c.k}</b> · ${c.name}</div>
    <div class="track"><div class="fill" data-tip="${c.name}: ${nl(c.n)} panden"
      style="width:0;background:${c.c}">${nl(c.n)}</div></div>`;
  cb.appendChild(row);
  requestAnimationFrame(()=>{row.querySelector(".fill").style.width=(c.n/max*100)+"%";});
});

const fb=document.getElementById("facts");
FACTS.forEach(f=>fb.appendChild(el("div","fact",`<span class="k">${f.k}</span><span class="val"${f.tip?` data-tip="${f.tip}"`:""}>${f.val}</span>`)));
if(PAYLOAD.bron===null){
  fb.parentNode.insertBefore(el("p","note",`<b>Bron-snapshot onbekend</b> — draai <code>run_proef.py</code> opnieuw,
    dan legt het vast uit welke BAG-ingest deze cijfers komen.`),fb.nextSibling);
}

// De score-opbouw: elke regel [label, punten, status, detail] staat één keer in PAYLOAD.criteria
// (VA-39); een pand heeft in 'ob' alleen de nummers van zijn regels.
const CRIT = PAYLOAD.criteria || [];
const opbouw = d => (d.ob || []).map(i => { const [label, punten, status, detail] = CRIT[i]; return {label, punten, status, detail}; });
function opbouwHTML(d){
  const cls={behaald:"ok",niet:"miss",aftrek:"neg",inactief:"off"};
  const ic={behaald:"✓",niet:"✕",aftrek:"▼",inactief:"○"};
  const rows=opbouw(d).map(it=>{
    let pts;
    if(it.status==="behaald") pts=`+${it.punten}`;
    else if(it.status==="aftrek") pts=`${it.punten}`;
    else if(it.status==="inactief") pts=`wacht · +${it.punten}`;
    else pts="0";
    return `<li class="${cls[it.status]}">
      <span class="ci">${ic[it.status]}</span>
      <span class="cl">${it.label}<em>${it.detail}</em></span>
      <span class="cp">${pts}</span></li>`;
  }).join("");
  return `<details class="brk"><summary>Score-opbouw
      <em>${d.raw} van ${BUDGET} punten benut</em>
      <span class="caret">▾</span></summary>
    <ul>${rows}</ul>
    <div class="brkfoot"><b>${d.raw}</b> van ${BUDGET} modelpunten → index <b>${d.s100}/100</b>.
      Grijze criteria (○) leveren nog niets tot hun databron is gekoppeld.</div>
  </details>`;
}

const lb=document.getElementById("leads");
/* De kleine luchtfoto (VA-71): PLEK.mini van PDOK, alleen voor een kaart die getekend wordt, met
   loading="lazy". Het vlak heeft een vaste maat; laden, mislukken en geen locatie zijn een klasse. */
const FOTO = PAYLOAD.kaartfoto;
function kaartFoto(vlak, d){
  const m = vlak.querySelector(".melding"), plek = d.detail && d.detail.loc;
  if (!plek || !PLEK.mini) { vlak.classList.add("geen"); m.textContent = FOTO.geen; return; }
  vlak.classList.add("laadt");
  const img = new Image(100, 100);
  img.alt = FOTO.alt.replace("{adres}", () => d.a); img.loading = "lazy"; img.decoding = "async";
  img.addEventListener("load", () => vlak.classList.replace("laadt", "geladen"), {once: true});
  img.addEventListener("error", () => { img.remove(); vlak.classList.replace("laadt", "mislukt"); m.textContent = FOTO.mislukt; }, {once: true});
  vlak.prepend(img); img.src = PLEK.mini.replace("{b}", plek.b);
}
function kaart(d){
  const order=["woon","winkel","kantoor","bedrijf","overig"];
  const segs=order.filter(k=>d.f[k]).map(k=>
    `<i data-tip="${FNL[k]}: ${d.f[k]} m²" style="flex:${d.f[k]};background:${FN[k]}"></i>`).join("");
  const leg=order.filter(k=>d.f[k]).map(k=>
    `<span><i class="dot" style="background:${FN[k]}"></i>${FNL[k]} ${d.f[k]} m²</span>`).join("");
  const chips=d.cat.map(c=>`<span class="chip c${c}">${c}</span>`).join("");
  const sigtags=d.sig.map(s=>`<span class="sigtag ${s.k}" data-tip="${s.d}">${s.t}</span>`).join("");
  const card=el("div","card");
  card.innerHTML=`
    <div class="card-top">
      <div class="card-foto"><span class="merk" aria-hidden="true"></span><span class="melding"></span></div>
      <div class="card-kern"><div class="addr">${d.a}</div><div class="lid"></div><span class="bw-label" hidden></span>
        <div class="chips">${chips}</div>
        ${sigtags?`<div class="sigtags">${sigtags}</div>`:""}</div>
      <div class="score"><b>${d.s100}</b><small>/100</small></div>
    </div>
    <div class="meter"><i style="width:0" data-w="${d.s100}"></i></div>
    <div class="meta">
      <div><div class="mv">${d.bj}</div><div class="ml">BOUWJAAR</div></div>
      <div><div class="mv">${nl(d.m2)}</div><div class="ml">M²</div></div>
      <div><div class="mv">${d.vbo}</div><div class="ml">VBO</div></div>
      <div><div class="mv">${d.adr}</div><div class="ml">ADRESSEN</div></div>
    </div>
    <div class="fnbar">${segs}</div>
    <div class="fnleg">${leg}</div>
    ${opbouwHTML(d)}
    <div class="foot">
      <a class="baglink" href="${BAG}${d.id}" target="_blank" rel="noopener">Open in BAG-viewer ↗</a>
      <span class="status">te controleren</span>
    </div>`;
  card.querySelector(".lid").textContent = d.r;   // de regel onder het adres komt uit Python
  kaartFoto(card.querySelector(".card-foto"), d);
  const m=card.querySelector(".meter i");
  requestAnimationFrame(()=>{m.style.width=m.dataset.w+"%";});
  card.insertBefore(BW.rij(d), card.querySelector(".foot")); BW.ververs(d);   // VA-90
  maakOpenbaar(card, d);
  return card;
}

/* ============================ PAND OPENEN (VA-61, VA-62) ============================
   Alle tekst en elke waarde komt kant-en-klaar uit pand_detail() in build_dashboard.py, in de
   korte vorm van pand_kort(): de labels één keer in PAYLOAD.velden, elke waarde één keer in
   PAYLOAD.waarden, de adressen van luchtfoto en kaarten één keer in PAYLOAD.plek. Alleen-lezen: openen of sluiten schrijft niets. De
   luchtfoto (PDOK, open data) wordt pas opgevraagd als een pand opengaat, en alleen voor dat pand. */
const PAND_TEKST = {
  laden: "De luchtfoto laadt…",
  mislukt: "De luchtfoto kon niet laden. Bekijk het pand via Google Maps of Street View hieronder.",
  bron: "Luchtfoto: Beeldmateriaal.nl, via PDOK · open data (CC BY 4.0).",
  geenLocatie: "Dit pand heeft geen bekende locatie, dus er is geen luchtfoto en geen link naar Google Maps of Street View.",
  alt: a => `Luchtfoto van ${a}`,
  maps: "Open in Google Maps", sv: "Open in Street View", bag: "Open in BAG-viewer",
  open: "Open pand", openLabel: a => `Open pand: alle gegevens van ${a}`,
};
const VELDEN = PAYLOAD.velden || [], WAARDEN = PAYLOAD.waarden || [], PLEK = PAYLOAD.plek || {};
const locatie = p => { if (!p) return null; const zet = s => s.replace("{b}", p.b).replace("{ll}", p.ll);
  return {foto: zet(PLEK.foto), maps: zet(PLEK.maps), streetview: zet(PLEK.streetview)}; };
const pandDlg = document.getElementById("pand");
let pandOpener = null, pandId = null, pandVanBewaard = false;   // VA-91: geopend vanaf Bewaarde panden?
const maak = (tag, cls, tekst) => { const e = document.createElement(tag); if (cls) e.className = cls; if (tekst != null) e.textContent = tekst; return e; };
function openPand(d, opener) {
  const det = d.detail; pandOpener = opener; pandId = d.id;
  pandVanBewaard = !!(opener && opener.closest && opener.closest("#bewaard"));
  document.getElementById("pandTitel").textContent = det.titel;
  document.getElementById("pandSub").textContent = `${d.p} ${d.wp} · BAG ${d.id}`;
  document.getElementById("pandScore").innerHTML = `<b>${d.s100}</b><small>/100</small>`;
  const romp = document.getElementById("pandRomp"); romp.textContent = "";
  romp.appendChild(BW.rij(d, true));   // VA-90: Bewaar en Verberg, ook hier
  const loc = locatie(det.loc);
  if (loc) {
    const fig = maak("figure", "pand-foto"), kader = maak("div", "kader"), melding = maak("div", "melding", PAND_TEKST.laden);
    const img = new Image(); img.alt = PAND_TEKST.alt(det.titel); img.decoding = "async";
    img.onload = () => { melding.remove(); kader.appendChild(maak("div", "merk")); };
    img.onerror = () => { img.remove(); melding.textContent = PAND_TEKST.mislukt; };
    kader.append(melding, img); img.src = loc.foto;
    fig.append(kader, maak("figcaption", null, PAND_TEKST.bron)); romp.appendChild(fig);
  } else {
    romp.appendChild(maak("p", "pand-geenlocatie", PAND_TEKST.geenLocatie));
  }
  const links = maak("div", "pand-links");
  const link = (href, tekst) => { const a = maak("a", null, tekst), pijl = maak("span", null, "↗"); pijl.setAttribute("aria-hidden", "true"); a.append(" ", pijl); a.href = href; a.target = "_blank"; a.rel = "noopener"; links.appendChild(a); };
  if (loc) { link(loc.maps, PAND_TEKST.maps); link(loc.streetview, PAND_TEKST.sv); }
  link(BAG + d.id, PAND_TEKST.bag);
  romp.appendChild(links);
  const dl = maak("dl", "pand-velden");
  det.w.forEach((nr, i) => {
    const v = WAARDEN[nr];
    if (v === null) return;   // een veld dat dit pand niet heeft (de landelijke velden bij een stad)
    const dd = maak("dd");
    if (Array.isArray(v)) { const ul = maak("ul"); v.forEach(x => ul.appendChild(maak("li", null, x))); dd.appendChild(ul); }
    else dd.textContent = v;
    dl.append(maak("dt", null, VELDEN[i]), dd);
  });
  romp.appendChild(dl);
  const ob = maak("div", "pand-opbouw"); ob.innerHTML = opbouwHTML(d); ob.querySelector("details").open = true;
  romp.appendChild(ob);
  pandDlg.showModal(); romp.scrollTop = 0;
  document.getElementById("pandSluit").focus();
}
document.getElementById("pandSluit").addEventListener("click", () => pandDlg.close());
pandDlg.addEventListener("click", e => { if (e.target === pandDlg) pandDlg.close(); });
// Terug naar de kaart die het opende (VA-61). Is die kaart weg (Verberg in dit venster, VA-90), dan naar zijn
// "Ongedaan maken" boven de werklijst, en is dat er niet, naar de werklijst zelf: nooit naar <body> (Lumi §8).
pandDlg.addEventListener("close", () => {
  if (pandOpener && pandOpener.isConnected) { pandOpener.focus(); return; }
  if (pandId != null) BW.naSluiten(pandId).focus();   // VA-91: vanaf Bewaarde panden naar zijn eigen Ongedaan maken
});
function maakOpenbaar(card, d) {
  if (!d.detail) return;
  card.classList.add("open-baar");
  const knop = maak("button", "pand-open", PAND_TEKST.open); knop.type = "button";
  knop.setAttribute("aria-haspopup", "dialog"); knop.setAttribute("aria-label", PAND_TEKST.openLabel(d.detail.titel));
  const voet = card.querySelector(".foot"); voet.insertBefore(knop, voet.querySelector(".status"));
  // Klik op de kaart opent het pand; de link, de score-opbouw en de knop zelf doen hun eigen ding.
  card.addEventListener("click", e => { if (e.target.closest("a, summary, details, button")) return; openPand(d, knop); });
  knop.addEventListener("click", () => openPand(d, knop));
}
/* ============================ einde PAND OPENEN ============================ */

/* ============================ BEWAREN EN VERBERGEN (VA-90) ============================
   Ayman: elk pand een knop Bewaar en een knop Verberg. Alleen in deze browser (localStorage), op dit
   apparaat; er gaat niets de pagina uit en geen cijfer verandert: Verberg haalt alleen een kaart uit de
   werklijst. Een pand is bewaard, verborgen of geen van beide; dezelfde knop nog eens zet het terug.
   Per pand bewaart de browser ook wat VA-91 nodig heeft om het later te tonen, ook als het niet meer
   in de data staat. Weigert de browser opslag (privévenster), dan zeggen de knoppen dat; de rest werkt.
   Alle tekst komt uit PAYLOAD.bewaar.tekst (Python).
   VA-97: verborgen geldt PAYLOAD.bewaar.dagen dagen (30) vanaf 'sinds'; daarna valt het pand bij het lezen uit
   de opslag en staat het weer op de werklijst. Een verborgen pand zonder geldige 'sinds' (of met een datum in de
   toekomst) begint vanaf nu te tellen, zodat niets wat VA-90 verborg verloren gaat of voor altijd blijft. */
const BW = (() => {
  const T = PAYLOAD.bewaar.tekst, DP = PAYLOAD.bewaar.dp, SLEUTEL = "levrai-vastgoed-panden", VORM = 1;
  const PER_ID = new Map(LEADS.map(d => [d.id, d]));
  const D = PAYLOAD.bewaar.duur, DAG = 864e5, DAGEN = PAYLOAD.bewaar.dagen || 30;   // VA-97
  const MND = PAYLOAD.bewaar.maanden, SP = PAYLOAD.bewaar.nbsp;   // het datumformaat van _nl() in Python
  let stand = {}, werkt = false, tonen = false, dlg = null;
  const luisteraars = [], alleLuisteraars = [], rijen = new Map();   // per pand-ID de knoppenrij van zijn kaart
  function lees() {
    try { const r = JSON.parse(localStorage.getItem(SLEUTEL) || "null");
      stand = r && r.v === VORM && r.panden && typeof r.panden === "object" ? r.panden : {}; } catch (e) { stand = {}; }
    return verlopen();
  }
  // VA-97: tot wanneer een verborgen pand verborgen blijft, en wat daarna weer op de werklijst komt.
  const tot = r => Date.parse(r.sinds) + DAGEN * DAG;
  // De korte datum van _nl(): dag, maand en jaar met harde spaties, in de eigen tijdzone. Geen tweede notatie (VA-31).
  const datum = r => { const t = new Date(tot(r)); return t.getDate() + SP + MND[t.getMonth()] + SP + t.getFullYear(); };
  function verlopen() {   // true als er iets veranderde (dan is het ook opgeslagen)
    const nu = Date.now(); let anders = false;
    for (const id of Object.keys(stand)) { const r = stand[id];
      if (!r || r.stand !== "verborgen") continue;
      const t = Date.parse(r.sinds);
      if (!Number.isFinite(t) || t > nu) { r.sinds = new Date(nu).toISOString(); anders = true; }   // van vóór VA-97 of scheef
      else if (tot(r) <= nu) { delete stand[id]; anders = true; } }
    if (anders) schrijf();
    return anders;
  }
  function schrijf() {
    try { localStorage.setItem(SLEUTEL, JSON.stringify({v: VORM, panden: stand})); return true; } catch (e) { return false; }
  }
  try { const k = SLEUTEL + "-proef"; localStorage.setItem(k, "1"); localStorage.removeItem(k); werkt = true; } catch (e) { werkt = false; }
  if (werkt) lees();
  const van = id => (stand[id] && stand[id].stand) || "";
  const zichtbaar = id => tonen || van(id) !== "verborgen";
  const aantalWeg = () => LEADS.filter(d => van(d.id) === "verborgen").length;
  // Wat VA-91 nodig heeft om een pand te tonen dat niet meer in de werklijst staat; 'sinds' is het moment van opslaan.
  const gegevens = (d, s) => ({stand: s, hoofdadres: d.detail ? d.detail.titel : d.a, woonplaats: d.wp, score100: d.s100,
    pandcategorie: d.pc || d.cat[0] || null, bag_viewer_url: BAG + d.id, datapeildatum: d.dp || DP, sinds: new Date().toISOString()});
  function zet(d, s) {   // s: "bewaard" of "verborgen"; dezelfde stand nog eens is terug naar geen van beide
    const oud = stand[d.id] || null, nu = van(d.id) === s ? "" : s;
    if (nu) stand[d.id] = gegevens(d, nu); else delete stand[d.id];
    if (!schrijf()) { if (oud) stand[d.id] = oud; else delete stand[d.id]; werkt = false; overal(false); return null; }
    overal(nu === "verborgen" || (oud && oud.stand === "verborgen")); return {oud, nu};   // alleen verbergen raakt de lijst
  }
  function herstel(d, oud) {   // Ongedaan maken: precies de stand van daarvoor, ook als die 'bewaard' was
    if (oud) stand[d.id] = oud; else delete stand[d.id];
    if (!schrijf()) { werkt = false; } overal(true);
  }
  function nietMeerBewaard(id) {   // VA-91: niet meer bewaren vanaf Bewaarde panden, ook voor een pand dat niet meer in de data staat
    const oud = stand[id] || null;
    if (!oud) return null;
    delete stand[id];
    if (!schrijf()) { stand[id] = oud; werkt = false; overal(false); return null; }
    overal(false); return oud;
  }
  const adres = d => d.detail ? d.detail.titel : d.a;
  // Vier iconen, inline SVG (Lumi, knoppen-spec.md): geen lettertype, beeld of bestand erbij. Nooit voorgelezen.
  const STER = "M12 3.2l2.6 5.5 6 .7-4.4 4.1 1.1 6L12 16.6l-5.3 2.9 1.1-6L3.4 9.4l6-.7z",
    OOG = "M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z",
    LIJN = ' fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"',
    STREEP = '<path d="M4 20L20 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>';
  const ICO = {
    ster: '<path d="' + STER + '"' + LIJN + '/>',
    ster_vol: '<path d="' + STER + '"' + LIJN.replace('fill="none"', 'fill="currentColor"') + '/>',
    oog: '<path d="' + OOG + '"' + LIJN + '/><circle cx="12" cy="12" r="2.8" fill="none" stroke="currentColor" stroke-width="1.8"/>' + STREEP,
    oog_uit: '<path d="' + OOG + '"' + LIJN + ' stroke-dasharray="2.6 2.4"/>' + STREEP};
  // Via de HTML-parser (template), die een <svg> zelf in de SVG-naamruimte zet.
  const SJ = document.createElement("template");
  function icoon(naam, cls) {
    SJ.innerHTML = '<svg class="' + cls + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false" data-ico="' + naam + '">'
      + ICO[naam] + "</svg>";
    return SJ.content.firstChild;
  }
  function knop(d, soort) {
    const b = maak("button", "bw-knop bw-" + (soort === "bewaard" ? "bewaar" : "weg")); b.type = "button";
    const ico = icoon(soort === "bewaard" ? "ster" : "oog", "bw-ico");
    const tk = maak("span", "bw-tk"); tk.append(maak("span", "bw-nm"), maak("span", "bw-terug"));
    b.append(ico, tk);   // de naam staat in aria-label, per stand (werkRij)
    b.addEventListener("click", e => { e.stopPropagation(); druk(d, soort, b); });
    return b;
  }
  function rij(d, inPand) {
    const r = maak("div", inPand ? "bw-rij-pand" : "bw-rij"), k = maak("div", "bw-rij");
    k.append(knop(d, "bewaard"), knop(d, "verborgen"));
    if (!inPand) { rijen.set(d.id, k); werkRij(d); return k; }
    r.className = "pand-bw"; r.append(k, maak("p", "bw-apparaat", werkt ? T["apparaat.kort"] : T.geen_opslag));
    const s = maak("div", "bw-status"); s.id = "pandBwStatus"; s.setAttribute("role", "status"); r.append(s);
    dlg = {d, r: k, s}; werkRij(d); return r;
  }
  function werkRij(d) {
    const s = van(d.id);
    for (const k of [rijen.get(d.id), dlg && dlg.d.id === d.id ? dlg.r : null]) { if (!k) continue;
      k.querySelectorAll(".bw-knop").forEach(b => { const soort = b.classList.contains("bw-bewaar") ? "bewaard" : "verborgen", aan = s === soort;
        b.setAttribute("aria-pressed", String(aan));
        b.setAttribute("aria-label", T["naam." + (aan ? soort : soort === "bewaard" ? "bewaar" : "verberg")].replace("{adres}", () => adres(d)));
        if (werkt) b.removeAttribute("aria-disabled"); else b.setAttribute("aria-disabled", "true");
        const naam = soort === "bewaard" ? (aan ? "ster_vol" : "ster") : (aan ? "oog_uit" : "oog"), ico = b.querySelector(".bw-ico");
        if (ico.getAttribute("data-ico") !== naam) ico.replaceWith(icoon(naam, "bw-ico"));
        b.querySelector(".bw-nm").textContent = aan ? T["label." + soort] : T[soort === "bewaard" ? "bewaar" : "verberg"];
        b.querySelector(".bw-terug").textContent = aan ? T["terug." + soort] : ""; });
    }
    const card = rijen.get(d.id) && rijen.get(d.id).closest(".card");
    if (card) { card.classList.toggle("bw-is-weg", s === "verborgen");
      const l = card.querySelector(".bw-label"); l.hidden = !s; l.className = "bw-label" + (s === "verborgen" ? " weg" : "");
      l.textContent = "";
      if (s) { const i = icoon(s === "bewaard" ? "ster_vol" : "oog_uit", "bw-label-ico");   // dezelfde iconen als de knop
        l.append(i, s === "verborgen" ? D["label.verborgen"].replace("{datum}", () => datum(stand[d.id])) : T["label." + s]); } }
  }
  // De statusregel boven de werklijst (en in 'Open pand'): role=status, dus voorgelezen zonder te onderbreken.
  const balk = document.getElementById("bwBalk");
  const el = id => document.getElementById(id);
  // Ongedaan maken draagt de zin als beschrijving (aria-describedby) en het pand waar hij bij hoort.
  function status(doel, tekst, terug, id) {
    const zin = maak("span", null, tekst); zin.id = doel.id + "-zin";
    doel.textContent = ""; doel.append(zin);
    if (!terug) return null;
    const b = maak("button", "bw-ongedaan", T.ongedaan); b.type = "button"; b.setAttribute("aria-describedby", zin.id);
    b.dataset.pand = id; b.addEventListener("click", terug); doel.append(b); return b;
  }
  const weg = r => D["status.verborgen"].replace("{datum}", () => datum(r));   // "… is verborgen tot <datum>" (VA-97)
  function druk(d, soort, b) {
    const inPand = !!b.closest("#pand"), hier = inPand ? dlg.s : el("bwStatus");
    const vanB = inPand && pandVanBewaard;   // VA-91: 'Open pand' vanaf Bewaarde panden; de regel daar zegt het ook
    if (!werkt) { status(hier, T.geen_opslag); return; }
    const uit = zet(d, soort);
    if (!uit) { status(hier, T.geen_opslag); return; }
    const zin = uit.nu === "verborgen" ? weg(stand[d.id]) : uit.nu === "bewaard" ? T["status.bewaard"]
      : soort === "verborgen" ? T["status.terug"] : T["status.niet_bewaard"];
    const tekst = zin.replace("{adres}", () => adres(d));
    const terug = () => { herstel(d, uit.oud);
      const t = (uit.oud ? (uit.oud.stand === "verborgen" ? weg(uit.oud) : vanB ? T["pagina.status.terug"] : T["status.bewaard"])
        : T["status.terug"]).replace("{adres}", () => adres(d));
      [el("bwStatus"), vanB ? el("bwBewaardStatus") : null, dlg && dlg.d.id === d.id ? dlg.s : null].forEach(s => s && status(s, t));
      // Focus naar de knop die je nu ziet: in 'Open pand' zolang het open is, anders op de kaart (een gesloten
      // venster houdt zijn knoppen in de pagina, maar die kunnen geen focus krijgen), anders de werklijst.
      const ziet = x => x && x.isConnected && (!x.closest("dialog") || x.closest("dialog").open);
      const k = [inPand ? dlg.r : null, rijen.get(d.id)].find(ziet);
      // Vanaf Bewaarde panden met het venster dicht: de Bewaar-knop van de teruggekomen rij daar, anders dat deel.
      const opPagina = vanB && !(k && k === dlg.r) ? document.querySelector(`#bwpLijst li[data-pand="${CSS.escape(String(d.id))}"] .bw-bewaar`) : null;
      if (vanB && !opPagina && !(k && k === dlg.r)) { el("bewaard").focus(); return; }
      const f = opPagina || (k && k.querySelector(soort === "bewaard" ? ".bw-bewaar" : ".bw-weg")); (f || lijstDeel()).focus(); };
    const ongedaan = status(el("bwStatus"), tekst, terug, d.id);
    if (inPand) status(dlg.s, tekst, terug, d.id);
    if (vanB) status(el("bwBewaardStatus"), tekst, terug, d.id);
    // Een kaart die verdwijnt, neemt de focus niet mee: die gaat naar Ongedaan maken.
    else if (!b.isConnected && ongedaan) ongedaan.focus();
  }
  function werkBalk() {
    if (!balk) return;
    const n = aantalWeg(), aantal = el("bwAantal"), toon = el("bwToon");
    if (n === 0) tonen = false;   // niets verborgen: geen telling en geen knop
    el("bwApparaat").textContent = werkt ? T.apparaat : T.geen_opslag;
    aantal.hidden = toon.hidden = n === 0;
    aantal.textContent = n === 1 ? T["aantal.een"] : T.aantal.replace("{n}", nl(n));
    // Geen aria-pressed: het label zegt al wat de knop doet (Lumi §4); de rand via de klasse.
    toon.textContent = T[(tonen ? "toon.uit" : "toon") + (n === 1 ? ".een" : "")]; toon.classList.toggle("aan", tonen);
  }
  // Een lege werklijst omdat alles verborgen is (Lumi §7). m: de panden die de filters halen, verborgen meegeteld;
  // 0 als de lijst niet leeg is door Verberg. Dan staat de zin van de filters (of niets) er weer.
  function leeg(vak, m, filters) {
    const p = vak.querySelector("p"), wis = vak.querySelector(".wl-wis");
    if (vak.dataset.zin == null) vak.dataset.zin = p.textContent;
    let b = vak.querySelector(".bw-leeg-toon");
    if (wis) wis.hidden = !!m && !filters;
    if (!m) { p.textContent = vak.dataset.zin; if (b) b.remove(); return; }
    p.textContent = !filters ? T["leeg.alles_verborgen"].replace("{totaal}", nl(m))
      : m === 1 ? T["leeg.verborgen.een"] : T["leeg.verborgen"].replace("{m}", nl(m));
    if (!b) { b = maak("button", "bw-leeg-toon"); b.type = "button"; vak.insertBefore(b, wis);
      b.addEventListener("click", () => { tonen = true; overal(true); el("bwToon").focus(); }); }   // daarna: "Verberg ze weer"
    b.textContent = T[m === 1 ? "toon.een" : "toon"];
  }
  const ongedaanVoor = id => { const b = el("bwStatus") && el("bwStatus").querySelector(".bw-ongedaan");
    return b && b.dataset.pand === String(id) ? b : null; };
  const lijstDeel = () => (balk && balk.closest("section")) || el("inhoud");
  // Na het sluiten van 'Open pand' zonder zijn kaart of rij (VA-61, Lumi VA-91 §9): Ongedaan maken van dit pand
  // waar het vandaan kwam, en anders dat deel zelf. Nooit <body>.
  function naSluiten(id) {
    const vanB = pandVanBewaard; pandVanBewaard = false;
    if (!vanB) return ongedaanVoor(id) || lijstDeel();
    const b = el("bwBewaardStatus") && el("bwBewaardStatus").querySelector(".bw-ongedaan");
    return (b && b.dataset.pand === String(id) ? b : null) || el("bewaard") || lijstDeel();
  }
  // lijst: alleen als een pand verborgen wordt of terugkomt, rekent de werklijst opnieuw; Bewaar verandert geen kaart van plek.
  function overal(lijst) { rijen.forEach((k, id) => { const d = PER_ID.get(id); if (d) werkRij(d); }); if (dlg) werkRij(dlg.d); werkBalk(); if (lijst) luisteraars.forEach(f => f());
    alleLuisteraars.forEach(f => f()); }   // VA-91: Bewaarde panden en de telling in het menu volgen elke verandering
  if (balk) el("bwToon").addEventListener("click", () => { tonen = !tonen; overal(true); });
  addEventListener("storage", e => { if (e.key === SLEUTEL) { lees(); overal(true); } });   // een ander tabblad van dit dashboard
  // VA-97: een tabblad dat dagen openstaat, laat een verlopen pand terugkomen zodra je er weer naar kijkt.
  document.addEventListener("visibilitychange", () => { if (!document.hidden && werkt && verlopen()) overal(true); });
  werkBalk();
  // VA-91: wat de pagina Bewaarde panden nodig heeft. bewaarde(): [id, opgeslagen object] van elk bewaard pand.
  const bewaarde = () => Object.keys(stand).filter(id => stand[id] && stand[id].stand === "bewaard").map(id => [id, stand[id]]);
  return {rij, ververs: werkRij, zichtbaar, aantalWeg, op: f => luisteraars.push(f), van, leeg, ongedaanVoor, lijstDeel,
    naSluiten, bewaarde, weg: nietMeerBewaard, herstelId: (id, oud) => herstel({id}, oud), status, werkt: () => werkt, opAlles: f => alleLuisteraars.push(f),
    icoon};   // VA-105: dezelfde SVG-iconen op de pagina Bewaarde panden
})();
/* ============================ einde BEWAREN EN VERBERGEN ============================ */

/* ============================ BEWAARDE PANDEN (VA-91) ============================
   Ayman: "links in menu moet er een aparte pagina zijn voor de bewaarde panden". Een eigen deel (#bewaard)
   tussen Voorraad en de werklijst, met alles wat in deze browser bewaard is: ook een pand dat niet meer in
   de werklijst staat, uit wat VA-90 per pand opsloeg. Alle tekst uit PAYLOAD.bewaar.tekst (Lumi, copy-va91.md).
   Het rekenen (volgorde, datums, adres) staat los van het tekenen, in BWP_REKEN. */
const BWP_REKEN = (() => {
  const M = PAYLOAD.bewaar.maanden || [], NB = " ";
  const tijd = s => { const t = typeof s === "string" && s ? Date.parse(s) : NaN; return Number.isFinite(t) ? t : null; };
  // 'sinds' is een ISO-tijd in UTC: de datum is de kalenderdag in de lokale tijd van deze browser.
  const sindsDatum = s => { const t = tijd(s); if (t === null) return null; const d = new Date(t);
    return d.getDate() + NB + M[d.getMonth()] + NB + d.getFullYear(); };
  // 'datapeildatum' is JJJJ-MM-DD: gelezen als kalenderdatum, niet via new Date() (dat schuift een dag op).
  const peilDatum = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof s === "string" ? s : "");
    if (!m) return null;
    const j = +m[1], mm = +m[2], dd = +m[3];
    if (mm < 1 || mm > 12 || dd < 1 || dd > new Date(Date.UTC(j, mm, 0)).getUTCDate()) return null;   // geen 31 februari
    return dd + NB + M[mm - 1] + NB + j; };
  // Nieuwste 'sinds' bovenaan; zonder leesbare 'sinds' onderaan; bij gelijke 'sinds' het adres op alfabet.
  const volgorde = r => r.slice().sort((a, b) => { const ta = tijd(a[1].sinds), tb = tijd(b[1].sinds);
    if (ta !== tb) { if (ta === null) return 1; if (tb === null) return -1; return tb - ta; }
    return String(a[1].hoofdadres || "").localeCompare(String(b[1].hoofdadres || ""), "nl"); });
  // Het adres met de woonplaats erachter, als die er nog niet aan het eind staat: altijd één keer.
  const adres = v => { const a = String(v.hoofdadres || ""), w = String(v.woonplaats || "");
    return !w || a.endsWith(w) ? a : a ? a + ", " + w : w; };
  const categorie = c => typeof c === "string" && /^[A-E]$/.test(c) ? c : null;
  const score = s => typeof s === "number" && Number.isFinite(s) ? s : null;
  return {sindsDatum, peilDatum, volgorde, adres, categorie, score};
})();
const BWP = (() => {
  const sec = document.getElementById("bewaard");
  if (!sec) return null;   // een bouw zonder dit deel (een stad)
  const T = PAYLOAD.bewaar.tekst, R = BWP_REKEN, $ = id => document.getElementById(id);
  const lijst = $("bwpLijst"), leeg = $("bwpLeeg"), meer = $("bwpMeer"), meta = $("bwpMeta"), app = $("bwpApparaat");
  const regel = $("bwBewaardStatus"), menuN = $("bwpMenuN"), menuSr = $("bwpMenuSr"), wl = $("werklijst");
  const EERST = +sec.querySelector(".bwp").dataset.eerst || 10;
  const PER = new Map(LEADS.map(d => [String(d.id), d]));   // wat in de huidige werklijst te zien is (met het slot: de eerste n)
  const gebouwd = new Map();   // per pand-ID {k: de opgeslagen gegevens als tekst, li}: een rij die niet verandert, blijft hangen
  let alles = false;
  const vul = (t, w) => t.replace(/\{(\w+)\}/g, (x, k) => k in w ? w[k] : x);
  const naamVan = v => String(v.hoofdadres || "") || R.adres(v);
  function rij(id, v) {
    const d = PER.get(id), li = maak("li", "card bwp-rij" + (d ? "" : " weg")); li.dataset.pand = id;
    const s = R.score(v.score100), sc = maak("div", "score" + (s === null ? " onb" : ""));
    if (s === null) sc.append(maak("b", null, "onbekend")); else sc.append(maak("b", null, String(s)), maak("small", null, "/100"));
    if (s !== null) sc.style.setProperty("--p", Math.max(0, Math.min(100, s)));   // de ring om de score (eigen pagina)
    const kern = maak("div", "bwp-kern");
    kern.append(maak("div", "addr", R.adres(v)));
    if (!d) kern.append(maak("span", "bw-label weg", T["pagina.weg.label"]));
    const c = R.categorie(v.pandcategorie);
    if (c) { const ch = maak("div", "chips"); ch.append(maak("span", "chip c" + c, c)); kern.append(ch); }
    const sinds = R.sindsDatum(v.sinds);
    if (sinds) kern.append(maak("div", "lid", vul(T["pagina.sinds"], {datum: sinds})));
    if (!d) { const p = R.peilDatum(v.datapeildatum);
      kern.append(maak("div", "lid", p ? vul(T["pagina.weg.zin"], {datum: p}) : T["pagina.weg.zin.onbekend"])); }
    const knoppen = maak("div", "bw-rij");
    if (d && d.detail) {   // in de huidige data: 'Open pand' (VA-61), zoals vanaf de kaart
      const o = maak("button", "pand-open", PAND_TEKST.open); o.type = "button";
      o.setAttribute("aria-haspopup", "dialog"); o.setAttribute("aria-label", PAND_TEKST.openLabel(d.detail.titel));
      o.addEventListener("click", () => openPand(d, o)); knoppen.append(o);
    } else {   // niet meer in de data: alleen de opgeslagen link naar de BAG-viewer (VA-62)
      const url = d ? BAG + d.id : typeof v.bag_viewer_url === "string" && v.bag_viewer_url.startsWith(BAG) ? v.bag_viewer_url : null;
      if (url) { const a = maak("a", "baglink", PAND_TEKST.bag), pijl = maak("span", null, "↗"); pijl.setAttribute("aria-hidden", "true");
        a.append(" ", pijl); a.href = url; a.target = "_blank"; a.rel = "noopener"; knoppen.append(a); }
    }
    // De Bewaar-knop van VA-90, in de ingedrukte stand; nog eens drukken is niet meer bewaren.
    const b = maak("button", "bw-knop bw-bewaar"); b.type = "button"; b.setAttribute("aria-pressed", "true");
    b.setAttribute("aria-label", vul(T["naam.bewaard"], {adres: naamVan(v)}));
    const ico = BW.icoon("ster_vol", "bw-ico");   // VA-105: de volle ster van de knop, niet voorgelezen
    const tk = maak("span", "bw-tk"); tk.append(maak("span", "bw-nm", T["label.bewaard"]), maak("span", "bw-terug", T["terug.bewaard"]));
    b.append(ico, tk); b.addEventListener("click", () => haalWeg(id));
    knoppen.append(b); li.append(sc, kern, knoppen);
    return li;
  }
  function haalWeg(id) {
    const oud = BW.weg(id);   // tekent deze lijst, de werklijst en het menu opnieuw
    if (!oud) { regel.textContent = T["pagina.geen_opslag"]; sec.focus(); return; }
    const naam = naamVan(oud);
    const terug = () => { BW.herstelId(id, oud);   // het oude object, met zijn oude 'sinds': dezelfde plek
      BW.status(regel, vul(T["pagina.status.terug"], {adres: naam}));
      const k = lijst.querySelector(`li[data-pand="${CSS.escape(id)}"] .bw-bewaar`); (k || sec).focus(); };
    const b = BW.status(regel, vul(T["status.niet_bewaard"], {adres: naam}), terug, id);
    (b || sec).focus();   // de rij is weg: de focus naar zijn Ongedaan maken, ook als de lijst nu leeg is
  }
  function teken() {
    const werkt = BW.werkt(), r = werkt ? R.volgorde(BW.bewaarde()) : [];
    const n = r.length, m = r.filter(([id]) => !PER.has(id)).length;
    menuN.hidden = !n; menuN.textContent = n ? vul(T["pagina.menu.n"], {n: nl(n)}) : "";
    menuSr.textContent = n ? vul(T["pagina.menu.n.sr"], {n: nl(n)}) : "";
    meta.textContent = !n ? "" : m ? (n === 1 ? T["pagina.meta.weg.een"] : vul(T["pagina.meta.weg"], {n: nl(n), m: nl(m)}))
      : n === 1 ? T["pagina.meta.een"] : vul(T["pagina.meta"], {n: nl(n)});
    app.hidden = !werkt;
    leeg.hidden = werkt && n > 0;
    leeg.querySelector("p").textContent = werkt ? T["pagina.leeg"] : T["pagina.geen_opslag"];
    if (n <= EERST) alles = false;
    const wil = (alles ? r : r.slice(0, EERST)).map(([id, v]) => { const k = JSON.stringify(v), g = gebouwd.get(id);
      if (!g || g.k !== k) gebouwd.set(id, {k, li: rij(id, v)}); return gebouwd.get(id).li; });
    // Ter plekke, zoals de werklijst: een rij die blijft, wordt niet opnieuw opgehangen (de focus blijft erop).
    const blijft = new Set(wil);
    [...lijst.children].forEach(c => { if (!blijft.has(c)) c.remove(); });
    let plek = lijst.firstElementChild;
    for (const li of wil) { if (li === plek) plek = plek.nextElementSibling; else lijst.insertBefore(li, plek); }
    lijst.hidden = !wil.length;
    meer.hidden = n <= EERST;
    meer.textContent = alles ? T["pagina.minder"] : vul(T["pagina.meer"], {n: nl(n)});
    held(werkt, r, n, m);
  }
  // De kop van de eigen pagina: vier tellingen en de verdeling over A–E, uit dezelfde opgeslagen gegevens.
  const tel = {n: $("bwpTelN"), in: $("bwpTelIn"), weg: $("bwpTelWeg"), score: $("bwpTelScore")};
  const cat = $("bwpCat"), staaf = $("bwpStaaf"), leg = $("bwpLeg");
  function held(werkt, r, n, m) {
    if (!tel.n) return;
    const streep = "–";
    tel.n.textContent = werkt ? nl(n) : streep;
    tel.in.textContent = werkt ? nl(n - m) : streep;
    tel.weg.textContent = werkt ? nl(m) : streep;
    const sc = r.map(([, v]) => R.score(v.score100)).filter(x => x !== null);
    tel.score.textContent = sc.length ? nl(Math.round(sc.reduce((a, b) => a + b, 0) / sc.length)) : streep;
    if (sc.length) tel.score.append(maak("small", null, "/100"));
    const per = {}; r.forEach(([, v]) => { const c = R.categorie(v.pandcategorie); if (c) per[c] = (per[c] || 0) + 1; });
    const cs = "ABCDE".split("").filter(c => per[c]);
    cat.hidden = !cs.length; staaf.replaceChildren(); leg.replaceChildren();
    cs.forEach(c => { const i = maak("i", "c" + c); i.style.flexGrow = per[c]; staaf.append(i);
      const li = maak("li"), k = maak("i", "c" + c); k.setAttribute("aria-hidden", "true"); li.append(k, c + " · " + nl(per[c])); leg.append(li); });
  }
  // Niet verspringen (Lumi §9): ligt dit deel helemaal boven het scherm, dan blijft de werklijst staan waar hij
  // stond. Safari kent geen scroll-anchoring, dus het script doet het zelf. In Chrome heeft scroll-anchoring het al
  // gedaan als 'na' gemeten wordt; het verschil is dan 0 en er schuift niets dubbel (gemeten, met en zonder).
  function ververs() {
    const boven = wl && sec.getBoundingClientRect().bottom <= 0, voor = boven ? wl.getBoundingClientRect().top : 0;
    teken();
    if (boven) { const na = wl.getBoundingClientRect().top; if (na !== voor) scrollBy({top: na - voor, behavior: "instant"}); }   // niet glijden (html heeft smooth)
  }
  meer.addEventListener("click", () => { alles = !alles; teken(); });   // de focus blijft op de knop
  BW.opAlles(ververs);
  teken();
  return {teken};
})();
/* ============================ einde BEWAARDE PANDEN ============================ */

/* ============================ WERKLIJST (VA-39, VA-68 t/m VA-70) ============================
   Tot 500 kaarten: de eerste STAP meteen, de volgende pas als je in de buurt scrolt, zodat de
   pagina op een telefoon snel staat. Elke kaart wordt één keer gebouwd en daarna teruggehangen,
   zodat zijn luchtfoto maar één keer wordt opgevraagd (VA-71 crit. 3).
   De filters (gemeente, categorie, signaal, gebied, en de getalvelden van VA-69) rekenen in de browser
   op de panden van de lijst: tussen filters EN, binnen een filter OF; het aantal bij een keuze telt de
   panden die alle andere filters halen. Sorteren (VA-70) hangt dezelfde kaarten in een andere volgorde. Elke zin komt uit Python (filter_html(), PAYLOAD.filter.tekst); het script
   vult alleen getallen in. De stand staat in het adres, zodat herladen en delen dezelfde lijst geven. */
(() => {
  const STAP = 40, wacht = document.querySelector(".schildwacht"), gebouwd = new Map();
  let rij = LEADS, getoond = 0;
  const io = "IntersectionObserver" in window ? new IntersectionObserver(e => {
    if (e.some(x => x.isIntersecting)) { meer(); kijk(); }
  }, {rootMargin: "0px 0px 1200px 0px"}) : null;
  function meer(minstens) {
    const tot = io ? Math.min(rij.length, Math.max(getoond + STAP, minstens || 0)) : rij.length, deel = document.createDocumentFragment();
    for (; getoond < tot; getoond++) {
      const d = rij[getoond];
      if (!gebouwd.has(d.id)) gebouwd.set(d.id, kaart(d));
      deel.appendChild(gebouwd.get(d.id));
    }
    lb.appendChild(deel);
  }
  // Opnieuw waarnemen geeft direct een nieuwe melding: staat de wacht nog in de buurt, dan volgt de volgende STAP.
  function kijk() { if (!io) return; io.unobserve(wacht); if (getoond < rij.length) io.observe(wacht); }
  // houd: na Bewaar of Verberg (VA-90) blijven zoveel kaarten staan als er al waren, dus de pagina springt niet.
  function teken(lijst, houd) {
    if (!houd) { rij = lijst; getoond = 0; lb.textContent = ""; meer(); kijk(); return; }
    // Ter plekke: kaarten die blijven, blijven hangen (een kaart die opnieuw wordt opgehangen, vraagt zijn
    // luchtfoto opnieuw op); alleen wat weg moet gaat eruit en wat erbij komt, komt op zijn plaats.
    // Tot en met de laatste kaart die er nu staat: een pand dat wegvalt, haalt er onderaan geen nieuwe kaart (en foto) bij;
    // de schildwacht doet dat pas als je verder scrolt, zoals altijd.
    rij = lijst;
    const staat = new Set(lb.children);
    let tot = 0; rij.forEach((d, i) => { if (staat.has(gebouwd.get(d.id))) tot = i + 1; });
    if (!io) tot = rij.length; else if (!tot) tot = Math.min(rij.length, STAP);
    const wil = rij.slice(0, tot).map(d => { if (!gebouwd.has(d.id)) gebouwd.set(d.id, kaart(d)); return gebouwd.get(d.id); });
    const blijft = new Set(wil);
    [...lb.children].forEach(c => { if (!blijft.has(c)) c.remove(); });
    let plek = lb.firstElementChild;
    for (const n of wil) { if (n === plek) plek = plek.nextElementSibling; else lb.insertBefore(n, plek); }
    getoond = tot; kijk();
  }

  const wl = document.querySelector(".wl"), kies = document.getElementById("gemeente");
  if (!kies || !PAYLOAD.filter) {   // zonder filterpaneel (een stad): alleen de verborgen panden eruit
    let vak = null;   // het lege vak, pas gemaakt als alles verborgen is (VA-90, Lumi §7)
    const alles = houd => { const r = LEADS.filter(d => BW.zichtbaar(d.id));
      if (!r.length && LEADS.length && !vak) { vak = maak("div", "wl-leeg"); vak.append(maak("p")); lb.before(vak); }
      if (vak) { BW.leeg(vak, r.length ? 0 : LEADS.length, false); vak.hidden = r.length > 0; }
      lb.hidden = !r.length; teken(r, houd); };
    BW.op(() => alles(true)); alles(false); return;
  }
  const F = PAYLOAD.filter;
  const T = PAYLOAD.filter.tekst, $ = s => wl.querySelector(s);
  const knop = $(".wl-knop"), paneel = $(".wl-paneel"), telling = $(".wl-telling"), chipsEl = $(".wl-chips");
  const leeg = $(".wl-leeg"), toon = $(".wl-toon"), opties = [...wl.querySelectorAll(".wl-optie")];
  const SIG = {leeg: "leeg", verbouwing: "bouw"};   // adreswaarde -> sig.k op de kaart
  const HEEFT = {cat: (d, w) => d.cat.includes(w), sig: (d, w) => d.sig.some(s => s.k === SIG[w]),
                 geb: (d, w) => d.gg === (w === "groot" ? 1 : 0)};
  const LIJST = [["cat", "categorie"], ["sig", "signaal"], ["geb", "gebied"]];   // groep, adresparameter
  const KEUZES = Object.fromEntries(LIJST.map(([g]) => [g, opties.filter(o => o.dataset.groep === g).map(o => o.dataset.waarde)]));
  const GEMEENTEN = [...kies.options].map(o => o.value).filter(Boolean);
  // Getalvelden (VA-69) en sorteren (VA-70): de velden, zinnen en richtingen komen uit bereik_filter() in Python.
  const BEREIK = F.bereik || [], SORT = F.sorteer || {}, STD = Object.keys(SORT)[0];
  const sortEl = document.getElementById("wl-sorteer"), dirEl = document.getElementById("wl-volgorde");
  const EIGEN = ["gemeente", ...LIJST.map(([, p]) => p), ...BEREIK.flatMap(b => b.url), "sorteer", "richting"];
  const leegRuw = () => Object.fromEntries(BEREIK.map(b => [b.k, {van: "", tm: ""}]));
  const st = {gemeente: "", cat: new Set(), sig: new Set(), geb: new Set(), ruw: leegRuw(),
              sort: STD, dir: STD ? SORT[STD].std : "af"};
  let B = {};   // per getalveld wat telt: {aan, van, tm}, of {aan: false, fout, veld} bij een ongeldige invoer
  const vul = (zin, n) => zin.replace("{n}", nl(n));
  const grens = (b, v) => b.jaar ? String(v) : nl(v);   // een jaartal nooit door nl(): 1939, niet 1.939

  // "1.200" en "1 200" worden 1200; een komma of een letter is ongeldig (Lumi, bouwnotitie 4).
  function getal(s) { s = String(s).trim(); if (!s) return null; const t = s.replace(/[.\s]/g, ""); return /^\d{1,6}$/.test(t) ? Number(t) : NaN; }
  // Een ongeldig getal of van > tot en met zet alleen dat veld uit, met een melding; de rest werkt door (crit. 5).
  function bereik(b, r) {
    const v = getal(r.van), t = b.url.length > 1 ? getal(r.tm) : null;
    const fv = Number.isNaN(v) || (b.max != null && v !== null && v > b.max), ft = Number.isNaN(t);
    if (fv || ft) return {aan: false, fout: b.fout, veld: fv && ft ? "beide" : fv ? "van" : "tm"};
    if (v === null && t === null) return {aan: false};
    if (v !== null && t !== null && v > t) return {aan: false, fout: T.omgekeerd, veld: "beide"};
    return {aan: true, van: v, tm: t};
  }

  function past(d, behalve, alle) {   // alle: ook de verborgen panden (alleen voor het lege vak, VA-90)
    if (!alle && !BW.zichtbaar(d.id)) return false;   // VA-90: een verborgen pand telt nergens mee, tot je ze toont
    if (behalve !== "gemeente" && st.gemeente && d.g !== st.gemeente) return false;
    for (const [g] of LIJST) if (g !== behalve && st[g].size && ![...st[g]].some(w => HEEFT[g](d, w))) return false;
    // Grenzen tellen mee; een pand zonder waarde valt weg zolang er een grens staat (VA-69 crit. 4).
    for (const b of BEREIK) { const x = B[b.k], v = d[b.veld]; if (!x.aan) continue;
      if (v == null || (x.van !== null && v < x.van) || (x.tm !== null && v > x.tm)) return false; }
    return true;
  }
  // Gelijk blijft in de volgorde van de werklijst (score, dan VA-32); zonder waarde altijd achteraan (VA-70 crit. 3).
  const PLAATS = new Map(LEADS.map((d, i) => [d, i]));
  function sorteer(lijst) {
    if (!STD) return lijst;
    const k = SORT[st.sort].veld, op = st.dir === "op", na = (a, b) => PLAATS.get(a) - PLAATS.get(b);
    return lijst.slice().sort((a, b) => { const x = a[k], y = b[k];
      if (x == null || y == null) return x == null && y == null ? na(a, b) : x == null ? 1 : -1;
      return x === y ? na(a, b) : op ? x - y : y - x; });
  }
  // Beide gebieden aan is hetzelfde als geen van beide (crit. 3): dat is geen actief filter.
  const telt = g => st[g].size > 0 && !(g === "geb" && st.geb.size === KEUZES.geb.length);

  function chips() {
    const c = [];
    if (st.gemeente) c.push([T.chipGemeente.replace("{gemeente}", () => st.gemeente), () => { st.gemeente = ""; }]);
    for (const g of ["geb", "cat", "sig"]) if (telt(g))
      opties.forEach(o => { const w = o.dataset.waarde; if (o.dataset.groep === g && st[g].has(w)) c.push([o.dataset.chip, () => st[g].delete(w)]); });
    for (const b of BEREIK) { const x = B[b.k]; if (!x.aan) continue;   // geen chip voor de sortering: dat is geen filter
      const zin = x.van !== null && x.tm !== null ? b.chips.vanTm : x.van !== null ? b.chips.van : b.chips.tm;
      c.push([zin.replace("{van}", () => grens(b, x.van)).replace("{tm}", () => grens(b, x.tm)), () => { st.ruw[b.k] = {van: "", tm: ""}; }]); }
    return c;
  }
  function knopje(cls, tekst, klik) { const b = maak("button", cls, tekst); b.type = "button"; b.addEventListener("click", klik); return b; }
  let volgordeVan = STD;   // voor welk veld de opties van Volgorde nu staan (de HTML begint bij score)
  function zetSortering() {
    if (!sortEl || !dirEl) return;
    if (volgordeVan !== st.sort) {   // een ander veld: de richtingen van dat veld, de standaard eerst
      dirEl.textContent = ""; SORT[st.sort].opties.forEach(([r, n]) => dirEl.add(new Option(n, r))); volgordeVan = st.sort; }
    sortEl.value = st.sort; dirEl.value = st.dir;
  }

  function werk(schrijf, houd) {
    B = Object.fromEntries(BEREIK.map(b => [b.k, bereik(b, st.ruw[b.k])]));
    const treffers = LEADS.filter(d => past(d, null)), n = treffers.length;
    const zonder = g => LEADS.filter(d => past(d, g));
    const basis = {gemeente: zonder("gemeente"), cat: zonder("cat"), sig: zonder("sig"), geb: zonder("geb")};
    opties.forEach(o => {
      const g = o.dataset.groep, w = o.dataset.waarde, c = basis[g].filter(d => HEEFT[g](d, w)).length;
      o.querySelector("input").checked = st[g].has(w);
      o.querySelector(".wl-getal").textContent = nl(c);
      o.classList.toggle("nul", c === 0);
    });
    const perGemeente = {};
    basis.gemeente.forEach(d => { perGemeente[d.g] = (perGemeente[d.g] || 0) + 1; });
    for (const o of kies.options) o.textContent = o.value
      ? T.gemOptie.replace("{gemeente}", () => o.value).replace("{aantal}", nl(perGemeente[o.value] || 0))
      : vul(T.gemAlle, basis.gemeente.length);
    kies.value = st.gemeente;
    BEREIK.forEach(b => {
      const x = B[b.k], fout = $(`#wl-${b.k}-fout`);
      for (const k of ["van", "tm"]) { const inp = $(`#wl-${b.k}-${k}`); if (!inp) continue;
        if (inp.value !== st.ruw[b.k][k]) inp.value = st.ruw[b.k][k];
        if (x.fout && (x.veld === "beide" || x.veld === k)) inp.setAttribute("aria-invalid", "true"); else inp.removeAttribute("aria-invalid"); }
      fout.textContent = x.fout || ""; fout.hidden = !x.fout;
    });
    zetSortering();

    const lijst = chips(), a = lijst.length, bol = $(".wl-aantal");
    bol.hidden = !a; bol.textContent = nl(a); $(".wl-actief").textContent = a ? vul(T.actief, a) : "";
    telling.textContent = a || n !== LEADS.length ? vul(T.telling, n) : T.alle;   // n = de kaarten op het scherm
    toon.textContent = n === 0 ? T.toonNul : n === 1 ? T.toonEen : vul(T.toon, n);
    chipsEl.textContent = ""; chipsEl.hidden = !a;
    lijst.forEach(([tekst, weg], i) => {
      const b = knopje("wl-chip", tekst, () => {
        weg(); werk(true);
        const rest = chipsEl.querySelectorAll(".wl-chip");
        (rest[i] || rest[i - 1] || knop).focus();
      });
      b.setAttribute("aria-label", T.chipNaam.replace("{chip}", () => tekst));
      const x = maak("span", "x", "×"); x.setAttribute("aria-hidden", "true"); b.append(x);
      chipsEl.append(b);
    });
    if (a) chipsEl.append(knopje("wl-wis", T.wis, wisAlles));
    BW.leeg(leeg, n ? 0 : LEADS.filter(d => past(d, null, true)).length, a > 0);   // VA-90: leeg door Verberg?
    leeg.hidden = n > 0; lb.hidden = n === 0;
    teken(sorteer(treffers), houd);   // dezelfde kaarten uit 'gebouwd', in de nieuwe volgorde: geen tweede PDOK-verzoek
    if (schrijf) schrijfAdres();
  }
  // De sortering blijft staan: die knop wist alleen de filters (Lumi, kopij 'wis').
  function wisAlles() { st.gemeente = ""; LIJST.forEach(([g]) => st[g].clear()); st.ruw = leegRuw(); werk(true); knop.focus(); }

  // Het adres (crit. 9): een onbekende of ongeldige waarde valt weg, de rest geldt.
  function leesAdres() {
    const q = new URLSearchParams(location.search), gem = (q.get("gemeente") || "").trim().toLowerCase();
    st.gemeente = GEMEENTEN.find(g => g.toLowerCase() === gem) || "";
    for (const [g, p] of LIJST) (q.get(p) || "").split(",").forEach(x => {
      const w = KEUZES[g].find(k => k.toLowerCase() === x.trim().toLowerCase()); if (w) st[g].add(w); });
    // Een ongeldig getal laat het veld leeg; van > tot en met krijgt de waarden en de melding, net als bij typen.
    for (const b of BEREIK) b.url.forEach((p, j) => { const v = (q.get(p) || "").trim();
      if (/^\d{1,6}$/.test(v) && !(b.max != null && Number(v) > b.max)) st.ruw[b.k][j ? "tm" : "van"] = v; });
    const s = (q.get("sorteer") || "").trim().toLowerCase(), r = (q.get("richting") || "").trim().toLowerCase();
    if (Object.keys(SORT).includes(s)) st.sort = s;
    if (STD) st.dir = r === "op" || r === "af" ? r : SORT[st.sort].std;
  }
  // In de volgorde van Lumi's tabel, alleen wat meetelt; de standaardsortering staat er niet in.
  function schrijfAdres() {
    const q = new URLSearchParams(location.search), uit = [];
    EIGEN.forEach(p => q.delete(p));
    const zet = (p, v) => uit.push(p + "=" + encodeURIComponent(v).replace(/%2C/gi, ","));
    if (st.gemeente) zet("gemeente", st.gemeente);
    for (const [g, p] of LIJST) { const w = KEUZES[g].filter(k => st[g].has(k)); if (w.length) zet(p, w.join(",")); }
    for (const b of BEREIK) { const x = B[b.k]; if (!x.aan) continue;
      if (x.van !== null) zet(b.url[0], x.van); if (x.tm !== null) zet(b.url[1], x.tm); }
    if (STD && st.sort !== STD) zet("sorteer", st.sort);
    if (STD && st.dir !== SORT[st.sort].std) zet("richting", st.dir);
    const rest = q.toString(), s = uit.concat(rest ? [rest] : []).join("&");
    history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash);
  }

  // Het paneel: open vanaf 801 px (de grens van het menu, VA-63), anders dicht achter "Filters".
  const zetOpen = open => { knop.setAttribute("aria-expanded", String(open)); paneel.hidden = !open; };
  const dicht = () => { zetOpen(false); knop.focus(); };
  knop.addEventListener("click", () => zetOpen(paneel.hidden));
  toon.addEventListener("click", dicht);
  paneel.addEventListener("keydown", e => { if (e.key === "Escape" && wl.clientWidth < 600) dicht(); });
  // Vakjes en selects gelden meteen; een getalveld 400 ms na de laatste toets, en meteen bij change.
  const typen = new Map();
  paneel.addEventListener("input", e => {
    const t = e.target; if (!t.dataset.k) return;
    st.ruw[t.dataset.k][t.dataset.x] = t.value; clearTimeout(typen.get(t)); typen.set(t, setTimeout(() => werk(true), 400));
  });
  paneel.addEventListener("change", e => {
    const t = e.target, o = t.closest(".wl-optie");
    if (t === kies) st.gemeente = t.value;
    else if (o) { const set = st[o.dataset.groep]; if (t.checked) set.add(o.dataset.waarde); else set.delete(o.dataset.waarde); }
    else if (t.dataset.k) { clearTimeout(typen.get(t)); st.ruw[t.dataset.k][t.dataset.x] = t.value; }
    else return;
    werk(true);
  });
  // Een ander veld springt naar zijn eigen standaardrichting (Lumi, VA-70).
  if (sortEl) sortEl.addEventListener("change", () => { st.sort = sortEl.value; st.dir = SORT[st.sort].std; werk(true); });
  if (dirEl) dirEl.addEventListener("change", () => { st.dir = dirEl.value; werk(true); });
  leeg.querySelector(".wl-wis").addEventListener("click", wisAlles);
  zetOpen(matchMedia("(min-width: 801px)").matches);
  leesAdres();
  werk(false);
  BW.op(() => werk(false, true));   // VA-90: na Bewaar of Verberg; het adres verandert niet
})();
/* ============================ einde WERKLIJST ============================ */

const tt=document.getElementById("tt");
document.addEventListener("pointerover",e=>{const t=e.target.closest("[data-tip]");
  if(!t)return;tt.textContent=t.getAttribute("data-tip");tt.style.opacity="1";});
document.addEventListener("pointermove",e=>{if(tt.style.opacity==="1"){
  tt.style.left=e.clientX+"px";tt.style.top=(e.clientY-6)+"px";}});
document.addEventListener("pointerout",e=>{if(e.target.closest("[data-tip]"))tt.style.opacity="0";});

const root=document.documentElement;
document.getElementById("themeBtn").addEventListener("click",()=>{
  const cur=root.getAttribute("data-theme");
  const dark=cur?cur==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme",dark?"light":"dark");
});

/* ============================ MENU (VA-63, VA-64) ============================
   Breed een zijbalk, tot 800 px een bovenbalk met lade. Elk item brengt je naar zijn deel van
   dezelfde pagina; het kantoor blijft altijd bovenaan in beeld (Ayman, VA-48 crit. 8).
   Het actieve item volgt het scrollen, één keer per frame. Alle tekst staat al in de HTML. */
(() => {
  const vg = document.getElementById("vg");
  const side = vg.querySelector(".side"), knop = vg.querySelector(".menuknop"), main = vg.querySelector(".inhoud");
  const links = [...vg.querySelectorAll(".nav a[data-doel]")];
  const DELEN = links.map(a => a.dataset.doel);
  const delen = DELEN.map(id => document.getElementById(id));
  const mqSmal = matchMedia("(max-width: 800px)"), rustig = matchMedia("(prefers-reduced-motion: reduce)");
  const isOpen = () => vg.classList.contains("open");

  function openMenu() {
    vg.classList.add("open"); knop.setAttribute("aria-expanded", "true");
    main.inert = true; document.body.style.overflow = "hidden";
    (side.querySelector(".nav a[aria-current]") || links[0]).focus();
  }
  function sluitMenu(terug) {
    if (!isOpen()) return;
    vg.classList.remove("open"); knop.setAttribute("aria-expanded", "false");
    main.inert = false; document.body.style.overflow = "";
    if (terug) knop.focus();
  }
  // Breder dan 800 px terwijl de lade open is: dicht, zonder de focus te verplaatsen.
  mqSmal.addEventListener("change", () => { if (!mqSmal.matches) sluitMenu(false); });
  // Overgangen pas na de eerste frames, anders schuift de lade bij het laden zichtbaar weg.
  requestAnimationFrame(() => requestAnimationFrame(() => vg.classList.add("klaar")));

  knop.addEventListener("click", () => isOpen() ? sluitMenu(true) : openMenu());
  vg.querySelector(".sluit-menu").addEventListener("click", () => sluitMenu(true));
  vg.querySelector(".scrim").addEventListener("click", () => sluitMenu(true));
  side.addEventListener("keydown", e => {   // Tab blijft in de open lade
    if (e.key !== "Tab" || !isOpen()) return;
    const f = [...side.querySelectorAll("a[href], button")];
    const eerste = f[0], laatste = f[f.length - 1];
    if (e.shiftKey && document.activeElement === eerste) { e.preventDefault(); laatste.focus(); }
    else if (!e.shiftKey && document.activeElement === laatste) { e.preventDefault(); eerste.focus(); }
  });
  // Escape sluit eerst de lade; de uitleg van het kantoor hoort deze toets dan niet.
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !isOpen()) return;
    e.preventDefault(); e.stopPropagation(); sluitMenu(true);
  }, true);

  // Een deel met .pagina (Bewaarde panden) is een eigen pagina: dan staat alleen dat deel er (.op-pagina op
  // .vg, .nu op het deel; de CSS doet de rest). De andere delen zijn samen de lange scroll.
  const PAGINAS = delen.filter(d => d.classList.contains("pagina")).map(d => d.id);
  const scroll = delen.filter(d => !PAGINAS.includes(d.id));
  const opPagina = () => vg.classList.contains("op-pagina");
  function toon(id) {   // geeft true als de keuze tussen pagina en lange scroll veranderde
    const p = PAGINAS.includes(id), was = opPagina();
    vg.classList.toggle("op-pagina", p);
    delen.forEach(d => d.classList.toggle("nu", p && d.id === id));
    return p !== was;
  }
  function ga(id, glijd) {   // naar een deel of pagina; het adres zet de aanroeper
    const anders = toon(id);
    zet(id, false); slot = Date.now() + 900;
    const d = document.getElementById(id);
    if (PAGINAS.includes(id)) { scrollTo({top: 0, behavior: "instant"}); d.focus({preventScroll: true}); }
    else d.scrollIntoView({behavior: glijd && !anders && !rustig.matches ? "smooth" : "instant"});
  }

  let actief = null, slot = 0;
  function zet(id, adres) {
    if (id === actief) return;
    actief = id;
    links.forEach(a => a.dataset.doel === id ? a.setAttribute("aria-current", "location") : a.removeAttribute("aria-current"));
    if (adres) history.replaceState(null, "", "#" + id);
  }
  // Actief is het laatste deel waarvan de bovenkant boven 30% van het scherm staat (smal: plus de
  // bovenbalk van 56 px); helemaal onderaan is het laatste deel actief.
  function bepaal() {
    if (Date.now() < slot || opPagina()) return;   // op een eigen pagina blijft die pagina actief
    const lijn = (mqSmal.matches ? 56 : 0) + innerHeight * 0.3;
    let id = scroll[0].id;
    scroll.forEach(d => { if (d.getBoundingClientRect().top <= lijn) id = d.id; });
    if (vg.getBoundingClientRect().bottom <= innerHeight + 2) id = scroll[scroll.length - 1].id;
    zet(id, true);
  }
  let wacht = false;
  addEventListener("scroll", () => { if (!wacht) { wacht = true; requestAnimationFrame(() => { wacht = false; bepaal(); }); } }, {passive: true});
  addEventListener("scrollend", () => { slot = 0; bepaal(); });

  // Elke link naar een deel (het menu, en 'Terug naar de werklijst' op een pagina) gaat via ga(): het
  // adres komt in de geschiedenis, dus de terugknop van de browser brengt je terug.
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest('a[href^="#"]');
    const id = a && a.getAttribute("href").slice(1);
    if (!DELEN.includes(id) || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (isOpen()) sluitMenu(!PAGINAS.includes(id));
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    ga(id, true);
  });
  addEventListener("popstate", () => { const id = location.hash.slice(1); ga(DELEN.includes(id) ? id : scroll[0].id, false); });

  // Openen met een adres: de cijfers en kaarten staan er nu, dus één keer naar het deel.
  const start = location.hash.slice(1);
  if (DELEN.includes(start)) ga(start, false);
  else zet(DELEN[0], false);
})();
/* ============================ einde MENU ============================ */

/* ============================ BEGIN PIXELKANTOOR ============================
   Pixelkantoor: elke stap van de pandenselectie is een medewerker aan een bureau.
   Toestand per medewerker: werkt = typt, aandacht = hand omhoog + "!",
   slaapt = dommelt met zzz, leeg = haalt de schouders op (geen data).
   Bouw: palet() -> tekenKamer() -> tekenMedewerker() per bureau; toestand en zinnen uit kantoor_teksten() in Python.
============================================================================== */
const PK = (() => {
  // ---------------------------------------------------------------- kleuren
  // Elke kleur is een token uit index.html of een menging van twee daarvan.
  const rgb = c => { c = String(c).trim();
    if (c[0] === "#") { if (c.length === 4) c = "#" + [...c.slice(1)].map(x => x + x).join("");
      return [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)); }
    const m = c.match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number) : [0, 0, 0]; };
  const hex = a => "#" + a.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const A = rgb(a), B = rgb(b); return hex(A.map((v, i) => v + (B[i] - v) * t)); };
  const helder = c => { const [r, g, b] = rgb(c); return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255; };

  // Mensen, schermen en kantoorspullen veranderen niet met het thema: vaste waarden uit index.html.
  const V = {
    zwart: "#0b0b0b", wit: "#ffffff", grijs: "#52514e", grijs2: "#898781", licht: "#c3c2b7", lijn: "#e1e0d9",
    navy: "#12233b", blauwgrijs: "#9fb3cc", ijsblauw: "#c6d3e4", bruin: "#3a2a00", donker: "#2c2c2a", donker2: "#383835",
    s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", s4: "#eda100", s5: "#e87ba4", good: "#0ca30c",
  };
  V.scherm = mix(V.navy, V.zwart, .35); V.schermUit = mix(V.navy, V.zwart, .6);
  // [haar, shirt, huid, kapsel, accent]
  const LOOK = {
    ingest:     [V.bruin,               V.navy,       mix(V.s2, V.wit, .66),                     0, V.wit],
    selectie:   [mix(V.s4, V.bruin, .3), V.blauwgrijs, mix(mix(V.s2, V.s4, .5), V.wit, .42),     1, null],
    verrijking: [V.zwart,               V.grijs,      mix(V.s2, V.bruin, .55),                   2, null],
    controle:   [V.grijs2,              V.ijsblauw,   mix(V.s2, V.wit, .56),                     3, V.navy],
  };

  function palet(el) {
    const cs = getComputedStyle(el), v = n => cs.getPropertyValue(n).trim();
    const T = {plane: v("--plane"), surface: v("--surface"), surface2: v("--surface-2"), ink2: v("--ink-2"),
      muted: v("--muted"), grid: v("--grid"), baseline: v("--baseline"), s1: v("--s1"), s3: v("--s3"),
      s4: v("--s4"), good: v("--good"), brand: v("--brand")};
    const d = helder(T.plane) < .5;
    const P = {donker: d, ...T};
    P.wand = d ? mix(T.surface, T.surface2, .5) : mix(T.plane, T.grid, .35);
    P.lambris = T.brand; P.lambrisLijn = mix(T.brand, V.blauwgrijs, d ? .14 : .3);
    P.plint = d ? T.baseline : mix(T.brand, V.blauwgrijs, .3);
    P.vloer = d ? mix(T.s4, T.surface, .8) : mix(T.s4, T.grid, .72);
    P.plank = d ? mix(T.s4, T.surface, .88) : mix(T.s4, T.baseline, .62);
    P.blad = d ? mix(mix(T.s4, V.bruin, .55), T.surface, .3) : mix(mix(T.s4, V.bruin, .4), T.baseline, .25);
    P.front = mix(P.blad, d ? V.zwart : V.bruin, .3); P.lade = mix(P.front, V.zwart, .25);
    P.kast = d ? T.baseline : T.baseline; P.kast2 = mix(T.baseline, V.zwart, d ? .3 : .15); P.greep = d ? T.muted : T.surface2;
    P.kozijn = d ? T.baseline : T.baseline;
    P.papier = d ? V.licht : V.wit; P.papier2 = d ? mix(V.licht, V.grijs, .3) : V.lijn;
    P.land = mix(T.s3, P.papier, .5); P.water = mix(T.s1, P.papier, .62);
    P.pot = mix(V.s2, V.bruin, .35); P.blad1 = T.s3; P.blad2 = mix(T.s3, V.zwart, .25);
    P.stoel = d ? V.zwart : V.donker2; P.schaduw = mix(P.vloer, V.zwart, .18);
    P.keuze = mix(T.s1, P.vloer, .72); P.z = T.muted;
    return P;
  }

  function lucht() {
    const u = new Date().getHours() + new Date().getMinutes() / 60;
    if (u < 6 || u >= 21) return [V.navy, mix(V.navy, V.s1, .25), true];
    if (u < 8) return [mix(V.s2, V.wit, .35), mix(V.s4, V.wit, .55), false];
    if (u < 18) return [mix(V.s1, V.wit, .5), mix(V.s1, V.wit, .72), false];
    return [mix(V.s2, V.wit, .2), mix(V.s4, V.wit, .45), false];
  }

  // ------------------------------------------------------------- tekenaar
  // Logische pixels; elke rechthoek valt op hele schermpixels, op elke breedte scherp.
  function tekenaar(cv) {
    const ctx = cv.getContext("2d");
    const R = {W: 1, H: 1, k: 1, ctx,
      maat(cssB) { const d = window.devicePixelRatio || 1;
        cv.width = Math.max(1, Math.round(cssB * d)); cv.height = Math.max(1, Math.round(cv.width * R.H / R.W));
        R.k = cv.width / R.W; ctx.imageSmoothingEnabled = false; },
      px(x, y, w, h, c) { const k = R.k; x = Math.round(x); y = Math.round(y);
        const x0 = Math.round(x * k), y0 = Math.round(y * k), x1 = Math.round((x + w) * k), y1 = Math.round((y + h) * k);
        ctx.fillStyle = c; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); },
      wis() { ctx.clearRect(0, 0, cv.width, cv.height); },
    };
    return R;
  }

  // ---------------------------------------------------------------- kamer
  const KAART = [ // Nederland, 16 x 20: # land, ~ IJsselmeer
    "...#.##.##.#....", "................", "....#..########.", "....#~~#########",
    "...##~~~########", "...#~~~~~#######", "...##~~~~#######", "...###~~########",
    "...#############", "..##############", "..#############.", "..############..",
    ".#.############.", "#.#############.", ".##############.", "#..###########..",
    "...........###..", "...........##...", "...........###..", "............#...",
  ];
  const DECOR = {
    kast(R, d, t, P, L) { const x = d.x, top = L.VLOER - 34;
      R.px(x, top, 16, 34, P.kast); R.px(x, top, 16, 1, P.kast2);
      for (let i = 0; i < 3; i++) { const y = top + 3 + i * 10;
        R.px(x + 2, y, 12, 8, P.kast2); R.px(x + 3, y + 1, 10, 6, P.kast);
        R.px(x + 6, y + 2, 4, 2, P.papier); R.px(x + 7, y + 5, 2, 1, P.greep); } },
    tekening(R, d, t, P) { const x = d.x, y = d.y; // bouwtekening: plattegrond op navy
      R.px(x, y, 28, 18, P.brand); const l = V.blauwgrijs;
      R.px(x + 3, y + 3, 22, 1, l); R.px(x + 3, y + 14, 22, 1, l); R.px(x + 3, y + 3, 1, 12, l); R.px(x + 24, y + 3, 1, 12, l);
      R.px(x + 12, y + 3, 1, 7, l); R.px(x + 12, y + 12, 1, 3, l); R.px(x + 13, y + 9, 11, 1, l);
      R.px(x + 6, y + 14, 3, 1, P.brand); R.px(x + 5, y + 12, 1, 1, l); R.px(x + 6, y + 11, 1, 1, l); R.px(x + 7, y + 11, 1, 1, l);
      R.px(x + 16, y + 6, 4, 1, mix(l, P.brand, .4)); R.px(x + 5, y + 6, 4, 1, mix(l, P.brand, .4));
      R.px(x + 1, y - 1, 2, 2, V.s2); R.px(x + 25, y - 1, 2, 2, V.s2); },
    raam(R, d, t, P) { const w = 30, h = 22, x = d.cx - w / 2, y = d.y, [a, b, nacht] = lucht();
      R.px(x - 2, y - 2, w + 4, h + 4, P.kozijn); R.px(x, y, w, h / 2, a); R.px(x, y + h / 2, w, h / 2, b);
      if (nacht) { for (let i = 0; i < 6; i++) { const sx = (d.cx * 7 + i * 37) % (w - 2), sy = (i * 13 + d.cx) % (h - 4);
          if (d.stil || (t / 600 + i) % 3 > .6) R.px(x + 1 + sx, y + 1 + sy, 1, 1, V.ijsblauw); } R.px(x + w - 8, y + 3, 4, 4, V.lijn); }
      else { const ctx = R.ctx, k = R.k, cx = x + ((d.stil ? 20 : t / 120 + d.cx * 3) % (w + 12)) - 8;
        ctx.save(); ctx.beginPath(); ctx.rect(Math.round(x * k), Math.round(y * k), Math.round(w * k), Math.round(h * k)); ctx.clip();
        R.px(cx, y + 4, 8, 2, V.wit); R.px(cx + 2, y + 2, 4, 2, V.wit); R.px(cx + 15, y + 13, 6, 2, mix(V.wit, b, .3)); ctx.restore();
        // daken achter het raam: trapgevels
        const dak = mix(V.navy, b, .55);
        for (let i = 0; i < w; i += 7) { const hg = 4 + ((i * 3 + d.cx) % 4);
          R.px(x + i, y + h - hg, 6, hg, dak); R.px(x + i + 2, y + h - hg - 2, 2, 2, dak); }
      }
      R.px(d.cx - 1, y, 2, h, P.kozijn); R.px(x, y + h / 2 - 1, w, 2, P.kozijn);
      R.px(x - 3, y + h + 2, w + 6, 2, P.kast2); },
    klok(R, d, t, P) { const cx = d.cx, cy = d.y + 5;
      R.px(cx - 3, cy - 5, 7, 1, P.brand); R.px(cx - 3, cy + 5, 7, 1, P.brand); R.px(cx - 5, cy - 3, 1, 7, P.brand); R.px(cx + 5, cy - 3, 1, 7, P.brand);
      R.px(cx - 4, cy - 4, 1, 1, P.brand); R.px(cx + 4, cy - 4, 1, 1, P.brand); R.px(cx - 4, cy + 4, 1, 1, P.brand); R.px(cx + 4, cy + 4, 1, 1, P.brand);
      R.px(cx - 4, cy - 3, 9, 7, P.papier); R.px(cx - 3, cy - 4, 7, 9, P.papier);
      const nu = d.stil ? new Date(0, 0, 1, 10, 10) : new Date(), uur = (nu.getHours() % 12 + nu.getMinutes() / 60) / 12, min = nu.getMinutes() / 60;
      const wijzer = (f, n, c) => { const a = f * Math.PI * 2; for (let i = 1; i <= n; i++) R.px(cx + Math.round(Math.sin(a) * i), cy - Math.round(Math.cos(a) * i), 1, 1, c); };
      wijzer(min, 3, V.grijs); wijzer(uur, 2, V.zwart); R.px(cx, cy, 1, 1, V.s2); },
    kaart(R, d, t, P) { const x = d.cx - 10, y = d.y; // kaart van Nederland, met punaises
      R.px(x, y, 20, 24, P.papier2); R.px(x + 1, y + 1, 18, 22, P.water);
      KAART.forEach((r, j) => [...r].forEach((c, i) => {
        if (c === "#") R.px(x + 2 + i, y + 2 + j, 1, 1, P.land);
        else if (c === "~") R.px(x + 2 + i, y + 2 + j, 1, 1, mix(P.water, P.land, .25)); }));
      R.px(x, y, 2, 2, V.s2); R.px(x + 18, y, 2, 2, V.s2); },
    ordners(R, d, t, P) { const x = d.x, y = d.y, kl = [V.navy, V.blauwgrijs, V.licht, V.navy, V.grijs, V.blauwgrijs, V.ijsblauw];
      kl.forEach((c, i) => { const h = 10 - (i % 3 === 1 ? 1 : 0); R.px(x + i * 4, y + 10 - h, 3, h, c); R.px(x + i * 4 + 1, y + 10 - h + 2, 1, 2, V.wit); });
      R.px(x - 2, y + 10, kl.length * 4 + 3, 2, P.front); },
    plant(R, d, t, P, L) { const pl = d.x, F = L.VLOER, sway = !d.stil && Math.sin(t / 900 + pl) > .6 ? 1 : 0;
      R.px(pl, F - 6, 7, 6, P.pot); R.px(pl + 1, F - 7, 5, 1, mix(P.pot, V.zwart, .2));
      R.px(pl + 2 + sway, F - 13, 3, 6, P.blad2); R.px(pl + sway, F - 11, 2, 3, P.blad1); R.px(pl + 5 + sway, F - 12, 2, 4, P.blad1); },
  };

  function tekenKamer(R, L, t, P, stil) {
    const {W, H, VLOER, LAMBRIS} = L;
    R.px(0, 0, W, VLOER, P.wand);
    R.px(0, LAMBRIS, W, VLOER - LAMBRIS, P.lambris); R.px(0, LAMBRIS, W, 1, P.lambrisLijn);
    for (let x = 6; x < W; x += 24) { R.px(x, LAMBRIS + 4, 16, 1, P.lambrisLijn); R.px(x, VLOER - 4, 16, 1, P.lambrisLijn);
      R.px(x, LAMBRIS + 4, 1, VLOER - LAMBRIS - 7, P.lambrisLijn); R.px(x + 15, LAMBRIS + 4, 1, VLOER - LAMBRIS - 7, P.lambrisLijn); }
    R.px(0, VLOER, W, H - VLOER, P.vloer);
    for (let y = VLOER + 8; y < H; y += 9) R.px(0, y, W, 1, P.plank);
    for (let x = 0; x < W; x += 24) for (let y = VLOER; y < H; y += 18) R.px(x + (y % 36 ? 12 : 0), y, 1, 9, P.plank);
    R.px(0, VLOER, W, 2, P.plint);
    (L.decor || []).forEach(d => DECOR[d.s](R, {...d, stil}, t, P, L));
  }

  // ------------------------------------------------------------ medewerker
  function persoon(R, cx, y, look, o) {
    const [haar, shirt, huid, kapsel, accent] = look, px = R.px;
    y += (o.bob || 0);
    px(cx - 4, y - 8, 8, 8, shirt);                                       // romp
    if (accent && kapsel === 0) px(cx - 1, y - 8, 2, 3, accent);          // overhemd onder colbert
    if (accent && kapsel === 3) px(cx - 1, y - 8, 1, 5, accent);          // das
    if (o.hand) { px(cx - 6, y - 7, 2, 6, shirt); px(cx - 6, y - 1, 2, 2, huid);
      px(cx + 4, y - 15, 2, 9, shirt); px(cx + 4, y - 17, 2, 2, huid); }
    else if (o.schouder) { px(cx - 6, y - 7, 2, 4, shirt); px(cx - 8, y - 8, 2, 2, shirt); px(cx - 9, y - 10, 2, 2, huid);
      px(cx + 4, y - 7, 2, 4, shirt); px(cx + 6, y - 8, 2, 2, shirt); px(cx + 7, y - 10, 2, 2, huid); }
    else if (o.typt !== undefined) { const a = o.typt;
      px(cx - 6, y - 7, 2, 5, shirt); px(cx - 5, y - 2 - a, 3, 2, huid); px(cx + 4, y - 7, 2, 5, shirt); px(cx + 2, y - 3 + a, 3, 2, huid); }
    else { px(cx - 6, y - 7, 2, 6, shirt); px(cx - 6, y - 1, 2, 2, huid); px(cx + 4, y - 7, 2, 6, shirt); px(cx + 4, y - 1, 2, 2, huid); }
    const hy = y - 15;                                                     // hoofd
    px(cx - 3, hy, 6, 7, huid); px(cx - 4, hy + 3, 1, 2, huid); px(cx + 3, hy + 3, 1, 2, huid);
    const k = o.kijk || 0;
    if (o.slaap) { px(cx - 2, hy + 4, 2, 1, V.bruin); px(cx + 1, hy + 4, 2, 1, V.bruin); }
    else if (!o.knipper) { px(cx - 2 + k, hy + 3, 1, 2, V.zwart); px(cx + 1 + k, hy + 3, 1, 2, V.zwart); }
    if (o.bril) { px(cx - 3, hy + 2, 6, 1, V.grijs); }
    if (o.zorg) px(cx - 1, hy + 6, 2, 1, V.bruin);
    else if (o.vraag) { px(cx - 1, hy + 6, 1, 1, V.bruin); px(cx, hy + 5, 1, 1, V.bruin); }
    if (kapsel === 0) { px(cx - 3, hy - 1, 6, 2, haar); px(cx - 4, hy, 1, 3, haar); px(cx + 3, hy, 1, 2, haar); }
    if (kapsel === 1) { px(cx - 4, hy - 1, 8, 2, haar); px(cx - 4, hy + 1, 1, 7, haar); px(cx + 3, hy + 1, 1, 7, haar); }
    if (kapsel === 2) { px(cx - 3, hy - 1, 6, 1, haar); px(cx - 3, hy, 1, 1, haar); px(cx + 2, hy, 1, 1, haar); }
    if (kapsel === 3) { px(cx - 3, hy - 1, 6, 2, haar); px(cx - 1, hy - 4, 3, 3, haar); px(cx - 4, hy, 1, 2, haar); }
  }

  function scherm(R, id, s, mx, my, tt, t, stil, P) {
    const px = R.px, X = mx + 1, Y = my + 1, w = 8, h = 7;
    if (s === "aandacht") { px(X, Y, w, h, stil || Math.floor(t / 300) % 2 ? V.s4 : mix(V.s4, V.bruin, .45));
      px(X + 3, Y + 1, 2, 3, V.scherm); px(X + 3, Y + 5, 2, 1, V.scherm); return; }
    if (s === "slaapt") { px(X, Y, w, h, V.schermUit); if (stil || Math.floor(t / 1500) % 2) px(X + w - 2, Y + h - 2, 1, 1, V.good); return; }
    if (s === "leeg") { px(X, Y, w, h, mix(V.grijs, V.scherm, .4));
      for (let i = 0; i < w; i += 2) { px(X + i, Y, 1, 1, V.grijs2); px(X + i, Y + h - 1, 1, 1, V.grijs2); }
      for (let j = 2; j < h - 1; j += 2) { px(X, Y + j, 1, 1, V.grijs2); px(X + w - 1, Y + j, 1, 1, V.grijs2); }
      px(X + 2, Y + 3, 4, 1, V.licht); return; }
    px(X, Y, w, h, V.scherm);
    const tik = stil ? 0 : Math.floor(tt / 220);
    if (id === "ingest") { // regels komen binnen, met voortgangsbalk
      for (let i = 0; i < 3; i++) px(X + 1, Y + 1 + i, 2 + ((tik + i * 3) % 5), 1, [V.s1, V.blauwgrijs, V.ijsblauw][i]);
      px(X + 1, Y + 5, 6, 1, V.grijs); px(X + 1, Y + 5, 1 + (stil ? 3 : Math.floor(tt / 300) % 6), 1, V.s1); }
    if (id === "selectie") { // de categorieën A–E, in dezelfde kleuren als het dashboard
      [V.s1, V.s2, V.s3, V.s4, V.s5].forEach((c, i) => px(X + 1, Y + 1 + i, 2 + ((tik + i * 2) % 5), 1, c)); }
    if (id === "verrijking") {
      for (let i = 0; i < 3; i++) px(X + 1, Y + 1 + i * 2, 2 + ((tik + i * 2) % 5), 1, [V.s3, V.good, V.ijsblauw][i]); }
    if (id === "controle") { const m = stil ? 1 : Math.floor(tt / 1400) % 3;
      if (m === 0) { px(X, Y, w, h, V.lijn); px(X, Y + 3, w, 1, V.wit); px(X + 4, Y, 1, h, V.wit); px(X + 1, Y + 1, 2, 1, V.s3); px(X + 5, Y + 5, 2, 1, V.s1); px(X + 2, Y + 4, 1, 1, V.s2); }
      if (m === 1) { px(X, Y, w, h, mix(V.s3, V.zwart, .45)); px(X + 1, Y + 1, 3, 2, mix(V.s2, V.bruin, .3)); px(X + 5, Y + 3, 2, 3, mix(V.licht, V.grijs, .4)); px(X, Y + 4, w, 1, V.grijs2); }
      if (m === 2) { px(X, Y, w, 2, mix(V.s1, V.wit, .5)); px(X, Y + 2, w, 5, mix(V.s2, V.bruin, .4)); px(X + 3, Y + 1, 2, 1, mix(V.s2, V.bruin, .4));
        px(X + 1, Y + 3, 1, 1, V.ijsblauw); px(X + 3, Y + 3, 1, 1, V.ijsblauw); px(X + 6, Y + 3, 1, 1, V.ijsblauw); px(X + 3, Y + 5, 2, 2, V.bruin); } }
  }

  function spullen(R, id, s, cx, y, tt, stil, P) { // wat op het bureau ligt, per rol
    const px = R.px;
    if (id === "ingest") { px(cx - 12, y - 1, 8, 1, V.grijs2); px(cx - 12, y - 3, 1, 2, V.grijs2); px(cx - 5, y - 3, 1, 2, V.grijs2);
      const n = s === "werkt" ? 1 + (stil ? 2 : Math.floor(tt / 700) % 3) : s === "slaapt" ? 3 : s === "aandacht" ? 1 : 0;
      for (let i = 0; i < n; i++) px(cx - 11, y - 2 - i, 6, 1, i % 2 ? P.papier2 : P.papier); }
    if (id === "selectie") { px(cx - 12, y - 4, 7, 4, V.navy); px(cx - 12, y - 4, 7, 1, V.blauwgrijs);
      const op = s === "werkt" ? (stil ? 1 : Math.floor(tt / 450) % 3) : -1;
      if (s !== "leeg") [V.s1, V.s3, V.s5].forEach((c, i) => px(cx - 11 + i * 2, y - 5 - (op === i ? 1 : 0), 1, 1 + (op === i ? 1 : 0), c)); }
    if (id === "verrijking") { px(cx - 13, y - 2, 7, 2, V.licht); px(cx - 12, y - 2, 1, 1, V.grijs); px(cx - 9, y - 2, 1, 1, V.grijs);
      if (s === "werkt" || s === "aandacht") { px(cx - 12, y - 4, 2, 2, V.donker); px(cx - 11, y - 6, 1, 2, V.donker);
        px(cx - 7, y - 2, 1, 1, s === "werkt" ? V.good : (stil || Math.floor(tt / 300) % 2 ? V.s4 : V.grijs)); }
      else { px(cx - 15, y, 2, 2, V.donker); px(cx - 14, y + 2, 1, 4, V.donker); px(cx - 7, y - 2, 1, 1, V.grijs); } }
    if (id === "controle") { const n = s === "aandacht" ? 4 : s === "werkt" ? 2 : s === "slaapt" ? 1 : 0;
      for (let i = 0; i < n; i++) px(cx - 12 + (i % 2), y - 1 - i, 7, 1, i % 2 ? V.blauwgrijs : V.navy);
      if (s === "werkt") { px(cx - 13, y - 4 - n + 1, 3, 3, V.grijs); px(cx - 12, y - 3 - n + 1, 1, 1, V.ijsblauw); px(cx - 10, y - 2 - n + 1, 2, 1, V.bruin); } }
    if (s === "slaapt") { px(cx - 4, y - 3, 3, 3, V.wit); px(cx - 1, y - 2, 1, 1, V.wit); px(cx - 4, y - 3, 3, 1, V.bruin); }
  }

  // w = {id, x, y (bureaurand), toestand, seed, gekozen}
  function tekenMedewerker(R, w, t, P, stil, deeltjes) {
    const px = R.px, cx = w.x, y = w.y, s = w.toestand, tt = stil ? 0 : t + w.seed;
    if (w.gekozen) px(cx - 17, y - 20, 34, 34, P.keuze);
    px(cx - 5, y - 13, 10, 3, P.stoel);                                    // rugleuning
    const schouder = s === "leeg" && (stil || tt % 3600 < 1700);
    persoon(R, cx, y, LOOK[w.id], {
      bob: s === "slaapt" ? 1 : s === "werkt" ? 0 : (!stil && Math.sin(tt / 600) > .7 ? 1 : 0),
      knipper: !stil && s !== "slaapt" && tt % 3800 < 140, slaap: s === "slaapt",
      typt: s === "werkt" ? (stil ? 0 : Math.floor(tt / 130) % 2) : undefined,
      hand: s === "aandacht" && (stil || Math.floor(t / 400) % 2 === 0), zorg: s === "aandacht",
      schouder, vraag: s === "leeg", kijk: s === "leeg" && !stil ? (Math.floor(tt / 1200) % 3) - 1 : 0,
      bril: w.id === "controle",
    });
    px(cx - 13, y, 26, 3, P.blad); px(cx - 12, y + 3, 24, 11, P.front); px(cx - 12, y + 3, 24, 1, P.lade);   // bureau
    px(cx - 10, y + 6, 8, 1, P.lade); px(cx + 2, y + 6, 8, 1, P.lade);
    px(cx - 5, y - 1, 9, 1, V.grijs2);                                     // toetsenbord
    const mx = cx + 5, my = y - 11;                                        // scherm, van opzij
    px(mx + 4, y - 2, 2, 2, V.grijs); px(mx, my, 10, 9, V.donker);
    scherm(R, w.id, s, mx, my, tt, t, stil, P);
    spullen(R, w.id, s, cx, y, tt, stil, P);
    if (s === "slaapt" && stil) { tekenZ(R, cx + 5, y - 23, P.z); tekenZ(R, cx + 9, y - 29, P.z); }
    if (deeltjes && !stil) {
      if (s === "werkt" && Math.random() < .05) deeltjes.push({x: mx + 5, y: my - 1, vx: (Math.random() - .5) * .2, vy: -.25, life: 70,
        c: {ingest: V.s1, selectie: [V.s1, V.s2, V.s3, V.s4, V.s5][Math.floor(Math.random() * 5)], verrijking: V.s3, controle: V.blauwgrijs}[w.id]});
      if (s === "slaapt" && Math.random() < .012) deeltjes.push({x: cx + 3, y: y - 18, vx: .12, vy: -.15, life: 120, z: true});
    }
  }
  function tekenZ(R, x, y, c) { R.px(x, y, 3, 1, c); R.px(x + 1, y + 1, 1, 1, c); R.px(x, y + 2, 3, 1, c); }

  // -------------------------------------------------------------- indeling
  const IDS = ["ingest", "selectie", "verrijking", "controle"];
  const BREED = {W: 384, H: 134, VLOER: 62, LAMBRIS: 44, plek: [[48, 104], [144, 104], [240, 104], [336, 104]], bord: [28, 4],
    decor: [{s: "kast", x: 4}, {s: "tekening", x: 28, y: 15}, {s: "raam", cx: 96, y: 12}, {s: "klok", cx: 144, y: 14},
            {s: "kaart", cx: 192, y: 10}, {s: "raam", cx: 288, y: 12}, {s: "ordners", x: 318, y: 22}, {s: "plant", x: 370}]};
  const SMAL = {W: 200, H: 198, VLOER: 56, LAMBRIS: 40, plek: [[54, 100], [146, 100], [54, 170], [146, 170]], bord: [24, 3],
    decor: [{s: "kast", x: 4}, {s: "tekening", x: 24, y: 15}, {s: "kaart", cx: 100, y: 10}, {s: "raam", cx: 152, y: 12}, {s: "plant", x: 186}]};
  const TEGEL = {W: 44, H: 46, VLOER: 16, LAMBRIS: 9, decor: []};

  // ------------------------------------------------------- toestandsmachine
  const NAMEN = {ingest: ["Ingest", "haalt de BAG op"], selectie: ["Selectie", "scoort de panden"],
    verrijking: ["Verrijking", "vult aan met extra bronnen"], controle: ["Controle", "zet panden klaar voor je controle"]};
  // Toestand en zinnen komen kant-en-klaar uit build_dashboard.py (kantoor_teksten(), VA-31):
  // het script kiest niets en maakt niets op. Zonder tekstblok: geen data.
  const LEEG = {s: "leeg", bel: "onbekend", zin: "onbekend", uitleg: "onbekend"};
  const lees = (data, id) => (data && data.tekst && data.tekst[id]) || LEEG;

  // ---------------------------------------------------------------- kantoor
  const rm = matchMedia("(prefers-reduced-motion: reduce)");
  function start(root, data, opties = {}) {
    const scene = root.querySelector(".pk-scene"), cv = scene.querySelector("canvas"), ov = scene.querySelector(".pk-ov");
    const uitleg = root.querySelector(".pk-uitleg"), R = tekenaar(cv);
    let L = null, breedte = 0, P = palet(root), stil = rm.matches || !!opties.stil, raf = 0, gekozen = null, deeltjes = [];
    const M = {}, el = {}, knoppen = {};
    let terug = null;
    IDS.forEach((id, i) => {
      M[id] = {id, x: 0, y: 0, toestand: "leeg", seed: i * 977 + 311, gekozen: false};
      const bel = document.createElement("div"), naam = document.createElement("div"), hit = document.createElement("button");
      bel.className = "pk-bel"; naam.className = "pk-naam"; hit.className = "pk-hit"; hit.type = "button";
      naam.innerHTML = `<b>${i + 1}</b>${NAMEN[id][0]}`;
      hit.onclick = bel.onclick = () => { terug = hit; kies(gekozen === id ? null : id); };
      ov.append(bel, naam, hit); el[id] = {bel, naam, hit};
    });
    // De werkbalk (VA-64): dezelfde kies(). Het 2D-kantoor heeft geen kantoormanager, dus geen knop voor hem.
    root.querySelectorAll(".pk-balk .pk-knop").forEach(k => {
      const id = k.dataset.wie;
      if (!IDS.includes(id)) { k.hidden = true; return; }
      knoppen[id] = k; k.onclick = () => { terug = k; kies(gekozen === id ? null : id); };
    });
    const bord = document.createElement("div"); bord.className = "pk-bord"; bord.innerHTML = "LEVRAI <span>·</span> VASTGOED"; ov.appendChild(bord);
    const pos = (e, x, y) => { e.style.left = x / L.W * 100 + "%"; e.style.top = y / L.H * 100 + "%"; };

    function zet(dataNieuw) {
      data = dataNieuw;
      IDS.forEach(id => {
        const r = lees(data, id), e = el[id];
        M[id].toestand = r.s; M[id].info = r;
        if (e.bel.textContent !== r.bel) { e.bel.textContent = r.bel; e.bel.style.animation = "none"; e.bel.offsetWidth; e.bel.style.animation = ""; }
        e.bel.className = "pk-bel " + r.s;
        e.hit.setAttribute("aria-label", `${NAMEN[id][0]}: ${r.bel}. Toon uitleg.`);
      });
      if (gekozen) toonUitleg(gekozen);
      if (stil) teken(performance.now());
    }
    function toonUitleg(id) {
      const r = M[id].info, [naam, rol] = NAMEN[id];
      uitleg.querySelector("h3").innerHTML = `${IDS.indexOf(id) + 1} · ${naam} <em>${rol}</em>`;
      const st = uitleg.querySelector(".pk-status"); st.className = "pk-status " + r.s; st.textContent = r.zin;
      uitleg.querySelector(".pk-tekst").textContent = r.uitleg;
    }
    function kies(id) {
      gekozen = id; IDS.forEach(k => { M[k].gekozen = k === id; el[k].hit.setAttribute("aria-expanded", String(k === id));
        if (knoppen[k]) knoppen[k].setAttribute("aria-expanded", String(k === id)); });
      uitleg.hidden = !id; if (id) toonUitleg(id);
      if (stil) teken(performance.now());
    }
    const sluit = () => { const was = gekozen; if (!was) return; kies(null); ((terug && terug.isConnected) ? terug : el[was].hit).focus(); };
    uitleg.querySelector(".pk-sluit").onclick = sluit;
    // VA-31: Escape sluit de uitleg; niet als een pand open is (dat sluit zelf), VA-64.
    document.addEventListener("keydown", e => { if (e.key === "Escape" && !e.defaultPrevented && !document.querySelector("dialog[open]")) sluit(); });

    function indeling() {
      const b = scene.clientWidth; if (!b || b === breedte) return; breedte = b;
      const nieuw = b < 560 ? SMAL : BREED;
      if (nieuw !== L) {
        L = nieuw; R.W = L.W; R.H = L.H; root.classList.toggle("pk-smal", L === SMAL);
        IDS.forEach((id, i) => { const [x, y] = L.plek[i]; M[id].x = x; M[id].y = y; const e = el[id];
          pos(e.bel, x, y - 20); pos(e.naam, x, y + 16); pos(e.hit, x, y - 6);
          e.hit.style.width = 30 / L.W * 100 + "%"; e.hit.style.height = 36 / L.H * 100 + "%"; });
        pos(bord, L.bord[0], L.bord[1]);
        deeltjes = [];
      }
      root.style.setProperty("--pk-bel-max", Math.round(b * (L === SMAL ? .44 : .23)) + "px");
      R.maat(b);
      teken(performance.now());
    }
    function teken(t) {
      if (!L) return;
      R.wis(); tekenKamer(R, L, t, P, stil);
      IDS.forEach(id => tekenMedewerker(R, M[id], t, P, stil, deeltjes));
      for (let i = deeltjes.length - 1; i >= 0; i--) { const q = deeltjes[i];
        q.x += q.vx; q.y += q.vy; q.life--; if (q.life <= 0) { deeltjes.splice(i, 1); continue; }
        if (q.z) tekenZ(R, q.x, q.y, P.z); else R.px(q.x, q.y, 1, 1, q.c); }
    }
    function lus() { raf = 0; if (stil || root.hidden || document.hidden) return; teken(performance.now()); raf = requestAnimationFrame(lus); }
    function speel() { if (!raf && !stil) raf = requestAnimationFrame(lus); }

    new ResizeObserver(indeling).observe(scene);
    const herkleur = () => { P = palet(root); teken(performance.now()); };
    new MutationObserver(herkleur).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", herkleur);
    rm.addEventListener("change", () => api.stil(rm.matches));
    document.addEventListener("visibilitychange", speel);

    const api = {
      zet, kies,
      stil(aan) { stil = !!aan; root.classList.toggle("pk-stil", stil); deeltjes = []; teken(performance.now()); speel(); },
    };
    root.classList.toggle("pk-stil", stil);
    zet(data); indeling(); speel();
    return api;
  }

  // Eén stilstaand beeld van één medewerker (de prefers-reduced-motion-versie), voor het toestandsvel.
  function tegel(cv, id, s, el) {
    const R = tekenaar(cv); R.W = TEGEL.W; R.H = TEGEL.H; R.maat(cv.clientWidth || 120);
    const P = palet(el); R.wis(); tekenKamer(R, TEGEL, 0, P, true);
    tekenMedewerker(R, {id, x: 20, y: 31, toestand: s, seed: 0}, 0, P, true, null);
  }

  return {start, tegel, lees, IDS, NAMEN, palet};
})();

/* ============================== BEGIN KANTOOR3D ==============================
   3D-kantoor (three.js r128): een voxel-diorama naar het voorbeeld van Hermes' hq3d.js.
   Achter: vier werkkamers, één per stap. Midden: de gang. Voor: kantine, maquettezaal, rustkamer.
   Toestand en zinnen komen uit PAYLOAD.kantoor.tekst (kantoor_teksten() in Python), net als in 2D:
     werkt = loopt naar het bureau en typt · aandacht = staat op en zwaait, "!" in de ballon
     slaapt = naar de kantine (en 's nachts naar de rustkamer) · leeg = staat bij het bureau en haalt de schouders op
   De kantoormanager is geen stap: die loopt naar wie aandacht vraagt.
============================================================================== */
const TEKST3D = {
  kamers: {ingest: "BAG-archief", selectie: "Taxatiekamer", verrijking: "Datalab", controle: "Kaartenkamer",
           kantine: "Kantine · koffiehoek", maquette: "Maquettezaal", rust: "Rustkamer"},
  // Wat de kantoormanager zegt (afhankelijk van de cijfers) komt uit PAYLOAD.kantoor.tekst.chef (VA-60).
  chef: {naam: "Kantoormanager", rol: "geen stap van de pandenselectie",
    uitleg: "De kantoormanager is geen stap van de pandenselectie en heeft geen eigen cijfers. Vraagt een medewerker je aandacht, dan loopt de kantoormanager daarheen. Anders loopt de kantoormanager een ronde door het kantoor."},
  // VA-63: de eerste twee zinnen staan nu als uitleg onder de titel van het kantoor.
  voet: "De kantoormanager loopt naar wie je aandacht vraagt. Klik op iemand in het kantoor of op een naam hierboven voor uitleg.",
  hit: (naam, bel) => `${naam}: ${String(bel).replace(/[.]$/, "")}. Toon uitleg.`,
  geenWebGL: "WebGL staat uit in je browser. Je ziet het kantoor in 2D.",
  geenThree: "Je browser kon de 3D-weergave niet laden. Je ziet het kantoor in 2D.",
  bord: {score: "CATEGORIE A–E", label: "ENERGIELABEL", bronnen: "BRONNEN", koop: "TE KOOP", verkocht: "VERKOCHT", krat: "PDOK", kaart: "NEDERLAND"},
};

// Pas gebouwd als three.js geladen is (VA-60): het script laadt los van de rest van de pagina.
let PK3D = null;
const bouwPK3D = () => (() => {
  const T = window.THREE;
  // ---------------------------------------------------------------- kleuren
  const rgb = c => { c = String(c).trim();
    if (c[0] === "#") { if (c.length === 4) c = "#" + [...c.slice(1)].map(x => x + x).join("");
      return [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)); }
    const m = c.match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number) : [0, 0, 0]; };
  const hex = a => "#" + a.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const A = rgb(a), B = rgb(b); return hex(A.map((v, i) => v + (B[i] - v) * t)); };
  // Vaste waarden uit index.html (dezelfde als V in het 2D-kantoor).
  const V = {
    zwart: "#0b0b0b", wit: "#ffffff", grijs: "#52514e", grijs2: "#898781", licht: "#c3c2b7", lijn: "#e1e0d9",
    navy: "#12233b", blauwgrijs: "#9fb3cc", ijsblauw: "#c6d3e4", bruin: "#3a2a00", donker: "#2c2c2a", donker2: "#383835",
    s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", s4: "#eda100", s5: "#e87ba4", good: "#0ca30c", crit: "#d03b3b",
  };
  V.scherm = mix(V.navy, V.zwart, .35); V.schermUit = mix(V.navy, V.zwart, .6);
  V.hout = mix(mix(V.s4, V.bruin, .45), V.lijn, .2); V.hout2 = mix(V.hout, V.zwart, .25);
  V.baksteen = mix(V.s2, V.bruin, .45); V.water = mix(V.s1, V.navy, .3); V.groen = mix(V.s3, V.zwart, .3);
  // [haar, shirt, huid, kapsel, accent, broek]: dezelfde mensen als in 2D, plus de kantoormanager.
  const LOOK = {
    ingest:     [V.bruin,                V.navy,       mix(V.s2, V.wit, .66),                 0, V.wit,  V.donker2],
    selectie:   [mix(V.s4, V.bruin, .3), V.blauwgrijs, mix(mix(V.s2, V.s4, .5), V.wit, .42), 1, null,   V.navy],
    verrijking: [V.zwart,                V.grijs,      mix(V.s2, V.bruin, .55),               2, null,   V.donker],
    controle:   [V.grijs2,               V.ijsblauw,   mix(V.s2, V.wit, .56),                 3, V.navy, V.grijs],
    chef:       [V.licht,                V.navy,       mix(V.s2, V.wit, .6),                  4, V.s2,   V.navy],
  };
  const IDS = PK.IDS, NAMEN = PK.NAMEN;

  // ------------------------------------------------------------- dagdelen
  const deelVan = u => (u < 7 || u >= 21) ? "nacht" : (u < 8.5 || u >= 18) ? "schemer" : "dag";
  const bedtijdVan = u => u >= 22 || u < 7;
  const LUCHT = {
    dag:     [mix(V.s1, V.wit, .38), mix(V.s1, V.wit, .62), mix(V.s1, V.wit, .82)],
    schemer: [mix(V.navy, V.s1, .3), mix(V.s5, V.wit, .25), mix(V.s4, V.wit, .4)],
    nacht:   [mix(V.navy, V.zwart, .5), V.navy, mix(V.navy, V.s1, .3)],
  };
  // Vaste toeval, zodat de skyline bij elk dagdeel dezelfde straat is.
  const zaad = s => () => { s |= 0; s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };

  function start(root, data, opties = {}) {
    // --- renderer eerst: als WebGL faalt, gooit dit vóór we de DOM aanraken
    const renderer = new T.WebGLRenderer({antialias: true, alpha: true});
    const sceneEl = root.querySelector(".pk-scene"), ov = sceneEl.querySelector(".pk-ov"), uitleg = root.querySelector(".pk-uitleg");
    const oud = sceneEl.querySelector("canvas"); if (oud) oud.remove();
    sceneEl.classList.add("pk-3d");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.domElement.setAttribute("aria-hidden", "true");
    sceneEl.insertBefore(renderer.domElement, ov);
    root.querySelector(".pk-voet").textContent = TEKST3D.voet;

    const rm = matchMedia("(prefers-reduced-motion: reduce)");
    let stil = rm.matches || !!opties.stil, uurVast = opties.uur == null ? null : +opties.uur;
    const uur = () => { if (uurVast != null) return uurVast; const d = new Date(); return d.getHours() + d.getMinutes() / 60; };
    let P = PK.palet(root);

    const scene = new T.Scene();
    const cam = new T.OrthographicCamera(-1, 1, 1, -1, 0.1, 300);
    const CAM_BASE = new T.Vector3(3, 20, 20), KIJK = new T.Vector3(0, 2, -4.2);
    const hemi = new T.HemisphereLight(0xffffff, mix(V.bruin, V.wit, .4), 0.8); scene.add(hemi);
    const zon = new T.DirectionalLight(0xffffff, 0.5);
    zon.position.set(10, 24, 14); zon.castShadow = true; zon.shadow.mapSize.set(1 << 11, 1 << 11);  // 2^11 px
    Object.assign(zon.shadow.camera, {left: -17, right: 17, top: 13, bottom: -13, near: 1, far: 70});
    scene.add(zon);

    const mats = {};
    const mat = c => mats[c] || (mats[c] = new T.MeshLambertMaterial({color: c}));
    const gloei = c => new T.MeshBasicMaterial({color: c});
    const thema = [];               // [materiaal, P => kleur]: volgt licht/donker
    const tm = f => { const m = new T.MeshLambertMaterial({color: f(P)}); thema.push([m, f]); return m; };
    function cube(w, h, d, kleur, x = 0, y = 0, z = 0, ouder = scene, schaduw = true) {
      const m = new T.Mesh(new T.BoxGeometry(w, h, d), typeof kleur === "object" ? kleur : mat(kleur));
      m.position.set(x, y, z); m.castShadow = schaduw; m.receiveShadow = true; ouder.add(m); return m;
    }
    function cyl(r, h, kleur, x, y, z, ouder = scene, seg = 16) {
      const m = new T.Mesh(new T.CylinderGeometry(r, r, h, seg), typeof kleur === "object" ? kleur : mat(kleur));
      m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; ouder.add(m); return m;
    }
    function doek(bw, bh, teken) { // canvas -> textuur
      const cv = document.createElement("canvas"); cv.width = bw; cv.height = bh; const g = cv.getContext("2d");
      const tex = new T.CanvasTexture(cv); tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
      const opnieuw = (...a) => { g.clearRect(0, 0, bw, bh); teken(g, bw, bh, ...a); tex.needsUpdate = true; };
      opnieuw(); return {tex, opnieuw, g, cv};
    }
    function paneel(w, h, tex, x, y, z, basic = false, ouder = scene, ry = 0) {
      const m = new T.Mesh(new T.PlaneGeometry(w, h), basic ? new T.MeshBasicMaterial({map: tex}) : new T.MeshLambertMaterial({map: tex}));
      m.position.set(x, y, z); m.rotation.y = ry; m.receiveShadow = !basic; ouder.add(m); return m;
    }
    const tekst = (g, s, x, y, px, kleur, uitlijn = "center", gewicht = 800) => {
      g.font = `${gewicht} ${px}px system-ui,-apple-system,"Segoe UI",sans-serif`; g.fillStyle = kleur;
      g.textAlign = uitlijn; g.textBaseline = "middle"; g.fillText(s, x, y); };
    const rnd = (a, b) => a + Math.random() * (b - a);

    // -------------------------------------------------------------- indeling
    const BACK = -6.4, WORK_END = -0.9, AISLE = 0, ROW2 = 0.9, FRONT = 7.4, TOTAL = 24;
    const KAMERS = [
      {id: "ingest", w: 6, accent: V.s1, bureau: 0.4}, {id: "selectie", w: 6, accent: V.s4, bureau: 0.4},
      {id: "verrijking", w: 6, accent: V.s3, bureau: -0.2}, {id: "controle", w: 6, accent: V.s2, bureau: -0.5},
    ];
    const VOOR = [{id: "kantine", w: 9.5, accent: V.s5}, {id: "maquette", w: 8, accent: V.s4}, {id: "rust", w: 6.5, accent: V.s1}];
    let x0 = -TOTAL / 2;
    KAMERS.forEach(r => { r.x0 = x0; r.x1 = x0 + r.w; r.cx = x0 + r.w / 2; r.z0 = BACK; r.z1 = WORK_END; x0 += r.w; });
    x0 = -TOTAL / 2;
    VOOR.forEach(r => { r.x0 = x0; r.x1 = x0 + r.w; r.cx = x0 + r.w / 2; r.z0 = ROW2; r.z1 = FRONT; x0 += r.w; });
    const ALLE = [...KAMERS, ...VOOR], K = Object.fromEntries(ALLE.map(r => [r.id, r]));

    // vloer, kamervloeren, gang
    cube(TOTAL + 0.6, 0.4, FRONT - BACK + 0.6, tm(P => mix(P.plank, V.zwart, P.donker ? .2 : .12)), 0, -0.2, (FRONT + BACK) / 2);
    ALLE.forEach(r => cube(r.w - 0.06, 0.06, r.z1 - r.z0, tm(P => mix(P.vloer, r.accent, P.donker ? .06 : .1)), r.cx, 0.03, (r.z0 + r.z1) / 2, scene, false));
    cube(TOTAL, 0.05, ROW2 - WORK_END, tm(P => mix(P.vloer, P.plank, .55)), 0, 0.025, AISLE, scene, false);
    const loper = tm(P => P.lambris);
    cube(TOTAL - 1, 0.02, 0.7, loper, 0, 0.06, AISLE, scene, false);              // navy loper door de gang

    // wanden: achterwand met navy lambrisering (Levrai), linkerwand, lage tussenwanden
    const wand = tm(P => P.wand), lambris = tm(P => P.lambris), lijst = tm(P => P.lambrisLijn);
    cube(TOTAL + 0.6, 3.2, 0.3, wand, 0, 1.6, BACK - 0.15);
    cube(TOTAL + 0.6, 1.0, 0.05, lambris, 0, 0.5, BACK + 0.02, scene, false);
    cube(TOTAL + 0.6, 0.06, 0.08, lijst, 0, 1.02, BACK + 0.03, scene, false);
    cube(0.3, 3.2, WORK_END - BACK + 0.3, wand, -TOTAL / 2 - 0.15, 1.6, (BACK + WORK_END) / 2);
    cube(0.05, 1.0, WORK_END - BACK, lambris, -TOTAL / 2 + 0.02, 0.5, (BACK + WORK_END) / 2, scene, false);
    cube(0.3, 1.2, FRONT - ROW2, wand, -TOTAL / 2 - 0.15, 0.6, (ROW2 + FRONT) / 2);
    KAMERS.forEach((r, i) => { if (i) cube(0.12, 1.3, 3.0, wand, r.x0, 0.65, BACK + 1.5); });
    VOOR.forEach((r, i) => { if (i) cube(0.14, 1.6, FRONT - ROW2 - 1.6, wand, r.x0, 0.8, (ROW2 + 1.6 + FRONT) / 2); });

    const ramen = [];
    function raam(wx) {
      cube(1.9, 1.3, 0.08, V.hout2, wx, 2.15, BACK + 0.02, scene, false);
      const glas = gloei(V.ijsblauw); cube(1.7, 1.1, 0.1, glas, wx, 2.15, BACK + 0.03, scene, false);
      cube(0.06, 1.1, 0.12, V.hout2, wx, 2.15, BACK + 0.05, scene, false); cube(1.7, 0.05, 0.12, V.hout2, wx, 2.35, BACK + 0.05, scene, false);
      cube(2.0, 0.06, 0.2, V.hout2, wx, 1.48, BACK + 0.1, scene, false); ramen.push(glas);
    }
    const planten = [];
    function plant(px, pz) {
      cube(0.4, 0.4, 0.4, mix(V.s2, V.bruin, .35), px, 0.2, pz);
      const gr = new T.Group(); gr.position.set(px, 0.4, pz); scene.add(gr); planten.push(gr);
      cube(0.18, 0.6, 0.18, V.groen, 0, 0.3, 0, gr); cube(0.45, 0.3, 0.45, V.s3, 0, 0.6, 0, gr); cube(0.28, 0.25, 0.28, V.s3, 0, 0.85, 0, gr);
    }
    const lijsten = (w, h, x, y) => cube(w + 0.14, h + 0.14, 0.06, V.donker2, x, y, BACK + 0.03, scene, false);

    // ------------------------------------------------------ 1 · BAG-archief
    const rI = K.ingest, leds = [];
    [BACK + 0.55, BACK + 1.5].forEach((rz, k) => {                               // serverkasten tegen de linkerwand
      const rx = rI.x0 + 0.5; cube(0.8, 2.2, 0.85, V.donker, rx, 1.1, rz); cube(0.04, 2.0, 0.7, V.donker2, rx + 0.41, 1.1, rz, scene, false);
      for (let j = 0; j < 7; j++) { cube(0.03, 0.04, 0.5, V.grijs, rx + 0.43, 0.35 + j * 0.27, rz, scene, false);
        for (let i = 0; i < 3; i++) { const m = gloei(V.s1); cube(0.03, 0.05, 0.05, m, rx + 0.44, 0.42 + j * 0.27, rz - 0.22 + i * 0.09, scene, false); leds.push({m, i: j * 3 + i + k * 30}); } }
    });
    [rI.x1 - 1.25, rI.x1 - 0.55].forEach(cx => {                                 // archiefkasten
      cube(0.65, 1.35, 0.7, V.licht, cx, 0.68, BACK + 0.45);
      for (let j = 0; j < 3; j++) { cube(0.58, 0.02, 0.02, V.grijs2, cx, 0.36 + j * 0.42, BACK + 0.81, scene, false);
        cube(0.18, 0.05, 0.04, V.grijs, cx, 0.55 + j * 0.42, BACK + 0.82, scene, false); cube(0.2, 0.1, 0.01, V.wit, cx, 0.43 + j * 0.42 + 0.22, BACK + 0.81, scene, false); }
    });
    cube(0.5, 0.06, 0.38, V.blauwgrijs, rI.x1 - 1.25, 1.39, BACK + 0.45); cube(0.46, 0.06, 0.36, V.wit, rI.x1 - 1.25, 1.45, BACK + 0.45);
    const krat = new T.Group(); krat.position.set(rI.x1 - 0.95, 0, -2.9); krat.rotation.y = -0.25; scene.add(krat);
    cube(1.0, 0.62, 0.72, V.hout, 0, 0.31, 0, krat);
    [-0.2, 0.05, 0.3].forEach(y => cube(1.02, 0.05, 0.74, V.hout2, 0, 0.31 + y, 0, krat, false));
    const kratLabel = doek(256, 120, g => { g.fillStyle = V.hout; g.fillRect(0, 0, 256, 120);
      tekst(g, TEKST3D.bord.krat, 128, 52, 62, V.navy); tekst(g, "BAG", 128, 100, 26, V.navy, "center", 700); });
    paneel(0.8, 0.38, kratLabel.tex, 0, 0.36, 0.365, false, krat);
    const kratPapier = new T.Group(); krat.add(kratPapier);
    [[-0.25, 0.04, V.wit], [0, -0.08, V.lijn], [0.22, 0.1, V.wit], [0.05, 0.16, V.ijsblauw]].forEach(([x, z, c], i) => {
      const p = cube(0.32, 0.36, 0.03, c, x, 0.7, z, kratPapier, false); p.rotation.z = (i - 1.5) * 0.12; });
    raam(rI.cx - 0.6);
    plant(rI.x0 + 0.45, -2.0);

    // ------------------------------------------------------ 2 · Taxatiekamer
    const rS = K.selectie;
    lijsten(2.3, 1.45, rS.x0 + 1.55, 2.1);
    const bord = doek(512, 320, (g, w, h, cat) => {
      g.fillStyle = V.navy; g.fillRect(0, 0, w, h);
      tekst(g, TEKST3D.bord.score, w / 2, 34, 30, V.blauwgrijs);
      const kl = [V.s1, V.s2, V.s3, V.s4, V.s5], letters = ["A", "B", "C", "D", "E"];
      const max = cat ? Math.max(1, ...letters.map(l => +cat[l] || 0)) : 0;
      g.fillStyle = mix(V.navy, V.blauwgrijs, .35); g.fillRect(40, 266, w - 80, 3);
      letters.forEach((l, i) => { const x = 58 + i * 84;
        if (cat) { const hh = Math.round(190 * (+cat[l] || 0) / max); g.fillStyle = kl[i]; g.fillRect(x, 266 - hh, 60, hh); }
        tekst(g, l, x + 30, 292, 30, V.wit); });
    });
    paneel(2.3, 1.45, bord.tex, rS.x0 + 1.55, 2.1, BACK + 0.07);
    cube(1.1, 0.8, 0.62, tm(P => P.kast2 || P.kast), rS.x1 - 0.7, 0.4, BACK + 0.5);
    [[-0.32, 5, [V.navy, V.blauwgrijs]], [0.02, 7, [V.wit, V.lijn]], [0.34, 4, [V.ijsblauw, V.navy]]].forEach(([dx, n, kl]) => {
      for (let i = 0; i < n; i++) cube(0.3, 0.07, 0.42, kl[i % 2], rS.x1 - 0.7 + dx + (i % 2 ? 0.015 : -0.01), 0.84 + i * 0.075, BACK + 0.5, scene, i === n - 1); });
    for (let i = 0; i < 6; i++) cube(0.42, 0.08, 0.32, [V.navy, V.wit, V.blauwgrijs][i % 3], rS.x0 + 0.65 + (i % 2) * 0.03, 0.04 + i * 0.085, -3.6, scene, i === 5);
    raam(rS.x1 - 2.1);
    plant(rS.x0 + 0.45, -1.9);

    // --------------------------------------------------------- 3 · Datalab
    const rV = K.verrijking;
    lijsten(1.05, 1.45, rV.x0 + 0.95, 2.1);
    const label = doek(256, 360, g => {
      g.fillStyle = V.wit; g.fillRect(0, 0, 256, 360);
      tekst(g, TEKST3D.bord.label, 128, 28, 24, V.navy);
      const kl = [V.good, V.s3, mix(V.s3, V.s4, .5), V.s4, mix(V.s4, V.s2, .5), V.s2, V.crit];
      "ABCDEFG".split("").forEach((l, i) => { const y = 58 + i * 42, w = 90 + i * 18;
        g.fillStyle = kl[i]; g.beginPath(); g.moveTo(20, y); g.lineTo(20 + w, y); g.lineTo(38 + w, y + 16); g.lineTo(20 + w, y + 32); g.lineTo(20, y + 32); g.fill();
        tekst(g, l, 40, y + 17, 24, V.wit); });
    });
    paneel(1.05, 1.45, label.tex, rV.x0 + 0.95, 2.1, BACK + 0.07);
    const stX = rV.x1 - 1.25;
    cube(1.4, 1.0, 0.08, V.licht, stX, 1.6, BACK + 0.06);
    const bronLabel = doek(256, 48, g => { g.fillStyle = V.navy; g.fillRect(0, 0, 256, 48); tekst(g, TEKST3D.bord.bronnen, 128, 25, 26, V.wit); });
    paneel(1.2, 0.22, bronLabel.tex, stX, 1.98, BACK + 0.11);
    for (let j = 0; j < 2; j++) for (let i = 0; i < 4; i++) cube(0.16, 0.16, 0.04, V.donker, stX - 0.45 + i * 0.3, 1.66 - j * 0.34, BACK + 0.11, scene, false);
    const bronLed = gloei(V.grijs2); cube(0.08, 0.08, 0.04, bronLed, stX + 0.6, 1.98, BACK + 0.12, scene, false);
    const kabelIn = new T.Group(), kabelUit = new T.Group(); scene.add(kabelIn, kabelUit);
    const kabel = V.s3;
    cube(0.14, 0.14, 0.12, V.zwart, stX - 0.45, 1.66, BACK + 0.17, kabelIn); cube(0.05, 1.62, 0.05, kabel, stX - 0.45, 0.85, BACK + 0.2, kabelIn, false);
    cube(1.6, 0.04, 0.05, kabel, stX - 1.25, 0.06, BACK + 0.2, kabelIn, false);
    cube(1.25, 0.04, 0.05, kabel, stX - 0.9, 0.06, BACK + 0.6, kabelUit, false); cube(0.05, 0.04, 0.45, kabel, stX - 0.28, 0.06, BACK + 0.4, kabelUit, false);
    cube(0.16, 0.12, 0.14, V.zwart, stX - 0.28, 0.08, BACK + 0.12, kabelUit);
    plant(rV.x0 + 0.45, -1.9);
    cube(0.55, 0.9, 0.55, V.licht, rV.x1 - 0.5, 0.45, -2.3); cube(0.45, 0.06, 0.45, V.wit, rV.x1 - 0.5, 0.93, -2.3);
    const kolf = new T.MeshLambertMaterial({color: V.s3, transparent: true, opacity: .75});
    cyl(0.09, 0.22, kolf, rV.x1 - 0.6, 1.07, -2.3, scene, 10); cyl(0.07, 0.3, V.ijsblauw, rV.x1 - 0.38, 1.11, -2.22, scene, 10);

    // ------------------------------------------------------- 4 · Kaartenkamer
    const rC = K.controle;
    lijsten(1.75, 2.15, rC.x0 + 1.25, 1.95);
    const kaart = doek(320, 400, g => {
      g.fillStyle = V.lijn; g.fillRect(0, 0, 320, 400); g.fillStyle = mix(V.s1, V.wit, .62); g.fillRect(10, 10, 300, 380);
      const land = mix(V.s3, V.wit, .5), meer = mix(mix(V.s1, V.wit, .62), land, .25), c = 17;
      const KAART = ["...#.##.##.#....", "................", "....#..########.", "....#~~#########", "...##~~~########", "...#~~~~~#######",
        "...##~~~~#######", "...###~~########", "...#############", "..##############", "..#############.", "..############..",
        ".#.############.", "#.#############.", ".##############.", "#..###########..", "...........###..", "...........##...", "...........###..", "............#..."];
      KAART.forEach((r, j) => [...r].forEach((ch, i) => { if (ch === ".") return; g.fillStyle = ch === "#" ? land : meer; g.fillRect(24 + i * c, 26 + j * c, c, c); }));
      tekst(g, TEKST3D.bord.kaart, 160, 382, 18, V.navy);
      g.fillStyle = V.s2; [[14, 14], [296, 14]].forEach(([x, y]) => g.fillRect(x, y, 10, 10));
    });
    paneel(1.75, 2.15, kaart.tex, rC.x0 + 1.25, 1.95, BACK + 0.07);
    const sv = doek(320, 200, g => {           // Street View: een gracht met gevels
      g.fillStyle = mix(V.s1, V.wit, .55); g.fillRect(0, 0, 320, 200);
      const kl = [V.baksteen, V.navy, mix(V.lijn, V.s4, .2), mix(V.s3, V.zwart, .4), V.baksteen];
      kl.forEach((c, i) => { const x = i * 64, h = 110 + (i * 37) % 40;
        g.fillStyle = c; g.fillRect(x + 2, 160 - h, 60, h);
        g.beginPath(); g.moveTo(x + 2, 160 - h); g.lineTo(x + 32, 160 - h - 26); g.lineTo(x + 62, 160 - h); g.fill();
        g.fillStyle = V.wit; for (let f = 0; f < 3; f++) for (let k = 0; k < 2; k++) g.fillRect(x + 12 + k * 26, 160 - h + 14 + f * 32, 12, 18); });
      g.fillStyle = V.grijs; g.fillRect(0, 160, 320, 40); g.fillStyle = V.wit; for (let x = 10; x < 320; x += 50) g.fillRect(x, 178, 26, 4);
      g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(290, 30, 16, 0, Math.PI * 2); g.fill();
      g.fillStyle = V.navy; g.beginPath(); g.moveTo(290, 20); g.lineTo(297, 36); g.lineTo(283, 36); g.fill();
    });
    cube(1.6, 1.05, 0.08, V.zwart, rC.x1 - 1.0, 2.2, BACK + 0.06); paneel(1.48, 0.92, sv.tex, rC.x1 - 1.0, 2.2, BACK + 0.11, true);
    const kijker = new T.Group(); kijker.position.set(rC.x1 - 0.7, 0, -3.3); scene.add(kijker);  // verrekijker op statief
    [[0, 0.25], [2.1, 0.25], [4.2, 0.25]].forEach(([a]) => { const poot = cube(0.04, 1.15, 0.04, V.donker, Math.sin(a) * 0.2, 0.55, Math.cos(a) * 0.2, kijker); poot.rotation.set(Math.cos(a) * 0.3, 0, -Math.sin(a) * 0.3); });
    cube(0.12, 0.1, 0.12, V.donker, 0, 1.15, 0, kijker);
    const kop = new T.Group(); kop.position.set(0, 1.28, 0); kop.rotation.set(0.25, 0.5, 0); kijker.add(kop);
    [-0.08, 0.08].forEach(x => { cube(0.12, 0.12, 0.38, V.zwart, x, 0, 0, kop); cube(0.1, 0.1, 0.04, V.blauwgrijs, x, 0, -0.2, kop, false); });
    cube(0.06, 0.06, 0.12, V.grijs, 0, 0, 0, kop);
    const dossiers = [];
    plant(rC.x0 + 0.45, -1.9);

    // ---------------------------------------------------------- bureaus
    const W = {};
    function persoon(id) {
      const [haar, shirt, huid, kapsel, accent, broek] = LOOK[id];
      const g = new T.Group(), body = new T.Group(); g.add(body);
      const lid = (w, h, d, c, x, y) => { const p = new T.Group(); p.position.set(x, y, 0); cube(w, h, d, c, 0, -h / 2, 0, p); body.add(p); return p; };
      const legL = lid(0.22, 0.6, 0.24, broek, -0.14, 0.6), legR = lid(0.22, 0.6, 0.24, broek, 0.14, 0.6);
      cube(0.24, 0.08, 0.3, V.donker, 0, -0.56, 0.03, legL); cube(0.24, 0.08, 0.3, V.donker, 0, -0.56, 0.03, legR);
      cube(0.58, 0.62, 0.32, shirt, 0, 0.9, 0, body);
      if (kapsel === 0 && accent) cube(0.16, 0.3, 0.02, accent, 0, 1.06, 0.17, body);          // overhemd onder het colbert
      if ((kapsel === 3 || kapsel === 4) && accent) cube(0.09, 0.4, 0.02, accent, 0, 0.98, 0.17, body); // das
      const armL = lid(0.17, 0.56, 0.18, shirt, -0.38, 1.17), armR = lid(0.17, 0.56, 0.18, shirt, 0.38, 1.17);
      cube(0.15, 0.13, 0.15, huid, 0, -0.62, 0, armL); cube(0.15, 0.13, 0.15, huid, 0, -0.62, 0, armR);
      const head = new T.Group(); head.position.set(0, 1.21, 0); body.add(head);
      cube(0.48, 0.46, 0.44, huid, 0, 0.23, 0, head);
      const eyes = [cube(0.07, 0.09, 0.02, V.zwart, -0.11, 0.25, 0.225, head, false), cube(0.07, 0.09, 0.02, V.zwart, 0.11, 0.25, 0.225, head, false)];
      if (kapsel === 0) { cube(0.52, 0.14, 0.48, haar, 0, 0.5, -0.01, head); cube(0.52, 0.3, 0.1, haar, 0, 0.33, -0.21, head); }
      if (kapsel === 1) { cube(0.54, 0.14, 0.5, haar, 0, 0.5, 0, head); cube(0.54, 0.6, 0.12, haar, 0, 0.18, -0.22, head); cube(0.06, 0.4, 0.44, haar, -0.26, 0.28, 0, head); cube(0.06, 0.4, 0.44, haar, 0.26, 0.28, 0, head); }
      if (kapsel === 2) cube(0.5, 0.07, 0.46, haar, 0, 0.47, 0, head);
      if (kapsel === 3) { cube(0.52, 0.12, 0.48, haar, 0, 0.5, 0, head); cube(0.22, 0.22, 0.22, haar, 0, 0.62, -0.12, head); cube(0.4, 0.04, 0.02, V.grijs, 0, 0.3, 0.235, head, false); }
      if (kapsel === 4) { cube(0.52, 0.12, 0.48, haar, 0, 0.5, 0, head); cube(0.06, 0.26, 0.46, haar, -0.26, 0.36, 0, head); cube(0.06, 0.26, 0.46, haar, 0.26, 0.36, 0, head);
        cube(0.3, 0.4, 0.04, V.hout, 0, -0.5, 0.14, armL); cube(0.24, 0.3, 0.01, V.wit, 0, -0.48, 0.165, armL, false); }   // klembord
      const mug = cube(0.14, 0.16, 0.14, V.wit, 0, -0.68, 0.1, armR); mug.visible = false;
      scene.add(g);
      return {g, body, legL, legR, armL, armR, head, eyes, mug};
    }
    const schermKl = {ingest: [V.s1, V.blauwgrijs, V.ijsblauw], selectie: [V.s1, V.s2, V.s3, V.s4, V.s5],
      verrijking: [V.s3, V.good, V.ijsblauw], controle: [V.lijn, V.s3, V.s1]};
    KAMERS.forEach((r, i) => {
      const id = r.id, dx = r.cx + r.bureau, dz = BACK + 1.0;
      cube(1.7, 0.08, 0.9, tm(P => P.blad), dx, 0.82, dz); cube(0.08, 0.8, 0.8, tm(P => P.front), dx - 0.78, 0.4, dz); cube(0.08, 0.8, 0.8, tm(P => P.front), dx + 0.78, 0.4, dz);
      cube(0.08, 0.3, 0.08, V.grijs, dx, 1.0, dz - 0.15); cube(0.9, 0.6, 0.08, V.donker, dx, 1.42, dz - 0.15);
      const screen = gloei(V.scherm); cube(0.8, 0.5, 0.02, screen, dx, 1.42, dz - 0.1, scene, false);
      cube(0.6, 0.03, 0.22, V.grijs2, dx, 0.87, dz + 0.2, scene, false);
      const seat = {x: dx, z: dz + 0.95};
      cube(0.6, 0.08, 0.6, V.donker2, seat.x, 0.48, seat.z); cube(0.08, 0.45, 0.08, V.donker, seat.x, 0.24, seat.z); cube(0.6, 0.6, 0.08, V.donker2, seat.x, 0.8, seat.z + 0.3);
      const p = persoon(id); p.g.position.set(seat.x + (i % 2 ? 1.2 : -1.2), 0.06, AISLE);
      W[id] = {id, nr: i + 1, kamer: r, seat, screen, p, path: [], mode: "stand", s: "leeg", face: 0, wait: 0, seed: i * 2.7 + 1, at: null, goal: null, spot: null};
      if (id === "controle") for (let k = 0; k < 4; k++) dossiers.push(cube(0.42, 0.07, 0.3, k % 2 ? V.blauwgrijs : V.navy, dx - 0.55 + (k % 2) * 0.03, 0.9 + k * 0.075, dz + 0.1, scene, false));
      if (id === "ingest") cube(0.3, 0.2, 0.22, V.s1, dx + 0.6, 0.96, dz + 0.1);   // externe schijf
      if (id === "selectie") { cube(0.34, 0.05, 0.26, V.navy, dx - 0.55, 0.89, dz + 0.1); cube(0.08, 0.14, 0.08, V.s4, dx - 0.6, 0.98, dz + 0.1); }
    });

    // ------------------------------------------------- kantine · koffiehoek
    const rK = K.kantine, PLEK = {};
    cube(0.7, 0.9, 2.3, V.hout, rK.x0 + 0.4, 0.45, 3.1); cube(0.74, 0.05, 2.34, V.lijn, rK.x0 + 0.4, 0.92, 3.1);
    cube(0.45, 0.62, 0.45, V.donker, rK.x0 + 0.4, 1.26, 2.4); cube(0.12, 0.12, 0.12, V.s2, rK.x0 + 0.64, 1.38, 2.4, scene, false);
    cube(0.1, 0.12, 0.2, V.grijs, rK.x0 + 0.66, 1.08, 2.4, scene, false);
    [2.95, 3.1].forEach(z => cube(0.14, 0.16, 0.14, V.wit, rK.x0 + 0.45, 1.03, z));
    const blik = cyl(0.2, 0.2, V.navy, rK.x0 + 0.4, 1.05, 3.75); cyl(0.21, 0.05, V.s4, rK.x0 + 0.4, 1.17, 3.75);   // stroopwafelblik
    const wafel = cyl(0.17, 0.035, mix(V.s4, V.bruin, .35), rK.x0 + 0.55, 1.25, 3.62); wafel.rotation.z = 0.9;
    PLEK.koffie = {kind: "koffie", x: rK.x0 + 1.25, z: 2.55, face: -Math.PI / 2};
    PLEK.koek = {kind: "koek", x: rK.x0 + 1.25, z: 3.75, face: -Math.PI / 2};
    const ptx = rK.x0 + 4.0, ptz = 4.7;                                              // pingpongtafel
    cube(2.4, 0.08, 1.3, mix(V.s1, V.navy, .5), ptx, 0.76, ptz); cube(2.4, 0.01, 0.03, V.wit, ptx, 0.81, ptz, scene, false);
    cube(0.04, 0.18, 1.4, V.lijn, ptx, 0.88, ptz, scene, false);
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(([i, k]) => cube(0.08, 0.72, 0.08, V.donker, ptx + i * 1.05, 0.36, ptz + k * 0.55));
    const bal = cube(0.1, 0.1, 0.1, V.s4, ptx, 1.0, ptz, scene, false); bal.visible = false;
    PLEK.pingL = {kind: "ping", x: ptx - 1.65, z: ptz, face: Math.PI / 2}; PLEK.pingR = {kind: "ping", x: ptx + 1.65, z: ptz, face: -Math.PI / 2};
    const tx = rK.x1 - 2.0, tz = 4.4;                                                // kantinetafel met banken
    cube(1.0, 0.07, 2.4, V.hout, tx, 0.75, tz); [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(([i, k]) => cube(0.07, 0.72, 0.07, V.hout2, tx + i * 0.42, 0.36, tz + k * 1.05));
    [tx - 0.8, tx + 0.8].forEach(bx => { cube(0.36, 0.07, 2.2, V.hout2, bx, 0.45, tz); cube(0.06, 0.42, 0.06, V.hout2, bx, 0.21, tz - 0.9); cube(0.06, 0.42, 0.06, V.hout2, bx, 0.21, tz + 0.9); });
    cube(0.14, 0.16, 0.14, V.wit, tx + 0.15, 0.86, tz - 0.5); cyl(0.17, 0.03, mix(V.s4, V.bruin, .35), tx - 0.1, 0.8, tz + 0.5);
    PLEK.bank1 = {kind: "bank", x: tx + 0.8, z: tz - 0.5, face: -Math.PI / 2, sit: true};
    PLEK.bank2 = {kind: "bank", x: tx - 0.8, z: tz + 0.6, face: Math.PI / 2, sit: true};
    cube(9.0, 0.02, 1.2, tm(P => P.donker ? mix(V.s5, V.zwart, .6) : mix(V.s5, V.wit, .45)), rK.cx, 0.07, 6.6, scene, false);
    plant(rK.x0 + 0.5, 6.9); plant(rK.x1 - 0.6, 6.9);

    // ----------------------------------------------------------- maquettezaal
    const rM = K.maquette, mx = rM.cx - 0.3, mz = 3.9;
    cube(4.8, 0.75, 2.2, V.wit, mx, 0.38, mz); cube(4.9, 0.06, 2.3, V.lijn, mx, 0.78, mz);
    cube(4.6, 0.03, 2.0, mix(V.s3, V.lijn, .55), mx, 0.82, mz, scene, false);
    cube(4.6, 0.025, 0.42, V.water, mx, 0.84, mz + 0.22, scene, false);                       // gracht
    cube(4.6, 0.04, 0.12, V.licht, mx, 0.85, mz - 0.05, scene, false); cube(4.6, 0.04, 0.3, V.licht, mx, 0.85, mz + 0.6, scene, false);
    const huisKl = [V.baksteen, V.navy, mix(V.lijn, V.s4, .25), mix(V.s3, V.zwart, .4), mix(V.baksteen, V.zwart, .2), V.blauwgrijs, V.baksteen, mix(V.lijn, V.s2, .2)];
    huisKl.forEach((c, i) => {
      const hx = mx - 2.0 + i * 0.57, h = 0.55 + ((i * 7) % 4) * 0.09, hz = mz - 0.45, base = 0.84;
      cube(0.52, h, 0.5, c, hx, base + h / 2, hz);
      if (i % 3 === 0) { cube(0.36, 0.12, 0.5, c, hx, base + h + 0.06, hz); cube(0.2, 0.1, 0.5, c, hx, base + h + 0.17, hz); }   // trapgevel
      else if (i % 3 === 1) { const t = cube(0.37, 0.37, 0.5, c, hx, base + h, hz); t.rotation.z = Math.PI / 4; }            // tuitgevel
      else { cube(0.26, 0.2, 0.5, c, hx, base + h + 0.1, hz); cube(0.56, 0.04, 0.52, V.wit, hx, base + h, hz, scene, false); } // halsgevel
      for (let f = 0; f < 2; f++) for (let k = 0; k < 2; k++) cube(0.1, 0.13, 0.01, V.wit, hx - 0.12 + k * 0.24, base + 0.28 + f * 0.22, hz + 0.255, scene, false);
      cube(0.1, 0.18, 0.01, V.donker, hx, base + 0.09, hz + 0.255, scene, false);
    });
    [mx - 1.6, mx + 0.3, mx + 1.9].forEach(bx => { cube(0.05, 0.18, 0.05, V.bruin, bx, 0.95, mz + 0.62); cube(0.22, 0.22, 0.22, V.groen, bx, 1.12, mz + 0.62); });
    function bordje(tekstBoven, verkocht, x, z) {
      const t = doek(256, 160, g => { g.fillStyle = verkocht ? V.wit : V.s2; g.fillRect(0, 0, 256, 160);
        g.strokeStyle = V.navy; g.lineWidth = 8; g.strokeRect(4, 4, 248, 152);
        tekst(g, tekstBoven, 128, 80, 52, verkocht ? V.s2 : V.wit);
        if (verkocht) { g.save(); g.translate(128, 80); g.rotate(-0.42); g.fillStyle = V.navy; g.fillRect(-160, -26, 320, 52);
          tekst(g, TEKST3D.bord.verkocht, 0, 2, 38, V.wit); g.restore(); } });
      cube(0.04, 0.7, 0.04, V.wit, x, 1.2, z); paneel(0.6, 0.375, t.tex, x, 1.52, z + 0.03);
    }
    bordje(TEKST3D.bord.koop, false, mx - 1.15, mz - 0.1); bordje(TEKST3D.bord.koop, true, mx + 1.15, mz - 0.1);
    const bf = new T.Group(); bf.position.set(rM.x1 - 1.9, 0, 6.35); bf.rotation.y = -0.12; scene.add(bf);   // bakfiets
    cube(0.8, 0.45, 0.6, V.hout, -0.55, 0.6, 0, bf); cube(0.84, 0.04, 0.64, V.hout2, -0.55, 0.84, 0, bf);
    const wiel = (r, x) => { const w = cyl(r, 0.06, V.donker, x, r, 0, bf, 20); w.rotation.x = Math.PI / 2; cyl(r * 0.25, 0.08, V.licht, x, r, 0, bf, 10).rotation.x = Math.PI / 2; };
    wiel(0.2, -0.55); wiel(0.3, 0.95);
    cube(1.2, 0.06, 0.06, V.navy, 0.3, 0.42, 0, bf); cube(0.06, 0.55, 0.06, V.navy, 0.62, 0.65, 0, bf); cube(0.24, 0.05, 0.12, V.zwart, 0.62, 0.95, 0, bf);
    cube(0.06, 0.65, 0.06, V.navy, 0.05, 0.72, 0, bf); cube(0.05, 0.05, 0.5, V.zwart, 0.05, 1.05, 0, bf);
    PLEK.maquette = {kind: "maquette", x: mx - 0.3, z: mz + 1.55, face: Math.PI};
    plant(rM.x0 + 0.5, 6.9);

    // --------------------------------------------------------------- rustkamer
    const rR = K.rust, BEDDEN = [], lampen = [];
    cube(rR.w - 0.8, 0.02, 3.6, tm(P => P.donker ? mix(V.ijsblauw, V.zwart, .65) : mix(V.ijsblauw, V.wit, .3)), rR.cx, 0.07, 4.9, scene, false);
    [0, 1, 2, 3].forEach(i => {
      const bx = rR.x0 + 0.85 + i * 1.6, head = 3.0, len = 2.2;
      cube(1.0, 0.35, len, V.hout2, bx, 0.18, head + len / 2); cube(0.92, 0.18, len - 0.1, V.wit, bx, 0.44, head + len / 2);
      cube(1.0, 0.9, 0.12, V.hout2, bx, 0.45, head - 0.02); cube(0.66, 0.14, 0.35, V.lijn, bx, 0.6, head + 0.3);
      const deken = cube(0.96, 0.12, 1.25, [V.navy, V.blauwgrijs, V.navy, V.blauwgrijs][i], bx, 0.6, head + len - 0.65);
      const feet = head + 0.15 + 1.75;
      BEDDEN.push({kind: "bed", x: bx, z: feet, face: 0, lie: true, via: {x: bx + 0.8, z: feet}, deken});
    });
    [rR.x0 + 0.3, rR.x1 - 0.3].forEach(lx => { cube(0.06, 1.2, 0.06, V.donker, lx, 0.6, 2.6); const l = gloei(V.lijn); cube(0.3, 0.22, 0.3, l, lx, 1.3, 2.6, scene, false); lampen.push(l); });
    const SPOTS = [PLEK.koffie, PLEK.koek, PLEK.pingL, PLEK.pingR, PLEK.bank1, PLEK.bank2, ...BEDDEN];
    const pong = [PLEK.pingL, PLEK.pingR];

    // ---------------------------------------------------------- de skyline
    // Een geschilderd decor dat altijd naar de camera kijkt: lucht en torens achter, molenwieken in het midden,
    // grachtenpanden en de gracht voor. Drie lagen, zodat de wieken achter de panden langs draaien.
    const SW = 1 << 11, SH = 900,  /* 2^11 px */ NOK = SH * 0.86;
    let deel = null, twinkel = [], molen = null;
    const achter = doek(SW, SH, (g, w, h, d) => {
      if (!d) return; const [boven, midden, onder] = LUCHT[d], r = zaad(11);
      const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, boven); gr.addColorStop(.55, midden); gr.addColorStop(1, onder);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      if (d === "nacht") {
        for (let i = 0; i < 240; i++) { const y = r() ** 1.6 * h * .6; g.fillStyle = `rgba(255,255,255,${.2 + r() * .7})`; const z = r() < .08 ? 3 : 2; g.fillRect(r() * w, y, z, z); }
        const mx = w * .9, my = h * .15, halo = g.createRadialGradient(mx, my, 8, mx, my, 140);
        halo.addColorStop(0, "rgba(255,255,255,.28)"); halo.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = halo; g.fillRect(mx - 140, my - 140, 280, 280);
        g.fillStyle = V.lijn; g.beginPath(); g.arc(mx, my, 34, 0, Math.PI * 2); g.fill();
      } else {
        if (d === "schemer") { const sx = w * .12, sy = h * .7, halo = g.createRadialGradient(sx, sy, 10, sx, sy, 260);
          halo.addColorStop(0, "rgba(255,255,255,.55)"); halo.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = halo; g.fillRect(sx - 260, sy - 260, 520, 520);
          g.fillStyle = mix(V.s4, V.wit, .45); g.beginPath(); g.arc(sx, sy, 46, 0, Math.PI * 2); g.fill(); }
        for (let i = 0; i < 9; i++) { const cx = r() * w, cy = h * (.08 + r() * .32), s = 30 + r() * 40;
          g.fillStyle = d === "dag" ? "rgba(255,255,255,.85)" : "rgba(255,255,255,.35)";
          [[0, 0, 1], [-1.1, .25, .7], [1.1, .3, .75], [.5, -.35, .7]].forEach(([a, b, k]) => { g.beginPath(); g.ellipse(cx + a * s, cy + b * s, s * k * 1.4, s * k * .8, 0, 0, Math.PI * 2); g.fill(); }); }
      }
      // verre daken
      const ver = mix(onder, V.navy, d === "nacht" ? .35 : .25);
      g.fillStyle = ver;
      for (let x = -20; x < w;) { const bw = 30 + r() * 60, bh = h * (.1 + r() * .1);
        g.fillRect(x, NOK - bh, bw, bh + 40); g.beginPath(); g.moveTo(x, NOK - bh); g.lineTo(x + bw / 2, NOK - bh - bw * .45); g.lineTo(x + bw, NOK - bh); g.fill(); x += bw + 2; }
      const mid = d === "dag" ? mix(V.navy, onder, .5) : d === "schemer" ? mix(V.navy, onder, .25) : mix(V.navy, V.zwart, .3);
      const licht = d === "nacht" ? mix(V.s4, V.wit, .45) : mix(onder, V.wit, .3);
      // kerktoren met spits, naar de Nieuwe Kerk
      const kx = w * .3; g.fillStyle = mid;
      g.fillRect(kx - 300, NOK - h * .17, 240, h * .17 + 40); g.beginPath(); g.moveTo(kx - 300, NOK - h * .17); g.lineTo(kx - 180, NOK - h * .27); g.lineTo(kx - 60, NOK - h * .17); g.fill();
      g.fillRect(kx - 58, h * .44, 116, NOK - h * .44 + 40); g.fillRect(kx - 46, h * .35, 92, h * .1); g.fillRect(kx - 30, h * .285, 60, h * .07);
      g.beginPath(); g.moveTo(kx - 32, h * .29); g.lineTo(kx, h * .09); g.lineTo(kx + 32, h * .29); g.fill();
      [-46, 46].forEach(o => { g.beginPath(); g.moveTo(kx + o - 8, h * .355); g.lineTo(kx + o, h * .32); g.lineTo(kx + o + 8, h * .355); g.fill(); });
      g.fillRect(kx - 2, h * .06, 4, h * .035); g.fillRect(kx - 9, h * .072, 18, 4);
      g.fillStyle = mix(mid, V.zwart, .35); [-22, 22].forEach(o => { g.beginPath(); g.moveTo(kx + o - 10, h * .6); g.lineTo(kx + o - 10, h * .53); g.arc(kx + o, h * .53, 10, Math.PI, 0); g.lineTo(kx + o + 10, h * .6); g.fill(); });
      [-12, 12].forEach(o => g.fillRect(kx + o - 4, h * .3, 8, h * .04));
      g.fillStyle = licht; g.beginPath(); g.arc(kx, h * .47, 17, 0, Math.PI * 2); g.fill();
      g.strokeStyle = mid; g.lineWidth = 3; g.beginPath(); g.moveTo(kx, h * .47); g.lineTo(kx, h * .47 - 11); g.moveTo(kx, h * .47); g.lineTo(kx + 8, h * .47 + 3); g.stroke();
      // molen: stellingmolen met kap, de wieken zijn een eigen laag
      const mx = w * .78, mt = h * .5; g.fillStyle = mid;
      g.beginPath(); g.moveTo(mx - 86, NOK + 40); g.lineTo(mx - 46, mt); g.lineTo(mx + 46, mt); g.lineTo(mx + 86, NOK + 40); g.fill();
      g.beginPath(); g.ellipse(mx, mt, 54, 26, 0, Math.PI, 0); g.fill(); g.fillRect(mx - 54, mt - 2, 108, 8);
      g.fillRect(mx - 130, h * .7, 260, 7); for (let x = -124; x <= 124; x += 31) g.fillRect(mx + x, h * .7 - 26, 4, 26);
      g.fillRect(mx - 128, h * .7 - 28, 256, 4);
      g.fillStyle = d === "nacht" ? licht : mix(mid, V.zwart, .35);
      g.fillRect(mx - 9, h * .58, 18, 24); g.fillRect(mx - 13, NOK - 46, 26, 46);
      molen = {x: mx, y: mt - 4, r: 236};
    });
    const voor = doek(SW, SH, (g, w, h, d) => {
      if (!d) return; const r = zaad(5); twinkel = [];
      const donker = d === "nacht" ? .72 : d === "schemer" ? .35 : 0;
      const kleur = c => mix(c, V.navy, donker);
      const panden = [V.baksteen, mix(V.baksteen, V.zwart, .25), V.navy, mix(V.lijn, V.s4, .22), mix(V.s3, V.zwart, .45), V.blauwgrijs, mix(V.s2, V.bruin, .25), V.lijn];
      const basis = h * .93;
      let n = 0;
      for (let x = -14; x < w; n++) {
        const bw = 76 + r() * 44, bh = h * (.2 + r() * .13), top = basis - bh, c = kleur(panden[Math.floor(r() * panden.length)]);
        const type = ["trap", "hals", "klok", "tuit", "lijst"][Math.floor(r() * 5)], cx = x + bw / 2;
        g.fillStyle = c; g.fillRect(x, top, bw, bh + 4);
        let spits = top;
        g.beginPath();
        if (type === "trap") { const st = 4, sw = bw / 2 / (st + 1), sh = 16; for (let k = 0; k < st; k++) g.rect(x + sw * (k + 1), top - sh * (k + 1), bw - 2 * sw * (k + 1), sh + 1); spits = top - sh * st; }
        if (type === "hals") { g.rect(cx - bw * .22, top - 46, bw * .44, 47); g.moveTo(cx - bw * .22, top); g.arc(cx - bw * .22, top, 18, Math.PI, Math.PI * 1.5); g.lineTo(cx - bw * .22, top);
          g.moveTo(cx + bw * .22, top); g.arc(cx + bw * .22, top, 18, Math.PI * 1.5, 0); g.lineTo(cx + bw * .22, top);
          g.moveTo(cx - bw * .26, top - 46); g.lineTo(cx, top - 64); g.lineTo(cx + bw * .26, top - 46); spits = top - 64; }
        if (type === "klok") { g.moveTo(x + 6, top); g.quadraticCurveTo(cx - bw * .3, top - 10, cx - bw * .24, top - 40); g.quadraticCurveTo(cx - bw * .26, top - 62, cx, top - 66);
          g.quadraticCurveTo(cx + bw * .26, top - 62, cx + bw * .24, top - 40); g.quadraticCurveTo(cx + bw * .3, top - 10, x + bw - 6, top); spits = top - 66; }
        if (type === "tuit") { g.moveTo(x + 4, top); g.lineTo(cx - 12, top - 58); g.lineTo(cx + 12, top - 58); g.lineTo(x + bw - 4, top); spits = top - 58; }
        if (type === "lijst") { g.rect(x - 3, top - 12, bw + 6, 13); spits = top - 12; }
        g.fill();
        if (type !== "lijst") { g.fillStyle = mix(c, V.zwart, .4); g.fillRect(cx - 2, spits + 4, 4, 14); g.fillRect(cx - 2, spits + 4, 12, 3); }   // hijsbalk
        if (type === "lijst") { g.fillStyle = mix(c, V.wit, .4); g.fillRect(x - 3, top - 12, bw + 6, 3); }
        const verd = Math.max(2, Math.floor((bh - 50) / 48)), kol = bw > 100 ? 3 : 2, rw = 15, rh = 27, gap = (bw - kol * rw) / (kol + 1);
        for (let f = 0; f < verd; f++) for (let k = 0; k < kol; k++) {
          const rx = x + gap + k * (rw + gap), ry = top + 16 + f * 48, aan = d !== "dag" && r() < (d === "nacht" ? .45 : .25);
          const warm = mix(V.s4, V.wit, .4 + r() * .3), glas = d === "dag" ? mix(V.navy, V.s1, .35) : mix(V.navy, V.zwart, .35);
          g.fillStyle = d === "nacht" ? mix(c, V.zwart, .3) : V.wit; g.fillRect(rx - 2, ry - 2, rw + 4, rh + 4);
          g.fillStyle = aan ? warm : glas; g.fillRect(rx, ry, rw, rh);
          if (!aan || d !== "dag") { g.fillStyle = d === "nacht" ? mix(c, V.zwart, .3) : V.wit; g.fillRect(rx, ry + rh / 2 - 1, rw, 2); }
          if (d === "nacht" && r() < .05) twinkel.push({x: rx, y: ry, w: rw, h: rh, aan, warm, glas, kozijn: mix(c, V.zwart, .3)});
        }
        g.fillStyle = d === "nacht" ? (r() < .5 ? mix(V.s4, V.wit, .5) : mix(V.navy, V.zwart, .3)) : mix(c, V.zwart, .55);
        g.fillRect(x + gap - 2, basis - 34, 18, 34); g.fillStyle = kleur(V.licht); g.fillRect(x + gap - 6, basis - 4, 26, 4);
        g.fillStyle = mix(c, V.zwart, .35); g.fillRect(x + bw - 1, top, 2, bh);
        if (n % 3 === 1) { const bx = x + bw, groen = kleur(V.groen);                                     // linde
          g.fillStyle = mix(groen, V.zwart, .3); g.fillRect(bx - 4, basis - 70, 8, 70); g.fillStyle = groen;
          [[0, -96, 46], [-30, -78, 32], [30, -80, 34], [0, -130, 30]].forEach(([a, b, s]) => { g.beginPath(); g.arc(bx + a, basis + b, s, 0, Math.PI * 2); g.fill(); }); }
        x += bw;
      }
      g.fillStyle = kleur(mix(V.licht, V.grijs, .3)); g.fillRect(0, basis, w, h * .02);                 // kade
      const wg = g.createLinearGradient(0, basis + h * .02, 0, h);
      wg.addColorStop(0, kleur(mix(V.water, V.s1, .3))); wg.addColorStop(1, kleur(V.water)); g.fillStyle = wg; g.fillRect(0, basis + h * .02, w, h);
      g.fillStyle = d === "nacht" ? `rgba(${rgb(mix(V.s4, V.wit, .5))},.35)` : "rgba(255,255,255,.35)";
      for (let i = 0; i < 70; i++) g.fillRect(r() * w, basis + h * (.03 + r() * .035), 14 + r() * 40, 2);
      if (d === "nacht") for (let x = 60; x < w; x += 170) { g.fillStyle = mix(V.navy, V.zwart, .4); g.fillRect(x, basis - 46, 4, 46);
        g.fillStyle = mix(V.s4, V.wit, .5); g.fillRect(x - 5, basis - 54, 14, 10); }
    });
    const wiek = doek(512, 512, (g, w, h, d) => {
      if (!d) return; const mid = d === "dag" ? mix(V.navy, LUCHT[d][2], .5) : d === "schemer" ? mix(V.navy, LUCHT[d][2], .25) : mix(V.navy, V.zwart, .3);
      g.translate(256, 256);
      for (let k = 0; k < 4; k++) { g.save(); g.rotate(k * Math.PI / 2);
        g.fillStyle = mid; g.fillRect(-6, -250, 12, 250);
        g.strokeStyle = mid; g.lineWidth = 4; g.strokeRect(6, -246, 44, 200);
        for (let y = -246; y < -46; y += 20) { g.beginPath(); g.moveTo(6, y); g.lineTo(50, y); g.stroke(); }
        g.beginPath(); g.moveTo(28, -246); g.lineTo(28, -46); g.stroke(); g.restore(); }
      g.fillStyle = mid; g.beginPath(); g.arc(0, 0, 16, 0, Math.PI * 2); g.fill(); g.setTransform(1, 0, 0, 1, 0, 0);
    });
    const decor = (tex, z, transp) => { const m = new T.Mesh(new T.PlaneGeometry(1, 1), new T.MeshBasicMaterial({map: tex, transparent: transp, depthWrite: false}));
      m.renderOrder = -3 + z; cam.add(m); m.position.z = -150 + z; return m; };
    const lagen = [decor(achter.tex, 0, false), decor(voor.tex, 2, true)];
    const wieken = decor(wiek.tex, 1, true);
    scene.add(cam);
    const wandTop = new T.Vector3();
    function plaatsDecor() {
      wandTop.set(0, 3.2, BACK - 0.3).applyMatrix4(cam.matrixWorldInverse);
      const onder = wandTop.y - 1.0, boven = cam.top + 0.3, hg = boven - onder, br = (cam.right - cam.left) * 1.04;
      const pa = br / hg, ca = SW / SH, rek = Math.max(1, pa / ca), rx = Math.min(1, pa / ca), ry = 1;   // nooit de torenspits afsnijden: liever iets breder
      lagen.forEach(m => { m.scale.set(br, hg, 1); m.position.set(0, (boven + onder) / 2, m.position.z); m.material.map.repeat.set(rx, ry); m.material.map.offset.set((1 - rx) / 2, 0); });
      if (molen) { const u = molen.x / SW, v = 1 - molen.y / SH;
        const wx = ((u - (1 - rx) / 2) / rx - .5) * br, wy = ((v) / ry - .5) * hg + (boven + onder) / 2, straal = molen.r / SW / rx * br;
        wieken.position.set(wx, wy, wieken.position.z); wieken.scale.set(straal * 512 / 250, straal * 512 / 250 / rek, 1); }
    }
    let laatsteTwinkel = 0;
    function twinkelen(t) {
      if (stil || deel !== "nacht" || t - laatsteTwinkel < 1200 || !twinkel.length) return; laatsteTwinkel = t;
      const g = voor.g; for (let k = 0; k < 2; k++) { const q = twinkel[Math.floor(Math.random() * twinkel.length)]; q.aan = !q.aan;
        g.fillStyle = q.aan ? q.warm : q.glas; g.fillRect(q.x, q.y, q.w, q.h); if (!q.aan) { g.fillStyle = q.kozijn; g.fillRect(q.x, q.y + q.h / 2 - 1, q.w, 2); } }
      voor.tex.needsUpdate = true;
    }
    function dagdeel(force) {
      const d = deelVan(uur()); if (d === deel && !force) return; deel = d;
      achter.opnieuw(d); voor.opnieuw(d); wiek.opnieuw(d); plaatsDecor();
      sceneEl.style.background = mix(V.water, V.navy, d === "nacht" ? .72 : d === "schemer" ? .35 : 0);   // het kantoor ligt aan de gracht: geen harde rand onder het decor
      const [, , onder] = LUCHT[d]; ramen.forEach(m => m.color.set(d === "nacht" ? mix(V.navy, V.zwart, .2) : onder));
      lichten();
    }
    function lichten() {
      const d = deel, dk = P.donker ? .85 : 1;
      hemi.color.set(d === "dag" ? V.wit : d === "schemer" ? mix(V.s4, V.wit, .6) : mix(V.ijsblauw, V.s1, .2));
      hemi.intensity = (d === "dag" ? .82 : d === "schemer" ? .74 : .62) * dk;
      zon.color.set(d === "dag" ? mix(V.s4, V.wit, .85) : d === "schemer" ? mix(V.s2, V.wit, .55) : V.blauwgrijs);
      zon.intensity = (d === "dag" ? .55 : d === "schemer" ? .45 : .35) * dk;
      lampen.forEach(l => l.color.set(bedtijdVan(uur()) ? mix(V.s4, V.wit, .45) : V.lijn));
    }

    // ------------------------------------------------------------- overlay
    const chefP = persoon("chef"); chefP.g.position.set(PLEK.maquette.x, 0.06, PLEK.maquette.z);
    const chef = {id: "chef", p: chefP, path: [], mode: "stand", face: Math.PI, wait: 0, seed: 7, at: "maquette", target: null, retarget: 0, k: 0};
    const ACT = [...IDS.map(id => W[id]), chef];
    const el = {};
    // De werkbalk staat al in de pagina (werkbalk_html() in Python, VA-64): hier alleen aanhaken.
    const balk = root.querySelector(".pk-balk");
    ACT.forEach(a => {
      const bel = document.createElement("div"), naam = document.createElement("div"), hit = document.createElement("button"), z = document.createElement("div");
      bel.className = "pk-bel"; naam.className = "pk-naam"; hit.className = "pk-hit"; hit.type = "button"; z.className = "pk-z"; z.hidden = true;
      naam.innerHTML = a === chef ? TEKST3D.chef.naam : `<b>${a.nr}</b>${NAMEN[a.id][0]}`;
      if (a === chef) { naam.classList.add("chef"); bel.hidden = true; }
      const knop = balk.querySelector(`.pk-knop[data-wie="${a.id}"]`); knop.hidden = false;
      hit.onclick = bel.onclick = () => kies(gekozen === a.id ? null : a.id, hit);
      knop.onclick = () => kies(gekozen === a.id ? null : a.id, knop);
      ov.append(naam, bel, z, hit); el[a.id] = {bel, naam, hit, z, knop, tekst: null};
    });
    const borden = ALLE.map(r => { const b = document.createElement("div"); b.className = r.z0 === BACK ? "pk-bord" : "pk-bord voor"; b.textContent = TEKST3D.kamers[r.id].toUpperCase(); ov.appendChild(b); return [b, r]; });
    const ring = new T.Mesh(new T.RingGeometry(0.5, 0.64, 32), new T.MeshBasicMaterial({color: V.s1, transparent: true, opacity: .9}));
    ring.rotation.x = -Math.PI / 2; ring.visible = false; scene.add(ring);

    // ------------------------------------------------------------ toestand
    let gekozen = null, opener = null, info = {}, smal = false;
    let g = (data && data.gebied) || "dit gebied";
    function zet(nieuw, forceer = {}) {
      data = nieuw; g = (data && data.gebied) || "dit gebied";
      IDS.forEach(id => {
        const r = PK.lees(data, id), a = W[id], e = el[id];
        if (a.s !== r.s) { a.wait = 0; if (a.mode === "lie" || a.mode === "sit") { a.mode = "stand"; } a.at = null; if (a.spot) { a.spot.occ = null; a.spot = null; } }
        a.s = r.s; info[id] = r;
        if (e.tekst !== r.bel) { e.tekst = r.bel; e.bel.textContent = r.bel; e.bel.style.animation = "none"; e.bel.offsetWidth; e.bel.style.animation = ""; }
        e.bel.className = "pk-bel " + r.s; e.naam.className = "pk-naam " + r.s;
        e.hit.setAttribute("aria-label", TEKST3D.hit(NAMEN[id][0], r.bel));
        e.knop.className = "pk-knop " + r.s; e.knop.querySelector(".bel").textContent = r.bel;
      });
      spullen(); chefInfo();
      if (gekozen) toonUitleg(gekozen);
      if (stil) stilBeeld();
    }
    const chefTekst = () => (data && data.tekst && data.tekst.chef) || {zin: "onbekend", bel: {}};
    function chefInfo() {
      const c = chefTekst(), e = el.chef, zin = c.zin;
      info.chef = {s: "chef", zin, uitleg: TEKST3D.chef.uitleg, bel: ""};
      e.hit.setAttribute("aria-label", TEKST3D.hit(TEKST3D.chef.naam, zin));
      e.knop.className = "pk-knop chef"; e.knop.querySelector(".bel").textContent = zin;
    }
    function spullen() {   // wat in de kamers meebeweegt met de cijfers
      const sel = data && data.selectie;
      bord.opnieuw(W.selectie.s !== "leeg" && sel && sel.categorieen ? sel.categorieen : null);
      kratPapier.visible = W.ingest.s !== "leeg";
      const aan = W.verrijking.s === "werkt" || W.verrijking.s === "aandacht";
      kabelIn.visible = aan; kabelUit.visible = !aan;
      const n = {aandacht: 4, werkt: 2, slaapt: 1, leeg: 0}[W.controle.s];
      dossiers.forEach((d, i) => d.visible = i < n);
    }
    function toonUitleg(id) {
      const r = info[id];
      const h3 = uitleg.querySelector("h3");
      if (id === "chef") h3.innerHTML = `${TEKST3D.chef.naam} <em>${TEKST3D.chef.rol}</em>`;
      else h3.innerHTML = `${IDS.indexOf(id) + 1} · ${NAMEN[id][0]} <em>${NAMEN[id][1]}</em>`;
      const st = uitleg.querySelector(".pk-status"); st.className = "pk-status " + (id === "chef" ? "" : r.s); st.textContent = r.zin;
      uitleg.querySelector(".pk-tekst").textContent = r.uitleg;
    }
    function kies(id, van) {
      gekozen = id; if (van) opener = van;
      ACT.forEach(a => { const x = String(a.id === id); el[a.id].hit.setAttribute("aria-expanded", x); el[a.id].knop.setAttribute("aria-expanded", x); });
      uitleg.hidden = !id; if (id) toonUitleg(id);
      if (stil) teken();
    }
    function sluit() { if (!gekozen) return; const terug = opener; kies(null); if (terug && terug.isConnected) terug.focus(); }
    uitleg.querySelector(".pk-sluit").onclick = sluit;
    // Escape sluit de uitleg; niet als een pand open is (dat sluit zelf) of de lade (VA-64).
    document.addEventListener("keydown", e => { if (e.key === "Escape" && gekozen && !e.defaultPrevented && !document.querySelector("dialog[open]")) sluit(); });

    // ------------------------------------------------------------ bewegen
    const SPEED = 2.3;
    function goTo(a, x, z, na, via) {
      if (a.spot) { a.spot.occ = null; a.spot = null; }
      const pos = a.p.g.position;
      if (stil) { pos.x = x; pos.z = z; a.path = []; a.mode = "stand"; na && na(); return; }
      const pad = [], zelfdeRij = Math.sign(pos.z - AISLE) === Math.sign(z - AISLE);
      if (!(zelfdeRij && Math.abs(pos.x - x) < 0.3 && !via)) { if (Math.abs(pos.z - AISLE) > 0.2) pad.push({x: pos.x, z: AISLE}); pad.push({x: via ? via.x : x, z: AISLE}); }
      if (via) pad.push(via); pad.push({x, z});
      a.path = pad; a.na = na || null; a.mode = "walk"; a.at = null;
    }
    const bureauDoel = a => a.s === "werkt" ? {x: a.seat.x, z: a.seat.z, face: Math.PI, sit: true}
      : a.s === "aandacht" ? {x: a.seat.x + 0.85, z: a.seat.z + 0.5, face: 0.45}
      : {x: a.seat.x - 0.9, z: a.seat.z + 0.35, face: -0.25};
    function aankomst(a, sp, t) {
      a.at = sp.kind; a.face = sp.face; a.spot = sp; sp.occ = a.id;
      if (sp.sit) a.mode = "sit";
      if (sp.lie) { a.mode = "lie"; a.p.g.position.x = sp.x; a.p.g.position.z = sp.z; }
      a.nap = sp.kind === "bank" && Math.random() < .75;
      a.wait = t + (sp.lie ? 1e9 : rnd(10000, 18000));
    }
    function denk(a, t) {
      a.typing = a.wave = a.sleepy = a.pong = a.shrug = false;
      if (a.s !== "slaapt") {
        a.coffee = false; const d = bureauDoel(a);
        if (a.at !== a.s) { if (!(a.mode === "walk" && a.goal === a.s)) { a.goal = a.s; const s = a.s; goTo(a, d.x, d.z, () => { a.at = s; a.face = d.face; if (d.sit) a.mode = "sit"; }); } }
        else { a.face = d.face; if (d.sit) a.mode = "sit"; a.typing = a.s === "werkt"; a.wave = a.s === "aandacht"; a.shrug = a.s === "leeg"; }
        return;
      }
      if (a.mode === "walk") return;
      const nacht = bedtijdVan(uur());
      if (nacht && a.at !== "bed") {
        const bed = BEDDEN.find(b => !b.occ || b.occ === a.id);
        if (bed) { bed.occ = a.id; a.goal = "bed"; goTo(a, bed.x, bed.z, () => aankomst(a, bed, t), bed.via); bed.occ = a.id; return; }
      }
      if (!nacht && a.at === "bed") { a.mode = "stand"; a.at = null; if (a.spot) { a.spot.occ = null; a.spot = null; } a.wait = 0; }
      const rally = a.at === "ping" && pong.every(sp => sp.occ);
      if (!nacht && t > a.wait && !(rally && t < a.wait + 8000)) {
        const vrij = SPOTS.filter(sp => !sp.occ && sp.kind !== "bed");
        const wacht = pong.find(sp => sp.occ && sp.occ !== a.id) && pong.find(sp => !sp.occ);
        const sp = wacht && Math.random() < .7 ? wacht : vrij[Math.floor(Math.random() * vrij.length)];
        if (sp) { if (a.mode === "sit") a.mode = "stand"; a.goal = sp.kind; goTo(a, sp.x, sp.z, () => aankomst(a, sp, performance.now())); sp.occ = a.id; a.spot = sp; a.wait = t + 1e9; }
      }
      a.pong = a.at === "ping"; a.coffee = a.at === "koffie" || a.at === "koek" || (a.at === "bank" && !a.nap);
      a.sleepy = a.at === "bed" || (a.at === "bank" && a.nap);
    }
    function denkChef(t) {
      chef.typing = chef.wave = chef.sleepy = chef.pong = chef.shrug = chef.coffee = false;
      const lijst = IDS.map(id => W[id]).filter(a => a.s === "aandacht");
      const bijDoel = chef.target && chef.target.s === "aandacht";
      if (t > chef.retarget || (lijst.length && !bijDoel) || (!lijst.length && chef.target)) {
        if (lijst.length) {
          const doel = lijst[chef.k++ % lijst.length], d = bureauDoel(doel);
          chef.target = doel; chef.retarget = t + 8000;
          goTo(chef, d.x + 1.3, d.z + 1.5, () => { chef.at = "bij"; chef.face = Math.atan2(d.x - (d.x + 1.3), d.z - (d.z + 1.5)); });
        } else {
          chef.target = null; chef.retarget = t + rnd(8000, 12000);
          const werkers = IDS.map(id => W[id]).filter(a => a.s === "werkt"), r = Math.random();
          if (r < .4 && werkers.length) { const w = werkers[Math.floor(Math.random() * werkers.length)];
            goTo(chef, w.seat.x + 1.0, w.seat.z + 1.0, () => { chef.at = "ronde"; chef.face = -2.4; }); }
          else if (r < .7) goTo(chef, PLEK.maquette.x + 0.6, PLEK.maquette.z, () => { chef.at = "maquette"; chef.face = Math.PI; });
          else { const x = rnd(-10, 10); goTo(chef, x, AISLE + 0.2, () => { chef.at = "gang"; chef.face = 0.2; }); }
        }
      }
    }
    function houding(a, dt, t) {
      const P_ = a.p, pos = P_.g.position; let loopt = false;
      if (a.mode === "walk" && a.path.length) {
        const doel = a.path[0], dx = doel.x - pos.x, dz = doel.z - pos.z, d = Math.hypot(dx, dz);
        if (d < 0.05) { a.path.shift(); if (!a.path.length) { a.mode = "stand"; a.na && a.na(); } }
        else { const s = Math.min(d, SPEED * dt); pos.x += dx / d * s; pos.z += dz / d * s; a.face = Math.atan2(dx, dz); loopt = true; }
      }
      const lig = a.mode === "lie", zit = a.mode === "sit";
      if (lig) P_.g.rotation.y = 0;
      else if (stil) P_.g.rotation.y = a.face;
      else { let dr = a.face - P_.g.rotation.y; dr = Math.atan2(Math.sin(dr), Math.cos(dr)); P_.g.rotation.y += dr * Math.min(1, dt * 10); }
      P_.g.rotation.x = lig ? -Math.PI / 2 : 0;
      const tt = stil ? a.seed : t / 1000 + a.seed;
      const zwaai = loopt ? Math.sin(tt * 11) * 0.7 : 0;
      P_.legL.rotation.x = zit ? -1.5 : zwaai; P_.legR.rotation.x = zit ? -1.5 : -zwaai;
      P_.body.position.y = zit ? 0.12 : 0; P_.body.rotation.z = 0; P_.head.rotation.set(0, 0, 0);
      P_.armL.rotation.set(-zwaai * 0.8, 0, 0); P_.armR.rotation.set(zwaai * 0.8, 0, 0);
      if (a.typing) { P_.armL.rotation.x = -1.25 + (stil ? 0 : Math.sin(tt * 18) * 0.12); P_.armR.rotation.x = -1.25 + (stil ? 0.05 : Math.cos(tt * 18) * 0.12); P_.head.rotation.y = stil ? 0 : Math.sin(tt * 0.7) * 0.15; }
      if (a.wave) { P_.armR.rotation.x = -2.9; P_.armR.rotation.z = stil ? 0.2 : Math.sin(tt * 9) * 0.35; }
      if (a.shrug) { const s = stil ? 1 : Math.min(1, Math.max(0, Math.sin(tt * 1.7) * 1.6));
        P_.armL.rotation.set(-0.55 * s, 0, -0.85 * s); P_.armR.rotation.set(-0.55 * s, 0, 0.85 * s);
        P_.body.position.y += 0.04 * s; P_.head.rotation.z = 0.2 * s; }
      if (a.pong) { P_.armR.rotation.x = -1.0 + (stil ? 0.3 : Math.sin(t / 1000 * Math.PI / 0.7) * 0.7); P_.armR.rotation.z = -0.3; }
      P_.mug.visible = !!a.coffee;
      if (a.coffee && !loopt) P_.armR.rotation.x = stil ? -1.9 : Math.sin(tt * 0.8) > 0.6 ? -1.9 : -0.6;
      if (a.sleepy && !lig) P_.head.rotation.x = stil ? 0.35 : 0.3 + Math.sin(tt * 0.9) * 0.08;
      const knipper = a.sleepy || (!stil && (tt * 1000) % 3700 < 120);
      P_.eyes.forEach(e => e.scale.y = knipper ? 0.2 : 1);
      P_.g.position.y = lig ? 0.68 + (stil ? 0 : Math.sin(tt * 1.6) * 0.015) : 0.06 + (loopt ? Math.abs(Math.sin(tt * 11)) * 0.05 : 0);
    }
    function stilBeeld() {      // prefers-reduced-motion: iedereen meteen op zijn plek, in een vaste houding
      SPOTS.forEach(sp => sp.occ = null);
      const nacht = bedtijdVan(uur()), volg = nacht ? BEDDEN : [PLEK.bank1, PLEK.koffie, PLEK.pingL, PLEK.pingR, PLEK.bank2, PLEK.koek];
      let k = 0;
      IDS.forEach(id => { const a = W[id], pos = a.p.g.position; a.path = []; a.spot = null;
        a.typing = a.wave = a.sleepy = a.pong = a.shrug = a.coffee = false;
        if (a.s === "slaapt") { const sp = volg[k++]; pos.x = sp.x; pos.z = sp.z; a.at = sp.kind; a.face = sp.face; a.spot = sp; sp.occ = id;
          a.mode = sp.lie ? "lie" : sp.sit ? "sit" : "stand"; a.sleepy = sp.kind === "bed" || sp.kind === "bank"; a.pong = sp.kind === "ping"; a.coffee = sp.kind === "koffie" || sp.kind === "koek"; }
        else { const d = bureauDoel(a); pos.x = d.x; pos.z = d.z; a.at = a.s; a.face = d.face; a.mode = d.sit ? "sit" : "stand";
          a.typing = a.s === "werkt"; a.wave = a.s === "aandacht"; a.shrug = a.s === "leeg"; }
      });
      const lijst = IDS.map(id => W[id]).filter(a => a.s === "aandacht");
      chef.path = []; chef.mode = "stand";
      if (lijst.length) { const d = bureauDoel(lijst[0]); chef.target = lijst[0]; chef.p.g.position.set(d.x + 1.3, 0.06, d.z + 1.5); chef.face = -2.45; chef.at = "bij"; }
      else { chef.target = null; chef.p.g.position.set(PLEK.maquette.x + 0.6, 0.06, PLEK.maquette.z); chef.face = Math.PI; chef.at = "maquette"; }
      chef.typing = chef.wave = chef.sleepy = chef.pong = chef.shrug = chef.coffee = false;
      teken();
    }

    // -------------------------------------------------------- beeld en overlay
    let B = 1, H = 1;
    function maat() {
      const w = sceneEl.clientWidth, h = sceneEl.clientHeight; if (!w || !h) return false;
      B = w; H = h; smal = w < 560; root.classList.toggle("pk-smal", smal);
      renderer.setSize(w, h, false);
      // De camera is afgesteld op 1,45 : 1 (smal 1 : 1). Is de scène breder, omdat haar hoogte
      // begrensd is (VA-64 crit. 13), dan kijkt ze breder in plaats van boven en onder af te snijden.
      const r0 = smal ? 1 : 1.45;
      let halfW = TOTAL / 2 + (smal ? 0.5 : 2.2), halfH = halfW * h / w;
      if (w / h > r0) { halfH = halfW / r0; halfW = halfH * w / h; }
      Object.assign(cam, {left: -halfW, right: halfW, top: halfH, bottom: -halfH}); cam.updateProjectionMatrix();
      root.style.setProperty("--pk-bel-max", Math.round(w * .19) + "px");
      ACT.forEach(a => { el[a.id].hit.tabIndex = smal ? -1 : 0; });
      return true;
    }
    const v3 = new T.Vector3();
    const naarScherm = (x, y, z) => { v3.set(x, y, z).project(cam); return [(v3.x + 1) / 2 * B, (1 - v3.y) / 2 * H]; };
    const zetPx = (e, [x, y]) => { e.style.left = x.toFixed(1) + "px"; e.style.top = y.toFixed(1) + "px"; };
    const binnen = (e, x, links) => { const w = e.offsetWidth, lo = links ? 2 : w / 2 + 2, hi = links ? B - w - 2 : B - w / 2 - 2;   // nooit afgesneden aan de rand
      e.style.left = Math.max(lo, Math.min(hi, x)).toFixed(1) + "px"; };
    function overlay(t) {
      const eenheid = B / (cam.right - cam.left), bellen = [];
      ACT.forEach(a => {
        const e = el[a.id], pos = a.p.g.position, lig = a.mode === "lie";
        const kop = lig ? naarScherm(pos.x, 1.5, pos.z - 1.4) : naarScherm(pos.x, pos.y + 2.05, pos.z);
        const naamP = lig ? naarScherm(pos.x, 0.3, pos.z + 0.35) : naarScherm(pos.x, 0, pos.z + 0.45);
        zetPx(e.naam, naamP); binnen(e.naam, naamP[0], false);
        const mid = lig ? naarScherm(pos.x, 0.8, pos.z - 0.8) : naarScherm(pos.x, pos.y + 0.95, pos.z);
        zetPx(e.hit, mid);
        e.hit.style.width = Math.max(30, (lig ? 1.0 : 0.85) * eenheid) + "px"; e.hit.style.height = Math.max(40, (lig ? 1.4 : 1.95) * eenheid) + "px";
        if (a === chef) { const tgt = chef.target && chef.target.s === "aandacht" ? chef.target : null;
          const tekst = tgt ? (chefTekst().bel[tgt.id] || "") : "";
          if (e.tekst !== tekst) { e.tekst = tekst; e.bel.textContent = tekst; } e.bel.hidden = !tekst || smal; e.bel.className = "pk-bel chef";
          if (tekst) zetPx(e.bel, kop);
          return; }
        if (!smal) bellen.push([e.bel, kop]);
        const zz = a.sleepy && !smal; e.z.hidden = !zz;
        if (zz) { e.z.textContent = stil ? "z z" : ["z", "z z", "z z z"][Math.floor(t / 700) % 3]; zetPx(e.z, lig ? naarScherm(pos.x + 0.5, 1.2, pos.z - 1.0) : naarScherm(pos.x + 0.55, pos.y + 1.75, pos.z)); }
      });
      // ballonnen die elkaar raken schuiven omhoog
      bellen.forEach(([b, p]) => { b.style.left = p[0].toFixed(1) + "px"; b._y = p[1]; b._x = p[0]; });
      const maten = bellen.map(([b]) => [b, b.offsetWidth, b.offsetHeight]);
      maten.sort((a, b) => b[0]._y - a[0]._y);
      for (let i = 0; i < maten.length; i++) for (let j = 0; j < i; j++) {
        const [bi, wi, hi] = maten[i], [bj, wj, hj] = maten[j];
        if (Math.abs(bi._x - bj._x) < (wi + wj) / 2 + 4 && bi._y > bj._y - hj - 4) bi._y = bj._y - hj - 6;
      }
      maten.forEach(([b]) => { b.style.top = b._y.toFixed(1) + "px"; if (b.offsetWidth) binnen(b, b._x, false); });
      borden.forEach(([b, r]) => { const p = r.z0 === BACK ? naarScherm(r.x0 + 0.3, 3.3, BACK) : naarScherm(r.x0 + 0.3, -0.2, FRONT + 0.3); zetPx(b, p); binnen(b, p[0], true); });
      const sel = gekozen && ACT.find(a => a.id === gekozen);
      ring.visible = !!sel; if (sel) { const p = sel.p.g.position; ring.position.set(p.x, 0.08, sel.mode === "lie" ? p.z - 0.9 : p.z); }
    }
    function teken(t = performance.now()) {
      if (!B || B < 2) return;
      cam.position.set(CAM_BASE.x + (stil ? 0 : Math.sin(t / 9000) * 0.8), CAM_BASE.y, CAM_BASE.z + (stil ? 0 : Math.cos(t / 11000) * 0.4));
      cam.lookAt(KIJK); cam.updateMatrixWorld(); plaatsDecor();
      if (stil) ACT.forEach(a => houding(a, 0, 0));
      overlay(t);
      renderer.render(scene, cam);
    }
    let laatst = performance.now(), raf = 0;
    function lus(t) {
      raf = 0; if (stil || root.hidden || document.hidden) return;
      const dt = Math.max(0, Math.min(0.25, (t - laatst) / 1000)); laatst = t;
      dagdeel(); twinkelen(t);
      wieken.rotation.z = -t / 2600;
      planten.forEach((p, i) => { p.rotation.z = Math.sin(t / 1300 + i) * 0.04; });
      IDS.forEach(id => { const a = W[id]; denk(a, t); houding(a, dt, t);
        const kl = schermKl[id], s = a.screen.color;
        if (a.s === "werkt" && a.at === "werkt") s.set(kl[Math.floor(t / 700 + a.seed) % kl.length]);
        else if (a.s === "aandacht") s.set(Math.floor(t / 300) % 2 ? V.s4 : mix(V.s4, V.bruin, .45));
        else if (a.s === "leeg") s.set(mix(V.grijs, V.scherm, .4)); else s.set(V.schermUit); });
      denkChef(t); houding(chef, dt, t);
      leds.forEach(l => l.m.color.set(W.ingest.s === "werkt" ? ((Math.floor(t / 180) + l.i * 7) % 5 ? V.s1 : V.good)
        : W.ingest.s === "aandacht" ? (Math.floor(t / 400) % 2 ? V.s4 : V.donker2) : W.ingest.s === "slaapt" ? (l.i % 4 ? V.donker2 : V.good) : V.donker2));
      bronLed.color.set(W.verrijking.s === "werkt" ? V.good : W.verrijking.s === "aandacht" ? (Math.floor(t / 400) % 2 ? V.s4 : V.donker2) : V.grijs2);
      bedden(); pingpong(t);
      teken(t);
      raf = requestAnimationFrame(lus);
    }
    function bedden() { BEDDEN.forEach(b => { const a = b.occ && W[b.occ], in_ = a && a.mode === "lie";
      b.deken.position.y = in_ ? 0.95 : 0.6; b.deken.scale.z = in_ ? 1.25 : 1; b.deken.position.z = in_ ? b.z - 0.65 : b.z - 0.55; }); }
    function pingpong(t) {
      const aan = pong.every(sp => sp.occ && W[sp.occ] && W[sp.occ].at === "ping"); bal.visible = aan;
      if (aan) { const ph = stil ? 0.5 : (t / 700) % 2, f = ph < 1 ? ph : 2 - ph;
        bal.position.set(pong[0].x + 0.35 + f * (pong[1].x - pong[0].x - 0.7), 0.9 + Math.sin(Math.PI * (ph % 1)) * 0.55, ptz + (stil ? 0 : Math.sin(t / 900) * 0.3)); }
    }
    function stilStatisch() {   // schermen, lampjes, bedden en bal in hun vaste stand
      IDS.forEach(id => { const a = W[id], kl = schermKl[id];
        a.screen.color.set(a.s === "werkt" ? kl[0] : a.s === "aandacht" ? V.s4 : a.s === "leeg" ? mix(V.grijs, V.scherm, .4) : V.schermUit); });
      leds.forEach(l => l.m.color.set(W.ingest.s === "werkt" ? (l.i % 5 ? V.s1 : V.good) : W.ingest.s === "aandacht" ? V.s4 : W.ingest.s === "slaapt" ? (l.i % 4 ? V.donker2 : V.good) : V.donker2));
      bronLed.color.set(W.verrijking.s === "werkt" ? V.good : W.verrijking.s === "aandacht" ? V.s4 : V.grijs2);
      wieken.rotation.z = 0.35; bedden(); pingpong(0);
    }
    function speel() { if (!raf && !stil) { laatst = performance.now(); raf = requestAnimationFrame(lus); } }

    function herkleur() { P = PK.palet(root); thema.forEach(([m, f]) => m.color.set(f(P))); if (deel) lichten(); if (stil) teken(); }
    new ResizeObserver(() => { if (maat()) { if (stil) teken(); } }).observe(sceneEl);
    new MutationObserver(herkleur).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", herkleur);
    rm.addEventListener("change", () => api.stil(rm.matches));
    document.addEventListener("visibilitychange", speel);

    const api = {
      zet: (d, f) => { zet(d, f); if (stil) { stilStatisch(); stilBeeld(); } }, kies: id => kies(id, id && el[id] ? (smal ? el[id].knop : el[id].hit) : null),
      stil(aan) { stil = !!aan; root.classList.toggle("pk-stil", stil);
        if (stil) { dagdeel(true); stilStatisch(); stilBeeld(); } else { SPOTS.forEach(sp => sp.occ = null); IDS.forEach(id => { const a = W[id]; a.spot = null; a.at = null; a.wait = 0; if (a.mode !== "walk") a.mode = "stand"; }); chef.retarget = 0; speel(); } },
      uur(u) { uurVast = u == null || u === "" ? null : +u; dagdeel(true); IDS.forEach(id => { W[id].wait = 0; }); if (stil) { stilStatisch(); stilBeeld(); } },
      is3d: true,
    };
    root.classList.toggle("pk-stil", stil);
    maat(); dagdeel(true); zet(data);
    if (stil) { stilStatisch(); stilBeeld(); } else speel();
    return api;
  }
  return {start};
})();

// Eén start voor het dashboard: 3D als het kan, anders het 2D-pixelkantoor met een noot.
function kantoorStart(root, data, opties = {}) {
  let gl = false;
  try { gl = !!document.createElement("canvas").getContext("webgl"); } catch (e) { gl = false; }
  if (window.THREE && gl && !opties.forceer2d) {
    const scene = root.querySelector(".pk-scene"), schoon = scene.cloneNode(true);
    try { PK3D = PK3D || bouwPK3D(); return PK3D.start(root, data, opties); }
    catch (e) { gl = false; scene.replaceWith(schoon); }  // half gebouwd 3D eerst weg
  }
  root.querySelector(".pk-scene").classList.remove("pk-start");   // het 2D-canvas bepaalt zijn eigen hoogte
  const noot = document.createElement("div"); noot.className = "pk-noot";
  noot.textContent = window.THREE ? TEKST3D.geenWebGL : TEKST3D.geenThree;
  if (!opties.forceer2d) root.querySelector(".pk-voet").appendChild(noot);
  return PK.start(root, data, opties);
}
/* =============================== EINDE KANTOOR3D =============================== */

/* Kantoor in het dashboard (VA-31): het blok PAYLOAD.kantoor uit bouw_payload().
   #pk is het aanhaakpunt; toestand en zinnen komen uit PAYLOAD.kantoor.tekst, nooit met de hand.
   Het kantoor is altijd zichtbaar: er is geen knop om het weg te halen (Ayman, VA-31-review). */
(() => {  // VA-60: three.js r128 (cdnjs, integrity) laadt los; hangt cdnjs, dan na 4 s het 2D-kantoor.
  const pk = document.getElementById("pk"); let gestart = false;
  const start = () => { if (gestart) return; gestart = true; kantoorStart(pk, PAYLOAD.kantoor); };
  const s = document.createElement("script");
  s.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
  s.integrity = "sha512-dLxUelApnYxpLt6K2iomGngnHO83iUvZytA3YjDUCjT0HDOHKXnVYdf3hU4JjM8uEhxf9nD1/ey98U3t2vZ0qQ==";
  s.crossOrigin = "anonymous"; s.referrerPolicy = "no-referrer";
  s.onload = start; s.onerror = start; setTimeout(start, 4000);
  document.head.appendChild(s);
})();
</script>
</body>
</html>
"""


def zonder_css_uitleg(t: str) -> str:
    """
    Het sjabloon zonder de /* uitleg */ in zijn <style> (VA-105). De uitleg blijft in de bron staan; de pagina
    blijft zo onder 1 MB (VA-39 crit. 5), en er verandert niets wat de browser toont. Het CSS heeft geen tekst
    tussen aanhalingstekens met '/*' erin; een test bewaakt dat.
    """
    i, j = t.index("<style>"), t.index("</style>")
    return t[:i] + re.sub(r"[ \t]*/\*.*?\*/[ \t]*\n?", "", t[i:j], flags=re.S) + t[j:]


def render(payload: dict) -> str:
    """Vul het sjabloon. De payload als laatste, zodat zijn inhoud niet wordt vervangen."""
    payload = {**payload, "kaartfoto": payload.get("kaartfoto") or kaartfoto_tekst(),  # elke kaart (VA-71)
               "bewaar": payload.get("bewaar") or bewaar_blok([])}  # elke kaart en elk pand (VA-90)
    tip = payload["peildatum_tip"]
    # Zonder 'pagina' (een payload van vóór VA-39, of een test) de teksten van een gebied als Delft.
    pg = payload.get("pagina") or pagina(
        "proefresultaat", f"Levrai · Pandenselectie Dashboard — {payload['gebied']}", "Proefselectie in cijfers",
        "De 20 hoogst scorende panden — de controlevraag uit de briefing", BRON_PIL)
    lijst = pg["lijst"]
    naam = next(n for g in menu_voor(lijst) for d, n in g["items"] if d == lijst)
    band = band_html(payload.get("kaart"))
    html = (zonder_css_uitleg(TEMPLATE)
            .replace("__TITEL__", escape(pg["titel"]))
            .replace("__LABEL__", payload["gebied"])
            .replace("__PEILDATUM__", escape(payload["peildatum"]))
            .replace("__PEILTIP__", f' data-tip="{escape(tip)}"' if tip else "")
            .replace("__BRONPIL__", escape(pg["bronpil"]))
            .replace("__FEITEN_TITEL__", escape(pg["feiten.titel"]))
            .replace("__FEITEN_CAP__", escape(pg["feiten.cap"]))
            .replace("__LIJST_NAAM__", escape(naam))
            .replace("__LIJST__", lijst)
            .replace("__FILTER__", filter_html(payload.get("filter"), KAARTFOTO_TEKST["bron"]))
            .replace("__MENU__", menu_html(lijst))
            .replace("__BEWAARD__", bewaard_html(lijst))
            .replace("__PLANNING__", planning_paneel(payload.get("planning")))
            .replace("__SLOT__", slot_html(payload.get("slot")))
            .replace("__BAND__", band[0]).replace("__TRAP__", band[1]).replace("__KAART__", band[2])
            .replace("__WERKBALK__", werkbalk_html((payload.get("kantoor") or {}).get("tekst"))))
    # De koppen van het lijstdeel ('proefresultaat.*' of 'werklijst.*') gaan naar __KOP_LIJST_*__.
    for sleutel, tekst in (payload.get("koppen") or koppen(payload["gebied"], None, None)).items():
        deel, _, rest = sleutel.partition(".")
        plek = f"lijst.{rest}" if deel == lijst else sleutel
        html = html.replace("__KOP_" + plek.upper().replace(".", "_") + "__", escape(tekst))
    # De waarschuwingen van de planning zijn voor wie bouwt, niet voor de pagina.
    payload = {k: v for k, v in payload.items() if k != "planning_waarschuwingen"}
    return html.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))


def main() -> int:
    payload = bouw_payload()
    OUT.write_text(render(payload), encoding="utf-8")
    print(f"dashboard geschreven -> {OUT.relative_to(BASE)} ({OUT.stat().st_size/1024:.1f} KB)")
    for regel in payload.get("planning_waarschuwingen") or []:
        print(f"LET OP: {regel}")
    if payload["bron"] is None:
        print(f"Snapshot: {BRON_ONBEKEND} ({payload['bron_reden']})")
    else:
        for regel in payload["bron_regels"]:
            print(f"Snapshot {regel}")
    if payload["leads"]:
        print(f"leads: {len(payload['leads'])}, score-index "
              f"{min(l['s100'] for l in payload['leads'])}–{max(l['s100'] for l in payload['leads'])}")
    else:
        print("leads: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
