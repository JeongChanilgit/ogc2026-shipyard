# CP-SAT Improvements Ledger (from `notes/research/cpsat-methodology/improvements.html`)

> User directive 2026-06-17/18: improve the solver using the improvements.html audit.
> **Do NOT discard an idea after one failure — modify/develop ~3 times, then drop it.**
> Decision metric (project rule): full set · total obj · never−1 · set1 no-regression.
> CP-SAT noise ±130K → cross-run ranking unreliable; prefer within-run diag.
> Run with `C:/Users/peter/anaconda3/envs/ogc2025/python.exe` (NOT conda run).

## Honest framing (from improvements.html verdict)
- set1 <1M is a **packing-density** ceiling, NOT reachable by CP-SAT modeling. Practical
  ceiling 1.31–1.39M. These CP-SAT changes buy **(1) speed** (same z1 sooner → reinvest
  budget in density/LNS) and **(2) never−1** (set2 submission safety = single biggest lever).
- So acceptance for the speed levers (C3/B2/A1) = set1 NO-REGRESSION + set2 obj ≤ baseline
  + feasible 40/40. The never−1 lever (B4) = pure insurance (no-op on feasible instances).

## Gates added (all default chosen so baseline = production, byte-identical)
| gate | default | what | item |
|---|---|---|---|
| `OGC_SERIAL_FLOOR_SAFETY` | **ON** | final serial-floor fallback if `sol` infeasible | B4 |
| `OGC_ORACLE_ZERO_STOP` | OFF | per-bay solve stops at proven tardiness LB | C3 |
| `OGC_TIMING_BUDGET_PROP` | OFF | per-bay budget ∝ block count (not flat) | B2 |
| `OGC_ORACLE_NOOVERLAP` | OFF | collision pairs → clique-edge-cover AddNoOverlap | A1 |

## Code locations (post-edit)
- `_zero_obj_stopper(cp_model, lb=0.0)` — myalgorithm.py:680 (generalized: stop at lb, not just 0).
- C3 wiring — myalgorithm.py:~2998 (monolithic) + ~2870 (decomp subset).
- B2 budget — myalgorithm.py:~2752 (`_budget_prop` weighted split, clamped to remaining wall).
- A1 NoOverlap + clique-edge-cover — myalgorithm.py:~2940 (build intervals + adjacency) +
  post-loop greedy clique edge cover.
- B4 safety net — myalgorithm.py:~7990 (before final `return sol`), reuses `_trivial_solution`
  (myalgorithm.py:2445, already an always-feasible EDD per-bay empty-window serial floor).

## Experiment log
> Format: `### [ID] hypothesis | cmd | result | decision (ADOPT/REJECT/ITERATE-n)`

### [I0] baseline + treatment A/B (C3+B2+A1) | ALL40 @120 | RESULT | DECISION=ISOLATE
- `imp_base` (gates OFF) vs `imp_c3b2a1` (all ON). **feasible 40/40 both (never−1 ✓).**
- **SET1 −73,514** (prob_20 −77,916, prob_12 −25,018 ; regress prob_6 +21,384, prob_14/15 +4K).
- **SET2 −5,081** (flat: prob_28 −1.41M, prob_30 −1.03M ; regress prob_39 +1.04M, prob_27 +0.92M,
  prob_26 +0.28M). **ALL40 −78,595.**
- **MECHANISM (per-z diag):** the combined change RESHUFFLES the search, not a clean improvement:
  - prob_20 win: z1=0 both, z2 1336→736 & z3 2361→1875 both ↓ → freed budget → better Pareto.
  - prob_28/30 win: z2/z3 identical, z1 ↓ (743→637, 1084→1007) → oracle reached lower z1.
  - prob_39/27/26 regress: z2/z3 identical, z1 ↑ slightly (oracle is z1-monotone, so the worse z1
    came from budget shift changing the produced floor/candidate). On w1≈13K, ±78 z1 = ±1M obj.
  - prob_6 regress: z1=0 both, downstream landed a worse z2/z3 Pareto from the budget shift.
- **DECISION: ISOLATE** which lever (C3/B2/A1) drives the real wins vs the reshuffle regressions.
  iso_c3 / iso_b2 / iso_a1 each alone on the 15 movers vs imp_base.
- ⚠ NOISE CAVEAT: instances that should be no-ops (prob_6 z1=0) moved → cross-run has real noise;
  trust only LARGE consistent deltas (prob_20, 28, 30). Plan a baseline-rerun noise control if needed.

### [I1] isolation C3 / B2 / A1 each alone | 15 movers @120 vs imp_base | CONFOUNDED BY NOISE
- Totals dominated by batch artifacts: prob_26 (+279,993) and prob_27 (+919,977) appeared IDENTICALLY
  across c3/b2/a1 → not gate effects, batch noise. Isolation totals uninterpretable as-is.

### [I2] ★ NOISE CONTROL — base×3 + comb×2 | 15 movers @120 | RESULT | DECISION=DO NOT ADOPT C3+B2+A1
- 3 baseline draws (SAME config, gates OFF): 15-mover total spread = **1,031,233**. Per-instance noise:
  prob_27 ±1,599,960 · prob_30 ±1,293,301 · prob_28 ±1,146,638 · prob_39 ±1,039,974. set1 near-zero
  (prob_20/14/15 = 0, prob_6 −326). ⇒ set2 single-draw is UNMEASURABLE (±1M CP-SAT 4-worker noise).
