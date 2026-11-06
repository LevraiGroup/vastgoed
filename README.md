# Pandenselectiesysteem — Levrai Group

Herhaalbaar systeem dat via BAG/PDOK een mastervoorraad samenstelt en maandelijks
200-500 nog niet behandelde, kansrijke panden oplevert.

**Status:** proefresultaat van 20 panden (Delft) opgeleverd — de controlevraag uit de
briefing. Het volledige systeem wordt pas na inhoudelijke goedkeuring uitgebouwd.

---

## Belangrijkste technische keuze: PDOK WFS, niet de BAG API

De BAG API Individuele Bevragingen (waarvoor de API-key is aangevraagd) is
**niet geschikt** voor deze opdracht. Kadaster stelt expliciet:

> "De API is expliciet niet bedoeld voor bulkbevragingen waarmee veel gegevens in
> 1 keer worden opgevraagd en in een database worden verwerkt. Hiervoor zijn andere
> BAG producten beschikbaar zoals het BAG Extract en de BAG GeoPackage."

Deze opdracht ís bulkverwerking: mastervoorraad, categorie-tellingen over de hele
voorraad, maandelijkse cyclus. Daarom gebruiken we de **PDOK BAG WFS**.

| Bron | Rol in dit systeem |
|---|---|
| **PDOK BAG WFS v2_0** | Primaire bulkbron. Geen key nodig, geen limieten, levert alle benodigde velden. |
| PDOK BAG GeoPackage (7,8 GB) | Reserveroute voor zeer grote steden (Rotterdam/Amsterdam) als partitionering tekortschiet. Maandelijks ververst. |
| BAG API Individuele Bevragingen | Alleen voor **verificatie van losse panden** — waarvoor de API wél bedoeld is. Gebruikt om leads tegen de bronregistratie te controleren. |

De API-key blijft dus nuttig, maar voor steekproefcontrole, niet voor de ingest.

## Twee valkuilen in de PDOK WFS

Beide zijn ontdekt tijdens de bouw en afgevangen in code:

1. **`cql_filter` wordt stilzwijgend genegeerd.** Een query met
   `cql_filter=woonplaats='Delft'` levert géén foutmelding maar `numberMatched=9.978.773`
   — heel Nederland. Alleen **OGC Filter XML** (parameter `filter`) werkt.
   `ingest.py` valideert daarom altijd de hit-count vóór het pagineren.

2. **Paginatieplafond bij `startIndex + count > 51.000`** (harde HTTP 400).
   Delft heeft 61.993 verblijfsobjecten en loopt hier dus tegenaan. Opgelost door
   **partitionering per postcodeprefix**, recursief gesplitst tot elke partitie
   onder het plafond past. Objecten zonder postcode (1.649 in Delft) worden apart
   opgehaald met `PropertyIsNull` — `Not(PropertyIsLike *)` matcht ze niet.

Resultaat: **100,0% dekking** (61.993 van 61.993), gededupliceerd op VBO-ID.

## Koppelsleutels

- **`pandidentificatie`** — primaire sleutel; alle verblijfsobjecten worden hierop
  gegroepeerd tot één acquisitielead (briefing sectie 1).
- **`identificatie`** (VBO) — deduplicatie over partitiegrenzen.

> **Let op:** `gebruiksdoel` is een **meerwaardig veld**. Waarden als
> `'winkelfunctie,woonfunctie'` komen voor op één VBO (87x in Delft). Zonder splitsen
> op komma missen we juist de gemengde panden die deze opdracht zoekt.

## Doelgebied kiezen: stad of provincie

Het doelgebied staat op één plek bovenaan `config.yaml`:

```yaml
doelgebied:
  steden: ["Delft"]        # één of meer woonplaatsen
  provincies: []           # bv. ["Zuid-Holland"] — alle woonplaatsen worden opgehaald
```

- **Stad(en):** vul `steden` met woonplaatsnamen.
- **Provincie(s):** vul `provincies`; de woonplaatsen worden automatisch opgehaald via
  de PDOK Locatieserver (gepagineerd; exacte match zodat "Zuid-Holland" niet ook
  "Noord-Holland" pakt). Let op: een hele provincie is zeer groot.

