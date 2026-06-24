# Rebuild Reflections (running log of what the data teaches)

## 2026-06-14 — Baseline gap structure (kickoff)

Scored gate200_v2 default vs competitor: **9/20 wins, total obj 1.52M (@200) / 1.64M (@600) vs comp 1.14M.**

**The losses are almost entirely z3-dominated** (z1=0 on 19/20, but our z3 ≈ 2–4× competitor's):

| inst | our z3 | comp z3 | gap (obj) | note |
|---|---|---|---|---|
| prob_18 | 704–726 | 172 | +58–63K | **worst z3 ratio (4×)** |
| prob_20 | 783–898 | 463 | +218–337K | z3 + **structural z1=7–12** |
| prob_13 | 689–805 | 435 | +28–37K | |
| prob_3 | 407 | 94 | +26K | 4× |
| prob_4 | 154 | 8 | +29K | 19× ratio |
| prob_12 | 702–770 | 332 | +10–20K | |
| prob_17 | 384–405 | 222 | +13–16K | |
| prob_6 | 461–591 | 345 | +7–27K | |
| prob_11 | 338 | 167 | +14K | |
| prob_15 | 226 | 192 | +2.6K | **closest loss** |

**Implication for the rebuild:** the realize barrier is real and it manifests as z3, not z1. Our assignment model *wants* low z3 (min c3·1000·Σpref) but when that assignment can't realize z1=0, ban-rebuild evicts blocks from preferred bays → z3 climbs to 2–4×. The competitor proves z1=0 AND low z3 is attainable in 5–47s → it's a construction/realize-quality problem, not a search-time problem.

**Priority for waves:** z3 reduction (W2/W3/W4) is where 11 losses live. W1 builds the controllable z1=0 foundation; its assignment must be z3-aware from the start (preference-greedy + deadline-aware spill) so W2+ can drive z3 down without the z3-blind ban-rebuild. prob_15 is the cheapest flip (+2.6K). prob_18 is the highest-value single z3 target.

**Wins to protect (don't regress):** prob_1,2,5,7,8,9,10,16,19.

## 2026-06-14 — W1 standalone result + diagnosis (1/20)

W1 foundation @100s: **1/20 wins (prob_2), feasible 20/20 (robust, no -1/crash).** Far below baseline 9/20 — expected for a from-scratch foundation. What the data taught:

1. **z1=0 is NOT guaranteed and that's fatal** — w1 is huge (each z1 unit ≈ 17–27K obj). W1 left z1>0 on 9 instances (prob_20 catastrophic z1=362; the large-instance spill/SA never converged). Any z1>0 dominates the objective → must structurally guarantee z1=0 before touching z3.
2. **z3 over-spill** — clearing z1 by spilling to non-preferred bays costs z3 ~linearly at ~5× the competitor's rate; W1's z3 is 1.5–3× even our own baseline. Root cause: spill measures z1 at fixed-time (pessimistic) and packs loosely.
3. **W2 (order portfolio) cut prob_3 z3 515→357** — better packing = fewer forced serialisations = less spill. But 5× decode cost starved z1-clearing (ended z1=2). Portfolio must stay OUT of the fast z1 phase.

**Restructure decided:** two phases. Phase 1 = greedy monotone z1-descent (fast EDD decode, spill cheapest-z3 blocks first) → guarantee z1=0 when reachable. Phase 2 = z3 descent within the z1=0 manifold (SA + W2 portfolio). Fall back to None (→legacy) when rebuild can't reach z1=0 (esp. prob_20). The competitor proves z1=0+low-z3 is attainable everywhere except prob_20's structural floor.

## 2026-06-14 — W3 (LBBD cap-cut) result: z3 nailed, z1 barrier confirmed

Built the per-bay capacity-calibration LBBD loop (CP-SAT `_cpsat_assignment` + decode oracle, shrink caps on tardy bays). On prob_1 it found **z3=2 (competitor=8!) with z1=6**, and construct→timing got z1=1, z3=2. So:

- **z3 is SOLVED at competitor level by CP-SAT** (it minimises pref globally). The whole game is the residual **1–8 units of z1 = crane serialization** that the area-time cap CANNOT model (necessary-not-sufficient → CP-SAT keeps finding cap-satisfying but crane-conflicting z3=0 assignments; shrinking caps oscillates, doesn't converge).
- **This is precisely the realize barrier the architecture predicted.** The fix is W4's *combinatorial* no-good cut, not the area relaxation: when bay j's block-set S realizes tardy, forbid that exact over-subscription. Implementable via `_cpsat_assignment`'s `feasible_bays` exclusions = ban the cheapest-z3 tardy block from j (a per-(block,bay) cut), iterating.
- Bugs found: PHASE-2 SA hogged the budget and starved LBBD (prob_3 never ran LBBD). Reorder: LBBD primary → single final SA polish. The per-bay timing oracle is valuable (prob_1 z1 7→1) — keep it in finalize.
- prob_1 obj 30590 (z1=1) vs baseline 1499 — still z1-blocked, but z3 is already there. Cross the last z1 unit and prob_1 ≈ matches/beats baseline.

## 2026-06-14 — W4 ban-cut behaviour + next-iteration plan

W4 combinatorial ban-cuts (evict cheapest-z3 tardy block from over-subscribed bay) **do** reach z1=0 where cap-cuts stalled (prob_3 z1=0 at round 3). But two problems:

1. **Over-eviction inflates z3** — prob_3 needed 6 bans → z3 105→599 (worse than baseline 407, far from competitor 94). Each ban costs z3; loose fixed-time packing forces many bans. The z1 was measured at FIXED-TIME (entry=R), which over-counts tardiness — many of those "tardy" bays would realize z1=0 if entries were STAGGERED (per-bay timing oracle). So we evict blocks that timing could have saved.
2. **Non-convergence wastes budget** — prob_1 churned 9 ban rounds (~20s) without reaching z1=0, leaving the FF fallback only 8s → final z1=1.

**Next iteration (the real W3 "decoder-in-loop"):**
- **Timing-in-loop**: in the LBBD acceptance, when fixed-time z1 ≤ THRESH, run the per-bay timing oracle to get TRUE z1; generate cuts only from bays STILL tardy after optimal timing. This avoids evicting blocks that staggering would save → far fewer bans → lower z3. Hypothesis: prob_1 z1=6→0 via timing alone (z3 stays 2 = competitor level); prob_3 needs far fewer bans.
- **LBBD early-abort** after K rounds with no true-z1 improvement → return budget to fallback.
- **Reserve FF fallback budget** (≥0.25·T) when LBBD hasn't found z1=0.

Root ceiling remains packing density, but timing-aware spreading should recover most of the gap without new geometry.

## 2026-06-14 — PIVOTAL: the ceiling is packing density, not search

Tested timing-in-loop (helped a little: prob_5 obj 103699→77753) and minimal one-cut banning (HURT: prob_5 z3 469→683 — fewer bans ≠ lower z3 because CP-SAT re-optimises z3 globally each round; reverted to multi-cut). The decisive observations:

1. **The per-bay timing oracle barely moves z1** (prob_5 fixed_z1 26 → true 24). The tardiness is **geometric over-subscription** (blocks can't coexist crane-safely at any timing), NOT bad timing. So z1 can only be cleared by spreading (eviction), which costs z3.
2. **The competitor trades z2 for z3; we do the opposite.** prob_3: competitor z2_unfloored=3654, z3=94; ours z2=700, z3=562. With w3≈133≫w2≈5, the z3 gap (468×133≈62K) is the whole obj gap. The competitor keeps blocks in *preferred* bays (low z3) and eats the imbalance (high z2) — possible only because their **packing fits many co-present blocks per preferred bay crane-safely**.
3. **Even legacy (same raster decoder) beats my LBBD on z3** (prob_3: legacy 407 vs mine 534) — its Front-B relocate+swap explores better than my ban-cut, and my fixed-time over-counting over-evicts.

**Conclusion: both legacy AND the rebuild are capped by crane-safe packing density.** The rebuild faithfully crosses the *realize barrier* (reaches z1=0 with global CP-SAT z3-min on 16/20) but can't reach competitor z3 because clearing the geometric z1 forces evictions. The architecture's W1–W4 are all built and gated; the genuine remaining lever is the architecture's **W2 done properly = crane-anticipatory placement (denser packing)**, OR feeding rebuild's CP-SAT z3-optimal assignments into a better decoder. Standalone rebuild ≈ 4/20 @100s (vs legacy 9/20); default OFF, zero submission risk.

**Next experiment:** does the EXACT crane-safe decoder (`_decode_bay`, exhaustive positions) pack denser than the raster for the FINAL chosen assignment → clear residual z1 without eviction? If yes, that's the ceiling-raiser.

## 2026-06-14 — EXACT decoder IS the lever (but budget-bound) — root cause found

Probe (z3-optimal assignment, raster vs exact `_decode_bay`): **exact clears 25–35% more geometric z1** — prob_3 23→15, prob_5 92→65, prob_12 484→370. Mechanism: exact `_decode_bay` *sequences* entry times (entry = earliest crane-safe slot after placed exits), while my raster `_fixed_time_decode` pins entry=R → forces temporal coexistence → conflict → forced serialization → tardiness. **This is exactly why legacy (which decodes via `_decode_bay`) beats my raster rebuild, and the architecture explicitly named `_decode_bay` the oracle — I substituted raster for speed and that substitution WAS the z3 ceiling.**

Wired `OGC_REBUILD_EXACT`. At tl=120 it's the right direction but **too slow**: prob_5 exact reached **z3=214 (vs raster 469!)** with far fewer evictions — but only 3 LBBD rounds fit, leaving z1=19 (unconverged → bad obj). The lever clearly works; it needs budget. The architecture targets ≤300s best; I'd been starving it at 100s. → testing exact-mode at tl=300 (SA off, all budget to LBBD). If prob_5 converges to z1=0 with z3≈214, that BEATS legacy (baseline z3=360) and validates the rebuild.

**Corrected standalone standing @100s: 6/20** (w4b_t100; multi-cut + timing + prob_17 continue-fix). Still < legacy 9/20 and never strictly beats legacy per-instance — but that's the RASTER ceiling; the exact@300 test is the real評価.

## 2026-06-14 — CLOSING: exact lever closed; rebuild adds zero competitive wins

exact@300 (SA off, all budget to LBBD): prob_3 z1=0 z3=551 (≈raster 534), **prob_5 z1=0 z3=652 — WORSE than the unconverged tl=120 z3=214**, prob_12 z1=27 (didn't converge). So the tl=120 "z3=214" was a mid-eviction snapshot, not a real win: reaching z1=0 still needs the same evictions regardless of decoder. **Exact `_decode_bay` clears z1 ~faster per-bay but ends at the same/worse z3 — the lever is closed.**

**Additive portfolio test:** per-instance min(rebuild@100, legacy@200) vs competitor = **9/20, total obj 1.512M ≈ legacy 1.515M.** The rebuild's improvements (e.g. prob_4 46011→43658) all fall on instances we lose to the competitor anyway → **zero new wins**. The rebuild contributes nothing to the competitive standing.

**Definitive conclusion:** Waves 1–4 are a faithful, fully-recorded implementation that VALIDATES the architecture's diagnosis (realize barrier; z3-dominated losses; CP-SAT reaches z1=0 with global z3-min). But the rebuild is **dominated by the mature legacy pipeline** (which already uses the exact `_decode_bay` oracle + CP-SAT seed + Front-B + postprocess) and is **far from the competitor (13+/20 goal)**. The remaining gap for BOTH legacy and rebuild is a single thing: **crane-safe packing/sequencing DENSITY** — fitting many co-present blocks in preferred bays so z1=0 holds without evicting (z3). Every incremental lever inside the assignment+cut+decode paradigm is exhausted (timing-in-loop, exact decode, cut strategy, capacity calibration, ban minimisation, SA). Closing this gap requires a fundamentally better packing algorithm (append-only greedy decoders can't reposition placed blocks) — a research-level build, not a tuning step. That is the decision fork for the user.

## 2026-06-14 — Packing research (user chose direction A): lever pinpointed

Two cheap probes nailed WHY congested preferred bays are tardy (`notes/devlog/probe_packing_slack.py`, `probe_order.py`):

1. **forced=0 everywhere** — no block is force-placed into an empty window; tardiness comes entirely from DELAY (the greedy shifts entries past R when it can't fit at R).
2. **peak bbox area-util is near/below 1.0 on the wasteful bays** (prob_3 bay0/2 = 0.88/0.87, prob_5 bay2 = 0.65) yet they're tardy → blocks that FIT BY AREA can't all be placed at entry=R. The append-only BL greedy wastes space. (prob_5 bay0 1.28, prob_12 bay2 1.74 are genuinely area-over-subscribed → those need either polygon-tighter packing or assignment spreading.)
3. **12–19 blocks/bay have zero deadline slack** (due = R+P) → must be at entry=R, can't be staggered → scheduling-first won't save them; only denser simultaneous packing will.
4. **Reordering is NOT enough** — 30 random shuffles + area/slack/tight orders beat EDD only on prob_5 bay2 (23→0); prob_3/prob_12 stuck regardless of order. Confirms the lever is genuine **repositioning** (move placed blocks), not reordering.

→ Building `src/packer.py`: a per-bay **repositioning packer** (insertion-with-ripple-shift + swap + nudge, crane-validated via fastfloor raster primitives) that fits tardy zero-slack blocks at entry=R by displacing co-present blocks into free space. Success metric: reduce prob_3 bay2 (greedy ft_tard 19) and prob_5 bay0 (69) while staying crane-feasible. If it works, wire as the rebuild's decoder/oracle and re-measure full-20. (Order-portfolio expansion added to decode_bay under OGC_W2 but it perturbs the search path without net gain — left gated OFF.)

## 2026-06-14 — Literature research → packer built → real but modest gain

Per the "3 failed hypotheses → research" rule, researched the literature (OGC == published Shipyard Block Spatial Scheduling). Findings in `notes/devlog/packing-research-2026-06-14.md`. Proven levers: LCA (largest-contact-area) placement, diagonal-fill (BL+TR anchors), extreme-point candidates, jostle/overlap-min ILS; competitor's likely method = fast two-phase situ-aware constructive (He 2024). Crane j≥k is absent from all BSS lit → our layer-aware geometry must be kept.

**Built `src/packer.py`** (repositioning, LNS window-rebuild + swap + nudge, crane-safe via fastfloor primitives, ≤greedy guaranteed): self-test = **8/13 congested bays strictly improved, 0 regressions** (prob_1 bay1 2→0, prob_4 bay1 8→3, prob_7 bay0 129→120, etc.). Critically, the 2 hardest bays (prob_3 bay2, prob_5 bay0) are **genuinely area-over-subscribed at release** (prob_5 bay0 = 164% footprint util in the release window) → NO spatial packing can fit them at R; they need time-repositioning (delay slack blocks to yield crane access) or a different assignment.

**Wired into rebuild** (`OGC_REBUILD_PACKER`, fires only on raster-tardy bays, small per-bay budget): prob_4 obj 43658→41780, z3 152→134 (real win — denser packing → fewer evictions → lower z3); prob_7 unchanged. So the packer is a **real but modest** lever — it helps the packing-wasteful bays but does NOT close the competitor gap, which is dominated by over-subscribed preferred bays (an assignment/time-repositioning problem) and a packing density the competitor reaches that even LNS repositioning doesn't in our budget. Full-20 with packer measuring now (pkfull200). Next lever if marginal: per-bay JOINT time+placement (delay slack blocks for crane access) — the code-writer's identified deeper lever.

## 2026-06-14 — Packer full-20: total obj −22% but win-count unchanged (6/20)

pkfull200 (W1/W3/W4 + packer @200): **6/20 (= w4b), total obj 4.16M→3.23M (−22%).** The packer slashed the WORST instances (prob_12 193K→117K, prob_14 600K→159K, prob_18 229K→113K, prob_20 1.91M→1.54M) but flipped no wins (they stay far above competitor), and REGRESSED prob_5/6/9 (path-sensitivity: lower per-bay tardiness → different LBBD cut path → worse z3). **The improvements land only on already-lost instances.**

**Root analysis of the eviction-z3 gap (the real blocker):** competitor prob_5 z3=94 vs ours 602. The z3-optimal assignment over-subscribes bay0 to 164% (area, at release) — mostly ZERO-SLACK blocks, so neither packing nor time-repositioning can fit them; some MUST be evicted (z3 cost). The competitor evicts ~the 64% overflow cheaply (z3=94); we evict far more (z3=602). WHY: our `_cpsat_assignment` area-time cap is **necessary-not-sufficient** — CP-SAT thinks blocks fit by area but they crane-conflict → realize z1>0 → ban-cut adds MORE evictions → z3 overshoots the optimal. **The gap = the cap's looseness vs true crane capacity.**

**Highest-probability next lever (decided): packer-calibrated capacity.** Use the packer to MEASURE each bay's true crane-safe block capacity, set `cap_alpha[j]` to that empirical value, then CP-SAT assigns min-z3 subject to TRUE capacities (not the loose area proxy) → evicts the right (minimal-z3) amount in one shot, no ban-cut overshoot. This couples the packer (density truth) to the assignment (z3 optimisation) — the missing link. (Time-repositioning is limited: over-subscription is dominated by zero-slack blocks.)

## 2026-06-14 — PCAP mixed/marginal → BIG STRUCTURAL CHANGE (user directive)

PCAP (`OGC_REBUILD_PCAP`, packer-measured true capacity → cap_alpha) tested on the close instances: **mixed** — prob_5 z3 602→496 (obj −22.8K, real win), but prob_3 534→567 (worse) and prob_11 z1=1 obj 72870→113997 (regressed). Still ~5× competitor z3. **Same pattern as every lever: marginal, instance-dependent, doesn't close the gap.** Per user directive ("그거 안 되면 로직 크게 수정 / 큰 변화로 타파"), the incremental tuning of the CP-SAT-assignment-first + cut architecture is exhausted.

**BIG CHANGE (launching): unified crane-aware greedy constructive** — abandon CP-SAT-assignment-first + cut loop. Instead, the competitor's reconstructed structure (He 2024 / DAS-CURVE / Shang&Gu): order blocks by criticality (tight-slack first), and for each block decide **(bay, position, entry-time) JOINTLY** to minimise marginal cost `w1·tardiness + w2·Δz2 + w3·pref-dev`, using crane-safe LCA placement. Crane-feasible BY CONSTRUCTION → **no realize barrier** (the entire root cause of the rebuild's z3 overshoot disappears: blocks are never assigned where they can't realize). z1/z2/z3 balanced per block (vs the z1-blind CP-SAT). Fast (O(N·K·place) ≈ competitor's 5–47s). New module `src/uconstruct.py`, gated, + jostle improvement pass. This is the structural break, not a tweak.

## 2026-06-14 — BIG CHANGE working: unified constructive + CP-SAT guidance

Built `src/uconstruct.py` (unified greedy constructive). First result: **z1=0 + feasible on ALL 5 test instances — the realize barrier is GONE** (crane-feasible by construction). But pure greedy was myopic on z2+z3 (prob_1 z3=452 vs legacy 2; z2-off blew up z2 → worse obj). Diagnosis: greedy can't find the joint z2+z3 optimum that CP-SAT finds.

**Synthesis (the breakthrough): CP-SAT bay-target guidance.** uconstruct now computes the CP-SAT global z2+z3-optimal assignment and, per block, tries that target bay first — commits if it realizes crane-safe at tardiness 0 (inheriting CP-SAT's optimum), else spills minimally. Result vs pure greedy:
- prob_1 obj 95153→**29065** (z3 452→142), prob_2 16730→**3690 = BEATS competitor (6624)**, prob_5 →79406 (+13% vs comp), prob_3 94640 (z3 514, unchanged), prob_11 →101017 (regressed — CP-SAT over-subscribed a bay).
- All z1=0, all feasible. This combines CP-SAT's global z2+z3 with z1=0-by-construction — the two strengths that were previously mutually exclusive (CP-SAT had realize barrier; greedy was myopic).

Wired into rebuild as `OGC_REBUILD_UNIFIED` (owns the run, self-verified, LBBD fallback). Full-20 measuring now (unified200). prob_2 already beats competitor — first time any rebuild variant strictly beats the competitor on an instance. Open issues: prob_11 over-subscription regression (CP-SAT target too aggressive there); prob_3 stuck.

## 2026-06-14 — ★ BREAKTHROUGH: additive unified+legacy = 10/20 (beats legacy 9/20)

Full-20 unified standalone = 5/20 BUT **total obj 1.96M (best rebuild ever, z1=0 on 19/20)** and it found **prob_15 as a NEW win legacy doesn't have** (46751 vs legacy 50783, comp 48206). Additive test min(unified, legacy) per instance vs competitor = **10/20, total obj 1.38M** (legacy alone 9/20 / 1.52M; competitor 1.14M). The unified engine CONTRIBUTES a win — first real win-count improvement over legacy.

**Integrated as `OGC_REBUILD_AUGMENT` (default OFF):** run uconstruct up front (capped ≤45s / 0.35T), stash its verified sol, fall through to legacy (remaining wall), append unified as a candidate before the gate → gate returns best-of (legacy, unified). Never worse than legacy below the floor (zero regression by construction). Validating on the real submission path now (augment200). If it confirms ≥10/20 on full-20 paired ×2, this is adoptable (the first thing that beats legacy). Then iterate: more unified wins (fix prob_11 over-subscription, prob_3 stuck, prob_1 over-spill) → each could add another flip. The unified's low total obj (1.38M additive) means many instances are CLOSE (prob_19 +2172, prob_5 +8826) — small per-instance gains could flip several more.

## 2026-06-14 — ADOPTED 10/20 + next lever toward 13/20

Augment paired ×2 = 10/20 confirmed, promoted to SUBMIT_V2 default (`OGC_REBUILD_AUGMENT=1`), smoke-validated (prob_15 win, prob_1 preserved), submission builds (0.19MB, all modules bundled). **Submission now 10/20 vs legacy 9/20.**

Toward 13/20 (user chose to continue autonomously): the close losses are **prob_11 (+43%, z3 338 vs comp 167), prob_17 (+26%, 405 vs 222), prob_6 (+29%, 538 vs 345)**. **Key competitor insight: they trade z2 UP for z3 DOWN** (w2≈5 ≪ w3≈133 → moving a block to its preferred bay even if it imbalances load is net obj-negative). Legacy's Front-B is too z2-conservative → z3 stuck at 338. Building an **aggressive z3-descent** (`_z3_improve` in uconstruct, gated `OGC_UC_Z3DESCENT`): move blocks toward preferred bays accepting z2↑, keep z1=0 via crane-safe re-decode of the 2 affected bays, accept iff w3·Δz3+w2·Δz2<0. Far losses (prob_18/20, 3–10× off) won't flip; the 3 close ones might. Self-test on prob_6/11/17 + prob_15(don't-regress) in progress.

## 2026-06-14 — z3-descent works but DOESN'T flip → win-count ceiling = 10/20 (robust)

The z3-descent (z2-for-z3 trade) **works**: prob_17 obj −24420, prob_3 −23050, prob_9 −41405, zero regressions, prob_15 win preserved. **But it flips ZERO new wins.** Decisive realization: **competition scoring is per-instance RANK (R − nb), not total obj — so reducing a loss-margin has zero score value; only flipping a loss→win counts.** The descent lowers margins but doesn't cross the competitor on any instance (prob_17 85863 still > comp 62070; legacy already better there). And it can't, because it saturates the preferred bay (packing density) and stalls — the SAME ceiling.

**Robust conclusion after ~12 distinct approaches (W1–W4, packing research+packer, PCAP, unified constructive, CP-SAT-guided, z3-descent): the win-count is fundamentally stuck at 10/20.** Flipping any of the remaining 10 losses requires matching the **competitor's preferred-bay crane-safe packing DENSITY** (they fit more blocks per preferred bay at z1=0 → lower z3 → e.g. prob_17 z2=6509/z3=222 vs our 4006/495; they trade z2 even harder but their packing realizes it). That is a genuine open problem (a better crane-aware dense nester — MergeDJD pre-merge / NFP-class — not a tweak), and a major dedicated build. The z3-descent is gated OFF by default (score-neutral, runtime risk); the validated 10/20 augment is preserved and shippable.

**Net session result: submission 9/20 → 10/20 (adopted, paired×2, shippable). Ceiling = 10/20 with all incremental + structural levers tried; 13/20 needs the packing-density problem solved.**

## 2026-06-14 — STRUCTURAL NEW: exact per-bay CP-SAT packer (the unbuilt W3)

User: "introduce something structurally new / modify the architecture." Built `src/baypack_cp.py` = **exact per-bay CP-SAT 2D box-packing + tardiness scheduling** (the architecture's W3 "small-bay CP-SAT exact" that I'd skipped). Key geometric fact: **bounding-box non-overlap of co-present blocks ⟹ polygon non-overlap ⟹ crane-safe** (box ⊇ polygon; clear descent columns) → every CP-SAT box solution is VALID. Per-pair 6-literal disjunction (left/right/below/above/before/after), minimise Σ tardiness, num_workers=4, deadline+budget bounded.

**Self-test: cuts congested-bay tardiness ~50%+, ALL crane-feasible** (prob_11 bay0 78→31, bay2 4→0, bay3 2→0; prob_6 bay0 84→39; prob_17 bay3 34→17). Full-solution check_feasibility passed (prob_11 z1 80→32). DENSER than greedy (global vs greedy BL gaps), despite box conservativeness. Slow on >40-block congested bays (15s incumbent-only) but fast (1–3s) on near-z1=0 bays.

**Payoff hypothesis (integrating now, `OGC_UC_CPPACK`):** in the unified, denser preferred-bay packing → fewer blocks spill to non-preferred bays → lower z3. If it realizes the CP-SAT z3-optimal assignment at z1=0 without spilling, z3 ≈ CP-SAT optimum → could finally match the competitor on the close losses (prob_11 z3 needs 338→~167, prob_17 405→~222). This is the first lever that attacks the packing-density root cause with an EXACT method. Integration self-test on prob_3/6/11/15/17 in progress; if z3 drops / flips, full-20 augment re-measure + adopt (paired ×2).

## 2026-06-14 — CP-SAT packer integrated (`OGC_UC_CPPACK`): z3 HALVED, no new flip yet

Integrated baypack_cp into uconstruct (assign all to CP-SAT target bays → dense CP-SAT pack each → spill only post-dense overflow). Self-test WITH vs WITHOUT: **z3 roughly HALVED on every instance** — prob_3 514→200, prob_6 844→601, prob_11 704→355, prob_15 192→160 (win, improved), prob_17 667→297. obj e.g. prob_11 101017→52640, prob_3 94640→63290. z1=0 (prob_17 z1=1 Pareto-optimal). Default-OFF path bit-unchanged.

**But still NO new competitor-flip** — gaps now 18–65% (prob_17 73142 vs 62070 = +18%, prob_3 +25%, prob_11 +65%). Closer than ever but the competitor's z3 is STILL lower (prob_11 167 vs our 355, prob_17 222 vs 297). **The residual gap is almost certainly box-vs-polygon: the CP-SAT packer uses bounding BOXES (wastes polygon concavity slack → fits fewer → more spill → higher z3); the competitor packs at POLYGON level.** Also cppack is slow (60–150s) — exceeds the augment's 45s cap (so it can't help the augment without a bigger unified budget). Running full-20 unified+cppack @300 standalone to confirm whether anything flips at scale + the additive standing. If still no flip, the final structural lever = a polygon-level dense nester (NFP/jagua-class) — the biggest build, and the genuine competitor-matching move.

## 2026-06-14 (PM) — polygon-LCA nester FALSIFIED + temporal stagger already-done; prelim reframe

Handoff's designated next lever = polygon-level dense nester (Extreme-Point + LCA + diagonal-slide, crane-validated). Built it: `fastfloor._ft_search_pos_lca` (BL-fallback feasibility-superset), gated `OGC_UC_NEST` in `uconstruct._place_one` (default OFF). **Per-bay density probe (`notes/devlog/probe_nest_density.py`) FALSIFIES it:** on congested bays LCA is WORSE than BL across the whole BL↔LCA band sweep (band=2/6/16) — prob_3 bay0 +8..+13 tard, prob_11 bay0 +10..+28 tard; net GRAND bay-tardiness +23..+37 vs BL. Root cause: fixed-time decode is **ONLINE (EDD-ordered)**; max-contact locally-optimizes each placement but **fragments residual free space** so later blocks no longer fit at z1=0. BL's "lowest Y,X" keeps free space contiguous → better for the whole sequence. Even near-pure-BL (band=2, contact only as exact-y tiebreak) regresses → ANY contact-bias hurts the online crane sequence. **Density via contact-area is a dead end for this problem.** (Matches the earlier box-CP `baypack_cp` result: halved z3 but flipped 0.)

**Temporal staggering also already exploited.** Tested: cumulative area-time model says congested bays CAN reach z1≈0 if entries stagger (prob_11 bay0 entry=R tard 60 → cum-achievable 9; prob_3 bay2 19→0). But a REAL crane-safe decode at those staggered targets (`M._decode_bay` release_override=t*) is MIXED and on prob_17 CATASTROPHIC (bay1 0→1689). Reason: **uconstruct already staggers optimally — the timing ORACLE `_cpsat_bay_timing_verified` re-times entries on the fixed layout to min-z1 (crane-safe). entry=R is just the layout-build phase; real entries are oracle-staggered.** Naive pre-stagger is worse because the oracle already does it better (= handoff "timing-in-loop rejected"). Both z3 density levers (spatial + temporal) are SATURATED.

**Weights confirm obj≈z3 on losses:** w1=9.7K–29.6K (z1 mandatory-zero), w2=4–10 (≈free, competitor maxes it), w3=125–200. So minimizing obj on a loss == minimizing z3 == packing density == the saturated ceiling.

**PRELIM REFRAME (decisive).** Prelim phase starts 2026-06-15 14:00 KST — the competitor table is TRAIN-only. The prior session shelved the obj-reducing levers (z3-descent −24K/−41K zero-regression; cppack prob_11 obj 101017→52640) as "train-rank-neutral (only flips count)." **That logic is train-overfit: against the unknown prelim FIELD, rank=R−nb is maximized by simply minimizing our obj — every reduction can outrank more teams.** User directive 2026-06-14 ("minimize the objective, don't fixate on z1/z2/z3 components") = exactly prelim-optimal. So the obj levers (z3desc/cppack) are VALUABLE for prelim, not worthless. Blocker to realizing them: the augment caps uconstruct at min(45s,0.35T) so even at 30-min eval uconstruct gets only 45s (cppack needs 60–150s; z3desc budget thin). Next: measure enabling them at realistic eval TL with adequate augment budget, gate on TOTAL obj + feasible 20/20 (not flips).

## 2026-06-14 (PM cont.) — finer-raster geom FALSIFIED + the realize-gap diagnosis (3 levers dead)

Measured the unit-raster superset over-estimates true polygon footprint by **31–40%** (raster/poly avg 1.31–1.40, max 2.3×) — `probe_fine_geom.py` re-rasterises verts×S (sound at any scale) for a 1/S-resolution cover, integer positions, scaled crane shift. Hypothesis: that conservativeness creates false crane conflicts → spurious tardiness. **FALSIFIED:** per-bay decode tardiness S=1 vs S=2/3 is MIXED/negative — prob_3 bay0 6→2 (helps) but bay2 23→31 (worse), prob_11 bay0 55→56 (flat), prob_17 bay3 27→21 (mild) but bay2 0→2 (worse). The 35% boundary slack is real but **NOT the binding constraint**: crane serialization is about which co-present blocks LAYER-STACK in the descent column (j≥k), not footprint boundary rounding. Finer footprints don't change the stacking structure.

**Realize-gap diagnosis (`probe_assign_realize.py`, the sharp new finding).** Swept the CP-SAT area-cap alpha; for each assignment reported closed-form z3 + realizable z1 (entry=R decode + timing oracle). **No alpha realizes z1=0** (tightest 0.85 still z1=22–43). prob_17: our area-optimal assignment z3=**159 < competitor 222**, but unrealizable (z1=72). **So the loss is NOT an assignment-quality gap — our z3-optimal assignment already beats the competitor's z3; it's a REALIZE gap.** The competitor realizes a HIGHER-z3 (222) but z1=0-realizable assignment; we over-spill to z3=384 to reach z1=0. demand_peak confirms the preferred bay is foot=115% (>100%) at the release peak (bbox=177–197% — our bbox-based CP-SAT/box-packer over-spreads), so SOME spill/stagger is unavoidable, but the competitor's is ~3.5× more z3-efficient.

**Robust conclusion (3 distinct NEW levers falsified this session + the handoff's prior 13).** LCA placement ✗, temporal pre-stagger ✗ (oracle already optimal), finer-raster geometry ✗. The remaining theoretical lever = min-z3 reassignment with a REAL-decode realize gate (= LBBD, already marginal). The ceiling is fundamental to the BL-greedy + per-bay-oracle architecture; breaking it needs a global joint position+time+assignment optimizer (large, uncertain build; baypack_cp's exact box version got only halfway). **Given prelim opens 2026-06-15 14:00 KST, the highest-value work is now prelim-readiness (robustness / never-(-1) on unknown shapes) + validating on the new instances, NOT more train-ceiling grinding.** Submit path untouched (10/20, OGC_UC_NEST default OFF, bit-identical). Artifacts: probe_nest_density / probe_nest_fullsolve / probe_assign_realize / probe_fine_geom in notes/devlog.
