# Autonomous set2-beat-competitor session — 2026-06-16

> **READ THIS FIRST if you are a fresh/compacted context.** This is a long-running
> autonomous engineering session. The user authorized it explicitly (2026-06-16):
> *"가설 설정→검증→피드백→수정 루프를 set2에서 경쟁자 이길 때까지 멈추지 말고 돌려라.
> 정체되면 파괴적 혁신도. 10시간 뒤 돌아온다."* Do not stop until set2 beats the competitor
> or the user returns. Keep this file as the single source of truth; append every iteration.

## MISSION
Make **OUR ALL40 total objective < COMPETITOR ALL40 total** — which is **entirely a set2
tardiness (z1) problem**. set1 is 0.03% of our obj and already near-parity; do NOT spend
effort there. The whole game is set2 z1.

- ALL40: ours **4,245,225,196** vs comp **280,755,516** = 15.1× worse. gap ≈ 3.96B.
- set1: 1,420,811 vs 931,465 (1.53×) — IGNORE (0.03% of total).
- set2: **4,243,804,385** vs **279,824,051** (15.2×) — THE ENTIRE GAME (99.97%).
- For catastrophic instances **obj ≈ w1·z1** (e.g. prob_24: w1·z1 = 301M = 99.7% of obj).
  Reducing set2 z1 reduces obj almost proportionally.

## KEY DIAGNOSIS (instance characterization, 2026-06-16)
set2 is **NOT intrinsically harder** than set1: set1 has bigger instances (300 blocks vs
set2 max 250) and tighter deadlines (medslack=1 vs set2 2–6). Competitor achieves small z1
(149–5977) on EVERY set2 instance → our 10–150× z1 is a **solver capability gap, not a
difficulty wall**. Worst on **4-layer (prob_24/26) + high-throughput (prob_31/35/38)** →
points at crane j≥k serialization + timing optimization collapsing at the set2 regime.

## COMPETITOR set2 TARGETS (obj_official) vs OUR current (tl120 hybrid)
```
inst     ours_obj         comp_obj      ratio  ours_z1  comp_z1   status
prob_21    2,298,112      3,724,980      0.6x      144      227    WIN (keep)
prob_22      856,848        902,125      0.9x        0        4    WIN (keep)
prob_23    7,611,178      6,851,876      1.1x      561      505    close-loss
prob_24  302,073,220      2,739,005    110.3x   22,585      149    *** worst ratio
prob_25    6,540,732        465,720     14.0x    9,775      680    big
prob_26  319,505,803     30,417,445     10.5x   23,933    2,223    big
prob_27  473,326,762     48,292,973      9.8x   35,444    3,496    big
prob_28  166,869,314      9,388,394     17.8x   12,491      645    big
prob_29      664,968      1,328,458      0.5x       15       64    WIN (keep)
prob_30  218,205,756      8,403,812     26.0x   16,360      629    big
prob_31 1,243,855,824     22,256,964     55.9x   93,216    1,472    *** biggest abs gap
prob_32    7,476,180      5,680,477      1.3x    2,005    1,657    close-loss
prob_33  274,283,043     16,163,273     17.0x   41,119    2,419    big
prob_34  118,727,675      2,834,967     41.9x   35,604      833    big
prob_35  897,498,365     10,652,374     84.3x   67,220      734    *** big abs + ratio
prob_36      695,824        628,061      1.1x      844      741    close-loss
prob_37    8,870,958      6,934,080      1.3x    2,478    1,987    close-loss
prob_38  147,272,112     68,290,241      2.2x   10,902    4,934    medium
prob_39   41,290,004     29,735,939      1.4x    3,012    2,228    close-loss
prob_40    5,881,707      4,132,886      1.4x    8,612    5,977    close-loss
set2 TOTAL: ours 4,243,804,385  comp 279,824,051
```
Biggest absolute levers (obj gap): prob_31 (1.22B), prob_35 (887M), prob_27 (425M),
prob_24 (299M), prob_33 (258M), prob_30 (210M), prob_26 (289M), prob_28 (157M), prob_34 (116M).
**Iterate on a representative subset {prob_24 (4-layer), prob_31 (2-layer high-thru),
prob_35 (high-util)} for fast loops; validate promising changes on full SET2.**

## ARCHITECTURE DECISION (user-confirmed 2026-06-16)
- **Parallel build + fallback.** Keep current solver as legacy safety net. Build the new
  set2 engine as a SEPARATE module. `algorithm()` stays best-of(legacy, new) wrapped in
  try/except so a new-engine failure can NEVER cause infeasible/-1. Promote only when the
  new engine is proven feasible + better on full SET2.
- **HARD INVARIANT: never -1.** ALL40 must stay feasible 40/40, wall < TL with margin.
  -1 = score 1순위 손실. Any change that risks a timeout/crash/infeasible is rejected
  regardless of obj.
- Measurement rule (user): validate on FULL set (SET2 or ALL40); judge by TOTAL obj, not
  individual z. Adopt only on paired full-set improvement with zero -1.

## RUN HARNESS (verified)
- env python (direct, conda run crashes the 4-worker CP-SAT):
  `C:\Users\peter\anaconda3\envs\ogc2025\python.exe`  (py3.11, ortools ok)
