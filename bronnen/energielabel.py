"""
RVO EP-online — energielabels.

Toegang: GRATIS data, maar een persoonlijke API-key is verplicht
(aanvragen via https://apikey.ep-online.nl, ~5 min later bruikbaar).

Geverifieerd API-contract (v5):
  Basis   : https://public.ep-online.nl/api/v5
  Header  : Authorization: <api-key>
  Adres   : GET /PandEnergielabel/Adres?postcode=&huisnummer=&huisletter=&huisnummertoevoeging=
  BAG-obj : GET /PandEnergielabel/AdresseerbaarObject/{adresseerbaarObjectId}
  Velden  : Energieklasse, Registratiedatum, Soort_opname, Berekeningstype, BAGVerblijfsobjectID
  Ping    : GET /Ping  (zonder key, gaf 200 'Pong' bij de verkenning)

Bulk-alternatief (aanrader bij grote steden): op https://www.ep-online.nl/PublicData
staat een maandbestand (XML/CSV/XLSX, ~220 MB CSV, elke 1e van de maand). Ook dat
vereist dezelfde API-key. Zet dan 'bulk_csv' in config.yaml naar het CSV-pad.

Signaal: een pand telt mee (+2) als het label E/F/G is OF als er geen label is
geregistreerd (ontbrekend label = vaak niet-verduurzaamd, ouder bezit).
"""
from __future__ import annotations

import csv
from pathlib import Path

import requests

NAAM = "energielabel"
_LABEL_VOLGORDE = ["A+++++", "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]


def _cfg(cfg: dict) -> dict:
    return cfg.get("bronnen", {}).get("energielabel", {})


def beschikbaar(cfg: dict) -> tuple[bool, str]:
    c = _cfg(cfg)
    if not c.get("actief"):
        return False, "uitgeschakeld (bronnen.energielabel.actief = false)"
    if c.get("bulk_csv"):
        return (True, f"bulk-CSV: {c['bulk_csv']}") if Path(c["bulk_csv"]).exists() \
            else (False, f"bulk_csv niet gevonden: {c['bulk_csv']}")
    if c.get("api_key"):
        return True, "API-modus (public.ep-online.nl v5)"
    return False, "geen api_key en geen bulk_csv ingesteld"


def _veld(obj: dict, *namen: str):
    laag = {k.lower(): v for k, v in obj.items()}
    for n in namen:
        if n.lower() in laag:
            return laag[n.lower()]
    return None


def _slechter(a: str | None, b: str | None) -> str | None:
    """Geef het 'slechtste' (hoogste letter) van twee labels terug."""
    def rang(x):
        x = (x or "").upper()
        return _LABEL_VOLGORDE.index(x) if x in _LABEL_VOLGORDE else -1
    if a is None:
        return b
    if b is None:
        return a
    return a if rang(a) >= rang(b) else b


# ---------------------------------------------------------------- bulk-CSV modus
def _uit_bulk(kandidaten: list[dict], csv_pad: str) -> dict[str, str | None]:
    """Bouw een index BAG-vbo-id -> label uit het EP-online maandbestand.

    De exacte kolomnamen van het bestand kunnen per release verschillen; we zoeken
    daarom flexibel naar een BAG-id-kolom en een labelkolom. Controleer bij de eerste
    run de header van je downloadbestand als er niets matcht.
    """
    gezocht = {vid for p in kandidaten for vid in p["vbo_ids"]}
    label_per_vbo: dict[str, str | None] = {}
    with open(csv_pad, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        reader = csv.DictReader(fh, dialect=dialect)
        bag_kol = next((k for k in reader.fieldnames or []
                        if "bag" in k.lower() and "verblijf" in k.lower()), None) \
            or next((k for k in reader.fieldnames or [] if "adresseerbaar" in k.lower()), None)
        lab_kol = next((k for k in reader.fieldnames or [] if "energieklasse" in k.lower()
                        or k.lower() in ("labelletter", "label")), None)
        if not bag_kol or not lab_kol:
            raise RuntimeError(f"EP-online CSV: kolommen niet herkend ({reader.fieldnames})")
        for rij in reader:
            vid = (rij.get(bag_kol) or "").strip()
            if vid in gezocht:
                label_per_vbo[vid] = (rij.get(lab_kol) or "").strip() or None
    return label_per_vbo


# ---------------------------------------------------------------- API modus
def _uit_api(kandidaten: list[dict], c: dict) -> dict[str, str | None]:
    sess = requests.Session()
    sess.headers.update({"Authorization": c["api_key"], "Accept": "application/json",
                         "User-Agent": "Levrai-Pandenselectie/1.0"})
    basis = c["api_url"].rstrip("/")
    plafond = int(c.get("max_bevragingen", 2000))
    label_per_vbo: dict[str, str | None] = {}
    calls = 0
    for pand in kandidaten:
        vid = pand["vbo_ids"][0] if pand["vbo_ids"] else None
        if not vid:
            continue
        if calls >= plafond:
            print(f"  [energielabel] plafond {plafond} bevragingen bereikt; rest onbekend")
            break
        try:
            r = sess.get(f"{basis}/PandEnergielabel/AdresseerbaarObject/{vid}", timeout=30)
            calls += 1
            if r.status_code == 404:
                label_per_vbo[vid] = None  # geen label geregistreerd
                continue
            r.raise_for_status()
            data = r.json()
            rec = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
            label_per_vbo[vid] = (_veld(rec, "Energieklasse", "labelletter") if rec else None)
        except requests.RequestException as exc:
            print(f"  [energielabel] fout bij {vid}: {exc.__class__.__name__}")
    print(f"  [energielabel] {calls} API-bevragingen gedaan")
    return label_per_vbo


def verrijk(kandidaten: list[dict], cfg: dict) -> dict[str, dict]:
    c = _cfg(cfg)
    if c.get("bulk_csv"):
        label_per_vbo = _uit_bulk(kandidaten, c["bulk_csv"])
    else:
        label_per_vbo = _uit_api(kandidaten, c)

    uit: dict[str, dict] = {}
    for pand in kandidaten:
        gevonden = None
        heeft_data = False
        for vid in pand["vbo_ids"]:
            if vid in label_per_vbo:
                heeft_data = True
                gevonden = _slechter(gevonden, label_per_vbo[vid])
        if not heeft_data:
            continue  # geen uitspraak -> blijft 'onbekend'
        uit[pand["bag_pand_id"]] = {
            "energielabel": gevonden,
            "energielabel_status": "gevonden" if gevonden else "geen",
        }
    return uit
