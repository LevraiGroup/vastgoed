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

Het doelgebied staat in `config.yaml`. Standaard is dat **heel Nederland**
(`doelgebied.nederland: true`): de werklijst van 500 komt uit de landelijke BAG-GeoPackage, voor
het grootste deel uit de grootste gemeenten volgens CBS (zie hieronder). Elke maand:

```bash
pip install -r requirements.txt
python ingest_gpkg.py       # leest data/bron/bag-light_<datum>.gpkg -> data/bag_nl_<datum>.sqlite
python run_proef.py         # selectie voor Nederland -> output/werklijst_nederland_<JJJJ-MM>.csv
                            #   + data/panden_nederland.json (ca. 15-20 min, < 200 MB geheugen)
python build_dashboard.py   # bouwt het dashboard voor het gekozen gebied
```

Voor één stad, zoals Delft (de regressiebasis): zet `doelgebied.nederland: false` met
`steden: ["Delft"]`, en haal de VBO's op met `python ingest.py` (PDOK WFS) in plaats van
`ingest_gpkg.py`. De Delft-cijfers en -CSV's veranderen daar niet door.

Online staat alleen het dashboard (`design/index.html`): Railway bouwt elke push naar `main`
met Railpack (`railpack.json`) en start `serve.py`, dat alleen `design/` serveert met de
standaardbibliotheek van Python, op de poort uit de variabele `PORT`. Lokaal hetzelfde:
`python serve.py`, dan http://localhost:8000/. De pipeline zelf draait niet op Railway.

Het dashboard is alleen te zien na inloggen met het ene gedeelde Levrai-account; zonder
sessie geeft de server alleen de inlogpagina (`web/login.html`). Alles komt uit
Railway-variabelen, die Ayman zet; er staat nooit een waarde in git:

| Variabele | Betekenis | Standaard |
| --- | --- | --- |
| `VASTGOED_GEBRUIKER` | gebruikersnaam van het gedeelde account | geen: zonder deze blijft het dicht |
| `VASTGOED_WACHTWOORD` | wachtwoord van het gedeelde account; alleen spaties telt als leeg | geen: zonder deze blijft het dicht |
| `VASTGOED_SESSIESLEUTEL` | willekeurige tekst van minstens 32 tekens waarmee sessies worden ondertekend | geen: zonder deze, of korter, blijft het dicht |
| `VASTGOED_BLIJVEN_DAGEN` | dagen dat "Ingelogd blijven" geldt | 30 |
| `VASTGOED_POGINGEN` | mislukte inlogs per adres voordat het dichtgaat | 5 |
| `VASTGOED_VENSTER_MIN` | binnen hoeveel minuten die mislukte inlogs tellen | 15 |
| `VASTGOED_BLOKKADE_MIN` | hoeveel minuten een adres daarna dicht is | 15 |
| `VASTGOED_GROOTBOEK` | pad naar het weekgrootboek van betaalde opzoekingen (VA-54), op een Railway-volume; nooit binnen de app-map, want die wordt bij elke deploy vervangen | `grootboek_betaald.json` in `RAILWAY_VOLUME_MOUNT_PATH` (VA-56); zonder beide wordt elke betaalde opzoeking geweigerd |
| `KVK_API_KEY` | sleutel voor de KVK-knop per pand (VA-56); 2 cent per adres, binnen de €2 per week | geen: zonder sleutel zegt de knop dat KVK niet is ingesteld |
| `KVK_BASIS` | `https://api.kvk.nl/api/v2` voor echte gegevens | leeg = de gratis testomgeving van KVK (verzonnen bedrijven) |
| `VASTGOED_WEEKLIMIET_CENT` | lager weekplafond voor alle betaalde bronnen samen, in centen; hoger dan 200 wordt genegeerd | 200 |
| `KVK_API_KEY` | sleutel van KVK (naam staat in `config.yaml`, `betaalde_bronnen`) | geen: dan is KVK "niet ingesteld" |
| `KADASTER_KOOPSOM_KEY` | sleutel van Kadaster Koopsom (idem) | geen: dan is Kadaster "niet ingesteld" |

