"""
Levrai Group - Pandenselectiesysteem
Snapshots van de BAG-ingest: elke ingest bewaart zijn eigen, gedateerde bestand en
overschrijft nooit een eerder bestand.

Waarom: de maandelijkse mutatiedetectie (TOEKOMSTVERBETERINGEN, punt 4) vergelijkt de
nieuwe maand met de vorige, dus de vorige maand moet blijven bestaan. En
data/vbo_delft.json (augustus 2026) is de enige kopie van de data achter het
goedgekeurde proefresultaat.

Indeling in data/:

    vbo_<plaats>_<JJJJ-MM-DD>.json         de VBO-rijen van één ingest
    vbo_<plaats>_<JJJJ-MM-DD>_<n>.json     tweede, derde ... ingest op dezelfde dag
    vbo_<plaats>_<...>.meta.json           ophaaldatum, tijdstip, aantal, bron

De ophaaldatum staat in de bestandsnaam én in het meta-bestand, zodat hij leesbaar is
zonder de datarijen te openen. Het meta-bestand wordt pas geschreven als de data
volledig op schijf staat; een databestand zonder meta-bestand is een afgebroken
ingest en wordt niet gebruikt.

Oude, ongedateerde bestanden (vbo_<plaats>.json, van vóór deze indeling) worden
gelezen zoals ze zijn: ze worden niet verplaatst, hernoemd of herschreven. Hun
ophaaldatum staat in config.yaml onder snapshots.ongedateerd.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SnapshotFout(RuntimeError):
    """Een snapshot ontbreekt of kan niet worden gekozen."""


@dataclass(frozen=True)
class Snapshot:
    woonplaats: str
    pad: Path
    ophaaldatum: str | None     # JJJJ-MM-DD, of None als die nergens is vastgelegd
    volgnummer: int             # 0 = oud ongedateerd bestand; 1, 2, ... = ingest op die dag
    datumbron: str              # 'meta', 'config' of 'onbekend'

    @property
    def sorteersleutel(self) -> tuple[str, int]:
        return (self.ophaaldatum or "", self.volgnummer)

    def omschrijving(self) -> str:
        if self.ophaaldatum is None:
            datum = "ophaaldatum onbekend"
        elif self.datumbron == "config":
            datum = f"opgehaald {self.ophaaldatum}, vastgelegd in config.yaml"
        else:
            datum = f"opgehaald {self.ophaaldatum}"
        return f"{self.pad.name} ({datum})"


def _meta_pad(data_pad: Path) -> Path:
    return data_pad.with_name(data_pad.stem + ".meta.json")


def _patroon(plaats_slug: str) -> re.Pattern:
    return re.compile(
        rf"^vbo_{re.escape(plaats_slug)}_(\d{{4}}-\d{{2}}-\d{{2}})(?:_(\d+))?\.json$"
    )


def _ongedateerd(cfg: dict) -> dict[str, str]:
    return ((cfg.get("snapshots") or {}).get("ongedateerd") or {})


def lijst(woonplaats: str, plaats_slug: str, data_dir: Path, cfg: dict) -> list[Snapshot]:
    """Alle bruikbare snapshots van een woonplaats, van oud naar nieuw."""
    gevonden: list[Snapshot] = []

    oud = data_dir / f"vbo_{plaats_slug}.json"
    if oud.is_file():
        datum = _ongedateerd(cfg).get(oud.name)
        if datum is not None:
            datum = str(datum)
            if not DATUM_RE.match(datum):
                raise SnapshotFout(
                    f"config.yaml snapshots.ongedateerd: datum {datum!r} voor {oud.name} "
                    "is geen JJJJ-MM-DD."
                )
        gevonden.append(Snapshot(woonplaats, oud, datum, 0, "config" if datum else "onbekend"))

    patroon = _patroon(plaats_slug)
    for pad in sorted(data_dir.glob(f"vbo_{plaats_slug}_*.json")):
        m = patroon.match(pad.name)
        if not m:
            continue  # o.a. de .meta.json-bestanden zelf
        if not _meta_pad(pad).is_file():
            print(f"  ! {pad.name} heeft geen meta-bestand (afgebroken ingest?) en wordt overgeslagen")
            continue
        volgnummer = int(m.group(2) or 1)
        gevonden.append(Snapshot(woonplaats, pad, m.group(1), volgnummer, "meta"))

    return sorted(gevonden, key=lambda s: s.sorteersleutel)


def kies(
    woonplaats: str, plaats_slug: str, data_dir: Path, cfg: dict, keuze: str | None = None
) -> Snapshot:
    """
    Kies de snapshot van een woonplaats.

    keuze None          -> de nieuwste
    keuze 'JJJJ-MM-DD'  -> de nieuwste van die ophaaldatum
    keuze bestandsnaam  -> precies dat bestand (bv. 'vbo_delft.json')
    """
    alle = lijst(woonplaats, plaats_slug, data_dir, cfg)
    if not alle:
        raise SnapshotFout(
            f"Geen snapshot gevonden voor {woonplaats} in {data_dir} "
            f"(verwacht vbo_{plaats_slug}_<datum>.json of vbo_{plaats_slug}.json). "
            "Draai eerst: python ingest.py"
        )
    if not keuze:
        return alle[-1]
    if DATUM_RE.match(keuze):
        passend = [s for s in alle if s.ophaaldatum == keuze]
    else:
        passend = [s for s in alle if s.pad.name == keuze]
    if not passend:
        beschikbaar = ", ".join(s.omschrijving() for s in alle)
        raise SnapshotFout(
            f"Snapshot {keuze!r} bestaat niet voor {woonplaats}. Beschikbaar: {beschikbaar}"
        )
    return passend[-1]


def schrijf(
    woonplaats: str,
    plaats_slug: str,
    rows: list[dict],
    data_dir: Path,
    opgehaald_vanaf: datetime,
    extra_meta: dict | None = None,
) -> Snapshot:
    """
    Schrijf een nieuwe snapshot. Overschrijft nooit: bestaat de naam al, dan krijgt
    de snapshot het volgende volgnummer, en het openen gebeurt exclusief ('x').
    """
    datum = opgehaald_vanaf.date().isoformat()
    volgnummer = 1
    while True:
        achtervoegsel = "" if volgnummer == 1 else f"_{volgnummer}"
        data_pad = data_dir / f"vbo_{plaats_slug}_{datum}{achtervoegsel}.json"
        if not data_pad.exists() and not _meta_pad(data_pad).exists():
            try:
                fh = open(data_pad, "x", encoding="utf-8")
            except FileExistsError:
                volgnummer += 1
                continue
            break
        volgnummer += 1

    with fh:
        json.dump(rows, fh, ensure_ascii=False)

    meta = {
        "woonplaats": woonplaats,
        "ophaaldatum": datum,
        "opgehaald_vanaf": opgehaald_vanaf.isoformat(timespec="seconds"),
        "opgehaald_tot": datetime.now().astimezone().isoformat(timespec="seconds"),
        "aantal_vbo": len(rows),
        "bestand": data_pad.name,
    }
    meta.update(extra_meta or {})
    # Pas na de volledige data: een meta-bestand betekent 'deze ingest is compleet'.
    with open(_meta_pad(data_pad), "x", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    return Snapshot(woonplaats, data_pad, datum, volgnummer, "meta")


def lees(snapshot: Snapshot) -> list[dict]:
    with open(snapshot.pad, encoding="utf-8") as fh:
        return json.load(fh)
