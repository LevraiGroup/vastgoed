"""
Nachtelijke controle op een nieuwere BAG-GeoPackage bij PDOK (VA-72).

Leest de Atom-feed van PDOK (config.yaml geopackage.atom_url) en vergelijkt de datum van de
GeoPackage-entry (zijn eigen <updated>, in Nederlandse tijd) met het nieuwste
bag-light_<datum>.gpkg in de bronmap. Is die niet nieuwer, dan wordt niets gedownload.

Is hij nieuwer, dan komt het bestand binnen onder een tijdelijke naam (bag-light.gpkg.<datum>.deel)
die het patroon bag-light_*.gpkg van ingest_gpkg.py niet raakt. Pas als het aantal bytes gelijk is
aan de length van de feed en aan de Content-Length van PDOK, en de eigen gpkg_contents.last_change
van het bestand nieuwer is dan het nieuwste bestand op schijf, krijgt het zijn eindnaam
bag-light_<datum>.gpkg (datum zoals VA-34: last_change in Nederlandse tijd). Anders blijft het
deelbestand staan; de volgende nacht gaat verder waar hij stopte (HTTP Range) of begint opnieuw.

Er wordt nooit een bestand verwijderd of overschreven. Onder de vrije-ruimtegrens
(geopackage.min_vrij_gb) wordt niets gedownload. De uitkomst gaat naar geopackage.resultaat
(JSON), zodat de nachtelijke run (VA-74) hem kan lezen; een onleesbare feed schrijft niets.

    python gpkg_ophalen.py
    python gpkg_ophalen.py --bron <map> --feed <url> --resultaat <pad> --min-vrij-gb 25

Exitcode 0: niets nieuwers, of nieuw bestand compleet binnen. Anders 1.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import ingest_gpkg
import snapshots
from selectie import load_config, nl_tal

BASE = Path(__file__).parent
ATOM = "{http://www.w3.org/2005/Atom}"
GPKG_TYPE = "application/geopackage+sqlite3"
NAAM_RE = re.compile(r"bag-light_(\d{4}-\d{2}-\d{2})\.gpkg")  # de eindnaam die ingest_gpkg.py leest
BLOK = 1 << 20
GB = 10 ** 9
SLEUTELS = ("atom_url", "bron_map", "resultaat", "min_vrij_gb")  # alle verplicht in config.yaml geopackage


class GpkgFout(RuntimeError):
    """De controle of download kan niet verder; 'uitkomst' zegt waarom, 'bytes' wat er binnenkwam."""

    def __init__(self, uitkomst: str, melding: str, bytes_: int = 0):
        super().__init__(melding)
        self.uitkomst, self.bytes = uitkomst, bytes_


@dataclass(frozen=True)
class FeedEntry:
    datum: str      # JJJJ-MM-DD van <updated>, in Nederlandse tijd
    updated: str    # <updated> zoals in de feed
    href: str
    lengte: int


def instellingen(cfg: dict) -> dict:
    """config.yaml geopackage.*, zonder stille standaardwaarden; paden relatief aan het project."""
    blok = cfg.get("geopackage") if isinstance(cfg, dict) else None
    ontbreekt = [f"geopackage.{k}" for k in SLEUTELS if not isinstance(blok, dict) or blok.get(k) in (None, "")]
    if ontbreekt:
        raise GpkgFout("config", f"config.yaml mist {', '.join(ontbreekt)}.")
    ins = {k: blok[k] for k in SLEUTELS}
    for sleutel in ("bron_map", "resultaat"):
        pad = Path(ins[sleutel])
        ins[sleutel] = pad if pad.is_absolute() else BASE / pad
    return ins


def datum_nl(tekst: str) -> str:
    """'2026-10-31T23:00:12Z' -> '2026-11-01': de datum in Nederlandse tijd (VA-34)."""
    return ingest_gpkg.naar_amsterdam(ingest_gpkg.lees_last_change(tekst)).date().isoformat()


def lees_feed(inhoud: bytes) -> FeedEntry:
    """De GeoPackage-entry uit de Atom-feed van PDOK; GpkgFout als die er niet (leesbaar) in staat."""
    try:
        wortel = ET.fromstring(inhoud)
    except ET.ParseError as fout:
        raise GpkgFout("feed_onleesbaar", f"De Atom-feed is geen leesbare XML: {fout}") from None
    for entry in wortel.iter(f"{ATOM}entry"):
        for link in entry.iter(f"{ATOM}link"):
            if link.get("type") == GPKG_TYPE or (link.get("href") or "").endswith(".gpkg"):
                updated = (entry.findtext(f"{ATOM}updated") or "").strip()
                try:
                    return FeedEntry(datum_nl(updated), updated, link.get("href") or "",
                                     int(link.get("length") or ""))
                except ValueError:
                    raise GpkgFout("feed_onleesbaar", "De GeoPackage-entry in de feed heeft geen geldige "
                                   f"datum of lengte (updated {updated!r}, length "
                                   f"{link.get('length')!r}).") from None
    raise GpkgFout("feed_zonder_gpkg", "De Atom-feed heeft geen GeoPackage-entry.")


def haal_feed(url: str, timeout: float) -> tuple[FeedEntry, int]:
    """(entry, aantal bytes van de feed)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as antwoord:
            inhoud = antwoord.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError) as fout:
        raise GpkgFout("feed_onbereikbaar", f"De Atom-feed {url} is niet bereikbaar: {_netwerkfout(fout)}") from None
    return lees_feed(inhoud), len(inhoud)


