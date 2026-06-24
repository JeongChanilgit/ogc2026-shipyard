# Assignment-level lever — z3 over-spill (2026-06-18, user PIVOT)

**Pivot rationale:** per-bay packer optimization does NOT transfer to instance obj (per-bay
LEDGER C16: COVERT-race full-set2 +0.41%, within noise, LBBD-coupling). User redirected to the
ASSIGNMENT level (gassign master/LBBD/z3), the proven instance-level lever (gassign-first =
set2 −95.7%). Target = INSTANCE obj directly (not a proxy).

## ★ DIAGNOSIS (decisive) — set2 ours vs competitor, T=240
Baseline = `covert_off_set2` (current production gassign-first). Competitor = `notes/
competitor-2026-06-15.json`. Per-instance gap decomposed by component (w·Δz):

| total set2 gap (ours − comp) | value |
|---|---|
| **z1** | **−11,084,226 (we WIN big)** |
| z2 | −69,529 |
| **z3** | **+13,970,830 (we LOSE big)** |
| **net** | **+2,817,075 (we trail by 2.8M)** |

**The ENTIRE deficit is z3 over-spill.** Our z1-aware assignment (gassign-first) beats the
competitor on tardiness by 11M, but we over-spill blocks off their preferred bays, losing 14M
on z3. Cutting z3 over-spill by ~20% (~2.8M) ⇒ match; more ⇒ BEAT competitor on set2.

Per-instance: z1-wins almost everywhere; z3-losses almost everywhere (g3>0). Biggest z3 losses:
prob_37 +3.27M, prob_39 +1.45M, prob_34 +1.15M, prob_27 +1.14M, prob_33 +1.03M, prob_32 +0.90M,
prob_29 +0.92M. Exceptions (z1-losses): prob_38 +13.7M (packing density), prob_30 +0.75M.

## Levers (gassign master/LBBD knobs)
- `OGC_GASSIGN_DEPGROUP_W` (default 0=OFF) — z3 tie-breaker (keep close-departure together →
  fewer crane conflicts → less spill). Memory: "provably ≥ production" (never-worse). SAFEST.
- `OGC_GASSIGN_TARDY_SLACK` (default 1.0) — cardinality-cut sensitivity; higher → fewer cuts →
  less FORCED spill → lower z3 (but risk higher z1 on high-w1 instances).
- `OGC_GASSIGN_RHO` (adaptive ~0.85→0.55) — density; higher → bays hold more → less spill →
  lower z3 (risk: too loose → decode fails → no-good cut → spill anyway).

## Experiments
- **E1 (running, bsqkx3vzw):** z3-heavy subset {27,29,33,34,37,39} @T240, configs
  {dep05=DEPGROUP_W 0.05, dep10=0.10, rho90=RHO 0.90} vs baseline (covert_off_set2). Measure
  total obj + z3/z1 breakdown. [PENDING]

## E1 RESULT (z3-heavy 6 inst @T240) — z3 lever WORKS
| config | sum obj | z1 | z3 | vs base |
|---|---|---|---|---|
| baseline | 110.73M | 10639 | 36565 | — |
| dep05 (depgroup_w=0.05) | 108.90M | 10438 | 35479 | **−1.6%** ✓ |
| dep10 (=0.10) | 112.75M | 10722 | 35795 | +1.8% ✗ (overshoot) |
| **rho90 (RHO=0.90)** | **106.81M** | 10420 | **31673 (−13%)** | **−3.5%** ✓✓ |
Higher rho → master assigns more to preferred bays → less spill → **z3 −13%, z1 also slightly
down**. rho90 mixed per-inst (prob_37 −27%, prob_39 −7.7% wins; prob_29 +41% regress — rho90
over-packs the dense ones; adaptive rho exists for that reason). dep05 safer/smaller.
**E2 (running):** full set2 @T240, {rho90, dep05} vs baseline — does it hold on the WON/z1-heavy
instances too (risk: rho90 over-packs prob_35/26/38 → z1 up → lose our 11M z1 edge)? [PENDING]

