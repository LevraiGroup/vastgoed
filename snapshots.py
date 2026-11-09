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

SQLite-snapshots (VA-35), voor gebieden die niet in het geheugen passen:

    vbo_<plaats>_<JJJJ-MM-DD>[_<n>].sqlite  de VBO's van één gebied
    bag_nl_<JJJJ-MM-DD>[_<n>].sqlite        de VBO's van heel Nederland
    <naam>.sqlite.deel                      nog in aanbouw of afgebroken

Eén bestand met de tabellen 'vbo' (de rijen) en 'meta' (sleutel, waarde; met o.a.
ophaaldatum). Het bestand krijgt een tijdelijke naam, de tabel meta wordt als laatste
geschreven en pas daarna krijgt het bestand zijn eindnaam. Alleen een bestand met een
eindnaam én een meta-tabel met de juiste ophaaldatum telt als compleet. De ophaaldatum
wordt uit meta gelezen zonder de datarijen te openen.

Een landelijke snapshot doet alleen mee als daarom gevraagd wordt (landelijk=True of de
bestandsnaam), zodat de standaardkeuze van een gebied niet ongemerkt verandert.

Woonplaatsnamen zijn landelijk niet uniek (70 namen, o.a. Beek driemaal; docs/gpkg_schema.md).
Lees zo'n plaats op woonplaats_id; op de naam alleen stopt stroom() met een fout.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATUM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEEL = ".deel"              # achtervoegsel van een snapshot die nog niet compleet is
LANDELIJK_BASIS = "bag_nl"
NEDERLAND = "Nederland"     # een landelijke snapshot met deze naam leest het hele land

# Veld in de pijplijn -> kolom in de tabel vbo. Staat ook in de meta-tabel van elke
# snapshot, zodat een andere indeling (VA-33, VA-34) hier geen codewijziging vraagt.
KOLOMMEN_STANDAARD = {
    veld: veld
    for veld in (
        "identificatie", "rdf_seealso", "oppervlakte", "status", "gebruiksdoel",
        "openbare_ruimte", "huisnummer", "huisletter", "toevoeging", "postcode",
        "woonplaats", "bouwjaar", "pandidentificatie", "pandstatus", "_x", "_y",
    )
}

# De kolomnamen van de GeoPackage (VA-33, docs/gpkg_schema.md), plus de sleutel die
# woonplaatsen met dezelfde naam uit elkaar houdt. _x en _y komen uit geom.
KOLOMMEN_GPKG = {
    **KOLOMMEN_STANDAARD,
    "pandidentificatie": "pand_identificatie",
    "openbare_ruimte": "openbare_ruimte_naam",
    "woonplaats": "woonplaats_naam",
    "woonplaats_identificatie": "woonplaats_identificatie",
}


class SnapshotFout(RuntimeError):
    """Een snapshot ontbreekt of kan niet worden gekozen."""


@dataclass(frozen=True)
class Snapshot:
    woonplaats: str
    pad: Path
    ophaaldatum: str | None     # JJJJ-MM-DD, of None als die nergens is vastgelegd
    volgnummer: int             # 0 = oud ongedateerd bestand; 1, 2, ... = ingest op die dag
    datumbron: str              # 'meta', 'config' of 'onbekend'
    soort: str = "json"         # 'json' of 'sqlite'
    landelijk: bool = False     # True: bag_nl-bestand, gelezen voor alleen 'woonplaats'

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


def _quote(naam: str) -> str:
    return '"' + naam.replace('"', '""') + '"'


def _open_alleen_lezen(pad: Path) -> sqlite3.Connection:
    return sqlite3.connect(pad.resolve().as_uri() + "?mode=ro", uri=True)