def _netwerkfout(fout: BaseException) -> str:
    """De tekst van een netwerkfout; een HTTPError houdt zijn verbinding vast en wordt hier gesloten."""
    if isinstance(fout, urllib.error.HTTPError):
        fout.close()
    return str(fout)


def nieuwste_op_schijf(bron: Path) -> str | None:
    """De datum van het nieuwste bag-light_<datum>.gpkg in de bronmap, of None."""
    datums = sorted(m.group(1) for p in bron.glob("bag-light_*.gpkg") if (m := NAAM_RE.fullmatch(p.name)))
    return datums[-1] if datums else None


def gpkg_datum(pad: Path) -> str:
    """De datum van een GeoPackage: gpkg_contents.last_change van verblijfsobject, in Nederlandse tijd."""
    try:
        with closing(ingest_gpkg.open_gpkg(pad)) as conn:
            rij = conn.execute("SELECT last_change FROM gpkg_contents WHERE table_name = ?",
                               (ingest_gpkg.TABEL,)).fetchone()
    except sqlite3.DatabaseError as fout:
        raise GpkgFout("ongeldig", f"{pad.name} is geen leesbare GeoPackage: {fout}") from None
    if not rij or not rij[0]:
        raise GpkgFout("ongeldig", f"{pad.name}: gpkg_contents heeft geen last_change voor {ingest_gpkg.TABEL}.")
    return datum_nl(rij[0])


def _gb(n: float) -> str:
    """Bytes als GB met één decimaal en een komma: 25000000000 -> '25,0'."""
    return f"{n / GB:.1f}".replace(".", ",")


