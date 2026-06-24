# FRESH-START INSIGHTS — OGC 2026 (2026-06-14 reset)

> The old solver (≈7,300-line `myalgorithm.py` + ~12 modules) is **archived**
> (`archive/src-full-2026-06-14-reset.zip`, `archive/old-solver-src-2026-06-14/`)
> and removed from `src/`. This file is the **only** thing the new algorithm
> inherits: the distilled, still-valid knowledge — no code, no env-flag history.
> `src/` now holds just `utils.py` (official, read-only) + a clean v0
> `myalgorithm.py`. Read this top-to-bottom before designing the new idea.

---

## 1. The problem (precise)

**Per block decide jointly:** bay `j`, integer position `(x,y)`, orientation `o`,
ENTRY time, EXIT time. A crane lowers the block straight DOWN into the bay at
ENTRY and lifts it straight UP at EXIT (no horizontal travel during crane move).

**Constraints**
- Assignment: every block in exactly 1 bay (1 ENTRY + 1 EXIT op).
- Time: `ENTRY ≥ release_time`; `EXIT − ENTRY ≥ processing_time`. (EXIT = ENTRY+P
  is WLOG-optimal — no reason to keep a block longer.)
- Space: block polygon within bay bounds; same-layer no-overlap among co-present
  blocks.
- **Crane vertical access (j≥k) — THE hard one.** Blocks are multi-LAYER (a stack
  of polygons; the crane descends/ascends through the layer axis). A co-present
  block's HIGHER layer can block another block's LOWER-layer descent/exit column
  even when their layer-0 footprints don't overlap. Two blocks only interact when
  their time intervals overlap (half-open `[a,e)`); non-time-overlapping blocks
  can reuse the same footprint freely.

**Objective** `min w1·z1 + w2·z2 + w3·z3`
- `z1 = Σ max(0, EXIT − due_date)` — total tardiness. **Needs a decode** (depends
  on timing, which depends on the crane-feasible layout).
- `z2 = max over bay pairs |u_j·load_j − u_k·load_k|`, `u_j = avg_bay_area/(W_j·H_j)`,
  `load_j = Σ workload in bay j`. **Closed-form on the block→bay map.**
- `z3 = Σ (max_j pref_i[j] − pref_i[chosen_bay])` — preference deviation.
  **Closed-form on the block→bay map.**
- **KEY: z2 and z3 depend ONLY on the assignment (which block → which bay),
  independent of x/y/orientation/timing. z1 is the only term that needs a decode.**

**Solution format** (what `algorithm` returns):
`{"operations": {str(time): [op, …]}}` where ENTRY op = `{type:"ENTRY", block_id,
bay_id, x, y, orient_idx}` and EXIT op = `{type:"EXIT", block_id, bay_id}`. At any
equal timestamp, EXIT ops must be listed before ENTRY ops (checker Stage 5).

---

## 2. Scoring & strategic implications

