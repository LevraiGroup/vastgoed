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