def _lees_meta(pad: Path) -> dict[str, str] | None:
    """De meta-tabel van een SQLite-snapshot, of None als het bestand niet compleet is."""
    try:
        with closing(_open_alleen_lezen(pad)) as conn:
            tabellen = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            if not {"meta", "vbo"} <= tabellen:
                return None
            return dict(conn.execute("SELECT sleutel, waarde FROM meta"))
    except sqlite3.Error:
        return None


def _sqlite_snapshots(
    patroon: re.Pattern, kandidaten: Iterable[Path], woonplaats: str, landelijk: bool
) -> list[Snapshot]:
    gevonden: list[Snapshot] = []
    for pad in sorted(kandidaten):
        m = patroon.match(pad.name)
        if not m:
            continue
        meta = _lees_meta(pad)
        if meta is None:
            print(f"  ! {pad.name} heeft geen complete meta-tabel (afgebroken ingest?) en wordt overgeslagen")
            continue
        if meta.get("ophaaldatum") != m.group(1):
            print(f"  ! {pad.name}: de ophaaldatum in meta wijkt af van de bestandsnaam; wordt overgeslagen")
            continue
        volgnummer = int(m.group(2) or 1)
        gevonden.append(Snapshot(woonplaats, pad, m.group(1), volgnummer, "meta", "sqlite", landelijk))
    return gevonden


def _sqlite_patroon(basis: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(basis)}_(\d{{4}}-\d{{2}}-\d{{2}})(?:_(\d+))?\.sqlite$")


def lijst(
    woonplaats: str, plaats_slug: str, data_dir: Path, cfg: dict, landelijk: bool = False
) -> list[Snapshot]:
    """Alle bruikbare snapshots van een woonplaats, van oud naar nieuw.

    Op dezelfde datum en met hetzelfde volgnummer telt SQLite als nieuwer dan JSON.
    Met landelijk=True doen ook de bag_nl-bestanden mee.
    """
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

    basissen = [(f"vbo_{plaats_slug}", False)] + ([(LANDELIJK_BASIS, True)] if landelijk else [])
    for basis, is_landelijk in basissen:
        for pad in sorted(data_dir.glob(f"{basis}_*.sqlite{DEEL}")):
            print(f"  ! {pad.name} is niet compleet (tijdelijke naam) en wordt overgeslagen")
        gevonden += _sqlite_snapshots(
            _sqlite_patroon(basis), data_dir.glob(f"{basis}_*.sqlite"), woonplaats, is_landelijk
        )

    return sorted(gevonden, key=lambda s: s.sorteersleutel)


def kies(
    woonplaats: str,
    plaats_slug: str,
    data_dir: Path,
    cfg: dict,
    keuze: str | None = None,
    landelijk: bool = False,
) -> Snapshot:
    """
    Kies de snapshot van een woonplaats.

    keuze None          -> de nieuwste
    keuze 'JJJJ-MM-DD'  -> de nieuwste van die ophaaldatum
    keuze bestandsnaam  -> precies dat bestand (bv. 'vbo_delft.json')

    Een bag_nl-bestand wordt alleen gekozen met landelijk=True of met zijn bestandsnaam.
    """
    landelijk = landelijk or bool(keuze and _sqlite_patroon(LANDELIJK_BASIS).match(keuze))
    alle = lijst(woonplaats, plaats_slug, data_dir, cfg, landelijk=landelijk)
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


def _hernoem_exclusief(bron: Path, doel: Path) -> None:
    """Geef een compleet bestand zijn eindnaam; een bestaand doel blijft onaangeroerd."""
    if os.name == "nt":
        os.rename(bron, doel)   # faalt op Windows altijd als het doel bestaat
    else:
        os.link(bron, doel)     # os.rename zou op POSIX overschrijven
        os.unlink(bron)