Het adres dat telt, is de kop `X-Real-IP`, die Railway zet; `X-Forwarded-For` wordt genegeerd.
Waarom: `X-Real-IP` is de enige kop die Railway documenteert voor het adres van de bezoeker
(docs.railway.com, "Specs & Limits"). Dat Railway's proxy een zelf meegestuurde `X-Real-IP`
overschrijft, staat niet in die documentatie maar alleen op Railway's forum, met een meting.
Over `X-Forwarded-For` spreken Railway's eigen antwoorden elkaar tegen (links of rechts te
vertrouwen), en via een CDN staat rechts het CDN-adres in plaats van de bezoeker. Staan er
toch meerdere `X-Real-IP`-regels of een lijst, dan telt de laatste; zonder geldig adres telt
de verbinding zelf. Na de eerste deploy controleren: vijf foute inlogs met een zelfgekozen
`X-Real-IP` en `X-Forwarded-For` moeten het eigen adres dichtzetten (15 minuten), niet het
zelfgekozen adres.

Sessies staan in het geheugen van de server: na elke deploy (dus elke push) moet iedereen
opnieuw inloggen. Lokaal testen: zet de drie eerste variabelen in je eigen shell, nooit in een
bestand in deze map.

Elke maand, na `run_proef.py`: draai `build_dashboard.py` en commit `design/index.html` in
dezelfde commit als de nieuwe `output/*.csv`. Railway bouwt de pagina niet zelf (daar is geen
`data/`), dus alleen zo toont de online versie dezelfde cijfers als de geleverde CSV's. Elke
commit die `build_dashboard.py` of `output/*.csv` wijzigt, neemt de herbouwde
`design/index.html` mee.

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
`drempels.score_min_voor_werklijst`, hoogste score eerst, hoogstens
`drempels.werklijst_max` stuks. De maand in de naam is die van de ophaaldatum van de
snapshot (bij meerdere woonplaatsen de nieuwste), niet die van vandaag. Panden met dezelfde
score staan op hun lotnummer van die maand, de SHA-256 (hexadecimaal, oplopend) van de
tekst `<JJJJ-MM>:<bag_pand_id>`, bijvoorbeeld `2026-08:0503100000000001`, zodat dezelfde
maand altijd dezelfde lijst geeft en een andere maand op de grensscore andere panden kiest.
Komen er minder dan `drempels.werklijst_min` panden in aanmerking, dan meldt
`run_proef.py` hoeveel het er zijn en schrijft het bestand toch.

Alle grenswaarden en scoregewichten staan ook in `config.yaml` en zijn configureerbaar,
zoals de briefing vereist. Bestandsnamen en dashboard-titel volgen automatisch het
gekozen gebied.

## Nachtelijke controle van de werklijst (VA-75)

```bash
python werklijst_controle.py    # nieuwste output/werklijst_nederland_<JJJJ-MM>.csv tegen de PDOK BAG WFS
```

Vraagt voor elk pand van de werklijst bij de PDOK BAG WFS (`bron.wfs_url`, open, geen sleutel)
de huidige pandstatus en de verblijfsobjecten met hun status op: één verzoek per pand, met
OGC Filter XML, één pand tegelijk. De controle **toont alleen**: hij wijzigt geen score, de
werklijst niet, de mastervoorraad niet en `panden_*.json` niet.

Vergeleken wordt met de waarden waaruit de werklijst is gebouwd: `pandstatus` en `vbo_ids` uit de
werklijst, en de status per verblijfsobject uit de snapshot die in de kolom `bron` staat
(`data/bag_nl_<datum>.sqlite`). Die statussen worden één keer per maand uit de snapshot gelezen
(enkele minuten) en bewaard in `data/controle/basis_nederland_<JJJJ-MM>.json`; daarna is de
snapshot voor de controle niet meer nodig. Is er geen snapshot en geen bewaarde basis, dan worden
de statussen van verblijfsobjecten niet vergeleken en zegt de controle dat (`LET OP:`).

Het resultaat is `output/controle/wijzigingen_nederland_<JJJJ-MM>.csv` (gecommit, `;`, UTF-8 met
BOM), één bestand per werklijstmaand, één rij per verschil:

| Kolom | Betekenis |
| --- | --- |
| `bag_pand_id` | het pand |
| `soort` | vaste soort, zie hieronder |
| `wijziging` | wat er veranderd is, in gewone tekst |
| `vbo_id` | het verblijfsobject, bij een wijziging van een verblijfsobject |
| `waarde_werklijst` | de waarde waaruit de werklijst is gebouwd |
| `waarde_nu` | de waarde vannacht bij PDOK |
| `eerst_gezien` | de datum (Nederlandse tijd) van de nacht waarin dit verschil het eerst gezien is |

