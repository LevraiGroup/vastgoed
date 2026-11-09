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
LUCHTFOTO_HALF_M = 40  # 80 m breed: pand en straat zichtbaar (VA-62 crit. 1: 50-150 m)


def pand_locatie(p: dict) -> dict | None:
    """Luchtfoto-URL en links voor een pand met bruikbare x,y; anders None (VA-62 crit. 7)."""
    x, y = p.get("x"), p.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not x or not y:
        return None
    breedte, lengte = rd_naar_wgs84(x, y)
    h = LUCHTFOTO_HALF_M
    foto = (f"{LUCHTFOTO_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=Actueel_orthoHR"
            f"&STYLES=&CRS=EPSG:28992&BBOX={x - h:.1f},{y - h:.1f},{x + h:.1f},{y + h:.1f}"
            f"&WIDTH=640&HEIGHT=640&FORMAT=image/jpeg")
    return {"lat": breedte, "lon": lengte, "foto": foto,
            "maps": f"https://www.google.com/maps/search/?api=1&query={breedte},{lengte}",
            "streetview": ("https://www.google.com/maps/@?api=1&map_action=pano"
                           f"&viewpoint={breedte},{lengte}")}


def pand_detail(p: dict) -> dict:
    """Alles voor de detailweergave van één pand: elk veld als Nederlandse tekst, plus locatie."""
    rijen = []
    for veld, label, soort in PAND_VELDEN:
        waarde = pand_waarde(soort, p.get(veld))
        if waarde is not None:
            rijen.append({"k": label, "v": waarde})
    return {"titel": p.get("hoofdadres") or LEEG, "rijen": rijen, "locatie": pand_locatie(p)}


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
            "detail": pand_detail(p),  # VA-61/62: alle velden, luchtfoto en kaartlinks
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
  /* =====================================================================
     KANTOOR3D — dit blok gaat mee naar build_dashboard.py (na het PIXELKANTOOR-blok)
     ===================================================================== */
  .pk-scene.pk-3d{aspect-ratio:1.45/1;min-height:240px;overflow:hidden;background:var(--surface-2)}
  .pk-smal .pk-scene.pk-3d{aspect-ratio:1/1}
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
  .pk-smal .pk-3d .pk-naam{font-size:0;padding:0 5px}   /* smal: alleen het nummer; de namen staan in de lijst eronder */
  .pk-smal .pk-3d .pk-naam b{font-size:10px;margin:0}
  .pk-smal .pk-3d .pk-naam.chef{display:none}
  .pk-smal .pk-3d .pk-naam.aandacht{background:color-mix(in srgb,var(--s4) 30%,var(--surface));border-color:var(--s4);color:var(--ink)}
  .pk-smal .pk-3d .pk-bord{font-size:7px;letter-spacing:.06em;padding:1px 4px}
  .pk-lijst{display:none;list-style:none;margin:0;padding:8px 10px 4px;gap:4px;border-top:1px solid var(--grid)}
  .pk-smal .pk-lijst{display:grid}
  .pk-lijst button{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;align-items:baseline;width:100%;text-align:left;
    font:inherit;font-size:12px;color:var(--ink);background:none;border:0;border-radius:8px;padding:5px 6px;cursor:pointer}
  .pk-lijst button:hover{background:var(--grid)}
  .pk-lijst button:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
  .pk-lijst button[aria-expanded="true"]{background:color-mix(in srgb,var(--s1) 12%,transparent)}
  .pk-lijst b{font-weight:700}
  .pk-lijst b::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--muted);transform:translateY(-1px)}
  .pk-lijst .werkt b::before{background:var(--s1)}
  .pk-lijst .aandacht b::before{background:var(--s4)}
  .pk-lijst .slaapt b::before{background:var(--baseline)}
  .pk-lijst .chef b::before{background:var(--brand)}
  .pk-lijst span{color:var(--ink-2)}
  .pk-lijst .aandacht span::before{content:"! ";color:var(--s2);font-weight:800}
  .pk-noot{flex-basis:100%;color:var(--ink-2)}
  /* ===================== einde KANTOOR3D-blok ===================== */

  @media(max-width:900px){
    .kpis{grid-template-columns:repeat(2,1fr)}
    .cols{grid-template-columns:1fr}
    .grid{grid-template-columns:1fr}
    .bar{grid-template-columns:120px 1fr}
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

/* ============================ PAND OPENEN (VA-61, VA-62) ============================
   Alle tekst en elke waarde komt kant-en-klaar uit pand_detail() in build_dashboard.py.
   Alleen-lezen: openen of sluiten schrijft niets. De luchtfoto (PDOK, open data) wordt pas
   opgevraagd als een pand opengaat, en alleen voor dat pand. */
const PAND_TEKST = {
  laden: "De luchtfoto laadt…",
  mislukt: "De luchtfoto kon niet laden. Bekijk het pand via Google Maps of Street View hieronder.",
  bron: "Luchtfoto: Beeldmateriaal.nl, via PDOK · open data (CC BY 4.0).",
  geenLocatie: "Dit pand heeft geen bekende locatie, dus er is geen luchtfoto en geen link naar Google Maps of Street View.",
  alt: a => `Luchtfoto van ${a}`,
  maps: "Open in Google Maps", sv: "Open in Street View", bag: "Open in BAG-viewer",
  open: "Open pand", openLabel: a => `Open pand: alle gegevens van ${a}`,
};
const pandDlg = document.getElementById("pand");
let pandOpener = null;
const maak = (tag, cls, tekst) => { const e = document.createElement(tag); if (cls) e.className = cls; if (tekst != null) e.textContent = tekst; return e; };
function openPand(d, opener) {
  const det = d.detail; pandOpener = opener;
  document.getElementById("pandTitel").textContent = det.titel;
  document.getElementById("pandSub").textContent = `${d.p} ${d.wp} · BAG ${d.id}`;
  document.getElementById("pandScore").innerHTML = `<b>${d.s100}</b><small>/100</small>`;
  const romp = document.getElementById("pandRomp"); romp.textContent = "";
  const loc = det.locatie;
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
  det.rijen.forEach(r => {
    const dd = maak("dd");
    if (Array.isArray(r.v)) { const ul = maak("ul"); r.v.forEach(x => ul.appendChild(maak("li", null, x))); dd.appendChild(ul); }
    else dd.textContent = r.v;
    dl.append(maak("dt", null, r.k), dd);
  });
  romp.appendChild(dl);
  const ob = maak("div", "pand-opbouw"); ob.innerHTML = opbouwHTML(d); ob.querySelector("details").open = true;
  romp.appendChild(ob);
  pandDlg.showModal(); romp.scrollTop = 0;
  document.getElementById("pandSluit").focus();
}
document.getElementById("pandSluit").addEventListener("click", () => pandDlg.close());
pandDlg.addEventListener("click", e => { if (e.target === pandDlg) pandDlg.close(); });
pandDlg.addEventListener("close", () => { if (pandOpener && pandOpener.isConnected) pandOpener.focus(); });
[...lb.children].forEach((card, i) => {
  const d = LEADS[i]; if (!d || !d.detail) return;
  card.classList.add("open-baar");
  const knop = maak("button", "pand-open", PAND_TEKST.open); knop.type = "button";
  knop.setAttribute("aria-haspopup", "dialog"); knop.setAttribute("aria-label", PAND_TEKST.openLabel(d.detail.titel));
  const voet = card.querySelector(".foot"); voet.insertBefore(knop, voet.querySelector(".status"));
  // Klik op de kaart opent het pand; de link, de score-opbouw en de knop zelf doen hun eigen ding.
  card.addEventListener("click", e => { if (e.target.closest("a, summary, details, button")) return; openPand(d, knop); });
  knop.addEventListener("click", () => openPand(d, knop));
});
/* ============================ einde PAND OPENEN ============================ */

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
  voet: "Elke medewerker is een stap van de pandenselectie. Wat ze zeggen, komt uit de cijfers van dit dashboard. De kantoormanager loopt naar wie je aandacht vraagt. Klik op iemand voor uitleg.",
  lijst: "Wat elke medewerker zegt",
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
    const lijst2 = document.createElement("ul"); lijst2.className = "pk-lijst"; lijst2.setAttribute("aria-label", TEKST3D.lijst);
    sceneEl.after(lijst2);
    ACT.forEach(a => {
      const bel = document.createElement("div"), naam = document.createElement("div"), hit = document.createElement("button"), z = document.createElement("div");
      bel.className = "pk-bel"; naam.className = "pk-naam"; hit.className = "pk-hit"; hit.type = "button"; z.className = "pk-z"; z.hidden = true;
      naam.innerHTML = a === chef ? TEKST3D.chef.naam : `<b>${a.nr}</b>${NAMEN[a.id][0]}`;
      if (a === chef) { naam.classList.add("chef"); bel.hidden = true; }
      const li = document.createElement("li"), knop = document.createElement("button"); knop.type = "button";
      knop.innerHTML = `<b></b><span></span>`; knop.querySelector("b").textContent = a === chef ? TEKST3D.chef.naam : `${a.nr} · ${NAMEN[a.id][0]}`;
      li.appendChild(knop); lijst2.appendChild(li);
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
        e.knop.className = r.s; e.knop.querySelector("span").textContent = r.bel;
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
      e.knop.className = "chef"; e.knop.querySelector("span").textContent = zin;
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
    document.addEventListener("keydown", e => { if (e.key === "Escape" && gekozen) sluit(); });

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
      const halfW = TOTAL / 2 + (smal ? 0.5 : 2.2), halfH = halfW * h / w;
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
  const noot = document.createElement("div"); noot.className = "pk-noot";
  noot.textContent = window.THREE ? TEKST3D.geenWebGL : TEKST3D.geenThree;
  if (!opties.forceer2d) root.querySelector(".pk-voet").appendChild(noot);
  return PK.start(root, data, opties);
}
/* =============================== EINDE KANTOOR3D =============================== */

/* Kantoor in het dashboard (VA-31): het blok PAYLOAD.kantoor uit bouw_payload().
   #pk is het aanhaakpunt; toestand en zinnen komen uit PAYLOAD.kantoor.tekst, nooit met de hand.
   Het kantoor is altijd zichtbaar: er is geen knop om het te verbergen (Ayman, VA-31-review). */
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
