# Kopij VA-61, VA-62 (en VA-51, VA-52): goedgekeurd door Lumi, 2026-11-09

Bron van het concept: `_scratch/main-va31/build_dashboard.py` (`PAND_VELDEN`, `LEEG`,
`NIET_INGEVULD`, `GEEN`, `PAND_TEKST`) en `serve.py` (`TE_VAAK`). **Status** zegt per regel
of hij blijft zoals hij is of verandert. Alleen de regels met **gewijzigd** moeten in de code
worden aangepast.

## Veldlabels (`PAND_VELDEN`)

Alle 34 labels zijn **ongewijzigd goedgekeurd**: Hoofdadres, Woonplaats, Postcode, Huisnummer,
Huisletter, Aantal adressen, Alle adressen, BAG-pand-ID, Lead-ID, Bouwjaar, Pandstatus,
Totale oppervlakte, Oppervlakte per functie, Verblijfsobjecten per functie, Gebruiksdoelen,
Aantal verblijfsobjecten, Verblijfsobject-ID's, Status verblijfsobjecten, Categorieën,
Hoofdcategorie, Leadscore (punten), Score-index (/100), Score-opbouw, Selectiereden,
Uitgesloten, Redenen voor uitsluiting, X-coördinaat (RD), Y-coördinaat (RD), Bron,
Peildatum van de gegevens, Visueel gecontroleerd, Beoordeling, Eerder geselecteerd,
Laatst beoordeeld.

## Woorden voor lege waarden

| Sleutel | Tekst | Status |
| --- | --- | --- |
| `LEEG` | onbekend | ongewijzigd |
| `NIET_INGEVULD` | niet ingevuld | ongewijzigd (voor Beoordeling en Laatst beoordeeld, die Levrai zelf invult) |
| `GEEN` | geen | ongewijzigd |
| Huisletter, leeg | geen | **gewijzigd:** was "onbekend". In `panden_delft.json` is de huisletter bij 22.690 van de 24.008 panden `''`. Dat betekent dat het adres geen huisletter heeft, niet dat we hem niet kennen. "onbekend" zou iets onwaars zeggen. Lege huisletter wordt dus `GEEN`. |
| ja / nee | ja · nee | ongewijzigd |

## Pand openen en luchtfoto (`PAND_TEKST`)

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `laden` | Luchtfoto wordt geladen… | De luchtfoto laadt… | **gewijzigd** (bedrijvende vorm) |
| `mislukt` | Luchtfoto kon niet worden geladen. Gebruik de kaart of Street View hieronder. | De luchtfoto kon niet laden. Bekijk het pand via Google Maps of Street View hieronder. | **gewijzigd:** noemt de links bij de namen die ze op de pagina hebben. "De kaart" bestaat daar niet als knop. |
| `bron` | Luchtfoto: PDOK, Landelijke Voorziening Beeldmateriaal · open data (CC BY). | Luchtfoto: Beeldmateriaal Nederland, via PDOK · open data (CC BY 4.0). | **gewijzigd, onder voorbehoud** (zie hieronder) |
| `geenLocatie` | De locatie van dit pand is onbekend; er is geen luchtfoto en geen kaartlink. | Dit pand heeft geen bekende locatie, dus er is geen luchtfoto en geen link naar Google Maps of Street View. | **gewijzigd:** zegt welke links ontbreken. De BAG-viewer-link blijft wel staan. |
| `alt` | Luchtfoto van {adres} | Luchtfoto van {adres} | ongewijzigd |
| `maps` | Open in Google Maps ↗ | Open in Google Maps ↗ | ongewijzigd. Zet de ↗ in `<span aria-hidden="true">`, anders leest een schermlezer "pijl rechtsboven" voor. |
| `sv` | Open in Street View ↗ | Open in Street View ↗ | ongewijzigd, met de ↗ in `aria-hidden` |
| `bag` | Open in BAG-viewer ↗ | Open in BAG-viewer ↗ | ongewijzigd (gelijk aan de link op de kaart), met de ↗ in `aria-hidden` |
| `open` | Open de gegevens van {adres} | Open de gegevens van {adres} | ongewijzigd |
| `pandSluit` | Sluiten | Sluiten | ongewijzigd |