Soorten: `pand_gesloopt`, `pand_buiten_gebruik`, `pand_niet_gevonden`, `pandstatus` (een andere
pandstatus), `vbo_erbij`, `vbo_weg`, `vbo_status`, en `niet_gecontroleerd`. Let op: de WFS bevat
geen panden met de status "Pand gesloopt" (0 op 2026-11-17); een gesloopt pand verdwijnt uit de
WFS en verschijnt dus als `pand_niet_gevonden`.

Een verschil dat een eerdere nacht al gezien is, houdt zijn `eerst_gezien`; is het pand weer zoals
in de werklijst, dan verdwijnt de rij. Bij `pandstatus`, `pand_*` en `vbo_status` is een andere waarde nu
(bijvoorbeeld eerst buiten gebruik, dan weg) een nieuw verschil met een nieuwe datum. Bij
`vbo_erbij` en `vbo_weg` is het erbij komen of weggaan zelf het verschil: krijgt zo'n
verblijfsobject later een andere status (eerst gevormd, dan in gebruik), dan wordt `waarde_nu`
bijgewerkt en blijft `eerst_gezien` staan. Een pand waarvan het verzoek ook na de herhaling
met wachttijd mislukt, krijgt die nacht een rij `niet_gecontroleerd` (datum = die nacht) en houdt
zijn eerder geziene verschillen. Mislukken `nachtcontrole.stop_na_mislukt` panden achter elkaar,
dan worden de overige niet meer gevraagd en ook `niet_gecontroleerd`. Lukt geen enkel pand (PDOK
plat), dan schrijft de controle niets, blijft het vorige bestand staan en is de exitcode 1.

De uitkomst van de laatste controle (tijdstip, panden gecontroleerd en niet gecontroleerd,
verschillen per soort, aantal verzoeken) staat in `data/controle_werklijst.json`, voor de
nachtelijke run (VA-74). Instellingen staan in `config.yaml` onder `nachtcontrole`; alle paden
zijn ook als argument te geven (`--werklijst`, `--uitvoer`, `--resultaat`, `--basis`,
`--snapshots`).

## Dedup-register: een geleverd pand komt nooit terug

Elke werklijstrun legt zijn panden vast in `register/geleverde_panden.csv`, buiten `output/`
en `data/`, zodat het opnieuw maken van de uitvoer het register nooit wist. Het bestand staat
in git. Per pand één regel met drie kolommen, gescheiden door `;`:

    bag_pand_id;maand;werklijst
    0503100000026198;2026-08;werklijst_delft_2026-08.csv

Er is één register voor alle gebieden (Delft, een provincie, heel Nederland): een pand dat in
een werklijst is geleverd, komt in geen enkele andere werklijst meer, en de lijst vult aan met
de volgende hoogste scores. In de mastervoorraad, het proefresultaat en `panden_<gebied>.json`
zegt `eerder_geselecteerd` `ja` bij elk pand dat in een *andere* werklijst is geleverd; in de
werklijst zelf staat dus altijd `nee`.

Dezelfde maand nog eens draaien geeft hetzelfde bestand en registreert niets dubbel. Staat de
werklijst van die maand al in het register en zou een nieuwe run een andere lijst geven
(bijvoorbeeld omdat `werklijst_max` in `config.yaml` is veranderd), dan stopt `run_proef.py`
met een melding en verandert hij niets: niet het werklijstbestand, niet het register. Een
geleverde lijst verandert nooit stil.

**Met de hand verbeteren.** Open het register in Kladblok (niet in Excel: Excel haalt de `0`
vooraan het BAG-pand-ID weg, en dan stopt de volgende run met een melding over die regel).
- *Een pand per ongeluk geleverd?* Verwijder zijn regel en sla op. Vanaf de volgende maand
  kan het weer op een werklijst komen. De werklijst van de maand waarin het stond, kan daarna
  niet meer opnieuw gemaakt worden; het bestand dat Levrai kreeg, blijft zoals het was.
- *Een pand buiten het systeem om geleverd?* Voeg een regel toe met zijn BAG-pand-ID (16
  cijfers), de maand (`JJJJ-MM`) en een naam voor de levering, bijvoorbeeld `handmatig`.