`score(team, instance) = −1` if infeasible/timeout/crash; else `R − nb` (R = #teams,
nb = #teams strictly better). Total = Σ over instances.
- **−1 is catastrophic** (≈ −R/2 vs a feasible mid solution). **Never −1** is the
  #1 rule: guaranteed feasibility + strict time-discipline + a fast always-feasible
  fallback returned before the wall.
- Ties are fine (nb counts *strictly* better). One stable feasible-everywhere
  solution beats a brilliant-but-fragile one.
- **Minimize the objective per instance** (user directive 2026-06-14): against the
  unknown competition field, lower obj ⇒ fewer teams strictly better ⇒ higher rank.
  Do NOT fixate on individual z-components or hardcode "z1=0"; minimize total obj.

---

## 3. Instances — hard facts

Two train sets in `instances/train/`: **set1 = prob_1..20**, **set2 = prob_21..40**
(added 2026-06-14, generally larger / more layers). `notes/competitor-2026-06-11.json`
has a competitor obj table for **set1 only** (none for set2).

- Sizes: n = 100–300 blocks, bays = 2–5.
- **Layers: set1 mostly 2-layer; set2 has many 3–4 layer instances** (prob_24, 26,
  32, 40 — crane constraint much harder, decode much slower).
- **Weights vary by ORDERS OF MAGNITUDE — the new algo MUST be weight-adaptive:**
  | regime | examples | implication |
  |---|---|---|
  | w1 huge (9.7K–29.6K) | set1 all; set2 prob_22/27/35/38… | z1=0 effectively mandatory (1 tardy unit ≫ all z3) |
  | w1 small (667–3.3K) | prob_25/32/34/36/37/40 | **z1>0 trades for z3 become NET-POSITIVE** — a brand-new lever the old solver never used |
  | w3 large (400–600) | prob_22/27/32/34/37 | z3 (preference) dominates even more |
  Always read `prob_info["weights"]` and let it steer the search.

---

## 4. What's CONFIRMED vs FALSIFIED (hard-won — don't re-spend)

**Confirmed true**
- **z1's root cause is CRANE SERIALISATION, not area.** Tardy blocks wait while the
  bay is 75–94% EMPTY — they can't get a crane-clear descent column among the
  co-present set. The lever is the co-present LAYOUT + entry TIMING, not packing
  more area.
- **Per-bay CP-SAT entry-RE-TIMING on a FIXED layout is a reliable primitive**
  (minimises z1, leaves z2/z3 invariant, stays crane-safe). The old "timing oracle"
  worked. Reproducible idea: once the layout is fixed, optimal entry staggering is
  a clean scheduling sub-problem.
- **z2,z3 are closed-form on the assignment** — you can evaluate/optimize the bay
  map without any decode; only z1 needs the (expensive) crane-feasible decode.
- **The raster footprint cover is sound at ANY resolution** (rasterise scaled verts
  → tighter superset). The unit-cell cover over-estimates true polygon area by
  ~31–40%.

**Falsified (measured this session — do NOT rebuild)**
- **LCA / contact-area / Extreme-Point placement** — worse than bottom-left under
  the online (EDD-ordered) decode: max-contact fragments residual free space so
  later blocks no longer fit. (`notes/structural-ceiling-2026-06-14.html`)
- **Temporal pre-staggering of entries** — the re-timing oracle already does this
  optimally on the fixed layout; naive pre-stagger is worse (prob_17 catastrophic).
- **Finer-raster geometry** — the 35% area over-estimate is NOT the binding
  constraint; crane serialisation is layer-stacking, not boundary rounding. Mixed/
  negative.
- **Exact CP-SAT box-packer** (`baypack_cp`) — bounding-box no-overlap is sound but
  conservative; halved z3 but flipped 0 wins.
- The old architecture (bottom-left greedy floor + per-bay timing oracle + best-of
  candidate ladder) hit **10/20 on set1** after ~16 distinct approaches and is
  **brittle on set2** (time overruns: prob_25 ran 203s @ TL=120; catastrophic z1 on
  multi-layer / tight-due instances). Hence this reset.

**The core open problem (sharpest diagnosis)**
The loss is a **realize gap, not an assignment gap.** Our z2+z3-optimal assignment
can already match/beat the competitor's z3 (prob_17: our area-optimal z3=159 <
competitor 222), but it does **not realise at z1=0** (z1=72). The competitor realises
a *higher-z3-but-z1=0-feasible* assignment efficiently; we over-spill to reach z1=0
(z3 159→384). `demand_peak` shows the preferred bay is ~115% of area at the release
peak (true polygon; bbox says 177–197%) → some spill/stagger is unavoidable but we
do far more than necessary. **The real question: find the assignment+layout+timing
that minimises total obj — accepting crane co-presence and (where w1 is small) some
z1 — rather than greedily forcing z1=0 then spilling z3.**

---

## 5. Robustness requirements (non-negotiable, from set2 failures)

1. **Strict time-discipline.** Return well before the wall on EVERY instance,
   including n=300 / 4-layer. Frequent monotonic-clock deadline checks; a
   guaranteed-feasible fallback already in hand before any optimization starts.
   (Old solver overran 70%+ on set2 → would be −1.)
