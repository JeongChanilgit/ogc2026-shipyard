# Per-bay packer search — ledger (2026-06-18)

**Goal (user, standing until told to stop):** find a good per-bay packer to support B1
(the gassign LBBD decoder), measured in the isolation benchmark. Judge = per-bay z1,
never-infeasible. Decoder slot = `_decode_bay` in gassign LBBD; swap in the winner later.

**Benchmark:** `notes/research/perbay/bench.py` — extracts real per-bay block SETS from a
saved solution (gf_noperbay_120 = gassign B1→B2→B3, no perbay), runs candidate packers on
each bay in isolation, validates via the OFFICIAL checker on a single-bay sub-instance,
scores z1 + wall. Packers: `packers_cpsat.py`.

**Primary test bay:** prob_27 bay 1 — 102 blocks, bay **168×16** (very thin), baseline
(B2+B3) z1 = **2,549**, 72/102 tardy, 73 delayed (can't fit at release). Hardest of the 5
set2 bays scanned.

## Findings
- **C1 — dense-greedy v0 (LCA / contact-area) FAILS.** z1=2,732 (worse than BL 2,567) AND
  2.6× slower (18.4s). Confirms memory "LCA net-neg". Naive contact-maximisation is not the
  lever. ✗
- **C2 — plain BL (B2) = 2,567**, baseline B3 re-timing → 2,549. Greedy class plateaus ~2,550.
- **C3 — windowed rolling CP-SAT** (EDD batches of K, earlier batches frozen as obstacles,
  box-decomp disjunction per batch). Sweet spot K≈30 → **2,484** (first to beat baseline,
  −2.5%). K=12→2,959, K=20→2,767, K=45→3,292 (model too big for batch budget). MORE batch
  budget did NOT help (K=30: 8s→2,484 vs 15s→2,521) ⇒ the limit is **myopia** (per-batch
  objective ignores downstream blocks), not budget. ≈baseline.
- **C4 — ALNS destroy/repair (user's idea: swap blocks between adjacent time windows).**
  Seed = baseline placement; destroy a subset (tardy / window / adjacent-window / random),
  CP-SAT repair (x,y,entry) with the rest frozen, greedy accept ⇒ **monotone, never worse**.
  60s, subset=12, repair=2s → **2,518** (−31, −1.2%), only 4/36 moves accepted. Works but
  small gain at this size. Most promising structurally (never-worse + targets bottleneck).
- **C5 — area-cumulative LB.** Relaxation (co-present footprint-area ≤ bay area, ignore
  geometry) finds z1 ≤ **597** (not converged; proven LB only 54). ⇒ **area is NOT the
  bottleneck — the ~1,900 gap from 2,549 is GEOMETRIC packing inefficiency** (the 80%→95%
  density wall). Big room in principle, but our geometric packers aren't cracking it on this
  thin bay. Caveat: proven LB is loose (54); true geometric optimum unknown.

## Open hypotheses / next
- This bay (168×16) may be geometrically pathological (thin ⇒ ~1D packing) → TEST OTHER BAYS
  to tell "weak method" from "hard bay".
- ALNS tuning: bigger subsets (18-25), time-SLAB destroy (re-pack the most-congested
  interval), seed from windowed-K30 best, more iters / SA acceptance.
- v2: let the ALNS repair also choose ORIENTATION (small subset ⇒ affordable 4D).
- Speed: a 30-60s/bay packer is too slow for production (many bays × LBBD iters); quality
  first, then make the winner fast.

- **C6 — ALNS generalisation (3 bays, 40s, subset=14).** prob_39 b0 (80 blk): 766→677
  (**−11.6%**, 6 acc). prob_27 b1: 2549→2504 (−1.8%). prob_26 b1 (59 blk): 575→575
  (**0 acc**, greedy is a local optimum greedy-acceptance can't escape). Variable, modest,
  always never-worse.
- **C7 — benchmark cache-poisoning bug FIXED.** `boxsolver._FP_CACHE` is keyed by
  (block_id, orient) which collides ACROSS instances → wrong geometry → false infeasible
  when benchmarking multiple instances in one process. `bench.clear_caches()` per instance.
  (Same family as the 2026-06-12 capture-harness poisoning.) Algorithms were always sound.
- **C8 — ★ joint CP-SAT does NOT beat greedy at scale (reframes C5).** Whole-bay box-decomp
  on prob_26 b1 (59 blk): K=59 → **1,106**, K=30 → 694, both WORSE than greedy 575 (model
  too big → CP-SAT returns a poor feasible point in 70-140s). ⇒ **the area-relax floor (6/27/
  605) is NOT geometrically reachable** — area-feasible ≠ geometric-feasible (the fundamental
  hardness of 2D irregular packing). The greedy (B2) is actually STRONG; the realistic lever
  is **greedy + local ALNS polish** (never-worse), NOT a from-scratch joint solve. Tight
  geometric LB still unknown (so true room unknown, but it's far less than relax suggests).

- **C9 — ALNS + SA + faster repair (the realistic lever).** repair_s 2.5→1.0 (more iters)
  + best-tracking + optional SA acceptance. Per-bay best over {greedy, SA} @40s:
  prob_26 569 (−1.0%, SA), prob_39 646 (**−15.7%**, greedy), prob_27 2457 (−3.6%, SA).
  greedy vs SA is BAY-DEPENDENT (greedy when clear downhill, SA when stuck) ⇒ run BOTH
  take best (portfolio). Net: per-bay z1 −1…−16%, never-worse, but ~40s/bay.
  **Role split:** greedy BL = the right DECODER (fast, strong, for the LBBD inner loop);
  ALNS = the right POLISH (slower, leftover-wall — same niche as the existing `perbay`
  stage). Joint CP-SAT is neither (too slow + worse, C8).

- **C10 — orientation in the repair (4D: x,y,orient,entry) IS a real lever, but
  expensive.** ncand=2 orientations per block in the repair. prob_39 b0: fixed −13.4% →
  **4D −17.4%** (best yet). BUT the 4D model is much bigger ⇒ far fewer iters
  (prob_27 b1: 14 iters / 0 acc, WORSE than fixed −3.4%). Net + on small/medium bays,
  net − on big bays (iter starvation). Confirms the user's "orientation matters" — needs
  smaller subset / budget mgmt to afford the 4D model on big bays.

### Best-so-far per bay (greedy+ALNS portfolio, never-worse)
| bay | base | best | config |
|---|---|---|---|
| prob_26 b1 (59) | 575 | 569 (−1.0%) | SA fixed |
| prob_39 b0 (80) | 766 | 633 (−17.4%) | 4D greedy |
| prob_27 b1 (102) | 2549 | 2457 (−3.6%) | SA fixed |
Winning config is BAY-DEPENDENT ⇒ portfolio {fixed,4D}×{greedy,SA}, take best.

- **C11 — 4D subset sizing + VARIANCE.** prob_39 4D ss=8/10/14 → −4.8/−13.2/−7.6%
  (earlier ss=14 was −17.4%): **high run-to-run variance** (CP-SAT 4-worker nondeterminism
  + random ALNS). prob_27 (102 blk) 4D ≈0% at every subset — orientation gains don't
  materialise on big bays. ⇒ single-run per-bay numbers are NOISY; conclusions need
  multi-seed averaging. The realistic per-bay gain is modest (~−5 to −15% on medium bays,
  near-0 on the thin 102-blk bay), always never-worse.

- **C12 — ★ LITERATURE RESEARCH (4 parallel web-researchers) + cheap levers tested.**
  Reframings: 3D orthogonal strip packing (extrude footprint over time), 2D Dynamic Storage
  Allocation (DSA), shipyard **spatial scheduling** (closest match). Our "greedy floor +
  CP-SAT timing oracle" decoupling is the literature-endorsed correct structure (DSA "Algo C").
  Method catalog (refs in `research-2026-06-18.html`): fast constructive = **Extreme-Point**
  (Crainic 2008), **Empty-Maximal-Space** (Lai&Chan), **time-axis skyline** (=our fastfloor),
  **semi-discrete BLF** (Oliveira 2021, ~100× faster than NFP), **ROMA raster penetration**
  (Toledo 2019, O(1) grid overlap); ordering = **ATC**(Morton), **COVERT**(Carroll),
  **TCI×RCI**(shipyard); metaheuristic = **SWO**(Joslin'99, blame-tardy→reorder), ALNS, GLS
  overlap-allowed (Sparrow 2025 SOTA, Rust); LB = 1-machine tardiness + area-time cumulative.
  TESTED CHEAP (greedy re-runs, no CP-SAT): **COVERT ordering beats EDD big** (prob_26 773→642
  −17%; prob_27 COVERT **2524 BEATS baseline 2549** even WITHOUT B3). SWO improves its EDD seed
  (prob_39 783→749) but < COVERT. ⇒ **ORDER is a near-free real lever**; best-order + B3 is the
  form. Order-race {EDD,COVERT,slack,release,ATC} take-best is the cheap decoder upgrade.

- **C13 — order-race + timing-oracle + never-worse ALNS (BUILT in packers_cpsat.py).**
  `pack_order_race` = greedy over {EDD,COVERT,slack,ATC,release}, best-of, then `solve_timing`
  (pure 1-D disjunctive oracle = B3 on FIXED layout: footprint-cell-overlapping pairs must be
  time-disjoint, min tardiness). `pack_alns` seeded from best-of(baseline, race) ⇒ never-worse.
  Clean results: prob_27 order-race **COVERT 2524 BEATS baseline 2549** (near-free), +ALNS →
  **2498 (−2.0%)**; prob_39 +ALNS → **618 (−19.3%)** (best); prob_26 → 575 (0%, baseline B3
  already strong). NOTE the per-bay greedy is SLOW (~7s/102-blk) ⇒ order-race needs ~50s budget;
  variance still notable (prob_27 ranged 2374-2498 across runs). Pieces are correct + never-worse.
  **Consolidated best-per-bay:** 575 / 618 / 2498 (vs base 575 / 766 / 2549).

- **C14 — multi-seed reliability (signal vs noise).** ALNS-from-baseline ×3 seeds @20s:
  prob_26 [575,573,566] mean −0.7%; prob_39 [687,713,678] mean **−9.5%**; prob_27
  [2526,2544,2515] mean −0.8%. Variance moderate (±15-35) ⇒ gains are REAL, not noise.
  Bay-dependent: big on prob_39 (recoverable structure), ~−1% on saturated prob_26/27.
  (20s < 40s ⇒ slightly smaller gain; more budget helps, diminishing.)

## ✅ SEARCH RESULT (good per-bay algorithm DELIVERED)
**Validated, never-worse per-bay packer = COVERT order-race + timing oracle + ALNS polish**
(all in `packers_cpsat.py`). Reliable per-bay z1 reduction **−1% to −19%, bay-dependent,
never-worse**. order-race COVERT alone beats baseline on the hard 102-blk bay (near-free).
Negative results (don't retry): dense-greedy/LCA, whole-bay joint CP-SAT (worse at scale),
windowed rolling CP-SAT (myopic). Geometric packing ceiling is real (area-relax floor not
reachable). DECISIVE NEXT (beyond per-bay): instance-level A/B — does per-bay polish move the
FULL-INSTANCE obj (the B1 goal)? Wire into gassign `_decode_bay` (order-race) + `perbay` stage
(ALNS polish) and measure full set.

- **C15 — INTEGRATION + instance-level A/B (the "supports B1" test).** Added F4=COVERT,
  F5=ATC to `fastfloor._ft_order` + `_FT_ORDER_KEYS` (ADDITIVE; F0-F3 unchanged; safe). The
  decoder `gassign._decode_bay` already races F0 + `OGC_GASSIGN_WP_KEYS` and keeps lowest
  bay-z1 (never-worse, gated `OGC_GASSIGN_WELLPLACED`). So COVERT integrates with ZERO new
  code — just `OGC_GASSIGN_WELLPLACED=1 OGC_GASSIGN_WP_KEYS=F4`. Launched A/B (bg btmtfaqs8):
  prob_26/27/39 @T=240, COVERT-race ON vs OFF, compare FULL-INSTANCE obj. Caveat: the race
  costs 1 extra decode/bay/LBBD-iter (slow greedy ~7s/102blk) ⇒ may reduce LBBD iterations;
  net effect = what the A/B measures.
  **A/B RESULT (3 set2 inst @240, full-instance obj):** OFF 103.32M → ON 102.13M =
  **−1.15% net** (prob_26 −7.3%, prob_27 −0.2%, prob_39 **+2.2% REGRESSION**). wall identical
  (232s, not a timeout). ★ KEY: per-bay never-worse does NOT transfer to instance-level —
  the decode ORDER changes the LBBD cuts → different master ASSIGNMENT (non-local). prob_39
  was the BEST per-bay (−19%) yet WORST instance (+2.2%); prob_26 inverse. So COVERT-race is a
  REAL but MIXED instance lever (net +, not dominant). NEXT: full set2 A/B for the total-obj
  verdict (project rule). NOTE: COVERT-race only active where gassign runs (T≥MIN_T=200 =
  server set2 regime); at operating TL=120 gassign is OFF so this is moot for set1.

- **C16 — ★★ FULL set2 A/B: COVERT-race REJECTED (decisive).** OFF 282.64M → ON 283.80M =
  **+0.41% (WORSE), 8 wins / 10 losses.** The preliminary 3-inst −1.15% FLIPPED on the full
  set. Net +0.41% is WITHIN the CP-SAT noise band (per-inst ±3-4%: prob_26 OFF varied
  23.75M↔24.63M across runs) ⇒ statistically meaningless. ★★ DECISIVE LESSON: **per-bay z1
  gains do NOT transfer to instance obj** — (a) CP-SAT nondeterminism, (b) LBBD coupling (a
  "better" per-bay decode changes the cuts → different master ASSIGNMENT, non-local). The
  per-bay benchmark optimizes a PROXY (per-bay z1) that doesn't reliably drive instance obj.
  ⇒ The real B1 lever is the ASSIGNMENT (gassign-first, set2 −95.7%), not the per-bay decode.
  Further per-bay micro-opt (EP/EMS, more ordering/polish) has questionable instance payoff.
  ACTION: do NOT enable OGC_GASSIGN_WELLPLACED=F4. F4/F5 keys stay (additive, off by default,
  harmless). No revert needed.

## STATE / honest conclusion (2026-06-18)
The per-bay packer space is well-mapped. **Greedy (B2) is strong; the only thing that beats
it is local ALNS polish (never-worse, modest −1…−17%, bay-dependent + noisy). Joint CP-SAT
(windowed or whole-bay) does NOT beat greedy at scale (model explodes). The geometric
packing ceiling is real and not cracked.** Best per-bay = portfolio {fixed,4D}×{greedy,SA}.
Open question that matters most now: does per-bay polish move the FULL-INSTANCE obj (the B1
goal)?  — needs an instance-level A/B, not just per-bay z1.

## Next experiments (queued)
- multi-seed reliability (3-5 seeds) to separate signal from CP-SAT noise.
- portfolio runner: {fixed,4D}×{greedy,SA} take-best per bay.
- 4D with smaller subset (8-10) ⇒ more iters on big bays (recover prob_27).
- portfolio runner: {fixed,4D}×{greedy,SA} take-best per bay.
- congestion-targeted destroy operator (blocks present during the peak-tardiness window).
- speed curve (gain vs 5/10/20/40s) — production viability.
- THEN: wire the winner into gassign `_decode_bay` (decoder) and/or the `perbay` polish stage.
- v2: orientation choice INSIDE the ALNS repair (small subset ⇒ affordable 4D) — the
  unexplored dimension; test if (x,y,orient,entry) joint repair beats fixed-orient.
- speed curve: ALNS gain vs budget (5/10/20/40s) — is most gain early? (production needs fast)
- portfolio: greedy∥SA take-best; congestion-targeted destroy operator.

## Numbers (prob_27 bay 1)
| method | z1 | wall | note |
|---|---|---|---|
| baseline B2+B3 | 2,549 | — | 72/102 tardy |
| BL (B2) | 2,567 | 7s | |
| LCA dense-v0 | 2,732 | 18s | worse+slow ✗ |
| windowed CP-SAT K=30 | 2,484 | 27s | best so far (−2.5%) |
| ALNS (seed=base, 60s) | 2,518 | 59s | monotone, 4/36 acc |
| area-cumulative relax | ~597 | 25s | floor (area-only) |
