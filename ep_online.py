"""
EP-online: het maandelijkse totaalbestand met energielabels ophalen en aan een snapshot koppelen (VA-58).

    python ep_online.py ophalen                       # het nieuwste totaalbestand (CSV) naar de map
    python ep_online.py koppel                        # labels voor de snapshot van het doelgebied
    python ep_online.py koppel --snapshot 2026-11-01  # of voor een eerdere snapshot
    python ep_online.py controleer <bestand.zip>      # alleen de kolomcontrole

De map is een instelling: config.yaml bronnen.energielabel.map (relatief aan het project of absoluut),
of --map. Zo werkt hetzelfde commando op de laptop en op Railway.

**De sleutel.** Alleen 'ophalen' heeft hem nodig, en leest hem uit de omgevingsvariabele
EP_ONLINE_API_KEY. Hij gaat uitsluitend mee in de Authorization-header van één verzoek aan
<api_url>/Mutatiebestand/DownloadInfo?fileType=csv (RVO, "Handleiding EP-online.nl Opvragen van
bestanden", januari 2025, par. 3.4). Hij komt nooit in een bestand, een melding, een log of een URL.
Het antwoord geeft een tijdelijke downloadlink met een eigen token; die link wordt ook nooit getoond
of bewaard, en de download zelf krijgt de sleutel niet mee. Zonder de variabele stopt 'ophalen' met
een Nederlandse melding en exitcode 1.

**Compleet of niet.** Het bestand komt binnen als <naam>.deel. Pas als het aantal bytes gelijk is aan
de Content-Length, de zip leesbaar is en precies één CSV bevat, en de kolomcontrole slaagt, krijgt
het zijn eigen naam (v<datum>_v4_csv.zip). Anders wordt het deelbestand verwijderd en blijft alles
zoals het was. Een bestaand bestand wordt nooit overschreven.

**Kolomcontrole (fail closed).** De kopregel van de CSV moet precies de kolommen van KOLOMMEN hebben
(hoofdletters en spaties tellen niet). Mist er een, of staat er een onbekende bij, dan stopt het
commando met een melding die ze noemt, en wordt niets gepubliceerd: geen nieuw zipbestand bij
'ophalen', geen labelbestand bij 'koppel'.

**Koppel.** Leest de CSV regel voor regel in een tijdelijke SQLite in de map (verblijfsobject ->
label en registratiedatum; bij twee registraties van hetzelfde object telt de nieuwste), loopt dan de
panden van de snapshot langs en schrijft per pand het beste label van zijn verblijfsobjecten naar
<map>/energielabel_<snapshot>.sqlite (energielabels.py). Een misvormde regel wordt geteld en gemeld,
niet als crash behandeld. Exitcode 0 als het labelbestand er staat, anders 1.
"""
from __future__ import annotations

import argparse
import csv
import http.client
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import energielabels
import snapshots
from gebieden import resolve, slug
from selectie import DATA, load_config, nl_tal

SLEUTEL_VAR = "EP_ONLINE_API_KEY"
BLOK = 1 << 20
NAAM_RE = re.compile(r"v(\d{8})_v\d+_csv\.zip")  # het totaalbestand, zoals op ep-online.nl/PublicData

