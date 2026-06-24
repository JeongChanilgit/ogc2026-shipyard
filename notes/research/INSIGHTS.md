# OGC 2026 — ALGORITHM INSIGHTS (living, accumulating)

> The single growing knowledge base for the from-scratch solver (2026-06-14 reset).
> Driven by a continuous **hypothesis → implement → verify(full-set obj) → feedback**
> loop over a 50+ source library. Append; never silently drop a rejected hypothesis
> (record WHY it failed — that's the value). Read with
> `notes/FRESH-START-INSIGHTS-2026-06-14.md` (problem facts, v0, falsified levers).

Conventions:
- **Verification = full instance set** (ALL40 = set1 prob_1..20 + set2 prob_21..40),
  judged by **total objective** + feasibility (never −1). set1 also has a competitor
  table (`notes/competitor-2026-06-11.json`) for win-counting.
- Every experiment: hypothesis, change, command, result table, verdict (KEEP/REJECT),
  and the one-line reason. Source citations as `[S##]` into the Source Library.

---

## 0. Current algorithm state

> ## ★★★ OPERATIVE TL = 120s (user, 2026-06-15) — re-validate EVERYTHING at TL=120
> The competition/eval time limit is **~120s per instance** (competitor wall_times: set1 56-110s, set2
> 105-110s, all <120). ⇒ (1) my hybrid set1 baseline **1.31M was measured at TL≈200 — OPTIMISTIC**; the REAL
> TL=120 set1 obj is worse and must be re-measured. (2) **−1 is NOT a set2-only risk:** the greedy floor cost
> is TL-independent (~124s on prob_25), so **set1's slow instances (prob_13/14/20) can ALSO overrun at TL=120 →
> −1 on instances we win/tie** (catastrophic). The floor-bounding fix below is needed for set1+set2 BOTH.
> (3) Competitor does prob_13 z1=0@z3=432 in **96.7s** ⇒ the realize gap is algorithmic, not time. All
> validation now at **TL=120** via the HYBRID (`_fstest.py`/`eval.py --set`).
>
> ## ★★★ SET2 −1 HARDENING 2026-06-15 PM (user-chosen track — highest real-score EV)
> **Reproduced (`_set2time.py`, legacy @TL=120):** prob_25 (100 blk, 2 bays 151×29/63×27) wall=**181s**
> (OVER +61s); prob_26 (150 blk, 3 bays) wall=**163.7s** (OVER +43.7s). Both → −1 on server.
> **TWO overrun sources:** (1) **GREEDY FLOOR** — Phase-1 EDD placement reached 100/100 @**124s** on prob_25
> (already past hard_stop=112s). Per-block search is O(blocks-in-bay) Shapely + whole-bay grid scan on the big
> 151×29 bay; the floor cost is essentially **TL-INDEPENDENT** (must place all blocks) and the `1.2e-3·n²`
> estimate under-predicts ~10× ⇒ `_fast_floor` never triggers, `force_after`(=0.94T=113s) fires too late, and
> one near-full-bay grid scan is 4-8s so a couple overrun before force. (2) **POSTPROCESS** — prob_26 greedy
> done @110.7s but cum_level/cpsat-timing ran to 163.7s (51s past hard_stop); the per-bay CP-SAT **model build**
> (O(n²) Shapely, NOT counted in max_time_in_seconds) overruns on big bays. **NO static size proxy separates
> set2-overrun from set1** (prob_13 has HIGHER cost yet fits at TL=200; set2 is more congested → slower per
> unit) ⇒ fix must be RUNTIME-adaptive.
> **★★★ FIX SHIPPED + VALIDATED (default-active, 2026-06-15):** THREE parts in `src/`:
> (a) `baseline_greedy._place_blocks` **ADAPTIVE FORCE** (`OGC_ADAPTIVE_FORCE`, default ON) — project finish from
> observed placement rate; force the remainder (bbox-only `_force_place`, ~instant) the moment it'd breach
> force_after. Self-calibrating: fast set1 floors finish first ⇒ never triggered ⇒ no regression.
> (b) `greedyalgorithm` Phase-1 call now PASSES `force_after=soft_stop_abs` (was None ⇒ floor ran unbounded —
> THE root bug). (c) `myalgorithm._legacy_algorithm` `OGC_FLOOR_BUDGET_PCT` default **50 for T≤150** (0 for
> generous TL) ⇒ floor finishes in ~50% of T, leaving the postprocess+wall-guard their window.
> **VALIDATED @TL=120 (real eval limit) via the HYBRID (`_fstest.py`):** prob_25 wall 181→**113.8s** (z1=9869,
> feasible), prob_26 163.7→**109.2s**, prob_13 **109.8s z1=0 obj 113,599** (=baseline, NO regression),
> prob_20 **110.7s z1=0 obj 181,166** (=baseline). ⇒ never −1 on set1+set2 slow instances AND zero set1 quality
> loss (the floor was wasting time; bounding it lets the postprocess still reach z1=0 in 120s). Set1 @TL=200
> also unaffected (prob_13 113,500, prob_14 111,991). Reversible: OGC_ADAPTIVE_FORCE=0 / OGC_FLOOR_BUDGET_PCT=0.
> **★★★ FULL ALL40 @TL=120 AUDIT — COMPLETE SUCCESS (`baselines/tl120_all40_fixed.json`): feasible 40/40,
> INFEASIBLE=NONE, all walls ≤ 115.4s ⇒ NEVER −1 across the entire set.** REAL TL=120 baseline (supersedes the
> optimistic 1.31M @TL≈200): **set1 total = 1,420,811** (5 wins prob_1/2/7/8/19; prob_13/20 keep z1=0 at baseline
> obj), set2 ALL feasible (walls 109-115s, was −1; wins prob_21/22/29), ALL40 total 4.245B. Box-decomp set1 wins
> shrink at TL=120 (prob_3 52→77K, prob_4 26→46K, prob_18 74→103K — box-decomp needs time). ⚠ tightest wall =
> prob_27 115.4s (4.6s margin) — fine on 4-core eval (==local); a touch more WALL_MARGIN_S could harden the
> biggest set2. **set2 −1 = SOLVED; single biggest real-score lever (each avoided −1 ≈ +R/2).** Competitor
> set1=931K ⇒ real gap −489K (realize wall, unbuilt).
>
> ## ★★★ REALIZE-GAP DIAGNOSTICS 2026-06-15 PM (approaches A & B + a key oracle finding)
> Per-instance work on prob_13 (legacy z1=0@z3=805→113.5K; comp z1=0@z3=432→71.8K):
> - **boxsolver `_solve_reassign` (approach B via bbox+greedy) STALLS at z1=161, z3=158** (`_h11test.py`):
>   a genuine under-spill local optimum (even cells/cpsat-final-packed). All bays full ⇒ no single move
>   helps ⇒ needs ALNS (multi-block destroy-repair / accept-worse) to escape. ACCZ1 Phase-B (my edit,
>   gated OGC_ACCZ1) is MOOT here — it's z1=0-gated and reassign never reaches z1=0.
> - **`_solve_feasspill` (approach B, greedy cells-guided spill): z1=70 @z3=268 @TL=200; obj 252K
>   @TL=400 (INSIGHTS cyc18); steeply time-sensitive (NOT plateaued at 200s).** Generous-TL test running.
> - **★★ KEY ORACLE FINDING (`_z3descent.py`): boxsolver's cells/cpsat realize is MUCH WEAKER than legacy's.**
>   Re-packing LEGACY's OWN z1=0 prob_13 assignment with boxsolver `_pack_one_cells` gives **z1=321** (cpsat
>   best-of: z1=21) vs legacy's **z1=0**. ⇒ legacy's `_fixed_time_decode` + verified-cpsat-timing oracle is
>   UNIQUELY strong; every boxsolver-based realize-gap attempt (reassign/feasspill/descent) is HANDICAPPED by
>   a weaker packer. ⇒ z3-descent from legacy's seed made 0 moves (its cells baseline wasn't z1=0). To test
>   "z3<805 @z1=0 reachable" CORRECTLY needs legacy's realize as the per-move oracle (slow). NOTE prior
>   `_combine.py` already tested legacy-realize on low-z3 assignments: plateaus z1~53 @z3=138, needs z3≈800
>   for z1=0 ⇒ even legacy's STRONG realize can't do z1=0 below z3≈800. Competitor's z1=0@z3=432 ⇒ a packing
>   density neither realize builds (= the falsified polygon-nester / spyrrow-doesn't-translate wall).
> - **★★★ BREAKTHROUGH LEAD (approach B, feasspill @generous TL): the assignment is EXCELLENT, only z1
>   remains.** prob_13 feasspill @TL=700 (converged ~387s): **z1=10, z2=4137-4609, z3=152-199, obj 229-233K.**
>   z3=152 CRUSHES competitor (432) and legacy (805)! But z1=10 × w1≈18,605 = 186K keeps obj at 229K. **If
>   z1=10→0 on THIS assignment: obj ≈ w2·z2 + w3·z3 ≈ 43,261 → BEATS competitor (71,823) by 28K on prob_13.**
>   z1≤3 already beats legacy (113,500). So prob_13 hinges entirely on closing the last z1≈10.
> - **z1=10 is NOT a realize-oracle problem** (legacy decode on the same assignment = z1=68, WORSE than
>   feasspill's box-decomp-cumulative z1=10; each realize tuned to its own assignment). It's a SPILL/ASSIGNMENT
>   problem: feasspill's PHASE A (OGC_FEASSPILL_STEPS=24, cheapest-z3 spill, tabu) + PHASE B (measure every 2nd
>   snapshot, patience=4) STOPS at the k≈8 sweet spot (z1≈8-10); the z1=0 point may be further along the
>   trajectory (more spill, z3 up — still cheap) OR needs a different spill target (the cheapest-z3 block isn't
>   the one causing residual z1). z1_lb=0 + comp z1=0 ⇒ z1=0 IS achievable, not intrinsic.
> - **★ SPILL CURVE MAPPED (`_spillcurve2.py`, cheapest-z3 spill, box-decomp realize each step):** z1 bottoms
>   at **≈11 (k=8-12, z3=152-199), best obj 250,368 @k=11** — then BOUNCES (k13 z1=53, k29 z1=13). **Cheapest-z3
>   spill NEVER reaches z1=0** and best obj (250K) still LOSES to legacy (113.5K) since z1=11×w1≈18.6K=205K. The
>   residual ≈11 is a STUCK tardy block cheapest-z3 doesn't remove (z1_lb=0 + comp z1=0 ⇒ removable). The z1
>   bounce (11↔53 adjacent k) is partly box-decomp 4-worker cpsat NOISE (±). z3 only reached 273 at k=30 (< comp's
>   432) — trajectory spills LESS than comp.
> - **★ MOST-TARDY SPILL (`_spillcurve3.py`) DOES close z1=0** — but over-spills: z1=0 first at k=21 (z3=782),
>   best obj **115,271 @k=27 (z1=0, z2=3184, z3=747)** ≈ legacy (113,500), within cpsat noise ⇒ TIES legacy, does
>   NOT beat comp. cheapest-z3 keeps z3 low (152) but floors z1=11; most-tardy closes z1 but needs z3≈747.
> - **★★ REALIZE FLOOR QUANTIFIED: our box-decomp realize needs z3≈747 for z1=0; competitor does z1=0 @z3=432.**
>   At z3≈432 our realize gives z1≈91 (most-tardy k6). The ~315 z3-unit gap = the packing-density deficit (comp
>   packs z1=0 denser; spyrrow density didn't translate). Both spill strategies converge to ~legacy's regime.
> - **★ EFFICIENT spill (max z1-relief/z3-cost, `_spillcurve4.py`): best z1=5 @z3=335, obj 154,230 (k=36).**
>   Gets the LOWEST z1 at low z3 of all three strategies but STILL not 0. Summary of the 3 spill strategies on
>   prob_13 (box-decomp realize, PACKTL=28): cheapest-z3 floors z1=11 (obj 250K); most-tardy reaches z1=0 but
>   @z3=747 (obj 115K≈legacy); efficient floors z1=5 @z3=335 (obj 154K). **⇒ the wall is the REALIZE, not the
>   spill: box-decomp floors z1≈5-11 for z3≤335; z1=0 only at z3≈747.**
> - **★★★ best-of-N REALIZE (`_bestof_realize.py`) — DETERMINISTIC FLOOR, hypothesis FALSIFIED.** Re-running
>   box-decomp on the SAME snapshot gives IDENTICAL z1 (k28: z1=7 ×7/7; k34: z1=9 ×7/7; k36: z1=5 ×7/7; k31:
>   8 mostly). The ±noise I saw was ACROSS different assignments, NOT on one snapshot. **⇒ z1=5 @z3=335 is a
>   GENUINE HARD realize floor, not samplable to 0.** best-of-N does not help.
> - **★★★ DEFINITIVE VERDICT (prob_13, exhaustive): the REALIZE-DENSITY WALL is real, deterministic, and NOT
>   crackable with buildable methods.** Confirmed by: 3 spill strategies (cheapest-z3/most-tardy/efficient) all
>   floor at the SAME wall; best-of-N shows it's deterministic; legacy realize, box-decomp, spyrrow density, and
>   `_combine.py` all hit it. **Our realize needs z3≈747 for z1=0; competitor does z1=0 @z3=432.** Best we
>   achieve on prob_13 = ~legacy (113-115K); competitor's 71.8K is OUT OF REACH (needs a denser crane-safe
>   co-presence packer we cannot build — spyrrow's geometric density did NOT translate to schedulable z1=0).
>   ⇒ beating the competitor on the z3-heavy instances (prob_13/14/18/20) is INFEASIBLE with current/buildable
>   methods; we MATCH legacy (no regression, no win). The only unbuilt shots are the Phase-3 heavy levers
>   (LBBD/Gurobi joint MIP) — low odds, high effort, project has hit this wall repeatedly.
> - **⇒ HIGHEST-EV PIVOT (recommend): (1) set2 −1 HARDENING** — legacy times out on set2 (prob_25 183.7s,
>   prob_26 161.6s @TL120 → −1); the competitor itself has z1>0 on all set2, so a FEASIBLE solution scores well
>   and avoiding even ONE −1 is worth ~R/2, far more than the set1 ~0.3-0.4M gap. **(2) per-instance audit** for
>   any set1 instance where we're already near comp (winnable cheaply). The realize-density chase is a confirmed
>   dead end for buildable methods.
>
> ## ★★★ COMPETITOR REFERENCE CORRECTED 2026-06-15 PM (user-provided official all-40 scores)
> **NEW authoritative file: `notes/competitor-2026-06-15.json`** (all 40 + full breakdown: objective_official,
> objective_shipped, z1, z2, z3, z1_lb, congestion_tax, wall, rss). **SUPERSEDES competitor-2026-06-11.json**
> (set1-only, weaker/different numbers). Active harnesses (eval.py, _fstest.py, _spyrrow_pack.py) now point here.
> - **★ COMPETITOR set1 total (objective_official) = 931,465** — NOT the 1,139,442 we'd been chasing. Our
>   hybrid set1 = 1,312,961 ⇒ TRUE GAP = **−381,496 (−29%)** to beat the competitor. (Goal <1,000,000 is now
>   the *easier* bar; beating the competitor needs **<931,465**.) Competitor is z1=0 on ALL set1.
> - **★★ THE STRATEGIC INSIGHT (changes the ALNS objective): the competitor keeps z3 LOW by accepting HIGHER
>   z2.** prob_13: comp z2=2873 / **z3=432** vs OURS z2=1287 / **z3=805**. Solving the two obj equations gives
>   prob_13 **w2≈5, w3≈133 (w3/w2 ≈ 27)** — preference deviation is ~27× costlier than imbalance. ⇒ **our
>   solver OVER-BALANCES (over-spills to cut z2), paying huge z3; the right move is KEEP-IN-PREFERRED (low z3)
>   even at z2 cost.** This is EXACTLY what approaches A (z1=0→cut z3) and B (preferred→cut z1) target. The
>   reason we over-spill: the bbox-proxy z1 says "keeping more in preferred breaks z1=0" ⇒ accurate-z1 (H11)
>   should unlock keep-in-preferred at true z1=0. set1 per-instance z3 targets (comp): prob_3 100, prob_4 8,
>   prob_5 228, prob_6 287, prob_7 387, prob_9 367, prob_10 492, prob_11 146, prob_12 439, prob_13 432,
>   prob_14 419, prob_17 256, prob_18 143, prob_19 373, prob_20 515.
> - **★ set2 competitor data EXISTS NOW (first time).** Objectives are HUGE (902K–68.3M) and the competitor
>   itself has **z1>0** on all set2 (227–5977; z1==congestion_tax) — set2 is genuinely hard. ⇒ a feasible-but-
>   mediocre set2 solution still massively beats −1; **set2 −1 avoidance (TL-discipline) is the dominant set2
>   lever**, confirming the parallel-critical task. Our legacy times out (prob_25 183.7s, prob_26 161.6s @TL120).
>
> ## ★★★ PIVOT 2026-06-15 PM — OLD SOLVER RESTORED (the fresh-start was a REGRESSION)
> **User revealed: the OLD (pre-2026-06-14-reset) solver already hit set1 ≈ 1.5M. The fresh-start
> rebuild (box-decomp/feasspill) only reached ~5M — a 3× REGRESSION on set1.** Root cause (code-
> analyzer on `archive/old-solver-src-2026-06-14/`): the old solver realises z1=0 on 19/20 set1 via
> **DECOUPLING** — (1) a crane-aware greedy BL layout fixes POSITIONS (`fastfloor._fixed_time_decode`,
> order = release-asc+area-desc, BL keeps free space contiguous), then (2) a per-bay **CP-SAT TIMING
> ORACLE on the FIXED layout** (`myalgorithm._cpsat_bay_timing_verified:2596`) — positions frozen ⇒
> crane/footprint conflicts become time-INDEPENDENT booleans (via official check_entry/check_exit/
> check_collisions) ⇒ the NP-hard joint problem collapses to a clean **1-D disjunctive single-machine
> tardiness problem** CP-SAT solves to OPTIMUM per bay in ms. My box-decomp searched position+time
> JOINTLY (6-literal disjunction/pair) ⇒ combinatorial explosion on 40+ block bays ⇒ floors z1 at
> 100-190. **The decoupling IS the technique I lost.** (Naive re-graft of just the oracle onto my
> greedy FAILED — my conservative `_footprint_cells` over-estimates footprints ⇒ spurious conflicts;
> the oracle needs the EXACT official crane check + the `_fixed_time_decode` layout, both in the old
> solver.) ⇒ **RESTORED `archive/old-solver-src-2026-06-14/*.py` → `src/`** (utils.py kept official;
> fresh-start preserved at `notes/research/myalgorithm-freshstart-2026-06-15.py`). prob_20 confirmed
> 1.99M→**181,166 (z1=0)**. **★ FULL SET1 GATE CONFIRMED: total = 1,385,779 (z1=0 on 19/20, only
> prob_14 z1=2; 10/20 wins; feasible 20/20; 6.5× over fresh-start 9.03M).** Baseline
> `baselines/oldsolver_set1.json`.
> **GAP TO <1M (all z3-dominated now):** losses vs comp — prob_20 +90K (z3 1336 vs 463), prob_18 +65K
> (744 vs 172), prob_14 +45K (540 vs 384), prob_13 +37K (805 vs 435), prob_4 +29K (154 vs 8), prob_3
> +26K (407 vs 94), prob_17 +16K, prob_11 +14K, prob_6 +7K, prob_12 +2K. Σloss-excess ≈ 331K; win
> margins ≈ 85K ⇒ matching comp on losses → ~1.055M (STILL >1M) ⇒ **must BEAT comp on big-z3 losses**.
> ★ Lever attempt (FALSIFIED for <1M): targeted-spill + old fastfloor floor + `_cpsat_bay_timing_verified`
> oracle (`_combine.py`). The oracle re-times a FIXED layout but the LAYOUT sets the z1 floor; on
> prob_13 floor z1 plateaus ~53 at z3=138 and does NOT reach 0 even at z3=230 — z1=0 needs z3≈800
> (= the old solver's own ban-race result ~115K). So targeted-spill+old-decode CONVERGES to the old
> solver, doesn't beat it. The competitor realises z1=0 at z3=435 via a DENSER decode neither the old
> solver nor fresh-start can build (= the FALSIFIED polygon-nester lever, FRESH §4). **⇒ old solver
> 1.39M is the practical ceiling; <1M needs competitor-class packing density (unbuilt).**
> - **HYBRID CONFIRMED (`_hybridtest.py` @TL=200): box-decomp BEATS old on prob_3=52,450(z3=88) vs
>   76,630; prob_4=25,597(z3=52) vs 46,011; prob_18=74,454(z3=458) vs 105,596 — all z1=0, LOWER z3
>   (old solver OVER-spills on the LESS-congested instances). best-of(old,box-decomp) = 1,310,043.**
>   Box-decomp wins ONLY where it realises z1=0 (less-congested prob_3/4/18); loses on congested
>   prob_11/12/13/14/17/20 (floors z1 high) where old solver wins. SERVER-SAFE (old solver plateaus by
>   ~300s per old @300=@600 ⇒ split TL: old TL-100 + box 100s, no regression). Integration = wrap
>   algorithm() to run both + best-of; risk = editing the 400KB proven old solver. Still >1M.
> - **FINAL <1M verdict: infeasible with buildable/validatable methods.** Floor: 1.39M (old) / 1.31M
>   (hybrid). <1M needs competitor packing density (FALSIFIED polygon-nester) or server-only Gurobi
>   joint MIP (unvalidatable at scale, low odds — CP-SAT already > Gurobi for this packing). Decision
>   = user's: retarget feasible (<1.3M), authorize Gurobi gamble, or prioritise set2 −1 hardening. Old solver =
> **10/20 wins, z1=0 on 19/20, ceiling = z3 (losses 2-4× comp)**; SET2-FRAGILE (timeouts → −1, the
> reset's reason — must harden TL-discipline before any ALL40 submit). NEXT = confirm ~1.5M, then
> push z3 toward the user goal **set1 < 1M** (improve the old solver's z3 ceiling — its losses are
> z3-dominated; my targeted-spill-at-z1=0 idea may help, but the old "polygon nester" z3-lever was
> FALSIFIED). Old-solver flags/maps: `notes/SESSION-HANDOFF-2026-06-14-rebuild.md`,
> `notes/devlog/integration-map.md` + REFLECTIONS.md. The fresh-start cycles below (13-18) are now
> HISTORY — box-decomp/feasspill are inferior to the old decoupled solver on set1 EXCEPT prob_3/4/18.
>
> ### ★ HYBRID SHIPPED 2026-06-15 (active solver). `src/myalgorithm.py` algorithm() = best-of(
> `_legacy_algorithm` [old solver, renamed], `boxsolver.algorithm` [= box-decomp, `src/boxsolver.py`]).
> Gated `OGC_HYBRID` (default ON; =0 ⇒ exact legacy). box-decomp wins prob_3/4/18 (lower-z3 z1=0 where
> legacy over-spills); legacy wins the congested rest. Budget: legacy gets T−reserve (reserve=min(80,
> 0.3T) when T≥150); legacy PLATEAUS by ~140-300s (verified prob_13/20 legacy@140=@200; prob_14 −1584
> only) ⇒ server-TL = strictly better, no regression. Smoke OK. **FULL SET1 GATE CONFIRMED:
> total = 1,312,961** (`baselines/hybrid_set1.json`; old 1.385M → −72,818; improved prob_3/4/18,
> regressed prob_14 +2918 [local budget-split, 0 on server], feasible 20/20, 10 wins). NOTE: renamed
> algorithm()→_legacy_algorithm is SAFE (no internal callers; siblings import specific funcs not
> algorithm). boxsolver = copy of fresh-start (standalone, utils-only). **DELIVERABLE FLOOR: set1
> 1,312,961.** Goal <1M still UNMET (−313K gap = competitor packing density, falsified lever).
>
> **★ RESUME POINT / SESSION HANDOFF (READ THIS FIRST). Set 2026-06-15.**
>
> ### ★★★ NEW EXPLORATION 2026-06-15 PM — "BEAT THE COMPETITOR ON SET1, no matter what"
> User directive: research new methodologies thoroughly → secure 10+ breakthrough leads → verify/apply
> SEQUENTIALLY. Done: 3 web-researcher agents (nesting · packing+scheduling · shipyard-literature) →
> **13 ranked leads in `notes/NEXT-EXPLORATION-HANDOFF-2026-06-15.html`**. The wall = polygon DENSITY
> (z3): competitor packs 2-4× denser ⇒ less spill. KEY: crane j≥k is a LITERATURE GAP (only Caprace
> "crane-hook-height") = our differentiator. Sequential backlog (EV order): **(1) spyrrow/sparrow**
> [SOTA nester, pip, jagua-rs CDE — BIGGEST lever, verify eval-env install]; (2) Diagonal-Fill placement
> [Kwon&Lee, +TR-slide to greedy BL]; (3) NFP-BLF [pyclipper, polygon interlocking vs bbox]; (4) CP-SAT
> add_no_overlap_2d + energetic params [use_energetic/area_energetic/timetabling — retry z1 ceiling];
> (5) Raster-Penetration-Map FFT; (6) Jostle/ejection-chain; (7) GRASP/beam order; (8) LBBD [EJOR-2024
> structurally identical]; (9) GLS-STA 4D [Caprace +12.7%, crane-aware]; (10) Gurobi separation-line MIP
> [server]; (11) ALNS-density; (12) 15° polygon approx + GA; (13) 3D-sRCPSP cumulative. Gate each: set1↓
> · feasible · never −1 · gated flag · INSIGHTS log. **★ EXTERNAL LIBS APPROVED by user 2026-06-15**
> (spyrrow/pyclipper/etc OK to pip-install + bundle into the submission zip — verify Linux-x86_64-py3.12
> wheel works in eval env, bundle since eval has no internet, watch 15MB zip limit). ⚠ PARALLEL CRITICAL:
> legacy −1's on set2 (prob_25 183.7s, prob_26 161.6s @TL=120) — harden TL-discipline before ALL40 submit.
> Next-session kickoff prompt: `notes/NEXT-SESSION-PROMPT-2026-06-15.md`.
>
> ### ▶ SESSION LOG 2026-06-15 PM-2 (executing the kickoff: H0 reconfirm → H1 spyrrow)
> - **H0 RECONFIRMED (structural).** Both packers are pure Bottom-Left first-feasible, no
>   backtracking / no global density objective: `fastfloor._ft_search_pos:302` sorts candidates
>   `(Y,X)` asc and returns the first feasible (`:305`); `boxsolver._bl_fit_cells:118-123` iterates
>   `ys` then `xs` (lowest-row-first) and returns the first cell-disjoint placement;
>   `boxsolver._bl_fit:155-163` BL-sorts and returns first non-overlapping. ⇒ the density wall is
>   real, exactly as H0 claims. (Quantitative single-bay density baseline = `notes/research/_density_selftest.py`, pending shell.)
> - **H1 spyrrow PACKAGING GATE = GO** (web-researcher, sources in `NEXT-EXPLORATION-HANDOFF`):
>   spyrrow **0.9.0** publishes `spyrrow-0.9.0-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`
>   = **0.84 MB**, `requires_dist=null` (NO python deps), Rust statically linked (`.so`, runs offline)
>   ⇒ trivially bundlable ≤15MB. Cross-deploy: `pip download --platform manylinux_2_17_x86_64
>   --python-version 312 --only-binary=:all: spyrrow`.
> - **H1 spyrrow API caveats** (shape the integration): only `StripPackingInstance` is exposed
>   (height fixed → width minimized; no `BinPackingInstance`). Use `strip_height=bay.height`, feasible
>   iff `sol.width ≤ bay.width` — width-minimization IS our density lever. `allowed_orientations=[0,90,180,270]`
>   (discrete OK). `StripPackingConfig(total_computation_time=int_s, seed=, num_workers=)`. **FLOAT
>   output** → must `round()` + re-verify with official `check_feasibility`. Crane j≥k unknown to spyrrow
>   but co-present footprint-disjoint packing is crane-safe by construction (same invariant we already use).
>   ⚠ MISMATCH: our blocks carry a discrete `shape[]` orientation list (pre-transformed polygons), not a
>   single polygon + angle — for the self-test feed each block its footprint OUTLINE polygon (unary_union
>   of layer polys) with 4 rotations; in integration map spyrrow's rotation back to nearest `oi` + re-verify.
> - **★ H1 SINGLE-BAY DENSITY GATE PASSED DECISIVELY (`_density_selftest.py`, env py3.11, spyrrow 0.9.0
>   already installed).** Metric = min strip WIDTH to pack a bay's preferred-member set at bay HEIGHT
>   (lower=denser, apples-to-apples; both packers free to choose orientations). spyrrow vs BL greedy:
>   prob_13 bays 1/3/2: 524/399/475 vs 1038/924/959 (**+49/57/50% denser**); prob_14: 390/354/449 vs
>   1087/891/940 (**+64/60/52%**); prob_20: 232/448/251 vs 768/968/781 (**+68/54/68%**). spyrrow
>   utilization 0.71–0.82. ⇒ **spyrrow packs ~2–3× denser than the BL greedy everywhere** — H0 wall +
>   H1 lever both confirmed quantitatively. (eval py3.12 → bundle cp312 wheel, NOT the local cp311.)
> - **⚠ MAGNITUDE CAVEAT (the real question the mini-gate must answer):** the preferred bays are 5–8×
>   AREA over-subscribed (prob_20 bay1 foot 6989 vs bay area 32×29=928). Even at spyrrow's 2–3× density
>   you CANNOT make all members co-present ⇒ heavy time-sharing remains. The win is INDIRECT: denser ⇒
>   more blocks co-present per slot ⇒ less serialization (z1) AND fewer blocks must SPILL to non-preferred
>   bays (z3). Whether 2–3× density yields enough to beat comp on OBJ is the mini-gate's job (single-bay
>   density ≠ obj). Integration challenge (handoff-flagged): spyrrow is STATIC strip packing → need
>   time-slot decoupling. Planned integration = the OLD SOLVER'S decoupling but with a DENSER layout:
>   FFD-group members into WxH-feasible co-present groups via spyrrow (bin-feasible iff strip-width ≤ Wbay),
>   give every block a fixed (x,y), then a TIMING ORACLE schedules (within-group footprints disjoint ⇒
>   co-present; cross-group overlap ⇒ time-disjoint). Prototype = `notes/research/_spyrrow_pack.py`.
> - **★ MINI-GATE ATTEMPT 1 (FFD-groups + greedy oracle) — REGRESSED, instructive.** prob_13 @preferred:
>   obj **136,069,284** (z1=7311!, z2=6886, **z3=103**) vs hybrid 113,500. z3 is GREAT (preferred kept,
>   103 vs hybrid 805) but z1 EXPLODED. Root cause: FFD packed each group from x=0 ⇒ groups STACK at
>   identical bay positions ⇒ overlap graph ≈ COMPLETE ⇒ oracle serializes ~all 69 blocks ⇒ z1 huge. The
>   density advantage is DESTROYED by independent-group stacking. (`min_items_separation=1.0` also caused
>   "item does not fit" Rust panics for height≈H blocks ⇒ BL fallback.) **LEARNING: the layout must give
>   blocks DIVERSE bay positions, and co-present detection must be EXACT-polygon (conservative cell-cover
>   counts touching as overlap ⇒ false serialization).** ⇒ redesign: ONE spyrrow strip per bay (all
>   members), slice into W-wide columns (`bay_x = sx mod W`) ⇒ diverse positions; exact-polygon overlap
>   graph; then timing oracle (greedy → CP-SAT). NOTE confirming the strategy: prob_13 is already z1=0 in
>   the hybrid; its gap is z3 (805 vs comp 435) ⇒ the lever must realize z1≈0 at LOWER z3 than 805, NOT
>   reduce z1. Pure-preferred gave z3=103 but couldn't realize z1=0 (the realize gap, exactly).
> - **★ MINI-GATE ATTEMPT 2 (1-strip + mod-W + exact-overlap, greedy oracle): still REGRESSED.** prob_13
>   @preferred obj 120,180,614 (z1=6457, z3=103); @capped(any α) obj 42,913,805 (z1=2241, z2=1807,
>   **z3=9105**). Two decisive learnings: (1) **the dominant lever is the ASSIGNMENT/SPILL, not packing** —
>   prob_13 bay-1 is 5× area-over-subscribed at preferred ⇒ z1=0 is UNREACHABLE without spill regardless
>   of packing density (hybrid spills to z3=805 for z1=0; comp to z3=435). Pure-preferred gives z3=103 but
>   un-realizable z1. `_assign_capped` uses area-TIME demand ⇒ spills maximally for all α≤1 (all identical).
>   (2) **the greedy EDD oracle is too weak** — floors z1 at thousands even with spill; the hybrid gets z1=0
>   only via a CP-SAT timing oracle. ⇒ Cannot test "does spyrrow density reach z1=0 at z3<805" without the
>   CP-SAT oracle. **BUILT `schedule_cpsat` (disjunctive: exact-overlapping placed footprints time-disjoint,
>   minimise Σtardiness) in `_spyrrow_pack.py` (ORACLE=cpsat, default).** ⚠ UNRUN — blocked by a sustained
>   Bash-safety-classifier infra outage (opus-4-8[1m] unavailable; read/Write OK, shell intermittently dead).
> - **★ RESUME COMMAND (run when shell recovers) — the make-or-break H1 test:**
>   `BAY_TL=5 ORACLE=cpsat CPSAT_TL=10 CPW=4 ASSIGN=preferred FS_TL=400 <envpy> notes/research/_spyrrow_pack.py prob_13`
>   then sweep ASSIGN/spill to find the z1≈0 frontier and read off z3. **DECISION RULE:** if spyrrow+CP-SAT
>   realizes z1=0 at z3 < 805 (hybrid) on prob_13 → H1 lever WORKS, integrate into boxsolver as a new packer
>   mode (rely on its assignment best-of + obj-gate). If z1=0 needs z3 ≥ 805 → density does NOT reduce
>   required spill ⇒ H1 packing-density lever does NOT beat comp on its own ⇒ pivot to H2/H7 then the
>   assignment-side levers (H11 ALNS-density / reassign with accurate-z1). NOTE the real integration likely
>   must co-optimize assignment+packing+timing (the realize gap), so even a positive prob_13 signal means
>   integrating spyrrow as a packer INSIDE boxsolver's existing assignment best-of, not the standalone.
> - Files: `notes/research/_density_selftest.py` (H1 density, PASSED), `notes/research/_spyrrow_pack.py`
>   (integration prototype: spyrrow 1-strip layout + mod-W slice + exact-overlap + greedy|cpsat oracle).
> - **★★★ H1 MINI-GATE VERDICT 2026-06-15 PM: FAILED (natural integration) — density ≠ schedulability.**
>   prob_13 full results (hybrid ref = obj 113,500, z1=0, z3=805; comp 76,685, z1=0, z3=435):
>   | assign | oracle | obj | z1 | z2 | z3 |
>   |---|---|---|---|---|---|
>   | preferred | greedy | 120,180,614 | 6457 | 6886 | 103 |
>   | preferred | CP-SAT | 29,220,769 | 1568 | 6886 | 103 |
>   | balanced | CP-SAT | 22,355,280 | **1136** | 1807 | 9105 |
>   The CP-SAT oracle cut z1 ~4× over greedy but **NEVER reaches z1=0**, even at balanced (z3=9105, heavy
>   spill). The existing solver reaches z1=0 at z3=805. ⇒ **spyrrow-as-static-dense-layout + decoupled
>   timing is strictly WORSE than the existing tardiness-aware online packer.** ROOT CAUSE (the key
>   insight): spyrrow minimizes WIDTH/density, NOT tardiness; a density-optimal static layout produces a
>   tardiness-HOSTILE footprint-overlap graph (urgent blocks forced to share positions ⇒ serialize), so no
>   timing oracle can recover z1=0. The single-bay 2-3× density (REAL, `_density_selftest`) does NOT
>   translate because (a) bays are 5× over-subscribed so density gain is swamped, (b) density ≠
>   schedulability. This is the SAME class of falsified lever as the old "polygon-nester" (FRESH §4) and
>   finer-raster/exact-box (CLAUDE.md falsified list). **⇒ H1 (spyrrow dense packing as a drop-in) does
>   NOT beat the competitor.** NOT-yet-tried (would be high-effort, uncertain): interleave spyrrow density
>   WITH scheduling per time-wave (pack only the EDD-urgent co-present set each wave), i.e. make the layout
>   tardiness-aware — but that is a full packer rebuild, and the project history says density levers keep
>   failing for the same reason. RECOMMEND: pivot to H2/H7 (cheap BL augmentation) + the ASSIGNMENT-side
>   levers (H11 ALNS-density / reassign with accurate-z1 = the realize-gap frontier the project keeps
>   circling), OR prioritize the set2 −1 hardening (higher real-score value than set1 0.17M). Decision = user's.
>
> ### 🎯 THE GOAL (user-set 2026-06-15, Stop-hook enforced)
> **set1 total objective < 1,000,000** (from c12's 9,033,067 — a 9× cut, BELOW competitor's 1,139,442).
> - **★ CYCLE 18 BREAKTHROUGH (the active lever): `_solve_feasspill` (`OGC_FEASSPILL`, default OFF).**
>   Targeted spill (cheapest-z3 block from most-tardy bay, bbox-guided trajectory) + box-decomp+
>   cumulative+4-worker realize on snapshots, keep best obj. **prob_13 @TL=400: 1.69M→252K (6.7×),
>   wall 302s (never −1).** Needs server-class TL (minutes); @TL=150 starved. Validated single-instance;
>   full-set1 gate pending. Est set1 with feasspill ≈ 2–2.5M (from 9M) — MAJOR, but <1M needs the
>   z1≈8→0 LAST MILE (our greedy trajectory bottoms at z1≈8-11 @z3~150-200; comp's z1=0 @z3=435 is a
>   different assignment we don't reach; z1=0-feasibility is UNSAT even at the sweet spot).
> - Loop: hypothesis → implement → verify (full set1 obj, never −1, wall≤TL) → feedback → accumulate.
> - Helpers: env python directly (`C:/Users/peter/anaconda3/envs/ogc2025/python.exe`) — `conda run`
>   CRASHES with 4-worker CP-SAT. `_fstest.py` (integrated runner), `_feasspill.py`/`_spillcurve.py`
>   (prototypes). Key envs: `OGC_FEASSPILL` `OGC_BOXDECOMP` `OGC_BD_CUMUL`(on) `OGC_BD_WORKERS`
>   `OGC_FEASSPILL_EVERY`/`_STEPS`/`_MARGIN`. Keep `OGC_BD_Z1ZERO` OFF (hurts).
>
> ### ★★ THE KEY REFRAME (this changes the strategy — do NOT just chase z1)
> **z1=0 alone is NOT enough.** If every set1 z1 were 0, our set1 total would still be **5,695,453
> ≈ 5× the competitor's 1,139,442.** The gap is concentrated and is z2+z3, not only z1:
> - **5 instances = 85% of our set1 total**: prob_14 (2.12M), prob_20 (1.99M), prob_13 (1.69M),
>   prob_12 (1.34M), prob_11 (0.57M).
> - **prob_12/13/14/20**: even at z1=0 they carry **~1.0–1.4M EACH of w2·z2 + w3·z3** (massive
>   preference/imbalance spill) vs the competitor's total ~67–94K. ⇒ their winning solution is a
>   z1=0-feasible NEAR-PREFERRED (low-z3) assignment we are NOT finding — we either keep preferred
>   (z1 explodes) or spill to balanced (z3 explodes). **THE realize gap, hardest cases.**
> - **prob_11**: still z1-bound (z1=24 × w1 22,857 = 549K of its 569K) — needs z1→0 too.
> - The other 15 set1 instances are already small (≤205K, within +4–85% of comp) — NOT the priority.
> ⇒ **PRIMARY TARGET = realize z1≈0 AT z3≈0 (near-preferred) on prob_11/12/13/14/20.** Per-instance
>   target obj (to roughly match comp): prob_14≤67K, prob_20≤91K, prob_13≤77K, prob_12≤94K,
>   prob_11≤32K. Full per-instance table: `notes/research/_alldata.json` + the
>   `objective-breakdown-2026-06-15.html` / `competitor-compare-2026-06-14.html` reports.
>
> ### Current best = c12 (`notes/research/baselines/c12.json`)
> ALL40 obj **326M**, set1 total **9.03M**, set1 wins **3** (prob_1/2/8), feasible 40/40, never −1.
> Chain v0→h1→h2→h3→h6→c8→c11→**c12**. Solver (`src/myalgorithm.py`): base 4-core `spawn` pool of
> greedy specs {preferred,capped,balanced}×{bbox,cells} + CP-SAT packing-by-scheduling
> (`_pack_bay_cpsat`, `OGC_CPSAT=1`); then **PHASE 2** = `_solve_reassign` (z3-aware reassignment
> LS: preferred start, dual-pass moves+2-opt-swaps, cpsat-final, budget base 0.65 / reassign→0.93,
> `OGC_REASSIGN=1`, solo post-pool ⇒ additive, never starves base). Obj-gated best-of + serialised
> fallback ⇒ never −1. `_FP_CACHE`/`_LAYER_CACHE` cleared per `algorithm()` call (block_id keys
> collide across instances — DON'T regress). `OGC_CRANE=0` (falsified), `OGC_PHASEB=0` (no payoff).
>
> ### HYPOTHESIS BACKLOG for the goal (pull top each loop; all must keep z1=0 AND low z3)
> 1. **✅ WHY-analysis DONE (2026-06-15, §4) — verdict: the lever is PACKING, not assignment.**
>    Energetic LB (`_whyhard.py`) ⇒ z1=0 at (near-)preferred is area-feasible (forced spill ≤39 z3);
>    packer ceiling (`_prefpack.py`) ⇒ our best packer floors z1 at 76–1411 there. The whole set1
>    gap is a per-bay REALIZE gap. ⇒ **NEXT BUILD = a stronger crane-safe co-presence packer/
>    scheduler that realises z1≈0 at (near-)preferred** (items #3 and/or #2 below). #4 demoted.
>    Cheapest first win: prob_11 (z3 116<comp 167 already) ⇒ pure z1→0 ⇒ ~20.5K < comp 31.9K.
> 2. **Accurate-z1 in the reassign loop** (current search uses FAST bbox proxy → misleads the
>    z1↔z2↔z3 frontier, esp. for swaps/phase-B). Use cells/cpsat tardiness for move eval on the
>    5 target instances (cache per-bay; budget OK since server TL is minutes). Likely unlocks the
>    low-z3 z1=0 points the bbox proxy hides.
> 3. **~~Box-DECOMPOSITION CP-SAT~~ DONE 2026-06-15 (cycle 13, §4) — MARGINAL, gated OFF.** K=2
>    beats single-bbox cpsat z1 ~15–20% but does NOT crack z1→0 (CP-SAT pairwise-disjunctive ceiling
>    ≫ energetic-feasible 0); K=3 backfires. Built (`OGC_BOXDECOMP`), un-validated at server long-TL.
>    ⇒ realise gap is deeper than geometry tightness. **Elevate #2/#4 or a NON-CP-SAT realise method.**
> 4. **SA / accept-worse** over assignment to escape the first-improvement local optima the greedy
>    reassign is stuck in (the 5 are local-optimum-trapped).
> 5. **LBBD** [S36]: MIP master (assign + schedule, z2/z3 closed-form) + CP subproblem (crane-
>    feasible 2D pack) with no-good cuts — the exact-ish attack on the realize gap. Heaviest.
> 6. **Determinize cpsat** (max_deterministic_time / best-of-N) — kills the ±130K noise that makes
>    single-run gates unreliable (needed to trust set1-total measurements).
>
> ### Measurement protocol
> `conda run -n ogc2025 python notes/research/eval.py --set SET1 --tl 120 --vs c12 --save <new>`
> (use **--tl ≥ 120** — reassign needs budget; tl=60 starves it to ~4s). Isolated full-budget probe:
> `notes/research/_reassign2.py <probs...>`. Diff/analysis helpers: `_diff.py`, `_compare.py`,
> `_alldata.py`. ⚠ cpsat noise ±130K → confirm "regressions" with a base-only (`OGC_REASSIGN=0`)
> re-run before trusting them (reassign is provably additive). NEVER touch `src/utils.py`/`baseline/`;
> `algorithm(prob_info, timelimit)` signature fixed. FALSIFIED (don't redo): crane-overlap (§4),
> richer BL candidates (cyc7), alpha-spill to z1=0 (explodes z3), phase-B bbox-proxy polish.

- **CYCLE 1 / H1 SHIPPED** (`src/myalgorithm.py`): most-preferred-bay assignment (z3≈0)
  + per-bay **time-extended 2D bbox packing** (co-present blocks bbox-disjoint ⇒ crane-safe
  by construction) + serialised fallback. **ALL40 feasible 40/40, total obj 32.13B→1.38B
  (−95.7%), 40/40 improved vs v0, ≤2.6s.** Baselines: `baselines/v0.json`, `baselines/h1.json`.
- **CYCLE 3 SHIPPED** (best-of {preferred, balanced} assignment, obj-gated): **total obj
  1.257B→386M (−69%)**, feasible 40/40, regress 0, wins still 2. Baseline `baselines/h3.json`.
  Balanced spreads area-time load → cuts congestion z1 (×huge w1) hugely. BUT no new set1 win:
  competitor achieves z1=0 AND low z3 simultaneously; we get either preferred(z3≈0,z1>0) or
  balanced(z1=0,z3 high) — each big on one axis. **To win set1: realize the PREFERRED (z3≈0)
  assignment at z1=0** ⇒ obj≈z2 (tiny) ⇒ WIN. That needs DENSER co-presence packing → CYCLE 4
  = footprint(polygon)-cell-disjoint packing (the `_footprint_cells`/`_bl_fit_cells` already in
  src, dormant). Watch speed (balanced `_fits_all` Shapely-heavy: prob_40 22s).
- ~~CYCLE 2 / H3 SHIPPED~~: per-bay best-of 5 orderings (EDD/slack/release/proc/area), keep
  lowest-tardiness packing. **total obj 1.38B→1.257B (−9%), 38/40 improved, regress 0, wins
  0→2** (prob_2, prob_8). Baseline `baselines/h2.json`. Cost: ≤15s (5×pack on big bays).
- **★ THE binding lever is now pinned: residual z1 = the ENTIRE set1 gap.** z2≈small, z3≈0
  already; every set1 loss is purely z1·w1 (e.g. prob_11 z1=108×22857=2.47M = its whole obj;
  prob_1 z1=2; prob_3 z1=40). The 2 wins are exactly the z1=0 instances. **Drive residual z1→0
  ⇒ win ~all of set1** (old solver hit z1=0 on 19/20, so it's achievable). z1 source: bbox-
  disjoint co-presence is CONSERVATIVE (loose bbox for irregular polygons wastes space →
  blocks delay) + greedy no-backtrack. Next: denser/crane-aware co-presence (footprint- not
  bbox-disjoint; or admit crane-safe overlap via official check_entry/exit) and/or a per-bay
  CP-SAT "packing-by-scheduling" model [S13,S31,S33] to find z1=0 layouts greedy misses.
  Weight-adaptive: low-w1 set2 (prob_25/36/40, w1=667) tolerate residual z1 — spend effort
  where w1 is large.

---

## 1. Source library (target ≥ 50; accumulating)

**74 sources harvested 2026-06-14 → full list in `notes/research/sources.md`** (grouped A–J,
each rated direct/adapt/ref). Deep-research academic pass was rate-limited mid-verification
(its "all refuted" is a fetch-failure artifact, NOT genuine refutation — claims = candidate
directions). Most actionable: [S11] wsgisler blocking-JS CP-SAT (direct), [S31] cpsat-primer
packing+rotation (direct), [S33] or-tools flexible_job_shop (direct), [S34] PyJobShop (direct),
[S51] N-Wouda/ALNS (direct), [S65] spyrrow nesting (direct), [S36] EJOR-2024 LBBD (structurally
identical to OGC), [S01] He 2024 (closest = likely competitor method), [S63] ATC dispatch.

---

## 2. Distilled methods & techniques (convergent across sources)

1. **Two-phase decomposition (assign+time-window → 2D place) is THE shipyard-SSP architecture**
   and matches the competitor's fast-near-optimal profile [S01 He 2024, S02 Kwon&Lee, S03 Park
   1996, S07]. Phase-1 fixes z2/z3 (closed-form on assignment) + the schedule (z1); phase-2
   realizes 2D positions crane-safely. → OUR v0 already does a degenerate version (assign +
   serialize); the lever is a better phase-1 schedule (co-presence) + phase-2 placement.
2. **The crane j≥k constraint == "a resource is HELD until the successor starts" (blocking job
   shop) / non-crossing / packing-as-scheduling** — and it is CP-SAT-encodable, not just a
   geometric afterthought [S11 wsgisler DIRECT CP-SAT code: `start_next==end_curr`+NoOverlap;
   S13 Luo "Packing by Scheduling" NoOverlap1D-via-cumulative; S12 Mascis alternative-graph;
   S17/S27/S30 non-crossing MIP]. Container-relocation B&B [S20-22] and aircraft-hangar
   exit-blocking MILP [S14] are the exact stacking/egress analogs.
3. **LBBD / branch-and-check is the proven exact-ish decomposition for "assign+schedule (master)
   + 2D-pack-feasibility (CP subproblem)"** and one paper [S36 EJOR 2024, additive manufacturing]
   solves a STRUCTURALLY IDENTICAL problem (irregular 2D batch packing + machine schedule +
   release/processing/tardiness). Blueprint: Hooker [S43], branch-and-check via lazy callbacks
   [S44,S45], parallel-machine+location LBBD [S46], local-branching Benders cut [S48].
4. **ALNS is the metaheuristic of record and has a direct Python lib** [S51 N-Wouda, 632★]:
   destroy (worst / Shaw-relatedness / segment) + repair (greedy / k-regret), pluggable
   acceptance (SA, late-acceptance, record-to-record). Berth allocation [S58] is the closest
   domain (assign + entry/exit times). Operators: worst-removal (highest obj contributor),
   Shaw-removal (temporally/spatially related blocks → attacks crane clustering).
5. **ATC apparent-tardiness-cost index orders construction by weighted-tardiness urgency** and
   is naturally WEIGHT-ADAPTIVE (uses wj, pj, slack, a κ scale) [S63 Vepsalainen&Morton; S64
   modified ATCR for mixed costs]. Use for sequencing within/across bays.
6. **Geometry**: SOTA nesting is callable from Python via spyrrow [S65]; pure-Python NFP exists
   [S69]; CP-SAT 2D no-overlap with rotation is a direct primitive [S31,S32]. But the OLD
   raster-density levers were FALSIFIED — density is NOT the binding constraint; co-presence
   SCHEDULING is. Treat geometry as a feasibility oracle, not the optimizer.

**Portability verdict**: build the optimizer in CP-SAT (crane-as-scheduling) + ALNS (assignment
search), use the official utils geometry as the crane-feasibility oracle. All Python, all
local-validatable. Defer Rust/RL/GPU items [S65 optional, S73].

---

## 3. Hypothesis backlog (prioritised — pull top TODO each loop)

| ID | hypothesis | source | expected | cost | status |
|----|-----------|--------|----------|------|--------|
| **H1** | Greedy CO-PRESENCE decode (bbox-disjoint over time). Collapses z1 vs serialised floor. | foundation | huge z1↓ | low | **KEPT (cyc1, −95.7%)** |
| **H2** | Per-bay CP-SAT "packing-by-scheduling": positions + entry times, co-presence = 3D(x,y,time)-no-overlap, min Σ tardiness → reach z1=0 layouts greedy misses | S11,S13,S31,S33 | z1→0 | med | **KEPT (cycle 8, −2.88% obj, +1 win, regress 0)** |
| **H9** | **Crane-OVERLAP co-presence: admit footprint overlap where the layer-aware j≥k descent column is clear (official check_entry/exit), beyond bbox/footprint-disjoint** | utils,FRESH§4 | **z1→0 on hard set1** | high | **TODO (cycle 9, TOP — the differentiated lever)** |
| **H7b** | Denser co-presence: footprint(polygon)-cell-disjoint not bbox-disjoint | S65,utils | z1↓ | med | **KEPT (cycle 4–6, cells)** |
| H3 | best-of orderings (EDD/slack/release/proc/area) — order-sensitive packing | foundation | z1↓ | low | **KEPT (cyc2, wins 0→2)** |
| H4 | z3-aware reassignment LS (move tardy-bay blocks to cheapest-z3 alt, obj-gated, phase 2) | S51,S56,S58 | obj↓ main | med | **KEPT (cycle 10, −2.58%, set1 −1M×4)** |
| H5 | LBBD: MIP master assigns+schedules (z2/z3 closed-form + tardiness), CP subproblem checks crane-feasible 2D pack, no-good cuts | S36,S43,S46 | obj↓ ceiling | high | TODO |
| H6 | Weight-adaptive z1↔z3: low-w1 (e.g. prob_25/36/40 w1=667) ACCEPT z1>0 to cut z3; high-w1 force z1→0 | weights §3 | obj↓ set2 | low | TODO |
| H7 | Dense per-bay placement (spyrrow/NFP/CP-SAT no-overlap) to admit more co-presence | S65,S31,S69 | z1↓ enabler | med | TODO |
| H8 | Virtual super-blocks: agglomerate time-space-close blocks before scheduling | S04 | scale | med | TODO |

---

## 4. Experiment log (hypothesis → result → verdict)

> Append-only. Each: date, hypothesis ID, change summary, command, full-set result
> (obj/feasible/wins-vs-competitor), verdict + reason.

### 2026-06-14 · Cycle 1 · H1 — per-bay time-extended bbox co-presence packing · **KEPT**
- Change: replace v0 serialisation with greedy time-extended 2D packing where co-present
  blocks have disjoint bboxes (⇒ disjoint footprints ⇒ no same-layer collision and no crane
  j≥k descent-blocking ⇒ feasible by construction). EDD order; enter at release if a BL-free
  slot exists among co-present blocks, else at earliest co-present exit, else serialise tail.
  Kept only if feasible AND obj ≤ serialised fallback.
- Cmd: `python notes/research/eval.py --set ALL40 --tl 10 --vs v0 --save h1`
- Result: **feasible 40/40, total_obj 32.13B→1.38B (−95.7%), improved 40/40, regressed 0,
  ≤2.6s/inst, wins-vs-competitor 0/20.**
- Verdict: KEPT (huge foundational z1 collapse, zero regression, never −1). Insight: bbox-
  disjoint co-presence is the cheap sound way to break serialisation; the residual z1 (not 0)
  is now the binding obj term because w1 is huge. Next: cut residual z1.

### 2026-06-14 · Cycle 4–6 · cells + α-sweep + 4-core parallel
- **Footprint-cell co-presence packing** (`_footprint_cells`/`_bl_fit_cells`): co-present blocks
  cell-disjoint (Shapely-rasterised footprint, prepared-geom) ⇒ crane-safe, denser than bbox.
  Two-phase: fast bbox best-of-orders ALWAYS + dense cell refine on the 2 lowest-z3 assignments.
  α-sweep assignment spectrum {preferred, capped(1.0), balanced}.
- **★ BUG FOUND+FIXED**: `_footprint_cells` cache keyed by (block_id, oi) — block_id is the
  per-instance index, so it COLLIDED across instances when eval runs 40 in one process
  (prob_1's block5 cells reused for prob_11's block5 → wrong footprint → check rejects → cells
  silently no-op → h5==h3). Fixed: module `_FP_CACHE` cleared per `algorithm()` call. (Same
  cross-instance contamination class as the old capture-harness poisoning.) Lesson: ALWAYS
  test multi-instance-in-one-process, not just standalone.
- **★ 4-CORE PARALLEL** (user asked — we were single-threaded, wasting 3 of 4 eval cores): the
  candidate spectrum (5 specs = 3 assignments × bbox + 2 lowest-z3 × cells) now evaluated across
  a `spawn` Pool(4) via `_solve_spec`/`_winit`; obj-gated best-of; monotonic-timestamp deadline
  (QPC system-wide → cross-process). `OGC_PARALLEL=0` disables (seq fallback on any pool error).
  Compatible with `_capture20_aff.py` (each instance pinned 4 cores → pool uses them) AND the
  eval server (1 instance, 4 cores).
- **h6 RESULT (new best baseline `baselines/h6.json`): total obj 386M→353M (−8.5%) vs h3,
  feasible 40/40, improved 32/40, regress 0, set1 wins 2, max wall 44s.** Cells now actually fire
  (cache fixed). Wins still 2: residual z1 on set1 (prob_11 z1=94, needs ≲1 to win @22857/unit;
  prob_16 z1=87) blocks more wins — cells cut z1 but not to ~0. NEXT: crack residual z1→~0 via
  richer cell BL candidates (all-4-side extreme points + gaps), temporal staggering, or per-bay
  CP-SAT "packing-by-scheduling" [S13,S31,S34] (the high-ceiling lever).

### 2026-06-14 · Cycle 11 · reassign + 2-opt swaps + cpsat-final · **KEPT → c12**
- Changes to `_solve_reassign`: (1) **2-opt SWAPS** (b1 in tardy bay ↔ b2 elsewhere, each fits
  the other's bay) added to the move set — relieve congestion at LOWER z3 than one-way spill,
  ranked by Δz3. (2) **DUAL-PASS**: run moves-only AND moves+swaps, final-pack each, keep best
  TRUE obj (the fast bbox search-proxy misleads the aggressive swap pass → swaps alone regressed
  some; dual-pass makes them never-worse-than-move-only, capturing wins like prob_3 z3 446→88).
  (3) **cpsat-FINAL**: final pack = best of cells AND cpsat on the reassigned assignment (cpsat
  global timing squeezes residual z1). (4) Budget rebalanced base 0.65 / reassign→0.93 (reassign
  is now heavy ~20-30s; needs a real share — server long-TL gives it plenty).
- Gate c12 @tl=120 vs c8: total 343M→**326M (−5.01%), improved 25/40, REGRESSED 0**, feasible
  40/40. z1=0 on ~half set1; prob_3/10 within +4% of competitor (z1=0). set1 wins still 3 (gap
  now z2/z3 micro, not z1). Stubborn prob_11/12/13/14/20 keep residual z1 (congested).
- Verdict: KEPT. FLIP ATTEMPT (z2 polish, "Phase B"): added a z1=0-preserving z2/z3 descent
  (`OGC_PHASEB`, default OFF) — **FAILED to flip prob_3/10**: at z1=0 (mandatory, w1=26,667) NO
  single move/swap lowers obj while keeping z1=0 (every z2-reducing move breaks z1=0 under the
  bbox proxy). The +4% gap is a genuine **z1↔z2 Pareto point** the competitor sits marginally
  better on — closing it needs ACCURATE-z1 (cells-in-loop, slow) or SA, high-effort/uncertain
  (~+2 wins max). Remaining real levers: determinize cpsat (noise); the congested 5
  (prob_11/12/13/14/20) need a stronger per-bay z1 engine (far, +1000%+, unlikely flips).

### 2026-06-14 · Cycle 10 · H4 — z3-aware reassignment local search · **KEPT (PHASE 2)**
- Change: `_solve_reassign` — start at preferred (z3≈0); repeatedly relieve a tardy bay by
  moving ONE block to its cheapest-z3 alternative fitting bay (free z3=0 moves first), accept
  only obj-lowering moves (first-improvement → monotone). Move eval re-packs ONLY the 2 affected
  bays (fast 1-order bbox, cached by membership) + closed-form z2/z3 ⇒ hundreds of moves fit
  budget; winning assignment then packed with full CELLS + check_feasibility.
- ARCHITECTURE FIX: first attempt ran reassign as a POOL spec → 5 set2 regressions from CPU
  STARVATION (reassign+cpsat overran 4 cores → timeout cut base specs). Fix = run reassign SOLO
  in the MAIN process as PHASE 2 AFTER the base pool (base keeps full 0.85 budget = byte-identical
  to c8 ⇒ no base change), reassign uses slack 0.85→0.92·TL, obj-gated. Provably additive.
- Isolated (full budget, `_reassign2.py`): prob_3 123,671→75,360 (**z1=0**), prob_9 518K→256K,
  prob_11 1.41M→798K (z3→116≈comp), prob_15 1.13M→117K, prob_16 470K→86K. Huge z1↓ at LOW z3.
- Gate c11 vs c8 @tl=60: total 343M→334M (−2.58%), feasible 40/40, 12 improved (set1
  prob_15/17/18/19 each ≈−1M). 3 apparent regressions (prob_24/35/36) PROVEN = cpsat variance
  (base-only reproduces them; reassign additive). Verdict: KEPT → c11 best. set1 wins still 3 at
  tl=60 (only ~4s reassign slack locally; flips expected on the server's long TL).
- NEXT: (i) determinize cpsat (kill ±130K noise); (ii) reassign→cpsat final pack (squeeze z1→0
  on the found assignment); (iii) give reassign more budget / 2-opt swaps to flip set1 wins.

### 2026-06-14 · Cycle 9 · H9 — crane-OVERLAP co-presence (official j≥k) · **FALSIFIED**
- Hypothesis: bbox/cells-disjoint is conservative; the true j≥k rule lets a block's
  UPPER layers OVERHANG others' lower layers ⇒ denser ⇒ lower z1. Diagnostic CONFIRMED
  overhang exists (`_overhang.py`: 11–28% of set1 multi-layer blocks have >1% upper-layer
  overhang). Built `_layer_cells`/`_bl_fit_crane`/`_pack_one_crane` (per-layer j≥k entry
  rule) + `_bay_crane_ok` (official check_entry/check_exit validator) + cells fallback.
- Result (`_cranetest.py`, preferred assignment, cells vs crane): **z1 IDENTICAL** on all 6
  z1-bound instances (prob_3=30, 4=18, 9=57, 11=94, 15=141, 16=87 — crane == cells), 2–4×
  slower. Adding base-box candidates didn't change it.
- Verdict: FALSIFIED. WHY: the BINDING constraint is **base-disjoint** — a block's layer-0
  must clear every co-present block's FULL footprint (j≥0 covers all of A's layers). Overhang
  only frees UPPER layers, which aren't binding. So crane-safe co-presence ≈ cells (full-FP-
  disjoint) in practice. `OGC_CRANE=0` default (code kept, opt-in). Geometry density is NOT
  the z1 lever (re-confirms FRESH §4 "density not binding"; crane serialisation is).

### 2026-06-14 · DIAGNOSTIC · the realize gap is PACKING/SCHEDULING, not assignment · **KEY**
- Competitor (set1 table) has **z1=0 on ALL 20** at **tiny z3 (94–473)**. We win exactly the
  3 where we also hit z1=0∧z3≈0 (prob_1/2/8). 6 z1-bound losses (prob_3/4/9/11/15/16, z3≈0)
  + 11 z3-bound (our z3 5K–12K vs comp ~200–470).
- α-sweep (`_alphasweep.py`, capped α∈{∞..0.8}, cells): our spill reaches z1=0 ONLY by
  exploding z3 (prob_16: z1=0 but z3=9,759 vs comp 232; prob_11 NEVER reaches z1=0, floors at
  z1=20 @ z3=7,183). ⇒ **no assignment in our spectrum hits the competitor regime (z1=0 ∧
  z3≤~240).** Winning the z1-bound losses REQUIRES z1≈0 on the NEAR-preferred assignment via
  PACKING ALONE — but cells floors prob_11 at z1=94, cpsat-bbox at 61 (TL-insensitive ⇒
  structural). The competitor packs a near-preferred bay to z1=0 where we can't.
- Reassignment LS prototype (`_reassign.py`, z3-aware, 1 move/min slow): one z3=0-cost move
  drops prob_11 z1 94→75, prob_16 87→69, prob_15 141→95 — DIRECTION works (free/cheap moves
  relieve congestion) but needs a FAST per-bay-incremental engine to run to convergence.
- ⇒ Two live levers for z1→0 at low z3 (cycle 10+): (a) **stronger per-bay packing+scheduling**
  — global timing on CELLS-tight geometry, e.g. box-DECOMPOSITION CP-SAT (cover each footprint
  with k rects, 3D no-overlap on rect pairs → tighter than single-bbox, still CP-SAT-able);
  (b) **fast z3-aware reassignment LS** (per-bay-cached pack, bbox-fast candidate eval, obj-gated).
  Both are meaty builds; time-discipline critical (FRESH §5: set2 timeouts → −1).

### 2026-06-14 · Cycle 8 · H2 — per-bay CP-SAT packing-by-scheduling · **KEPT**
- Change: new `_pack_bay_cpsat` — per bay, CP-SAT chooses integer translations (tx,ty) + entry
  times e to MIN Σ tardiness s.t. 3D (x,y,time) no-overlap (any two time-overlapping blocks have
  disjoint bboxes ⇒ crane-safe by construction, same invariant as the greedy bbox packer). Sound
  integer encoding despite FLOAT bboxes: tx integer ⇒ "a right ≤ b left" ⇔ tx_a−tx_b ≤
  floor(minx_b−maxx_a) (exact). Seeded with the greedy bbox layout as a CP-SAT HINT (feasible ⇒
  CP-SAT only improves the bay) + greedy fallback. Fixed orientation = greedy's pick (keeps hint
  valid). Skips bays >`OGC_CPSAT_MAX`=60 (O(n²) disjunction). Added as 2 obj-gated specs
  (preferred/capped × cpsat); `OGC_CPSAT=1` default & reversible. Pool hardened: `map_async`+hard
  sub-wall timeout ⇒ a slow solve can never breach the wall (→−1).
- Cmd: `OGC_CPSAT=1 … eval.py --set ALL40 --tl 60 --vs h6 --save c8`
- Result: **feasible 40/40, total obj 353.4M→343.3M (−2.88%), improved 24/40, REGRESSED 0,
  set1 wins 2→3 (prob_1 flips, z1 2→0).** Mini-gate (clean, fresh proc): prob_1 60,247→2,065
  (z1 2→0), prob_11 2.16M→1.41M (z1 94→61), prob_16 807K→585K (z1 87→49).
- Verdict: KEPT (broad gain, zero regression, never −1, +1 win). BUT z1 NOT 0 on the binding
  set1 instances (prob_11=61, prob_15=74, prob_16=49) → residual×huge-w1 keeps them LOSS. This
  is the **bbox-conservatism ceiling** (the SAME one the old falsified `baypack_cp` hit). The
  total −2.88% is small only because the huge set2 instances (prob_26/27/38/39) have bays >60 →
  CP-SAT skipped. Honest note: cycle 8's CP-SAT family OVERLAPS the old solver (old had a
  fixed-layout timing oracle + a falsified bbox box-packer); the NEW part is JOINT position+time
  (FRESH §8 "the timing oracle only half-solved"), and it works. Next (cycle 9) = crane-OVERLAP.

### 2026-06-14 · MEASUREMENT BUG (harness, not solver) · throwaway probe lacked `__main__` guard
- `notes/research/_probe.py` had no `if __name__=="__main__":` guard → on Windows `spawn`, the
  pool workers RE-RAN the whole probe body (each printed a spurious line + a nested failed
  algorithm), and the re-entrancy CORRUPTED the main `pool.map` results (e.g. a false "prob_11
  cpsat = no change"). Fixed by adding the guard. **`eval.py` HAS the guard → all canonical
  baselines (h1..h6, c8) are unaffected.** Lesson: any standalone script that calls
  `algorithm()` (which spawns a Pool) MUST have the `__main__` guard.

### 2026-06-14 · Cycle 7 · richer 4-side cell BL candidates · **REJECTED**
- Added left/below extreme-point anchors to `_bl_fit_cells`. MIXED: prob_11 slightly ↓ but
  prob_16 807K→1.2M (z1 87→131) WORSE. Reverted. Same lesson as the falsified LCA: under online
  BL "first-feasible", MORE candidates change the greedy pick and fragment space for later
  blocks. Candidate-set tweaks are a dead end for residual z1; need global packing/scheduling.

### 2026-06-14 · DIAGNOSTIC · intrinsic z1 lower bound · **KEY FINDING**
- `z1_LB = Σ max(0, R+P−due)` (layout-independent floor) = **0 on every set1 loss instance**
  (prob_1/3/4/5/11/16/17/20…), but greedy_z1 = 1–94. ⇒ residual z1 is FULLY RECOVERABLE; z1=0
  is achievable; chasing it wins most of set1. This justifies building the per-bay CP-SAT
  scheduler (or staggering) as the next major cycle — it's not wasted effort on an inherent floor.

### 2026-06-14 · Cycle 2 · H3 — per-bay best-of-5 orderings · **KEPT**
- Change: `_pack_bay_copresent` now packs the bay under 5 orderings (EDD, slack, release, proc,
  area-desc) and keeps the lowest-tardiness one (packing is order-sensitive). Short-circuits at
  tardiness 0.
- Cmd: `python notes/research/eval.py --set ALL40 --tl 20 --vs h1 --save h2`
- Result: **feasible 40/40, total_obj 1.38B→1.257B (−9%), improved 38/40, regress 0, wins
  0→2 (prob_2, prob_8), ≤15s.**
- Verdict: KEPT. Insight: confirmed residual z1 IS the entire set1 gap (z3≈0, z2 small); only
  z1=0 instances win. Diminishing returns from ordering alone — need denser co-presence /
  optimal scheduling to reach z1=0.

### 2026-06-15 · Cycle 14 · #1 — per-bay LNS (ruin-and-recreate) realize engine · **REJECTED**
- Built `_pack_bay_lns` (mode `lns`, spec gated `OGC_LNS`): start from greedy cells layout, RUIN a
  temporal cluster (Shaw relatedness, tardy-biased seed, K≈m/6) + RECREATE by best-insertion over
  (orientation × bounded entry-scan × BL cell-position), accurate cells decode, first-improvement
  + equal-drift, deterministic RNG. Two levers CP-SAT lacks: orientation freedom + non-bbox z1.
- Result (`_lnstest.py` per-bay, prob_11 @15s/bay): bay0 95→90, bay2 13→3, total z1 108→**93**.
  Even after speed fixes (single-orient, bounded tscan) bay0 floors ~90. **z1 RANKING at preferred
  (prob_11): box-decomp 50 < cpsat 61 < LNS 93 ≈ cells 94.** LNS is the WORST optimizer — barely
  beats greedy, far behind CP-SAT.
- Verdict: **REJECTED (gated OFF).** WHY: per-bay tardiness comes from a GLOBAL over-subscription of
  a release time-window (too many blocks competing for the bay at once). Small-K ruin-recreate can't
  restructure the whole co-present schedule — it re-inserts a handful of blocks while the other ~40
  pin the space/time. CP-SAT's GLOBAL joint position+time search finds the dense staggered schedule
  the local moves can't (box-decomp got bay0 to ~47 vs LNS 90). ⇒ the realize engine wants a GLOBAL
  solver, not local search. Confirms box-decomp/cpsat (global) as the right family; LNS is a dead end
  for z1. (LNS could still help z3-reassignment search, but that's a different use — see #2/#4.)
- ⇒ RE-READ of cycle 13: box-decomp is NOT "marginal" vs the realisable frontier — it is the BEST
  realize engine we have (prob_11 z1 108→50, beating greedy 94, cpsat 61, LNS 93). It's "marginal"
  only vs single-bbox cpsat (50 vs 61) and only fails the absolute bar (z1=0). Its real value =
  whether it NETS obj in the full pipeline (base pool + reassign + obj-gate) — gating now (`_bdgate.py`).

### 2026-06-15 · Cycle 18 · TARGETED-SPILL realize search · **★ BREAKTHROUGH (8.8× on prob_13)**
- The realize wall is NOT absolute — it's a SWEET SPOT the old generators miss. `_feasspill.py`
  (forced targeted spill: cheapest-z3 block from the most-tardy bay, one at a time; box-decomp+
  cumulative+4-worker pack measured periodically; keep best TRUE obj). prob_13 curve:
  | k | z3 | BD z1 | obj |  k=0: 103/184/3.47M → k=4: 120/104/1.98M → **k=8: 152/8/192,101 (−89% vs
  c12 1.69M)** → k=12: 199/8/196K → k=16: 256/72/1.39M (over-spilled, oscillates). **The sweet spot
  (z3≈152, z1≈8, obj 192K) is the competitor regime** (comp 76.7K @ z1=0,z3=435); capped over-spills
  PAST it (cliff to z3~9000), bbox-proxy reassign stalls BEFORE it (z3~24). prob_14 descends too
  (z1 235→176 by k=6, more congested ⇒ needs more steps).
- KEY: box-decomp z1 does NOT track cells-z1 (prob_13 cells 146 ⇒ BD z1 8; prob_14 cells ~360) ⇒
  cells can't locate the sweet spot; must measure box-decomp periodically + keep best.
- SHIPPED `_solve_feasspill` (PHASE 3, `OGC_FEASSPILL`, default OFF): preferred → tabu targeted spill
  → periodic box-decomp+cumulative pack (4 workers, solo main process = all cores) → best obj,
  early-stop after `patience` non-improving measures. Budget: base_frac 0.30, feasspill 0.30→0.97·TL,
  REPLACES reassign. obj-gated + fallback ⇒ never −1. Gating the full set1 next.
- Residual: z1=8 last mile (×w1 = 149K of prob_13's 192K) — to BEAT comp need z1→0 (e.g. push the
  best assignment's box-decomp harder, or z1=0-feasibility mode on the sweet-spot assignment).
- **INTEGRATION VALIDATED** (`_solve_feasspill` PHASE 3, `OGC_FEASSPILL`, default OFF): TIME-DISCIPLINE
  bug fixed (v1 re-packed cells-every-bay-every-step ⇒ prob_11 overran 350s @TL=200 = would be −1).
  v2 = cheap bbox-guided spill TRAJECTORY (Phase A, ~O(steps) incremental bbox packs) + budget-strict
  box-decomp measures on snapshots (Phase B, hard `margin`=30s ⇒ no wall overrun). **prob_13 @TL=400:
  obj 1.69M→251,807 (z1=11, z3=199), wall 302s (disciplined, 6.7× cut).** @TL=150 starved (returns
  capped 1.24M — needs ~30s/measure for box-decomp to realize z1≈8; server TL=minutes is fine).
- **z1=0-feasibility (`OGC_BD_Z1ZERO`) HURTS feasspill**: z1=0 is INFEASIBLE even at the sweet-spot
  assignment (z3=199) ⇒ the SAT solve wastes budget then falls through with less ⇒ z1 11→50. Our
  greedy spill trajectory BOTTOMS at z1≈8-11 (z3~150-200); the competitor's z1=0 @z3=435 is a
  DIFFERENT assignment our trajectory doesn't reach. Keep z1zero OFF.
- ⇒ feasspill is a MAJOR win (prob_13 6.7×) toward the user goal set1<1M, but on its own won't beat
  the competitor (we're ~2.5–3× comp per hard instance, vs 7–30× before). Full set1 est ~2–2.5M
  (from 9.03M). Reaching <1M needs the z1≈8→0 last mile (a stronger realize than our greedy reaches).
- **5-TARGET VALIDATION** (`_fstest.py`, TL=380–400, OGC_FEASSPILL=1, integrated): prob_11
  569K→**168,122** (z1=5,z3=297, 3.4×); prob_13 1.69M→**251,807** (6.7×); prob_14 2.12M→**671,456**
  (z1=35,z3=312, 3.2× but z1 NOT realised low); prob_12 1.34M→1,141,243 (z3 STUCK 7659); prob_20
  1.99M→1,585,438 (z3 STUCK 10802). **5-target total 7.71M → 3.82M (−50%)**, all wall ≤ TL (never −1).
  TWO failure modes: (a) prob_12/20 — feasspill trajectory never reaches a low-z3 sweet spot ⇒
  obj-gate keeps the capped high-z3 result (the bbox-guided spill picks wrong blocks, or sweet spot
  is at higher k than the budget reaches); (b) prob_14 — trajectory DOES reach low z3 (312) but
  box-decomp can't realise z1 below 35 (more congested ⇒ realise-starved). Diagnosing prob_12/20 with
  the cells-guided prototype. Next: fix the 2 stuck + prob_14 realise; then full-set1 + other-15 gate.

### 2026-06-15 · Cycle 17 · cumulative + workers + the spill→z1 frontier · **realize-wall mapped**
- **GOAL set by user: set1 total obj < 1,000,000** (from 9.03M; below competitor's 1.139M). Requires
  cracking the realize gap (z1≈0 at low z3) on every congested instance.
- **Redundant area-cumulative** (`OGC_BD_CUMUL`, default ON): co-present footprints disjoint ⊆ bay
  ⇒ Σarea ≤ bay area; CP-SAT's cumulative propagator prunes the weak pairwise-disjunctive space.
  prob_13 preferred z1 **300→152** (1 worker). **4 workers** (`OGC_BD_WORKERS`) → **123**. Still
  plateaus FAR from 0 ⇒ CP-SAT cannot realise z1≈0 at preferred regardless of power/time.
- **z1=0 feasibility mode** (`OGC_BD_Z1ZERO`): force exit≤due, pure SAT. **UNSAT at preferred** for
  prob_13 ⇒ z1=0 genuinely INfeasible at preferred (the energetic area-bound was optimistic; true
  2D+crane floor is real). z1=0 needs SOME spill.
- Cumulative gave **0 full-pipeline change** (5-target total still 6,029,009): the pipeline winner is
  the heavily-spilled capped assignment (z3~9000) where box-decomp already hits z1≈1 WITHOUT the
  cumulative; the cumulative only helps the congested preferred end the obj-gate doesn't pick.
- **Spill→obj frontier** (`_spillcurve.py`): `_assign_capped` has a CLIFF (preferred z3=103 z1=251 →
  any α-spill jumps to z3≈9000, z1≈1) — capped over-spills globally. **`_assign_capped` is the wrong
  spill tool.**
- **★ TARGETED minimal-spill** (`_feasspill.py`, spill cheapest-z3 block from the most-tardy bay one
  at a time): walks the RIGHT frontier — z1 **354→80 while z3 stays 24** (vs the capped cliff). This
  is the competitor direction (z1↓ at tiny z3). BUT the greedy STALLS ~z1=80 (box-decomp z1 estimate
  noisy/starved during search ⇒ premature "no-improving-spill"). The competitor sits at z3=435 (MORE
  spill than our stuck z3=24) at z1=0 ⇒ we may be UNDER-spilling. Running FORCED spill + periodic
  box-decomp measurement to map whether z1→0 as z3→~435 (decisive for goal reachability).
- NOTE: `conda run` wrapper CRASHES with 4-worker CP-SAT (thread issue) — run the env python
  directly (`C:/Users/peter/anaconda3/envs/ogc2025/python.exe`). em-dash in prints → cp949 crash; ASCII only.

### 2026-06-15 · Cycle 15 · box-decomp FULL-PIPELINE gate · **NET −21% → ADOPT (pending ALL40)**
- `_bdgate.py` (5 hard targets, full `algorithm()`, TL=180, BD off vs on): **TOTAL(5) 7,641,692 →
  6,029,009 = −1.61M (−21.1%), 0 regression** (prob_11 unchanged). z1-driven: prob_12 14→5,
  prob_13 25→1, prob_14 51→19, prob_20 23→8 (box-decomp realises lower z1 on the reassigned
  assignment ⇒ less residual ×huge-w1). **z3 UNCHANGED (7659–10802)** — the dominant residual is
  still the z3 over-spill, untouched by box-decomp.
- DESIGN for adoption: box-decomp now REPLACES single-bbox cpsat (not adds) when `OGC_BOXDECOMP=1`
  ⇒ pool size constant (7 specs) ⇒ no extra CPU contention ⇒ the set2-starvation regression vector
  stays closed. box-decomp dominates cpsat per-bay + falls back to cells on timeout (= cpsat's
  fallback) ⇒ low regression risk. Still default OFF until the full ALL40 gate confirms.
- ADOPTION GATE running: `OGC_BOXDECOMP=1 eval.py --set ALL40 --tl 120 --vs c12 --save bd120`
  (apples-to-apples: c12.json is BD-off@120). Screens the other 15 set1 + 20 set2 for regression /
  −1 / timeout. If clean ⇒ flip `OGC_BOXDECOMP` default ON (new baseline c13).
- NEXT (cycle 16) = #2 ACCURATE-z1 reassign: the z3 over-spill (7659–10802 vs comp ~330–460, energetic
  forced LB ≤39) is now the #1 residual lever on prob_12/13/14/20 (55–76% of their obj). The reassign
  LS over-spills because its move-eval uses a FAST 1-ORDER BBOX proxy for z1 (`_solve_reassign`'s
  `packbay`) — it over-estimates congestion ⇒ spills more than needed. Replace/augment the proxy with
  a cells (or box-decomp) z1 eval on candidate assignments so the LS stops at low z3. Big expected win.

### 2026-06-15 · Cycle 13 · H/#3 — box-DECOMPOSITION CP-SAT packer · **MARGINAL (gated OFF)**
- Built `_cell_rects` (footprint-cell → ≤K-rect cover, greedy row-merge partition + least-waste
  merge-down) + `_pack_bay_boxdecomp` (generalises `_pack_bay_cpsat`: each block's single LOOSE
  bbox → ≤K-rect cover of its footprint CELLS; co-present blocks need EVERY rect-pair disjoint ⇒
  cell-set disjoint ⇒ crane-safe, but far tighter than single-bbox; cells-greedy hint+fallback,
  obj-gated + check downstream). Wired mode `boxdecomp` into `_pack_all`; spec gated `OGC_BOXDECOMP`
  (default OFF). Env `OGC_BOXDECOMP_K`/`_MAX`/`_CAP`.
- Probe (`_prefpack.py`, pure preferred, z1 floor): @15s/inst box-decomp ≈ or WORSE than single-bbox
  cpsat (prob_11 104 vs cpsat 76; prob_20 failed=budget). **@80s on prob_11 (small bays): K=2 z1=50
  BEATS single-bbox cpsat 61 (−18%); K=3 z1=68 WORSE (9× model, CP-SAT can't solve it in budget).**
- Verdict: **MARGINAL, NOT the breakthrough.** Tighter geometry (K=2) helps z1 ~15–20%, but even
  tight-geometry + long budget **floors z1 at ~50 on prob_11, nowhere near the energetic-feasible 0**
  (and ×w1 still ⇒ obj 1.16M ≫ comp 31.9K — no win flip). The realize gap is DEEPER than geometry
  conservatism: **CP-SAT pairwise-disjunctive packing has a structural ceiling >> z1=0**, even at
  small scale (46–52 blk bays), even though z1=0 provably exists (energetic + competitor comp_z1=0).
  K=3 backfires (model bloat). Set K=2 default; kept gated OFF (live = c12, never −1, slow ⇒ needs
  server long-TL). Echoes the OLD "exact CP-SAT box-packer" falsification (FRESH §4).
- ★ SHARPENED PICTURE for next loop: for prob_12/13/14/20 (79% of set1 total) the DOMINANT obj term
  is **w3·z3 (55–76%)** from our z3 OVER-spill (7659–10802 vs comp ~330–460; energetic forced-spill
  LB ≤39). The spill is the lesser-evil because the packer can't realise z1≈0 at near-preferred
  (z1=397 at preferred ⇒ obj 8.76M ≫ spilled 1.34M). z1 and z3 are COUPLED: cutting the z3 over-spill
  REQUIRES a packer that hits z1≈0 at near-preferred — which neither cpsat nor box-decomp does. The
  open prize: a stronger realise method (accurate-z1 reassign #2, or a non-CP-SAT constructive/nesting
  approach) that the competitor evidently has. Box-decomp may still NET an obj reduction as a long-TL
  gated spec (z1 nibbles ×huge-w1), un-validated at scale.

### 2026-06-15 · WHY-ANALYSIS (backlog #1) · the lever is PACKING, not assignment · **KEY/DECISIVE**
- Question: for the 5 hard set1 instances (prob_11/12/13/14/20 = 85% of set1 total), is a
  z1=0 + near-preferred (low-z3) assignment even FEASIBLE? Two cheap, no-decode probes:
- **(A) Energetic reasoning** (`_whyhard.py`, sound cumulative area-time LB under the PREFERRED
  map; footprint = union-of-layers true polygon, min over orientations ⇒ a sound infeasibility
  cert): z1=0-at-preferred is area-feasible on **almost every bay**. Forced-spill LB (greedy
  cheapest-z3 removal, dest-capacity ignored = optimistic LB) to make every bay area-feasible:
  prob_11=**0**, prob_13=**0**, prob_12=**2**, prob_14=**6**, prob_20=**39** z3. The competitor
  sits at z3 167–463; **our c12 spills z3 7659–10802** (20×+ the competitor, ~200–4500× the LB).
- **(B) Packer ceiling at pure preferred** (`_prefpack.py`, our best of bbox/cells/cpsat, 15s):
  z1 floors at prob_11=**76**, prob_12=**397**, prob_13=**347**, prob_14=**398**, prob_20=**1411**
  — vs the area-feasible z1≈0. obj@preferred = 1.75M / 8.76M / 6.50M / 7.11M / **37.7M** (all ≫ comp).
- **VERDICT**: The whole set1 gap is a **REALIZE gap = per-bay packing/scheduling weakness**, NOT
  an assignment gap. (1) Area-time says z1≈0 is reachable at (near-)preferred; mandatory spill is
  tiny (≤39 z3). (2) Our packers reach only z1=76–1411 there — bbox is loose (wastes 31–40%),
  cells is tight geometry but BL-greedy/no-backtrack, cpsat is single-loose-bbox + skips bays >60.
  (3) The reassign LS then spills z3→~10K via assignment moves chasing z1 the packer can't deliver
  — net-harmful on these high-w3·z3 instances (trades ~1M z3 to shave z1), but obj-gated picks it
  only because preferred-packed obj is even worse (8.76M). Matches FRESH §4 "tardy blocks wait while
  the bay is 75–94% EMPTY" ⇒ scheduling/placement defect, not area.
- **RE-PRIORITISES the backlog**: build a STRONGER per-bay crane-safe co-presence
  packer/scheduler that realises z1≈0 at (near-)preferred. TOP = #3 box-DECOMPOSITION CP-SAT
  (k-rect cover ≈ true polygon, tight, vs single loose bbox; 3D no-overlap; joint position+time)
  and/or #2 accurate-z1 per-bay local search (cells/crane decode in the move eval, ruin-recreate to
  escape the BL greedy local optimum). DEMOTE #4 SA-on-assignment (assignment isn't the lever).
  prob_11 is the cheapest win: z3 already < comp (116<167) ⇒ pure z1→0 ⇒ ~20.5K < comp 31.9K.

---

## 5. Open questions / dead-ends

- Falsified on the OLD architecture (do not re-test blindly; may differ on fresh build):
  LCA/contact-area placement, temporal pre-staggering, finer-raster geometry, exact
  box CP-SAT packer. See `notes/structural-ceiling-2026-06-14.html`.
