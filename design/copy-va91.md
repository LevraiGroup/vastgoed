# Kopij VA-91 (Bewaarde panden, alleen op dit apparaat): Lumi, 2026-11-16

Bron: `build_dashboard.py` op `bd574d1` (main): `MENU`, `KOP_TEKST_LANDELIJK`, `BEWAAR_TEKST` en het blok
`BEWAREN EN VERBERGEN (VA-90)` in het script, en de opslag `levrai-vastgoed-panden` (`v: 1`).

## Welke kolom geldt

**Alleen de kolom `GOEDGEKEURD` is kopij.** Die bouw je letterlijk zoals hij hier staat, en die pint de test vast.
Er is geen concept: alle regels van VA-91 zijn nieuw, behalve de regels die "bestaat al" zeggen.
Die staan al in `BEWAAR_TEKST` en blijven zoals ze zijn. De kolom "Toelichting" is uitleg en geen tekst voor de pagina.
Het Python-blok in §8 is dezelfde kolom, overgenomen om te plakken. Als het blok en de tabel ooit verschillen,
geldt de tabel.

Alle tekst staat in Python, in `BEWAAR_TEKST` (nieuwe sleutels beginnen met `pagina.`). Het script vult alleen
`{adres}`, `{n}` en `{datum}` in, met `nl()` voor getallen. De pagina is alleen Nederlands, dus er is geen tweede
taal om te vullen. Geen enkele regel is Engels, en geen enkele bevat het woord dat Nova op 6 november uitsloot.

## 1. Het menu-item (criteria 1 en 6)

**Naam: "Bewaarde panden".** De knop heet "Bewaar", het label "Bewaard" en de statusregel "is bewaard". Zou het
menu "Opgeslagen" zeggen, dan heeft dezelfde handeling twee namen. Ayman gebruikte allebei de woorden, en de
pagina laat hem dus maar één ervan zien.

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `MENU`, groep Panden | `("bewaard", "Bewaarde panden")` | Adres `#bewaard`. Volgorde in de groep: Voorraad, **Bewaarde panden**, Werklijst. Zie §9 voor waarom het vóór de werklijst staat. |
| `pagina.menu.n` (zichtbaar) | `{n}` | Een getal in een pil rechts in het item. Bij 0 bewaard, of als de browser niets opslaat, staat er geen pil. |
| `pagina.menu.n.sr` (alleen voor schermlezers) | `, {n} bewaard` | Een visueel verborgen span direct na de naam. De schermlezer leest dan "Bewaarde panden, 3 bewaard, link". De zichtbare pil krijgt `aria-hidden="true"`. Bij 1: `, 1 bewaard`, dus hetzelfde patroon. |

## 2. De kop van de pagina

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| kruimel | `Levrai Vastgoed / Bewaarde panden` | Zoals de andere delen: `<b>Bewaarde panden</b>`. |
| `pagina.titel` | `Bewaarde panden` | De `h2`, `id="t-bewaard"`. |
| `pagina.zin` | `De panden die je hebt bewaard, het laatst bewaarde bovenaan. Een pand blijft hier staan, ook als het niet meer in de werklijst staat.` | |
| `pagina.meta` | `{n} panden` | Rechts in de kop-rij, net als `secmeta`. |
| `pagina.meta.een` | `1 pand` | |
| `pagina.meta.weg` | `{n} panden · {m} niet in deze werklijst` | Alleen als m > 0. Bij n = 1 en m = 1: `1 pand · niet in deze werklijst`. Dat is `pagina.meta.weg.een`. |
| `pagina.meta.weg.een` | `1 pand · niet in deze werklijst` | |
| `pagina.apparaat` | `Deze lijst staat alleen op dit apparaat, in deze browser. Op een ander apparaat zie je hem niet, ook niet met dezelfde inlog. Wis je de browsergegevens, dan ben je hem kwijt.` | Criterium 5 ("alleen op dit apparaat"). Eén keer, onder de kop, in de stijl van `.bw-apparaat`. Dezelfde belofte als VA-90's `apparaat`, in woorden voor een lijst. |

## 3. Een bewaard pand in de lijst (criteria 2 en 3)