## Gebruik

```bash
pip install requests pyyaml
python ingest.py            # haalt VBO's op -> data/vbo_<plaats>_<JJJJ-MM-DD>.json (+ .meta.json)
python run_proef.py         # aggregeert, scoort -> output/*.csv + data/panden_<gebied>.json
python build_dashboard.py   # bouwt het dashboard voor het gekozen gebied
```

Elke ingest bewaart een eigen, gedateerde snapshot en overschrijft nooit een eerdere;
twee keer op één dag geeft `..._<datum>_2.json`. De ophaaldatum staat in de bestandsnaam
en in het bijbehorende `.meta.json`. `run_proef.py` en `verrijk.py` lezen standaard de
nieuwste snapshot en melden op scherm welke; een eerdere kies je met
`python run_proef.py --snapshot 2026-08-04`. Het oude `data/vbo_delft.json` (augustus
2026) blijft ongewijzigd staan; de ophaaldatum ervan staat in `config.yaml` onder
`snapshots.ongedateerd`.

De kolom `datapeildatum` in de CSV's is de ophaaldatum van de snapshot waaruit het pand
komt, niet de datum waarop `run_proef.py` draaide. Combineert een gebied meerdere
woonplaatsen, dan draagt elk pand de datum van zijn eigen woonplaats. Heeft een snapshot
geen vastgelegde ophaaldatum, dan stopt `run_proef.py` met een melding die het bestand
noemt; het valt nooit terug op de datum van vandaag.

Naast het proefresultaat en de mastervoorraad schrijft `run_proef.py` de maandelijkse
werklijst: `output/werklijst_<gebied>_<JJJJ-MM>.csv`, met dezelfde kolommen en hetzelfde
formaat als de mastervoorraad. Daarin staan de panden die niet zijn uitgesloten, in
minstens één categorie A-E vallen en een leadscore hebben van minstens
`drempels.score_min_voor_werklijst`, in de volgorde van de mastervoorraad (hoogste score
eerst, dan BAG-pand-ID), hoogstens `drempels.werklijst_max` stuks. De maand in de naam is
die van de ophaaldatum van de snapshot (bij meerdere woonplaatsen de nieuwste), niet die
van vandaag. Komen er minder dan `drempels.werklijst_min` panden in aanmerking, dan meldt
`run_proef.py` hoeveel het er zijn en schrijft het bestand toch.

Alle grenswaarden en scoregewichten staan ook in `config.yaml` en zijn configureerbaar,
zoals de briefing vereist. Bestandsnamen en dashboard-titel volgen automatisch het
gekozen gebied.

## Resultaat Delft (peildatum augustus 2026)

| | Aantal |
|---|---|
| Verblijfsobjecten ingelezen | 61.993 |
| Unieke BAG-panden | 24.008 |
| Uitgesloten | 1.314 |
| **Binnen categorie A-E** | **2.346** |
| Werklijst (score ≥ 8) | 1.655 |

### Technische voorraad per categorie

| Cat. | Aantal | Omschrijving |
|---|---|---|
| A | 348 | Winkel + wonen |
| B | 322 | Bedrijf/kantoor + wonen |
| C | 1.322 | Klein wooncomplex (3-15 woningen) |
| D | 562 | Groot oud pand (<1940, 1-2 eenheden) |
| E | 360 | Afwijkende combinatie |

Een pand kan in meerdere categorieën vallen; de kolom `categorieen` toont alle.

1.655 panden boven de werklijstdrempel biedt ruim voldoende voorraad voor meerdere
maanden à 200-500 leads, vóórdat Den Haag en Rotterdam worden toegevoegd.

## Scoring: bewuste afwijking van de briefing

De briefing kent +5 voor "winkel + wonen" en +4 voor "bedrijf/kantoor + wonen".
Letterlijk toegepast stapelen deze: een winkelpand met woningen én één bergingsobject
(`overige gebruiksfunctie`) krijgt beide bonussen. In de eerste versie scoorden
daardoor 23 panden exact 22 punten, waardoor de top-20 willekeurig werd.

