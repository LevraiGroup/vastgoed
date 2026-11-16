# Copy VA-93 (the werklijst says plainly when it is full): Lumi, 2026-11-16

For Ada. Read from VASTGOED `origin/main` at `65d8945`, read-only: `config.yaml` (`drempels.werklijst_max: 500`,
`score_min_voor_werklijst: 8`), `nederland.py` (`draai`, `totalen`), `selectie.werklijst`, and in
`build_dashboard.py` `KOP_TEKST_LANDELIJK`, `LIJST_TEKST`, `SLOT_TEKST`, `KAART_TEKST` and `nl_getal`.
Figures below are the 1 November 2026 run (geschikt 263.319, werklijst 500), for illustration only; the build
takes every number from the data and `config.yaml`.

All copy Dutch, one table in Python (`LIMIET_TEKST`), placed by the script, never formatted there. No second
locale exists.

---

## 0. Tension with Ayman's direction of today (Nova rules, not me)

The story is Ayman's own words: *"zet bij werklijst ook ergens 500 limiet bereikt"*. Later the same day, about
the band (`0b1d010`): *"500 on werklijst dont sound like a lot ... replace that with just stating werklijst"*.
Criterion 1 requires the status to show `werklijst_max`, and its test looks for that number. So:

- **Column A (as the story is written, my default):** the limit figure is shown, but framed as a rule,
  "per maand", next to "Limiet bereikt", not as a count after the word werklijst. The second line
  (262.819 others also qualified) makes the list read as a selection of the best, which is the opposite
  of "not a lot".
- **Column B (if Nova applies Ayman's later remark to VA-93):** no figure in the status line. Criterion 1's
  test then changes. One key differs; everything else is the same.

---

## 1. Where it goes, and how it looks

- **In the werklijst section**, one line directly under the section's meta line (`#secmeta`, "500 panden ·
  450 uit de 25 grootste gemeenten · 50 elders"), above the filter bar. A plain `<p class="wl-limiet">`:
  built at build time, it does not change on the page, so **no `role="status"` and no `alert`** (criterion 7).
- **Look: a status, not a warning.** A small pill with a filled dot in `--s3` (the band's werklijst green),
  text in `--ink`, the second line in `--ink-2`. No orange, no red, no icon of a stop sign: the list is full
  on purpose.
- **No "·" in these lines.** Some screen readers read the middle dot aloud ("punt in het midden", my note in
  `copy-va90.md`); colons and commas only.
- **Not in VA-85's band (criterion 5, my choice): no.** Ayman removed the count from the band this evening
  (`0b1d010`, "just stating werklijst"). A "500 limiet bereikt" beside "Werklijst" in the band would put back
  exactly what he took out. The band's five figures stay as they are.

---

## 2. The copy table (`LIMIET_TEKST`)

| Key | When | Column A (default, story as written) | Column B (Ayman's later remark applied) |
| --- | --- | --- | --- |
| `vol` | panden on the werklijst = `werklijst_max` | **Limiet bereikt:** {max} panden per maand. | **Limiet bereikt.** |
| `deels` | fewer than `werklijst_max` (criterion 2) | {n} van de {max} plaatsen gevuld. | {n} van de {max} plaatsen gevuld. |
| `meer` | limit reached and `meer` > 1 (criterion 3) | {meer} andere panden haalden ook score {drempel} of hoger, maar staan niet op de werklijst van {maand}. | same |
| `meer.een` | limit reached and `meer` = 1 | 1 ander pand haalde ook score {drempel} of hoger, maar staat niet op de werklijst van {maand}. | same |
| *(none)* | `meer` = 0 | line not shown | line not shown |

Placeholders:

- `{max}` = `drempels.werklijst_max`, `{n}` = number of panden on this month's werklijst (the data, not the
  slot's 5 and not a filter count), `{meer}` = `geschikt` − `{n}`, `{drempel}` = `score_min_voor_werklijst`,
  `{maand}` = the werklijst month in words, as the section title has it ("november 2026"). Numbers through
  `nl_getal()`. Rendered today (A): "**Limiet bereikt:** 500 panden per maand." and "262.819 andere panden
  haalden ook score 8 of hoger, maar staan niet op de werklijst van november 2026."
- **Bold:** only "Limiet bereikt" (`<b>`), in both columns.
- The Delft test of criterion 1 (`werklijst_max` 20) renders "**Limiet bereikt:** 20 panden per maand.", with
  no "500" anywhere in the status.
- **`deels` has no "bereikt"** (criterion 2) and uses "plaatsen", not "panden", so it cannot be read as the
  filter count "{n} van {totaal} panden" (criterion 4). It shows `{n}`; that is the criterion, and with a short
  list the number is the information. Ayman's remark was about a full 500.

### Why the wording is true in every month

- **"per maand"** holds: `werklijst_max` caps one werklijst, and there is one werklijst per month (Q37
  answered "C: volgende maandrun", VA-94 Rejected). It promises nothing about a next set (criterion 6): no
  "volgende", no "leegmaken", no "wachten".
- **`meer` says "staan niet op de werklijst", never "passen er niet op".** `geschikt` in `totalen` also counts
  panden that met the score but were delivered in an earlier month (`nederland.draai`:
  `tel["al_geleverd"]`, "telt mee als geschikt"). From December those are in `geschikt` too. They are not
  on this werklijst, so the sentence stays true; "passen niet" would not be. Today `al_geleverd` is 0 in
  practice (the register holds only November).

### Against the filters and Verberg (criterion 4)

The status counts this month's list and never moves. The filter count keeps its own place (in the filter bar)
and wording ("Alle {totaal} panden", "{n} van {totaal} panden", and with the slot "De {n} zichtbare panden").
The two cannot be read as one number: the status speaks of "plaatsen" or "per maand", the filter of
"panden" shown. VA-90's Verberg changes neither the status nor `meer`.

---

## 3. Questions for Nova

1. **Column A or B?** VA-93 is Ayman's "500 limiet bereikt"; later the same day he said "500 on werklijst"
   does not sound like a lot and asked for just "werklijst" (in the band). Which came last in the chat, and
   does it reach this line? With B, criterion 1's test ("finds that number") has to be rewritten.
2. **`meer` and earlier deliveries.** From the second month on, `geschikt − werklijst` includes panden
   delivered before. My sentence stays true, but if you want `meer` to mean "qualified and still new", Rex
   adds `al_geleverd` to `totalen` and the build subtracts it. Same gap as the Brein page's register step
   (`copy-va98-99.md`, Q3).
