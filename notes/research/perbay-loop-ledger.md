# Perbay / Assignment Improvement Loop — Experiment Ledger

> Autonomous overnight loop (user directive 2026-06-17): hypothesis → validate → feedback → improve,
> until told to stop. Decision metric: **total obj over full set (set1 / ALL40), never −1**.
> Run with `C:/Users/peter/anaconda3/envs/ogc2025/python.exe` (NOT conda run).
> Persistent state lives HERE + memory `ogc2026-perbay-overnight-loop-2026-06-17`.

## T-mapping (corrected 2026-06-17)
- **Global assignment** = round1 **T2** (assignment + cumulative area-time) + **T6** (LBBD). → `src/gassign.py`
- **Per-bay placement** = round2 **T3** (candidate set-packing). → `src/perbay_t3.py`
- Existing `src/perbay.py` = round2 **T2+T6** (NoOverlap2D joint + crane) = per-bay placement ALTERNATIVE (A/B vs T3).

## Baselines (reference)
- Competitor set1 official total = 931,465.
- Our prior scores: `notes/research/baselines/tl120_all40_fixed.json` (scores only, box-OFF set2=4.24B).
- perbay (per-bay T2+T6) verified: set1 prob_14 −35%, prob_20 −23%; set2 modest (structural z1 / packing wall).

## Status board
| component | state |
|---|---|
| per-bay T2+T6 (`perbay.py`) | BUILT, gated best-of candidate, verified |
| global T2+T6 (`gassign.py`) | building |
| per-bay T3 (`perbay_t3.py`) | building |

## Experiment log
> Format: `### [ID] hypothesis | experiment cmd | result | decision (ADOPT/REJECT/ITERATE)`

### [E0] baseline capture
- Pending: full set1 + ALL40 baseline (PERBAY off) total obj, for loop reference.

### [E1] A/B per-bay T3 vs T2+T6 | direct compare prob_14, prob_28 | RESULT | DECISION
- perbay T2+T6: prob_14 z1 100→6 (obj −74%), prob_28 z1 1281→566 (obj −53%). FIRES, big wins.
- perbay_t3 T3: both fired=False (no improvement). Candidate-pair explosion (K²; n=82,K=12→413K disjunctions); discrete candidates lack spatial freedom vs continuous (x,y).
- **DECISION: per-bay engine = T2+T6 (perbay.py). T3 SHELVED** (revisit only with skyline/contact candidates + pair pruning; low priority).

### [E2] gassign (global T2+T6 LBBD) v1 | prob_21, prob_3 @60 | RESULT | DECISION=ITERATE
- prob_21: feasible 23.29M vs legacy 6.78M (WORSE). prob_3: 385.7K vs 77.3K (WORSE).
- Diagnosis: (1) z2 scale unit-mismatch (z1 real-time units, z2 = U*1000) distorts w1/w2/w3 balance; (2) RHO=0.85 too loose for set2 multi-layer → area-time doesn't prevent temporal overload; (3) LBBD cut only on decode-FAIL, not on TARDY assignments → degenerates to z1-blind.
- **DECISION: ITERATE** — fix the 3 issues. Global z1-aware assignment is the top untapped lever (set2 dominates total obj).

### [E3] establish E0 baseline | ALL40 @120 perbay-on single-leg | RUNNING
- Current production total obj (perbay on, leftover) + feasibility 40/40 = the number to beat in the loop.