# De velden van het totaalbestand, in de volgorde van RVO's "Handleiding EP-online.nl Opvragen van
# bestanden" (januari 2025), bijlage 2 "Verklaring velden totaalbestand". De laatste staat daar zo,
# met spaties; of de CSV hem zo noemt, is pas bij het eerste echte bestand te zien (criterium 7).
KOLOMMEN = (
    "Pand_opnamedatum", "Pand_opnametype", "Pand_status", "Pand_berekeningstype",
    "Pand_energieprestatieindex", "Pand_energieklasse", "Pand_energielabel_is_prive",
    "Pand_is_op_basis_van_referentie_gebouw", "Pand_gebouwklasse", "Meting_geldig_tot",
    "Pand_registratiedatum", "Pand_postcode", "Pand_huisnummer", "Pand_huisletter",
    "Pand_huisnummertoevoeging", "Pand_detailaanduiding", "Pand_bagverblijfsobjectid",
    "Pand_bagligplaatsid", "Pand_bagstandplaatsid", "Pand_bagpandid", "Pand_gebouwtype",
    "Pand_gebouwsubtype", "Pand_projectnaam", "Pand_projectobject", "Pand_SBIcode",
    "Pand_gebruiksoppervlakte_thermische_zone", "Pand_energiebehoefte", "Pand_eis_energiebehoefte",
    "Pand_primaire_fossiele_energie", "Pand_eis_primaire_fossiele_energie",
    "Pand_primaire_fossiele_energie_EMG_Forfaitair", "Pand_aandeel_hernieuwbare_energie",
    "Pand_eis_aandeel_hernieuwbare_energie", "Pand_aandeel_hernieuwbare_energie_EMG_forfaitair",
    "Pand_temperatuuroverschrijding", "Pand_eis_temperatuuroverschrijding", "Pand_warmtebehoefte",
    "Energie Index met EMG forfaitair",
)
VBO, LABEL, DATUM = "Pand_bagverblijfsobjectid", "Pand_energieklasse", "Pand_registratiedatum"
VBO_RE = re.compile(r"\d{16}")
VOORBEELDEN = 5  # zoveel misvormde regels worden met regelnummer en reden gemeld


class EpFout(RuntimeError):
    """Het commando kan niet verder. De melding bevat nooit de sleutel of de downloadlink."""


def _norm(kolom: str) -> str:
    return re.sub(r"\s+", " ", kolom.strip()).lower()


def kolomverschil(kop: list[str]) -> tuple[list[str], list[str]]:
    """(ontbrekend, onbekend) ten opzichte van KOLOMMEN; hoofdletters en spaties tellen niet."""
    verwacht = {_norm(k): k for k in KOLOMMEN}
    gezien = {_norm(k): k for k in kop}
    return ([verwacht[k] for k in verwacht if k not in gezien], [gezien[k] for k in gezien if k not in verwacht])


def _kolomfout(ontbrekend: list[str], onbekend: list[str], naam: str) -> EpFout:
    delen = []
    if ontbrekend:
        delen.append(f"ontbrekende kolommen: {', '.join(ontbrekend)}")
    if onbekend:
        delen.append(f"onbekende kolommen: {', '.join(onbekend)}")
    return EpFout(f"De kolommen van {naam} wijken af van wat de code verwacht ({'; '.join(delen)}). "
                  "Er is niets gepubliceerd. Pas KOLOMMEN in ep_online.py pas aan nadat je het nieuwe "
                  "formaat hebt bekeken.")


def _csv_lid(zf: zipfile.ZipFile, naam: str) -> zipfile.ZipInfo:
    leden = [i for i in zf.infolist() if i.filename.lower().endswith(".csv")]
    if len(leden) != 1:
        raise EpFout(f"{naam} moet precies één CSV-bestand bevatten, niet {len(leden)}.")
    return leden[0]


class Csv:
    """De CSV in de zip, met gecontroleerde kopregel. Een iterator over (regelnummer, velden)."""

    def __init__(self, zip_pad: Path):
        self.naam = Path(zip_pad).name
        try:
            self._zf = zipfile.ZipFile(zip_pad)
            lid = _csv_lid(self._zf, self.naam)
        except zipfile.BadZipFile:
            raise EpFout(f"{self.naam} is geen leesbaar zipbestand.") from None
        except EpFout:
            self._zf.close()
            raise
        self.lid = lid.filename
        self._fh = io.TextIOWrapper(self._zf.open(lid), encoding="utf-8-sig", newline="")
        try:
            eerste = self._fh.readline()
            self.kopregel_vooraf = ""
            regel = 1
            if not re.search(r"pand_", eerste, re.IGNORECASE):
                # Een regel vóór de kopregel (het totaalbestand kent een laatst verwerkt mutatievolgnummer
                # en een aanmaakdatum, handleiding par. 3.1). Hoogstens één; die wordt bewaard in de meta.
                self.kopregel_vooraf, eerste, regel = eerste.strip(), self._fh.readline(), 2
            self.scheiding = ";" if eerste.count(";") >= eerste.count(",") else ","
            self.kop = next(csv.reader([eerste], delimiter=self.scheiding))
        except UnicodeDecodeError:
            self.sluit()
            raise EpFout(f"{self.naam}: de kopregel is geen UTF-8.") from None
        self.kopregelnummer = regel
        ontbrekend, onbekend = kolomverschil(self.kop)
        if ontbrekend or onbekend:
            self.sluit()
            raise _kolomfout(ontbrekend, onbekend, self.naam)
        index = {_norm(k): i for i, k in enumerate(self.kop)}
        self.i_vbo, self.i_label, self.i_datum = (index[_norm(k)] for k in (VBO, LABEL, DATUM))

    def __iter__(self):
        lezer = csv.reader(self._fh, delimiter=self.scheiding)
        try:
            for n, velden in enumerate(lezer, start=self.kopregelnummer + 1):
                yield n, velden
        except (UnicodeDecodeError, csv.Error) as fout:
            raise EpFout(f"{self.naam} is na regel {nl_tal(lezer.line_num)} onleesbaar: "
                         f"{fout.__class__.__name__}. Er is niets gepubliceerd.") from None

    def sluit(self) -> None:
        if getattr(self, "_fh", None):
            self._fh.close()
        self._zf.close()