**Voorbehoud bij `bron` (VA-62, criterium 2).** In de GetCapabilities van
`service.pdok.nl/hwh/luchtfotorgb/wms/v1_0` (opgevraagd 2026-11-09) staat
`<AccessConstraints>None</AccessConstraints>` en geen licentie. Data.overheid.nl vermeldt
CC BY 4.0 voor de Beeldmateriaal-luchtfoto's en de PDOK-diensten ervan. Beeldmateriaal
Nederland vraagt om naamsvermelding. Neem "CC BY 4.0" en "Beeldmateriaal Nederland" alleen
over als het metadatarecord van de dienst (Nationaal Georegister) dat zegt, en citeer dat in de
close-out. Zegt het record iets anders, dan volgt de regel het record.

## Inloggen (VA-51, VA-52) en dashboard

| Sleutel | Tekst | Status |
| --- | --- | --- |
| `TE_VAAK` | Te veel mislukte pogingen. Probeer het over {minuten} opnieuw. | ongewijzigd goedgekeurd. {minuten} is "1 minuut" of "{N} minuten", zoals `te_vaak_melding()` het al doet. De regel zegt niet of de gebruikersnaam of het wachtwoord fout was, net als `FOUTMELDING`. |
| Uitloggen | Uitloggen | ongewijzigd. In het menu van VA-63 staat de knop onderaan de zijbalk. |

Geen regel gebruikt het woord dat Nova op 2026-11-06 uitsloot, en geen regel is Engels
(Google Maps, Street View en PDOK zijn namen).

## Knop in de voet van de kaart (VA-61, Vera ronde 2), 2026-11-09

| Sleutel | Concept | Goedgekeurd | Status |
| --- | --- | --- | --- |
| knop, zichtbaar | Alle gegevens | Open pand | **gewijzigd:** een knop zegt wat er gebeurt, en het sluit aan bij "Open in BAG-viewer ↗" ernaast. Kort genoeg voor de voet op 375 px. |
| knop, `aria-label` | Alle gegevens van {adres} | Open pand: alle gegevens van {adres} | **gewijzigd:** begint met de zichtbare tekst, zodat de naam de zichtbare tekst bevat (WCAG 2.5.3). Vervangt `PAND_TEKST.open` ("Open de gegevens van {adres}"), dat bij het oude kaartlabel hoorde. |

## Energielabel in de pandweergave (VA-58, criterium 5), 2026-11-17

Twee velden die het record alleen heeft als het energielabel aan staat
(`ALLEEN_MET_ENERGIELABEL`). Zonder die velden is er geen rij. Met het veld maar zonder label
(`None`) is de waarde `GEEN` ("geen").

| Veld | Concept (Rex) | Goedgekeurd | Status |
| --- | --- | --- | --- |
| `energielabel` | Energielabel (EP-online) | Energielabel (EP-online) | ongewijzigd goedgekeurd. Tussen haakjes staat het register, zoals bij "X-coördinaat (RD)". Zo ziet Levrai dat de klasse uit het officiële register komt en geen schatting is. "Energielabel (EP-online): geen" zegt eerlijk dat het pand daar geen label heeft. |
| `energielabel_registratiedatum` | Energielabel geregistreerd op | Registratiedatum energielabel | **gewijzigd:** zonder label is de waarde "geen", en dan leest het concept als "Energielabel geregistreerd op: geen". Een zelfstandig naamwoord past bij elke waarde ("Registratiedatum energielabel: 4 mrt 2021" of "geen"). Het sluit ook aan bij "Peildatum van de gegevens" en gebruikt het woord van RVO zelf. |

In de code verandert alleen het tweede label: in `PAND_VELDEN` in `build_dashboard.py` en de
drie keer dat `tests/test_dashboard_pand.py` het noemt (`test_energielabel_rijen`). Daarna
`python build_dashboard.py` opnieuw draaien. Er is geen andere locale: het dashboard is alleen
Nederlands.
