# Kopij VA-90 (Bewaar en Verberg, alleen op dit apparaat): Lumi, 2026-11-16

Bron van het concept: `build_dashboard.py` op `6ffcb00` (`visueel-1113`): `BEWAAR_TEKST`, het blok
`BEWAREN EN VERBERGEN (VA-90)` in het script, en `LIJST_TEKST["leeg"]`. **Status** zegt per regel of
hij blijft zoals hij is of verandert. Alleen de regels met **gewijzigd** of **nieuw** moeten in de code
worden aangepast. Alle tekst blijft in Python (`BEWAAR_TEKST`), het script vult alleen `{adres}` en
`{n}` in, met `nl()` voor de duizendtallen. {adres} is het hoofdadres met postcode en woonplaats
(`d.detail.titel`), zoals nu.

De pagina is alleen Nederlands (VA-90 criterium 14). Er is geen tweede taal om te vullen.

## 1. De twee knoppen, op de kaart en in "Open pand"

Ayman's woorden "Bewaar" en "Verberg" staan op de knop zolang er niets gekozen is. Ingedrukt zegt de
bovenste regel wat er nu geldt, en de kleine regel eronder wat de knop dan doet.

| Sleutel | Concept (Ada) | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `bewaar` | Bewaar | Bewaar | ongewijzigd (Ayman) |
| `verberg` | Verberg | Verberg | ongewijzigd (Ayman) |
| `bewaard` / `label.bewaard` | Bewaard | Bewaard | ongewijzigd |
| `verborgen` / `label.verborgen` | Verborgen | Verborgen | ongewijzigd |
| `terug.bewaard` | Nog eens: niet meer bewaren | **Druk om niet meer te bewaren** | **gewijzigd.** "Nog eens:" is geen Nederlandse zin, en een knop zegt wat er gebeurt. "Druk" geldt voor muis, vinger en toetsenbord ("klik" en "tik" niet). 28 tekens, 1 meer dan het concept, dus het past op 375 px zoals Vera het mat. |
| `terug.verborgen` | Nog eens: weer tonen | **Druk om weer te tonen** | **gewijzigd**, om dezelfde reden. "Weer tonen" sluit aan bij de statusregel "staat weer op de werklijst". |
| iconen | ☆ / ★ (Bewaar), ⊘ / ◌ (Verberg) | ongewijzigd | Blijven in `aria-hidden`. |

### Toegankelijke naam (`aria-label`) van de knoppen

Nu bouwt de knop zijn naam uit losse spans: "Bewaar · {adres}", en ingedrukt plakt de schermlezer
"Bewaard" en de kleine regel zonder spatie aan elkaar. De " · " wordt door sommige schermlezers
voorgelezen als "punt in het midden". **Gewijzigd:** zet de naam expliciet met `aria-label`, en houd
`aria-pressed`.

| Stand | Concept (Ada, berekend) | Goedgekeurd `aria-label` | Status |
| --- | --- | --- | --- |
| Bewaar, niet ingedrukt | Bewaar · {adres} | **Bewaar {adres}** | **gewijzigd** (geen middenpunt) |
| Bewaar, ingedrukt | Bewaard Nog eens: niet meer bewaren · {adres} | **Bewaard, druk om niet meer te bewaren: {adres}** | **gewijzigd** |
| Verberg, niet ingedrukt | Verberg · {adres} | **Verberg {adres}** | **gewijzigd** (geen middenpunt) |
| Verberg, ingedrukt | Verborgen Nog eens: weer tonen · {adres} | **Verborgen, druk om weer te tonen: {adres}** | **gewijzigd** |

De naam begint met de zichtbare tekst en bevat die helemaal (WCAG 2.5.3), net als bij "Open pand"
(`copy-va61-62.md`). Een schermlezer zegt dan bijvoorbeeld: "Bewaard, druk om niet meer te bewaren:
Hippolytusbuurt 1, 2611HM Delft, schakelknop, ingedrukt."

## 2. Het label op de kaart (ook op een verborgen pand dat weer getoond wordt)

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| kaartlabel, bewaard | ★ Bewaard | ★ Bewaard | ongewijzigd. Zet de ★ in een eigen `<span aria-hidden="true">`. Nu staat hij in de tekst, en dan leest een schermlezer "zwarte ster" voor. |
| kaartlabel, verborgen en weer getoond | Verborgen | **◌ Verborgen** | **gewijzigd:** hetzelfde teken als op de ingedrukte Verberg-knop, zodat label en knop bij elkaar horen. De ◌ in `aria-hidden`. De stippelrand van de kaart en van het label blijven. |

## 3. De statusregel en "Ongedaan maken"