- comb (C3+B2+A1) 2 draws vs base 3 draws: **comb avg 170.0M vs base avg 168.5M = +1.55M (WORSE)**, all
  within noise. The set1 "wins" DO NOT reproduce: prob_20 comb draws = {103250, 181166} (one win, one
  no-change); prob_14/15 comb = {regress, identical}. **prob_20 −78K was a lucky draw, not a real win.**
- **DECISION: DO NOT ADOPT C3+B2+A1.** They are a noise-level reshuffle at fixed TL, not a reliable
  improvement. Keep all 3 gated OFF (= default, baseline unaffected). This is exactly the measurement
  trap the audit doc warned about (±130K, within-run diag only). Code stays in (gated) for possible
  higher-TL revisit, but NOT activated. **3-tries note:** before fully dropping, one more angle worth a
  try = C3 alone at HIGH TL (where freed budget compounds) on set1 (deterministic) — but low priority.
- **B4 (never−1) UNAFFECTED:** deterministic, pure safety, stays default ON. Validate engagement next.

## ★ BASELINE CORRECTION (user 2026-06-18): the baseline is the 290M algorithm, NOT 330M.
- 330M was a LOCAL T=120 artifact: gassign (`OGC_GASSIGN_MIN_T=200`) is OFF below 200s → only
  legacy+box → set2 ~329M. At the eval server's realistic TL (set2 = "minutes~30min"), gassign
  ACTIVATES → best-of(legacy,box,gassign) → **~290M** (the [E13] banked win, competitor 280.8M).
- **The DEFAULT config already IS the 290M algorithm** (OGC_HYBRID=1, OGC_GASSIGN_ON=True,
  OGC_GASSIGN_MIN_T=200, OGC_PERBAY=True, OGC_SERIAL_FLOOR_SAFETY=True). No code change needed to
  "make it default" — the 330M was a measurement-TL choice, not a default-config issue.
- Pipeline explained: `notes/research/algorithm-290M-explained.html` (6-stage sequence + budget + roles).
- ACTION: re-baseline at gassign-active TL. `base290_set2` = SET2 @240 production defaults (RUNNING).
  Future improvement A/B must use the 290M (gassign-active) baseline, and judge set2 on ≥3 draws.

## Smoke (pre-A/B, sanity only — single draw, NOT adoption evidence)
- prob_14 @45 C3+B2+B4: feas, obj=589338, z1=6, 38.4s. C3+B2+A1: feas, obj=589338, z1=6, 38.8s.
- prob_28 @45 C3+B2+A1 (set2 congested): feas, obj=10,398,707, z1=710, 42.6s. No exceptions; A1
  clique-edge-cover accepted by official checker (correctness confirmed).

## Recon for next iteration (code-analyzer, 2026-06-18)
- **B3 (box workers 1→4) — NEXT, highest-EV untested set2 lever.** `OGC_BD_WORKERS` read at
  `boxsolver.py:390,592` default `"1"`. Box-decomp runs STRICTLY SEQUENTIAL (`_pack_all` :1063 =
  plain per-bay loop, one `solver.Solve` per bay) → workers=4 = 4 cores, NO oversubscription.
  Box already auto-sets 4 in the solo feasspill path (:1400). **Caveat**: `OGC_PARALLEL_CANDS`
  (parcand.py) runs box ∥ gassign → 4×2 would oversub; parcand uses `OGC_PARALLEL_WORKERS=2`.
  Plan: bump boxsolver default 1→4 (gated), ensure parcand pins box workers=2 in parallel path.
  **B3 A/B is ENV-ONLY (no code edit to test):** baseline `OGC_BD_WORKERS=1` vs treatment
  `OGC_BD_WORKERS=4`. Sequential hybrid box (myalgorithm.py:7877, main process) gets all 4 cores;
  parcand `_box_worker` (parcand.py:36) sets its own (=2) so the parallel path is unaffected;
  feasspill solo (boxsolver.py:1400) + OGC_BOX_ONLY already 4. If 4 wins set2 → change the
  boxsolver.py:390,592 default literal "1"→"4". Run this A/B AFTER the C3+B2+A1 decision.
- **A3 (area-cumulative) — DEPRIORITIZED.** Valid demand = true polygon footprint area
  `max(1,int(_unary_union(layer_polys).area))` (boxsolver.py:497-500,538-540), NOT bbox w*h.
  Marginal value for the timing oracle (collisions already constrain). Revisit only if A1 shows
  the propagator route helps.
- **B1 (seed unify) — DEPRIORITIZED.** 4 distinct CP-SAT seeds (1/20260611/20260616/12345);
  `_dev_det` default OFF → submission path has NO seed = the ±130K noise. But forcing determinism
  costs eval throughput (doc + memory). Low payoff vs risk; revisit only for A/B reproducibility.

## Backlog (improvements.html, by priority — 3-tries rule each)
- P0: B1 (det-time cap + seed unify), B2 ✓, B4 ✓.
- P1: C3 ✓, A1 ✓, A3 (area-cumulative — needs VALID footprint-area demand, not bbox), B3 (param
  helper + box workers 1→4).
- P2: A2 (boxsolver NoOverlap2D), A4 (symmetry lex), C2 (wire dead lns.py time-shift destroy),
  C1 (hint carryover), D1–D3 (cp-sat/ LBBD cuts).
- FALSIFIED (do not retry): LCA/contact-area, temporal pre-staggering, finer-raster, exact box
  packer (pos+time joint), polygon-nester, learning-based, Gurobi timing port.
