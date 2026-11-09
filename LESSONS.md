# Lessons — VASTGOED

Read before starting. One line per lesson, with its date and source. Superseded lessons are
struck through with the reason, never deleted.

- **README figures can be stale. Pin against the committed output, not the prose.** The
  README says werklijst 1.655; the committed CSV, `data/panden_delft.json` and the dashboard
  all give 1.668 (1.655 dates from before the `verbouwing_bag` signal). *(2026-11-06, found by
  Ada in VA-9, explained by Vera in VA-2)*
- **`data/vbo_delft.json` is the only copy of the August data and is not in git.** Read it,
  never move, rename or overwrite it; test pipeline changes on a copy of the folder.
  *(2026-11-06, Nova's seed backlog, VA-3)*
- **Since VA-3 the pipeline reads the newest snapshot by default.** Anything meant to
  reproduce August Delft must pass `snapshot="vbo_delft.json"` (the file name, not the date)
  explicitly. *(2026-11-06, Vera, VA-2/VA-3)*
- **`datapeildatum` comes from the snapshot; `vbo_delft.json`'s date exists only in
  `config.yaml` (`snapshots.ongedateerd`).** Remove that line and every run on the August data
  stops with FOUT. Fix it by restoring the date, never by falling back to today.
  *(2026-11-06, Rex, VA-4)*
- **This repo has `core.autocrlf=true`.** `git show HEAD:output/*.csv` is LF; the checked-out
  CSVs and `run_proef.py`'s output are CRLF. Compare a regenerated CSV against the checked-out
  file (or with `git diff`), never against `git show`. *(2026-11-06, Vera, VA-4)*
- **The real `data/` has no `panden_delft.bron.json` (it predates VA-3), so a dashboard built
  from it says "Peildatum onbekend" until `run_proef.py` has run. That is correct, not a
  regression.** Since VA-12 `nl_datum()` returns hard spaces (` `); tests comparing a date
  string must use `bd.NBSP`. *(2026-11-06, Vera, VA-12)*
- **On this Windows checkout (`core.autocrlf=true`) a plain Python text-mode rewrite keeps
  CRLF; it turns to LF only if the write passes `newline='\n'`, or `newline=''` after a
  default read.** Check a rewritten file with `git diff --stat`: a whole-file diff means the
  line endings changed. *(2026-11-06, Rex, corrected by Vera, VA-5)*
- **A safety check lists the files it protects, not everything in a folder that other
  processes also write to.** The read-only test watched all of `data/` and went red while the
  GeoPackage downloaded into `data/bron/`. *(2026-11-06, Vera, VA-44)*
- **Check a scratch copy is complete before trusting it (sha256 of every file on both
  sides), and count "rows moved" by position, not by diff lines.** Scratch copies under Temp
  lost files twice on 11-06/07; a diff's 411 changed lines were 491 moved rows.
  *(2026-11-07, Vera, VA-32)*
- **Every push deploys to Railway, and the deploy serves everything in `design/`.** Stage
  files by name; never `git add -A` (an untracked design page would go live). Railway's
  `railway.json` is closed to new services (hard cutoff 2026-12-01): configure the build in
  `railpack.json`. The deploy serves the committed LF blob, so compare its hash with
  `git show HEAD:<file>`, not the CRLF checkout. *(2026-11-07, Rex and Vera, VA-46)*
- **A line the page shows is built and tested in Python, never formatted in template
  JavaScript.** A second date or number formatter in the script drifts from `nl_datum()` with
  no test turning red; `kantoor_teksten()` returns the finished line and the script only places
  it. Check a ported copy table mechanically (run the old JS table and the new Python on the same
  inputs, every state), not by eye. *(2026-11-08, Vera, VA-31)*
- **A WFS figure in the record has a date; compare only figures of the same date.** The older
  9.978.773 was labelled as checked on 11-06, and VA-33 reported a 19.683 "unexplained" gap
  that was really 1.370. *(2026-11-08, Vera, VA-33)*
- **Check "is it deterministic?" under two `PYTHONHASHSEED` values, not by running twice.** The
  key order of a dict filled from a set varied per process: `panden_delft.json` had another
  SHA-256 per seed while the CSVs stayed equal. *(2026-11-09, Vera, VA-42)*
- **A scratch copy can carry other stories' uncommitted work.** Build the `design/index.html`
  for a commit from HEAD plus only that commit's files, in a clean worktree, after
  `run_proef.py`. *(2026-11-09, Vera, VA-42/VA-47)*
- **A config check that names the key and its value stops a typo before anything is written.**
  `NaN` passes `isinstance(x, float)`; compare `x != x`. *(2026-11-09, Vera, VA-41)*
- VA-24 and VA-43 taught nothing new beyond their criteria (stated plainly, as the DoD asks).
- **A memory test has to be able to go red.** Holding all 1M rows still peaked at only 270 MB,
  under the 500 MB criterion, so the assert is 100 MB; checked by forcing the writer to hold
  every row (19,9 MB streaming). *(2026-11-09, Vera, VA-35)*
- **Move a design file's text into Python as data, not as functions, and express any literal a
  guard test bans (2048 as `1 << 11`) instead of loosening the test.** Test a blocked CDN and
  WebGL off separately (headless Chrome `--disable-3d-apis`). *(2026-11-09, Vera, VA-60)*
- **A third-party script must not hold up the page.** A plain `<script src>` to cdnjs that hangs
  delays every card; the page now loads three.js itself and starts the 2D office after 4 s.
  *(2026-11-09, Vera, VA-60)*
- **Make a dialog with a header a flex column with `min-height:0` on its body.** Capping the body
  with `calc(100dvh - N)` cut off 66 px at 375 px when the header wrapped; measure the scrolled
  bottom, not only `scrollWidth`. *(2026-11-09, Vera, VA-61)*
- **Headless Chrome cannot make a 375 px window; measure 375 inside an iframe.** *(2026-11-09,
  Vera, VA-61)*
- **A pand's x,y is not its hoofdadres point.** 11 of 20 Delft leads are 5,7–18,3 m off, because
  x,y, postcode and huisnummer come from another VBO of the pand. *(2026-11-09, Vera, VA-62)*