Elke rij toont: het adres, de woonplaats, de score, de categorie en de datum waarop het pand is bewaard.

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| adres | *(opgeslagen `hoofdadres`)* | Geen nieuwe tekst. Eindigt `hoofdadres` niet op de opgeslagen `woonplaats` (dat kan bij een kaart zonder `detail`), plak dan `, {woonplaats}` erachter. Zo staat de woonplaats er altijd, en nooit twee keer. |
| `pagina.sinds` | `Bewaard op {datum}` | `{datum}` komt uit `sinds`, in het formaat van het dashboard (zie de bouwnotities). |
| score | *(getal)* + `/100` | Het score-blok van de kaart, kleiner. Zonder score: `onbekend`, net als elders in het dashboard. |
| categorie | *(letter, chip `cA`…`cE`)* | Geen nieuwe tekst. Zonder categorie: geen chip. |
| "Open pand" | `Open pand` | **Bestaat al** (VA-61), net als zijn `aria-label`. Alleen voor een pand dat in de huidige data staat. |
| Bewaar-knop | `Bewaard` / `Druk om niet meer te bewaren` | **Bestaat al** (VA-90). Het is dezelfde knop in dezelfde ingedrukte stand, met hetzelfde `aria-label` (`naam.bewaard`). Hier staat geen Verberg-knop, want deze pagina gaat over bewaren. |

### Een pand dat niet in deze werklijst staat

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `pagina.weg.label` | `Niet in deze werklijst` | Een pil op de rij, met tekst en een stippelrand, dus niet alleen kleur. |
| `pagina.weg.zin` | `Dit pand staat niet in de werklijst van deze maand. Score en categorie komen uit de gegevens van {datum}.` | `{datum}` is de opgeslagen `datapeildatum`, in het formaat van het dashboard. |
| `pagina.weg.zin.onbekend` | `Dit pand staat niet in de werklijst van deze maand. Van wanneer de score en categorie zijn, is onbekend.` | Als `datapeildatum` ontbreekt of onleesbaar is. |
| BAG-link | `Open in BAG-viewer` | **Bestaat al** (VA-62), naar de opgeslagen `bag_viewer_url`. Hij opent in een nieuw tabblad, zoals in "Open pand". Deze rij heeft geen "Open pand": de pagina heeft het pand niet meer, en een detailweergave met alleen vijf velden zou meer beloven dan hij kan waarmaken. |

## 4. Weghalen en Ongedaan maken (criterium 4)

De statusregel van deze pagina (`#bwBewaardStatus`, `role="status"`) staat onder `pagina.apparaat` en boven de
lijst.

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `status.niet_bewaard` | `{adres} is niet meer bewaard.` | **Bestaat al.** De rij gaat meteen weg. |
| `ongedaan` | `Ongedaan maken` | **Bestaat al**, met `aria-describedby` zoals in VA-90 §3. |
| `pagina.status.terug` | `{adres} staat weer bij je bewaarde panden.` | **Nieuw:** na Ongedaan maken op deze pagina. Het pand komt terug op zijn oude plek, want `herstel()` zet het oude object terug, met zijn oude `sinds`. |

### Een vervolg op VA-90's statusregel (beloofd in `copy-va90.md` §3)

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `status.bewaard` | `{adres} is bewaard. Je vindt het terug bij Bewaarde panden.` | **Gewijzigd** (was `{adres} is bewaard.`). Dit geldt op de werklijst en in "Open pand". Er komt geen link bij: de telling in het menu gaat op hetzelfde moment omhoog. De tekst die VA-90's eigen Ongedaan maken na een Verberg toont (`uit.oud.stand === "bewaard"`), gebruikt ook deze sleutel. Dat is goed zo. |

## 5. Leeg, en geen opslag (criterium 5)

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `pagina.leeg` | `Je hebt nog geen panden bewaard. Druk bij een pand in de werklijst op Bewaar, dan staat het hier.` | In het vak `.wl-leeg`, zonder knop. Je bewaart in de werklijst, en die staat er direct onder. |
| `pagina.geen_opslag` | `Deze browser laat het dashboard niets opslaan, dus hier staan geen bewaarde panden. Dat gebeurt bijvoorbeeld in een privévenster, of als opslag voor websites uit staat. Open het dashboard in een gewoon venster om je bewaarde panden te zien.` | Zelfde vak. Dan staan `pagina.apparaat` en de telling in het menu er niet. Dit geldt ook als de opslag halverwege weigert. |

## 6. Lange lijst

| Sleutel | GOEDGEKEURD | Toelichting |
| --- | --- | --- |
| `pagina.meer` | `Toon alle {n} bewaarde panden` | Je ziet eerst de 10 nieuwste. Deze knop staat er alleen bij n > 10. |
| `pagina.minder` | `Toon alleen de laatste 10` | Dezelfde knop als hij open staat. Geen `aria-pressed`, want het label zegt al wat hij doet (zoals `toon` in VA-90 §4). De focus blijft op de knop. |

## 7. Wat niet verandert

