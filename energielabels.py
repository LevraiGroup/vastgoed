"""
Energielabels per pand, per snapshot (VA-58). Geen netwerk: dit leest en schrijft alleen bestanden.

ep_online.py koppelt het maandbestand van EP-online aan een snapshot en schrijft het resultaat naar
<map>/energielabel_<snapshot>.sqlite, met <map> uit config.yaml (bronnen.energielabel.map) en
<snapshot> de volledige bestandsnaam van de snapshot (bijvoorbeeld bag_nl_2026-11-01.sqlite; met extensie,
omdat een JSON- en een SQLite-snapshot van dezelfde dag verder gelijk heten). Zo houdt
een oudere maand de labels die hij had (VA-18): een nieuwe snapshot krijgt een eigen bestand, en een
bestaand bestand wordt nooit overschreven.

Regel per pand (README, "Energielabel per pand"): het beste label van zijn verblijfsobjecten (A+++++
het best, G het slechtst); bij gelijke letters telt de nieuwste registratiedatum. Een pand zonder
verblijfsobject met een label krijgt "geen label". In het bestand staan alleen de panden met een label;
een pand dat er niet in staat, had in die snapshot geen label.

selectie.py leest het bestand alleen als bronnen.energielabel.actief true is. Ontbreekt het dan, dan
stopt de run (fail closed): zonder labels doorgaan mag alleen als het signaal in config.yaml uit staat.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

BASE = Path(__file__).parent
# Van best naar slechtst; de XSD van het totaalbestand (RVO, handleiding januari 2025, bijlage 1).
LABELS = ("A+++++", "A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G")
RANG = {label: i for i, label in enumerate(LABELS)}
SLEUTELS = ("actief", "telt_mee", "map")  # verplicht in config.yaml bronnen.energielabel


class LabelFout(RuntimeError):
    """De labels van een snapshot ontbreken of zijn onleesbaar."""


def instellingen(cfg: dict) -> dict:
    """bronnen.energielabel.{actief, telt_mee, map}, zonder stille standaardwaarden; map relatief aan het project."""
    blok = cfg["bronnen"]["energielabel"]
    ontbreekt = [f"bronnen.energielabel.{k}" for k in SLEUTELS if blok.get(k) in (None, "")]
    if ontbreekt:
        raise LabelFout(f"config.yaml mist {', '.join(ontbreekt)}.")
    for k in ("actief", "telt_mee"):
        if not isinstance(blok[k], bool):
            raise LabelFout(f"config.yaml bronnen.energielabel.{k} moet true of false zijn, niet {blok[k]!r}.")
    pad = Path(blok["map"])
    return {"actief": blok["actief"], "telt_mee": blok["telt_mee"], "map": pad if pad.is_absolute() else BASE / pad}


def bestand_voor(snapshot_pad: Path, map_: Path) -> Path:
    """Het labelbestand van een snapshot: <map>/energielabel_<bestandsnaam van de snapshot>.sqlite."""
    return Path(map_) / f"energielabel_{Path(snapshot_pad).name}.sqlite"


def beter(a: tuple[str, str] | None, b: tuple[str, str] | None) -> tuple[str, str] | None:
    """Het beste van twee (label, registratiedatum); bij gelijk label de nieuwste datum."""
    if a is None:
        return b
    if b is None:
        return a
    if RANG[a[0]] != RANG[b[0]]:
        return a if RANG[a[0]] < RANG[b[0]] else b
    return a if a[1] >= b[1] else b


class Labels:
    """De labels van een of meer snapshots, opgezocht per pand. Leest alleen; houdt niets in het geheugen."""

    def __init__(self, bestanden: list[Path]):
        self._conns: list[sqlite3.Connection] = []
        for pad in bestanden:
            if not pad.is_file():
                self.sluit()
                raise LabelFout(
                    f"Het energielabel staat aan (config.yaml bronnen.energielabel.actief), maar {pad.name} "
                    f"ontbreekt in {pad.parent}. Koppel eerst de labels: python ep_online.py koppel. Of zet "
                    "het signaal uit; zonder labels gaat de run niet verder.")
            try:
                conn = sqlite3.connect(f"{pad.resolve().as_uri()}?mode=ro", uri=True)
                conn.execute("SELECT bag_pand_id, energielabel, registratiedatum FROM pand LIMIT 1").fetchall()
            except sqlite3.DatabaseError as fout:
                self.sluit()
                raise LabelFout(f"{pad.name} is geen leesbaar labelbestand: {fout}") from None
            self._conns.append(conn)

    def voor(self, pand_id: str) -> dict:
        """De velden voor het pandrecord: energielabel (of None = geen label) en registratiedatum."""
        best = None
        for conn in self._conns:
            rij = conn.execute("SELECT energielabel, registratiedatum FROM pand WHERE bag_pand_id = ?",
                               (pand_id,)).fetchone()
            if rij:
                best = beter(best, (rij[0], rij[1]))
        return {"energielabel": best[0] if best else None,
                "energielabel_registratiedatum": best[1] if best else None}

    def sluit(self) -> None:
        for conn in self._conns:
            conn.close()
        self._conns = []


def voor_snapshots(snapshot_paden: list[Path], cfg: dict) -> Labels | None:
    """Labels voor deze snapshots als het signaal aan staat; None als het uit staat. LabelFout als ze ontbreken."""
    ins = instellingen(cfg)
    if not ins["actief"]:
        return None
    return Labels([bestand_voor(p, ins["map"]) for p in snapshot_paden])


def meta(pad: Path) -> dict[str, str]:
    """De meta-tabel van een labelbestand (bronbestand, kolomcontrole, aantallen)."""
    with closing(sqlite3.connect(f"{Path(pad).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        return dict(conn.execute("SELECT sleutel, waarde FROM meta"))