Eén regel boven de werklijst (`#bwStatus`) en, als je in "Open pand" drukt, ook daar. `role="status"`,
geen `alert`.

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `status.verborgen` | {adres} is verborgen. | {adres} is verborgen. | ongewijzigd. De regel zegt dat het gebeurd is en welk pand, en "Ongedaan maken" staat ernaast. |
| `status.terug` | {adres} staat weer op de werklijst. | {adres} staat weer op de werklijst. | ongewijzigd (na Verberg nog eens, of na Ongedaan maken van een Verberg) |
| `status.bewaard` | {adres} is bewaard. | {adres} is bewaard. | ongewijzigd. Hij zegt niet waar je het terugvindt: de pagina "Bewaarde panden" (VA-91) bestaat nog niet. Als VA-91 landt, krijgt deze regel een vervolg in de kopij van VA-91. |
| `status.niet_bewaard` | {adres} is niet meer bewaard. | {adres} is niet meer bewaard. | ongewijzigd |
| `ongedaan` | Ongedaan maken | Ongedaan maken | ongewijzigd (de woorden van criterium 3 zijn hiermee van Lumi). **Nieuw:** geef de knop `aria-describedby` naar de tekst van zijn statusregel, zodat wie er met de focus op landt ook hoort wat er ongedaan wordt ("Ongedaan maken, knop, Vughterstraat 54, 5211GK 's-Hertogenbosch is verborgen."). |

**Opmaak, Vera's aanbeveling overgenomen:** laat `#bwStatus` en de statusregel in "Open pand" leeg in de
toegankelijkheidsboom staan. Verberg ze niet met `.bw-status:empty{display:none}`, maar laat ze leeg
zonder hoogte (bijvoorbeeld `min-height:0` en geen padding als ze leeg zijn). Een live-regio die pas
verschijnt met zijn eerste bericht, wordt door sommige schermlezers niet voorgelezen.

## 4. Telling en tonen boven de werklijst

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `aantal` | {n} panden verborgen | {n} panden verborgen | ongewijzigd |
| `aantal.een` | 1 pand verborgen | 1 pand verborgen | ongewijzigd |
| `toon` | Toon verborgen panden | Toon verborgen panden | ongewijzigd |
| `toon.een` | (ontbreekt; nu ook "Toon verborgen panden") | **Toon het verborgen pand** | **nieuw:** bij precies 1 verborgen pand |
| `toon.uit` | Verberg ze weer | Verberg ze weer | ongewijzigd. "Ze" verwijst naar de telling ernaast. |
| `toon.uit.een` | (ontbreekt) | **Verberg het weer** | **nieuw:** bij precies 1 |

**`aria-pressed` op deze knop vervalt.** Het label wisselt al van wat de knop doet ("Toon …") naar wat
hij dan doet ("Verberg ze weer"). Met `aria-pressed` erbij zegt een schermlezer "Verberg ze weer,
ingedrukt", en dat zijn twee standen in één zin. De rand bij "aan" kan blijven, via een klasse. (Bij de
knoppen per pand blijft `aria-pressed` wel: daar zegt de bovenste regel de stand, niet de actie.)

## 5. "Alleen op dit apparaat"

Ada's zin zegt "Collega's zien het niet". Dat kan de pagina niet waarmaken: Levrai heeft één inlog
(Q22), en een collega achter dezelfde computer, in dezelfde browser, ziet het wel. Wat klopt is: een
ander apparaat of een andere browser ziet het niet. En wie de browsergegevens wist, is het kwijt. Dat
laatste is een echte grens van de opslag, dus de pagina zegt het één keer, boven de werklijst.

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `apparaat` (boven de werklijst) | Bewaren en verbergen geldt alleen op dit apparaat, in deze browser. Collega's zien het niet. | **Wat je bewaart of verbergt, staat alleen op dit apparaat, in deze browser. Op een ander apparaat zie je het niet, ook niet met dezelfde inlog. Wis je de browsergegevens, dan ben je het kwijt.** | **gewijzigd**, zie hierboven |
| `apparaat.kort` (in "Open pand", onder de knoppen) | (zelfde zin als boven de werklijst) | **Alleen op dit apparaat, in deze browser. Een ander apparaat ziet het niet.** | **nieuw:** de korte vorm. In het venster staat de zin bij elk pand opnieuw, dus hij is kort. |

## 6. Als de browser niets wil opslaan (criterium 8)

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `geen_opslag` | Bewaren en verbergen werkt niet in deze browser: hij slaat niets op (bijvoorbeeld in een privévenster). De rest van het dashboard werkt gewoon. | **Deze browser laat het dashboard niets opslaan, dus Bewaar en Verberg werken hier niet. Dat gebeurt bijvoorbeeld in een privévenster, of als opslag voor websites uit staat. Open het dashboard in een gewoon venster om panden te bewaren. De rest van het dashboard werkt gewoon.** | **gewijzigd:** noemt de knoppen bij hun naam, zegt de tweede oorzaak (opslag uit) en wat je kunt doen. |

