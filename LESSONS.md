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
- ~~**Headless Chrome cannot make a 375 px window; measure 375 inside an iframe.** *(2026-11-09,
  Vera, VA-61)*~~ Struck 2026-11-15: it can, see the CDP `Emulation.setDeviceMetricsOverride`
  line (VA-63) below.
- ~~**A pand's x,y is not its hoofdadres point.**~~ ~~11 of 20 Delft leads are 5,7–18,3 m off,~~
  9 of 20, 3,4–26,3 m (VA-78, 2026-11-14), ~~because x,y, postcode and huisnummer come from
  another VBO of the pand. *(2026-11-09, Vera, VA-62)*~~
  Superseded by VA-78 (2026-11-13): the address fields and x,y now come from the hoofdadres VBO.
- **A fixed `data-theme="light"` on `<html>` overrides `prefers-color-scheme`.** Ayman wants the
  dashboard to open light on every computer; only the Thema button sets the theme. A design file
  that follows the OS colour scheme quietly decides the default. *(2026-11-09, Vera, VA-66)*
- **Refetching from CBS into scratch and comparing byte for byte proves "fetched, not typed".**
  CBS names keep their own suffixes ("Utrecht (gemeente)"); stripping them would be typing.
  *(2026-11-09, Vera, VA-65)*
- **Measure memory on Windows with `K32GetProcessMemoryInfo` and declare its `argtypes`; without
  them the call quietly returns nothing.** The national ingest of 9.998.456 VBO's then measured
  26 MB peak. *(2026-11-09, Vera, VA-34)*
- **A test that writes its own expected value proves nothing.** VA-34's Delft-gemeente test fed
  0503 in itself; a real-data test that skips without `bag_nl_*.sqlite` checks the real file.
  *(2026-11-09, Vera, VA-34)*
- **A streaming rewrite must match the in-memory route for every input that route took, not only
  the one being measured.** Several snapshots that share a pand merged in memory, and the first
  stream dropped them; it now merges per pand-ID in snapshot order. National run: 9.998.456 VBO's,
  6.568.913 panden, peak 174 MB, 832 s. *(2026-11-09, Vera, VA-36)*
- **A box with `aspect-ratio` and `max-height` keeps its ratio by shrinking its width.** Set
  `width:100%` and measure the width as well as the height when you cap it; the 3D camera then
  widens its view instead of cropping. *(2026-11-11, Ada and Vera, VA-64)*
- **Turn transitions on after the first frame.** A layout class set at load otherwise animates:
  the drawer slid across the phone screen on every load. *(2026-11-11, Lumi, VA-63/VA-64)*
- **"Not a literal in the code" includes `.get(key, default)` fallbacks.** Read required config
  keys bare and let the config check name what is missing. *(2026-11-11, Vera, VA-37)*
- **A national run never holds all panden.** Counts, the 20 best and the best `werklijst_max` per
  part stay in memory; the 441.997-row master stock is sorted in a temporary SQLite on D:. Peak
  172–184 MB for 6.568.913 panden. *(2026-11-11, VA-37)*
- **A payload with hundreds of records puts labels and repeated values in once and gives each
  record numbers** (2 MB went to 0,89 MB for 500 panden); a test unfolds the short form back to
  the full one. When measuring Fast 4G, report warm and cold runs apart: a cold headless start adds
  about 2 s at any page size. *(2026-11-12, Ada and Vera, VA-39)*
- **A test that pins committed bytes must be told which columns a story is allowed to move, and
  check those columns by their meaning.** VA-79's `ja`/`nee` turned the byte-for-byte Delft check
  in `test_werklijst.py` red even though `VERWACHT` held; it now compares column by column and reads
  ja/nee and the August `True`/`False` alike (`selectie.lees_janee`). *(2026-11-13, Rex, VA-79)*
