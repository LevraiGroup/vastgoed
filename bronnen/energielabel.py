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

Bulk (VA-58): het maandbestand (CSV in een zip, ~230 MB, elke 1e van de maand) haalt en koppelt
ep_online.py, met de sleutel uit EP_ONLINE_API_KEY en een vaste kolomcontrole. Deze module doet
alleen nog de bevraging per adres voor verrijk.py.

Signaal: een pand telt mee (+2) als het label E/F/G is OF als er geen label is
geregistreerd (ontbrekend label = vaak niet-verduurzaamd, ouder bezit).
"""
from __future__ import annotations

import requests

NAAM = "energielabel"
_LABEL_VOLGORDE = ["A+++++", "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]


def _cfg(cfg: dict) -> dict:
    return cfg.get("bronnen", {}).get("energielabel", {})


def beschikbaar(cfg: dict) -> tuple[bool, str]:
    c = _cfg(cfg)
    if not c.get("actief"):
        return False, "uitgeschakeld (bronnen.energielabel.actief = false)"
    if c.get("api_key"):
        return True, "API-modus (public.ep-online.nl v5)"
    return False, "geen api_key ingesteld (het maandbestand gaat via ep_online.py)"


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
    label_per_vbo = _uit_api(kandidaten, _cfg(cfg))

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