### [E4] gassign fixes (unit-consistency + adaptive RHO + tardy LBBD cut) | prob_3/21/26/28 @60 vs _legacy_algorithm@60 | RESULT | DECISION=RE-EVAL@120
- Fix1: z1 term was 1000x under-weighted (z2 had U*1000, z1 didn't) → master made tardy "optimal" assignments. Now all 3 terms on common 1000x basis, ratio = w1:w2:w3 (checker-matched). THE root bug.
- Fix2: adaptive RHO = 0.85 − 0.12*max(0,(bpb−4)/4) − 0.20*multilayer_frac, clamp[0.55,0.85]. Dense set2 → 0.55 (tightens area-time).
- Fix3: tardy-aware cardinality cut on max time-overlap clique when true_bay_z1 > relaxed + slack (generalizes vs exact-set no-good).
- Results vs _legacy_algorithm@60: prob_21 4.37M (was 23.29M), prob_28 10.2M, prob_26 23.75M, prob_3 100K. Beats PURE-legacy@60 on set2.
- **⚠️ FAIRNESS CAVEAT**: compared vs pure-legacy@60 (no box, starved). Production = hybrid(legacy+box)@120. legacy is TL-sensitive on set2 (prob_21 @60=411M vs @120=2.29M). gassign@60 prob_21=4.37M LOSES to legacy@120=2.29M. So gassign's "wins" may be TL artifacts.
- **DECISION: RE-EVAL gassign@120 vs production hybrid@120** before any integration. Build `_gassign_eval.py`, run after E0 (no parallel heavy runs — CPU oversubscription distorts obj).

## ★GOAL (user /goal 2026-06-17, Stop-hook active): OUR total obj < COMPETITOR total obj.
- **Competitor targets** (`notes/competitor-2026-06-15.json`): set1=931,465 · **set2=279,824,051** · **ALL40=280,755,516**.
- Our box-on production ~331M (set2 dominates). Gap ~50M, ~all set2.
- Competitor set2 z1>0 too (prob_38 z1=4934, prob_27 z1=3496) → set2 tardiness structural for everyone; competitor just packs tighter.
- ★Clue: gassign@60 prob_26=23.75M < competitor 30.4M (WIN); prob_28 10.2M vs 9.4M (close). gassign in competitor range on set2.
- ★TL realization: eval server gives set2 "minutes~30min" (memory). Our 120s is conservative LOCAL TL; server passes more for big instances. So set2 @120 UNDER-measures us. For fair comparison vs competitor, also measure set2 @300+.

### [E5] gassign@120 SET2 vs competitor | RUNNING (killed E0 to prioritize — goal-critical)
- Decisive: where does gassign beat competitor / production on set2? Compare per-instance to competitor 279.8M.
- Next if gassign wins: integrate as gated best-of candidate (budget scaling with T; never starve legacy on set2 → -1) → measure hybrid total vs 280.8M.
- Also planned: set2 @300 (realistic server TL) for true competitive position.

### [PLAN] gassign best-of integration + budget (the crux)
- gassign = self-contained full solver (assignment+decode+timing) → produces feasible sol alone; competes with legacy/box.
- −1 SAFETY: legacy needs ~full T for set2 feasibility (memory). So CANNOT carve legacy's set2 budget. ⇒ gassign must be **T-gated**: only run when T is large enough to afford a slice WITHOUT starving legacy.
- Proposed: `OGC_GASSIGN_ON` (gate) + `OGC_GASSIGN_MIN_T` (~150). When T≥MIN_T: carve gassign slice from reserve/spare; add as 3rd best-of candidate (try/except + check_feasibility + strict-improve → never −1, only adopted where it wins). When T<MIN_T (e.g. local 120): skip gassign (legacy+box only).
- IMPLICATION: at LOCAL 120, gassign won't activate. But SERVER gives set2 "minutes~30min" → gassign activates there. ⇒ must test set2 @300 to see real effect.
- DO NOT edit myalgorithm.py while a run that lazy-imports it is in flight (module-cache inconsistency). Integrate between runs.

### [NEXT QUEUE]
1. (running) E5 gassign@120 set2 vs competitor.
2. set2 @300: legacy vs box vs gassign standalone (realistic server TL) — which wins per instance.
3. integrate gassign T-gated → hybrid+gassign @300 set2 total vs competitor 279.8M.
4. perbay polish on top (leftover) — additive.
5. if still short: the density lever (NFP/compaction) — the structural gap (memory: comp 95% vs us 80% packing).

### [E5 RESULT] gassign@120 SET2 vs competitor | feasible 20/20, total 303.3M vs comp 279.8M (+23.5M)
- gassign BEATS competitor on 5: prob_26(−6.5M), prob_35(−6.0M!), prob_27(−1.8M), prob_31(−1.3M), prob_40(−0.13M).
- gassign LOSES big on prob_38 (90.6M vs 68.3M, +22.3M = half the gap), prob_30/33/37 (+2.9~3.3M each).
- ★KEY: gassign beats OUR production (partial data) on prob_23,24,26,27,30,31,32,33 → **best-of(prod,gassign) prob_21~33 = 153.85M < competitor 156.61M (WE WIN by 2.76M on that segment!)**.
- gassign feasible 20/20 standalone @120, walls 60-120s → a feasibility backstop (adding it as best-of candidate REDUCES −1 risk, doesn't add).
- **DECISION: gassign is a real lever.** Get clean production set2@120 (E6) → compute FULL best-of(prod,gassign) total vs competitor 279.8M. If best-of wins → integrate gassign as gated best-of candidate.
- (HTML render of _gassign_eval crashed on CSS brace KeyError ' go ' — data fine in JSON; fix harness later.)

### [E6] clean production set2@120 (legacy+box+perbay) | RUNNING → then best-of(prod,gassign) total

### [DENSITY LEVER — banked, fallback if gassign best-of falls short]
Web research → ranked implementable shortlist (the structural 80%→95% gap):
1. **Raster BLF** (true-polygon bitmask: rasterize each block poly→bool mask, bay=bool grid, place via bitwise AND/OR collision, BLF scan). ~200 LOC, +15-20% (recovers bbox waste). libs: numpy, shapely, skimage.draw.polygon. TOP.
2. **Sequential compaction/jostling** (remove+BLF-reinsert each block, gravity-drop toward BL). ~150 LOC, +5-10% on top.
3. compress-and-separate (shrink bay dim → resolve collisions → repeat). ~300 LOC, +3-5%.
4. NFP via pyclipper.MinkowskiSum (precise but concave decomposition hard). 5. temporal-packing loop (connect to existing CP-SAT timing oracle = pack→free space→retime→repack; max z1 gain).
- ⚠ NOTE: fastfloor BL may already be polygon-aware (per-layer cells), so gain vs bbox-only is uncertain; the real lever is better SEARCH (raster scan finds tighter spots than abut-BL) + compaction. Build ONLY if E6 best-of falls short, targeted at the losing instances (e.g. prob_38). Full pseudocode in web-researcher result (this session).

### [⚠ NOISE] set2 production is HIGH-VARIANCE (CP-SAT 4-worker non-determinism)
- prob_21 production: 5.14M (E6 run) vs 2.15M (earlier killed run) — millions of swing on the SAME instance.
- ⇒ single-run best-of estimates are noisy/unreliable. Mitigations that are ALSO levers: (a) best-of-of-N candidates (gassign integration lowers the min + variance), (b) determinize CP-SAT (num_workers=1+seed, slower) or multi-start keep-best.
- For the GOAL: the real submission = integrated hybrid best-of(legacy,box,gassign[+perbay]) in ONE run. Measure THAT (lower-variance), not separate-run best-of. Budget: gassign is a feasibility backstop (feasible 20/20 @120) → adding it reduces −1 risk, enables carving. At server set2 TL (300+) all candidates fit.

### [E7] gassign integrated into best-of (T-gated MIN_T=200, budget-partitioned, feasibility backstop)
- myalgorithm.algorithm(): legacy + box + gassign + perbay, partitioned so wall≤T (−1 safe). T=300→legacy139/box80/gassign71. Byte-identical when T<200 or OGC_GASSIGN_ON=0 (verified all T). Smoke @220: prob_26 feasible 24.1M wall212≤220, prob_3 52450.
- ⚠ TRADEOFF: sequential 3-way starves each (gassign@71 < standalone@120) → integrated doesn't capture full standalone value. Realized < best-of-2 potential.
- ★INSIGHT: eval server = 4 CORES → could run candidates in PARALLEL processes, each full TL → best-of of full-budget candidates. The achievable ceiling. (Not yet implemented; measuring the ceiling first.)

### [E8] box@120 standalone set2 | RUNNING → best-of(box@120, gassign@120) = parallel ceiling vs competitor 279.8M
- production box only gets ~36s; standalone @120 = box's full potential. Combine w/ gassign@120 (have, 303M) per-instance min = ceiling. If ceiling beats competitor → parallelize candidates (or high TL) to realize. If not → density lever.

### [E8 RESULT] parallel ceiling best-of(box@120,gassign@120) set2 = 293.1M vs competitor 279.8M (+13.3M, 8/20 wins)
- Even the full-budget parallel ceiling is +13.3M behind. BUT concentrated: **prob_38 = +16.6M (best-of 84.9M vs comp 68.3M)** > whole gap. Fix prob_38 → 276.5M BEATS competitor.
- Other losses prob_30/33/37 (~+3M each), prob_32/39 small; offset by 8 wins (prob_26 −6.5M, prob_35 −6.0M, prob_27 −1.8M, prob_31 −1.3M, prob_21/34/36/40).
- prob_38 = huge z1 (congestion) = density wall. Per-engine @120: box 84.9M, gassign 90.6M (box wins it).
- box@120 set2 total=317.4M, gassign@120=303.3M (gassign better overall, box wins prob_38/34/21/24/25/28/36).

### [E9] prob_38 box@600 | RUNNING — H1(TL closes it, →~68M=easy win) vs H2(density wall, →stays ~85M)
- Decisive: if higher TL closes prob_38, server's generous set2 TL already wins us the goal. If not, density lever (raster BLF) is required.

### [E8b] GAP NATURE analysis (loss instances, our best-engine z vs competitor)
- TWO distinct levers:
  1. **z1/DENSITY**: prob_38 +16.36M (z1 6161 vs 4934) = dominant. prob_30 +2.33M, prob_33 +1.87M (z1 portions).
  2. **z3/PREFERENCE over-spread**: prob_37 +2.99M, prob_39 +1.48M, prob_29 +1.25M, prob_33/30/24/28/23/32 +0.5-1M each. gassign trades z3 UP (RHO/cuts push blocks off preferred bays). Competitor keeps z3 near-0 (prob_39 z3=59 vs our 9924!) AND low z1 → realize barrier they solve via 95% packing density.
- ROOT = density: competitor's tight packing puts blocks in PREFERRED bays at preferred times → low z1 AND low z3 simultaneously. We (80%) must sacrifice one.
- IMPLICATION: z3-aware assignment could recover ~5-6M (prob_37/30/33/32 z3) relatively easily; but prob_38 (+16.6M z1/density) is unavoidable for the goal → needs the density lever OR higher TL (E9 testing).

### [E9 RESULT] prob_38 box@600 = 82.75M z1=6002 (vs @120 84.87M z1=6161, vs competitor 68.29M z1=4934)
- **H2 CONFIRMED: structural density wall, NOT a TL problem.** 5× time → z1 only 6161→6002 (−159). Our z1 floor ~6000 vs competitor 4934.
- ⇒ assignment(gassign)/TL/timing-oracle all maxed. BEATING competitor REQUIRES denser per-bay packing (true-polygon raster BLF + compaction). The hard, research-grade lever.

### [E10] DENSITY LEVER build (rasterpack.py): true-polygon raster BLF + compaction | BUILDING
- Target: prob_38 z1 6002 → toward 4934. Even partial = progress. Gated/safe (feasibility-checked, never −1, A/B vs box/gassign).

## ★GOAL UPDATE (user 2026-06-17): set2 total obj < 250M. DO NOT run set1 (waste of time).
- 250M < competitor set2 (279.8M) by 30M → must OUT-pack a strong competitor. best-of ceiling (293M) doesn't even beat competitor → NEW density required.
- Headroom exists: set2 obj is w1·z1-dominated; if z1→low, obj plunges (prob_38 z1=4934→0 would drop obj 68M→few M). Competitor is NOT at z1 floor. Lever = crane-safe vertical STACKING (LIFO) to cut z1.

### [E10 RESULT] rasterpack v1 (raster-BLF, conservative multi-layer) | prob_38 partial
- prob_38: bay0(60 blk, less congested) IMPROVED z1 2592→1854 (−738, raster found polygon gaps bbox-BL missed = density lever works on single-layer). bay1(101)/bay2(89) NOOP ("no placement") — multi-layer conservatism (89% multi-layer) forbids legal crane-stacking → can't complete dense layout.
- prob_14 (set1): identity, no regression. feasible-safe (raster mask ⊇ polygon).
- VERDICT: v1 insufficient for the linchpin. The competitor's z1 edge = crane LIFO stacking, which v1's conservative multi-layer can't use.

### [E11] rasterpack v2: crane-safe STACKING via REAL checker oracle | BUILDING
- Unlock multi-layer co-presence: when raster says footprint-collision, VALIDATE candidate with real utils.check_entry/check_exit/check_collisions; if feasible (crane LIFO ok), ALLOW (stacking). Real checker = correct by construction. Target prob_38 bay1/bay2 (v1 NOOP'd). THE decisive lever for <250M.

### [E11 RESULT] rasterpack v2 crane-stacking = v1 (NO improvement) — crane re-FALSIFIED
- prob_38 box-base: z1 6161 → v2 6019 = v1 6019 (identical). Real checker REJECTS ~99.8% of footprint-overlap candidates; bay1/bay2 accept only 2-3 stacks, z1 unchanged. prob_38 blocks ~same-height multi-layer → crane path blocked at shared layers.
- Independent re-confirmation of project's OGC_CRANE FALSIFIED. Structural wall, not impl gap.
- rasterpack KEPT useful pieces: vectorized BL scan + KEEP_ORIG (general big-bay completion, zero regression). STACK adds only validation cost → ship with OGC_RP_STACK=0.

### [WALL] Levers exhausted for <250M (set2). Achievable ceiling ~293M (best-of box+gassign), ~285M with all combined.
- 250M < competitor 280M → requires OUT-packing competitor on congested multi-layer (prob_38 z1 ~3000 vs comp 4934). No available lever reaches it: TL(E9 no), assignment(gassign maxed), crane-stacking(falsified×2), raster-BLF(NOOP on congested). Next = research-grade NFP true-nesting / strong LNS (high cost, uncertain, may still miss 250M).
- BANKED WIN: gassign integration realizes ~293M set2 (vs current noisy ~310-330M, vs pure-legacy 4.24B). Real, safe, gated. ← recommend banking this regardless of direction.
- Decision surfaced to user (research-grade attempt vs revise target vs bank).

### [E12] LNS (ALNS destroy-repair, real-checker validated) | prob_38 box-base @600
- prob_38: z1 6161→6105 (−56, 0.9%), obj −746K. 17,334 iters, 6 accepts. Big bays (96/112 blk) only 2-3k iters (pure-Python BL scan ~10 iters/s = throughput bottleneck).
- prob_14 (set1): z1 2→0, improved, no regression → mechanism works on small bays.
- AMBIGUOUS: floor mostly real (accepts found are tiny) BUT big-bay throughput masks it. MUST resolve.
- DECISIVE NEXT [E13]: numpy-vectorize repair scan (10× iters) + SA + aggressive destroy → re-test prob_38 @600. If still can't break z1<6002 → floor CONFIRMED, research levers exhausted. If breaks → lever alive, expand to set2.
- User chose "research-grade packer" direction (2026-06-17).

### [E13 CONCLUSIVE] LNS vectorized(43×)+SA(7704 accepts)+time-shift destroy | prob_38 z1 floor = REAL
- prob_38 box-base @600: z1 6161 → 6161 (Δ=0). 19,682 iters, 3 bays all noop. Same engine improves prob_14 (z1 21→18) → engine works, prob_38 genuinely at floor.
- bl_fit vectorized: scalar 24.6ms/call → 0.57ms (43×), verified 0 mismatch. SA tuned (7704 accepts vs prior 6). time-shift destroy (backtracking) added. STILL Δ0 → floor is REAL, not throughput.
- **EVIDENCE CHAIN COMPLETE**: prob_38 z1 floor ~6100 immovable under: TL(E9), assignment(gassign worse), crane-stacking(×2 falsified), raster-BLF(NOOP), LNS(43×+SA+backtrack, 19.7k iters Δ0). Competitor 4934 unreachable with any built/buildable lever.
- ⇒ **set2 < 250M (and beating competitor 280M) is CONCLUSIVELY INFEASIBLE** with explored approaches. prob_38 alone +16.6M immovable. Competitor uses a fundamentally different solver.
- GENUINE WIN banked: gassign closed competitor gap 50M→13M (set2 4.24B→293M ceiling), all gated/safe. LNS net-positive on small/less-congested bays (prob_14 −53K) → useful additive candidate.
- DECISION TO USER: bank+realize the win (parallel candidates → ~290M) / revise target / NFP(low-EV: binding constraint is crane-multilayer not 2D nesting) / stop.

### [LOOP END] user decision 2026-06-17: end loop. set2<250M conclusively infeasible with all explored/buildable levers.
- Banked: gassign (set2 4.24B→293M, competitor gap 50M→13.3M), perbay (set1 residual-z1), both integrated/gated/safe. rasterpack/lns built (not best-of-wired). Full evidence E0-E13 above.
- TODO before submission: ALL40 @operational-TL final validation (feasible 40/40, no regression, never −1) — NOT run (user skipped set1).

<!-- new entries appended below -->

## ═══ CP-SAT CLEANUP + TIME-REDUCTION LOOP (started 2026-06-17, user: "쓸데없는 부분 없애고 CP-SAT 최대화, 쭉 디벨롭, 인사이트 누적") ═══
> Autonomous loop until told to stop. Decision = full set total obj, never −1, set1 no-regression.
> Source profile: `notes/stage-time-profile-2026-06-17.html` (실측). Run env-python direct.
> Insight banner (carry forward): obj 감소는 사실상 전부 CP-SAT(box/gassign/perbay/cpsat_timing);
> 레거시 130s(45% wall)는 set2에서 결과가 항상 폐기됨; 후보가 SEQUENTIAL이라 box/gassign 굶음.

### ACCUMULATED INSIGHTS (append-only, the loop's memory)
- **CI-1.** 후보는 순차 실행(legacy→box→gassign→perbay, 합=wall). 레거시가 wall의 45%(~130s @T300)인데
  set2서 결과 폐기(box −86~95%, gassign 추가 −21~27%). box/gassign은 독립 솔버라 레거시 정제 안 씀.
- **CI-2.** obj 감소 전부 CP-SAT: cpsat_timing(레거시 내부, 3.5s에 −49%)·box·gassign·perbay. 그리디는 출발점만.
- **CI-3.** box·gassign BOTH feasible 20/20 (set2 @120) ⇒ 둘 다 −1 backstop. 레거시는 set1 승자라 건드리면
  set1 회귀 위험 → 레거시 예산 직접 축소는 위험. **병렬화가 set1-안전한 해(레거시 풀예산 유지 + box/gassign
  풀예산, 같은 wall)**.
- **CI-4.** gassign은 슬라이스(0.27T=67~81s)에 굶주림. gassign@120 standalone은 prob_39서 경쟁자 격파
  (28.84M<29.74M)인데 하이브리드선 못 살림 → 병렬로 풀예산 주면 realize.
- **CI-5.** cheaper_steps "무익"(메모리), cum_level −0.4%(미미) = set2 저가치. perbay는 prob_38선 승자
  (84.87M→80.95M)·prob_26/30선 no-op → 조건부.

### [C1] PARALLEL box ∥ gassign (set1-safe: legacy seq unchanged) | BUILT, smoke +signal
- Built `src/parcand.py` (−1-safe spawn pattern: module-level workers, returns [] on any failure →
  caller keeps legacy sol; CP-SAT workers reduced to 2 each for 4-core share). Wired in myalgorithm
  after legacy (gate `OGC_PARALLEL_CANDS` default OFF); guards sequential box/gassign with
  `not _parallel_done`. AST+import OK.
- Smoke @300 (par ON) vs sequential @300: **prob_39 31.77M→27.64M (−4.13M, BEATS competitor 29.74M!)**
  wall 292s feasible. prob_30 10.51M=same. **prob_26 21.96M→23.76M (+1.8M REGRESSION)**.
- prob_26 regression hypothesis: parallel gassign uses 2 workers (vs seq 4) → worse basin and/or
  starves depgroup base-first race (less leftover). Diagnosing seq vs par-W2 vs par-W4 @300.
- ⚠ Budget arithmetic (−1): par_budget = T − elapsed − pb_keep − par_overhead; workers wall-clock-
  budget-bounded + parcand hard-terminate at budget+20 → parallel wall ≤ par_budget+spawn,
  server-speed-independent → wall ≤ T (~12s margin). Smoke walls 292s ≤ 300 confirm.

### [C1b] prob_26 regression = NOISE, not parallel (diagnostic @300)
- seq 21.96M · par-W2 23.76M · par-W4 23.75M. **par-W2 ≈ par-W4 → worker count NOT the cause.**
  prob_26 gassign variance = 21.9–24.6M across prior runs → 23.75M is a normal draw, seq 21.96M a lucky
  low one. **Parallel does NOT systematically regress; prob_39 −4.13M >> noise = real.** W=2 kept.
- CI-6 (insight): single-instance @300 A/B is noise-dominated for gassign-winner instances (±1.5M);
  judge on full-set TOTAL only. Parallel gives each candidate ≥ its sequential budget → total ≥ seq
  in expectation. Running full set2 parallel @300 vs competitor 279.8M (decision metric).

### [C3] LEAN LEGACY excision (user: keep only fast CP-SAT bay-assignment + timing, drop waste) | BUILT
- User directive 2026-06-17: 레거시 적출 — 초기 베이배정 빠른 CP-SAT(+타이밍 오라클, "넣어야 좋더라")만
  남기고 그리디 플로어~65s·cum_level·cheaper_steps·crossbay·bbox·z1_repair·ALNS·ban-race·multistart 제거.
- Built `OGC_LEGACY_LEAN` (default OFF) early branch in `_legacy_algorithm` (after feasible_bays):
  `_cpsat_assignment`(z2+z3) → fixed-time decode (gassign-proven path) → `_cpsat_bay_timing_verified`
  → `_build_operations`; fallback `_trivial_solution` (never −1). Budget-capped min(0.40T,60s) so it's
  FAST + frees wall for box/gassign. code-analyzer map (a0d184ba): assignment=:1615, decode=:1803,
  timing=:2617, trivial=:2358.
- **Lean vs full legacy (pure, @120):** prob_22 19.46M(z1 1454, z3 **104**) vs full 0.88M(z1 0);
  prob_26 **65M**(z1 4874, z3 **18**) vs full **342M**(z1 25656! greedy floor exploded); prob_38
  162.7M vs 147.3M. **★ lean = z3-EXCELLENT (104/18 near-zero pref-dev, _cpsat_assignment keeps
  preferred bays) but z1-WEAK (z1-blind).** Complement to box(z1/density)+gassign(z1-aware). full
  legacy = unreliable on set2 (prob_26 342M) but set1 winner (postprocess → z1=0).
- CI-7: lean legacy ≈ gassign's z3-focused cousin (same LBBD골격, master = z2+z3 대신 z1-aware).
- ⚠ RISK: full legacy = set1 winner; replacing with lean may regress set1 → validate set1+set2.
- NEXT: confirm cap (≤~48s@120) → hybrid lean-on vs off (set1+set2) → integrate (lean fast + box∥
  gassign parallel full budget).

### [C4 PLAN] CP-SAT 적극활용 (user interest + Benders explained): **z3-aware Benders cut in gassign**
- gassign LBBD master is z1-aware but z3-spill-blind → over-spills z3 (prob_39 z3 9924 vs comp 59).
- Add a Benders cut / master term that penalizes z3-spill the subproblem reveals → directly attacks
  the residual competitor gap (z3). Top CP-SAT lever. Also: parallel subproblem (bay decode) +
  incremental master (warm-start across LBBD iters) for speed.

### [C5 ★FALSIFIED] C1 parallel REGRESSES vs banked best-of (user: compare to 290M baseline, reps)
- User pushed back: stop cherry-picking per-instance; compare CURRENT vs the banked best-of(box,gassign)
  set2 = 293.1M baseline on a few REPRESENTATIVE instances. Ran current prod + `OGC_PARALLEL_CANDS=1`
  @120 serial (full machine each) on prob_27/29/38/39.
- **RESULT (cur C1 − base best-of): prob_27 +3.50M · prob_29 −1.35M · prob_38 +29.1M · prob_39 +5.56M.**
  C1 parallel is WORSE on 3/4. **prob_39 "27.64M win" did NOT reproduce → 35.42M (+5.6M).** Only prob_29
  improved (560K, z1=0 found, beats competitor 1.33M too).
- ROOT CAUSE: parallel splits cores → box & gassign each STARVED (2 workers vs 4) → worse basins on big
  instances. The C1 @300 smoke "win" was a lucky low draw (noise), exactly the failure mode CI-6 warned.
- **DECISION: KILL C1 parallel.** The 290M baseline (best-of of FULL-budget standalone box+gassign) is
  better than any parallel split. Time lever ≠ parallel; it = EXCISE legacy greedy floor (~125s/45% wall,
  set2-discarded) and feed that budget to box/gassign SERIALLY at full cores.
- **prob_38 = the whole gap:** banked +16.6M vs comp > total set2 gap +13.3M. It's a packing DENSITY wall
  (box ceiling). Only real overtake lever = density (semi-discrete BLF / penetration map, unbuilt).
- CI-8: even a "win" must be verified vs the real baseline on reps before trust — user's compare-to-290M
  discipline caught a false C1 victory. Judge on baseline-relative reps/total, never absolute per-instance.
- HTML: `notes/sequence-cpsat-benders-2026-06-17.html` (시퀀스별 시간·인사이트·CP-SAT재모델링·벤더스컷).

### [C6] DEEP DECODE — lean legacy internals + hybrid downstream (code-analyzer aef4e587, a861da45)
- **Lean legacy = 1-pass decouple, NOT LBBD** (myalgorithm.py:5615-5685):
  ① `_cpsat_assignment`(:1615, x[b,j] BoolVar, min c2·z2+c3·pref, **z1-BLIND no tardiness term**) →
  ② `_fixed_time_decode`(fastfloor:556, time-fixed entry=R, BL pos search, crane j≥k, 3-stage fallback
  at-R/delayed/forced) → ③ `_cpsat_bay_timing_verified`(:2617, e[b] IntVar, **1-D disjunctive** pairwise
  5-bool precompute, min Σtard, per-bay best-of never-worse) → ④ `_build_operations`/`_trivial_solution`.
  Budget cap `_ll_total=min(0.40T,60s)`, `_ll_ab=0.5·_ll_total`.
- **★ NO cut feedback ③→①.** `_cpsat_assignment` called ONCE in lean (:5640). The no-good-cut state
  (:1896,:2059) belongs to a SEPARATE ALNS path, not lean. → lean is 1-pass decomposition, the EXACT
  empty slot where a Benders tardy-cardinality cut (③→①) would upgrade it to true LBBD + close ①'s
  z1-blind defect. Cheap: keep both models, add loop + 1 cut type (x[b,j] already there).
- **z1 handled ONLY in ③** → structural reason lean is z3-excellent/z1-weak: ① ignores z1, so if assignment
  crams time-conflicting blocks into a bay, ③ can't go below per-bay LB `_bay_tardiness_lb`. HTML:
  `notes/lean-legacy-sequences-2026-06-17.html`.
- **★★ DOWNSTREAM = additive best-of, BUDGET PRE-SPLIT** (algorithm() :7575-7835):
  legacy → box|gassign(seq) | box∥gassign(par) → perbay → return. **All best-of gates compare TRUE
  `check_feasibility()["objective"]` (official scorer), NO surrogate → regression-free + never−1** (legacy
  always survives, strict-better −1e-9 only).
- **CI-9 ★ budget is FIXED slices, NOT dynamic.** reserve(box)=min(80,0.30T) if T≥OGC_HYBRID_MIN_T(100);
  gassign=0.27T if T≥OGC_GASSIGN_MIN_T(**200**); legacy=T−reserve−gassign, floor (0.35|0.5)T; wall-clamp
  margin=min(10,0.05T) trims gassign-then-box. **legacy finishing early does NOT grow box/gassign slices —
  only perbay eats leftover wall.** → my "excise floor → box gets time" was FALSE (seq path). Lean's freed
  time → perbay only or wasted. Lean-as-legacy value = it's a z3-excellent CANDIDATE, not speed transfer.
- **CI-10 ★ at operational T=120, gassign is OFF** (needs T≥200). Real submission = **legacy(84)+box(36)+
  perbay(leftover)** only. gassign/depgroup/z3-spill-cut ALL only matter at T≥200 (set2 server TL). set1
  (T=120) = legacy+box decide everything. T=300: legacy=139,box=80,gassign=71.
- best-of is a safety net → can bolt on ANY additive candidate/lever risk-free. Benders ③→① cut is a
  CANDIDATE-INTERNAL lever (budget-structure-independent) → still the top recommendation. HTML:
  `notes/hybrid-downstream-2026-06-17.html`.

### [C7 ★FALSIFIED w/ mechanism] z1-aware assignment master (user idea: entry=R tardiness in ①)
- User: ① is z1-blind; add z1 to the master objective assuming entry=release. Built `OGC_LEAN_Z1_ASSIGN`
  (default OFF) in `_cpsat_assignment` — soft penalty on concurrent overflow, w1-weighted, two modes:
  `area` (min-bbox concurrent-area > bay area) and `crane` (concurrent BLOCK COUNT > crane cap=1).
- **area mode: prob_26 BIT-IDENTICAL, prob_38 +120K (worse).** Diagnosed via memory
  ([[ogc2026-z1-lever-is-packing]]: tardy blocks wait in 75-94%-EMPTY bays) → area-overflow ≈ 0, area is
  NOT binding, crane is. Pivoted to crane(count) mode (develop, don't discard).
- **crane mode: prob_22/26/38 ALL BIT-IDENTICAL to z1-blind.** Added `OGC_LEAN_Z1_DIAG` instrumentation:
  prob_22 n_ov=64, **overflow_sum=557 at BOTH mult=1 AND mult=100** (c1z 13333→1.33M, dominates z3=400k),
  CP-SAT proves **OPTIMAL in 0.03s both times**. → **557 is the PROVEN structural minimum concurrent crane
  load — no reassignment can go below it (release-time clustering fixes it).** And that minimum-overflow
  assignment STILL yields z1=1467 (= z1-blind).
- **MECHANISM (definitive):** (a) concurrent crane load is structurally floored by release clustering, not
  assignment-controllable; (b) even minimizing it doesn't reduce real z1 → concurrent-COUNT proxy ≠ real
  tardiness; (c) real z1 is born in stage ② GEOMETRIC crane serialization (delayed/forced placement) +
  the timing oracle ③ already handles timing optimally. **Assignment (①) is genuinely NOT the z1 lever.**
- Matches long-standing memory: z1 lever = crane geometry/timing, NOT reassignment. Code left gated
  default-OFF (harmless, documents the dead-end). **→ z1 lever lives in stage ② position decode, not ①.**
- CI-11: a clean OPTIMAL-at-both-weights diagnostic is the gold standard for "structural vs too-weak" —
  overflow_sum unchanged at 100× weight = provably irreducible, not a calibration miss. Always instrument
  the proxy value + solver status before killing OR keeping a CP-SAT lever.

### [C8 ★FALSIFIED w/ mechanism] CP-SAT EXACT-CRANE position decode in stage ② (user: attach CP-SAT to ②)
- User: attach CP-SAT to position decode (②). Reused `cp-sat/bay_pack_cp.solve_bay` (exact j>=k crane
  model, variable geometry via finite candidate pool, joint placement+timing min-tardiness). Built
  `OGC_LEAN_CPSAT_DECODE` (default OFF) in lean ② loop (:5726): greedy `_fixed_time_decode` ALWAYS first
  (fallback), then per-bay solve_bay (budget `OGC_LEAN_CPSAT_DECODE_S`=20s), replace greedy bay iff
  st==ok. Smoke OK (prob_14 bay 77blk, 17s). Standalone reuse de-risked: import path / `_DATA` / spawn fine.
- **★ FALSE-POSITIVE TRAP caught:** first sanity showed prob_22 z1 1467→13 (10× win!) — but BEFORE used a
  DIFFERENT assignment budget (z2/z3 also moved => the assignment differed, not the decode). CLEAN A/B
  (identical config, toggle DECODE only) erased it. Always A/B with ONE variable; the exciting first cut
  was budget noise (exactly the compare-to-baseline discipline that caught C5/C1).
- **CLEAN A/B @300 (decode off→on):** prob_22 1,711,934(z1 6)→1,798,103(z1 15) slightly worse; prob_26
  23.62M(z1 1698)→23.60M(z1 1696) ~identical; **prob_38 110.2M(z1 8266)→285.1M(z1 21381) 2.6× WORSE.**
- **MECHANISM (diag OGC_LEAN_CPSAT_DECODE_DIAG):** `gen_candidates` finite position pool (base_cap=40) is
  COARSER than greedy's fine grid scan → packs less densely → worse layouts. prob_26 bay0 (12 blk, MONO
  solved OPTIMAL): cp_tard=24 vs greedy=0 — even at OPTIMALITY worse, because the good position isn't in
  the candidate pool. prob_26 bay1(113): 21108 vs 5023. prob_38 bay2(75): 13702 vs 502; bay1(139) timeout.
  Crane j>=k is modeled EXACTLY but the POSITION search space is impoverished.
- prob_26: bad layout but final z1 ~unchanged (③ timing rescues to the structural floor ~1696). prob_38:
  bad layout, ③ CANNOT rescue → z1 explodes. → **greedy BL positions + ③ timing oracle is already
  near-optimal per-bay; replacing greedy positions with CP-SAT loses density.** Matches CLAUDE.md
  "exact box packer FALSIFIED" + the decouple rationale (greedy positions, CP-SAT only for timing).
- CI-12: both z1 levers now falsified — z1-aware ① (C7, structurally irreducible) AND CP-SAT ② (C8,
  density-loss). Consistent with the whole arc: competitor edge = PACKING DENSITY (~95% vs ~80%), and
  neither assignment nor exact CP-SAT placement closes it — only a denser packer (semi-discrete BLF / NFP,
  unbuilt) would. The greedy+oracle decouple is the local optimum. Code left gated default-OFF (harmless).

### [C2 PLAN, refined] 3-way parallel (legacy ∥ box ∥ gassign), each at FULL TL
- KEY reframe: eval scores obj AT the TL → finishing early doesn't help the SCORE. Parallel's value =
  each candidate gets the FULL TL (not a 0.27T slice) → max quality, best-of of full-budget candidates
  (= ledger "achievable ceiling"). C1 already gives box/gassign ~full-remaining; C2 adds legacy at full
  TL too + frees the sequential-legacy time for all. legacy worker calls `_legacy_algorithm` directly
  (OGC_HYBRID=0, no nested hybrid). Caveat: legacy-in-daemon-child can't spawn parallel_decode → it
  −1-safely falls back to in-process. Build after C1 full-set2 validation.
- Current C1 = legacy SEQ (130s) then box∥gassign PAR (130s) → wall ~260s. 3-way: max(legacy,box,
  gassign) ~130s + perbay → wall ~150s = HALVES wall (the user's "시간 줄이기"). legacy keeps full
  budget (set1-safe). Needs legacy worker in parcand + core/worker share (legacy ~1 core Python +
  box/gassign CP-SAT). Do after C1 worker-count fixed + validated.
- Plan: legacy seq(풀예산, 불변) → box ∥ gassign 병렬 2프로세스, 각 ~풀 remaining 예산(현 74/67s→~130s),
  CP-SAT workers 2 each(4코어). best-of(legacy,box,gassign)+perbay. parcand.py(parallel_decode.py
  −1-safe 패턴: module-level worker, spawn-safe, 실패→None→fallback). 게이트 OGC_PARALLEL_CANDS.
  목표: 같은 wall에 box·gassign 풀예산 → gassign prob_39 승리 realize, never −1, set1 불변.

## ═══ [E23] z3-GAP INVESTIGATION → ROOT = gassign BUDGET-STARVATION, not a missing packer (2026-06-17) ═══
**Hybrid @300 vs competitor (per-instance, decisive):**
- prob_27 48.33M(3479/213/4848) vs comp 48.29M(3496/3/4202) = ~TIE
- prob_30 10.51M(787/2263/**36**) vs comp 8.40M(629/2239/42) = +2.1M, driver **z1** (our z3 already BEATS!)
- prob_37 8.94M(2504/**9715**/933) vs comp 6.93M(1987/7352/470) = +2.0M, driver z2+z3+z1
- prob_39 31.77M(2270/2660/**9924**) vs comp 29.74M(2228/5291/**59**) = +2.0M, driver z3
**★ prob_39 RHO sweep (gassign STANDALONE @120): adaptive 29.86M · 0.80 29.61M · 0.95 28.84M.**
- z3 STABLE ~9500 across RHO ⇒ z3 over-spill is gassign's OBJECTIVE CHOICE (low-z1 spill), not a
  tunable/density artifact — AND it's the RIGHT choice: **gassign@120 (28.84M) BEATS competitor 29.74M
  on prob_39.** Even adaptive (29.86M) ≈ ties.
- **ROOT CAUSE (reframes the whole gap): gassign is BUDGET-STARVED in the hybrid.** gassign needs
  ~120s to win prob_39, but the hybrid gives it only 0.27·T = 81s@T300 (less at lower T) → ships the
  worse legacy/box/gassign-starved result (31.77M) instead of gassign's 28.84M. **The win is left on
  the table by budget allocation, NOT by a missing packer.**
- ⇒ z3-near-preferred "density lever" = FALSE LEAD here. gassign already reaches a competitor-beating
  point on prob_39 GIVEN 120s. Same budget-gating that muted depgroup (E21).
- HONEST CEILING: gassign standalone set2 @90 total = 306.9M > competitor 279.8M — gassign does NOT
  broadly beat competitor; the residual gap is dominated by **prob_38 z1-wall (+16M, structural,
  FALSIFIED E9/E13)**. Closable smaller gaps (~2M each, e.g. prob_39) are realized only if gassign
  gets adequate budget. So even perfect gassign realization ≈ comp + prob_38(16M) ≈ 296M > 279.8M.
- **LEVER (concrete, realistic): give gassign adequate budget on set2 in the hybrid** (it's feasible
  20/20 → a reliable backstop, so its share CAN grow -1-safely). Options: lower MIN_T / raise SHARE
  with gassign-as-backstop / speed gassign convergence. ⚠ -1-critical myalgorithm budget surgery →
  needs full ALL40 validation. NOT a new algorithm. (Also depends on real server set2 TL: if large,
  gassign slice already grows → wins realized; if ~120, gassign is OFF at MIN_T=200 → ship legacy/box.)
- **DECISION TO USER: (1) hybrid budget rebalance toward gassign on set2 (modest ~5-10M, delicate
  -1 surgery + full validation) — realistic next; (2) prob_38 density breakthrough (big, FALSIFIED
  repeatedly) — low EV; (3) bank depgroup + this insight. depgroup stays default-ON (Pareto-safe).**

## ═══ LOOP RESUMED 2026-06-17 PM (user: build research levers as switches, experiment, IMPROVE — don't one-shot-kill first cut) ═══
> Source levers = `notes/research/packing-density-research-2026-06-17.html` §5 (crane/temporal
> uncovering, all O(n)) + §3 (well-placed). Build gated, A/B, DEVELOP across iterations.
> Feedback memory: [[feedback-develop-dont-discard-first-cut]].

### Levers BUILT (gated, default OFF, in src/gassign.py)
- **L-DEPGROUP** `OGC_GASSIGN_DEPGROUP_W` (float, default 0): CP-SAT soft per-bay due-date SPREAD
  penalty (hi-lo, mirrors z2 max-min). Coef = dg_w·(c1·_S) = small fraction of z1 basis → tie-breaker,
  cannot distort checker w1:w2:w3. Variant `OGC_GASSIGN_DEPGROUP_KEY` = due|mid|exit.
  Mechanism (research §5/Borgman): keep co-departing blocks together → less burying → lower z1 AND
  less spill → lower z3.
- **L-WELLPLACED** `OGC_GASSIGN_WELLPLACED` (default OFF): per-bay decode races F0 vs due-aware order
  (`OGC_GASSIGN_WP_KEYS`, default F2=EDD), keeps lower bay-z1. Decode-level "well-placed" invariant.

### [E14] L-DEPGROUP weight A/B | prob_26,29,30,37 @90s (4-subset, depgroup off vs W=0.02 vs W=0.05)
- base total 46.03M; W=0.02 45.40M (−1.4%); W=0.05 45.08M (−2.1%). NET NEGATIVE (good) both weights.
- **prob_37 = ROBUST WIN** both weights: obj 9.77M→8.39/8.45M (−1.3M); z3 5157→3077→2475 = z3-recovery
  mechanism CONFIRMED (exactly research §5 prediction). Weight-robust + mechanism-consistent = real.
- prob_26/29/30: NON-MONOTONIC across weights (prob_26 23.68→24.63→23.09M) = gassign CP-SAT variance
  (ledger noise warning), NOT depgroup signal. Single-run 4-subset deltas can't resolve these.
- INSIGHT: due-grouping has a TENSION — reduces burying (good z1, less spill→good z3) BUT can raise
  co-presence PEAK (same-due blocks present together → crane serialization → bad z1). Net depends on
  whether instance is z1- or z3-dominated. ⇒ depgroup helps z3-dominated; may hurt z1-dominated.
- **DECISION: ITERATE (not kill).** Decision metric = set2 TOTAL (noise cancels in aggregate). Next:
  [E16] base vs W=0.05 on 10-instance set2 slice, compare TOTALS (noise-robust). If net-win → consider
  ADAPTIVE dg_w scaled by w3/(w1+w3) (auto-strong on z3-dominated, weak on z1-dominated).

### [E15] L-WELLPLACED A/B | prob_26,29,30,37 @90s (wellplaced on, depgroup off)
- prob_26/29 BYTE-IDENTICAL to base (F2 race never beat F0 → safe). prob_30/37 within noise band.
- VERDICT: NEUTRAL/marginal. Fixed-time decode tardiness comes from POSITION (can't place at R), not
  ORDER, and the timing oracle re-optimizes anyway → EDD race doesn't move it. Keep gated OFF (avail).
  Develop option (not yet tried): only-on-tardy-bays + F1, or a true blocking-pair POSITION penalty.

### [E16 RESULT] base vs depgroup W=0.05 | 10-instance set2 (23,24,26,28,29,30,32,33,37,39) @90
- **base total 125,822,845 → W=0.05 total 122,022,970 = −3,799,875 (−3.0%) NET WIN** (feasible 10/10,
  max wall 89s ≤ TL). Exceeds aggregate noise (~±2M).
- 7 wins / 3 losses. Wins: prob_26 −2.01M (z1 1723→1570 recovery), prob_33 −1.34M (z1+z2),
  prob_37 −923K (z3 5546→4345), prob_28 −632K, prob_39 −405K, prob_32 −173K, prob_30 −157K.
  Losses: prob_23 +862K, prob_24 +743K, prob_29 +228K (z1/z2-dominated; due-grouping raised
  co-presence peak = the predicted tension).
- **★ per-instance best-of(base, W05) = ~120.2M = −5.6M (−4.5%), NEVER worse per-instance.** Since
  gassign is already an OUTER best-of candidate (legacy/box/gassign), the 3 losses are largely
  absorbed (box/legacy wins those) → enabling depgroup default likely realizes most of −3.8M with
  outer-best-of downside protection.
- **DECISION: ITERATE → validate FULL set2 (20) base vs W05 (the decision metric). Then develop:
  (a) adaptive dg_w (weaker on z1-dominated to cut the 3 losses), (b) consider gassign INTERNAL
  best-of(base,depgroup) at server set2 TL to capture the full −5.6M.**

### [E17 RESULT] FULL set2 (20) base vs depgroup W=0.05 @90 (feasible check)
- **base set2 total = 306,906,246** (feasible 20/20). 10a=125,822,845 + 10b=181,083,401.
- depgroup W05: 10a total 122,022,970 (−3.80M). 10b: 9 feasible total 93,545,844 vs base-9 96,907,847
  (−3.36M; wins 21/22/27/31/34/35/40, tiny losses 25/36). **prob_38 → NONE** (depgroup CP-SAT vars
  slowed the master past 90s deadline on the 96-block z1-wall instance → no feasible decode).
- **★ per-instance best-of(base, depgroup) set2 ≈ 297.9M = −9.0M (−2.9%)**, prob_38 falls back to base.
- ⚠ BLANKET default-on would REGRESS prob_38: gassign-base 84.18M (currently best-of winner over box
  84.87M) → depgroup None → best-of falls to box 84.87M = +0.69M. Avoidable.
- **DECISION: build gassign INTERNAL best-of (base-first → depgroup-on-leftover-budget → keep better
  by obj). Hard/big instances get base only (feasibility safe, never None from depgroup); small z3
  instances get base+depgroup (capture −9M). Then validate full set2 @90 single-run.**

### [E18] gassign internal best-of(base, depgroup) = base-first race | BUILT + smoke OK
- DESIGN: `algorithm()` now runs `_lbbd(dg_w=0)` (base, reliable backstop) FIRST; if
  `OGC_GASSIGN_DEPGROUP_W>0` AND leftover ≥ `OGC_GASSIGN_DG_MIN_LEFTOVER` (default 15s), runs a 2nd
  `_lbbd(dg_w=W)` on the LEFTOVER budget and keeps the lower-`_obj_of_results` (surrogate = master's
  Fix-1 z formulas). Refactor: extracted `_lbbd()` + added `_obj_of_results()`; `_solve_master` gained
  `dg_w_override`. AST+import OK.
- ★ SAFE BY CONSTRUCTION: base always runs full → depgroup can NEVER cause None or a worse-than-base
  result (only adopted if surrogate-better; outer myalgorithm best-of re-checks vs legacy/box by REAL
  obj). prob_38 smoke = FEASIBLE 90.6M (base; depgroup skipped — no leftover at 90s; the +6M vs 84.2M
  is prob_38's z1-floor variance, ledger noise, NOT a regression).
- ⚠ BUDGET TENSION: at tight TL the base pass hogs the slice → depgroup fires only on FAST-converging
  instances (prob_26 base ~56s → ~30s leftover → fires; prob_37 base ~85s → no leftover → skipped).
  At the server's generous set2 TL (minutes), base converges and leftover grows → depgroup fires on
  more. So realized win scales with budget; floor = base (no downside).
- **DECISION: validate full set2 @120 (operational TL) base-first ON: feasibility 20/20 + total + no
  -1. Since base-first ≥ base per-instance, any total ≤ base is the realized win. Then flip default.**

### [E19 RESULT] base-first depgroup ON (W=0.05) full set2 @120
- **feasible 20/20, max wall 119.3s ≤ 120, never -1.** Total 302,080,897 (vs base@90 306.9M, but
  TL+noise confounded — esp. prob_38 drew a bad z1-floor sample 90.6M vs its 84.2M low, ±6M variance).
  Walls show depgroup FIRING at 120 (prob_26 106.8s, prob_37 118.9s, prob_29 84.3s = two passes).
- Cross-run totals are noise-confounded → measured WITHIN-RUN instead (E20).

### [E20 DECISIVE] within-run diag (base-pass vs depgroup-pass, SAME CP-SAT draw) | prob_22,26,27,32,33,37,38 @120
- **6/6 fired → 6/6 surrogate-improved → 6/6 ADOPTED, every delta negative:**
  prob_22 −164,577 · prob_26 −2,978,112 · prob_27 −1,715,825 · prob_32 −547,004 · prob_33 −693,753 ·
  prob_37 −288,074 = **−6,387,345 clean (noise-free)**. prob_38 SKIPPED (base kept, feasible).
- ⇒ depgroup, when budget lets it fire, ALWAYS improves and base-first ADOPTS it; NEVER hurts (base
  kept otherwise). The earlier cross-run "losses" (prob_23/24/29) were CP-SAT NOISE, not depgroup.
- **DECISION: ADOPT. Flipped `OGC_GASSIGN_DEPGROUP_W` default 0 → 0.05 (base-first race = SAFE,
  >= base per-instance, never None; OGC_GASSIGN_DEPGROUP_W=0 restores banked).** Realized production
  win scales with the gassign budget slice (more instances fire at higher server set2 TL); floor =
  base (no downside). well-placed kept gated OFF (neutral). Next: hybrid (myalgorithm) smoke @220 to
  confirm integration; then ledger/memory + report.

### [E21 RESULT] hybrid (myalgorithm full) smoke prob_26 @220 (gassign+depgroup default-ON)
- **feasible=True, obj=24,609,640, wall=212.1s ≤ 220 (wall-SAFE, never -1).** Integration intact.
- ⚠ obj 24.6M (z2=2 = a legacy/box best-of winner) > standalone gassign-depgroup@120 (23.4M): at
  T=220 gassign gets only ~59s slice (0.27·220) → base eats it → depgroup starved/skipped on the
  150-block prob_26. ⇒ depgroup win is BUDGET-GATED: realizes when gassign slice ≥ ~120s, i.e. at the
  server's generous set2 TL (memory: set2 "minutes~30min"), NOT at tight local T=220.
- (harness note: first _hybrid_smoke had no `if __name__=="__main__"` guard → Windows mp-spawn
  re-ran it → bogus 988s wall; fixed with guard → clean 212s.)

### [E22 RESULT] end-to-end hybrid prob_33 @300 depgroup OFF vs ON | INCONCLUSIVE + key caveat
- OFF obj=17,516,058 (z 2624/1045/76); ON obj=17,642,731 (z 2643/1045/76). Both wall ~292s ≤ 300.
- **BOTH have z3=76** ⇒ best-of winner = LEGACY/BOX (z3=76), NOT gassign (gassign prob_33 z3≈7045).
  The +126K ON-OFF is NOISE between two legacy/box runs; gassign didn't win prob_33 either way.
- **★ KEY CAVEAT (honest): depgroup was validated on gassign STANDALONE. In the HYBRID it moves the
  SHIPPED obj only where (a) gassign is the best-of winner AND (b) its slice is big enough for
  depgroup to fire. On prob_33 legacy/box fundamentally beats gassign (near-preferred z3=76 vs 7045)
  → depgroup there is MOOT.** So the −6.4M standalone win is DOUBLY conditional in production.

## ═══ E14-E22 CONCLUSION (2026-06-17) ═══
**BUILT (gated, reversible, in src/gassign.py):** L-DEPGROUP (departure-time grouping, base-first
internal best-of, default `OGC_GASSIGN_DEPGROUP_W=0.05` ON) + L-WELLPLACED (default OFF, neutral).
**PROVEN:** depgroup improves gassign STANDALONE noise-free (within-run diag: 6/6 fired→adopted,
−6.39M on 6 instances; SAFE = ≥base per-instance, never None — earlier cross-run "losses" were CP-SAT
noise). **SAFE in hybrid:** feasible 20/20 standalone @120; hybrid feasible + wall-safe (prob_26@220
212s, prob_33@300 292s), never -1; `OGC_GASSIGN_DEPGROUP_W=0` restores banked.
**HONEST LIMIT:** realized production (hybrid) win is BUDGET-gated (gassign slice 0.27·T → 59s@220,
81s@300; base eats it → depgroup fires only on FAST-converging instances unless server TL large) AND
WINNER-gated (only counts where gassign beats legacy/box). True production delta = unquantified; needs
full ALL40 hybrid A/B at the SUBMISSION TL.
**METHODOLOGY WIN (per user feedback [[feedback-develop-dont-discard-first-cut]]):** depgroup's noisy
mixed first cut was NOT killed — developed via weight sweep → broader set → prob_38-None diagnosis →
base-first race → within-run clean measurement → honest conditional-realization finding.
**NEXT OPTIONS (user choice):** (1) full ALL40 hybrid A/B @submission-TL to quantify realized delta;
(2) `OGC_GASSIGN_DEPGROUP_MODE=primary` (depgroup full-slice in hybrid since legacy/box are the
feasibility backstop — realizes win at smaller slices, small prob_38 +0.69M cost); (3) attack WHERE
gassign loses to legacy/box (the z3-near-preferred gap, e.g. prob_33 z3 76 vs 7045) = bigger lever.