def _totaal_uit_content_range(waarde: str | None) -> tuple[int, int] | None:
    m = re.fullmatch(r"bytes (\d+)-\d+/(\d+)", (waarde or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def download(href: str, deel: Path, lengte: int, timeout: float) -> int:
    """
    Haal het bestand naar 'deel', of vul een eerder deel aan. Geeft het aantal overgedragen bytes.
    GpkgFout als het niet compleet binnenkomt; het deelbestand blijft dan staan.
    """
    begin = deel.stat().st_size if deel.exists() else 0
    if begin == lengte:
        return 0  # al compleet binnen (een eerdere nacht stopte na de download)
    if begin > lengte:
        begin = 0  # groter dan de feed zegt: opnieuw beginnen
    verzoek = urllib.request.Request(href, headers={"Range": f"bytes={begin}-"} if begin else {})
    overgedragen = 0
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            kop = antwoord.headers.get("Content-Length")
            if begin and antwoord.status == 206:
                bereik = _totaal_uit_content_range(antwoord.headers.get("Content-Range"))
                if bereik != (begin, lengte):
                    raise GpkgFout("onvolledig", f"PDOK gaf Content-Range {antwoord.headers.get('Content-Range')!r}"
                                   f" bij een vervolg vanaf byte {nl_tal(begin)} van {nl_tal(lengte)}.")
                modus = "ab"
            elif antwoord.status == 200:
                begin, modus = 0, "wb"  # geen vervolg mogelijk: het deelbestand wordt vervangen
            else:
                raise GpkgFout("onvolledig", f"PDOK antwoordde met HTTP {antwoord.status}.")
            if kop is None or begin + int(kop) != lengte:
                raise GpkgFout("onvolledig", f"De Content-Length van PDOK ({kop}) past niet bij de length in "
                               f"de feed ({nl_tal(lengte)} bytes, vanaf byte {nl_tal(begin)}); niets gedownload.")
            with open(deel, modus) as fh:
                while blok := antwoord.read(BLOK):
                    fh.write(blok)
                    overgedragen += len(blok)
    except GpkgFout:
        raise
    except (urllib.error.URLError, http.client.HTTPException, OSError) as fout:
        raise GpkgFout("onvolledig", f"De download brak af na {nl_tal(overgedragen)} bytes: {_netwerkfout(fout)}",
                       overgedragen) from None
    grootte = deel.stat().st_size
    if grootte != lengte or overgedragen != int(kop):
        raise GpkgFout("onvolledig", f"Er kwamen {nl_tal(grootte)} van {nl_tal(lengte)} bytes binnen.", overgedragen)
    return overgedragen


def controleer(feed_url: str, bron: Path, min_vrij_gb: float, timeout: float = 60) -> tuple[dict, int]:
    """
    De controle en zo nodig de download. Geeft (resultaat, exitcode). Een onbereikbare of
    onleesbare feed geeft GpkgFout: dan is er niets gedaan en wordt er niets geschreven.
    """
    r: dict = {"gecontroleerd_om": datetime.now().astimezone().isoformat(timespec="seconds"),
               "feed_url": feed_url, "bron_map": str(bron)}
    entry, n_feed = haal_feed(feed_url, timeout)
    nieuwste = nieuwste_op_schijf(bron)
    r.update(feed_datum=entry.datum, feed_updated=entry.updated, feed_lengte=entry.lengte,
             feed_href=entry.href, nieuwste_op_schijf=nieuwste, bytes_overgedragen=n_feed)

    def klaar(uitkomst: str, melding: str, code: int) -> tuple[dict, int]:
        r.update(uitkomst=uitkomst, melding=melding)
        return r, code

    if nieuwste and entry.datum <= nieuwste:
        return klaar("geen_nieuwere", f"Geen nieuwere GeoPackage: PDOK meldt {entry.datum}, het nieuwste "
                     f"bestand op schijf is bag-light_{nieuwste}.gpkg. Niets gedownload.", 0)

    bron.mkdir(parents=True, exist_ok=True)
    deel = bron / f"bag-light.gpkg.{entry.datum}.deel"
    al_binnen = deel.stat().st_size if deel.exists() else 0
    vrij, nodig = shutil.disk_usage(bron).free, min_vrij_gb * GB
    if vrij < nodig:
        return klaar("te_weinig_ruimte", f"Te weinig vrije ruimte voor de GeoPackage van {entry.datum}: "
                     f"{_gb(vrij)} GB vrij, {_gb(nodig)} GB nodig (geopackage.min_vrij_gb). "
                     "Niets gedownload en niets verwijderd.", 1)
    r["deelbestand"] = deel.name
    try:
        n = download(entry.href, deel, entry.lengte, timeout)
        r["bytes_overgedragen"] += n
        datum = gpkg_datum(deel)
    except GpkgFout as fout:
        r["bytes_overgedragen"] += fout.bytes
        return klaar(fout.uitkomst, f"{fout} Het deelbestand {deel.name} blijft staan voor de volgende "
                     f"nacht (nu {nl_tal(deel.stat().st_size if deel.exists() else 0)} bytes, "
                     f"was {nl_tal(al_binnen)}).", 1)
    r["gpkg_datum"] = datum
    if nieuwste and datum <= nieuwste:
        return klaar("niet_nieuwer", f"De feed meldt {entry.datum}, maar de last_change van het gedownloade "
                     f"bestand is {datum}, niet nieuwer dan bag-light_{nieuwste}.gpkg. Niet hernoemd; "
                     f"{deel.name} blijft staan.", 1)
    doel = bron / f"bag-light_{datum}.gpkg"
    try:
        if doel.exists():
            raise FileExistsError(doel)
        snapshots._hernoem_exclusief(deel, doel)  # overschrijft nooit (VA-3, VA-35)
    except FileExistsError:
        return klaar("bestaat_al", f"{doel.name} bestaat al en wordt niet overschreven; {deel.name} blijft staan.", 1)
    r.update(nieuwste_op_schijf=datum, bestand=doel.name)
    return klaar("gedownload", f"Nieuwe GeoPackage binnen: {doel.name} ({nl_tal(entry.lengte)} bytes).", 0)


def schrijf_resultaat(pad: Path, r: dict) -> None:
    """De uitkomst voor VA-74, in één keer vervangen (nooit een half bestand)."""
    pad.parent.mkdir(parents=True, exist_ok=True)
    tijdelijk = pad.with_name(pad.name + ".tmp")
    tijdelijk.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tijdelijk, pad)


def main(argv: list[str] | None = None) -> int:
    try:
        ins = instellingen(load_config())
    except GpkgFout as fout:
        print(f"FOUT: {fout} Niets gedownload en niets geschreven.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description="Controleer bij PDOK op een nieuwere BAG-GeoPackage (VA-72).")
    parser.add_argument("--feed", default=ins["atom_url"], help="URL van de Atom-feed")
    parser.add_argument("--bron", type=Path, default=ins["bron_map"], help="map met bag-light_<datum>.gpkg")
    parser.add_argument("--resultaat", type=Path, default=ins["resultaat"], help="JSON met de uitkomst")
    parser.add_argument("--min-vrij-gb", type=float, default=ins["min_vrij_gb"], help="vrije ruimte vooraf")
    args = parser.parse_args(argv)
    begin = time.monotonic()
    try:
        r, code = controleer(args.feed, args.bron, args.min_vrij_gb)
    except GpkgFout as fout:
        print(f"FOUT: {fout} Niets gedownload en niets geschreven.", file=sys.stderr)
        return 1
    r["seconden"] = round(time.monotonic() - begin, 1)
    schrijf_resultaat(args.resultaat, r)
    print(r["melding"], file=sys.stdout if code == 0 else sys.stderr)
    print(f"Gecontroleerd in {r['seconden']:.1f} s; ".replace(".", ",")
          + f"{nl_tal(r['bytes_overgedragen'])} bytes overgedragen. Uitkomst -> {args.resultaat}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