Twee aanpassingen:
- De bonussen sluiten elkaar uit (A of B, niet beide) — het zijn onderscheidende
  categorieën in de briefing.
- `overige gebruiksfunctie` telt alleen als bedrijfsmatig wanneer er géén
  winkelfunctie is; in de praktijk is dit vaak een berging.

Beide zijn terug te draaien in `config.yaml`/`selectie.py` als u de letterlijke
briefingregels prefereert.

## Wat automatisch gaat en wat handmatig blijft

**Automatisch:** ingest, aggregatie per pand-ID, categorisering A-E, uitsluitingen,
leadscore, selectiereden, deduplicatie, CSV-export.

**Handmatig (briefing sectie 6):** visuele controle van de hoogst scorende panden via
kaart, luchtfoto en Street View. Elke lead bevat een `bag_viewer_url` als startpunt.
De velden `visuele_controle`, `beoordeling` en `laatst_beoordeeld` staan klaar.

## Nog niet geïmplementeerd

## Kwalificatie-signalen: staat, leegstand, verkoophistorie

Naast de structuur-signalen kwalificeert het systeem panden op **staat, leegstand en
verkoophistorie** via pluggable bronmodules in `bronnen/`. Elke module voedt één
scoresignaal. Draai `python verrijk.py` om ze op te halen (schrijft
`data/verrijking_<plaats>.json`; `run_proef.py` leest dat automatisch).

| Signaal | Score | Bron | Toegang | Status |
|---|---|---|---|---|
| Buiten gebruik / leegstaand | +4 | BAG-status | **gratis, in data** | **actief** — 2 panden in Delft |
| In verbouwing | +2 | BAG-status | **gratis, in data** | **actief** — 328 panden in Delft |
| Slecht/ontbrekend energielabel | +2 | RVO EP-online v5 | gratis, persoonlijke API-key | module klaar, key nodig |

Belangrijke ontwerpkeuze: **leegstand is een kans, geen uitsluiting.** Een pand "buiten
gebruik" wordt daarom niet meer uitgesloten maar krijgt juist punten. Buiten gebruik
(leegstaand) en verbouwing zijn bewust APARTE signalen: het eerste is een duidelijke
kans, het tweede kan al in ontwikkeling zijn.

EP-online-contract (zie module-docstring): `https://public.ep-online.nl/api/v5`, header
`Authorization`, endpoints `/PandEnergielabel/Adres` en `/AdresseerbaarObject/{bag-id}`.
De module staat standaard **uit** (`bronnen.energielabel.actief: false`); zonder sleutel
blijft het signaal inactief en verandert de score niet.

**Geparkeerd in [TOEKOMSTVERBETERINGEN.md](TOEKOMSTVERBETERINGEN.md):** leegstand via KVK
(koppeling getest en werkend, wacht op productiesleutel) en verkoophistorie via Kadaster
Koopsom (betaald). Het budget voor de /100-index (`schaal_max`) is nu **26**.

Verder nog te bouwen na goedkeuring: het **dedup-register** van eerder behandelde
panden (briefing sectie 7 stap 4) en de maandelijkse mutatiedetectie. De datastructuur
ondersteunt dit al via `eerder_geselecteerd` en `laatst_beoordeeld`.

## Beheerkosten per maand

| Post | Kosten |
|---|---|
| PDOK BAG WFS / GeoPackage | € 0 (open data) |
| BAG API Individuele Bevragingen | € 0 (gratis key, alleen verificatie) |
| Hosting/rekenkracht | € 0-25 (draait op een laptop of kleine VM) |
| RVO EP-online (optioneel) | € 0 (open data) |
| Kadaster koopsommen (optioneel) | vanaf ± € 250/mnd, afhankelijk van volume |

Zonder betaalde databronnen zijn de vaste lasten vrijwel nul; de maandelijkse inspanning
zit in de visuele controle (sectie 6), circa 4-8 uur per 200-500 leads.