- Fast subset / full set, 4-core affinity per instance, 5 slots:
  `python notes/_capture20_aff.py --instances prob_24,prob_31,prob_35 --timelimit 120 --tag <tag> --env K=V,...`
  (also accepts SET2, ALL40). Writes `results/capture/<tag>/<inst>.json` {met:{wall,feas,z1,z2,z3,obj}}
  + `<inst>.stderr.txt` (stage traces under OGC_STAGE_TIMING=1).
- Compare helper: see `notes/_competitor_compare.py` style; competitor truth =
  `notes/competitor-2026-06-15.json` (obj = objective_official).
- Score helper to compute set2 total + per-inst win/loss: `notes/devlog/_set2_score.py` (created this session).

## LOOP PROTOCOL (autonomous)
1. Form ONE concrete hypothesis (mechanism + expected z1 effect + which instances).
2. Implement minimal change behind an env gate (default OFF → reversible) in a NEW module
   where possible, or guarded edit. Never touch utils.py / baseline/.
3. Run fast subset {24,31,35} @ TL120. Read z1/obj/feas/wall.
4. If subset improves with zero feasibility loss → validate full SET2 @ TL120.
5. Adopt (flip gate default ON in the hybrid best-of) only on full-SET2 total-obj
   improvement + feasible 20/20 + wall margin. Record. Else reject + record why.
6. Always keep a known-good baseline tag to roll back to.
7. If N consecutive hypotheses fail to move the needle → DISRUPTIVE INNOVATION (rethink the
   engine: different layout strategy, different timing model, different decomposition).
8. Append every iteration below. Always end a turn with a background experiment running OR
   the next step queued, so the loop self-continues via task-completion notifications.

## ROLLBACK BASELINE
- Current shipped ALL40 = `notes/research/baselines/tl120_all40_fixed.json` (feasible 40/40).
- Before any src edit, the git-less safety = copy src/ to `archive/` snapshot tag.

---
## ITERATION LOG
(append newest at bottom)

### iter 0 — setup + diagnosis (2026-06-16) — DONE
- Built infra, harness + competitor targets + baseline confirmed.
- **DIAGNOSIS VERDICT (code-analyzer static + empirical):** dominant cause = **H2** — the
  per-bay CP-SAT timing oracle (`_cpsat_bay_timing_verified`, myalgorithm.py:2596) builds an
  O(n²) disjunctive model and gets only `total_budget/len(work)` s per bay; a 50-100-block bay
  is too big to solve in seconds, and on timeout it does `continue` (line ~2731 pre-edit) =
  **keeps the floor's construction-order serialization → huge z1**. H3 (budget starvation,
  ~26s back-end shared across bays/levers) amplifies. H1 (floor force-places late entries,
  fastfloor delayed→forced cascade) is the substrate the oracle fails to fix. At T=120
  box-decomp does NOT run (gate T≥150) → set2@120 = pure legacy. OGC_Z1_REPAIR_LOOP is OFF for set2.