2. **Scale to multi-layer.** The crane-feasible decode / containment cost grows with
   layers; budget for it. Don't let the floor/decode eat the whole wall.
3. **Weight-adaptive effort.** Don't burn the budget chasing z1=0 when w1 is tiny;
   spend it where obj-marginal-return is highest for THIS instance's weights.
4. **Eval server:** 4 CPU cores, 16 GB, NO internet, NO GPU; full Gurobi license is
   present on the server (local is restricted — can't validate large MIPs locally).
   OR-Tools CP-SAT is available and was the workhorse.

---

## 6. Allowed dependency: `src/utils.py` (read-only, official)

Useful primitives (don't reinvent; do NOT modify utils.py — the eval server
overwrites it):
- `check_feasibility(prob_info, solution) -> {feasible, stage, objective, obj1..3}`
  — the exact 5-stage Shapely gate (ground truth). Cheap even at 4-layer (~0.02s on
  a sparse solution). Use it as the final arbiter for any candidate.
- `Bay.from_dict(d, idx)` → `.width .height .id`; `bay.contains_block(block)` (exact
  boundary check).
- `Block(block_id, block_data, x, y, orient_idx)` → `.layers_at_pos()` (world
  polygons per layer), orientation accessors.
- `_resolve_layers(...)`, the crane `check_entry`/`check_exit`/`check_collisions`
  pair predicates (the official j≥k logic) live in utils — reuse them for any
  crane-safe placement check instead of hand-rolling geometry.
- `prob_info["weights"]` = `{w1,w2,w3}` (default 1.0 each).

---

## 7. The v0 foundation (`src/myalgorithm.py` as it stands)

- Assigns each block to its **most-preferred bay it fits** (z3 ≈ 0), serialises
  within each bay in **EDD order** (one block present at a time → zero crane
  co-presence → trivially feasible). O(n), <0.05s, feasible on all 40 instances.
- It is the **z3-optimal / z1-terrible corner** of the trade space (z1 15K–395K).
  The new idea's whole job is to move off that corner: introduce crane-SAFE
  CO-PRESENCE (parallel blocks sharing a bay in time) + optimal entry timing to
  collapse z1, weight-adaptively, while keeping z2/z3 near the v0 optimum.
- It NEVER returns −1 and always returns in time — so it is the safe fallback the
  optimizer can always fall back to.

---

## 8. Open design directions for the NEW idea (framed, not prescribed)

The decision is the user's to shape. Some candidate framings consistent with the
insights above:
- **Frontier search from v0.** Start at v0 (z3-optimal, z1-max). Repeatedly let
  pairs/groups of blocks be co-present where crane-safe (using the utils pair
  predicates) and re-time via a CP-SAT scheduling sub-problem, accepting moves by
  TRUE total obj (so low-w1 instances naturally tolerate residual z1). Pure
  obj-descent with the v0 fallback ⇒ never worse, never −1.
- **Assignment-first MIP/CP (server Gurobi).** z2+z3 are closed-form on the bay map;
  the only coupling to z1 is realisability. A model that picks the assignment AND a
  crane-feasible schedule minimising w1·z1+w2·z2+w3·z3 directly attacks the realize
  gap. Local validation limited (restricted Gurobi) — design for the server.
- **Per-bay joint position+time scheduler.** Given a bay's block set, a crane-aware
  scheduler that decides positions + entry times to minimise that bay's contribution
  — the sub-problem the old timing oracle only half-solved (it fixed the layout).
- Whatever the shape: **weight-adaptive, time-disciplined, obj-gated against the v0
  floor.** Measure on BOTH sets (full-40), gate by total obj + feasibility, never −1.

Measurement harnesses still work: `notes/_capture20_aff.py` (now supports
`--instances ALL20 | SET2 | ALL40`), `notes/devlog/score.py` (set1 competitor
scoring), `notes/devlog/run_one.py`. Old-algo probe scripts in `notes/devlog/`
reference archived modules and will no longer import — ignore them.
