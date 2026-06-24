# Archive: 2026-06-09 known-good

Snapshot of `src/` taken 2026-06-09 ~05:11, BEFORE the tl=100 combined-solver
experiments. This is the verified-good submission bundle.

## What this is
- Default config (no env flags) = the "300s good config": **20/20 z1<20 at tl=300**,
  prob_20=9~14, prob_14 single-digit. Reliable (low variance) at tl>=300.
- Includes the 2026-06-09 adaptive **fast-floor** (short-tl robustness): at tl<150
  large instances run BL-only floor so cum_level keeps a window. Inactive at tl>=150
  (full greedy), so the 300s behaviour is unchanged from the 2026-06-08 v7-frontb-z1
  state.
- Gurobi timing port present but **default OFF** (OGC_GUROBI_TIMING=0; measured worse
  than CP-SAT on the disjunctive timing model).

## Known tl=100 limitation (the thing being worked on)
- prob_20 ~120 (variance 119~830), prob_14 ~110 at tl=100. Both >30.
- Root cause (measured 2026-06-09): cum_level's geometric layout-spread (~42s, ESSENTIAL
  -- CUMLEVEL=0 -> 1544) starves the efficient bbox_pack (0.6s in trace) which is what
  reaches the assignment bbox-floor ~68. crossbay reassign then -> 9 at tl=300.
  tl=100 is architecturally time-starved for the 250/300-block instances.

## Restore
Copy these files back over `src/`:
    cp archive/2026-06-09-known-good/src/*.py src/
md5 of myalgorithm.py at snapshot: 94ad7b751773343e9606ea65ff8f211e

## Do NOT touch
- `src/utils.py` (eval server overwrites it), `baseline/` (original).