`bewaar`, `bewaard`, `terug.bewaard`, `naam.*`, `apparaat`, `apparaat.kort`, `geen_opslag` en de rest van
`BEWAAR_TEKST` blijven zoals in `copy-va90.md`. Alleen `status.bewaard` verandert (§4).

## 8. Hetzelfde als Python, om te plakken (gelijk aan de kolom GOEDGEKEURD)

```python
# nieuw in BEWAAR_TEKST (VA-91, Lumi, design/copy-va91.md)
"status.bewaard": "{adres} is bewaard. Je vindt het terug bij Bewaarde panden.",   # gewijzigd
"pagina.titel": "Bewaarde panden",
"pagina.zin": "De panden die je hebt bewaard, het laatst bewaarde bovenaan. Een pand blijft hier staan, "
              "ook als het niet meer in de werklijst staat.",
"pagina.meta": "{n} panden",
"pagina.meta.een": "1 pand",
"pagina.meta.weg": "{n} panden · {m} niet in deze werklijst",
"pagina.meta.weg.een": "1 pand · niet in deze werklijst",
"pagina.menu.n": "{n}",
"pagina.menu.n.sr": ", {n} bewaard",
"pagina.apparaat": "Deze lijst staat alleen op dit apparaat, in deze browser. Op een ander apparaat zie je hem "
                   "niet, ook niet met dezelfde inlog. Wis je de browsergegevens, dan ben je hem kwijt.",
"pagina.sinds": "Bewaard op {datum}",
"pagina.weg.label": "Niet in deze werklijst",
"pagina.weg.zin": "Dit pand staat niet in de werklijst van deze maand. Score en categorie komen uit de "
                  "gegevens van {datum}.",
"pagina.weg.zin.onbekend": "Dit pand staat niet in de werklijst van deze maand. Van wanneer de score en "
                           "categorie zijn, is onbekend.",
"pagina.status.terug": "{adres} staat weer bij je bewaarde panden.",
"pagina.leeg": "Je hebt nog geen panden bewaard. Druk bij een pand in de werklijst op Bewaar, dan staat het hier.",
"pagina.geen_opslag": "Deze browser laat het dashboard niets opslaan, dus hier staan geen bewaarde panden. Dat "
                      "gebeurt bijvoorbeeld in een privévenster, of als opslag voor websites uit staat. Open het "
                      "dashboard in een gewoon venster om je bewaarde panden te zien.",
"pagina.meer": "Toon alle {n} bewaarde panden",
"pagina.minder": "Toon alleen de laatste 10",
```

In het menu: `MENU[1]["items"]` wordt `[("voorraad", "Voorraad"), ("bewaard", "Bewaarde panden"),
("proefresultaat", "Proefresultaat")]`. `menu_voor()` maakt van het laatste item Werklijst, zoals nu.

## 9. Bouwnotities voor Ada

**Waar het deel staat.** Het dashboard is één pagina die je scrolt (VA-64). Het actieve menu-item volgt het
scrollen. "Een aparte pagina" is daarom een eigen `section.deel` met id `bewaard`, net als Kantoor en Werklijst.
Het kantoor blijft bovenaan staan. Het deel komt **tussen Voorraad en de werklijst**, niet erna. Onder de
werklijst laadt de schildwacht steeds 40 kaarten bij, en dan kom je met scrollen nooit bij het deel aan. Een klik
in het menu laat de pagina dan ook verspringen. De volgorde in het menu is dezelfde als op de pagina.

**Niet verspringen.** Bewaar je een pand op de werklijst, dan wordt het deel erboven een rij hoger. Ligt de
onderkant van `#bewaard` boven de bovenrand van het scherm, meet dan de bovenkant van de werklijst voor en na het
tekenen, en `scrollBy` het verschil. Safari kent geen scroll-anchoring, dus doe dit zelf. Doe het ook bij een
verandering vanuit een ander tabblad (het `storage`-event).

**Adres.** `#bewaard`, met dezelfde regels als de andere items. Na herladen sta je op het deel.

**Volgorde.** De nieuwste `sinds` staat bovenaan. Een `sinds` die ontbreekt of onleesbaar is, gaat onderaan. Bij
gelijke `sinds` beslist het adres, op alfabet (`localeCompare(…, "nl")`). Ongedaan maken zet het oude object
terug met zijn oude `sinds`, dus het pand komt op zijn oude plek terug.

**Datumformaat.** Dat is `nl_datum()` van het dashboard: `16 nov 2026`, met harde spaties, en de maanden uit
`MAANDEN`. Geef `MAANDEN` mee in `PAYLOAD.bewaar`, zodat het script geen eigen maandnamen heeft. `sinds` is een
ISO-tijd in UTC, dus neem de datum in de **lokale** tijd van de browser. `datapeildatum` is `JJJJ-MM-DD`: lees
die als kalenderdatum, niet via `new Date()`, anders schuift hij een dag op.

