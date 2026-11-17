# Kopij VA-37 (crit. 5) en VA-39 (eerste plak "alleen NL"): Lumi, 2026-11-09

Sleutels tussen accolades komen uit de cijfers. Ze worden in Python opgebouwd en niet in het
script van de pagina (LESSONS, VA-31). Getallen krijgen een punt voor de duizendtallen. De
voorbeelden gebruiken de eerste landelijke run: GeoPackage van 1 nov 2026, 500 panden op de
werklijst, waarvan 450 uit de 25 grootste gemeenten en 50 elders.

## 1. VA-37, criterium 5: kolom in de werklijst-CSV

| Concept | Goedgekeurd | Waarden |
| --- | --- | --- |
| `in_25_grootste_gemeenten` | **`grote_gemeente`** | `ja` / `nee` |

**Gewijzigd.** Het getal 25 is `drempels.aantal_grote_gemeenten` in `config.yaml`. Staat die
op 30, dan zegt een kolomnaam met "25" iets onwaars, en een kolomnaam veranderen breekt de
bestanden van Levrai. `grote_gemeente` blijft kloppen bij elke instelling, en past bij
`gemeentecode` en de CBS-naam ernaast. Hoeveel gemeenten er meetellen, staat in de
config en in de toelichting bij de levering, niet in de kolomnaam.

**Gezien, niet aangepast (apart verhaal):** `visuele_controle` en `eerder_geselecteerd` staan
in `werklijst_delft_2026-08.csv` als `False`/`True`, dus in het Engels, in een bestand dat
Levrai gebruikt. De nieuwe kolom gebruikt meteen `ja`/`nee`. Of de twee oude kolommen
moeten volgen, beslist Nova, want hun waarden veranderen dan in de CSV die als regressie
dient.

## 2. VA-39: de pagina toont Nederland

### Kop, titel en menu

| Sleutel | Tekst | Opmerking |
| --- | --- | --- |
| `<title>` | Levrai · Pandenselectie — Nederland | Vandaag "… Dashboard — Delft". |
| merk.sub | Pandenselectie · Nederland | Onder het merk in de zijbalk (VA-63). |
| pil.bron | Bron: PDOK BAG GeoPackage | Vandaag "Bron: PDOK BAG WFS v2_0". De tekst volgt het veld `bron` dat VA-37 schrijft. Staat daar iets anders, dan wordt de pil dat. |
| pil.peildatum | Peildatum 1 nov 2026 | Uit `peildatum()`, zoals nu. |
| menu-items | Kantoor · Kerncijfers · Voorraad · **Werklijst** | **"Proefresultaat" wordt "Werklijst"**, met adres `#werklijst`. Het proefresultaat was de controlevraag van 20 Delftse panden, en criterium 1 haalt Delft van de pagina. In de groep "Panden" staat de werklijst nu op de plek van het proefresultaat. De latere item "Werklijst" van VA-63 (VA-17) is daarmee hier gekomen. VA-17 gaat dan alleen nog over beoordelen op de pagina. VA-64's test (elk menu-item wijst naar een bestaand deel) vangt de nieuwe naam. |
| kerncijfers.titel | Nederland in vier cijfers | Volgt al uit VA-63: "{gebied} in vier cijfers". |

### De vier kerncijfers

| # | Waarde | Label | Hint |
| --- | --- | --- | --- |
| 1 | 9.998.456 | Verblijfsobjecten ingelezen | uit de BAG van 1 nov 2026 |
| 2 | 6.568.913 | Unieke BAG-panden | 475.372 uitgesloten |
| 3 | 441.997 | Binnen categorie A–E | de mastervoorraad |
| 4 | 263.319 | Geschikt · score ≥ 8 | 139.846 in de 25 grootste gemeenten · 123.473 elders |

- Hint 1: vandaag "100,0% dekking van Delft". **Er staat bewust geen dekkingspercentage.** De
  9.999.826 van de WFS (6 nov) komt uit een andere bron en is van een andere datum, en dat mag
  je niet vergelijken (LESSONS, VA-33). Levert VA-37 een dekking tegen de GeoPackage zelf, dan
  wordt de hint "{pct} dekking van Nederland".
- Kaart 4: vandaag "Werklijst · score ≥ 8" met de hint "ruim meerdere maanden voorraad". Landelijk
  is de werklijst vast 500, en die staat in de kop van de werklijst. Deze kaart toont dus de pool
  waaruit gekozen wordt. De hint "voorraad voor zoveel maanden" vervalt, want vraag 4 (komt een
  pand terug?) is open. **Ter controle bij Rex:** "geschikt" moet precies "score ≥ drempel en niet
  uitgesloten" zijn, de 263.319 van VA-37. Telt VA-37 iets anders, dan volgt het label dat.
  Zo nodig: ≥ {drempel}.

