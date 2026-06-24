# archive/2026-06-09-adaptive-raster

Snapshot of `src/` after wiring the **adaptive raster floor gate** (handoff Task A,
`notes/SESSION-HANDOFF-2026-06-09-adaptive-raster.md`). Supersedes
`archive/2026-06-09-raster-verified/` (gated-OFF raster) — here raster is the
DEFAULT inside the fast-floor branch.

## What changed (vs raster-verified)

`src/myalgorithm.py`, inside `if base_budget >= 2.0:` → `if _fast_floor:` only:

- When the fast floor triggers (short tl relative to n), it now defaults to
  **raster floor ON (`OGC_FLOOR_RASTER`) + `pos_k=3`** (was non-raster `pos_k=2`).
  Scoped to the greedy call: `os.environ["OGC_FLOOR_RASTER"]` is set right before
  and popped in `finally` (`_fast_raster_applied` guard), so only the floor call
  sees it.
- The raster crane/collision check is a cheap polygon-raster (cell-set
  disjointness, no Shapely), which makes the wider `pos_k=3` position search
  affordable in the short-tl budget → denser, still provably-feasible floor that
  crashes z1.
- **Kill-switches preserved**: explicit `OGC_FLOOR_RASTER` / `OGC_FAST_FLOOR_POS_K`
  win. `OGC_FLOOR_RASTER=0` reproduces the EXACT old shipped default (non-raster,
  `pos_k=2`). pos_k default pairs with raster (3 when on, else the old safe 2).
- **Non-fast-floor path is untouched** → keeps the z3-friendly default layout.

No other files changed from the raster-verified snapshot. `utils.py` / `baseline/`
untouched. AST OK.

## Why this is safe to ship

The gate fires only when `1.2e-3·n² > 0.4·T` (short tl relative to instance size).

- **tl=300 (eval-likely long tl): provably + empirically INERT.** Max est=108
  (n=300) < 0.4·300=120 → no instance triggers fast-floor → bit-identical to the
  old default. Verified: prob_17 obj 182223 == 182223 (identical); prob_20 z1=10
  (= default 10, NOT raster's ~5), obj 436829 vs 442347 = search-phase noise.
- **tl=100 (short-tl safety net): net hugely positive.** Converts 4 z1
  catastrophes into controlled solutions; costs 3 modest regressions (irreducible
  raster z1↔z3 trade; no size threshold can separate slack from catastrophe
  instances — prob_9 and prob_11 are both n=200, opposite needs).

## Evidence (tl=100, prob_9–20, conc 2; `results/capture/{adaptive100,default100}/`)

| inst | adaptive (raster+k3) z1 / obj | default (non-raster) z1 / obj | note |
|---|---|---|---|
| prob_9  | 0 / 208510   | 482  / 6552581  | ✅ catastrophe avoided |
| prob_10 | 0 / 99491    | 0    / 100478   | ✅ ~tie |
| prob_11 | 1 / 206376   | 1    / 133030   | ❌ obj +55% (z3) |
| prob_12 | 0 / 214998   | 13   / 483888   | ✅ |
| prob_13 | 1 / 245705   | 4    / 226382   | ❌ obj +9% (z1↓ z3↑) |
| prob_14 | 4 / 314332   | 1271 / 22730146 | ✅ catastrophe avoided |
| prob_15 | 0 / 137484   | 0    / 133284   | ❌ obj +3% |
| prob_16 | 0 / 147209   | 1    / 212208   | ✅ |
| prob_17 | 1 / 213946   | 8    / 293105   | ✅ |
| prob_18 | 4 / 284640   | 952  / 12899202 | ✅ catastrophe avoided |
| prob_19 | 0 / 97595    | 0    / 126101   | ✅ |
| prob_20 | 5 / 668584   | 1728 / 46435390 | ✅ catastrophe avoided |

All feasible, no −1. prob_1–8 (n≤150) never trigger → bit-identical to default.

`raster+pos_k=2` is strictly dominated (`results/capture/raster_k2_100/`): higher
z1 AND higher z3 than k3 (prob_20 z1=39/obj 1.75M; prob_14 z1=11). pos_k=3 is best
on all axes when raster is on.

## Future refinement (deferred)

Best-of-two floor (run raster + non-raster, pick min-obj by the existing candidate
gate) would recover the 3 regressions while keeping the wins, but is unaffordable
for the catastrophe instances (their non-raster floor doesn't finish in the short
budget). Out of scope for a short-tl safety net; eval is long-tl where this is moot.