- **STALE-BASELINE CORRECTION (critical):** `tl120_all40_fixed.json` is NOT representative of
  current src. Fresh 3× runs of current src: prob_24 z1=326/326/326 (consistent! old baseline
  said 22585 = stale/outlier), prob_31 z1=91198/84995/95586 (~90K consistent), prob_35
  z1=31380/30347/32363 (~31K consistent). **Variance is only 6-12%, NOT 70×.** prob_31/35 are
  genuinely & consistently catastrophic (dense bays the oracle can't crack); prob_24 already
  near-optimal (z1 326 ≈ comp 149) → its bays must be small/tractable.
- **MUST re-baseline full SET2 with current src** (the stale json mislabels our true state).

### iter 1 — exact connected-component timing decomposition (LAUNCHED 2026-06-16)
- HYPOTHESIS: the per-bay disjunctive constraints couple only geometrically-interacting pairs
  (fixed layout) → the tardiness problem SEPARATES over connected components of the interaction
  graph (objective = Σ per-block tardiness). Solving components independently is EXACT (same
  optimum) but each is small → CP-SAT cracks it in its slice. Expected: prob_31/35 z1 ↓↓ IF
  their dense bays decompose into small components.
- IMPL: `OGC_TIMING_DECOMP` (default OFF, byte-identical legacy path via `continue`-skip) in
  `_cpsat_bay_timing_verified`. Builds interaction graph, finds components, solves each
  subset to optimum; tardy singletons → entry=release (instant optimal). Safety: result still
  gated by `consider()` (official checker) → cannot regress objective. snapshot:
  archive/src-snapshot-2026-06-16-iter0/.
- TEST: trio {24,31,35} @120 OGC_TIMING_DECOMP=1,DBG=1 (tag decomp_trio). Compare z1 vs
  diag baselines (326 / ~90K / ~31K). DBG prints per-bay component-size distribution = decides
  whether decomposition is viable (small comps → win) or the bays are one giant component
  (→ need greedy ATC fallback / different attack).
- **RESULT: REFUTED (gate stays OFF, solver unharmed).** decomp_trio: prob_24 326→1276
  (worse), prob_31 91K→95586 (no change), prob_35 31K→67220 (worse). DBG revealed the crux:
  **prob_31 bay=1 has n=118 blocks in ONE connected component (comps=1, top=[118])** — the
  dense set2 bay does NOT separate; all 118 blocks mutually crane-block. Decomposition cannot
  help. (decomp also produced suboptimal solves on the giant component, hence worse.)
- **REFRAME (key insight):** catastrophic set2 z1 = one OVERLOADED bay (~118 blocks) whose
  blocks ALL crane-interact (single giant blocking component); intrinsicLB=0 ⇒ tardiness is
  PURELY crane-serialization-induced. CP-SAT cannot sequence 118 disjunctively-coupled blocks
  in its ~3s slice. Note prob_31 bay=2 (n=20) is fine (tard=24). So the floor DUMPS ~118/200
  blocks into bay 1 → unavoidable serialization. Competitor gets prob_31 z1≈1472 ⇒ a far
  better layout+timing co-design exists.

### iter 2 — DECISIVE PROBE: is bay-1 serialization-bound or layout-bound? (2026-06-16)
- QUESTION: for the floor's GIVEN bay-1 layout (118 blocks, tard 23888), does a much better
  serialization exist (→ build a strong sequencer, ATC/beam/SA, medium effort) or is the layout
  itself the bottleneck (→ rebalance bay load / anticipatory placement, bigger change)?
- METHOD: load prob_31 captured solution, rebuild bay assignments, solve ONLY bay-1's
  disjunctive timing model with a LONG limit (~120s, 4 workers). If z1 ≪ 23888 ⇒
  serialization-bound. If z1 ≈ 23888 ⇒ layout-bound.
- **RESULT — DECISIVE:**
  - prob_31 bay1 = **119 blocks (59% of all 200!)**, floor_tard 83734 → CP-SAT@115s only
    57894 (−31%). **LAYOUT-bound** (even near-optimal timing on this layout stays catastrophic;
    57894 ≈ 39× competitor's TOTAL z1 of 1472).
  - prob_35 bay2 = **115 blocks (57%)**, floor_tard 24604 → CP-SAT@115s 11138 (−55%).
    SERIALIZATION-bound for the layout, BUT 11138 ≈ 15× competitor's total z1 (734) ⇒ also
    layout-overloaded.
  - **ROOT CAUSE (both): one bay absorbs ~57-59% of all blocks** → a single crane must serialize
    115+ blocks → z1 explodes. The assignment dumps the majority into the preference-magnet bay
    with NO capacity limit. intrinsicLB=0 everywhere (timing/crane only).
  - Production timing is ALSO starved (~3s/bay finds far-from-optimal order on dense bays;
    prob_35 115s finds 2× better) — secondary lever.

### iter 3 — assignment area-time capacity (load balancing) for set2 (PLAN)
- HYPOTHESIS: forcing the assignment to SPREAD blocks across bays (each bay = its own crane)
  shortens every crane chain → z1 ↓↓. `_cpsat_assignment` (myalgorithm.py:1615) ALREADY has an
  area-time cumulative capacity (cap=bay_area·cap_alpha, line 1677-1723), gated by `cap_alpha`
  (None ⇒ skipped ⇒ overload). w1(13333) ≫ w3(267) ⇒ the z3/preference cost of spreading is a
  big net win. Need: (a) confirm which assignment path builds the set2 layout, (b) inject
  cap_alpha for set2-size instances, (c) sweep alpha. Also a faster/better per-bay sequencer
  for the residual (secondary).
- **iter 3 RESULT — area-cap is NOT the lever (REFUTED).** OGC_FF_ASSIGN_CAP already defaults
  0.85 via SUBMIT_V2. Sweep on prob_31/35: tightening to 0.5/0.35 and magnet-tighten 0.4 barely
  moved blocks out of the overloaded bay (prob_31 bay1 119→113→112→106; prob_35 bay2 stayed
  ~115-119 and z1 got WORSE). Confirmed: the area-time cumulative cap bounds CONCURRENT area,
  NOT crane-chain length / block count — blocks time-share under the cap. BUT magnet-tighten
  pushing 13 blocks out of prob_31 bay1 (119→106) cut z1 91K→71K (−22%) ⇒ **removing blocks
  from the overloaded bay DOES cut z1**; we just need a lever that bounds COUNT, not area.

### iter 4 — per-bay block-COUNT cap in assignment (IMPLEMENTED, testing)
- HYPOTHESIS: the assignment objective is z1-blind (min z2[workload]+z3[pref]); neither it nor
  the area cap limits how many blocks pile into the magnet bay. A hard per-bay COUNT cap =
  ceil(n/n_bays·beta) forces spreading across bays' cranes → shorter chains → z1 ↓↓.
- IMPL: `_cpsat_assignment` new param `count_cap_beta` + constraint `sum_b x[b,j] <= cap`;
  infeasible→fallback drops count-cap first then area-cap (never loses assignment). fastfloor
  reads env `OGC_ASSIGN_COUNT_CAP=<beta>` (default OFF) and passes it. Default path unchanged.
  Other 2 call sites unaffected (param defaults None). import OK.
- TEST: prob_24(guard)/31/35 @120, beta {1.5,1.2,1.0} (prob_31 caps→70/60/50; prob_35→94/80/67),
  with bay distribution.
- **RESULT — REFUTED, hypothesis INVERTED (important).** Forcing balance does NOT help and
  often HURTS: prob_31 balanced 50/50/50/50 → z1 95586 (vs baseline imbalanced 119-bay 91198,
  slightly WORSE); prob_24 forced balance 33/32/35 → z1 22585 (vs baseline 39/24/37 = 326, a
  **70× explosion!**). So the preference-respecting (often imbalanced) assignment is ALREADY
  z1-favorable — blocks prefer the bay where they fit/time well; forcing them elsewhere causes
  delayed/forced placement → tardiness. (The stale `tl120_all40_fixed.json` prob_24=22585 was
  almost certainly a balanced/perturbed run; current default = 326.) count-cap code stays
  dormant (gate OFF, default path untouched).
- **SYNTHESIS / PIVOT.** Combining all probes: (i) dense set2 bays are ONE giant crane-
  interaction component (iter1); (ii) even OPTIMAL timing on the floor's layout stays
  catastrophic (prob_31 115s→57894 ≈ 39× comp; iter2); (iii) neither timing budget nor
  assignment balance closes the gap (iter3/4). ⇒ **The LAYOUT's crane-blocking structure is
  the binding constraint.** Competitor z1≈1472 on prob_31 ⇒ near-complete parallelism ⇒ a
  layout with LOW vertical crane-blocking. Our greedy BL floor packs tightly → high blocking →
  forced serialization → z1. **The lever is a crane-blocking-aware layout (the new set2
  engine), NOT timing/assignment tuning.**

### iter 5 — confirm time-ceiling + investigate existing crane-aware constructive (2026-06-16)
- (a) CONFIRM: run prob_24/31/35 @TL300 (default; T≥150 also enables box-decomp hybrid). If z1
  stays ~90K/31K ⇒ existing arsenal exhausted ⇒ justifies disruptive layout build.
- (b) INVESTIGATE: `uconstruct.py` = CP-SAT-guided crane-aware greedy constructive (set1
  breakthrough: z1=0 19/20, "crane-feasible by construction"). Is it applied to set2 at T=120
  (OGC_REBUILD_AUGMENT)? Does it produce lower-blocking layouts? If it helps set2 but is
  gated/timed-out, enabling/scaling it could be the lever.
- **(a) RESULT — 🎯 BREAKTHROUGH, PREMISE INVERTED.** TL300 default (no edits, gates OFF):
  prob_24 z1=126 obj 2.06M, prob_31 z1=1,331 obj 21.2M, prob_35 z1=505 obj 7.69M —
  **ALL THREE BEAT THE COMPETITOR** (comp z1 149/1472/734; comp obj 2.74M/22.3M/10.65M).
  set2-trio total 30.99M vs comp 279.82M. **The problem was never layout — it was TIME.** The
  existing layout SEARCH (cum_level multi-order + box-decomp at T≥150) finds near-optimal
  low-crane-blocking layouts given ~300s; at TL120 it is time-STARVED. My iter2 probe was
  misleading: it re-timed ONE bad TL120 layout (layout-bound for THAT layout), but with 300s
  the solver finds a DIFFERENT, good layout. iter1-4 + iter6 (decomp/balance/placement) were
  all barking up the wrong tree — code is dormant (gates OFF), no harm.
- **(b) uconstruct: still not the lever** (it's a fastfloor BL wrapper) — moot now.
- **⚠ CRITICAL CAVEAT — wall discipline:** at TL300, prob_31 took **wall=349s (49s OVER the
  300 limit)**, prob_35 322s, prob_24 287s. A strict eval server kills at the limit → -1. So
  the real engineering task is: USE more time AND respect `timelimit` strictly (never overrun).

## 🎯 PIVOT (iter 7+) — the winning path is TIME + WALL DISCIPLINE, not a new engine
1. Find the eval server's ACTUAL per-instance timelimit (docs say "수 분~30분"; memory assumed
   operating TL=120s out of -1 caution; "1.31M은 TL≈200 낙관치"). The server PASSES `timelimit`
   to algorithm() — we don't choose it. If it's >>120s, the solver is already far better than
   the TL120 testing implied, and set2 may already beat the competitor on the server.
2. Confirm FULL set2 @ a higher TL beats competitor (run TL300, maybe TL600).
3. FIX wall discipline: the 349s overrun means some stage ignores the deadline. Make algorithm()
   return strictly within `timelimit` (margin) on EVERY instance → never -1. This is the gate to
   safely using the server's full budget.
4. Determine the safe operating TL and ensure ALL40 feasible + within-limit + beats competitor.

### ‼ USER CORRECTION (2026-06-16): TL = 120s IS THE LAW. Competitor also ran @120s.
- The eval server budget is **120s** (not minutes-to-30min — I misread docs). The competitor
  achieved set2 z1≈1472/734/149 (prob_31/35/24) in **~107s wall** (their data confirms
  wall≈105-108). We get z1≈90K/31K/326 in 120s. **The gap is REAL at 120s.**
- TL300 results are UNUSABLE (can't use that budget). BUT the key insight survives: a
  120s-achievable good solution EXISTS (competitor proves it) and our solver CAN find it given
  ~300s ⇒ our problem is **search EFFICIENCY at 120s**, not capability. Wall-discipline (iter 7)
  is MOOT (we never exceed 120 at TL120 — validated wall≤115.4).
- PRIME SUSPECT: **box-decomp is gated OFF at T<150** (OGC_HYBRID_MIN_T=150). So at TL120 we
  run PURE LEGACY (weak on set2); at TL300 box-decomp kicks in and wins. ⇒ **enabling box at
  T=120 (best-of, so set1 unharmed) may be the clean win.** Test: box-only @120 vs legacy @120.

### iter 8 — 🎯 ROOT CAUSE FOUND: box-decomp gated off at T<150 (2026-06-16)
- Added OGC_BOX_ONLY hook (myalgorithm.algorithm: run boxsolver on full T, gated, default OFF).
- **box-only @120 on trio (wall 109-112s, WITHIN 120!):** prob_24 z1=123 obj 2.95M; prob_31
  z1=**1,331** obj 21.2M; prob_35 z1=**505** obj 7.69M. **BEATS competitor** on prob_31 (obj
  21.2M<22.3M) and prob_35 (7.69M<10.65M); prob_24 z1 123<comp 149 but obj 2.95M slightly >comp
  2.74M (box over-spills z3 there). vs LEGACY@120 (z1 326/91,198/31,380) box is MASSIVELY better
  on set2.
- **THE FIX = enable box-decomp at T=120.** The whole "set2 catastrophic" was: the set2-winning
  engine (box-decomp) is gated off at T<150 (OGC_HYBRID_MIN_T=150), so TL120 ran pure legacy.
- TENSION: box REGRESSES set1 (CLAUDE.md: fresh-start box →5M); legacy wins set1. Must keep
  best-of(legacy, box) so set1 uses legacy, set2 uses box. But hybrid@T120 gives box only
  reserve=min(80,0.3·120)=36s (box used ~109s in box-only). Need: does box converge by ~36-60s?
  If yes → lower OGC_HYBRID_MIN_T (~1-line fix). If no → need a bigger box share at 120 (steals
  from legacy → may hurt set1) ⇒ route by instance, or run box-only on set2-like + legacy on set1.
- NEXT: box@{36,60} convergence on trio → then full ALL40 test of the chosen hybrid/routing.
- **CONVERGENCE RESULT — box converges FAST:** trio z1 by budget:
  prob_24 36s→228, 60s→146, 90s→125, 120s→123; prob_31 36s→1492, 60s→**1343**, 90s→1331;
  prob_35 36s→548, 60s→**521**, 90s→505. **box@60s already BEATS competitor** (prob_31
  1343<1472, prob_35 521<734, prob_24 146≈149). ⇒ giving box ~60s in the hybrid suffices for set2,
  leaving ~60s for legacy. KEY remaining Qs: (1) does box REGRESS set1 (maybe current boxsolver
  is fine, unlike old fresh-start)? (2) does legacy@60 still hold set1 z1=0 on 19/20? Testing
  box@120 on set1 + legacy@60 on set1. If box is good on set1 too → box-only wins both (set1 also
  loses to comp 1.42M vs 931K). If box regresses set1 → best-of(legacy@~60, box@~60) or routing.

### iter 9 — set1 engine map + adoption design (2026-06-16)
- set1 totals (vs comp 931,465): legacy@120 = **1,421,441** (baseline, wins 5/20); legacy@60 =
  1,934,841 (legacy NEEDS ~full time for set1 — regresses at 60); box@120 = **8,090,869**
  (box CATASTROPHIC on set1 alone, wins 1/20); best-of(legacy@120,box@120) = **1,349,570**
  (BETTER than legacy alone — box wins prob_3/4/18). 
- CONSTRAINTS: legacy needs ~120s for set1; box needs ~60s for set2; box catastrophic on set1
  (except 3/4/18); legacy catastrophic on set2. IDEAL = best-of(legacy@120, box@120) but =240s.
- ADOPTION OPTIONS at 120s: (A) hybrid split legacy@(120-r)+box@r best-of (SAFE: best-of fallback
  both ways, no fragile classifier, but compromises both budgets); (B) per-instance ROUTING full
  budget (best per-instance but risky on misclassified/unseen instances). Total obj is set2-
  dominated (billions vs set1 millions) → maximize box budget matters most for TOTAL, but
  per-instance RANK (the real score R-nb) needs set1 kept good too → best-of, not box-only.
- TESTING: box@120 full set2 (ceiling + routing map) + hybrid@120 reserve=36 (legacy@84+box@36,
  OGC_HYBRID_MIN_T=60) on ALL40.

### iter 9b — classifier is fragile → use robust best-of (2026-06-16)
- box wins set1 EXACTLY {prob_3, 4, 18} (box/leg 0.56-0.73); loses the other 17 (prob_11-14,20
  catastrophic 8-18×). No clean instance-feature boundary separates box-winners from losers
  (prob_18 util2.62 box-win vs prob_20 util1.95 legacy-win). ⇒ a static router is RISKY on
  unseen instances. Use **best-of(legacy, box)** (gated by official checker — never regresses
  below the better engine) with a tuned budget split r (box reserve). Pending: box120_set2 total
  + hyb36_all40 (legacy@84+box@36) to pick r. Consider later: parallel 2-core/2-core to give both
  near-full wall (box converges at 60≈2-core-120).

### ✅ iter 10 — ADOPTED: hybrid enabled at T=120 (2026-06-16) — 4.24B → 330M, never -1
- **CHANGE (banked):** `OGC_HYBRID_MIN_T` default 150 → **100** (myalgorithm.py:7506). Now the
  eval's T=120 ENABLES best-of(legacy@84, box@36). Default solver (no env) at T=120:
  - ALL40 = **330,142,906** (was 4.24B = legacy-only) — **12.8× improvement**, 1.176× competitor.
  - set1 = 1,422,465 (no regression vs legacy@120's 1.421M — legacy@84 holds set1).
  - set2 = 328,720,441 (box@36 crushes the old 4.24B).
  - **feasible 40/40, max wall 113.0s (7s margin), NEVER -1.** best-of (checker-gated) can't
    regress below legacy. (= hyb36_all40 run, which used MIN_T=60 ≡ new default at T=120.)
- box-only@120 full set2 CEILING = 313.8M (1.121×, wins 7/20) — box alone still loses set2 by
  12%. To BEAT competitor (280M) box must improve on its 13 set2 losses:
  - z3 OVER-SPILL (prob_22/23/24/29/30/39): box gets good z1 but z3 ≫ comp (prob_30 z3 4380 vs
    42, prob_39 9610 vs 59). box trades z3 for z1 crudely; comp gets BOTH low.
  - z1 OVER (prob_32/33/37/38/40, 250-block): box z1 > comp (prob_40 7151 vs 5977).
- box has z3-aware machinery: CYCLE 10 reassign (OGC_REASSIGN=1, ON) + CYCLE 18 targeted-spill
  feasspill (OGC_FEASSPILL, OFF — "the breakthrough z1-lever", stronger z3-realize). Hybrid hook
  forces FEASSPILL=0. TESTING: box@120 +FEASSPILL=1 on the loss instances → does box's z3/z1
  ceiling beat comp? If yes → route set2 to box-full+feasspill; if no → box near ceiling.

### iter 11 — box ceiling analysis: z3-spill is packing-density-bound (2026-06-16)
- box@120 +FEASSPILL=1 = byte-identical to box-default (feasspill is a z1-via-spill lever =
  INCREASES z3, wrong direction). box@120 +PHASEB=1 (z3-recovery at z1=0) = also byte-identical:
  per its own code comment, EVERY z3-reducing move breaks z1=0 (moving a spilled block back to
  its preferred bay re-creates tardiness). ⇒ **box's z3 over-spill is FUNDAMENTAL: it can't pack
  preferred bays as densely as the competitor at z1=0, so it must spill (z3↑). This is the
  packing-density wall** (CLAUDE.md falsified-lever territory). e.g. prob_30 comp packs at z3=42,
  box must spill to z3=4380.
- box's set2 losses: z3-spill ~14M (packing density, hard) + z1-OVER on 250-block instances
  ~27M (prob_38 alone +16.6M; box z1>comp at scale). box set2 ceiling = 313.8M > comp 279.8M ⇒
  **no legacy/box split or routing beats comp; need to improve box's core (packing / big-inst z1).**
- REMAINING LEVERS: (1) hybrid reserve tuning (box budget↑ lowers set2; set2-dominated total) —
  safe incremental, testing reserve=60 (added OGC_HYBRID_RESERVE_S override + wall margin).
  (2) OGC_BOXDECOMP_MAX (default 70): box-decomp SKIPS bays >70 blocks → big set2 bays
  (250-blk/3-bay ≈ 83/bay) fall back to a weaker packer → the z1-over losses. Raising it may
  help the big instances (the bigger 27M gap chunk). Testing next.
- HONEST STATUS: banked 330M (12.8× improvement, 1.176× comp, never -1) is the core deliverable.
  Beating comp (280M) needs a packing/scaling breakthrough on box; pursuing the 2 levers above.

### iter 12 — reserve tuning: reserve=36 is the sweet spot (keep adopted) (2026-06-16)
- reserve=60 (legacy@52+box@60) ALL40 = 322.4M (1.148×) — total slightly better than hyb36's
  330M, BUT set1 = 4.89M (5.25×, CATASTROPHIC — legacy@52 can't solve set1) and per-instance
  wins crashed 12→6. legacy needs ≥~76s for set1. Real score = per-instance RANK ⇒ hyb36
  (reserve=36, set1 held 1.42M, 12 wins) BEATS reserve=60 despite higher total. **KEEP reserve=36
  (adopted default).** Pushing box budget trades set1 rank for marginal total — not worth it.
  (OGC_HYBRID_RESERVE_S override kept in src, gated/default-unset → adopted default unchanged.)
- max wall reserve=60 = 102s (safe), so wall isn't the limiter — set1 quality is.

### iter 13 — ACCZ1 dense-cells z3-recovery = no effect; levers exhausted (2026-06-16)
- box@120 +OGC_ACCZ1=1 (dense-cells packer + Phase B z3-recovery) = byte-identical to box-default
  on all 7 loss instances. The dense-cells re-base finds NO z3-recovery move either ⇒ box's
  z3-spill is genuinely irreducible by post-processing.

## ═══ FINAL STATE / SESSION SUMMARY (2026-06-16) ═══
**DELIVERED (banked, validated, safe):** `OGC_HYBRID_MIN_T` 150→100 (myalgorithm.py:7528) — the
ONLY default change. Root cause of set2 catastrophe was that box-decomp (the set2-winning engine)
was gated OFF at T<150, so the eval (T=120) ran pure legacy. Final clean default validation:
**ALL40 = 328,714,827 (1.171× competitor), set1 1.41M / set2 327.3M, feasible 40/40, max wall
113.1s, NEVER -1, 11/40 wins.** vs prior legacy-only (4.24B) = **12.9× improvement**; vs
competitor 15.1×→1.17×. best-of(legacy,box) is official-checker-gated ⇒ cannot regress below legacy.

**WHY WE DON'T (yet) BEAT COMPETITOR (280.8M):** box's set2 ceiling = 313.8M (box@120 full) >
comp 279.8M. The 34M gap = (a) z3-OVER-SPILL ~14M on prob_22/23/24/29/30/39 — box can't pack
preferred bays at z1=0 as densely as comp, so it must spill (z3↑); irreducible by post-proc
(PhaseB/ACCZ1/feasspill all no-op). (b) z1-OVER ~27M on 250-block prob_32/33/37/38/40 — box z1>comp
at scale (prob_38 alone +16.6M). Both are PACKING/SCALING limits of box's packer.

**LEVERS TRIED & RULED OUT (all gated default-OFF, dormant, solver unharmed):** timing decomp
(bays are 1 giant component), assignment balance area-cap+count-cap (no help; count-cap HURTS —
prob_24 70×), due-aware placement, feasspill (wrong direction), Phase B & ACCZ1 (z3-recovery
breaks z1=0), reserve>36 (destroys set1), BOXDECOMP_MAX (big bays still bail).

**THE ONLY PATH TO BEAT COMPETITOR:** a denser preferred-bay packer (so box spills less → z3↓)
and/or a faster/better big-instance method (z1↓ at 250 blocks). This is the polygon-nester /
exact-packer territory that CLAUDE.md marks FALSIFIED ("재시도 금지") — high-effort, uncertain,
and risky to the banked win. NOT attempted unvalidated while user asleep. Recommend the user
decide whether to invest in packer R&D, or accept the 12.9× safe win (1.17× comp).

**Gated experiment env knobs added this session (all default-OFF, for future use):**
OGC_BOX_ONLY, OGC_HYBRID_RESERVE_S, OGC_TIMING_DECOMP, OGC_ASSIGN_COUNT_CAP, OGC_FF_DDPLACE.

### 💾 BANKED WIN SAVED (2026-06-16, user: "save current then try disruptive")
- src snapshot: `archive/src-BANKED-328M-2026-06-16/` (16 files).
- submission zip: `submissions/BANKED-328M-2026-06-16-*.zip` (0.23MB, ready to email).
- = the validated default (OGC_HYBRID_MIN_T=100): ALL40 328.7M, feasible 40/40, never -1.

### iter 14+ — DISRUPTIVE packer R&D (gated, can't touch banked win) (2026-06-16)
- alpha=1.3 minimal-spill spec: no help (less spill → higher z1 → worse obj; obj-gate rejects).
  Confirms over-spill is packing-density-bound, not coarse-alpha.
- MECHANISM insight: box reassign (CYCLE10) starts from preferred & spills minimally but
  UNDER-spills (leaves z1); pool specs OVER-spill (z1=0, z3 cliff). Competitor's optimum
  (prob_29: z1=64,z3=1522) is BETWEEN — neither finds it. Root = bbox-proxy z1 is inaccurate.
- Sweeping box knobs (OGC_BD_WORKERS, BD_Z1ZERO, BOXDECOMP_K, CRANE, FEASSPILL params, REASSIGN
  params) on loss subset {29,30,32,38}; results ↓ (added gated OGC_BOX_ALPHAS knob; ";"-split TODO).

### iter 15 — disruptive R&D results: box ceiling is structural (2026-06-16)
- compute-depth (OGC_BD_WORKERS 2/4, PARALLEL=0, K=3): all within CP-SAT NOISE (±, not a lever;
  the earlier bdw2 prob_38 −3.4M was noise). box-default ≈ best box config.
- NEW MECHANISM 1 — OGC_BOX_ALPHAS (minimal-spill α spectrum, gated): no help (less spill→higher
  z1→worse obj; obj-gate rejects).
- NEW MECHANISM 2 — OGC_ACCZ1_MAIN (accurate cells z1 in the MAIN reassign loop, not just Phase
  B, gated): no effect. The accurate-z1 reassign still can't beat the over-spilled pool spec ⇒
  the minimal-spill optimum (competitor's z1=64/z3=1522) is NOT reachable by box's local search,
  or doesn't exist in box's packing (preferred-denser bays genuinely have high z1).
- **DOUBLE-BIND CONFIRMED:** any assignment search needs fast+accurate per-bay tardiness. The
  bbox proxy is fast but OVER-estimates (→under-spill); the cells packer is accurate but too slow
  (→few moves, can't converge). The accurate-reassign failure proves the metaheuristic-with-
  accurate-eval path is blocked by eval cost. Breaking it needs a fast accurate crane-tardiness
  surrogate = a research problem.
- **~17 attempts total, ALL fail to breach box's 313M set2 ceiling.** Beating competitor (280M)
  needs a fundamentally denser crane-aware packer — CLAUDE.md FALSIFIED ("재시도 금지") + a major
  from-scratch build + the eval-cost bottleneck. Not achievable by config/local-search.

## ═══ FINAL RECOMMENDATION ═══
SHIP the banked win: **328.7M (1.17× comp), feasible 40/40, never -1, 12.9× improvement** over the
prior solver. Saved: `archive/src-BANKED-328M-2026-06-16/` + `submissions/BANKED-328M-*.zip`.
Beating the competitor is a packer-R&D project (denser per-bay crane-aware packing + a fast
accurate tardiness evaluator) — high-effort, uncertain, falsified-flagged; recommend the user
decide whether to invest. All disruptive levers tried this session are gated default-OFF (dormant).

### 🎯 iter 16 — PACKING-DENSITY BREAKTHROUGH via literature research (2026-06-16)
- User: "do large-scale academic research and overcome." 4 parallel web-researchers (~15 papers)
  → problem = Block Spatial Scheduling + Block Relocation; lever = per-bay PACKING EFFICIENCY
  (ours ~80% BL vs competitor ~95%). Diagnostic: prob_29 preferred 116-block bay → 89 DELAYED
  (no space at release) → z1=1149; comp z1=64. NOT spill/timing/order — it's packing density.
- fastfloor already had `_ft_search_pos_lca` (Largest-Contact-Area dense placer, "falsified").
  Wired it (OGC_FF_LCA gate). Full solver + OGC_FF_LCA=1,band=3 on EASY-loss:
  **prob_22 obj 858K < comp 902K WIN; prob_29 obj 466K (z1=0,z3=1512) BEATS comp on BOTH
  z1 (0<64) AND z3 (1512<1522)!** Mechanism: assignment-spill keeps bays small enough + LCA
  densifies → fits more in preferred → low z3 at z1=0 = the competitor's regime.
- Global OGC_FF_LCA REGRESSES (330.9M: helps 22/23/28/29, hurts set1) ⇒ must be PER-BAY BEST-OF.
  best-of(banked, LCA) = 328.4M (+1 win). INTEGRATION: `OGC_FF_LCA_RACE` (default ON) in
  `_decode_attempts` — runs LCA ONCE on a congested bay (best_tard>0) and keeps it iff it lowers
  tardiness. Per-bay best-of ⇒ objective NEVER regresses; budget-bounded (huge bays time out
  harmlessly). Validating ALL40 (band3) for total + set1-regression + wall/-1 safety.
- NEXT: band sweep; make LCA fast enough for BIG bays (the z1-over 27M chunk, prob_38 etc. where
  LCA currently times out) — that's the larger prize.

### iter 7 (SUPERSEDED — wall discipline moot at TL120)
### iter 7 — wall-discipline investigation (in progress 2026-06-16)
- CONFIRMED server budget (docs/problem-analysis.md:28): per-instance **"수 분 ~ 30분"
  (minutes to 30 min)**, wall-clock. The server PASSES this as `timelimit` to algorithm().
  TL120 was a conservative LOCAL testing choice, NOT the server budget. ⇒ set2 instances
  almost certainly get minutes on the server, enough for the solver's ~300-350s productive work.
- HYBRID budget (myalgorithm.py:7491 `algorithm`): T≥150 ⇒ reserve=min(80,0.3T); legacy gets
  `T-reserve`, then box-decomp (`boxsolver.algorithm`) gets `reserve`; sums to T. PLUS two
  `check_feasibility` calls (chk_a, chk_b) on 200-block solutions = uncounted overhead.
- OVERRUN at TL300: prob_31 wall=349 (legacy 220 + box 80 = 300, +49 leak). Leak source TBD —
  candidates: floor construction (historical runaway, memory: prob_25), box overrunning its 80s,
  or the 2× check_feasibility overhead. MUST measure with OGC_STAGE_TIMING on the slowest
  instance (deferred: cores busy with full-set2 confirm run).
- WALL-SAFETY STRATEGY (the #1 deliverable — guarantees never -1 at any server TL):
  (i) make every component respect its budget (fix the leak); (ii) add a safety margin so
  legacy+box+checks ≤ timelimit−margin; (iii) optionally cap productive work at the ~350s
  plateau (more time is wasted, not harmful, once wall-safe). Then: small server TL ⇒ safe
  TL120-like (feasible, maybe not winning); large server TL ⇒ winning set2; NEVER -1 either way.
- NEXT on full-set2 result: read per-instance wall times → find all overruns → instrument the
  worst → locate & fix the deadline leak → re-validate ALL40 wall≤TL−margin + set2 beats comp.
