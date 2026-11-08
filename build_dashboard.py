"""
Levrai Group - Pandenselectiesysteem
Bouwt het dashboard (design/index.html) data-gedreven uit panden_delft.json.

Draai na run_proef.py. Genereert een zelfstandige HTML met ingesloten payload,
zodat de pagina ook als statische snapshot (Claude Design) werkt zonder fetch.

Welke BAG-snapshot(s) het resultaat voeden staat in data/panden_<gebied>.bron.json,
geschreven door run_proef.py. Het dashboard meldt die op scherm en in de pagina; ontbreekt
het bestand, dan staat er dat de bron onbekend is.
"""
from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

from gebieden import resolve, slug
from selectie import load_config

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT = BASE / "design" / "index.html"

MAANDEN = ("jan", "feb", "mrt", "apr", "mei", "jun",
           "jul", "aug", "sep", "okt", "nov", "dec")
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
                     "werklijst_max": drempels.get("werklijst_max")},
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
    uitleg = (f"Ingest haalt alle verblijfsobjecten van {g} op uit de BAG, via de open PDOK-dienst. "
              "Elke ophaling blijft bewaard als eigen, gedateerde momentopname, zodat je altijd ziet "
              "uit welke ophaling een cijfer komt.")
    if s == "werkt":
        o = opgehaald(d["bron"])
        return (f"BAG opgehaald {o['kort']}",
                f"Ingest heeft de BAG van {g} opgehaald {o['zin']}: {nl_getal(d.get('vbo'))} verblijfsobjecten.",
                uitleg)
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
    uitleg = (f"Selectie groepeert de verblijfsobjecten per BAG-pand, sluit panden uit die buiten de "
              f"briefing vallen, deelt de rest in categorie A–E in en geeft elk pand een leadscore. Van de "
              f"{nl_getal(d.get('panden'))} panden in {g} vallen er {nl_getal(d.get('a_e'))} in A–E; {w} halen "
              f"score {dr} of hoger.")
    if s == "werkt":
        return (f"{w} panden op de werklijst",
                f"Selectie heeft {nl_getal(d.get('a_e'))} panden in categorie A–E gescoord. {w} halen score "
                f"{dr} of hoger en staan op de werklijst.", uitleg)
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
    uitleg = (f"Controle zet de {tot} hoogst scorende panden klaar voor je visuele controle. Bekijk elk "
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
    return uit


def bouw_payload() -> dict:
    cfg = load_config()
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
        return f"{n:,}".replace(",", ".") if gelezen is not None else "onbekend"

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

    labels = {"A": "Winkel + wonen", "B": "Bedrijf/kantoor + wonen",
              "C": "Klein wooncomplex", "D": "Groot oud pand", "E": "Afwijkende combinatie"}
    slot = {"A": "var(--s1)", "B": "var(--s2)", "C": "var(--s3)", "D": "var(--s4)", "E": "var(--s5)"}
    cats = [{"k": k, "name": labels[k], "n": sum(1 for p in act if k in p["categorieen"]),
             "c": slot[k]} for k in "ABCDE"]

    scores = [p["score100"] for p in top]
    bjs = [p["bouwjaar"] for p in top]
    # Zonder panden in de proefselectie bestaat geen bereik of gemiddelde: 'onbekend'.
    facts = [
        {"k": "Panden in proefselectie", "val": str(len(top)) if gelezen is not None else "onbekend"},
        {"k": "Score-index (/100)", "val": f"{min(scores)}–{max(scores)}" if top else "onbekend"},
        {"k": "Bouwjaren", "val": f"{min(bjs)}–{max(bjs)}" if top else "onbekend"},
        {"k": "Oudste pand", "val": str(min(bjs)) if top else "onbekend"},
        {"k": "Gem. oppervlakte",
         "val": f"{round(sum(p['totale_oppervlakte'] for p in top) / len(top))} m²" if top else "onbekend"},
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

    # Korte tags voor de kwalificatie-signalen die de gebruiker belangrijk vindt.
    # 'kind' stuurt de kleur: leeg = opvallend (amber), rest = groen.
    qual_tag = {
        "Buiten gebruik / leegstaand": ("🏚 leegstaand", "leeg"),
        "In verbouwing": ("🔧 in verbouwing", "bouw"),
        "Slecht of ontbrekend energielabel": ("⚡ slechte staat", "ok"),
    }

    leads = []
    for p in top:
        f = {k: round(v) for k, v in p["opp_per_functie"].items() if v}
        sig = [{"t": qual_tag[it["label"]][0], "k": qual_tag[it["label"]][1], "d": it["detail"]}
               for it in p["score_opbouw"] if it["label"] in qual_tag and it["behaald"]]
        leads.append({
            "a": p["hoofdadres"].split(",")[0],
            "p": p["postcode"],
            "id": p["bag_pand_id"],
            "bj": p["bouwjaar"],
            "m2": round(p["totale_oppervlakte"]),
            "vbo": p["aantal_vbo"],
            "adr": p["aantal_adressen"],
            "won": p["aantal_per_functie"].get("woon", 0),
            "cat": p["categorieen"],
            "f": f,
            "wp": p.get("woonplaats", ""),
            "s100": p["score100"],
            "raw": p["leadscore"],
            "sig": sig,
            "opbouw": p["score_opbouw"],
        })

    budget = cfg["score"].get("schaal_max", 26)
    return {"kpi": kpi, "cats": cats, "facts": facts, "leads": leads,
            "budget": budget, "gebied": label,
            "bron": bron, "bron_regels": bron_regels(bron), "bron_reden": bron_reden,
            "peildatum": peildatum(bron), "peildatum_tip": peildatum_tip(bron, bron_reden),
            "kantoor": kantoor(label, bron, gelezen, len(leads) if gelezen is not None else None,
                               cfg)}


TEMPLATE = r"""<!-- @dsCard group="Levrai VASTGOED" name="Pandenselectie dashboard" subtitle="__LABEL__ · 20-pand proefresultaat met score-opbouw" -->
<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Levrai · Pandenselectie Dashboard — __LABEL__</title>
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

  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.45}
  a{color:inherit}
  .wrap{max-width:1160px;margin:0 auto;padding:22px 22px 64px}

  .top{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
    background:var(--brand);color:#fff;border-radius:16px;padding:20px 24px;box-shadow:var(--shadow)}
  .mark{font-weight:800;letter-spacing:.16em;font-size:15px}
  .mark small{display:block;letter-spacing:.28em;font-weight:600;font-size:10px;color:#9fb3cc;margin-top:3px}
  .top .sub{font-size:13px;color:#c6d3e4}
  .spacer{flex:1}
  .pill{font-size:12px;color:#c6d3e4;border:1px solid rgba(255,255,255,.18);padding:5px 11px;border-radius:999px;white-space:nowrap}
  .toggle{cursor:pointer;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);
    color:#fff;font:inherit;font-size:12px;padding:6px 12px;border-radius:999px}
  .toggle:hover{background:rgba(255,255,255,.18)}

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}
  .kpi{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow)}
  .kpi .v{font-size:30px;font-weight:750;letter-spacing:-.02em;line-height:1}
  .kpi .v.onb{font-size:22px;letter-spacing:0}
  .kpi .l{font-size:12.5px;color:var(--ink-2);margin-top:8px}
  .kpi .h{font-size:11px;color:var(--muted);margin-top:3px}
  .kpi .accent{width:26px;height:3px;border-radius:2px;margin-bottom:12px;background:var(--s1)}

  .cols{display:grid;grid-template-columns:1.35fr 1fr;gap:14px;margin-top:14px}
  .panel{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}
  .panel h2{margin:0 0 4px;font-size:14px;font-weight:700}
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

  .sec-h{display:flex;align-items:baseline;gap:10px;margin:26px 2px 12px}
  .sec-h h2{margin:0;font-size:15px}
  .sec-h span{font-size:12px;color:var(--muted)}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
  .card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:16px 17px;
    box-shadow:var(--shadow);display:flex;flex-direction:column;gap:11px}
  .card .rowtop{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
  .card .addr{font-size:14.5px;font-weight:700;letter-spacing:-.01em}
  .card .lid{font-size:11px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}
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
  .pk{margin-top:18px;background:var(--surface);border:1px solid var(--ring);border-radius:14px;
    box-shadow:var(--shadow);overflow:hidden}
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
    border-top:1px solid var(--grid);font-size:11.5px;color:var(--muted)}
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

  @media(max-width:900px){
    .kpis{grid-template-columns:repeat(2,1fr)}
    .cols{grid-template-columns:1fr}
    .grid{grid-template-columns:1fr}
    .bar{grid-template-columns:120px 1fr}
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="mark">LEVRAI GROUP<small>VASTGOED</small></div>
    <div class="sub">Pandenselectie&nbsp;·&nbsp;__LABEL__</div>
    <div class="spacer"></div>
    <div class="pill">Bron: PDOK BAG WFS v2_0</div>
    <div class="pill"__PEILTIP__>__PEILDATUM__</div>
    <button class="toggle" id="themeBtn" type="button">◐ Thema</button>
  </header>

  <section class="pk" id="pk" aria-label="Kantoor">
    <div class="pk-scene">
      <canvas aria-hidden="true"></canvas>
      <div class="pk-ov"></div>
    </div>
    <div class="pk-uitleg" hidden aria-live="polite">
      <h3></h3>
      <p class="pk-status"></p>
      <p class="pk-tekst"></p>
      <button class="pk-sluit" type="button">Sluit uitleg</button>
    </div>
    <div class="pk-voet">Elke medewerker is een stap van de pandenselectie. Wat ze zeggen, komt uit de cijfers van dit dashboard. Klik op een medewerker voor uitleg.</div>
  </section>

  <section class="kpis" id="kpis"></section>

  <div class="cols">
    <div class="panel">
      <h2>Technische voorraad naar categorie</h2>
      <p class="cap">__LABEL__ · panden binnen categorie A–E · een pand kan in meerdere vallen</p>
      <div id="cats"></div>
    </div>
    <div class="panel">
      <h2>Proefselectie in cijfers</h2>
      <p class="cap">De 20 hoogst scorende panden — de controlevraag uit de briefing</p>
      <div class="facts" id="facts"></div>
      <p class="note">Score is een <b>index van 1–100</b> tegen het volledige modelbudget.
        Open een pand voor de volledige score-opbouw per criterium.</p>
    </div>
  </div>

  <div class="sec-h">
    <h2>Proefresultaat — 20 panden</h2>
    <span id="secmeta"></span>
  </div>
  <div class="grid" id="leads"></div>

  <p class="foothint">
    Klik op <b>Score-opbouw</b> in een pand om te zien waar elk punt vandaan komt ·
    grijze criteria wachten op een extra databron (energielabel, verkoophistorie, leegstand).
  </p>
</div>
<div id="tt"></div>

<script>
const PAYLOAD = __PAYLOAD__;
const {kpi:KPI, cats:CATS, facts:FACTS, leads:LEADS, budget:BUDGET} = PAYLOAD;
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

function opbouwHTML(d){
  const cls={behaald:"ok",niet:"miss",aftrek:"neg",inactief:"off"};
  const ic={behaald:"✓",niet:"✕",aftrek:"▼",inactief:"○"};
  const rows=d.opbouw.map(it=>{
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

document.getElementById("secmeta").textContent=`${LEADS.length} panden · ${PAYLOAD.gebied} · gesorteerd op score-index`;
const lb=document.getElementById("leads");
LEADS.forEach(d=>{
  const order=["woon","winkel","kantoor","bedrijf","overig"];
  const segs=order.filter(k=>d.f[k]).map(k=>
    `<i data-tip="${FNL[k]}: ${d.f[k]} m²" style="flex:${d.f[k]};background:${FN[k]}"></i>`).join("");
  const leg=order.filter(k=>d.f[k]).map(k=>
    `<span><i class="dot" style="background:${FN[k]}"></i>${FNL[k]} ${d.f[k]} m²</span>`).join("");
  const chips=d.cat.map(c=>`<span class="chip c${c}">${c}</span>`).join("");
  const sigtags=d.sig.map(s=>`<span class="sigtag ${s.k}" data-tip="${s.d}">${s.t}</span>`).join("");
  const card=el("div","card");
  card.innerHTML=`
    <div class="rowtop">
      <div><div class="addr">${d.a}</div>
        <div class="lid">${d.p} ${d.wp} · BAG ${d.id}</div></div>
      <div class="score"><b>${d.s100}</b><small>/100</small></div>
    </div>
    <div class="meter"><i style="width:0" data-w="${d.s100}"></i></div>
    <div class="chips">${chips}</div>
    ${sigtags?`<div class="sigtags">${sigtags}</div>`:""}
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
  lb.appendChild(card);
  const m=card.querySelector(".meter i");
  requestAnimationFrame(()=>{m.style.width=m.dataset.w+"%";});
});

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
        // daken van Delft achter het raam: trapgevels
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
    const M = {}, el = {};
    IDS.forEach((id, i) => {
      M[id] = {id, x: 0, y: 0, toestand: "leeg", seed: i * 977 + 311, gekozen: false};
      const bel = document.createElement("div"), naam = document.createElement("div"), hit = document.createElement("button");
      bel.className = "pk-bel"; naam.className = "pk-naam"; hit.className = "pk-hit"; hit.type = "button";
      naam.innerHTML = `<b>${i + 1}</b>${NAMEN[id][0]}`;
      hit.onclick = bel.onclick = () => kies(gekozen === id ? null : id);
      ov.append(bel, naam, hit); el[id] = {bel, naam, hit};
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
      gekozen = id; IDS.forEach(k => { M[k].gekozen = k === id; el[k].hit.setAttribute("aria-expanded", String(k === id)); });
      uitleg.hidden = !id; if (id) toonUitleg(id);
      if (stil) teken(performance.now());
    }
    uitleg.querySelector(".pk-sluit").onclick = () => { const was = gekozen; kies(null); if (was) el[was].hit.focus(); };
    document.addEventListener("keydown", e => { if (e.key === "Escape" && gekozen) { const was = gekozen; kies(null); el[was].hit.focus(); } }); // VA-31: Escape sluit de uitleg

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

/* Kantoor in het dashboard (VA-31): het blok PAYLOAD.kantoor uit bouw_payload().
   #pk is het aanhaakpunt; toestand en zinnen komen uit PAYLOAD.kantoor.tekst, nooit met de hand.
   Het kantoor is altijd zichtbaar: er is geen knop om het te verbergen (Ayman, VA-31-review). */
PK.start(document.getElementById("pk"), PAYLOAD.kantoor);
</script>
</body>
</html>
"""


def render(payload: dict) -> str:
    """Vul het sjabloon. De payload als laatste, zodat zijn inhoud niet wordt vervangen."""
    tip = payload["peildatum_tip"]
    return (TEMPLATE
            .replace("__LABEL__", payload["gebied"])
            .replace("__PEILDATUM__", escape(payload["peildatum"]))
            .replace("__PEILTIP__", f' data-tip="{escape(tip)}"' if tip else "")
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)))


def main() -> int:
    payload = bouw_payload()
    OUT.write_text(render(payload), encoding="utf-8")
    print(f"dashboard geschreven -> {OUT.relative_to(BASE)} ({OUT.stat().st_size/1024:.1f} KB)")
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