Dezelfde zin staat boven de werklijst, in "Open pand" in plaats van `apparaat.kort`, en in de
statusregel als iemand toch op een uitgeschakelde knop drukt. Ook als de opslag halverwege weigert
(`QuotaExceededError`), want ook dan werkt hij vanaf dat moment niet meer.

## 7. Een lege werklijst omdat alles verborgen is

Nu zegt de lege werklijst altijd `LIJST_TEKST["leeg"]`: "Geen enkel pand op de werklijst van deze maand
past bij deze filters …". Als de filters wel panden vinden, maar die allemaal verborgen zijn, is dat
onwaar, en "Wis alle filters" helpt dan niet. Er zijn dus drie gevallen. Het script kiest ertussen met
twee tellingen: de panden die de filters halen **zonder** te letten op verborgen (`m`), en de panden op
het scherm (`n = 0`).

| Geval | Sleutel | Tekst | Knop(pen) in het vak | Status |
| --- | --- | --- | --- | --- |
| Filters actief, `m = 0` (de filters zelf vinden niets) | `LIJST_TEKST["leeg"]` | Geen enkel pand op de werklijst van deze maand past bij deze filters. Verwijder hierboven een filter, of wis ze allemaal. | Wis alle filters | ongewijzigd |
| Filters actief, `m > 0`, alle `m` verborgen | `leeg.verborgen` | **Je hebt alle {m} panden verborgen die bij deze filters passen.** | **Toon verborgen panden**, daarna Wis alle filters | **nieuw** |
| idem, `m = 1` | `leeg.verborgen.een` | **Het enige pand dat bij deze filters past, heb je verborgen.** | **Toon het verborgen pand**, daarna Wis alle filters | **nieuw** |
| Geen filter actief, alle panden verborgen | `leeg.alles_verborgen` | **Je hebt alle {totaal} panden van de werklijst van deze maand verborgen.** | **Toon verborgen panden** (geen "Wis alle filters": er is geen filter) | **nieuw** |

"Toon verborgen panden" in het vak doet hetzelfde als de knop in de balk en gebruikt dezelfde sleutels
(`toon`, `toon.een`). Daarna staat de balkknop op "Verberg ze weer", zoals altijd. De nieuwe zinnen
horen bij `BEWAAR_TEKST`, niet bij `LIJST_TEKST`, want ze bestaan alleen door VA-90.

## 8. Focus als "Open pand" sluit en zijn kaart weg is (criterium 13, VA-61)

**Uitspraak: Vera's voorstel geldt.** Sluit "Open pand" (Escape of Sluiten) en staat de kaart die het
opende niet meer in de werklijst, dan gaat de focus naar **"Ongedaan maken" in de statusregel boven de
werklijst** (`#bwStatus`).

Waarom:
- Het is dezelfde regel als Ada al heeft voor een kaart die verdwijnt na Verberg op de kaart zelf. Eén
  regel voor beide wegen: een pand dat uit de lijst gaat, geeft de focus aan zijn "Ongedaan maken".
- Het is de handeling die je dan het meest nodig hebt, en de knop staat naast de regel die het pand
  noemt. Met `aria-describedby` (§3) hoor je bij aankomst ook welk pand.
- Het volgende pand in de lijst is geen goede plek: daar heb je niet om gevraagd, en je verliest de
  enige weg terug zonder te zoeken.

Twee grenzen, zodat de focus nooit op `<body>` valt:
1. Staat de kaart er bij het sluiten wel (je drukte in het venster op "Ongedaan maken", of "Toon
   verborgen panden" staat aan, zodat de verborgen kaart gemarkeerd blijft staan), dan geldt VA-61
   zoals het is: focus terug naar de "Open pand"-knop van die kaart.
2. Is er geen "Ongedaan maken" voor dit pand in `#bwStatus` (de regel is intussen door iets anders
   vervangen), dan gaat de focus naar de werklijst-sectie zelf (`#werklijst`, die heeft al
   `tabindex="-1"`).

De pagina scrolt daarbij naar de balk boven de werklijst. Dat is een sprong, maar het is dezelfde sprong
als bij Verberg op een kaart, en Vera heeft die goedgekeurd.

## Voor Ada

- `tests/test_dashboard_bewaren.py` en eventuele pins op de oude teksten volgen deze tabel.
- Geen regel is Engels en geen regel bevat het woord dat Nova op 6 november uitsloot.
- Gezien, niet beslist: de filteropties tellen verborgen panden niet mee (bijvoorbeeld "Delft (0)" als
  alle 7 Delftse panden verborgen zijn). Dat volgt criterium 5 ("filters apply to what is shown") en is
  dus zo bedoeld. De nieuwe lege-werklijstzinnen van §7 maken duidelijk waarom de lijst leeg is.