def _schrijf_sqlite(
    basis: str,
    woonplaats: str,
    rows: Iterable[Mapping],
    data_dir: Path,
    opgehaald_vanaf: datetime,
    extra_meta: dict | None,
    kolommen: Mapping[str, str] | None,
    landelijk: bool,
) -> Snapshot:
    kolommen = dict(kolommen or KOLOMMEN_STANDAARD)
    datum = opgehaald_vanaf.date().isoformat()
    volgnummer = 1
    while True:
        achtervoegsel = "" if volgnummer == 1 else f"_{volgnummer}"
        eind_pad = data_dir / f"{basis}_{datum}{achtervoegsel}.sqlite"
        deel_pad = eind_pad.with_name(eind_pad.name + DEEL)
        # Een achtergebleven .deel-bestand blijft staan: de snapshot neemt het volgende nummer.
        if not eind_pad.exists() and not deel_pad.exists():
            try:
                open(deel_pad, "x").close()
            except FileExistsError:
                volgnummer += 1
                continue
            break
        volgnummer += 1

    velden = tuple(kolommen)
    aantal = 0

    def waarden() -> Iterator[tuple]:
        # Eén rij tegelijk: executemany vraagt ze pas op als ze aan de beurt zijn.
        nonlocal aantal
        for rij in rows:
            if not rij.keys() <= kolommen.keys():
                raise SnapshotFout(
                    f"Rij heeft velden zonder kolom: {sorted(rij.keys() - kolommen.keys())}"
                )
            aantal += 1
            yield tuple(rij.get(veld) for veld in velden)

    try:
        with closing(sqlite3.connect(deel_pad)) as conn:
            # Kolommen zonder type: SQLite laat '0503...' dan een tekst met voorloopnul.
            lijst_kolommen = ", ".join(_quote(k) for k in kolommen.values())
            conn.execute(f"CREATE TABLE vbo ({lijst_kolommen})")
            plekken = ", ".join("?" for _ in velden)
            conn.executemany(f"INSERT INTO vbo VALUES ({plekken})", waarden())
            conn.commit()
            # Twee losse indexen: een index op (naam, id) zou ORDER BY rowid laten sorteren.
            for veld, index in (
                ("woonplaats", "vbo_woonplaats"),
                ("woonplaats_identificatie", "vbo_woonplaats_id"),
            ):
                if veld in kolommen:
                    conn.execute(f"CREATE INDEX {index} ON vbo ({_quote(kolommen[veld])})")

            meta = {
                "woonplaats": woonplaats,
                "ophaaldatum": datum,
                "opgehaald_vanaf": opgehaald_vanaf.isoformat(timespec="seconds"),
                "opgehaald_tot": datetime.now().astimezone().isoformat(timespec="seconds"),
                "aantal_vbo": aantal,
                "bestand": eind_pad.name,
                "kolommen": kolommen,
            }
            meta.update(extra_meta or {})
            # Pas na de volledige data: een meta-tabel betekent 'deze ingest is compleet'.
            conn.execute("CREATE TABLE meta (sleutel TEXT PRIMARY KEY, waarde TEXT NOT NULL)")
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                (
                    (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
                    for k, v in meta.items()
                ),
            )
            conn.commit()
        _hernoem_exclusief(deel_pad, eind_pad)
    except BaseException:
        deel_pad.unlink(missing_ok=True)    # ons eigen, exclusief aangemaakte bestand
        raise

    return Snapshot(woonplaats, eind_pad, datum, volgnummer, "meta", "sqlite", landelijk)


def schrijf_sqlite(
    woonplaats: str,
    plaats_slug: str,
    rows: Iterable[Mapping],
    data_dir: Path,
    opgehaald_vanaf: datetime,
    extra_meta: dict | None = None,
    kolommen: Mapping[str, str] | None = None,
) -> Snapshot:
    """Schrijf een SQLite-snapshot van één gebied; 'rows' mag een iterator zijn."""
    return _schrijf_sqlite(
        f"vbo_{plaats_slug}", woonplaats, rows, data_dir, opgehaald_vanaf, extra_meta, kolommen, False
    )


