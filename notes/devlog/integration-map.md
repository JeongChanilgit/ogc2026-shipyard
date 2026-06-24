# Rebuild Integration Map (2026-06-14)

Load-bearing reference for `src/rebuild.py`. Derived from code-analyzer sweep of `src/myalgorithm.py` (397KB, do NOT read wholesale), `src/fastfloor.py`, `src/z3race.py`. Line numbers approximate; grep `def ` to confirm.

## Data structures

- **Block** = `prob_info["blocks"][i]`, `block_id == list index`. Fields read by solver:
  - `release_time` (R, int), `processing_time` (P, int; exit = entry+P is WLOG-optimal),
    `due_date` (int), `workload` (float), `bay_preferences` (list[float], len=n_bays),
    `shape` (list of orientation dicts: `{"orientation":int,"layers":[[[x,y]...]...]}`).
- **Bay** = `prob_info["bays"][j]` = `{"width":int,"height":int}`. `Bay.from_dict(d, j)`; `.width .height .id`. No level/weight field.
  - `u_j` derived: `u_j = avg_bay_area / (W_j*H_j)` → `bay_u` list. Pass to `_objective`.
- **Placement record** (the atom): `{"block_id","bay_id","x","y","orient_idx","entry_time","exit_time"}`.
- **Per-bay results**: `{bay_idx: {block_id: placement_record}}`.
- **Flat list** (for `_objective`): `[a for r in results.values() for a in r.values()]`.
- **assign**: `list[int]`, index=block id, value=bay id (the master output / seed form).
- **weights**: `prob_info["weights"]["w1"/"w2"/"w3"]`, default 1.0 each.

## Objective (utils.check_feasibility authoritative; _objective is internal proxy)
- z1 = Σ max(0, exit - due_date)   (tardiness)
- z2 = official: floor(max pairwise |u_j*load_j - u_k*load_k|); internal proxy: max(u*load)-min(u*load). load_j=Σ workload in bay j.
- z3 = Σ (max(bay_preferences) - bay_preferences[bay_id])
- total = w1*z1 + w2*z2 + w3*z3
- **KEY: z2 and z3 are closed-form on the block→bay map ONLY (independent of x/y/timing).** z1 is the only component that needs decode.

## Primitives (reuse as black boxes)

| fn | loc | sig → return |
|----|-----|--------------|
| `algorithm` | my:5249 | `(prob_info, timelimit=60) -> {"operations":{str_time:[op,...]}}` |
| `_decode_bay` | my:1115 | `(bay, bay_idx, order, blocks_data, deadline=None, cand_cap=0, release_override=None, exhaustive_pos=False, fast_geom=None) -> (result|None, forced_ids:set)`. crane-safe via `_find_slot_crane_safe`. force-place → tardiness born here. |
| `_decode_assignment` | my:1782 | `(decoder, assign, n_bays, deadline) -> (per_bay_results, total_tard)` or `(None, inf)` |
| `_Decoder` | my:1358 | `.decode`, `.decode_full -> (result, tardiness, forced_ids)` |
| `_cpsat_bay_timing_verified` | my:2596 | `(prob_info, bays, results, deadline=None, lb_skip=True) -> {"operations":...}|None`. **THE ORACLE**: fixes layout, re-times entry only, preserves z2/z3, minimizes z1. |
| `_objective` | my:1437 | `(prob_info, flat_assignments, bay_u) -> (total,obj1,obj2,obj3)` |
| `_quick_objective` | my:1461 | fast rank proxy |
| `_components_from_solution` | my:2431 | `(prob_info, sol, bay_u) -> (total,obj1,obj2,obj3)|None` |
| `_results_from_solution` | my:2401 | `(prob_info, sol) -> (assign, per_bay_results, flat)` |
| `_build_operations` | baseline_greedy:1765 | `(flat_assignments) -> operations dict` (EXIT sorts before ENTRY per time) |
| `_cpsat_assignment` | my:1615 | `(prob_info, bays, feasible_bays, bay_u, time_budget, diag=None, hint=None, cap_alpha=None) -> assign:list[int]|None`. **z1-blind**: `min c2*z2 + c3*1000*Σpref`. optional `AddCumulative` area cap (necessary-not-sufficient). |
| `_trivial_solution` | my:2337 | full-serialization floor, always feasible (-1 guard) |
| `_bay_tardiness_lb` | my:2486 | per-bay tardiness lower bound |
| `_orderings` | my:1295 | EDD-first orderings |
| `_balanced_seed` | my:1505 | balanced assignment seed |
| `_tardiness_seed` | my:1523 | tardiness-aware seed |

## The realize barrier (diagnosis)
`_cpsat_assignment` minimizes z2+z3 (z1-blind). Decoder force-serializes congested bays (crane j≥k) → z1>0. ban-rebuild evicts tardy blocks from preferred bay (`build_fast_floor(ban={block:bay})`, fastfloor:619-648 removes bay from feasible set) → z3 inflates. Both bad.

## fastfloor
- `_ft_search_pos` (ff:231): `(b,blk,geo,bay,aB,eB,At,deadline,grid=False,ft=None) -> (x,y,oi,wlayers,wcbox)|None`. Time fixed, position search only.
- `_fixed_time_decode` (ff:390): `(bay,bay_idx,ids,blocks_data,deadline,order_key="F0") -> (asgn|None, ft_stats)`. ft_stats has `tardy_map` (b→j for late blocks) = no-good cut source.
- `build_fast_floor(..., ban=None)`: ban dict removes bay from block's feasible set.

## Existing cut hooks (check before W4!)
- `OGC_M4_CUT` / `OGC_M4_CRANE_CUT` at my:1902 inside `_local_search` — possible existing no-good/forced_ids cut prior-art. Read my:1836-2070 before reimplementing W4.
- `_cumulative_leveled_redecode_verified` (my:2892), `_temporal_reassign_redecode_verified` (my:3737) — z1/z3 reassign levers, oracle candidates.

## Env flags (gate readers)
`OGC_SUBMIT_V2` (my:630, default ON → injects 16-knob gate200_v2 bundle at my:5280-5291 when T≥60). `OGC_REBUILD` not yet read anywhere = new namespace for this work. crane core: `OGC_CRANE_SAFE`(570, default ON), `OGC_DEV_DET`(208, determinism). Per-bay timing oracle is invokable standalone.
