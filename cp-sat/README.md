# cp-sat — an all-CP-SAT solver for the Grand Shipyard Puzzle

A self-contained, **fully CP-SAT** solver for OGC 2026. Every decision the
problem asks for — *bay assignment, x, y, orientation, entry time, exit time* —
is made by a Google OR-Tools CP-SAT solve. The parts of the production hybrid
that were greedy (the bottom-left floor for positions, the EDD time-first
heuristic, the best-fit assignment, the greedy crane-safe stacking) are all
replaced here by CP-SAT models.

This lives in its own folder and **does not touch `src/`** — it is a clean
experiment, not the submission path.

```
  python myalgorithm.py <instance.json> [timelimit]      # local run + grade
```

## Architecture — logic-based Benders decomposition (LBBD)

A single monolithic CP-SAT model over all blocks deciding position *and* time
jointly explodes (this is documented in the project notes as a falsified
lever). So instead the work is split into two CP-SAT models that exchange cuts —
but **both** are CP-SAT, so nothing greedy remains.

```
                     ┌────────────────────────── master_cp.py ──────────────────────────┐
   prob_info ───────▶│ CP-SAT MASTER                                                     │
                     │   vars:  x[b,j] (bay), entry[b], tard[b]                          │
                     │   relax: per-bay area-time AddCumulative (packing lower bound)    │
                     │   obj:   w1·Z1 + w2·Z2(imbalance) + w3·Z3(preference)             │
                     │          on the grader's exact 1000× integer basis                │
                     └───────────────┬───────────────────────────▲──────────────────────┘
                       assignment +  │                            │  no-good / cardinality
                       relaxed Z1     ▼                            │  cuts
                     ┌────────────────────────── bay_pack_cp.py ───┴──────────────────────┐
                     │ CP-SAT PER-BAY PACKER  (one solve per bay)                         │
                     │   each block picks one of a finite candidate pool (orient, x, y)   │
                     │   entry[b] IntVar,  exit = entry + P                               │
                     │   EXACT crane rule: for every interacting candidate pair the three │
                     │   checker booleans (same-layer collision, A-blocks-B, B-blocks-A)  │
                     │   are precomputed and gated on the chosen candidates, reproducing  │
                     │   utils.check_entry/check_exit/check_collisions (j≥k, area>0,      │
                     │   half-open / co-exit time semantics) exactly.                     │
                     │   obj:  minimise the bay's tardiness                               │
                     └────────────────────────────────────────────────────────────────────┘
```

`solver.py` drives the loop: solve master → pack each bay → if a bay can't fit
its set, add a **no-good cut** (reassign); if the true tardiness beats the
master's optimistic relaxation, add a **cardinality cut** over the
time-overlap clique (the bay was over-packed). The best **grader-verified**
solution is kept and warm-starts the next round.

### Why this is genuinely "all CP-SAT"