- Een extra kolom (bijvoorbeeld `opmerking`) en lege regels mogen. Een regel die niet klopt,
  stopt de run met het regelnummer; het register wordt nooit stil als leeg gelezen.

Tests en proefruns op een kopie kunnen een ander register aanwijzen met de omgevingsvariabele
`VASTGOED_REGISTER`.

## De 25 grootste gemeenten (CBS)

Welke gemeenten "de 25 grootste" zijn, staat in `referentie/gemeenten_cbs_<peiljaar>.csv`: alle
gemeenten met hun inwonertal op 1 januari en hun rang, uit CBS-tabel `03759ned` ("Bevolking op 1
januari en gemiddeld; geslacht, leeftijd en regio", open data). Naast het bestand staat
`gemeenten_cbs_<peiljaar>.bron.json` met tabel, titel, peiljaar en ophaaldatum. De gemeentecode is
dezelfde als `bronhouder_identificatie` in de BAG-GeoPackage.

Eens per jaar vernieuwen, nadat CBS de cijfers van 1 januari heeft toegevoegd (in het tweede
kwartaal):

```bash
python cbs_gemeenten.py
```

Dat schrijft een nieuw bestand naast het oude en overschrijft nooit iets. De pipeline gebruikt
het nieuwste peiljaar dat er staat; `run_proef.py` haalt zelf niets op bij CBS en blijft offline.
Is CBS onbereikbaar, of heeft de nieuwste periode geen gemeentecijfers, dan schrijft het script
niets en meldt het waarom.

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
| Slecht/ontbrekend energielabel | +2 | RVO EP-online (maandbestand) | gratis, sleutel in Railway | **actief** — label per pand sinds de snapshot van november; de +2 telt vanaf de werklijst van december (`telt_mee_vanaf`) |

Belangrijke ontwerpkeuze: **leegstand is een kans, geen uitsluiting.** Een pand "buiten
gebruik" wordt daarom niet meer uitgesloten maar krijgt juist punten. Buiten gebruik
(leegstaand) en verbouwing zijn bewust APARTE signalen: het eerste is een duidelijke
kans, het tweede kan al in ontwikkeling zijn.

EP-online-contract (zie module-docstring): `https://public.ep-online.nl/api/v5`, header
`Authorization`, endpoints `/PandEnergielabel/Adres` en `/AdresseerbaarObject/{bag-id}`.
Het signaal staat **aan** (`bronnen.energielabel.actief: true`, `telt_mee: true`), met
`telt_mee_vanaf: "2026-12"`: de geleverde werklijst van november blijft zoals hij is (Ayman,
2026-11-19), en vanaf de snapshot van december telt de +2 mee.

### Energielabel per pand (VA-58)

Twee stappen, beide met `ep_online.py`, en een map die een instelling is
(`bronnen.energielabel.map`, standaard `data/energielabel`, of `--map`):

    railway run -- python ep_online.py ophalen   # het CSV-totaalbestand van de maand -> <map>/v<JJJJMMDD>_v4_csv.zip
    python ep_online.py koppel       # labels voor de snapshot van het doelgebied -> <map>/energielabel_<snapshot>.sqlite

- **De sleutel staat alleen in Railway.** De berekening draait op de laptop, dus `ophalen` loopt via
  `railway run` (Railway CLI, gekoppeld aan de dienst `vastgoed`): die zet `EP_ONLINE_API_KEY` alleen in
  de omgeving van dat ene commando. `koppel` heeft geen sleutel nodig. Eerste koppeling (2026-11-19):
  3.467.008 van de 6.568.913 panden hebben een label (52,8%), 73 minuten.
- **Op Railway** hoort de map op het volume, onder `/data` (daar hangt het volume `vastgoed-volume`),
  bijvoorbeeld `/data/energielabel`: zet `bronnen.energielabel.map` op dat absolute pad, of geef
  `--map /data/energielabel` mee. Buiten het volume is de map na een nieuwe deploy weg, en daarmee de
  maand-zip (ongeveer 230 MB) en de labels per snapshot. `koppel` maakt zijn tijdelijke werkbestand in
  dezelfde map. De standaardwaarde `data/energielabel` is voor de laptop.

- **De sleutel** komt alleen uit de omgevingsvariabele `EP_ONLINE_API_KEY` (op Railway), gaat alleen
  mee in de `Authorization`-header van `GET <api_url>/Mutatiebestand/DownloadInfo?fileType=csv`, en
  wordt nergens geschreven of getoond. De tijdelijke downloadlink uit het antwoord ook niet. Zonder de
  variabele stopt `ophalen` met exitcode 1.
- **Compleet of niet:** de zip komt binnen als `.deel` en krijgt pas zijn naam na de bytecontrole, de
  zipcontrole en de kolomcontrole. Een bestaand bestand wordt nooit overschreven.
- **Kolomcontrole (fail closed):** de kopregel moet precies de kolommen hebben van het echte
  totaalbestand (`KOLOMMEN` in `ep_online.py`, gelezen uit `v20261101_v4_csv.zip` op 2026-11-19). Die
  wijken af van RVO's *Handleiding EP-online.nl Opvragen van bestanden* (januari 2025): het bestand
  noemt ze `Energieklasse`, `BAGVerblijfsobjectID`, `Registratiedatum`, zonder `Pand_`. Boven de kopregel
  staan `PublicatieDatum` en `LaatstVerwerkteMutatievolgnummer`; die worden overgeslagen en bewaard in de
  meta. Hoofdletters en spaties tellen niet. Een ontbrekende of onbekende kolom stopt het commando met
  een melding die haar noemt; er wordt dan niets gepubliceerd.
- **De regel per pand:** het **beste** label van zijn verblijfsobjecten (A+++++ het best, G het
  slechtst), met de registratiedatum van dat label; heeft een verblijfsobject twee registraties, dan
  telt de nieuwste. Een pand zonder verblijfsobject met een labelklasse heeft **geen label**. Regels
  zonder verblijfsobject-ID (ligplaats, standplaats, alleen een pand) en EI-certificaten zonder klasse
  koppelen niet; ze worden geteld. Een misvormde regel (verkeerd aantal velden, geen 16 cijfers,
  onbekende klasse, onleesbare datum) wordt geteld en met regelnummer gemeld. *Keuze van Rex:* het
  verhaal zegt "best known label"; dat is gelezen als het gunstigste label. Daarmee krijgt een pand
  de +2 van VA-101 alleen als geen enkel verblijfsobject beter dan E scoort.
- **Per snapshot:** elke snapshot krijgt een eigen `energielabel_<bestandsnaam van de snapshot>.sqlite`,
  dus een oudere maand houdt de labels die hij had.
- **In de run:** met `actief: true` krijgt elk pandrecord `energielabel` (letter, of leeg = geen label)
  en `energielabel_registratiedatum`; ontbreekt het labelbestand van de snapshot, dan stopt de run.
  Met `actief: false` heeft het record die velden niet. **`telt_mee: false`** houdt de score gelijk:
  de regel in de score-opbouw zegt dan "telt nog niet mee in de score". VA-101 zet hem aan.

**Geparkeerd in [TOEKOMSTVERBETERINGEN.md](TOEKOMSTVERBETERINGEN.md):** leegstand via KVK
(koppeling getest en werkend, wacht op productiesleutel) en verkoophistorie via Kadaster
Koopsom (betaald). Het budget voor de /100-index (`schaal_max`) is nu **26**.

Het **dedup-register** (briefing sectie 7 stap 4) is gebouwd: zie "Dedup-register" hierboven.
Verder nog te bouwen: de maandelijkse mutatiedetectie. Het veld `laatst_beoordeeld` staat al
in de CSV's.

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

## Slot op de werklijst (VA-96)

Zolang Levrai nog niet betaald heeft, laat het dashboard alleen de eerste panden van de werklijst zien. De rest
staat achter één slotblok met de tekst "Ik zal het openzetten, volgt na betaling." Het slot staat in
`config.yaml`:

    werklijst:
      vrij_zichtbaar: 5     # zoveel panden zijn te zien; null of weglaten = alles zichtbaar

Het slot openen is Aymans besluit, gekoppeld aan de betaling. Dan: zet `vrij_zichtbaar` op `null`, draai
`python build_dashboard.py`, commit `design/index.html` en `config.yaml`, en push. Er is geen knop op de pagina
die iets openzet.

Wat het slot niet doet: het is een visueel slot. De gegevens van alle panden staan nog in de broncode van de
pagina, en wie de broncode bekijkt, ziet ze. Ayman koos daarvoor ("statisch afschermen is genoeg"). De
kerncijfers, de band met zijn 500 stippen en de tellingen per gemeente blijven kloppen: een telling noemt
geen pand.