def controleer_zip(zip_pad: Path) -> dict:
    """De kolomcontrole van een totaalbestand; EpFout bij een afwijking. Geeft wat er gelezen is."""
    c = Csv(zip_pad)
    try:
        return {"bestand": c.naam, "csv": c.lid, "kolommen": len(c.kop), "scheiding": c.scheiding,
                "kopregel_vooraf": c.kopregel_vooraf}
    finally:
        c.sluit()


def lees_datum(tekst: str) -> str | None:
    """'20210304', '2021-03-04', '2021-03-04T00:00:00' of '4-3-2021' -> '2021-03-04'; anders None."""
    t = tekst.strip()
    for patroon, volgorde in ((r"(\d{4})(\d{2})(\d{2})", "jmd"), (r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", "jmd"),
                              (r"(\d{1,2})-(\d{1,2})-(\d{4})(?:[T ].*)?", "dmj")):
        m = re.fullmatch(patroon, t)
        if m:
            a, b, c = (int(x) for x in m.groups())
            j, mnd, d = (a, b, c) if volgorde == "jmd" else (c, b, a)
            try:
                return date(j, mnd, d).isoformat()
            except ValueError:
                return None
    return None


# ------------------------------------------------------------------------------------- ophalen
def _zonder_geheimen(tekst: str, *geheimen: str) -> str:
    for g in geheimen:
        if g:
            tekst = tekst.replace(g, "***")
    return tekst


def _netwerkfout(fout: BaseException) -> str:
    if isinstance(fout, urllib.error.HTTPError):
        code = fout.code
        fout.close()
        return f"HTTP {code}" + (" (sleutel ongeldig of nog niet actief)" if code == 401 else "")
    if isinstance(fout, urllib.error.URLError):
        return f"verbinding mislukt ({fout.reason.__class__.__name__})"
    return fout.__class__.__name__


def downloadinfo(api_url: str, sleutel: str, timeout: float) -> dict:
    """Het antwoord van DownloadInfo voor het CSV-totaalbestand: bestandsnaam en tijdelijke downloadlink."""
    verzoek = urllib.request.Request(f"{api_url.rstrip('/')}/Mutatiebestand/DownloadInfo?fileType=csv",
                                     headers={"Authorization": sleutel, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(verzoek, timeout=timeout) as antwoord:
            info = json.loads(antwoord.read().decode("utf-8"))
    except (urllib.error.URLError, http.client.HTTPException, OSError) as fout:
        raise EpFout(f"EP-online gaf geen downloadinformatie: {_netwerkfout(fout)}.") from None
    except ValueError:
        raise EpFout("EP-online gaf downloadinformatie die geen leesbare JSON is.") from None
    if not isinstance(info, dict) or not isinstance(info.get("bestandsnaam"), str) \
            or not isinstance(info.get("downloadUrl"), str):
        raise EpFout("De downloadinformatie van EP-online mist bestandsnaam of downloadUrl.")
    return info


def _download(url: str, deel: Path, timeout: float) -> int:
    """Haal de link naar 'deel' zonder sleutel; EpFout als hij niet compleet binnenkomt."""
    n = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as antwoord, \
                open(deel, "wb") as fh:
            kop = antwoord.headers.get("Content-Length")
            if antwoord.status != 200 or kop is None:
                raise EpFout(f"De download gaf HTTP {antwoord.status}" +
                             ("" if kop else " zonder Content-Length") + "; niets gepubliceerd.")
            while blok := antwoord.read(BLOK):
                fh.write(blok)
                n += len(blok)
    except EpFout:
        raise
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as fout:
        raise EpFout(f"De download brak af na {nl_tal(n)} bytes: {_netwerkfout(fout)}.") from None
    if n != int(kop):
        raise EpFout(f"Er kwamen {nl_tal(n)} van {nl_tal(int(kop))} bytes binnen; niets gepubliceerd.")
    return n


def ophalen(map_: Path, api_url: str, timeout: float = 120) -> dict:
    """Het nieuwste CSV-totaalbestand naar de map, compleet of niet. EpFout als het niet lukt."""
    sleutel = os.environ.get(SLEUTEL_VAR, "").strip()
    if not sleutel:
        raise EpFout(f"De omgevingsvariabele {SLEUTEL_VAR} ontbreekt of is leeg. Zonder sleutel kan het "
                     "maandbestand van EP-online niet worden opgehaald; niets gedownload. Op Railway staat "
                     "hij als variabele van de dienst.")
    url = ""
    try:
        info = downloadinfo(api_url, sleutel, timeout)
        naam, url = info["bestandsnaam"], info["downloadUrl"]
        if not NAAM_RE.fullmatch(naam):
            raise EpFout(f"EP-online noemt het totaalbestand {naam!r}; verwacht v<JJJJMMDD>_v<n>_csv.zip. "
                         "Niets gedownload.")
        map_.mkdir(parents=True, exist_ok=True)
        doel = map_ / naam
        r = {"bestand": naam, "bestandsdatum": lees_datum(NAAM_RE.fullmatch(naam).group(1))}
        if doel.exists():
            return {**r, "uitkomst": "al_binnen", "bytes": 0,
                    "melding": f"{naam} staat al in {map_}; niets gedownload."}
        deel = map_ / f"{naam}.deel"
        try:
            n = _download(url, deel, timeout)
            r.update(controleer_zip(deel))
            r["bestand"] = naam
            snapshots._hernoem_exclusief(deel, doel)  # overschrijft nooit
        except FileExistsError:
            raise EpFout(f"{naam} bestaat al en wordt niet overschreven.") from None
        finally:
            if deel.exists():
                deel.unlink()
        return {**r, "uitkomst": "gedownload", "bytes": n,
                "melding": f"Totaalbestand binnen: {naam} ({nl_tal(n)} bytes), kolomcontrole geslaagd."}
    except EpFout as fout:
        raise EpFout(_zonder_geheimen(str(fout), sleutel, url)) from None


# --------------------------------------------------------------------------------------- koppel
def nieuwste_zip(map_: Path) -> Path:
    gevonden = sorted((m.group(1), p) for p in Path(map_).glob("v*_csv.zip") if (m := NAAM_RE.fullmatch(p.name)))
    if not gevonden:
        raise EpFout(f"Geen totaalbestand (v<datum>_v4_csv.zip) in {map_}. Draai eerst: python ep_online.py ophalen")
    return gevonden[-1][1]


def _vbo_index(c: Csv, conn: sqlite3.Connection, tel: Counter, voorbeelden: list[str]) -> None:
    """Zet de regels van de CSV in tabel vbo (id -> beste rang, datum); misvormde regels worden geteld."""
    conn.execute("CREATE TABLE vbo (id TEXT PRIMARY KEY, label TEXT NOT NULL, datum TEXT NOT NULL, rang INTEGER NOT NULL)")
    upsert = ("INSERT INTO vbo VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET label = excluded.label, "
              "datum = excluded.datum, rang = excluded.rang WHERE excluded.datum > vbo.datum "
              "OR (excluded.datum = vbo.datum AND excluded.rang < vbo.rang)")
    breedte = len(c.kop)

    def misvormd(n: int, reden: str) -> None:
        tel["misvormd"] += 1
        if len(voorbeelden) < VOORBEELDEN:
            voorbeelden.append(f"regel {nl_tal(n)}: {reden}")

    batch = []
    for n, velden in c:
        tel["regels"] += 1
        if len(velden) != breedte:
            misvormd(n, f"{len(velden)} velden in plaats van {breedte}")
            continue
        vbo, label = velden[c.i_vbo].strip(), velden[c.i_label].strip().upper()
        if vbo and not VBO_RE.fullmatch(vbo):
            misvormd(n, f"verblijfsobject-ID {vbo[:20]!r} is geen 16 cijfers")
            continue
        if label and label not in energielabels.RANG:
            misvormd(n, f"onbekende energieklasse {label[:10]!r}")
            continue
        datum = lees_datum(velden[c.i_datum])
        if label and datum is None:
            misvormd(n, f"registratiedatum {velden[c.i_datum][:20]!r} is geen datum")
            continue
        if not vbo:
            tel["zonder_vbo"] += 1  # ligplaats, standplaats of alleen een pand: niet aan een VBO te koppelen
            continue
        if not label:
            tel["zonder_klasse"] += 1  # een EI-certificaat zonder labelklasse telt als geen label
            continue
        batch.append((vbo, label, datum, energielabels.RANG[label]))
        if len(batch) >= 10_000:
            conn.executemany(upsert, batch)
            batch = []
    if batch:
        conn.executemany(upsert, batch)
    conn.commit()


def _panden(snap: snapshots.Snapshot):
    """(pand-ID, [VBO-ID's]) per pand van de snapshot; de SQLite-route pand voor pand (VA-36)."""
    if snap.soort == "sqlite":
        for vbos in snapshots.stroom_per_pand(snap):
            yield vbos[0]["pandidentificatie"], [v.get("identificatie") or "" for v in vbos]
        return
    per_pand: dict[str, list[str]] = {}
    for rij in snapshots.lees(snap):
        if rij.get("pandidentificatie"):
            per_pand.setdefault(rij["pandidentificatie"], []).append(rij.get("identificatie") or "")
    yield from per_pand.items()


def koppel(zip_pad: Path, snap: snapshots.Snapshot, map_: Path) -> dict:
    """Schrijf <map>/energielabel_<snapshot>.sqlite, compleet of niet. EpFout als het niet lukt."""
    doel = energielabels.bestand_voor(snap.pad, map_)
    if doel.exists():
        raise EpFout(f"{doel.name} bestaat al en wordt niet overschreven: een snapshot houdt de labels die "
                     "hij had. Verwijder het bestand eerst als je opnieuw wilt koppelen.")
    map_.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    tel: Counter = Counter()
    voorbeelden: list[str] = []
    c = Csv(zip_pad)  # de kolomcontrole; bij een afwijking stopt het hier, voordat er iets geschreven is
    with tempfile.TemporaryDirectory(dir=map_, prefix="ep_online_") as werk:
        try:
            with closing(sqlite3.connect(Path(werk) / "vbo.sqlite")) as idx:
                _vbo_index(c, idx, tel, voorbeelden)
                c.sluit()
                deel = Path(werk) / doel.name
                with closing(sqlite3.connect(deel)) as uit:
                    uit.execute("CREATE TABLE pand (bag_pand_id TEXT PRIMARY KEY, energielabel TEXT NOT NULL, "
                                "registratiedatum TEXT NOT NULL)")
                    uit.execute("CREATE TABLE meta (sleutel TEXT PRIMARY KEY, waarde TEXT NOT NULL)")
                    rijen = []
                    for pand_id, vbo_ids in _panden(snap):
                        tel["panden"] += 1
                        best = None
                        ids = [v for v in vbo_ids if v]
                        for i in range(0, len(ids), 500):
                            stuk = ids[i:i + 500]
                            for label, datum in idx.execute(
                                    f"SELECT label, datum FROM vbo WHERE id IN ({','.join('?' * len(stuk))})", stuk):
                                best = energielabels.beter(best, (label, datum))
                        if best:
                            tel["panden_met_label"] += 1
                            rijen.append((pand_id, best[0], best[1]))
                            if len(rijen) >= 10_000:
                                uit.executemany("INSERT INTO pand VALUES (?, ?, ?)", rijen)
                                rijen = []
                    uit.executemany("INSERT INTO pand VALUES (?, ?, ?)", rijen)
                    m = {"bronbestand": Path(zip_pad).name, "csv": c.lid, "snapshot": snap.pad.name,
                         "snapshot_ophaaldatum": snap.ophaaldatum or "", "kolomcontrole": "geslaagd",
                         "kopregel_vooraf": c.kopregel_vooraf,
                         "gekoppeld_om": datetime.now().astimezone().isoformat(timespec="seconds"),
                         "regels": tel["regels"], "misvormd": tel["misvormd"], "zonder_vbo": tel["zonder_vbo"],
                         "zonder_klasse": tel["zonder_klasse"], "panden": tel["panden"],
                         "panden_met_label": tel["panden_met_label"]}
                    uit.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in m.items()])
                    uit.commit()
            if tel["panden"] == 0:
                raise EpFout(f"De snapshot {snap.pad.name} heeft geen panden; niets gepubliceerd.")
            try:
                snapshots._hernoem_exclusief(deel, doel)
            except FileExistsError:
                raise EpFout(f"{doel.name} bestaat al en wordt niet overschreven.") from None
        finally:
            c.sluit()
    m.update(seconden=round(time.monotonic() - begin, 1), voorbeelden=voorbeelden, bestand=doel.name)
    return m


def rapport(m: dict) -> str:
    aandeel = m["panden_met_label"] / m["panden"] * 100 if m["panden"] else 0.0
    regels = [
        f"Kolomcontrole geslaagd: {m['bronbestand']} ({m['csv']}).",
        f"{nl_tal(m['regels'])} regels gelezen; {nl_tal(m['misvormd'])} misvormd, "
        f"{nl_tal(m['zonder_vbo'])} zonder verblijfsobject, {nl_tal(m['zonder_klasse'])} zonder labelklasse.",
        f"{nl_tal(m['panden_met_label'])} van {nl_tal(m['panden'])} panden hebben een label "
        f"({f'{aandeel:.1f}'.replace('.', ',')}%).",
        f"Labels voor {m['snapshot']} -> {m['bestand']}.",
    ]
    regels += [f"  misvormd: {v}" for v in m["voorbeelden"]]
    return "\n".join(regels)


# ----------------------------------------------------------------------------------------- main
def _snapshot(cfg: dict, keuze: str | None) -> snapshots.Snapshot:
    """De snapshot die de run leest: de landelijke als doelgebied.nederland aan staat, anders de stad."""
    if cfg["doelgebied"]["nederland"]:
        import nederland
        return nederland.nieuwste_snapshot(cfg, keuze)
    label, woonplaatsen = resolve(cfg)
    if len(woonplaatsen) != 1:
        raise EpFout("Koppelen kan per snapshot; kies één stad of heel Nederland in config.yaml doelgebied.")
    return snapshots.kies(woonplaatsen[0], slug(woonplaatsen[0]), DATA, cfg, keuze)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EP-online-energielabels ophalen en koppelen (VA-58).")
    parser.add_argument("stap", choices=("ophalen", "koppel", "controleer"))
    parser.add_argument("bestand", nargs="?", type=Path, help="bij controleer en koppel: het totaalbestand (zip)")
    parser.add_argument("--map", type=Path, help="de map voor het totaalbestand en de labels")
    parser.add_argument("--snapshot", help="bij koppel: ophaaldatum JJJJ-MM-DD of bestandsnaam")
    args = parser.parse_args(argv)
    try:
        cfg = load_config()
        ins = energielabels.instellingen(cfg)
        map_ = args.map or ins["map"]
        if args.stap == "ophalen":
            r = ophalen(map_, cfg["bronnen"]["energielabel"]["api_url"])
            print(r["melding"])
        elif args.stap == "controleer":
            if not args.bestand:
                raise EpFout("Geef het totaalbestand: python ep_online.py controleer <bestand.zip>")
            r = controleer_zip(args.bestand)
            print(f"Kolomcontrole geslaagd: {r['bestand']} ({r['csv']}, {r['kolommen']} kolommen).")
        else:
            m = koppel(args.bestand or nieuwste_zip(map_), _snapshot(cfg, args.snapshot), map_)
            print(rapport(m))
    except (EpFout, energielabels.LabelFout, snapshots.SnapshotFout) as fout:
        print(f"FOUT: {fout}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