def schrijf_landelijk(
    rows: Iterable[Mapping],
    data_dir: Path,
    opgehaald_vanaf: datetime,
    extra_meta: dict | None = None,
    kolommen: Mapping[str, str] | None = None,
) -> Snapshot:
    """Schrijf een landelijke SQLite-snapshot (bag_nl_<datum>.sqlite), standaard met KOLOMMEN_GPKG."""
    return _schrijf_sqlite(
        LANDELIJK_BASIS,
        NEDERLAND,
        rows,
        data_dir,
        opgehaald_vanaf,
        extra_meta,
        kolommen or KOLOMMEN_GPKG,
        True,
    )


def _kolomindeling(
    conn: sqlite3.Connection, snapshot: Snapshot, kolommen: Mapping[str, str] | None
) -> dict[str, str]:
    """Veld -> kolom: de opgegeven indeling, anders die uit meta, anders de kolomnamen zelf."""
    bestaand = [r[1] for r in conn.execute("PRAGMA table_info(vbo)")]
    if kolommen is None:
        rij = conn.execute("SELECT waarde FROM meta WHERE sleutel = 'kolommen'").fetchone()
        kolommen = json.loads(rij[0]) if rij else {k: k for k in bestaand}
    # Vooraf nodig: SQLite leest een onbekende "naam" stilzwijgend als tekst.
    ontbreekt = sorted(set(kolommen.values()) - set(bestaand))
    if ontbreekt:
        raise SnapshotFout(f"{snapshot.pad.name}: kolommen bestaan niet in vbo: {ontbreekt}")
    return dict(kolommen)


def stroom(
    snapshot: Snapshot,
    kolommen: Mapping[str, str] | None = None,
    woonplaats_id: str | None = None,
) -> Iterator[dict]:
    """
    Geef de rijen van een snapshot één voor één, in de volgorde van de ingest.

    Een landelijke snapshot geeft alleen de rijen van snapshot.woonplaats (of alles bij
    NEDERLAND); met woonplaats_id alleen die woonplaats, ongeacht de naam. 'kolommen'
    (veld -> kolom) gaat voor de indeling uit meta. Een JSON-snapshot staat in één
    bestand en wordt daarom wel eerst helemaal gelezen.
    """
    if snapshot.soort != "sqlite":
        if woonplaats_id is not None:
            raise SnapshotFout(f"{snapshot.pad.name}: een JSON-snapshot kent geen woonplaats_id.")
        yield from lees(snapshot)
        return

    with closing(_open_alleen_lezen(snapshot.pad)) as conn:
        indeling, sql, parameters, filterwaarde = _vraag(conn, snapshot, kolommen, woonplaats_id)
        velden = tuple(indeling)
        sql += " ORDER BY rowid"  # kost geen sortering: tabel en index liggen al op rowid

        gevonden = False
        for rij in conn.execute(sql, parameters):
            gevonden = True
            yield dict(zip(velden, rij))
    if filterwaarde is not None and not gevonden:
        raise SnapshotFout(f"{snapshot.pad.name} bevat geen rijen voor {filterwaarde!r}.")


