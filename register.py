"""
Levrai Group - Pandenselectiesysteem
Het dedup-register (VA-6): welke panden Levrai al in een werklijst heeft gekregen.

Briefing sectie 7 stap 4. Een pand dat in een werklijst is geleverd, komt nooit meer in
een latere werklijst, voor welk doelgebied ook: er is één register voor alle gebieden, en
het BAG-pand-ID is landelijk uniek.

Het register is een gewone CSV (';', UTF-8 met BOM, zoals de andere CSV's) buiten output/
en buiten data/, zodat het opnieuw maken van de uitvoer het nooit wist. Het staat in git.
Per pand één regel: bag_pand_id, de maand van de werklijst (JJJJ-MM) en de bestandsnaam van
de werklijst. Een mens mag het openen, lezen en met de hand verbeteren (README,
"Dedup-register"); een regel die niet klopt stopt de run, nooit stil een leeg register.

Een werklijst wordt herkend aan zijn bestandsnaam (gebied en maand). Dezelfde werklijst
opnieuw draaien geeft dezelfde lijst en registreert niets dubbel. Geeft een nieuwe run voor
een al geregistreerde werklijst een andere lijst, dan stopt hij (VA-6 crit. 8).
"""
from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

BASE = Path(__file__).parent
STANDAARD = BASE / "register" / "geleverde_panden.csv"
VAR_REGISTER = "VASTGOED_REGISTER"  # ander registerbestand, voor tests en kopieën
KOLOMMEN = ["bag_pand_id", "maand", "werklijst"]

_PAND_ID = re.compile(r"\d{16}")
_MAAND = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class RegisterFout(RuntimeError):
    """Het register is onleesbaar, of de run zou een geleverde werklijst veranderen."""


def pad(basis: Path | None = None) -> Path:
    """
    Het registerbestand: VASTGOED_REGISTER als die is gezet, anders register/geleverde_panden.csv
    in de projectmap ('basis', standaard de map van deze module).
    """
    if os.environ.get(VAR_REGISTER):
        return Path(os.environ[VAR_REGISTER])
    return STANDAARD if basis is None else Path(basis) / STANDAARD.relative_to(BASE)


def toon(p: Path) -> str:
    """Het pad zoals de console het noemt: relatief aan de projectmap als het daarin ligt."""
    try:
        return str(p.resolve().relative_to(BASE.resolve()))
    except ValueError:
        return str(p)


class Register:
    """De regels van het register, in de volgorde van het bestand."""

    def __init__(self, bestand: Path | None = None):
        self.pad = Path(bestand) if bestand is not None else pad()
        self.regels: list[dict] = self._lees()

    def _lees(self) -> list[dict]:
        if not self.pad.exists():
            return []
        with open(self.pad, encoding="utf-8-sig", newline="") as fh:
            lezer = csv.DictReader(fh, delimiter=";")
            kop = [k.strip() for k in (lezer.fieldnames or [])]
            if kop[:len(KOLOMMEN)] != KOLOMMEN:
                raise RegisterFout(
                    f"{toon(self.pad)}: de eerste regel moet {';'.join(KOLOMMEN)} zijn, niet "
                    f"{';'.join(kop) or '(leeg)'}. Er is niets geschreven.")
            regels = []
            for rij in lezer:
                waarden = {k: (rij.get(k) or "").strip() for k in KOLOMMEN}
                if not any(waarden.values()):
                    continue  # een lege regel
                fout = None
                if not _PAND_ID.fullmatch(waarden["bag_pand_id"]):
                    fout = (f"bag_pand_id {waarden['bag_pand_id']!r} is geen BAG-pand-ID van 16 cijfers "
                            "(Excel haalt de 0 vooraan weg: bewerk het register in Kladblok)")
                elif not _MAAND.fullmatch(waarden["maand"]):
                    fout = f"maand {waarden['maand']!r} is geen JJJJ-MM"
                elif not waarden["werklijst"]:
                    fout = "de werklijst (bestandsnaam) ontbreekt"
                if fout:
                    raise RegisterFout(f"{toon(self.pad)}, regel {lezer.line_num}: {fout}. Er is niets geschreven.")
                regels.append(waarden)
        return regels

    def alle(self) -> set[str]:
        """Elk geregistreerd BAG-pand-ID."""
        return {r["bag_pand_id"] for r in self.regels}

    def elders(self, werklijst: str) -> set[str]:
        """De panden die in een andere werklijst zijn geleverd dan 'werklijst' (een bestandsnaam)."""
        return {r["bag_pand_id"] for r in self.regels if r["werklijst"] != werklijst}

    def van(self, werklijst: str) -> list[str]:
        """De panden die onder deze werklijst zijn geregistreerd, in de volgorde van het register."""
        return [r["bag_pand_id"] for r in self.regels if r["werklijst"] == werklijst]

    def controleer(self, werklijst: str, maand: str, pand_ids: list[str]) -> None:
        """
        Stop als deze werklijst al is geregistreerd met andere panden (VA-6 crit. 8). Dan
        wordt niets geschreven: niet het werklijstbestand, niet het register.
        """
        eerder = self.van(werklijst)
        if not eerder or eerder == list(pand_ids):
            return
        anders = len(set(eerder) ^ set(pand_ids))
        raise RegisterFout(
            f"De werklijst van {maand} ({werklijst}) is al geleverd: het register "
            f"({toon(self.pad)}) heeft er {len(eerder)} panden van, en deze run geeft een andere lijst "
            f"({len(pand_ids)} panden, {anders} anders"
            f"{', zelfde panden in een andere volgorde' if anders == 0 else ''}). "
            "Een geleverde werklijst verandert niet stil, dus het bestand en het register blijven zoals "
            "ze zijn. Was er iets verkeerd geleverd, maak de levering dan met de hand ongedaan in het "
            "register (README, 'Dedup-register').")

    def leg_vast(self, werklijst: str, maand: str, pand_ids: list[str]) -> int:
        """
        Voeg de panden van deze werklijst toe aan het register (achteraan, met de hand gemaakte
        regels blijven staan). Staat deze werklijst er al precies zo in, dan verandert er niets.
        Geeft het aantal nieuwe regels.
        """
        self.controleer(werklijst, maand, pand_ids)
        if self.van(werklijst):
            return 0
        nieuw = [{"bag_pand_id": i, "maand": maand, "werklijst": werklijst} for i in pand_ids]
        if not nieuw:
            return 0
        buffer = io.StringIO()
        w = csv.DictWriter(buffer, fieldnames=KOLOMMEN, delimiter=";", lineterminator="\r\n")
        bestaat = self.pad.exists() and self.pad.stat().st_size > 0
        if not bestaat:
            w.writeheader()
        w.writerows(nieuw)
        tekst = buffer.getvalue()
        if bestaat:
            with open(self.pad, "rb") as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) not in (b"\n", b"\r"):
                    tekst = "\r\n" + tekst  # met de hand bewerkt zonder regeleinde aan het eind
        self.pad.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pad, "a", encoding="utf-8-sig" if not bestaat else "utf-8", newline="") as fh:
            fh.write(tekst)
        self.regels += nieuw
        return len(nieuw)


def regel(reg: Register, nieuw: int, uitgesloten: int) -> str:
    """De consoleregel over het register na een werklijstrun (VA-6), voor beide routes."""
    def tal(n: int) -> str:
        return f"{n:,}".replace(",", ".")
    return (f"Register        -> {toon(reg.pad)}  ({tal(nieuw)} panden nieuw vastgelegd; "
            f"{tal(uitgesloten)} panden uit andere werklijsten doen niet mee)")
