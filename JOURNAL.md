# Journal — VASTGOED

A dated entry every working day: what moved, what got in the way, what we know now that we
did not know this morning.

## 2026-11-06 (Friday)

- **Assigned.** Ayman put the squad on VASTGOED and confirmed that Levrai approved the 20-pand
  Delft proof. The folder became a local git repository (no remote, `data/` ignored), first
  commit `ea91e7f`.
- **Sprint 1 started early** at Ayman's request ("Start now"), 2026-11-06 to 11-13, 10 points:
  VA-1, VA-2, VA-3, VA-4, VA-9.
- **VA-9 (Ada):** the dashboard's werklijst count and label follow
  `drempels.score_min_voor_werklijst`. Checked DONE by Vera; with threshold 8 the rebuilt
  dashboard is byte-for-byte the committed one.
- **Learned:** the werklijst figure is 1.668, not the README's 1.655 (see LESSONS.md).
- **In progress:** VA-2 (Vera's regression suite, 15 tests green; being pinned to the August
  snapshot), VA-3 (Rex's dated snapshots, built, awaiting check; the dashboard part is Ada's).
- **Waiting on Ayman:** Q2, whether the public KVK test key may stay in
  `TOEKOMSTVERBETERINGEN.md` (blocks VA-1).
- **Noticed, not on the board yet:** `selectie.py` (~line 387) and `build_dashboard.py`
  (line 24) open JSON files without closing them (ResourceWarning in every test run).
