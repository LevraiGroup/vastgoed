"""
Landelijke ingest: alle verblijfsobjecten uit de PDOK BAG-GeoPackage in één gedateerde
SQLite-snapshot (VA-34), via de schrijver van VA-35 (snapshots.schrijf_landelijk).

- Leest data/bron/bag-light_<datum>.gpkg alleen-lezen (sqlite3, mode=ro); het bestand verandert niet.
- Alleen de tabel verblijfsobject, zonder join (docs/gpkg_schema.md, VA-33).
- De ophaaldatum is gpkg_contents.last_change, omgerekend naar Nederlandse tijd (VA-4): niet de
  UTC-datum en niet de wijzigingstijd van het bestand.
- Dekking per VA-14: het aantal geschreven rijen tegen COUNT(*) van verblijfsobject. Een tekort
  geeft een Nederlandse waarschuwing; de snapshot wordt toch geschreven ("Warn and write").
- Rijen gaan één voor één door; het geheugen blijft klein (VA-35).

    python ingest_gpkg.py                      # nieuwste data/bron/bag-light_*.gpkg
    python ingest_gpkg.py --gpkg <pad> --data <map>
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import struct
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import snapshots

BASE = Path(__file__).parent
DATA = BASE / "data"
BRON = DATA / "bron"
TABEL = "verblijfsobject"
# Pijplijnveld -> kolom in de snapshot (de GeoPackage-namen), plus de gemeente (VA-34 crit. 4).
KOLOMMEN = {**snapshots.KOLOMMEN_GPKG, "gemeentecode": "gemeentecode"}
LEEG_ALS_NULL = ("huisletter", "toevoeging", "postcode")  # de WFS-vorm: "" in plaats van NULL
# GeoPackage-blob: grootte van de envelope per indicator in de flags-byte (bits 1-3).
ENVELOPE = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


# ------------------------------------------------------------------ datum (VA-4)
def _laatste_zondag(jaar: int, maand: int) -> datetime:
    """De laatste zondag van een maand, 01:00 UTC: het moment van de Europese tijdwissel."""
    dag = datetime(jaar, maand + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    return dag - timedelta(days=(dag.weekday() + 1) % 7)


def naar_amsterdam(utc: datetime) -> datetime:
    """UTC -> Nederlandse tijd met de EU-zomertijdregel; zonder tzdata (geen nieuwe afhankelijkheid)."""
    utc = utc.astimezone(timezone.utc)
    zomer = _laatste_zondag(utc.year, 3) <= utc < _laatste_zondag(utc.year, 10)
    return utc.astimezone(timezone(timedelta(hours=2 if zomer else 1)))


def lees_last_change(tekst: str) -> datetime:
    """'2026-10-31T23:00:12.563Z' -> datetime in UTC."""
    tekst = tekst.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(tekst)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ geometrie
def punt_uit_geom(blob: bytes | None) -> tuple[float, float] | None:
    """(x, y) uit een GeoPackage-puntblob; None als het geen leesbaar punt in RD (28992) is."""
    if not blob or len(blob) < 8 or blob[:2] != b"GP":
        return None
    flags = blob[3]
    hoofd = "<" if flags & 1 else ">"
    envelope = ENVELOPE.get((flags >> 1) & 0b111)
    if envelope is None:
        return None
    (srs,) = struct.unpack(hoofd + "i", blob[4:8])
    wkb = blob[8 + envelope:]
    if srs != 28992 or len(wkb) < 21:
        return None
    orde = "<" if wkb[0] == 1 else ">"
    (soort,) = struct.unpack(orde + "I", wkb[1:5])
    if soort % 1000 != 1:   # 1 = punt; 1001/2001/3001 = punt met Z/M
        return None
    return struct.unpack(orde + "dd", wkb[5:21])


# ------------------------------------------------------------------ lezen
KOLOMMEN_GPKG_SELECT = ["identificatie", "rdf_seealso", "oppervlakte", "status", "gebruiksdoel",
                        "openbare_ruimte_naam", "huisnummer", "huisletter", "toevoeging", "postcode",
                        "woonplaats_naam", "bouwjaar", "pand_identificatie", "pandstatus",
                        "woonplaats_identificatie", "bronhouder_identificatie", "geom"]


def open_gpkg(pad: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{pad.resolve().as_uri()}?mode=ro", uri=True)


class Teller:
    def __init__(self):
        self.rijen = 0
        self.zonder_postcode = 0
        self.niet_gedecodeerd: list[str] = []
        self.zonder_gemeente = 0


def rijen(conn: sqlite3.Connection, teller: Teller) -> Iterator[dict]:
    """Elke VBO als pijplijnrij; een geometrie die niet leesbaar is wordt geteld en genoemd."""
    cur = conn.execute(f"SELECT {', '.join(KOLOMMEN_GPKG_SELECT)} FROM {TABEL} ORDER BY feature_id")
    for r in cur:
        (ident, see, opp, status, doel, straat, nr, letter, toev, pc, wp, bj, pand, pstat,
         wp_id, bronhouder, geom) = r
        punt = punt_uit_geom(geom)
        if punt is None:
            teller.niet_gedecodeerd.append(ident)
        code = (bronhouder or "").strip()
        if not re.fullmatch(r"\d{4}", code):
            teller.zonder_gemeente += 1
        rij = {"identificatie": ident, "rdf_seealso": see, "oppervlakte": opp, "status": status,
               "gebruiksdoel": doel, "openbare_ruimte": straat, "huisnummer": nr,
               "huisletter": letter, "toevoeging": toev, "postcode": pc, "woonplaats": wp,
               "bouwjaar": bj, "pandidentificatie": pand, "pandstatus": pstat,
               "woonplaats_identificatie": wp_id, "gemeentecode": code or None,
               "_x": punt[0] if punt else None, "_y": punt[1] if punt else None}
        for veld in LEEG_ALS_NULL:
            if rij[veld] is None:
                rij[veld] = ""
        if not rij["postcode"]:
            teller.zonder_postcode += 1
        teller.rijen += 1
        yield rij


def piek_geheugen_mb() -> float | None:
    """Piek-werkgeheugen van dit proces (Windows), zoals VA-33 mat; elders None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    meet = k32.K32GetProcessMemoryInfo  # zelfde functie als psapi, zonder 32-bits handle-afkapping
    meet.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    meet.restype = wintypes.BOOL
    if not meet(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.PeakWorkingSetSize / 1e6


def nieuwste_gpkg(map_: Path = BRON) -> Path | None:
    paden = sorted(map_.glob("bag-light_*.gpkg"))
    return paden[-1] if paden else None


def ingest(gpkg: Path, data_dir: Path) -> tuple[snapshots.Snapshot, dict]:
    voor = gpkg.stat()
    begin = time.monotonic()
    with closing(open_gpkg(gpkg)) as conn:
        lc = conn.execute("SELECT last_change FROM gpkg_contents WHERE table_name = ?", (TABEL,)).fetchone()
        if not lc:
            raise snapshots.SnapshotFout(f"{gpkg.name}: gpkg_contents heeft geen rij voor {TABEL}")
        utc = lees_last_change(lc[0])
        lokaal = naar_amsterdam(utc)
        verwacht = conn.execute(f"SELECT COUNT(*) FROM {TABEL}").fetchone()[0]
        teller = Teller()
        meta = {"bron": gpkg.name, "bron_bytes": voor.st_size, "last_change": lc[0],
                "referentie_aantal": verwacht}
        snap = snapshots.schrijf_landelijk(rijen(conn, teller), data_dir, lokaal, extra_meta=meta,
                                           kolommen=KOLOMMEN)
    na = gpkg.stat()
    with closing(sqlite3.connect(f"{snap.pad.resolve().as_uri()}?mode=ro", uri=True)) as s:
        uniek = s.execute("SELECT COUNT(DISTINCT identificatie) FROM vbo").fetchone()[0]
    rapport = {"verwacht": verwacht, "geschreven": teller.rijen, "uniek": uniek,
               "zonder_postcode": teller.zonder_postcode, "niet_gedecodeerd": teller.niet_gedecodeerd,
               "zonder_gemeente": teller.zonder_gemeente, "seconden": round(time.monotonic() - begin),
               "piek_mb": piek_geheugen_mb(), "snapshot_bytes": snap.pad.stat().st_size,
               "gpkg_ongewijzigd": (voor.st_size, voor.st_mtime_ns) == (na.st_size, na.st_mtime_ns),
               "last_change_utc": utc.isoformat(), "ophaaldatum": snap.ophaaldatum}
    return snap, rapport


def nl(n) -> str:
    return f"{n:,}".replace(",", ".")


def main() -> int:
    parser = argparse.ArgumentParser(description="Landelijke VBO-snapshot uit de BAG-GeoPackage (VA-34).")
    parser.add_argument("--gpkg", type=Path, default=None, help="standaard het nieuwste data/bron/bag-light_*.gpkg")
    parser.add_argument("--data", type=Path, default=DATA, help="map voor de snapshot (standaard data/)")
    args = parser.parse_args()
    gpkg = args.gpkg or nieuwste_gpkg()
    if gpkg is None or not gpkg.is_file():
        print(f"FOUT: geen GeoPackage gevonden ({args.gpkg or BRON / 'bag-light_*.gpkg'})", file=sys.stderr)
        return 1
    print(f"GeoPackage {gpkg.name} lezen (alleen-lezen) ...", flush=True)
    try:
        snap, r = ingest(gpkg, args.data)
    except snapshots.SnapshotFout as fout:
        print(f"FOUT: {fout}", file=sys.stderr)
        return 1
    tekort = r["verwacht"] - r["geschreven"]
    if tekort:
        print(f"LET OP: {nl(r['geschreven'])} van {nl(r['verwacht'])} verblijfsobjecten geschreven; "
              f"{nl(tekort)} ontbreken. De snapshot is toch geschreven.", file=sys.stderr)
    if r["niet_gedecodeerd"]:
        print(f"LET OP: {nl(len(r['niet_gedecodeerd']))} geometrieën niet leesbaar (x,y leeg), o.a. "
              f"{', '.join(r['niet_gedecodeerd'][:5])}", file=sys.stderr)
    if r["zonder_gemeente"]:
        print(f"LET OP: {nl(r['zonder_gemeente'])} rijen zonder geldige gemeentecode", file=sys.stderr)
    print(f"Snapshot  -> {snap.pad.name} (opgehaald {snap.ophaaldatum}; last_change {r['last_change_utc']})")
    print(f"Rijen     : {nl(r['geschreven'])} van {nl(r['verwacht'])}, uniek {nl(r['uniek'])}, "
          f"zonder postcode {nl(r['zonder_postcode'])}")
    piek = f"{r['piek_mb']:.0f} MB" if r["piek_mb"] is not None else "niet gemeten"
    print(f"Tijd      : {r['seconden']} s; piekgeheugen {piek}; snapshot {nl(r['snapshot_bytes'])} bytes")
    print(f"GeoPackage ongewijzigd: {'ja' if r['gpkg_ongewijzigd'] else 'NEE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
