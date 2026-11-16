"""
De ene bewaker voor alle betaalde opzoekingen (VA-54): weekteller, prijzen, weigeren vóór de call.

Alles wat geld kost, gaat hierlangs; geen script en geen pipeline roept een betaalde bron zelf aan.

- **Plafond:** 200 cent per ISO-week (maandag 00:00 tot zondag 24:00, Europe/Amsterdam), voor
  alle betaalde bronnen samen (Ayman, 2026-11-13). VASTGOED_WEEKLIMIET_CENT mag het lager
  zetten; een hogere of ongeldige waarde wordt genegeerd en 200 geldt.
- **Prijzen** staan in config.yaml (`betaalde_bronnen`), in hele centen; geen prijs = geen call.
- **Eerst reserveren:** de volledige kosten gaan in het grootboekbestand (en dat staat op
  schijf) vóór de eerste uitgaande call. Gaat het plafond erover, dan wordt niets aangeroepen.
- **Dicht bij twijfel:** geen pad (VASTGOED_GROOTBOEK), een onleesbaar of onschrijfbaar
  bestand, of geen te bepalen week: elke betaalde opzoeking wordt geweigerd.
- Kosten blijven staan zodra een vraag de server heeft verlaten, ook bij een fout of timeout
  (de bron kan toch rekenen). Alleen als er niets is verstuurd (`NietVerstuurd`) vervallen ze.

Bedragen zijn overal hele centen (int), nooit floats. Sleutels staan alleen in de omgeving;
deze module schrijft nooit een sleutelwaarde naar een antwoord, het log of een bestand.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

PLAFOND_CENT = 200  # Ayman, 2026-11-13: "at most €2 in total per week". Nooit hoger.
VAR_GROOTBOEK = "VASTGOED_GROOTBOEK"
VAR_WEEKLIMIET = "VASTGOED_WEEKLIMIET_CENT"
GROOTBOEK_VERSIE = 1

# Ayman's regel, woord voor woord (BACKLOG, "Rules for all six"). Niet herschrijven.
WEEKLIMIET = "Weeklimiet van €2 voor betaalde opzoekingen bereikt, weer beschikbaar vanaf maandag"
GEEN_OPSLAG = ("Betaalde opzoekingen staan uit: de weekteller heeft geen vaste opslag. "
               "Er is niets opgevraagd.")
TELLER_ONLEESBAAR = ("Betaalde opzoekingen staan uit: de weekteller is niet te lezen. "
                     "Er is niets opgevraagd.")
TELLER_NIET_BIJGEWERKT = ("Betaalde opzoekingen staan uit: de weekteller kon niet worden bijgewerkt. "
                          "Er is niets opgevraagd.")
WEEK_ONBEKEND = ("Betaalde opzoekingen staan uit: de server kan niet bepalen welke week het is. "
                 "Er is niets opgevraagd.")
ONBEKENDE_BRON = "Deze bron kennen we niet. Er is niets opgevraagd."
GEEN_PRIJS = "{naam} heeft geen geldige prijs. Er is niets opgevraagd."
NIET_GEKOPPELD = "{naam} is nog niet gekoppeld. Er is niets opgevraagd."
NIET_INGESTELD = "{naam} is niet ingesteld. Er is niets opgevraagd."
ONBEKEND_PAND = "Dit pand staat niet in de selectie. Er is niets opgevraagd."
GEEN_ADRES = "Dit pand heeft geen adres dat {naam} kan opzoeken. Er is niets opgevraagd."
LOOPT_AL = "Dit pand wordt al opgezocht bij {naam}. Wacht op dat antwoord."
BRON_FOUT = ("{naam} gaf geen bruikbaar antwoord. De kosten blijven geteld, "
             "omdat de vraag wel is verstuurd.")
NIET_VERSTUURD = "{naam} is niet bereikt. Er is niets gerekend."


# ------------------------------------------------------------------------------ tijd
def _laatste_zondag(jaar: int, maand: int) -> date:
    eind = date(jaar, maand, 31)
    return eind - timedelta(days=(eind.weekday() + 1) % 7)


def amsterdam(moment: float) -> datetime:
    """
    De Amsterdamse kloktijd bij een Unix-tijd. Wintertijd UTC+1, zomertijd UTC+2, van de laatste
    zondag van maart tot de laatste zondag van oktober, telkens om 01:00 UTC (EU-richtlijn
    2000/84/EG). Zelf gerekend, zodat de server geen tijdzonedatabase nodig heeft die op Railway
    misschien ontbreekt; een test vergelijkt het uur voor uur met zoneinfo.
    """
    if not isinstance(moment, (int, float)) or isinstance(moment, bool) or not math.isfinite(moment):
        raise ValueError(f"geen bruikbare tijd: {moment!r}")
    utc = datetime.fromtimestamp(moment, tz=timezone.utc)
    zomer_van = datetime.combine(_laatste_zondag(utc.year, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    zomer_tot = datetime.combine(_laatste_zondag(utc.year, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    uren = 2 if zomer_van <= utc < zomer_tot else 1
    return utc.astimezone(timezone(timedelta(hours=uren)))


def iso_week(moment: float) -> str:
    """'2026-W47': de ISO-week van dit moment in Amsterdam. ValueError als dat niet lukt."""
    try:
        jaar, week, _ = amsterdam(moment).isocalendar()
    except (OverflowError, OSError) as fout:
        raise ValueError(f"geen bruikbare tijd: {moment!r}") from fout
    return f"{jaar}-W{week:02d}"


# ------------------------------------------------------------------------------ prijzen
@dataclass(frozen=True)
class Prijs:
    naam: str              # wat de gebruiker ziet, bijvoorbeeld "KVK"
    cent: int              # per bevraging, hele centen
    sleutel_variabele: str  # naam van de omgevingsvariabele; de waarde staat nooit in een bestand


def lees_prijzen(blok) -> tuple[dict[str, Prijs], dict[str, str]]:
    """
    `betaalde_bronnen` uit config.yaml -> (bruikbare prijzen, {bron: waarom niet}).
    Een prijs moet een heel getal van minstens 1 cent zijn; 2.0, "2", true of 0 telt niet.
    """
    goed: dict[str, Prijs] = {}
    fout: dict[str, str] = {}
    if not isinstance(blok, dict):
        return goed, fout
    for bron, velden in blok.items():
        bron = str(bron)
        if not isinstance(velden, dict):
            fout[bron] = "geen blok met prijs_cent, naam en sleutel_variabele"
            continue
        cent = velden.get("prijs_cent")
        if isinstance(cent, bool) or not isinstance(cent, int) or cent < 1:
            fout[bron] = f"prijs_cent is {cent!r}, geen heel aantal centen van minstens 1"
            continue
        naam = velden.get("naam")
        var = velden.get("sleutel_variabele")
        if not isinstance(naam, str) or not naam.strip():
            fout[bron] = "naam ontbreekt"
            continue
        if not isinstance(var, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", var):
            fout[bron] = f"sleutel_variabele is {var!r}, geen naam van een omgevingsvariabele"
            continue
        goed[bron] = Prijs(naam.strip(), cent, var)
    return goed, fout


def lees_config(pad: Path) -> tuple[dict[str, Prijs], dict[str, str], str]:
    """(prijzen, afgekeurd, melding). Een config die niet te lezen is, geeft geen enkele prijs."""
    try:
        import yaml  # al een afhankelijkheid (requirements.txt); hier pas geladen zodat de server altijd opkomt
        with open(pad, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as fout:  # noqa: BLE001 - elke fout betekent: geen prijzen, dus geen calls
        return {}, {}, f"{pad.name} niet te lezen ({type(fout).__name__}); geen betaalde bron bruikbaar"
    blok = cfg.get("betaalde_bronnen") if isinstance(cfg, dict) else None
    if blok is None:
        return {}, {}, f"{pad.name} heeft geen blok betaalde_bronnen; geen betaalde bron bruikbaar"
    prijzen, afgekeurd = lees_prijzen(blok)
    return prijzen, afgekeurd, ""


def weeklimiet(omgeving: dict[str, str]) -> tuple[int, str]:
    """(plafond in cent, melding voor het log). Nooit meer dan PLAFOND_CENT."""
    ruw = omgeving.get(VAR_WEEKLIMIET, "").strip()
    if not ruw:
        return PLAFOND_CENT, ""
    try:
        waarde = int(ruw)
    except ValueError:
        return PLAFOND_CENT, f"{VAR_WEEKLIMIET} is geen heel getal; {PLAFOND_CENT} cent gebruikt"
    if waarde < 0:
        return PLAFOND_CENT, f"{VAR_WEEKLIMIET} is negatief; {PLAFOND_CENT} cent gebruikt"
    if waarde > PLAFOND_CENT:
        return PLAFOND_CENT, (f"{VAR_WEEKLIMIET}={waarde} is hoger dan Ayman's plafond en wordt "
                              f"genegeerd; {PLAFOND_CENT} cent gebruikt")
    return waarde, ""


# ------------------------------------------------------------------------------ panden
def lees_panden(output_map: Path) -> dict[str, dict]:
    """
    Alle panden uit de gecommitte output/*.csv, per bag_pand_id. Staat een pand in meer bestanden,
    dan geldt de rij met de nieuwste datapeildatum. Alleen lezen; er wordt niets geschreven.
    """
    panden: dict[str, dict] = {}
    for pad in sorted(output_map.glob("*.csv")):
        with open(pad, encoding="utf-8-sig", newline="") as f:
            for rij in csv.DictReader(f, delimiter=";"):
                pid = (rij.get("bag_pand_id") or "").strip()
                if not pid:
                    continue
                peil = rij.get("datapeildatum") or ""
                if pid in panden and panden[pid]["datapeildatum"] >= peil:
                    continue
                panden[pid] = {
                    "bag_pand_id": pid,
                    "hoofdadres": rij.get("hoofdadres") or "",
                    "gekoppelde_adressen": [a.strip() for a in (rij.get("gekoppelde_adressen") or "").split("|")
                                            if a.strip()],
                    "postcode": rij.get("postcode") or "",
                    "woonplaats": rij.get("woonplaats") or "",
                    "datapeildatum": peil,
                }
    return panden


# ------------------------------------------------------------------------------ bronnen
class NietVerstuurd(Exception):
    """Een bron gooit dit alleen als er zeker geen vraag de server heeft verlaten."""


@dataclass(frozen=True)
class Bron:
    """
    Een betaalde bron in code. `aantal(pand)` telt de calls vóóraf; `zoek(pand, sleutel)` doet
    precies zoveel calls en geeft een JSON-baar antwoord, of gooit een fout.
    """
    aantal: Callable[[dict], int]
    zoek: Callable[[dict, str], object]


# Geen enkele bron is in deze story gekoppeld (VA-54: geen live betaalde call). VA-56 en VA-59
# voegen hier KVK en Kadaster toe; tot dan is elke betaalde opzoeking "nog niet gekoppeld".
GEKOPPELD: dict[str, Bron] = {}


# ------------------------------------------------------------------------------ grootboek
class Weigering(Exception):
    """Een opzoeking die niet doorgaat. Er is niets aangeroepen, tenzij `kosten_cent` > 0."""

    def __init__(self, status: int, melding: str, log: str = "", **extra):
        super().__init__(melding)
        self.status, self.melding, self.log, self.extra = status, melding, log, extra


class Grootboek:
    """
    Het weekgrootboek in één JSON-bestand. Elke reservering wordt gelezen, gecontroleerd en
    weggeschreven onder één slot, dus twee gelijktijdige verzoeken kunnen nooit allebei door.
    Het bestand wordt bij elke reservering opnieuw gelezen: een herstart verandert niets, en een
    bestand dat intussen kapot is, sluit meteen alles af.

        {"versie": 1, "weken": {"2026-W47": [{"id", "tijd", "bron", "bag_pand_id", "cent"}, ...]}}
    """

    def __init__(self, pad: Path | None, plafond: int, klok):
        self.pad, self.plafond, self._klok = pad, plafond, klok
        self._slot = threading.Lock()
        self._bezig: set[tuple[str, str]] = set()

    # -- bestand
    def _lees(self) -> dict:
        if not self.pad.exists():
            if not self.pad.parent.is_dir():
                raise OSError(f"map {self.pad.parent} bestaat niet")
            return {"versie": GROOTBOEK_VERSIE, "weken": {}}
        data = json.loads(self.pad.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("versie") != GROOTBOEK_VERSIE:
            raise ValueError("onbekende vorm of versie")
        weken = data.get("weken")
        if not isinstance(weken, dict):
            raise ValueError("geen weken")
        for week, posten in weken.items():
            if not isinstance(posten, list):
                raise ValueError(f"week {week} is geen lijst")
            for p in posten:
                if (not isinstance(p, dict) or isinstance(p.get("cent"), bool)
                        or not isinstance(p.get("cent"), int) or p["cent"] < 0):
                    raise ValueError(f"onleesbare post in {week}")
        return data

    def _schrijf(self, data: dict) -> None:
        tijdelijk = self.pad.with_name(self.pad.name + ".nieuw")
        with open(tijdelijk, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tijdelijk, self.pad)

    @staticmethod
    def totaal(data: dict, week: str) -> int:
        return sum(p["cent"] for p in data["weken"].get(week, []))

    # -- gebruik
    def _week(self) -> tuple[str, float]:
        try:
            nu = self._klok()
            return iso_week(nu), nu
        except Exception as fout:  # noqa: BLE001 - elke klokfout: dicht
            raise Weigering(503, WEEK_ONBEKEND, f"week niet te bepalen ({type(fout).__name__})") from None

    def _lees_of_weiger(self) -> dict:
        try:
            return self._lees()
        except Exception as fout:  # noqa: BLE001 - elke leesfout: dicht
            raise Weigering(503, TELLER_ONLEESBAAR, f"grootboek niet te lezen ({type(fout).__name__})") from None

    def reserveer(self, bron: str, pand_id: str, naam: str, cent: int) -> tuple[str, str, int]:
        """
        Zet `cent` op deze week, op schijf, en geeft (post-id, week, resterend). Weigert met 429
        als het plafond erover zou gaan, en met 409 als dit pand al bij deze bron loopt.
        Na een geslaagde reservering moet `klaar()` altijd volgen.
        """
        if self.pad is None:
            raise Weigering(503, GEEN_OPSLAG, f"{VAR_GROOTBOEK} niet gezet")
        week, nu = self._week()
        with self._slot:
            if (bron, pand_id) in self._bezig:
                raise Weigering(409, LOOPT_AL.format(naam=naam), f"{bron} {pand_id} loopt al")
            data = self._lees_of_weiger()
            uitgegeven = self.totaal(data, week)
            if uitgegeven + cent > self.plafond:
                raise Weigering(429, WEEKLIMIET, f"plafond: {uitgegeven}+{cent} > {self.plafond} in {week}",
                                resterend_cent=max(0, self.plafond - uitgegeven), week=week)
            post_id = secrets.token_hex(8)
            data["weken"].setdefault(week, []).append({
                "id": post_id, "tijd": datetime.fromtimestamp(nu, timezone.utc).isoformat(timespec="seconds"),
                "bron": bron, "bag_pand_id": pand_id, "cent": cent})
            try:
                self._schrijf(data)
            except Exception as fout:  # noqa: BLE001 - niet op schijf = niet gereserveerd = geen call
                raise Weigering(503, TELLER_NIET_BIJGEWERKT,
                                f"grootboek niet te schrijven ({type(fout).__name__})") from None
            self._bezig.add((bron, pand_id))
            return post_id, week, self.plafond - uitgegeven - cent

    def klaar(self, bron: str, pand_id: str) -> None:
        with self._slot:
            self._bezig.discard((bron, pand_id))

    def vrijgeven(self, week: str, post_id: str) -> str:
        """Haalt een reservering weg (alleen als er niets is verstuurd). '' of een logregel."""
        with self._slot:
            try:
                data = self._lees()
                data["weken"][week] = [p for p in data["weken"].get(week, []) if p.get("id") != post_id]
                self._schrijf(data)
            except Exception as fout:  # noqa: BLE001 - dan blijft het geteld: te veel tellen is veilig
                return f"reservering {post_id} niet vrijgegeven ({type(fout).__name__}); blijft geteld"
        return ""


def grootboek_pad(omgeving: dict[str, str], verboden: Path) -> tuple[Path | None, str]:
    """
    Het pad uit VASTGOED_GROOTBOEK, of None met de reden. Een pad binnen de app-map (`verboden`)
    telt niet: die wordt bij elke deploy vervangen, en design/ wordt geserveerd.
    """
    ruw = omgeving.get(VAR_GROOTBOEK, "").strip()
    if not ruw:
        return None, f"{VAR_GROOTBOEK} niet gezet; elke betaalde opzoeking wordt geweigerd"
    pad = Path(ruw).resolve()
    if pad == verboden.resolve() or verboden.resolve() in pad.parents:
        return None, (f"{VAR_GROOTBOEK} wijst in de app-map, die bij elke deploy wordt vervangen; "
                      "elke betaalde opzoeking wordt geweigerd")
    return pad, ""


# ------------------------------------------------------------------------------ de opzoeking
class Bewaker:
    """Alles voor één betaalde opzoeking, in de volgorde waarin niets geld kan kosten tot het moet."""

    def __init__(self, omgeving: dict[str, str], config_pad: Path, output_map: Path, app_map: Path,
                 klok, bronnen: dict[str, Bron] | None = None, log=print):
        self._omgeving = omgeving
        self._log = log
        self.bronnen = GEKOPPELD if bronnen is None else bronnen
        self.prijzen, afgekeurd, melding = lees_config(config_pad)
        self.meldingen = [melding] if melding else []
        self.meldingen += [f"betaalde bron {b} afgekeurd: {r}" for b, r in afgekeurd.items()]
        self.afgekeurd = afgekeurd
        self.plafond, melding = weeklimiet(omgeving)
        if melding:
            self.meldingen.append(melding)
        pad, melding = grootboek_pad(omgeving, app_map)
        if melding:
            self.meldingen.append(melding)
        self.grootboek = Grootboek(pad, self.plafond, klok)
        self._output_map = output_map
        self._panden: dict[str, dict] | None = None
        self._panden_slot = threading.Lock()

    def _pand(self, pand_id: str) -> dict | None:
        with self._panden_slot:
            if self._panden is None:
                try:
                    self._panden = lees_panden(self._output_map)
                except Exception as fout:  # noqa: BLE001 - dan is geen pand bekend
                    self._log(f"BETAALD: panden niet te lezen ({type(fout).__name__})")
                    return None
            return self._panden.get(pand_id)

    def zoek(self, bron: str, pand_id: str) -> tuple[int, dict]:
        """(HTTP-status, JSON-antwoord). Gooit nooit; elke weigering is een antwoord."""
        try:
            return self._zoek(bron, pand_id)
        except Weigering as w:
            if w.log:
                self._log(f"BETAALD geweigerd: {bron} {pand_id}: {w.log}")
            return w.status, {"fout": w.melding, "kosten_cent": 0, **w.extra}

    def _zoek(self, bron: str, pand_id: str) -> tuple[int, dict]:
        if self.grootboek.pad is None:  # dicht bij twijfel, vóór al het andere
            raise Weigering(503, GEEN_OPSLAG)
        prijs = self.prijzen.get(bron)
        if prijs is None:
            if bron in self.afgekeurd:
                raise Weigering(503, GEEN_PRIJS.format(naam=bron), f"prijs: {self.afgekeurd[bron]}")
            raise Weigering(404, ONBEKENDE_BRON)
        code = self.bronnen.get(bron)
        if code is None:
            raise Weigering(503, NIET_GEKOPPELD.format(naam=prijs.naam), "nog niet gekoppeld")
        pand = self._pand(pand_id)
        if pand is None:
            raise Weigering(404, ONBEKEND_PAND)
        sleutel = self._omgeving.get(prijs.sleutel_variabele, "").strip()
        if not sleutel:
            raise Weigering(503, NIET_INGESTELD.format(naam=prijs.naam), f"{prijs.sleutel_variabele} niet gezet")
        try:
            aantal = code.aantal(pand)
        except Exception as fout:  # noqa: BLE001
            raise Weigering(503, GEEN_ADRES.format(naam=prijs.naam), f"aantal niet te tellen ({type(fout).__name__})") from None
        if isinstance(aantal, bool) or not isinstance(aantal, int) or aantal < 1:
            raise Weigering(422, GEEN_ADRES.format(naam=prijs.naam), f"aantal bevragingen {aantal!r}")
        kosten = aantal * prijs.cent

        post_id, week, resterend = self.grootboek.reserveer(bron, pand_id, prijs.naam, kosten)
        self._log(f"BETAALD: {bron} {pand_id} {aantal} x {prijs.cent} = {kosten} cent gereserveerd; "
                  f"{week} nog {resterend} van {self.plafond}")
        try:
            resultaat = code.zoek(pand, sleutel)
            json.dumps(resultaat)
        except NietVerstuurd:
            regel = self.grootboek.vrijgeven(week, post_id)
            self._log(f"BETAALD: {bron} {pand_id} niet verstuurd; " + (regel or f"{kosten} cent vrijgegeven"))
            if regel:  # niet vrijgegeven: dan blijft het ook in het antwoord geteld
                return 502, {"fout": BRON_FOUT.format(naam=prijs.naam), "kosten_cent": kosten,
                             "resterend_cent": resterend, "week": week}
            return 502, {"fout": NIET_VERSTUURD.format(naam=prijs.naam), "kosten_cent": 0,
                         "resterend_cent": resterend + kosten, "week": week}
        except Exception as fout:  # noqa: BLE001 - verstuurd en mislukt: de kosten blijven staan
            self._log(f"BETAALD: {bron} {pand_id} fout na versturen ({type(fout).__name__}); "
                      f"{kosten} cent blijft geteld")
            return 502, {"fout": BRON_FOUT.format(naam=prijs.naam), "kosten_cent": kosten,
                         "resterend_cent": resterend, "week": week}
        finally:
            self.grootboek.klaar(bron, pand_id)
        return 200, {"bron": bron, "bag_pand_id": pand_id, "resultaat": resultaat,
                     "kosten_cent": kosten, "resterend_cent": resterend, "week": week}

