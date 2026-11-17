"""
Bewaarde en verborgen panden op de server, gedeeld door iedereen met de Levrai-inlog.

Ayman, 2026-11-17: de lijst mag niet meer "alleen op dit apparaat, in deze browser" staan; het moet
productieklaar zijn. Er is één gedeeld account (VA-50), dus er is één lijst: wie op de laptop een pand
bewaart, ziet het op de telefoon terug.

Het bestand staat op blijvende opslag, nooit in de app-map (die wordt bij elke deploy vervangen):

    VASTGOED_BEWAARD            pad naar het JSON-bestand; anders
    RAILWAY_VOLUME_MOUNT_PATH   de map van het Railway-volume (zet Railway zelf), met bewaard.json erin

Zonder een van beide is er geen opslag: de API zegt dat met 503 en het dashboard valt terug op de browser.

Vorm op schijf, één regel per pand, met dezelfde velden als het dashboard per pand bewaart (VA-90/VA-91):

    {"versie": 1, "panden": {"<bag_pand_id>": {"stand": "bewaard"|"verborgen", "sinds": ..., ...}}}

Alleen de standaardbibliotheek.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

VAR_BEWAARD = "VASTGOED_BEWAARD"
VAR_VOLUME = "RAILWAY_VOLUME_MOUNT_PATH"
BESTAND = "bewaard.json"
VERSIE = 1
MAX_PANDEN = 5000          # ruim boven de 500 van een werklijst, ook met maanden aan bewaarde panden
MAX_TEKST = 300            # tekens per tekstveld
STANDEN = ("bewaard", "verborgen")
PAND_ID = re.compile(r"[0-9]{16}")
TEKSTVELDEN = ("stand", "sinds", "hoofdadres", "woonplaats", "pandcategorie", "bag_viewer_url", "datapeildatum")
VELDEN = TEKSTVELDEN + ("score100",)


class Ongeldig(ValueError):
    """Een verzoek dat niet past; er is niets geschreven."""


def opslag_pad(omgeving: dict[str, str], verboden: Path) -> tuple[Path | None, str]:
    """Het pad van het bestand, of None met de reden. Een pad in de app-map (`verboden`) telt niet."""
    ruw = omgeving.get(VAR_BEWAARD, "").strip()
    if not ruw:
        volume = omgeving.get(VAR_VOLUME, "").strip()
        if not volume:
            return None, f"{VAR_BEWAARD} en {VAR_VOLUME} niet gezet; bewaarde panden blijven in de browser"
        ruw = str(Path(volume) / BESTAND)
    pad = Path(ruw).resolve()
    if pad == verboden.resolve() or verboden.resolve() in pad.parents:
        return None, f"{pad} ligt in de app-map, die bij elke deploy wordt vervangen; bewaarde panden blijven in de browser"
    return pad, ""


def schoon(waarde) -> dict:
    """Een pand zoals het dashboard het stuurt, met alleen de bekende velden; anders Ongeldig."""
    if not isinstance(waarde, dict) or not set(waarde) <= set(VELDEN):
        raise Ongeldig("onbekende velden")
    if waarde.get("stand") not in STANDEN:
        raise Ongeldig("stand moet bewaard of verborgen zijn")
    uit = {}
    for k in TEKSTVELDEN:
        v = waarde.get(k)
        if v is None:
            continue
        if not isinstance(v, str) or len(v) > MAX_TEKST:
            raise Ongeldig(f"{k} is geen korte tekst")
        uit[k] = v
    s = waarde.get("score100")
    if s is not None:
        if isinstance(s, bool) or not isinstance(s, (int, float)) or s != s or not -1000 <= s <= 1000:
            raise Ongeldig("score100 is geen getal")
        uit["score100"] = s
    return uit


class Opslag:
    """Leest en schrijft het bestand; één schrijver tegelijk, en een schrijfactie is heel of niet."""

    def __init__(self, pad: Path | None):
        self.pad = pad
        self._slot = threading.Lock()

    @property
    def aan(self) -> bool:
        return self.pad is not None

    def _lees(self) -> dict:
        if not self.pad.exists():
            if not self.pad.parent.is_dir():
                raise OSError(f"map {self.pad.parent} bestaat niet")
            return {}
        data = json.loads(self.pad.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("versie") != VERSIE or not isinstance(data.get("panden"), dict):
            raise ValueError("onbekende vorm of versie")
        return data["panden"]

    def _schrijf(self, panden: dict) -> None:
        tijdelijk = self.pad.with_name(self.pad.name + ".nieuw")
        with open(tijdelijk, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"versie": VERSIE, "panden": panden}, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tijdelijk, self.pad)

    def alles(self) -> dict:
        with self._slot:
            return self._lees()

    def wijzig(self, wijzigingen) -> dict:
        """
        Zet of wist panden: [{"id": "<16 cijfers>", "waarde": {...} of null}, ...]. Alles wordt eerst
        gecontroleerd; één fout en er verandert niets. Geeft alle panden na de wijziging.
        """
        if not isinstance(wijzigingen, list) or not 0 < len(wijzigingen) <= MAX_PANDEN:
            raise Ongeldig("wijzigingen moet een lijst zijn")
        klaar = []
        for w in wijzigingen:
            if not isinstance(w, dict) or set(w) != {"id", "waarde"}:
                raise Ongeldig("elke wijziging heeft id en waarde")
            if not isinstance(w["id"], str) or not PAND_ID.fullmatch(w["id"]):
                raise Ongeldig("id is geen BAG-pand-ID")
            klaar.append((w["id"], None if w["waarde"] is None else schoon(w["waarde"])))
        with self._slot:
            panden = self._lees()
            for pid, waarde in klaar:
                if waarde is None:
                    panden.pop(pid, None)
                else:
                    panden[pid] = waarde
            if len(panden) > MAX_PANDEN:
                raise Ongeldig(f"meer dan {MAX_PANDEN} panden")
            self._schrijf(panden)
            return panden