### De verdeling (de naam van de split)

| Sleutel | Tekst |
| --- | --- |
| deel.groot | uit de 25 grootste gemeenten |
| deel.groot, uitleg (tooltip en uitleg van Selectie) | de 25 gemeenten met de meeste inwoners (CBS) |
| deel.rest | **elders in Nederland** (kort: "elders") |
| verdeling, één regel | {n_groot} uit de 25 grootste gemeenten · {n_rest} elders in Nederland |

"overig" is een administratief restwoord. "Elders in Nederland" zegt waar de panden liggen. 25 is
`{aantal_grote_gemeenten}`.

### Voorraad: het rechterpaneel

"Proefselectie in cijfers" wordt de werklijst. Het linkerpaneel blijft "Technische voorraad
naar categorie", met als onderschrift "Nederland · panden binnen categorie A–E · een pand kan in
meerdere vallen".

| Sleutel | Tekst |
| --- | --- |
| paneel.titel | Werklijst in cijfers |
| paneel.onderschrift | De {n} panden van deze maand, verdeeld over het land |
| rij | Panden op de werklijst · 500 |
| rij | Uit de 25 grootste gemeenten · 450 |
| rij | Elders in Nederland · 50 |
| rij | Score-index (/100) · {min}–{max} |
| rij | Bouwjaren · {min}–{max} |
| rij | Gem. oppervlakte · {m²} |
| rij | Doelgebied · Nederland |
| rij | **Bronbestand** · bag-light_2026-11-01.gpkg · 1 nov 2026 |
| rij, tooltip | Heel Nederland: BAG-GeoPackage van PDOK, stand 1 nov 2026 |

"Oudste pand" vervalt. Het herhaalt het eerste getal van "Bouwjaren". **Let op:**
`build_dashboard.py` schrijft vandaag nog "Bron-snapshot" in deze rij (VA-26 is niet geland).
Landelijk is er één bestand, dus het label is gewoon "Bronbestand", zonder woonplaats (Nova's
regel van 6 november).

### De werklijst

| Sleutel | Tekst |
| --- | --- |
| kruimel | Levrai Vastgoed / Werklijst |
| werklijst.titel | Werklijst {maand} {jaar} (bv. "Werklijst november 2026") |
| werklijst.zin | De {n} hoogst scorende panden van Nederland, klaar voor je visuele controle. Open een pand voor alle gegevens. |
| werklijst.meta | {n} panden · {n_groot} uit de 25 grootste gemeenten · {n_rest} elders · gesorteerd op score-index |
| kaart, regel onder het adres | {postcode} {woonplaats} · gemeente {gemeente} |
| kaart, als gemeente = woonplaats | {postcode} {woonplaats} |

{maand} is de maand waarvoor de lijst is gekozen (de maand van de loting), voluit en met kleine
letter.

### Filter op gemeente

| Sleutel | Tekst |
| --- | --- |
| filter.label | Gemeente |
| filter.alle | Alle gemeenten ({n}) |
| filter.optie | {gemeente} ({aantal}) |
| filter.groep 1 (`optgroup`) | De 25 grootste gemeenten |
| filter.groep 2 (`optgroup`) | Elders in Nederland |
| filter.resultaat (`aria-live`) | {aantal} panden in {gemeente} · Alle gemeenten: {n} panden |
| filter.resultaat, 1 pand | 1 pand in {gemeente} |
| filter.leeg | Er staan geen panden uit {gemeente} op de werklijst van deze maand. |
| filter.terug | Toon alle gemeenten |

Het filter toont alleen gemeenten die op de lijst staan, dus "leeg" komt normaal niet voor. Het
kan wel als een adres of herlaadbeurt een gemeente kiest die deze maand ontbreekt. Gemeenten
staan per groep op alfabet. De twee groepen hergebruiken de namen van de verdeling.

### Kantoor (uit `kantoor_teksten()`, VA-31 en VA-60)

