# Design and copy, VA-98 (the Brein page) and VA-99 (each step explains its rule): Lumi, 2026-11-16

For Ada. Mockup: `D:\Fortunas Apps\_scratch\lumi-1116\brein-mockup.html` (static, no external resource,
real figures of the 1 November 2026 run typed in **only in the mockup**; in the build every figure and
rule value comes from Python, VA-31's lesson).

Read from `origin/main` at `65d8945` (VASTGOED), read-only: `config.yaml`, `selectie.py` (`categoriseer`,
`uitsluiten`, `scoor`, `score_opbouw`, `naar_100`, `maandloting`, `werklijst`), `nederland.py`
(`aantallen`, `verdeel`, `draai`'s `totalen`), `register.py`, `build_dashboard.py` (`KAART_TEKST`, `MENU`,
`KOP_TEKST*`, `nl_getal`, `nl_datum_voluit`, `CATEGORIE_NAAM`), and the built `design/index.html`.
Searched the backlog and `design\richting.html` (VA-80) for what was tried: concept B "Selectiebrein" was
judged *"de ringen moet je eerst uitgelegd krijgen"*. This page answers that directly (section 1).

All copy is Dutch. The dashboard has no second language, so there is no other locale to fill.
Everything goes in one Python table, `BREIN_TEKST`; the script only places finished strings.

---

## 0. Tension with Ayman's direction of today (Nova rules, not me)

Ayman, 2026-11-16 (`0b1d010`, band): *"500 on werklijst dont sound like a lot ... replace that with just
stating werklijst"*. VA-98's title and criterion 3 ask for "the real count at every step", werklijst
included. **My default below honours Ayman:** the last step is named "Werklijst" with no big count; its real
numbers appear as the split (450 uit de 25 grootste gemeenten, 50 elders) in the step before it, and the
screen-reader text keeps the total, exactly as Ayman's band commit does (`aria` keeps the real count).
**Variant (story as written):** the werklijst step shows `{werklijst}` as its figure like every other step.
One key changes (`stap.werklijst.getal`); nothing else in this file moves. See the questions for Nova at
the end.

---

## 1. Design: what the page is

**One idea: the brain is the route.** Concept B's rings failed because nothing named them. Here each ring
*is* one step of the route, outside to inside in the same order as the list beside it, and each ring
carries its step number at twelve o'clock, so ring 3 and step 3 are found together without a legend.
Hover or focus a step, or open it (VA-99): its ring lights up and the others dim. Hover a ring: the tip
names its step and figure. That is the whole explanation the drawing needs.

**Layout, 1280 px.** Light page, navy sidebar (VA-63/66), as the dashboard. At the top, one navy panel in
the band's look (`--held`, glass, `--gloed`, `--schaduw-hoog`; no new base colour), full width of the
content column:

- left, about 58 %: the brain, a square 2D `<canvas>` (no three.js, no library, no font, no image);
- right: the route, an `<ol>` of glass steps in the band's `.trap` style, with the figure right-aligned in
  tabular numerals;
- under both, inside the panel: the scale note and (VA-99) the "open een stap" hint, small, `--nav-label`.

**375 px (and anything ≤ 800 px).** The brain on top at full width (square, max 420 px), the route below it
reading top to bottom. Opened steps push the list down; nothing scrolls sideways.

**The rings (outside to inside), and what moves.** Ring widths are *not* to scale (on scale the werklijst
would be 0,008 % and invisible); the note says so. Within a ring, divisions *are* to scale.

| # | Ring | Drawn as | Moves |
| --- | --- | --- | --- |
| 1 | Verblijfsobjecten | a wide field of faint dots | dots drift inward slowly |
| 2 | Panden | a dotted ring | dots gather onto it in small clusters (several VBO's, one pand) |
| 3 | Categorie A–E | five arc segments in `--s1`…`--s5`, **lengths in proportion to the five category counts of this build** (criterion 2) | most dots fade grey here; survivors take their category colour |
| 4 | Score ≥ drempel | a dashed ring, as `legenda.ring` in the band | the dash runs slowly (band's `lineDashOffset`) |
| 5 | Nooit twee keer | a thin solid ring with a small gap-gate | a dot that "was delivered" bounces off (only if the build has a count > 0; otherwise the ring is drawn still) |
| 6 | Rangorde en loting | a ring of short ticks | ticks shuffle once per cycle and stop: "fixed per month" |
| 7 | Verdeling | two arcs, 25 grootste vs elders, **in proportion to `werklijst_25` : `werklijst_overig`** (450 : 50) | dots split into the two arcs |
| 8 | Werklijst | the glowing core, label "Werklijst" (same as the band's `kern.label`) | soft pulse |

Ring 7 is drawn only for doelgebied Nederland. On a Delft build it is absent and the list has seven steps.

**Highlight.** Active ring: full opacity, 2 px brighter stroke, its step number white. Others: 35 % opacity.
No active step: all at their normal opacity.

**Motion (criterion 5).** `prefers-reduced-motion: reduce`: one complete still frame, every ring and the core
drawn, no button. Pauses when the page is hidden and when the canvas is out of view (IntersectionObserver),
as the band does. **Recommended, Nova may cut:** a small text button in the panel's top right corner to stop
the motion (WCAG 2.2.2: this page's centre moves for longer than 5 seconds). Copy in the table.

**Screen readers (criterion 7).** The canvas is `aria-hidden="true"`: the `<ol>` beside it already says
everything in order, and reading both would say every number twice. Each `<li>` reads name, figure and
sub-line as plain text.

**Size.** Its own file, `design/brein.html`. The page needs only the build's totals and the config values
below, not the 500 panden, so it should be small (tens of KB).

---

## 2. VA-98 copy table (`BREIN_TEKST`)

Placeholders: every figure through `nl_getal()`; dates through `nl_datum_voluit()` (hard spaces). `{maand}` is
the werklijst month in words, as `KOP_TEKST_LANDELIJK["werklijst.titel"]` already shows it ("november 2026").
A value the build does not have becomes "onbekend" (house convention), except where a row says the line is
left out.

### Menu and page head

| Key | Copy | Source / note |
| --- | --- | --- |
| `menu.brein` | Brein | Ayman's word. In `MENU`, group **Overzicht**, after Kerncijfers: it explains, it lists no panden. On `brein.html` the same menu; Kantoor, Kerncijfers, Voorraad and Werklijst link back to the dashboard at their anchor; Brein carries `aria-current="page"`. |
| `pagina.titel` (`<title>`) | Levrai · Pandenselectie — Brein | Same pattern as "Levrai · Pandenselectie — Nederland". |
| `kruimel` | Overzicht · **Brein** | As the dashboard's `.kruimel`. |
| `kop.titel` (h1) | Brein | |
| `kop.zin` | Van elk verblijfsobject in de BAG tot je werklijst, stap voor stap, met het echte aantal uit de selectie van {datum}. | `{datum}` = ophaaldatum of the build's bron, `nl_datum_voluit` ("1 november 2026"). Ayman asked for no intro line above the *Kantoor* band; this is a different page whose job is to explain, so I keep one line. Nova may strike it. |
| `route.label` (`aria-label` of the `<ol>`) | Van BAG naar werklijst | Same as the band's `trap.label`. |
| `noot.schaal` | De ringen zijn niet op schaal, de cijfers wel. | Follows the band's "De stroom is niet op schaal, de cijfers wel." |
| `knop.stil` | Zet stil | Optional pause button. `aria-label`: "Zet het brein stil". |
| `knop.beweeg` | Laat bewegen | Same button after pressing. `aria-label`: "Laat het brein bewegen". Not shown with reduced motion. |

### The steps (name, figure, sub-line)

| Step | `naam` | `getal` | `sub` | Source |
| --- | --- | --- | --- | --- |
| 1 `vbo` | Verblijfsobjecten | {vbo} | in de BAG van {datum} | `totalen.vbo`; Delft: `sub` = "in {gebied}, uit de BAG van {datum}" |
| 2 `panden` | Panden | {panden} | verblijfsobjecten samengevoegd per gebouw | `totalen.panden` |
| 3 `a_e` | Categorie A–E | {a_e} | A {A} · B {B} · C {C} · D {D} · E {E} | `totalen.a_e`, `totalen.categorieen`. Each letter on its colour swatch (`CATEGORIE_KLEUR`). Screen-reader text per letter: "A, Winkel + wonen: {A}" (`CATEGORIE_NAAM`), so the middle dots are not read aloud. |
| 3 `a_e.noot` | Een pand kan in meer dan één categorie vallen. Daarom tellen A tot en met E samen op tot meer dan {a_e}. | | | Shown only when the five counts add up to more than `a_e` (today 561.655 against 441.997). Without it, anyone who adds the letters finds the figures "wrong". |
| 4 `geschikt` | Score {drempel} of hoger | {geschikt} | panden in A–E met genoeg punten | `totalen.geschikt`, `drempels.score_min_voor_werklijst` |
| 5 `register` | Nooit twee keer | *(no big figure)* | {n_register} panden staan in het register als geleverd | Count of rows in the dedup register at build time (`register.Register`), if Ada's build reads it; **if the build does not have it, the sub-line is "Een geleverd pand komt niet terug"** and no number is shown. Not a big figure on purpose: the register count is not the number that dropped out at this step (see Nova Q3). |
| 6 `loting` | Rangorde en loting | *(no figure)* | hoogste score eerst, bij gelijke score de loting van {maand} | `totalen.maand` |
| 7 `verdeling` | Verdeling | {n_groot} + {n_rest} | uit de {aantal} grootste gemeenten · elders (each on the swatch of its arc: `--s1` and white, so the two arcs of ring 7 read without a legend) | `totalen.werklijst_25`, `werklijst_overig`, `aantal_grote_gemeenten`. Only for Nederland. Screen-reader text: "{n_groot} uit de {aantal} grootste gemeenten en {n_rest} elders". |
| 8 `werklijst` | Werklijst | *(default: no figure, the name glows; see section 0)* | {maand}, klaar voor je visuele controle | Screen-reader text adds the count, as the band's `aria`: visually hidden " — {werklijst} panden". Variant (story as written): `getal` = {werklijst}. |
| tips (canvas) | `tip.ring` = "{naam} · {getal}"; categories reuse `KAART_TEKST["cat.tip"]`; the core reuses `KAART_TEKST["kern.tip"]` | | | A step without a figure shows only its name. |

**Route order.** Steps 5 and 6 sit before the split, which is the order the code works in
(`nederland.draai`: geleverd panden are dropped, then each part is ranked with the month lottery, then
`verdeel`). The story's criterion 3 lists the six counted steps in an order this keeps; it only says the
tie-break and the register are "shown as steps". If Nova reads it otherwise, steps 5 to 7 can move without
any copy change.

---

## 3. VA-99 copy: each step opens to its rule

**Interaction.** Each step's header is a `<button aria-expanded aria-controls>` (the whole row; a chevron on
the right, `aria-hidden`). Click, Enter or Space opens; a second press or Escape closes, and Escape returns
focus to the step's button. **One step open at a time**, so the brain lights one ring. The rule text sits in
a region under the header, normal page text (not a dialog, not `role="alert"`). Accessible name of the
button = its visible text (name, figure, sub-line); no extra "Lees meer".

| Key | Copy |
| --- | --- |
| `noot.open` | Open een stap om te lezen hoe de regel werkt. |
| `grenzen` (once, under Categorie and Score) | Grenzen tellen mee. |

The same rule the werklijst filters follow (VA-69). True for every range below: the code compares with `<=`
and `>=`, and "vóór" with `<`.

### Step 1, Verblijfsobjecten (`regel.vbo`)

> Het systeem leest de hele BAG in, het openbare register van het Kadaster met elk gebouw en elk adres in
> Nederland, uit het bestand van PDOK van {datum}. Een verblijfsobject is één woning, winkel, kantoor of
> andere ruimte met een eigen adres.

Delft build: "Het systeem haalt alle verblijfsobjecten van {gebied} op uit de BAG, het openbare register
van het Kadaster, via de open dienst van PDOK. Deze ophaling is van {datum}."

### Step 2, Panden (`regel.panden`)

> Verblijfsobjecten in hetzelfde gebouw horen bij één BAG-pand. Het systeem voegt ze per pand samen en telt
> hoeveel woningen, winkels, kantoren en andere ruimtes erin zitten, hoeveel adressen het pand heeft, de
> oppervlakte van alles samen en het bouwjaar. Vanaf hier is het pand de eenheid: één pand is één lead.

(`selectie.aggregeer`: grouped on `pandidentificatie`, `totale_oppervlakte` is the sum over the VBO's.)

### Step 3, Categorie A–E (`regel.a_e`), and what always drops out (`regel.uit`)

Intro:

> Een pand gaat door als het in minstens één van vijf categorieën uit de briefing van Levrai valt:

One line per category, name from `CATEGORIE_NAAM`, values from `config.yaml` `categorieen.<key>.<field>`:

| Key | Copy |
| --- | --- |
| `cat.A` | **A · Winkel + wonen.** Minstens {min_winkel} winkel en {min_woon} woning, samen minstens {min_vbo} verblijfsobjecten, {opp_min}–{opp_max} m², gebouwd vóór {bouwjaar_voor}. |
| `cat.B` | **B · Bedrijf/kantoor + wonen.** Minstens {min_woon} woning en {min_overig_bedrijfsmatig} kantoor- of bedrijfsruimte, minstens {min_vbo_of_adressen} verblijfsobjecten of adressen, {opp_min}–{opp_max} m², gebouwd vóór {bouwjaar_voor}. Een ruimte met een overige gebruiksfunctie, vaak een berging, telt alleen mee als het pand geen winkel heeft. |
| `cat.C` | **C · Klein wooncomplex.** {woon_vbo_min} tot en met {woon_vbo_max} woningen, {opp_min}–{opp_max} m², gebouwd vóór {bouwjaar_voor}. |
| `cat.D` | **D · Groot oud pand.** Gebouwd vóór {bouwjaar_voor}, minstens {opp_min} m², met {vbo_min} tot en met {vbo_max} verblijfsobjecten. |
| `cat.E` | **E · Afwijkende combinatie.** Minstens {groot_opp_weinig_eenheden_opp} m² met hoogstens {groot_opp_weinig_eenheden_vbo} verblijfsobjecten, of minstens {min_adressen} adressen met minstens {functiegroepen_min} soorten gebruik in één pand (wonen, winkel, kantoor, bedrijf, overig). |
| `cat.noot` | Een pand kan in meer dan één categorie vallen; het telt dan in elke categorie mee, maar het blijft één pand. |

Today's values render as: A "Minstens 1 winkel en 1 woning, samen minstens 2 verblijfsobjecten,
150–1.000 m², gebouwd vóór 2000." Numbers through `nl_getal` (1.000, 1.500), **years never** (2000, 1940:
VA-69's rule, `jaar` stays unformatted).

**`{functiegroepen_min}` is not in `config.yaml`.** It is the literal `>= 3` in `selectie.categoriseer` (and
again in `scoor`). See Nova Q4. Until it is a named value, the page must not type "3" in its own table.

Then, under a small heading `uit.kop` = **Wat altijd afvalt**:

> Sommige panden doen nooit mee, ook niet als ze in een categorie passen:

| Key | Copy | Source |
| --- | --- | --- |
| `uit.status` | panden met de BAG-status {statussen}; | `uitsluitingen.status_uitsluiten`, each in single curly quotes, joined "‘a’, ‘b’ of ‘c’" |
| `uit.opp` | panden groter dan {opp_groter_dan} m², en panden zonder bekende oppervlakte; | `uitsluitingen.opp_groter_dan`; "zonder bekende oppervlakte" is `opp <= 0` in the code |
| `uit.doel` | panden die alleen een of meer van deze gebruiksdoelen hebben: {doelen}; | `uitsluitingen.enkel_gebruiksdoel_uitsluiten`, the BAG names as they are, joined "a, b, … of z" |
| `uit.complex` | grote moderne complexen: {modern_complex_vbo_min} of meer verblijfsobjecten en gebouwd in {modern_complex_bouwjaar_vanaf} of later. | `uitsluitingen.modern_complex_*` |
| `uit.leegstand` | Leegstand sluit niet uit. Een pand dat buiten gebruik is, krijgt juist {buiten_gebruik_bag} punten extra (zie Score). | House rule in `PROJECT.md`; `score.buiten_gebruik_bag` |
| `uit.aantal` (only if the build has it) | {uitgesloten} panden vallen hierdoor af. | `totalen.uitgesloten` exists in `panden_nederland.json` but is not in the page payload today |

**Do not list `uitsluitingen.bouwjaar_vanaf` here.** It sits under `uitsluitingen` in `config.yaml` (with the
comment "tenzij ander sterk kanssignaal"), but in the code it excludes nothing: it is the year from which the
−4 "recent gebouwd" aftrek applies (`scoor`). Listing it as an exclusion would be a promise the product does
not keep. It appears under Score.

### Step 4, Score (`regel.score`)

Intro:

> Elk pand in A–E krijgt punten voor wat het kansrijk maakt. Opgeteld is dat de leadscore.

A two-column list, label left, points right (tabular numerals, plus sign "+", minus sign "−" U+2212).
Weights from `config.yaml` `score.*`. The conditions in the labels are code literals today (Nova Q4).

| Key (`score.<config key>`) | Label | Points | Note line (small, under the label) |
| --- | --- | --- | --- |
| `winkel_plus_wonen` | Winkel en woning in één pand | +{w} | |
| `bedrijf_kantoor_plus_wonen` | Kantoor of bedrijf en woning in één pand | +{w} | Niet samen met winkel en woning: dan telt alleen die. |
| `vbo_3_tot_10` | 3 tot en met 10 verblijfsobjecten | +{w} | |
| `groot_opp_1_2_eenheden` | 400 m² of meer, met 1 of 2 verblijfsobjecten | +{w} | Kan niet samen met 3 tot en met 10 verblijfsobjecten. |
| `bouwjaar_voor_1940` | Gebouwd vóór 1940 | +{w} | |
| `opp_200_800` | 200–800 m² | +{w} | |
| `min_3_adressen` | 3 of meer adressen | +{w} | |
| `opvallende_functiecombinatie` | 3 of meer soorten gebruik in één pand | +{w} | |
| `buiten_gebruik_bag` | Leegstaand: buiten gebruik volgens de BAG | +{w} | |
| `verbouwing_bag` | In verbouwing volgens de BAG | +{w} | |
| `slecht_of_ontbrekend_energielabel` | Slecht of geen energielabel ({labels}) | **uit** | Staat uit: telt nu niet mee. |
| *(heading)* `score.aftrek` | **Aftrek** | | |
| `recent_gebouwd_of_vernieuwd` | Gebouwd in {bouwjaar_vanaf} of later | −{w} | |
| `groot_appartementencomplex` | {modern_complex_vbo_min} of meer verblijfsobjecten | −{w} | |

- `{labels}` = `bronnen.energielabel.slechte_labels` joined "E, F of G".
- **The energielabel row (my choice under criterion 3: shown as off, not hidden).** While
  `bronnen.energielabel.actief` is false it shows "uit" in `--muted` instead of "+2", and the note line.
  When it is switched on, it shows "+{w}" like the others and the note disappears. Same wording the Kantoor
  already uses ("telt daardoor nog niet mee"), minus the "nog", which promises a date nobody has set.
- The minus figures come from config already negative (−4, −5); print the sign as "−", not "-".

Then:

| Key | Copy |
| --- | --- |
| `score.drempel` | Een pand komt in aanmerking voor de werklijst bij {drempel} punten of meer. |
| `score.index` | Op de kaarten van de werklijst staat de score als index: {schaal_max} punten is 100, {drempel} punten is {drempel_index}. |

`{drempel_index}` = `selectie.naar_100(drempel, cfg)` (today 31), never computed in the template.

### Step 5, Nooit twee keer (`regel.register`)

> Een pand dat op een werklijst is geleverd, komt niet opnieuw op een werklijst, in welk gebied ook. Het
> register legt per pand vast in welke maand en op welke werklijst het is geleverd.

If the build has the count, add `regel.register.aantal`:

> Nu staan er {n_register} panden in het register, de werklijst van {maand} meegerekend.

("Meegerekend" because `nederland.draai` registers this month's list in the same run; today the register
holds exactly November's 500.)

### Step 6, Rangorde en loting (`regel.loting`)

> De geschikte panden staan op leadscore, de hoogste eerst. Bij gelijke score beslist een loting die voor de
> hele maand vastligt: wie de werklijst van {maand} opnieuw maakt, krijgt precies dezelfde volgorde. Elke
> maand heeft zijn eigen loting, en waar een pand in het land staat, telt daarin niet mee.

(`selectie.maandloting`: SHA-256 of "JJJJ-MM:bag_pand_id"; no location in it.)

### Step 7, Verdeling (`regel.verdeling`, Nederland only)

> De werklijst heeft plaats voor {werklijst_max} panden. {plaatsen_rest} daarvan zijn voor panden buiten de
> {aantal} gemeenten met de meeste inwoners (CBS), de andere {plaatsen_groot} voor die {aantal} gemeenten.
> Elk deel neemt de hoogste scores van heel Nederland. Heeft een deel te weinig geschikte panden, dan vult het
> andere deel aan.

`{plaatsen_groot}`, `{plaatsen_rest}` from `nederland.aantallen(cfg)` (today 450 and 50, from
`werklijst_aandeel_overig: 0.10`), shown as a count of panden (criterion 4), never as "10 %". These are the
*places*; the step's figure shows the *result* (`werklijst_25`, `werklijst_overig`), which differs only when a
part fell short.

### Step 8, Werklijst (`regel.werklijst`)

> Wat overblijft, is je werklijst van {maand}: de hoogst scorende panden die je nog niet kreeg, klaar voor je
> visuele controle op de kaart, de luchtfoto en Street View.

Delft build: "… de hoogst scorende panden van {gebied} die je nog niet kreeg, …". It says nothing about a next
set (VA-94 is Rejected; Q37 answered "C: volgende maandrun").

---

## 4. Words I did not use, and why

- **"live", "realtime", "online":** the selection is monthly (VA-85's rule).
- **"snapshot":** banned (Bronbestand ruling); "momentopname" only where the Kantoor already uses it.
- **"algoritme", "AI", "slim":** the page shows rules, all of which Levrai can check. "Brein" is Ayman's
  word for the picture; the text explains rules, not intelligence.
- **"500 op je werklijst":** removed from the band by Ayman today. Not reintroduced (section 0).

---

## 5. Open questions for Nova

1. **Does Ayman's "just stating werklijst" (`0b1d010`, the band) reach the Brein page?** VA-98 criterion 3
   asks for a count at the werklijst step. My default leaves it out (name only, split shown, count in the
   screen-reader text, as the band). Rule which column goes in.
2. **Where else does it reach?** The live page still puts "500" next to the werklijst in several places that
   are not the band: `werklijst.meta` "500 panden · 450 uit …", `werklijst.zin` "De 500 hoogst scorende
   panden van Nederland", the Kantoor's "500 panden op de werklijst" and "500 panden wachten op …",
   `feiten.cap` "De 500 panden van deze maand". Not my story to change; the record should say whether his
   remark was about the band only.
3. **Register count.** The build has no figure for "geschikt, but dropped because already delivered"
   (`tel["al_geleverd"]` is printed but not written to `totalen`). The register's row count is available but
   includes this month's own list, so it is not the funnel number. A true funnel figure needs Rex to add
   `al_geleverd` to `totalen` (a one-line change in `nederland.py`, Rex's territory). Until then the step
   shows the register size as a sub-line only.
4. **Rule values that live in code, not config.** The score conditions (3–10 verblijfsobjecten, vóór 1940,
   200–800 m², 3 adressen, 400 m² with 1–2, 3 soorten gebruik) and E's "3 soorten gebruik" are literals in
   `selectie.scoor()` / `categoriseer()`, and typed a second time in `score_opbouw()` labels ("Recent
   bouwjaar (≥ 2000)", "Groot complex (≥ 16 vbo)", which do not follow config). VA-99's page would be a third
   copy. Recommend: Rex names them as constants in `selectie.py` (no behaviour change, no config schema
   change) so the page reads the same value the score uses. Otherwise the page's table types them, and a
   test pins them against `scoor()` on crafted panden. Your call which story carries it.
5. **`uitsluitingen.bouwjaar_vanaf` is not an exclusion** in the code (it is the −4 threshold), despite its
   place and comment in `config.yaml`. My copy lists it under Score. VA-99 criterion 2 says "what keeps a
   pand out, from `uitsluitingen`": confirm that "not every key under `uitsluitingen` is an exclusion" is
   the right reading, so Vera does not fail Ada for leaving it out.
6. **The pause button** (WCAG 2.2.2). The band has none; this page's centre moves continuously. In VA-98 or
   not?
7. **Menu placement:** "Brein" in Overzicht, after Kerncijfers. VA-91 puts the bewaarde panden in the Panden group.