- **Fields shown together must come from one record.** `hoofdadres` was the first address in sorted
  order but postcode and x,y came from the first VBO in input order; VA-78 takes them from the
  hoofdadres VBO. Nationally 31.946 postcodes and 156.407 locations moved, and no gemeentecode or
  werklijst ID did. A hoofdadres VBO can lack a postcode (8 national werklijst/proef rows, 2
  Delft proof leads), so the Postcode row can go empty. *(2026-11-13, Rex, VA-78)*
- **Take a download's date from its own entry, never from the feed header.** PDOK's BAG feed says
  `<updated>2026-11-08</updated>` at the top because of the zip; the GeoPackage entry still says
  11-01. A partial download gets a name the ingest pattern cannot match, and a live check of a
  real folder runs with an impossible disk floor, so it can never start a 7,8 GB download by
  accident. *(2026-11-13, Rex, VA-72)*
- **Keep built cards in a Map keyed by ID and hang them back on redraw,** so a filter change
  never re-requests the PDOK photos (500 cards scrolled = 500 requests; filtering after that = 0).
  Screenshot the dashboard headless with CDP `captureScreenshot` and a clip, and test lazy
  rendering with reduced motion on. *(2026-11-13, Ada and Vera, VA-68/VA-71)*
- **The KVK test key is in the public history of `ea91e7f` by Ayman's "Push as is" (2026-11-06), and
  in no tree since `2bef49f`.** A history scan that finds it in those two commits is expected; a
  third hit is a new leak. *(2026-11-13, Vera, VA-1)*
- **`requirements.txt` is also what makes Railpack detect Python; without it every build fails
  ("Railpack failed to prepare the build", `9efe917`).** It pins only `requests` and `pyyaml` to
  `pip show` on this laptop; any new line, pytest included, is an escalation to Ayman.
  *(2026-11-13, Vera, VA-10)*
- **Headless Chrome can measure 375 px after all: CDP `Emulation.setDeviceMetricsOverride`
  {width:375} gives innerWidth 375 and fires the max-width media queries; `setEmulatedMedia`
  covers dark mode and reduced motion.** *(2026-11-13, Vera, VA-63)*
- **To test page code against data the pipeline cannot make, edit the built PAYLOAD, not
  `panden_*.json`: `build_dashboard.py` stops on a missing bouwjaar or oppervlakte before the page
  exists.** *(2026-11-14, Vera, VA-69)*
- **A full-page or element screenshot does not show where a sticky element sits: the capture draws
  beyond the viewport without resizing it, so `position: sticky; bottom: 0` lands mid-page.** Judge
  sticky controls from viewport screenshots at the start, middle and end of their container.
  *(2026-11-14, Lumi, VA-69)*
- **A finding's figures go on record with their per-item list. VA-78's "11 of 20, 5,7–18,3 m" had
  none and did not reproduce (9 of 20, 3,4–26,3 m).** *(2026-11-14, Vera, VA-78)*
- **Locatieserver's free search returns the closest match, not always the exact address: 2 of 20
  Delft hoofdadressen came back as 18A or 9A.** Check `weergavenaam` before measuring a distance
  to it. *(2026-11-14, Vera, VA-78)*
- **An output built in a scratch run matches its commit when three checks agree:** the code copy's
  hashes equal the commit's, the output equals the commit after CRLF normalisation, and a cheap
  independent recompute agrees. *(2026-11-14, Vera, VA-78/VA-79)*
- **A headless browser never makes `document.hidden` true, even when a second tab is in front; prove
  "pauses when the tab is hidden" by overriding `document.hidden` and firing `visibilitychange`, then
  counting frames, and say in the close-out that it was simulated.** *(2026-11-16, Vera, VA-85)*
- **The dedup register is the only state the pipeline must never rebuild: it lives in git
  (`register/geleverde_panden.csv`), not in `data/`, and a test that runs `run_proef.main()` must point it
  elsewhere.** `nederland.draai()` takes it as a required keyword so a forgotten test fails instead of
  writing the real register; the Delft route follows `run_proef.BASE`. *(2026-11-16, Rex, VA-6)*
