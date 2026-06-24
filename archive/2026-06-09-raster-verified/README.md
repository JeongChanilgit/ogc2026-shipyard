# Archive: 2026-06-09 raster-verified

Snapshot of `src/` after the POLYGON-RASTER floor breakthrough, BEFORE wiring it
default-ON and before any postprocess-insight experiments.

## State captured
- pos_k=2 adaptive floor: SHIPPED (default ON).
- **OGC_FLOOR_RASTER: implemented, gated OFF (default).** When ON: tl=100 full-20 = 20/20 z1<30 (prob_20=20, prob_14=1, prob_18=0), no regression, no infeasible. This is the verified tl=100 solution; just needs default-wiring after a tl=300 no-regression check.
- Other gated experimental flags (default OFF): OGC_FLOOR_ANTISTACK, OGC_FLOOR_SERIAL, OGC_FLOOR_GRID, OGC_PP_ROUND_S (warm-restart).
- Default behaviour (no env) = pos_k=2 only (raster OFF) → prob_20=64 at tl=100. To get the 20/20, set OGC_FLOOR_RASTER=1 (or wire default ON).

## md5
- myalgorithm.py: 05c4a85317a050a3b3518a9ce34d0bfa
- baseline_greedy.py: 990b94c9c8d995ffffdbbc02149b3772

## Restore
    cp archive/2026-06-09-raster-verified/src/*.py src/

## Do NOT touch
- src/utils.py (eval overwrites), baseline/ (original).

See notes/SESSION-HANDOFF-2026-06-09-raster-floor.md for the full picture + next steps.
Prior safe archive: archive/2026-06-09-known-good/ (pre-pos_k=2, 300s good config).
