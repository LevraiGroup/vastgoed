"""
Levrai Group - externe verrijkingsbronnen.

Actieve module(s):
  - energielabel : RVO EP-online          -> slecht_of_ontbrekend_energielabel (+2)

Geparkeerd (zie TOEKOMSTVERBETERINGEN.md): KVK-leegstand en Kadaster-koopsom.

Contract per module:
  NAAM: str
  beschikbaar(cfg) -> tuple[bool, str]      # (bruikbaar?, uitleg)
  verrijk(kandidaten, cfg) -> dict[str, dict]   # bag_pand_id -> velden om te mergen

De modules doen ALLE netwerkcalls; de scoring (selectie.py) leest alleen het
resultaat uit de cache data/verrijking_<woonplaats>.json. Zo blijft de dagelijkse
scoring snel en offline, net zoals ingest en scoring al gescheiden zijn.
"""
from . import energielabel

MODULES = {
    "energielabel": energielabel,
}