def _vraag(
    conn: sqlite3.Connection,
    snapshot: Snapshot,
    kolommen: Mapping[str, str] | None,
    woonplaats_id: str | None,
) -> tuple[dict[str, str], str, tuple, str | None]:
    """(indeling, SELECT zonder ORDER BY, parameters, filterwaarde of None) voor een snapshot."""
    indeling = _kolomindeling(conn, snapshot, kolommen)
    selectie = ", ".join(_quote(k) for k in indeling.values())
    sql = f"SELECT {selectie} FROM vbo"
    parameters: tuple = ()
    filterveld, filterwaarde = None, None
    if woonplaats_id is not None:
        filterveld, filterwaarde = "woonplaats_identificatie", woonplaats_id
    elif snapshot.landelijk and snapshot.woonplaats != NEDERLAND:
        filterveld, filterwaarde = "woonplaats", snapshot.woonplaats
    filteren = filterveld is not None
    if filteren:
        if filterveld not in indeling:
            raise SnapshotFout(f"{snapshot.pad.name}: geen kolom voor het veld {filterveld}.")
        voorwaarde = f" WHERE {_quote(indeling[filterveld])} = ?"
        parameters = (filterwaarde,)
        if filterveld == "woonplaats" and "woonplaats_identificatie" in indeling:
            id_kolom = _quote(indeling["woonplaats_identificatie"])
            ids = [
                r[0]
                for r in conn.execute(
                    f"SELECT DISTINCT {id_kolom} FROM vbo{voorwaarde}", parameters
                )
            ]
            if len(ids) > 1:
                raise SnapshotFout(
                    f"{snapshot.pad.name}: de naam {filterwaarde!r} hoort bij meer dan één "
                    f"woonplaats ({', '.join(sorted(map(str, ids)))}). Kies met woonplaats_id."
                )
        sql += voorwaarde
    return indeling, sql, parameters, (filterwaarde if filteren else None)


# Een landelijke snapshot (2,9 GB) sorteren op pand kost tijdelijke ruimte van dezelfde orde.
# Die gaat naar VASTGOED_SQLITE_TMP (of de map van de snapshot), nooit naar de systeem-TEMP op C:.
VAR_TMP = "VASTGOED_SQLITE_TMP"


def stroom_per_pand(
    snapshot: Snapshot,
    kolommen: Mapping[str, str] | None = None,
    woonplaats_id: str | None = None,
    tmp_map: Path | None = None,
) -> Iterator[list[dict]]:
    """
    Geef de VBO's van een SQLite-snapshot pand voor pand (VA-36): telkens de lijst rijen van
    één pandidentificatie, binnen het pand in de volgorde van de ingest (de eerste VBO is
    dezelfde als in aggregeer()). De panden komen op volgorde van hun ID. Er staat nooit
    meer dan één pand tegelijk in het geheugen.
    """
    if snapshot.soort != "sqlite":
        raise SnapshotFout(f"{snapshot.pad.name}: alleen een SQLite-snapshot kan per pand stromen.")
    tmp = Path(tmp_map or os.environ.get(VAR_TMP) or snapshot.pad.parent)
    with closing(_open_alleen_lezen(snapshot.pad)) as conn:
        conn.execute("PRAGMA temp_store = FILE")
        pad_sql = tmp.resolve().as_posix().replace("'", "''")  # een ' in het pad breekt de PRAGMA niet
        conn.execute(f"PRAGMA temp_store_directory = '{pad_sql}'")
        conn.execute("PRAGMA cache_size = -65536")  # 64 MB paginacache
        indeling, sql, parameters, filterwaarde = _vraag(conn, snapshot, kolommen, woonplaats_id)
        if "pandidentificatie" not in indeling:
            raise SnapshotFout(f"{snapshot.pad.name}: geen kolom voor pandidentificatie.")
        velden = tuple(indeling)
        pand_kolom = _quote(indeling["pandidentificatie"])
        sql += f" ORDER BY {pand_kolom}, rowid"
        huidig, rijen = None, []
        for waarden in conn.execute(sql, parameters):
            rij = dict(zip(velden, waarden))
            pand = rij["pandidentificatie"]
            if not pand:
                continue  # een VBO zonder pand hoort bij geen lead (zoals in aggregeer())
            if pand != huidig and rijen:
                yield rijen
                rijen = []
            huidig = pand
            rijen.append(rij)
        if rijen:
            yield rijen
        elif filterwaarde is not None:
            raise SnapshotFout(f"{snapshot.pad.name} bevat geen rijen voor {filterwaarde!r}.")


def lees(snapshot: Snapshot) -> list[dict]:
    if snapshot.soort == "sqlite":
        return list(stroom(snapshot))
    with open(snapshot.pad, encoding="utf-8") as fh:
        return json.load(fh)
