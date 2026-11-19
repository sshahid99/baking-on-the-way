# Errors the agent made that our checks caught

| # | date | error | caught by | fix |
|---|---|---|---|---|
| 1 | 2026-11-18 | **US-format timestamps silently declined every order as "late".** `12/06/2026 7:45 PM` could not be read, so the cleaner treated unreadable as after-cutoff and then stopped with "No orders survived cleaning", blaming the data. | Small evaluation, case E6 (criteria written before the run): 17/20 points, E6 0/3 | Rule C5b: read ISO and US formats and AM/PM times; an unreadable time gets its own message. Re-run: 20/20. `work/eval-results.md` |
| 2 | 2026-11-18 | **OSMnx failed and the system quietly used the straight-line fallback.** The road download worked but `nearest_nodes` needs scikit-learn. | Reading the `source` column of the matrix file ("fallback: straight-line…") and the stderr line | Installed scikit-learn, rebuilt from real OSM roads (legs 1.8–14.4 min vs fallback). Fallback still exists by design. |
| 3 | 2026-11-18 | **Unrealistic oven model:** one full batch at a time capped the oven at ~3 trays/hour; the first plan declined 6 of 13 orders and the old rule lost $235. | Looking at the first run sheet against common sense, before building further | Team chose staggered 12-piece trays (M6). |
| 4 | 2026-11-18 | **Success measures that could not fail:** median arrival gap was ~1 min even before learning; profit uplift +395% against a straw-man baseline. | `checks/measures.py`, comparing first 10 vs last 20 mornings | Team changed KPI to worst-stop gap (G3) and made the baseline fairer (B2). Reported the learning effect as profit over-promise $52 → $11/morning. |
| 5 | 2026-11-18 | **Clock-skew rule would have hidden real lateness.** v1 of L4 called any row 40–85 min off plan a clock error, which a truly late van would also be. | Agent re-reading its own rule against early mornings, which are late before learning | Rule L4 now looks for a jump between consecutive rows. |
| 6 | 2026-11-18 | **Misleading instruction to Rosa:** "Say no: Uptown Commons" while Uptown was stop 7 (only its 9:07 PM add-on was declined). The independent reviewer passed it because every number was right. | Main session, comparing the declined list with the route in the first live `/plan-run` (trace `work/runs/2026-11-09-trace.md`) | Rule C5c (commit 699b3d1) and reviewer prompt v2 check 4 |
| 7 | 2026-11-18 | **Prompt text corrupted by argument substitution:** `$1` in plan-run.md became the log file path. | Reading the expanded command at the start of the first live run | plan-run.md v2 ("one dollar") |

To add: one error the **plan-reviewer** subagent catches during a `/plan-run`, and one that the
pre-push hook blocks (see `work/hook-log.md`).
