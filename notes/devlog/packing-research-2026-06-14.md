# Packing-density breakthrough research (2026-06-14)

Triggered after exhausting 5+ incremental hypotheses (timing-in-loop, exact decode, cut strategy, capacity calibration, order portfolio) — the ceiling is crane-safe packing DENSITY. Researched the SSP + irregular-nesting literature (local store `research/z1-tardiness/z1-literature-2026-06-06.html` §1 + §9; web research in progress). The OGC problem == published **Shipyard Block Spatial Scheduling (SSP)** — directly-applicable methods exist.

## Actionable breakthrough shortlist (prioritized, implementable)

1. **Diagonal-fill / multi-anchor BLF** — Kwon & Lee 2015 (Comp&IE), "Spatial scheduling for large assembly blocks". Modify bottom-left-fill to consider **both bottom-left AND top-right anchor points** (and ideally all corners) when generating candidate positions for irregular blocks; objective = total weighted tardiness. **Our decoder uses BL-only → this is the cheapest density win.** Generate candidates from multiple anchors, keep the feasible one that packs tightest.

2. **Largest-contact-area placement** — Zheng et al 2011 (IJPR). Among feasible candidate positions, pick the one **maximizing contact area** with already-placed blocks + bay walls (minimizes wasted gaps). Denser packing AND less mutual blocking → directly shrinks crane-serialization tardiness. Replaces "lowest-BL" tiebreak with "max-contact".

3. **Jostle re-pack** — Martinez-Sykora et al 2018 (IJPE). Iteratively re-pack by alternating leftmost/rightmost placement passes ("shaking" the bay to fill gaps); re-insertion loop after any block exits re-tightens remaining shapes → enables earlier entry of tardy blocks. Good gap-filler / improvement pass on top of #1+#2.

4. **(heavy) ILS + NLP overlap-minimization** — Imamichi, Yagiura, Nagamochi 2009 (Discrete Opt). Allow temporary overlap, minimize via quasi-Newton separation + iterated local search w/ polygon swaps → strongest compaction. Most powerful but continuous-NLP; likely too heavy for our raster/integer + crane constraint. Defer.

5. **Semi-discrete fast BLF** — Chehrazad, Roose, Wauters 2021 (EJOR, arXiv 2103.08739). Discretize pieces+strip as equidistant vertical segments; sweep-line BLF in **milliseconds** with rotation. If placement cost is the bottleneck for #1–#3, adopt this representation. (We already have a raster; this is a faster variant.)

## Structural confirmation (the competitor's likely method)

- **He, Hong, Kim 2024 (J. Scheduling), "Quick and situ-aware spatiotemporal scheduling"** — most recent direct analog, KSOE (Hyundai)-validated: **phase 1 = assign bay + processing-start-date; phase 2 = exact (x,y) + rotation.** Targets tardiness + workload fairness, FAST. This matches the competitor's 5–47s near-optimal profile → strong constructive two-phase, not heavy search. Our rebuild already uses this decomposition; the gap is the phase-2 PLACEMENT density (→ techniques #1–#3).
- **Zhang & Chen 2012 two-stage**: agglomerate spatiotemporally-close blocks into "virtual blocks" before scheduling → reduces combinatorics.
- **Dixit 2018 RCI/TCI dispatch**: criticality-based ordering of which block to place/move first under congestion.

## CRITICAL caveat — blocks are multi-layer → crane constraint is central

Checked instance data: blocks are **mostly 2-LAYER** (prob_3 86/100, prob_5 123/150, prob_12 171/200, prob_20 254/300). So the crane j≥k descent rule genuinely matters — an existing block's UPPER layer (j=1) blocks a new block's LOWER layer (k=0) descent column even when rest-footprints (layer 0) don't overlap. **This rules out naive footprint-raster / `fftconvolve` BLF** (the standard nesting tools assume footprint non-overlap = feasible, which is crane-INcorrect here). The web-research's #1 recommendation (raster fftconvolve BLF) would produce crane-infeasible placements.

→ The packer MUST keep the existing layer-aware crane-safe geometry (`_ft_search_pos` / utils.check_entry/exit). The density lever is therefore **repositioning** (jostle: remove + re-insert to fill gaps; overlap-min ILS adapted with the crane "blocked-column" term) on TOP of the crane-correct placer — NOT a new footprint packer. A crane-aware raster (per-layer occupancy masks, forbidden = ∪ existing layers j≥k) is possible but a larger build; defer unless `_ft_search_pos`-based repositioning is too slow.

## Plan

Build the per-bay packer around **#1 (multi-anchor candidates) + #2 (contact-area scoring)** — the proven SSP density levers, implementable on our existing raster geometry — with **#3 (jostle)** as an improvement pass. This generates more, better candidate positions than the BL-only `_ft_search_pos`, fitting more co-present blocks → fewer evictions → lower z3. Validate per-bay (prob_3 bay2 ft_tard 19→?, prob_5 bay0 69→?), then full-20. The ripple-shift packer (code-writer v1) is a parallel attempt; merge whichever wins.

## SSP synthesis — the concrete breakthrough recipe (web research, both agents)

The competitor's fast-near-optimal profile is reconstructed by both research angles as a **strong constructive**, not search:
- **order**: EDD / ATC (deadline-pressure first).
- **bay**: greedy max-contact-area (or our CP-SAT z3 assignment).
- **position [THE LEVER]**: **Extreme-Point candidate set + Largest-Contact-Area (LCA) scoring** — maintain candidate points = {bay corners} ∪ {feature points (TL,TR,BR,BL) + vertices of each placed block}; for each block × candidate × orientation try **both BL-slide and TR-slide (diagonal-fill, Kwon&Lee 2015)**; pick the feasible position **maximizing contact perimeter** with placed blocks + walls (Shang&Gu 2017 BCA/LCA, Koh 2008). This packs far denser than bottom-left's "lowest-y,x" tiebreak.
- **crane j≥k**: validate each candidate with the existing layer-aware raster check (`fastfloor._verify`/`_ft_pair_ok`/`_ft_geom`) — reject if an existing co-present block's higher layer blocks the descent column. (Aircraft-hangar "exit-blocking" is the only analog; BSS lit ignores it.)
- complexity O(N·J·K·R) ≈ ms. Optional **MergeDJD** pre-merge of block pairs into composite (more-rectangular) units for extra density; **Sparrow/overlap-min ILS** as a slow refiner (defer — 20-min regime).

**Packer v2 design (decided): Extreme-Point + LCA + diagonal-slide, crane-validated via fastfloor raster.** I control candidate generation (vs `_ft_search_pos`'s BL-abut) and pick by contact-area, not BL. This is the literature-proven density lever and the most likely path to competitor-level z3. Sources in DEVLOG/agents: Shang&Gu 2017, Koh 2008, Kwon&Lee 2015, Gardeyn 2026 (MergeDJD/Sparrow), He 2024.