## E2 RESULT — rho90 full set2 = NET-NEGATIVE (key reversal)
| config | total obj | total z3 | vs base | vs comp |
|---|---|---|---|---|
| baseline | 282.64M | 122,950 | — | +2.82M |
| **rho90** | **284.11M** | **110,251 (−10%)** | **+0.5% WORSE** | +4.28M |
rho90 cut z3 −10% but RAISED total obj: on full set2 it over-packs the z1-heavy/dense instances
(regressions: prob_28 +21%, prob_29 +41%, prob_30 +17%, prob_27 +7%...) → z1 up more than z3
down (weighted). The E1 z3-heavy win did NOT generalize. ⇒ rho is a CRUDE z3 lever: it trades
z3 for z1 at a net-BAD rate (forcing density makes blocks tardy).
**★ DEEPER INSIGHT.** We pay 14M z3 to save 11M z1 = a BAD trade (net −3M) ⇒ the master
OVER-spills. Root cause: the master is an area-time RELAXATION that OVER-estimates how much
spilling reduces z1 (the real geometric decode can't realize that z1 benefit) ⇒ it spills more
than the true optimum. The right lever is NOT density (rho) but **biasing the master objective
to spill LESS** (inflate c3 or deflate c1 in the master to counteract the relaxation's
z1-overestimate). dep05 (safe tie-breaker) full-set2 result PENDING.
**NEXT (E3):** add an env z3-bias multiplier to the master objective (gassign.py:355-370) and
sweep it on full set2 — does spilling less lower the TRUE total obj toward the competitor?

## E2b — dep05 full set2 = NEUTRAL
dep05 (depgroup_w=0.05) full set2: 282.64M (−0.0%, within noise); z3 122950→121537 (−1.2% only).
The departure-grouping tie-breaker barely moves z3 ⇒ neutral. So BOTH crude knobs (rho density,
depgroup) FAIL to net-fix the z3 over-spill (rho +0.5%, dep05 −0.0%).

## E3 (running, b3z2i5edl) — master objective z3-bias
Added `OGC_GASSIGN_C3_MULT` / `C1_MULT` to the master objective (gassign.py:356-364, default
1.0 = byte-identical). Hypothesis: master OVER-spills because the area-time relaxation
over-estimates z1-benefit of spilling; inflating c3 makes the master spill LESS, PER-BLOCK
(surgical, unlike rho which over-packs everything). Sweep C3_MULT {1.5,2,3} on z3-heavy 6 inst.
Test: does spilling less lower TRUE total obj (z3↓ without z1 exploding)? [PENDING]

## ★★ E3 RESULT — master z3-bias WORKS (over-spill confirmed)
z3-heavy 6 inst @T240:
| config | sum obj | z1 | z3 | vs base |
|---|---|---|---|---|
| baseline | 110.73M | 10639 | 36565 | — |
| C3_MULT=1.5 | 104.26M | 10156 | 32495 | **−5.8%** |
| **C3_MULT=2.0** | **103.58M** | **10220** | **30525** | **−6.5%** |
| C3_MULT=3.0 | 106.88M | 10399 | 28931 | −3.5% (overshoot) |
**C3_MULT=2.0 cuts z3 −16.5% with z1 ESSENTIALLY UNCHANGED (slightly down).** Unlike rho90
(z3↓ z1↑ net-bad), this is SURGICAL (per-block spill decision) → z3↓ at ~no z1 cost → net −6.5%.
**CONFIRMS the master OVER-spills** (relaxation over-estimated z1-benefit of spilling). Sweet
spot ~2.0; 3.0 over-keeps (z1 rises). Wins 5/6 (only prob_27 +1.2%).
**E4 (running, bqw6gw3w6):** full set2 @T240, C3_MULT {2.0, 1.5} — does it hold on the z1-heavy
WON instances (prob_35/26/38)? If net −2-3% on full set2 → MATCH/BEAT competitor (gap +2.82M). [PENDING]

## ★★★ E4 RESULT — C3_MULT=2.0 BEATS THE COMPETITOR on set2
full set2 @T240:
| config | total obj | total z3 | vs base | vs comp (279.82M) |
|---|---|---|---|---|
| baseline | 282.64M | 122950 | — | +2.82M (behind) |
| **C3_MULT=2.0** | **271.93M** | 112308 | **−3.79% (−10.71M)** | **−7.89M BEAT!** 🏆 |
| C3_MULT=1.5 | 282.37M | 121874 | −0.10% | +2.55M (weak) |
The z3-heavy −6.5% TRANSFERRED to full set2 (z1-heavy included): net −10.71M, BEATS competitor
by 7.89M (was +2.82M behind). Wins ~12 inst (prob_24 −43%, prob_34 −32%, prob_22 −33%, prob_29
−25%, prob_37 −17%, prob_39 −12%, prob_31 −10%); small regressions ~8 inst (prob_35 +10%,
prob_30 +8%, prob_23 +7% — the z1-wins where less spill raised z1 a touch; total ~+2.5M) far
outweighed. −10.71M >> noise band ⇒ ROBUST. C3=1.5 too weak ⇒ 2.0 is the sweet spot.
**THE biggest score lever of the session.** Unlike per-bay (didn't transfer), this is the
ASSIGNMENT (master objective) → directly drives instance obj, no transfer problem.
**E5 (running):** set1 no-regression check (set1 also runs gassign+C3_MULT at T>=200) + never-1,
before adopting C3_MULT=2.0 as the gassign default. Then: weight-adaptive mult (recover the
high-w1 regressions) for even more.

## ✅ ADOPTED — C3_MULT=2.0 is the gassign default (gassign.py:362)
E5 set1 check @T240 (gassign-first active): OFF(C3=1.0)=3,380,242, ON(C3=2.0)=3,313,945 =
**−1.96%** (C3=2.0 helps set1 too), **feasible 20/20 never −1**. So C3=2.0: set2 −3.79% (beat
comp +7.89M), set1 −1.96%, never −1 ⇒ ADOPTED (default 1.0→2.0, revert OGC_GASSIGN_C3_MULT=1.0).
NEXT refinement: weight-adaptive mult (recover high-w1 regressions prob_35/30 where less spill
raised z1).

## ⚠️ SEPARATE FINDING (bigger risk) — gassign-first is BAD on set1 at high TL
E5 exposed: set1 @T240 under gassign-first = **3.31–3.38M**, vs legacy ~1.31M (memory) and
competitor 931K. ⇒ **gassign-first PURE (the 2026-06-18 change) is ~2.5× WORSE than legacy on
set1.** It's GATE-protected at operating TL=120 (gassign OFF, MIN_T=200 → set1 uses legacy =
fine), BUT if the eval server gives set1 ≥200s, set1 degrades to 3.3M (potential −2M+ loss,
BIGGER than the C3_MULT set2 gain). ROOT: gassign's assignment is worse than legacy on the
small/congested set1 instances (legacy was the set1 champion z1=0 19/20). FIX: SIZE-gate
gassign-first (set2-like only: large/multi-layer) so set1 ALWAYS uses legacy regardless of TL.
This was flagged early ("set1 보호") — the TL gate is a weak proxy; a size gate is robust.
**= the next high-value work** (protects set1 1.31M independent of server TL).

## Post-hoc cross-bay REFINER (src/refiner.py, 2026-06-18) — user-requested A+B
Built: shared `_redecode` (bays are spatially independent → moving b:bayA→bayB re-decodes ONLY
bays A,B via fastfloor BL + B3 timing; obj-gated by official checker → never-worse).
Phase A `refine_moves` (single over-spill move), Phase B `refine_alns` (subset destroy/repair).
Tested on the C3_MULT=2.0 solutions (measure RESIDUAL recoverable z3 after the master lever).
- **PHASE A RESULT (prob_37, worst z3 case):** 61 over-spilled blocks, **53 moves tried, 0
  ACCEPTED** (8.74M unchanged). Confirms: after C3_MULT the residual over-spill is NOT
  recoverable by single moves — the preferred bay is FULL (that's why it spilled), so moving
  one block back fails/raises obj. Needs chain/swap (Phase B). ALSO SLOW: 259s (each move
  re-decodes 2 bays w/ B3 ~5s) ⇒ impractical for many iterations. [Phase B PENDING]

- **PHASE B RESULT + A+B VERDICT (post-hoc cross-bay refiner REJECTED).** Phase B ALNS
  (subset destroy + cross-bay greedy re-insert + re-decode, SA): prob_37 19 iters / **0 acc**,
  prob_34 20 iters / **0 acc** — ZERO improvement on the C3_MULT=2.0 solutions, same as Phase A
  (0/53). ⇒ **post-hoc cross-bay refinement adds NOTHING on top of C3_MULT.** The master z3-bias
  already captured the recoverable z3; residual over-spill is PACKING-LOCKED (preferred bays
  genuinely full → any reassignment fails/raises obj). z3 is correctly fixed IN the master
  (prevention), not post-hoc. (A stronger CP-SAT swap-repair might find marginal gains but
  re-decode ~5s/move is too slow + diminishing — not worth it given C3_MULT already beats comp.)
  BUG noted: first run infinite-looped (caller passed time.time()+X vs internal time.monotonic());
  fixed refiner to take relative time_budget. src/refiner.py kept (gated, not wired to pipeline).

## ═══ ASSIGNMENT-LEVEL TRACK: DONE ═══
WIN = **C3_MULT=2.0** (master z3-bias): set2 271.9M, BEATS competitor by 7.89M; set1 −1.96%;
never −1. ADOPTED as gassign default. Rejected (tested): rho/depgroup knobs, post-hoc cross-bay
refiner (A+B, 0 gain). OPEN RISK (bigger than any remaining z3): gassign-first is 2.5× worse than
legacy on set1 (3.3M vs 1.31M) at high TL — gate-protected at operating TL=120 but risky if
server gives set1 ≥200s → SIZE-gate gassign-first (set1 always legacy) is the next high-value work.

## ★ WINDOWED RELAYOUT POLISH (per-bay, final-stage) — WORKS at instance level
User per-bay layout idea, applied as a FINAL polish (post-gassign, z1-only, obj-gated → no
LBBD-cut coupling → transfers). For each tardy bay: best-of {pack_windowed_cpsat (fixed-orient),
pack_windowed_4d (orient selection)} + solve_timing(B3); swap bay layout iff per-bay z1 improves.
- 5-inst (generous 12s/bay): −2.37M (prob_26 −1.72M, prob_31 −627K).
- **FULL set2 (bounded 6s/bay): 271.93M → 269.33M = −2,597,923 (−0.96%), NEVER-worse.**
  Competitor lead −7.89M → **−10.49M**. Big wins: prob_38 −1.85M, prob_31 −333K, prob_34 −243K.
- ★ BEATS the existing perbay.improve (C3_MULT solutions had perbay ON; windowed found −2.6M more)
  ⇒ windowed best-of is a STRONGER per-bay polish. Budget-dependent + noisy (prob_26 −1.72M@12s
  vs +0@6s). Validates: per-bay LAYOUT gains DO transfer when applied as a final obj-gated polish
  (unlike per-bay-as-decoder, which changed cuts and didn't transfer).
- WALL cost: 6s/bay × tardy bays (CP-SAT). Slot = leftover wall after gassign; bound to worst bays.
- NEXT: wire into pipeline (move packers to src, add bounded final stage, gated, validate never-1).
- Code: notes/research/perbay/packers_cpsat.py (pack_windowed_cpsat/4d, solve_timing), refiner.py.

## ═══ WIRING THE WINDOWED RELAYOUT INTO THE LIVE PIPELINE (2026-06-19) ═══
The post-hoc −2.6M used UNLIMITED fresh budget (6s/bay) applied to the box+perbay FINAL winner.
The live pipeline at T=240 has NO spare budget (walls already ~232/240) → wiring it must STEAL
budget from gassign/box/perbay. Tested THREE injection points (all kept gated, default OFF;
production = relayout OFF, unchanged):

- **[B] gassign FINAL decode** (`gassign.py`, after _lbbd converges, `OGC_GASSIGN_RELAYOUT`):
  relayout.polish on gassign's RAW output, gassign's own budget, obj-gated. **ALL40 @T240 =
  +4.69% set2 (REGRESS).** Root cause: it polishes gassign's RAW assignment (NOT the box best-of
  winner, which IS the set2 champion — prob_34 box=1.92M vs gassign-raw 3.46M) AND consuming
  gassign's idle tail makes gassign return later → starves the downstream perbay leftover-wall
  slot (baseline ~46s → ~4s). DIAG confirmed relayout itself worked (prob_34 3.46M→3.07M) but on
  the wrong (weaker) candidate.
- **[C] replace perbay** (`myalgorithm.py` per-bay slot, `OGC_RELAYOUT`): relayout.polish instead
  of perbay.improve, SAME leftover-wall budget, on the box+gassign best-of winner. **ALL40 @T240
  = set2 +19.2M, set1 +2.6% (REGRESS, worst of the three).** Root cause: windowed best-of is a
  WEAKER per-bay polish than perbay.improve on set1's SMALL/congested bays (perbay's joint
  NoOverlap CP-SAT wins there); replacing perbay LOSES perbay's z1 reductions (set1 prob_5/6/9/12/14
  gained z1 1-4 where perbay held z1=0). The post-hoc −2.6M was perbay+windowed (additive), NOT
  windowed-alone.
