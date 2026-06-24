# Archived config — 2026-06-08 (DUAL)

Snapshot of src/ after the 2026-06-07/08 Z1-quality + speed session.

## Submission-active defaults (no env flags = submission)
- OGC_SLAB_PACK = ON  (polygon-tight packing; 14->16/20 z1=0)
- OGC_SLAB_DUAL = ON  (all-bbox first then slab per-bay-if-better; prob_13 27->10, no regress)
- OGC_ORDER_BREAK = ON  (cum_level stops bay at LB; objective-safe)
- skip_greedy_floor for 300x5 only when T < 150 (so prob_20 runs the load-bearing
  greedy floor at the eval's budget: prob_20 z1 ~1731@240s -> 10@300s)

## Measured (tl=300, eval-representative): z1=0 16/20, z1>0 all <=10
  z1=0: 1-10,14,15,16,17,18,19   z1>0: p11=1, p12=3, p13=10, p20=10

## Off-by-default tunables (experiments)
  OGC_EXIT_ON_Z1_ZERO (dev speed, score-neutral), OGC_GREEDY_BL_ONLY (fast floor,
  worse assignment), OGC_FLOOR_BUDGET_PCT (breaks prob_20 -> do not use),
  OGC_CUMLEVEL_BUDGET_PCT(70), OGC_SLAB_PCT(100), OGC_SLAB_BESTOF, OGC_FORCE_GREEDY_FLOOR

## Dead ends (do not retry): best-of half/asymmetric budget (prob_6 starve),
  temporal_reassign (no-op), CUMLEVEL_PARALLEL (pollution), byte-id greedy (slower),
  greedy floor cap (infeasible).

## UPDATE (speed work, same day)
- OGC_BR_CACHE = ON (NEW): memoize Block.bounding_rect per-instance (monkeypatch).
  General speedup ~10-17% on converging instances (prob_3/5/7/19), z1 EXACT (verified
  same on all incl prob_11/13/20). Slow instances are CP-SAT-bound -> cache no help there.
- REDECODE_FAST: REJECTED (negligible + prob_20 10->19, approximation breaks it). OFF.
- BL_ONLY: Phase1 124->27s but assignment worse (prob_20 200s -> 83 vs full-floor 10). OFF.