- **Bay assignment** — was best-fit greedy → now `x[b,j]` in the CP-SAT master.
- **(x, y) position** — was bottom-left greedy fill → now the chosen candidate
  in the CP-SAT packer. Candidate *enumeration* is just the explicit finite
  domain of the position variable (like listing an IntVar's values), not a
  heuristic decision.
- **Orientation** — was min-bbox greedy → now part of the chosen candidate.
- **Entry/exit time** — was EDD time-first greedy → now `entry[b]` IntVars with
  the reified disjunctive crane/collision constraints.
- **Crane j≥k feasibility** — was enforced greedily during placement → now
  *modeled* in CP-SAT with the exact three-boolean reified disjunctions, with
  variable geometry.

The only non-CP-SAT code is `serial_floor()` in `solver.py`: a trivial
one-block-at-a-time-per-bay layout used purely as a **feasibility floor** so the
solver can never return −1 even if every CP-SAT solve times out. It is a safety
net, not the solver.

## Scalability

A whole crowded bay (50+ blocks) is too big for one packing solve, so the
per-bay packer has two modes (`bay_pack_cp.py`):

- **≤ `MONO` (14) blocks** — one CP-SAT solve over the whole bay (often optimal).
- **larger** — **incremental CP-SAT in EDD batches**: each batch is a small
  CP-SAT solve that places ~`BATCH` (8) free blocks against the already-placed
  blocks held as *fixed obstacles* (constants). Every placement is still a
  CP-SAT decision; only the batch *order* is heuristic (a branching order, not a
  solution variable).

The construction cost is kept low by (a) precomputing each candidate's layer
polygons once and deriving the booleans directly (no per-call Shapely rebuild),
(b) a strict-AABB pre-filter, and (c) small, size-adaptive candidate caps.

### Compactness tie-breaker (density)

The per-bay objective is `K·Σtardiness + Σ(bottom-left rank)` with `K` larger
than the maximum possible rank sum, so **tardiness is strictly dominant** and
compactness only breaks ties. Without it, the batched packer freely places a
block high/right whenever timing allows, wasting low-left space that *later*
batches then need — forcing them to serialise in time and inflating Z1. Packing
bottom-left leaves room for more spatial coexistence. Measured effect (60 s/inst,
no regressions, all still feasible):

| instance | without | with tie-break | Δ |
|---|---:|---:|---:|
| prob_21 (set2) | 105.6M | 69.2M | −34% |
| prob_22 (set2) |  72.3M | 41.3M | −43% |
| prob_23 (set2) | 162.4M | 138.0M | −15% |
| prob_24 (set2) | 116.9M | 100.8M | −14% |
| prob_25 (set2) |  33.4M (30s) | 7.2M | −78% |
| prob_1  (set1) | 128.2M | 103.7M | −19% |

## Files

| file | role |
|---|---|
| `myalgorithm.py` | entry: `algorithm(prob_info, timelimit)` + a CLI test harness |
| `solver.py` | LBBD driver, feasibility floor, output assembly, grader verification |
| `master_cp.py` | CP-SAT master: assignment + relaxed schedule + z2/z3, with cuts |
| `bay_pack_cp.py` | CP-SAT per-bay packer (candidate set-packing + exact crane) |
| `geom.py` | candidate enumeration + the exact pair-boolean precompute (binds to `src/utils.py`) |
| `data.py` | parse `prob_info` into typed, weight-aware specs |
| `cuts.py` | time-overlap-clique selection for cardinality cuts |

All geometry and the final feasibility check defer to the official, unmodified
`src/utils.py`, so what the models believe is feasible is bit-identical to what
the grader enforces.

## Results & honest limitations

Verified on set1 + set2 (`conda` env `ogc2025`, env-python directly):

- **Always feasible, never −1** — set1 + set2 all feasible, including the
  historically −1-prone `prob_25` (set2) and `prob_14` (250 blocks, 4 layers).
  (A correctness fix was needed: `fitting_bays` must require an *integer* (x, y)
  slot, not just a continuous bbox fit — otherwise the 200-block instances
  `prob_32/33/34` crashed the floor and returned −1.)
- **Small / uncongested bays**: reaches the tardiness optimum (e.g. the 10-block
  example hits Z1 = 0).
- **Large congested bays**: feasible but Z1-dominated. The candidate grid packs
  less densely than the production hybrid's specialised bottom-left floor, so
  more blocks are delayed. With w1 in the tens of thousands this dominates the
  objective. This is the documented **per-bay packing-density wall** — the
  weakness here is packing *density*, not correctness.

**set2 (prob_21–40, 60 s/inst): 20/20 feasible, total obj ≈ 16.9 B.** The total
is dominated by the large instances (150–250 blocks, 3–4 layers): `prob_31`
3.5 B, `prob_38` 3.6 B, `prob_39` 1.8 B, `prob_27` 1.6 B — Z1 of 90 K–400 K each.
Small (100-block) set2 instances are reasonable (7.6 M–140 M). So on set2 totals
this is **not competitive** with the production hybrid (set2 ≈ 330 M) — its value
is the never-−1 guarantee and being a clean all-CP-SAT reference. Closing the
large-instance gap needs the heavier density work below.

So this is a correct, scalable, end-to-end CP-SAT solver and a clean reference
for "what is the pure-CP-SAT formulation of every decision", but it does **not**
beat the tuned hybrid in `src/` on dense set1 instances.

Levers to close the density gap (all keep the all-CP-SAT property):
- finer / NFP-based candidate positions (denser pools, more time per bay);
- larger `BATCH` / `MONO` when the time budget allows;
- a compaction pass (CP-SAT re-pack of the achieved layout with tightened
  position domains);
- per-bay connected-component decomposition to solve more blocks jointly.

### Tuning knobs

- `bay_pack_cp.MONO`, `bay_pack_cp.BATCH` — joint-solve / batch sizes.
- `bay_pack_cp._cap_for` — candidate-pool size vs. construction cost.
- `master_cp.solve_master(rho=…)` — area-cumulative tightness of the relaxation.
- `OGC_CPSAT_VERBOSE=1` — per-iteration / per-bay progress on stderr.