- **[A] LBBD SUBPROBLEM decoder** (`gassign.py` `_decode_bay`, user's design intent — "벤더스컷
  하위문제를 relayout이"; `OGC_GASSIGN_RELAYOUT_DECODER`): fastfloor stays the FEASIBILITY oracle
  (cuts clean); escalate to windowed ONLY on already-feasible TARDY bays → tighter true-z1 → tardy
  cut fires less → master spills less → attacks z3 at the subproblem. Built with hard −1 guards
  (per-call deadline + per-bay SIZE cap n_max + shared GLOBAL escalation-time cap esc_frac). **The
  SPEED WALL is fatal:** windowed CP-SAT model-BUILD cost (pairwise disjunction bool-vars, ~n·K,
  NOT bounded by max_time_in_seconds) explodes on the LARGE bays (40-60 blocks) — and the
  z3-over-spill set2 instances are EXACTLY the large-bay ones. n_max=30 (needed for −1 safety on
  one instance prob_34 @T200 overshot 200→260s+ uncapped) SKIPS those large bays → A fires almost
  nowhere relevant (3-inst check: prob_29 1 fire/+22K, prob_30 & prob_33 0 fires; deltas = pure
  CP-SAT noise ±130-200K). Raising n_max → single-call build overshoot → −1 risk. ⇒ confirms the
  earlier FALSIFICATION ("per-bay packer as LBBD decoder = too slow / no transfer").
  **ALL40 @T240 = set2 +9.4M (281.3M, +3.46%), set1 +10.71% (3.67M) — REGRESS on BOTH; never −1
  (max wall 232.6).** On set1 (small bays ≤ n_max) escalation FIRES and HURTS (stolen master time +
  changed tardy cuts → worse assignment; set1 worst of the three); on set2 the large z3-bays are
  skipped so A barely touches the deficit. Least-bad on set2 (+9.4M vs B +12.7M, C +19.2M) but
  still a clear regression.

**VERDICT: the windowed relayout does NOT wire profitably into the live T=240 pipeline.** All three
placements REGRESS at ALL40 @T240 (A set2 +9.4M, B +4.69%, C set2 +19.2M; all never −1, walls ≤ 240).
The −2.6M post-hoc gain is a fresh-budget-on-the-FINAL-winner artifact the saturated live wall cannot
afford. Production stays gassign-first + C3_MULT=2.0 + perbay (relayout OFF) = set2 271.93M (beats
competitor +7.89M). All three relayout placements preserved as gated-OFF experiments (B/C/A =
OGC_GASSIGN_RELAYOUT / OGC_RELAYOUT / OGC_GASSIGN_RELAYOUT_DECODER); production path byte-identical
when unset.
**ONE UNTESTED variant [D-windowed] that matches the post-hoc setup:** windowed ADDITIVE *after*
perbay (NOT replacing it) at a HIGH TL (≥~400s) where leftover wall is ample (the −2.6M was perbay-ON
+ windowed @6s/bay on top). At T=240 the wall saturates so it can't fire; only worth building IF the
eval server grants set2 well above 240s. Not built (depends on the eval-TL assumption).

- **[D] B2↔B3 coordinate descent** (user 2026-06-19 "b3하고 다시 그 시간 기준으로 b2를 하고 b3하고
  마무리"; `gassign.py:_second_b2b3_pass`, `OGC_GASSIGN_B2B3`): the working form of the handoff's
  REJECTED "iterative B2↔B3" — instead of feeding B3 times as B2 TARGETS (which B2 ignores → entry=R
  reset ping-pong), feed them as the B2 placement ORDER (which B2 honours). B2(F0)→B3(0.6
  budget)→B2(reorder by B3 entry order)→B3(0.4), per-bay obj-gated, CHEAP (fastfloor + 1 extra B3,
  no windowed speed wall). **ALL40 @T240 = set2 +9.0M (281.0M), set1 −3.1% (NOISE, see below);
  never −1 (max wall 232.6). The 2nd pass was ADOPTED 0/40 times.** The reorder-by-B3-time NEVER
  beats the original F0-order decode: B3 only re-times FIXED positions, so its entry order ≈ the
  original placement order → re-decoding with it gives the same/worse packing. The set1 −3.1% is
  cross-run MASTER-assignment noise (z3 varies; D keeps assignment fixed → cannot move z3 → not a D
  gain); the set2 +9.0M is the 0.6 B3-budget CAP starving the large-tardy-bay instances (B3 needs
  full budget there) with NO compensating 2nd-pass gain. ⇒ D fails: the coordinate-descent's extra
  half-cycle adds nothing and the budget split hurts. Confirms the original "iterative B2↔B3"
  rejection even in its ORDER-fed form.

**FINAL VERDICT (A/B/C/D all tested full-set @T240, vs production set2 271.93M / set1 3.31M, all
never −1, walls ≤240):** A set2 +9.4M, B +4.69%, C +19.2M, D +9.0M. **NONE beats production.** The
windowed relayout post-hoc −2.6M is a fresh-budget-on-the-winner artifact; the saturated live wall
has no spare budget, and every reallocation (from gassign tail / perbay / B3) loses more than it
gains. Production stays gassign-first + C3_MULT=2.0 + perbay (relayout OFF). All 5 placements kept
gated-OFF (byte-identical when unset): OGC_GASSIGN_RELAYOUT_DECODER [A], OGC_GASSIGN_RELAYOUT [B],
OGC_RELAYOUT [C], OGC_GASSIGN_B2B3 [D].

## Rule
Judge by FULL-SET total obj (project rule); never −1; never regress set1 (gassign off there at
operating TL). z3 lever must not blow up z1 (we'd lose our 11M advantage).