| Medewerker | Ballon | Zin / uitleg |
| --- | --- | --- |
| Ingest | BAG opgehaald 1 nov 2026 | Zin: "Ingest heeft de BAG van heel Nederland ingelezen uit het bestand van 1 nov 2026: 9.998.456 verblijfsobjecten." Uitleg: "Ingest leest de BAG van heel Nederland in uit het GeoPackage-bestand van PDOK, de open dataset van het Kadaster. Elke ophaling blijft bewaard als eigen, gedateerde momentopname, zodat je altijd ziet uit welke ophaling een cijfer komt." |
| Selectie | 500 panden op de werklijst | Zin: "Selectie heeft 441.997 panden in categorie A–E gescoord. 263.319 halen score 8 of hoger; de 500 beste staan op de werklijst." Uitleg: "Selectie groepeert de verblijfsobjecten per BAG-pand, sluit panden uit die buiten de briefing vallen, deelt de rest in categorie A–E in en geeft elk pand een leadscore. Van de 6.568.913 panden in Nederland vallen er 441.997 in A–E; 263.319 halen score 8 of hoger. Daaruit komen de 500 hoogst scorende op de werklijst: 450 uit de 25 gemeenten met de meeste inwoners (CBS) en 50 elders in Nederland. Bij gelijke score beslist een loting die de hele maand gelijk blijft." |
| Verrijking | ongewijzigd | ongewijzigd |
| Controle | {n} panden wachten op visuele controle | Zin en uitleg zoals nu, met "de {n} panden van de werklijst" in plaats van "de 20 hoogst scorende panden". **Ter controle bij Ada:** dit geldt alleen als Controle landelijk de werklijst telt. Telt hij iets anders, dan noemt de regel wat hij telt. |
| Kantoormanager | ongewijzigd | ongewijzigd |

Ingest zegt niet "elke maand". Wie de run elke maand draait, is nog open (vraag 19), dus die
belofte kan de pagina niet waarmaken.

Geen regel bevat het woord dat Nova op 6 november uitsloot, en geen regel is Engels. PDOK,
BAG, GeoPackage en CBS zijn namen.

## 3. Aanvulling na de bouw (2026-11-11)

### Voorraad: titel en uitlegregel

| Sleutel | Was | Wordt |
| --- | --- | --- |
| voorraad.titel | Voorraad en proefselectie | **Voorraad en werklijst** |
| voorraad.zin | … de 500 panden van de proef … | **Hoeveel van de {n_ae} panden in elke categorie A–E vallen, en wat de {n} panden op de werklijst van deze maand kenmerkt.** |

{n_ae} = 441.997 en {n} = 500 in de eerste run. Op de landelijke pagina is er geen proef.

### Nieuwe velden in "Open pand"

| Veld | Label | Waarde |
| --- | --- | --- |
| gemeente | Gemeente | {CBS-naam}, ingekort zoals hieronder |
| gemeentecode | Gemeentecode | {code}, bijvoorbeeld 0344 (vier cijfers, zonder "GM"; zie §4) |
| grote_gemeente | **In de {aantal_grote_gemeenten} grootste gemeenten** | ja / nee |

Het derde label is **gewijzigd**. Het getal komt uit `drempels.aantal_grote_gemeenten` op het
moment van de bouw, net als in de verdeling, dus het label klopt bij elke instelling. De
CSV-kolom houdt de vaste naam `grote_gemeente`. Een leeg veld volgt `LEEG` ("onbekend"). Zet de
drie velden in `PAND_VELDEN` direct na "Woonplaats".

### Het achtervoegsel " (gemeente)" van het CBS

**Goedgekeurd, met één grens:** haal alleen het exacte achtervoegsel " (gemeente)" weg, in het
filter, op de kaarten en in "Open pand". Laat elk ander deel tussen haakjes staan. Zo onderscheidt
het CBS twee gemeenten met dezelfde naam, en zonder de haakjes vallen ze samen in het filter.
Een test: elke gemeentenaam in het filter is uniek.

## 4. Uitspraak: de vorm van de gemeentecode (Lumi, 2026-11-12, op vraag van Vera)

**De gemeentecode is vier cijfers, zonder "GM": `0503`.** Het voorbeeld "GM0344" in §3 ("Nieuwe
velden in Open pand") is daarmee **vervangen door "0344"**. De waarde in "Open pand" en in de CSV
is precies wat de data bewaart. De pagina zet er niets voor.

Waarom: zo staat het vastgelegd (`BACKLOG.md` VA-34 criterium 4 en VA-65: "four digits, the CBS
gemeentecode without its `GM` prefix"), en `cbs_gemeenten.py` haalt het voorvoegsel er bewust af.
"GM" is het voorvoegsel van de regio-indeling van het CBS, niet een deel van de code. Een BAG-ID
begint met dezelfde vier cijfers (Delft: `0503…`), dus in deze vorm kun je ze naast elkaar lezen.
Het label blijft "Gemeentecode". Let op: de voorloopnul hoort erbij. Het veld is tekst, nooit
een getal, anders wordt `0503` in de CSV of in Excel `503`.
