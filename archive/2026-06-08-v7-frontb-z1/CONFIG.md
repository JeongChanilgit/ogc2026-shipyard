# Archive 2026-06-08-v7-frontb-z1

Snapshot of `src/{myalgorithm,baseline_greedy,parallel_decode}.py` after the
2026-06-08 session's Front-B + z1 work. All changes are **objective-safe**
(consider() = official check_feasibility + strict obj-improvement gate, so no
candidate can ever worsen the returned solution).

## Submission defaults (env flag 0개로 돌 때)

| Lever | flag (default) | what |
|---|---|---|
| Front B z2/z3 reassign | `OGC_FRONTB` (ON) | iterated relocate + swap-fallback, ranked by exact `_assignment_proxy` (w2·z2+w3·z3), each gated. **Gate = current `best_z1<=0`** (was the buggy incoming-floor `base_report.obj1` -> skipped all z2/z3 opt). |
| Front B swaps | `OGC_FRONTB_SWAP` (ON) | only when relocates stall (relocate-first so swaps don't crowd out the feasible relocates). Frees a slot in a full pref bay. |
| Front B z1>0 ext | `OGC_FRONTB_Z1POS` (ON) | run Front B on z1>0 too (after tardy moves); consider() keeps z1 unchanged -> captures z3 on tardy instances (prob_12 -28%). |
| Tardy relocation | `OGC_TARDY_RELOC` (ON), `OGC_TARDY_RELOC_K` (16) | relocate worst-K tardy blocks for ALL n (was OFF for n>120) — full-obj gated, accepts z3 cost for z1 gain. prob_12/14 z1 1->0. |
| Wide cum_level orders | `OGC_CUMLEVEL_ORDERS` (size-gated: **5 if n>150 else 3**) | more decode orderings = the lever that scales z1 down with time. prob_13 10->7, prob_20 10->2 (tl=600). Inner order loop is deadline-bounded with FULL per_cum, so safe. |
| cum_level alphas | `OGC_CUMLEVEL_ALPHAS` (`90;85;80`, 3) | KEPT at 3: `per_cum = bay_slice*0.30/len(alphas)` so MORE alphas STARVE every decode (regressed prob_6/14). Breadth comes from ORDERS, not alphas. |
| xbatch | `OGC_XBAY_BATCH` (ON) | batch bay-clearing cross-bay. prob_12 z1 3->1, full-20 no regression (old prob_18 50->102 dead-end obsolete in cum_level-first pipeline). |
| -1 hardening | `OGC_CHECK_COST_CAP` (1.3), `OGC_HARD_FRAC_LARGE` (0.988) | reserve real check cost + larger wall margin on big n. prob_20 returns 296->293s. |
| BR cache | `OGC_BR_CACHE` (ON) | memoize Block.bounding_rect. |

## Key results

- **Front B**: z1=0 instances total obj ~-348K (prob_10/2 -42%, prob_9 -37%, prob_19 -33%, prob_16 -31%, etc.).
- **z1 (the headline)**: z1>0 is a TIME+SEARCH-BREADTH issue, not a floor. With eval-server time (per-instance up to 30 min) + wide cum_level:
  - prob_11 -> 0 (480s), prob_12/14 -> 0 (tardy reloc), prob_13 10->7->1 (tl 300->600->1800), prob_20 10->9->2.
  - obj on prob_13 -48%, prob_20 -53% (z1 dominates).
- **-1**: none (all feasible, all runs).

## Why prob_13/20 need time
crane j>=k = blocking job-shop: many tight-due blocks compete for one bay's crane in one time window -> serial queue -> some late (musical chairs). Finding a packing/order where all get crane in time is NP-hard; more cum_level orders (deadline-bounded) finds it given time.

## Do NOT
- raise cum_level ALPHAS count (per_cum starvation).
- mix relocate+swap in one ranked list (swaps crowd out feasible relocates).
- gate Front B on base_report.obj1 (incoming floor z1) — use best_z1.

## Dead-ends retested-obsolete / confirmed
- xbay_batch prob_18 50->102 (2026-06-07): obsolete now (cum_level runs first+capped).
- wide alphas (95;90;..): regresses via per_cum starvation.

Validation: v7 (full-20 tl=300) — see results/capture/v7/.
Prior archive: archive/2026-06-08-dual-config/.

## Addendum — z2/z3 + runtime phase (2026-06-08, post-v7)

User asked to lower z2/z3 (z1-safe) and cut runtime (z1-safe). Findings (data-backed):

- **z2/z3 is MAXIMAL via Front B.** Tested `OGC_FRONTB_STALL=6` + `OGC_FRONTB_TRIES=40`
  on prob_7/10/15/17 -> obj/z2/z3 BYTE-IDENTICAL to v7. Front B already captures every
  feasible reassignment; the residual z2 (prob_17 z2=5825, prob_15 z2=3759 etc.) is
  load imbalance the PACKING forbids removing (can't move blocks to balance without a
  crane/tardiness violation). New flags (both default-neutral): `OGC_FRONTB_STALL` (2).

- **Runtime is necessary incumbent-building.** Profiled prob_2 (n=100, tl=200):
  baseline/greedy 27s + seeds_decode 33s + search 65s -> incumbent obj 10760, then
  Front B 10760->5030. The search is somewhat redundant on Front-B-dominated instances
  but is the cum_level INPUT on hard ones (prob_13/20), so cutting it risks z1.
  `OGC_SEARCH_STALL_PCT` (default 0=off) global-best wall-stall early-exit added but it
  does NOT bite reliably (the worker search keeps finding sub-0.1% internal gains) and
  runtime reduction has ZERO score impact (fixed per-instance eval budget). Left OFF.

- **The one remaining deep lever: a polygon-nesting packer** (bbox->polygon gap, the
  long-standing #1 lever). Tighter packing -> more feasible reassignments (z2/z3 down)
  AND less crane serialization (z1 down). NOT attempted: it replaces core geometry =
  high regression risk to the locked wins, uncertain payoff. Decision deferred to user.

## Addendum 2 — wall-margin safety floor (2026-06-08)

User: "speed feels shaky" -> the algorithm returned ~294/300s (only ~6s margin),
risky for -1 on the eval server's hard wall-clock.

- **`OGC_WALL_MARGIN_S` (default 8.0)**: hard_stop = t_start + min(hard_frac*T, T - 8).
  Guarantees >=8s below the wall regardless of T.  Only pulls in hard_stop (NOT the
  search budget done_by), so cum_level keeps its time -> prob_13 STAYS z1=7 while the
  margin nearly doubles (6s -> 11s at T=300, return 294->289s).  Small instances
  already had >=9s (hard_frac 0.970) so unchanged; at large eval T the fraction
  dominates and this is a no-op (no productive time lost).  `OGC_DONE_BY_FRAC` (0.88)
  also made env-tunable.
- TRADE-OFF measured: cutting done_by too (0.80 + hard_frac 0.95) gave 18s margin but
  COST prob_13 z1 7->10 (cum_level starved).  So the margin floor (hard_stop-only) is
  the right lever; raising OGC_WALL_MARGIN_S much past ~12 starts to cost prob_13 z1.
