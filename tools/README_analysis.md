# OGC2026 analysis toolkit

A cohesive, read-only data system for verifying hypotheses and tracking progress
toward the three goals (Z1=0, faster runtime, better Z2/Z3). Every tool scores
with the **official** `check_feasibility` (eval-server mirror) and never modifies
`src/` or `baseline/`.

Run everything under conda env `ogc2025` from the project root.

## Core library: `tools/ogc_analysis.py`
Import: `sys.path.insert(0,"tools"); import ogc_analysis as A`. Key API:
- `A.load_instance(name)` / `A.load_solution(path)` / `A.list_train_instances()`
- `A.score(prob,sol)` -> official report; `A.obj_tuple` -> (feas,obj,o1,o2,o3)
- `A.per_block_tardiness` (Z1), `A.bay_loads` (Z2), `A.pref_deviations` (Z3)
- Static (no solver): `A.intrinsic_z1_lb`, `A.demand_peak` (bbox vs footprint %),
  `A.bbox_fragmentation` (rectangle waste vs true polygon area)

## CLI tools
| tool | use |
|---|---|
| `python tools/inst_report.py [names] [--json P]` | STATIC per-instance structure; classifies AREA-FEASIBLE vs OVER-CAPACITY (Cat1/Cat2) |
| `python tools/sol_report.py <name> <sol.json> [--top N]` | deep anatomy of one solution: 3 objectives + shares, tardy blocks w/ slack diagnosis, Z2 imbalance pair, Z3 off-pref list, per-bay bbox waste |
| `python tools/board.py --sols <dir> [--json P --html P]` | dashboard over all 20 from cached solution files |
| `python tools/board.py --run --timelimit T [--conc N --instances ...]` | dashboard by running the solver fresh (isolated processes) |
| `python tools/collect_trace.py --timelimit T [--conc N --instances ... --out P]` | run with stage instrumentation; per-stage **time + objective contribution + wasted-time** |

## In-algorithm instrumentation (gated, OFF on eval server)
Set `OGC_STAGE_TIMING=1` to make `algorithm()` emit two stderr lines per run:
- `[STAGE_TIMING]{...}` wall-seconds per pipeline stage.
- `[STAGE_OBJ]{...}` per-stage objective reduction (`delta`, `n_adopt`) recorded at
  each adoption in `consider()`, plus `_postproc_base` (the search incumbent obj).

Join rule (what to look for):
- large `delta` -> high-value lever (GOAL 1).
- `time_s` > 0 but `delta` == 0 -> ran without improving = wasted budget (GOAL 2).

`OGC_TRACE=1` additionally writes a full event trace to `results/traces/` (search
improvements with t_rel, per-candidate events, final decision).

## Typical loops
- Progress check: `python tools/board.py --run --timelimit 300 --conc 2 --json results/board_latest.json`
- Where is an instance stuck: `python tools/sol_report.py prob_13 <its sol.json>`
- Which stage to cut / strengthen: `python tools/collect_trace.py --timelimit 300 --conc 4`