**Indeling, met wat er al is.**
- Het menu: het bestaande `.nav a`-item. De telling is een pil `margin-left:auto`, 11.5px, 700, tabular-nums,
  `background:var(--nav-actief)`, `color:#fff`, `border-radius:999px`, `padding:1px 8px`. In het actieve item
  wordt hij `rgba(255,255,255,.22)`. Er komen geen nieuwe kleuren bij.
- De kop: dezelfde `header.kop` als de andere delen. Daaronder `.bw-apparaat` en de statusregel `.bw-status`,
  met dezelfde klassen als in de balk van de werklijst. De statusregel is leeg zonder hoogte, en niet
  `display:none` (VA-90 §3).
- De lijst: een `<ul>` met per pand een `.card` in één kolom, ook op 1280px. Het is een korte rij en geen volle
  kaart: links het score-blok (`.score`, 44px), dan het adres (`.addr`), de chip en `.lid` met `Bewaard op …`,
  en rechts de knoppen `Open pand` (of `Open in BAG-viewer`) en de Bewaar-knop van VA-90. Er komt geen
  luchtfoto bij: dat houdt de lijst kort en vraagt niets extra op bij PDOK. Op 375px gaan de knoppen onder de
  tekst, in een `.bw-rij` die mag teruglopen. Er komt geen horizontale scroll, en niets komt over het adres of
  de score.
- Niet in deze werklijst: dezelfde rij, met `border-style:dashed` in `var(--baseline)`. De pil
  `Niet in deze werklijst` krijgt de vorm van `.bw-label.weg`, en `pagina.weg.zin` staat in `.lid` onder de datum.
- Leeg en geen opslag: het bestaande `.wl-leeg`-vak, met alleen de zin.
- Licht en donker komen alleen uit de tokens. Er komt niets bij.

**Een pand dat niet in deze werklijst staat.** Dat is een `bag_pand_id` in de opslag met `stand: "bewaard"`, dat
niet in `LEADS` (`PER_ID`) staat. De rij toont alleen wat is opgeslagen: `hoofdadres`, `woonplaats`, `score100`,
`pandcategorie`, `sinds` en `datapeildatum`, en de link naar `bag_viewer_url`. Ze heeft geen "Open pand", want
VA-61 heeft de data niet. Weghalen werkt op het opgeslagen object zelf, want `zet()` heeft nu een lead `d` nodig.
Geef het een pad dat met het id en het opgeslagen object werkt, en dat ook `herstel()` aankan. Gebruik
`hoofdadres` als `{adres}` in de statusregels. In de opslag verandert niets: VORM blijft 1.

**Focus.**
- Na weghalen: de rij is weg, en de focus gaat naar **Ongedaan maken** in `#bwBewaardStatus`. Dat is dezelfde
  regel als VA-90 §8: een pand dat uit de lijst gaat, geeft de focus aan zijn Ongedaan maken.
- Na Ongedaan maken: de focus gaat naar de Bewaar-knop van de teruggekomen rij.
- Is de lijst na weghalen leeg: de focus gaat toch naar Ongedaan maken. Het lege vak staat eronder.
- Na "Open pand" vanaf deze pagina: sluit je het venster, dan gaat de focus terug naar de "Open pand" van de rij
  (VA-61). Haal je het pand in het venster weg en sluit je het dan, dan is de rij er niet meer. De focus gaat
  dan naar Ongedaan maken in `#bwBewaardStatus`, en anders naar `#bewaard` zelf (`tabindex="-1"`). Nooit naar
  `<body>`. Een pand dat je opent vanaf deze pagina, krijgt zijn statusregel daarom ook in `#bwBewaardStatus`.
- Op "Toon alle / Toon alleen de laatste 10" blijft de focus op de knop.

**Wat er ook zo blijft.** Verborgen panden staan niet op deze pagina. Verbergen haalt een pand uit de bewaarde,
want dat is de regel van VA-90. De rij en de telling in het menu volgen dat zonder herladen. Ook de telling in de
menulade op 375px volgt het.
Uitloggen wist niets. Geen cijfer verandert: de werklijst blijft 500, net als de KPI's en het kantoor.

**Proefresultaat (de bouw voor één stad).** De tekst zegt "werklijst". De live pagina is de landelijke bouw.
Krijgt de stadsbouw dit deel ook, vraag Lumi dan om `pagina.weg.*` voor die bouw. Verzin het niet zelf.
