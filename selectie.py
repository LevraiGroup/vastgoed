"""
Levrai Group - Pandenselectiesysteem
Stap 2: aggregatie per BAG-pand-ID, categorisering, uitsluitingen en leadscore.

Kern van de briefing (sectie 1): een winkel van 120 m2 plus drie woningen moet als
EEN acquisitielead verschijnen, niet als vier losse records. Daarom groeperen we
alle verblijfsobjecten op pandidentificatie.

Belangrijk detail uit de data: 'gebruiksdoel' is een meerwaardig veld. Waarden als
'winkelfunctie,woonfunctie' komen voor op een enkel VBO. Splitsen op komma is
essentieel, anders missen we juist de gemengde panden die deze opdracht zoekt.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

import snapshots
from gebieden import slug

BASE = Path(__file__).parent
DATA = BASE / "data"

# Indeling van BAG-gebruiksdoelen naar de functiegroepen uit de briefing.
FUNCTIEGROEP = {
    "woonfunctie": "woon",
    "winkelfunctie": "winkel",
    "kantoorfunctie": "kantoor",
    "industriefunctie": "bedrijf",
    "bijeenkomstfunctie": "overig",
    "logiesfunctie": "overig",
    "onderwijsfunctie": "overig",
    "gezondheidszorgfunctie": "overig",
    "sportfunctie": "overig",
    "celfunctie": "overig",
    "overige gebruiksfunctie": "overig",
}


def load_config() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def split_gebruiksdoel(waarde: str | None) -> list[str]:
    """'winkelfunctie,woonfunctie' -> ['winkelfunctie', 'woonfunctie']."""
    if not waarde:
        return []
    return [d.strip() for d in waarde.split(",") if d.strip()]


def _adres(rij: dict) -> str:
    """Bouw een leesbaar adres uit de losse BAG-velden."""
    straat = (rij.get("openbare_ruimte") or "").strip()
    nr = str(rij.get("huisnummer") or "").strip()
    letter = (rij.get("huisletter") or "").strip()
    toev = (rij.get("toevoeging") or "").strip()
    kern = f"{straat} {nr}{letter}"
    if toev:
        kern += f"-{toev}"
    pc = (rij.get("postcode") or "").strip()
    plaats = (rij.get("woonplaats") or "").strip()
    return ", ".join(p for p in (kern.strip(), f"{pc} {plaats}".strip()) if p)


def aggregeer(rows: list[dict]) -> list[dict]:
    """Groepeer verblijfsobjecten op BAG-pand-ID tot een record per pand."""
    per_pand: dict[str, list[dict]] = defaultdict(list)
    for rij in rows:
        pand_id = rij.get("pandidentificatie")
        if pand_id:
            per_pand[pand_id].append(rij)

    panden = []
    for pand_id, vbos in per_pand.items():
        opp_per_functie: dict[str, float] = defaultdict(float)
        aantal_per_functie: dict[str, int] = defaultdict(int)
        alle_doelen: set[str] = set()

        for vbo in vbos:
            doelen = split_gebruiksdoel(vbo.get("gebruiksdoel"))
            alle_doelen.update(doelen)
            opp = float(vbo.get("oppervlakte") or 0)
            groepen = {FUNCTIEGROEP.get(d, "overig") for d in doelen} or {"overig"}
            for groep in groepen:
                aantal_per_functie[groep] += 1
                # Bij meervoudig gebruiksdoel de oppervlakte evenredig verdelen,
                # zodat de som over functies gelijk blijft aan de totale oppervlakte.
                opp_per_functie[groep] += opp / len(groepen)

        adressen = sorted({_adres(v) for v in vbos if _adres(v)})
        eerste = vbos[0]

        panden.append(
            {
                "bag_pand_id": pand_id,
                "hoofdadres": adressen[0] if adressen else "",
                "gekoppelde_adressen": adressen,
                "aantal_adressen": len(adressen),
                "woonplaats": eerste.get("woonplaats") or "",
                "postcode": eerste.get("postcode") or "",
                "huisnummer": eerste.get("huisnummer"),
                "huisletter": eerste.get("huisletter") or "",
                "bouwjaar": int(eerste.get("bouwjaar") or 0),
                "pandstatus": eerste.get("pandstatus") or "",
                "vbo_ids": sorted(v.get("identificatie", "") for v in vbos),
                "aantal_vbo": len(vbos),
                "gebruiksdoelen": sorted(alle_doelen),
                "opp_per_functie": {k: round(opp_per_functie[k], 1) for k in sorted(opp_per_functie)},
                "aantal_per_functie": {k: aantal_per_functie[k] for k in sorted(aantal_per_functie)},
                "totale_oppervlakte": round(sum(float(v.get("oppervlakte") or 0) for v in vbos), 1),
                "x": eerste.get("_x"),
                "y": eerste.get("_y"),
                "vbo_statussen": sorted({v.get("status", "") for v in vbos}),
            }
        )

    return panden


def _n(pand: dict, groep: str) -> int:
    return pand["aantal_per_functie"].get(groep, 0)


def categoriseer(pand: dict, cfg: dict) -> list[str]:
    """Bepaal alle categorieen (A-E) waar een pand technisch in valt."""
    c = cfg["categorieen"]
    opp = pand["totale_oppervlakte"]
    bj = pand["bouwjaar"]
    n_vbo = pand["aantal_vbo"]
    n_adres = pand["aantal_adressen"]
    woon, winkel, kantoor, bedrijf, overig = (
        _n(pand, "woon"), _n(pand, "winkel"), _n(pand, "kantoor"),
        _n(pand, "bedrijf"), _n(pand, "overig"),
    )
    cats: list[str] = []

    a = c["A_winkel_wonen"]
    if (winkel >= a["min_winkel"] and woon >= a["min_woon"] and n_vbo >= a["min_vbo"]
            and a["opp_min"] <= opp <= a["opp_max"] and 0 < bj < a["bouwjaar_voor"]):
        cats.append("A")

    b = c["B_bedrijf_kantoor_wonen"]
    # Alleen kantoor/bedrijf telt; 'overig' (vaak berging) is te zwak signaal,
    # tenzij het pand verder geen winkelfunctie heeft.
    b_bedrijfsmatig = kantoor + bedrijf + (overig if winkel == 0 else 0)
    if (woon >= b["min_woon"] and b_bedrijfsmatig >= b["min_overig_bedrijfsmatig"]
            and max(n_vbo, n_adres) >= b["min_vbo_of_adressen"]
            and b["opp_min"] <= opp <= b["opp_max"] and 0 < bj < b["bouwjaar_voor"]):
        cats.append("B")

    cc = c["C_klein_wooncomplex"]
    if (cc["woon_vbo_min"] <= woon <= cc["woon_vbo_max"]
            and cc["opp_min"] <= opp <= cc["opp_max"] and 0 < bj < cc["bouwjaar_voor"]):
        cats.append("C")

    d = c["D_groot_oud_pand"]
    if (0 < bj < d["bouwjaar_voor"] and opp >= d["opp_min"]
            and d["vbo_min"] <= n_vbo <= d["vbo_max"]):
        cats.append("D")

    e = c["E_afwijkend"]
    groot_weinig = (opp >= e["groot_opp_weinig_eenheden_opp"]
                    and n_vbo <= e["groot_opp_weinig_eenheden_vbo"])
    veel_adressen = n_adres >= e["min_adressen"]
    # Meerdere functiegroepen binnen een pand is een afwijkende combinatie.
    meerdere_functies = sum(
        1 for g in ("woon", "winkel", "kantoor", "bedrijf", "overig") if _n(pand, g) > 0
    ) >= 3
    if groot_weinig or (veel_adressen and meerdere_functies):
        cats.append("E")

    return cats


def uitsluiten(pand: dict, cfg: dict) -> list[str]:
    """Geef de redenen waarom een pand wordt uitgesloten (leeg = behouden)."""
    u = cfg["uitsluitingen"]
    redenen: list[str] = []
    opp = pand["totale_oppervlakte"]
    bj = pand["bouwjaar"]

    if pand["pandstatus"] in u["status_uitsluiten"]:
        redenen.append(f"pandstatus: {pand['pandstatus']}")
    if opp > u["opp_groter_dan"]:
        redenen.append(f"oppervlakte {opp:,.0f} m2 > {u['opp_groter_dan']:,} m2")
    if opp <= 0:
        redenen.append("geen oppervlakte bekend")

    # Uitsluitend niet-interessante functie: alleen als er geen woon/winkel is.
    doelen = set(pand["gebruiksdoelen"])
    if doelen and doelen.issubset(set(u["enkel_gebruiksdoel_uitsluiten"])):
        redenen.append(f"uitsluitend {'/'.join(sorted(doelen))}")

    # Groot modern appartementencomplex.
    if (pand["aantal_vbo"] >= u["modern_complex_vbo_min"]
            and bj >= u["modern_complex_bouwjaar_vanaf"]):
        redenen.append(f"groot modern complex ({pand['aantal_vbo']} vbo, bouwjaar {bj})")

    return redenen


# ---------------------------------------------------------------------------
# Kwalificatie-signalen (staat / leegstand / verkoophistorie).
# Elke helper geeft (status, behaald, detail, punten) terug en wordt door zowel
# scoor() als score_opbouw() gebruikt, zodat score en uitleg nooit uiteenlopen.
#   status: "behaald" | "niet" | "inactief"  (inactief = bron niet gedraaid)
# ---------------------------------------------------------------------------

def _sig_buiten_gebruik(pand: dict, cfg: dict) -> tuple[str, bool, str, int]:
    """GRATIS uit BAG: pand/VBO buiten gebruik = leegstaand (echte acquisitiekans)."""
    punten = cfg["score"]["buiten_gebruik_bag"]
    statussen = set(pand.get("vbo_statussen", []))
    if pand.get("pandstatus") == "Pand buiten gebruik" or "Verblijfsobject buiten gebruik" in statussen:
        return "behaald", True, "buiten gebruik — leegstaand", punten
    return "niet", False, "in gebruik", punten


def _sig_verbouwing(pand: dict, cfg: dict) -> tuple[str, bool, str, int]:
    """GRATIS uit BAG: pand/VBO in verbouwing = mutatie (mogelijk al in ontwikkeling)."""
    punten = cfg["score"]["verbouwing_bag"]
    statussen = set(pand.get("vbo_statussen", []))
    if pand.get("pandstatus") == "Verbouwing pand" or "Verbouwing verblijfsobject" in statussen:
        return "behaald", True, "in verbouwing", punten
    return "niet", False, "geen verbouwing", punten


def _sig_energielabel(pand: dict, cfg: dict) -> tuple[str, bool, str, int]:
    """RVO EP-online: label E/F/G of ontbrekend = slechte/verouderde staat."""
    punten = cfg["score"]["slecht_of_ontbrekend_energielabel"]
    st = pand.get("energielabel_status", "onbekend")
    if st == "onbekend":
        return "inactief", False, "bron nodig: RVO EP-online", punten
    slecht = {str(x).upper() for x in cfg["bronnen"]["energielabel"].get("slechte_labels", ["E", "F", "G"])}
    label = pand.get("energielabel")
    if st == "geen":
        return "behaald", True, "geen energielabel geregistreerd", punten
    if label and label.upper() in slecht:
        return "behaald", True, f"energielabel {label}", punten
    return "niet", False, f"energielabel {label}", punten


_KWALIFICATIE_SIGNALEN = [
    ("Buiten gebruik / leegstaand", _sig_buiten_gebruik),
    ("In verbouwing", _sig_verbouwing),
    ("Slecht of ontbrekend energielabel", _sig_energielabel),
]


def scoor(pand: dict, cats: list[str], cfg: dict) -> tuple[int, list[str]]:
    """Bereken de leadscore en leg per punt de selectiereden vast."""
    s = cfg["score"]
    score = 0
    redenen: list[str] = []
    opp = pand["totale_oppervlakte"]
    bj = pand["bouwjaar"]
    n_vbo = pand["aantal_vbo"]
    woon, winkel = _n(pand, "woon"), _n(pand, "winkel")
    bedrijfsmatig = _n(pand, "kantoor") + _n(pand, "bedrijf") + _n(pand, "overig")

    # A en B zijn onderscheidende categorieen; de bonussen sluiten elkaar uit.
    # Anders stapelt een winkel+woonpand met een bergingsobject beide bonussen
    # en loopt de ranglijst vol met gelijke scores.
    # 'overige gebruiksfunctie' alleen telt niet als bedrijfsmatig: dat is in de
    # praktijk vaak een berging of opslagruimte, geen transformatiekans.
    echt_bedrijfsmatig = _n(pand, "kantoor") + _n(pand, "bedrijf")
    if winkel >= 1 and woon >= 1:
        score += s["winkel_plus_wonen"]
        redenen.append(f"winkel + {woon} won{'ing' if woon == 1 else 'ingen'}")
    elif echt_bedrijfsmatig >= 1 and woon >= 1:
        score += s["bedrijf_kantoor_plus_wonen"]
        redenen.append(f"bedrijf/kantoor + {woon} won{'ing' if woon == 1 else 'ingen'}")
    if 3 <= n_vbo <= 10:
        score += s["vbo_3_tot_10"]
        redenen.append(f"{n_vbo} verblijfsobjecten")
    if 0 < bj < 1940:
        score += s["bouwjaar_voor_1940"]
        redenen.append(f"bouwjaar {bj}")
    if 200 <= opp <= 800:
        score += s["opp_200_800"]
        redenen.append(f"{opp:,.0f} m2")
    if pand["aantal_adressen"] >= 3:
        score += s["min_3_adressen"]
        redenen.append(f"{pand['aantal_adressen']} adressen")
    if opp >= 400 and n_vbo <= 2:
        score += s["groot_opp_1_2_eenheden"]
        redenen.append(f"groot oppervlak ({opp:,.0f} m2) met {n_vbo} eenhe{'id' if n_vbo == 1 else 'den'}")

    functiegroepen = sum(
        1 for g in ("woon", "winkel", "kantoor", "bedrijf", "overig") if _n(pand, g) > 0
    )
    if functiegroepen >= 3:
        score += s["opvallende_functiecombinatie"]
        redenen.append(f"{functiegroepen} functiegroepen gecombineerd")

    # Kwalificatie-signalen (staat / leegstand / verkoophistorie). Inactieve
    # bronnen leveren niets; BAG-status telt altijd mee (gratis).
    for _label, helper in _KWALIFICATIE_SIGNALEN:
        _st, behaald, detail, punten = helper(pand, cfg)
        if behaald:
            score += punten
            redenen.append(detail)

    if bj >= cfg["uitsluitingen"]["bouwjaar_vanaf"]:
        score += s["recent_gebouwd_of_vernieuwd"]
        redenen.append(f"recent bouwjaar {bj}")
    if n_vbo >= cfg["uitsluitingen"]["modern_complex_vbo_min"]:
        score += s["groot_appartementencomplex"]
        redenen.append(f"groot complex ({n_vbo} vbo)")

    return score, redenen


def score_opbouw(pand: dict, cfg: dict) -> list[dict]:
    """Volledige criteria-checklist per pand: elk criterium, resultaat en punten.

    Spiegelt exact de logica van scoor(), inclusief de nog niet actieve signalen,
    zodat het dashboard bij het openen van een pand kan tonen waar elk punt vandaan
    komt (en welke punten nog 'op slot' zitten wegens ontbrekende databron).
    """
    s = cfg["score"]
    opp = pand["totale_oppervlakte"]
    bj = pand["bouwjaar"]
    n_vbo = pand["aantal_vbo"]
    n_adres = pand["aantal_adressen"]
    woon, winkel = _n(pand, "woon"), _n(pand, "winkel")
    echt_bedrijfsmatig = _n(pand, "kantoor") + _n(pand, "bedrijf")
    functiegroepen = sum(
        1 for g in ("woon", "winkel", "kantoor", "bedrijf", "overig") if _n(pand, g) > 0
    )

    items: list[dict] = []

    def add(label, punten, behaald, detail, status=None):
        items.append({
            "label": label,
            "punten": punten,
            "behaald": bool(behaald),
            "detail": detail,
            "status": status or ("behaald" if behaald else "niet"),
        })

    winkel_wonen = winkel >= 1 and woon >= 1
    add("Winkel + wonen", s["winkel_plus_wonen"], winkel_wonen,
        f"{winkel} winkel + {woon} woning(en)" if winkel_wonen else "geen winkel-woon combinatie")
    bedr = (not winkel_wonen) and echt_bedrijfsmatig >= 1 and woon >= 1
    add("Bedrijf/kantoor + wonen", s["bedrijf_kantoor_plus_wonen"], bedr,
        f"{echt_bedrijfsmatig} bedrijf/kantoor + {woon} woning(en)" if bedr
        else ("vervalt: winkel+wonen telt al" if winkel_wonen else "geen bedrijf-woon combinatie"))
    add("3–10 verblijfsobjecten", s["vbo_3_tot_10"], 3 <= n_vbo <= 10, f"{n_vbo} verblijfsobjecten")
    add("Bouwjaar vóór 1940", s["bouwjaar_voor_1940"], 0 < bj < 1940, f"bouwjaar {bj}")
    add("Oppervlakte 200–800 m²", s["opp_200_800"], 200 <= opp <= 800, f"{opp:,.0f} m²")
    add("Minimaal 3 adressen", s["min_3_adressen"], n_adres >= 3, f"{n_adres} adressen")
    add("Groot oppervlak, 1–2 eenheden", s["groot_opp_1_2_eenheden"], opp >= 400 and n_vbo <= 2,
        f"{opp:,.0f} m² met {n_vbo} eenhe{'id' if n_vbo == 1 else 'den'}")
    add("3+ functiegroepen gecombineerd", s["opvallende_functiecombinatie"], functiegroepen >= 3,
        f"{functiegroepen} functiegroepen")

    if bj >= cfg["uitsluitingen"]["bouwjaar_vanaf"]:
        add("Recent bouwjaar (≥ 2000)", s["recent_gebouwd_of_vernieuwd"], True,
            f"bouwjaar {bj}", status="aftrek")
    if n_vbo >= cfg["uitsluitingen"]["modern_complex_vbo_min"]:
        add("Groot complex (≥ 16 vbo)", s["groot_appartementencomplex"], True,
            f"{n_vbo} vbo", status="aftrek")

    for label, helper in _KWALIFICATIE_SIGNALEN:
        st, behaald, detail, punten = helper(pand, cfg)
        add(label, punten, behaald, detail, status=st)

    return items


def naar_100(score: int, cfg: dict) -> int:
    """Reken de rauwe leadscore om naar een 1–100 index tegen het modelbudget."""
    budget = cfg["score"].get("schaal_max", 28)
    return max(1, min(100, round(score / budget * 100)))


def laad_verrijking(label: str) -> dict[str, dict]:
    """Lees de bron-verrijking (energielabel e.d.) van dit doelgebied uit, indien aanwezig."""
    f = DATA / f"verrijking_{slug(label)}.json"
    if f.exists():
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def kies_snapshots(
    woonplaatsen, cfg: dict, keuze: str | None = None
) -> list[snapshots.Snapshot]:
    """Kies per woonplaats de snapshot (standaard de nieuwste) en meld welke op scherm.

    'keuze' is None (nieuwste), een ophaaldatum 'JJJJ-MM-DD' of een bestandsnaam.
    """
    if isinstance(woonplaatsen, str):
        woonplaatsen = [woonplaatsen]
    gekozen = []
    for w in woonplaatsen:
        snap = snapshots.kies(w, slug(w), DATA, cfg, keuze)
        print(f"Snapshot {w}: {snap.omschrijving()}")
        gekozen.append(snap)
    return gekozen


def lees_snapshots(gekozen: list[snapshots.Snapshot]) -> list[dict]:
    rows: list[dict] = []
    for snap in gekozen:
        rows += snapshots.lees(snap)
    return rows


def eis_ophaaldatum(gekozen: list[snapshots.Snapshot]) -> None:
    """Stop als een snapshot geen vastgelegde ophaaldatum heeft.

    De datapeildatum van een lead is de ophaaldatum van zijn data. Zonder die datum
    valt er niets te stempelen, en de datum van vandaag is het juist niet.
    """
    for snap in gekozen:
        if not snap.ophaaldatum:
            raise snapshots.SnapshotFout(
                f"Snapshot {snap.pad.name} ({snap.woonplaats}) heeft geen vastgelegde "
                "ophaaldatum, dus de datapeildatum is onbekend. Leg de ophaaldatum vast in "
                f"config.yaml onder snapshots.ongedateerd (\"{snap.pad.name}: JJJJ-MM-DD\") "
                "of draai een nieuwe ingest: python ingest.py"
            )


def verwerk(
    woonplaatsen,
    cfg: dict,
    label: str | None = None,
    snapshot: str | None = None,
    gekozen: list[snapshots.Snapshot] | None = None,
) -> list[dict]:
    """Verwerk één of meer woonplaatsen tot gescoorde panden voor het doelgebied.

    'woonplaatsen' mag een enkele naam (str) of een lijst zijn. 'label' is de
    leesbare gebiedsnaam (stad of provincie) voor bestandsnamen en lead-id's.
    'snapshot' kiest welke ingest gelezen wordt (zie kies_snapshots); standaard de
    nieuwste. 'gekozen' geeft de snapshots direct mee als ze al gekozen zijn.
    """
    if isinstance(woonplaatsen, str):
        woonplaatsen = [woonplaatsen]
    if label is None:
        label = woonplaatsen[0]

    if gekozen is None:
        gekozen = kies_snapshots(woonplaatsen, cfg, snapshot)
    eis_ophaaldatum(gekozen)
    if all(s.soort == "sqlite" for s in gekozen):
        # VA-36: een SQLite-snapshot gaat pand voor pand; het geheugen houdt alleen de uitkomst.
        return list(stroom_panden(gekozen, cfg, label))
    rows: list[dict] = []
    peildatum: dict[str, str] = {}  # BAG-pand-ID -> ophaaldatum van zijn snapshot
    for snap in gekozen:
        snap_rows = snapshots.lees(snap)
        for rij in snap_rows:
            pand_id = rij.get("pandidentificatie")
            if pand_id:
                # Eerste VBO wint, net als de woonplaats in aggregeer().
                peildatum.setdefault(pand_id, snap.ophaaldatum)
        rows += snap_rows
    panden = aggregeer(rows)
    verrijking = laad_verrijking(label)
    kort = lead_kort(label)
    for pand in panden:
        verwerk_pand(pand, cfg, verrijking, kort, peildatum[pand["bag_pand_id"]])
    return panden


def lead_kort(label: str) -> str:
    """De twee letters in het lead-ID: 'DE' voor Delft."""
    return ("".join(c for c in label if c.isalnum())[:2] or "NL").upper()


def verwerk_pand(pand: dict, cfg: dict, verrijking: dict, kort: str, datapeildatum: str) -> dict:
    """Uitsluiten, categoriseren en scoren van één geaggregeerd pand (beide routes, VA-36)."""
    v = verrijking.get(pand["bag_pand_id"])
    if v:
        pand.update(v)  # energielabel/koopsom/kvk-velden voor scoring
    pand["uitsluitredenen"] = uitsluiten(pand, cfg)
    pand["uitgesloten"] = bool(pand["uitsluitredenen"])
    pand["categorieen"] = categoriseer(pand, cfg)
    pand["pandcategorie"] = pand["categorieen"][0] if pand["categorieen"] else ""
    score, redenen = scoor(pand, pand["categorieen"], cfg)
    pand["leadscore"] = score
    pand["score100"] = naar_100(score, cfg)
    pand["score_opbouw"] = score_opbouw(pand, cfg)
    pand["selectiereden"] = "; ".join(redenen)
    pand["lead_id"] = f"LEV-{kort}-{pand['bag_pand_id'][-8:]}"
    pand["bron"] = "PDOK BAG WFS v2_0"
    pand["datapeildatum"] = datapeildatum
    pand["visuele_controle"] = False
    pand["beoordeling"] = ""
    pand["eerder_geselecteerd"] = False
    pand["laatst_beoordeeld"] = ""
    return pand


def stroom_panden(
    gekozen: list[snapshots.Snapshot],
    cfg: dict,
    label: str,
    woonplaats_id: str | None = None,
    kort: str | None = None,
):
    """
    Gescoorde panden uit SQLite-snapshots, één voor één (VA-36). Er staat nooit meer dan één
    pand aan VBO's in het geheugen; de uitkomst is per pand dezelfde als bij verwerk() op JSON.
    De panden komen op volgorde van hun BAG-ID.

    Bij meer snapshots (een provincie, of de landelijke snapshot per woonplaats) kan één pand
    in meer snapshots VBO's hebben. Die worden samengevoegd in de volgorde van 'gekozen', net
    als de JSON-route de rijen achter elkaar zet: de eerste VBO en de datapeildatum komen uit de
    eerste snapshot waarin het pand voorkomt.
    """
    eis_ophaaldatum(gekozen)
    verrijking = laad_verrijking(label)
    kort = kort or lead_kort(label)

    def per_snapshot(i: int, snap: snapshots.Snapshot):
        for vbos in snapshots.stroom_per_pand(snap, woonplaats_id=woonplaats_id):
            yield vbos[0]["pandidentificatie"], i, vbos

    stromen = [per_snapshot(i, s) for i, s in enumerate(gekozen)]
    huidig, eerste_i, vbos = None, None, []
    # Gesorteerd op (pand-ID, snapshotnummer): gelijke panden komen achter elkaar, eerste snapshot eerst.
    for pand_id, i, rijen in heapq.merge(*stromen, key=lambda x: (x[0], x[1])):
        if pand_id != huidig and vbos:
            yield verwerk_pand(aggregeer(vbos)[0], cfg, verrijking, kort, gekozen[eerste_i].ophaaldatum)
            vbos = []
        if pand_id != huidig:
            huidig, eerste_i = pand_id, i
        vbos.extend(rijen)
    if vbos:
        yield verwerk_pand(aggregeer(vbos)[0], cfg, verrijking, kort, gekozen[eerste_i].ophaaldatum)


def mastervolgorde(pand: dict) -> tuple[int, str]:
    """Sorteersleutel van mastervoorraad en proef: hoogste leadscore eerst, dan BAG-pand-ID."""
    return (-pand["leadscore"], pand["bag_pand_id"])


def maandloting(maand: str, pand_id: str) -> str:
    """Lotnummer van een pand voor de werklijst van een maand (VA-32).

    De SHA-256 (hex) van "<JJJJ-MM>:<bag_pand_id>". Het hangt alleen af van de maand en
    het BAG-pand-ID, dus niet van PYTHONHASHSEED, de invoervolgorde of het aantal panden,
    en iedereen kan het narekenen.
    """
    return hashlib.sha256(f"{maand}:{pand_id}".encode("utf-8")).hexdigest()


def werklijstvolgorde(maand: str):
    """Sorteersleutel van de werklijst van een maand (VA-32).

    Hoogste leadscore eerst; bij gelijke score beslist het lotnummer van de maand
    (maandloting), en het BAG-pand-ID alleen als twee lotnummers gelijk zouden zijn.
    """
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", maand or ""):
        raise ValueError(f"werklijstmaand moet JJJJ-MM zijn, niet {maand!r}")

    def sleutel(pand: dict) -> tuple[int, str, str]:
        return (-pand["leadscore"], maandloting(maand, pand["bag_pand_id"]), pand["bag_pand_id"])

    return sleutel


def werklijst(panden: list[dict], cfg: dict, maand: str) -> tuple[list[dict], int]:
    """Kies de maandelijkse werklijst uit de gescoorde panden (VA-5, VA-32).

    In aanmerking komt een pand dat niet is uitgesloten, in minstens één categorie A-E
    valt en een leadscore heeft van minstens drempels.score_min_voor_werklijst. Die
    panden staan op leadscore, hoogste eerst; panden met dezelfde score staan in een
    volgorde die vastligt voor de maand (JJJJ-MM, zie werklijstvolgorde). De werklijst
    is het begin daarvan, hoogstens drempels.werklijst_max panden. Wie op de grensscore
    meedoet, hangt dus af van de maand, niet van het BAG-pand-ID.

    Geeft (werklijst, aantal panden dat in aanmerking kwam) terug.
    """
    drempels = cfg["drempels"]
    score_min = drempels["score_min_voor_werklijst"]
    maximum = drempels["werklijst_max"]
    geschikt = sorted(
        (
            p for p in panden
            if not p["uitgesloten"] and p["categorieen"] and p["leadscore"] >= score_min
        ),
        key=werklijstvolgorde(maand),
    )
    return geschikt[:maximum], len(geschikt)


def werklijst_waarschuwing(aantal_geschikt: int, cfg: dict) -> str | None:
    """Nederlandse waarschuwing als er minder dan drempels.werklijst_min panden in aanmerking komen."""
    drempels = cfg["drempels"]
    minimum = drempels["werklijst_min"]
    if aantal_geschikt >= minimum:
        return None
    return (
        f"WAARSCHUWING: slechts {_nl(aantal_geschikt)} panden komen in aanmerking voor de "
        f"werklijst (leadscore >= {drempels['score_min_voor_werklijst']}), minder dan het "
        f"minimum van {_nl(minimum)} (drempels.werklijst_min). De werklijst is toch geschreven."
    )


def _heel_getal(waarde) -> bool:
    return isinstance(waarde, int) and not isinstance(waarde, bool)


def controleer_drempels(cfg: dict) -> list[str]:
    """
    Fouten in drempels.* die een lege of onzinnige werklijst zouden geven (VA-41).
    Een lege lijst betekent: in orde. Elke melding noemt de sleutel en zijn waarde.
    """
    drempels = cfg.get("drempels") or {}
    schaal = (cfg.get("score") or {}).get("schaal_max")
    mn, mx = drempels.get("werklijst_min"), drempels.get("werklijst_max")
    score = drempels.get("score_min_voor_werklijst")
    fouten = []
    if not _heel_getal(mn):
        fouten.append(f"drempels.werklijst_min = {mn!r} is geen heel getal")
    elif mn < 0:
        fouten.append(f"drempels.werklijst_min = {mn} is kleiner dan 0")
    if not _heel_getal(mx):
        fouten.append(f"drempels.werklijst_max = {mx!r} is geen heel getal")
    elif mx < 1:
        fouten.append(f"drempels.werklijst_max = {mx} is kleiner dan 1")
    if _heel_getal(mn) and _heel_getal(mx) and mn > mx:
        fouten.append(f"drempels.werklijst_min = {mn} is groter dan drempels.werklijst_max = {mx}")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or score != score:  # NaN != NaN
        fouten.append(f"drempels.score_min_voor_werklijst = {score!r} is geen getal")
    elif isinstance(schaal, (int, float)) and not isinstance(schaal, bool) and score > schaal:
        fouten.append(f"drempels.score_min_voor_werklijst = {score} is hoger dan score.schaal_max = "
                      f"{schaal}: geen pand kan die score halen")
    return fouten


def nl_tal(n: float) -> str:
    """Getal met punt als duizendtalscheiding, afgerond op een heel getal: 1668 -> '1.668'."""
    return f"{round(n):,}".replace(",", ".")


_nl = nl_tal  # oude naam, blijft werken


def werklijst_maand(gekozen: list[snapshots.Snapshot]) -> str:
    """De maand (JJJJ-MM) van de werklijst: die van de nieuwste ophaaldatum, niet van vandaag.

    Bij één woonplaats is dat de maand van zijn snapshot. verwerk() heeft al gestopt
    als een snapshot geen ophaaldatum heeft.
    """
    eis_ophaaldatum(gekozen)
    return max(s.ophaaldatum for s in gekozen)[:7]
