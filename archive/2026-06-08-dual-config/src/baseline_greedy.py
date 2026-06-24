"""
baseline_greedy.py -- EDD + Best-Fit Greedy Algorithm with Post-Hoc Repair

===============================================================================
ALGORITHM OVERVIEW
===============================================================================

Phase 1 -- Aggressive greedy placement (EDD order):
  Blocks are sorted by Earliest Due Date (ties broken by Shortest Processing
  Time).  For each block, every (bay, orientation, position, time-slot)
  combination is scored; the cheapest is committed.  Crane-path feasibility
  (check_entry / check_exit) is verified against the current bay state, so
  most Phase-1 placements are already crane-feasible.

Phase 2 -- Iterative repair:
  check_feasibility is called on the Phase-1 solution.  Violating blocks are
  re-placed in EDD order.  Two modes are supported (repair_mode parameter):

  * "greedy" (default)
      Violating blocks are removed from the current solution and re-placed
      using the same full Phase-1 search (best bay + position + time-slot).
      State (bay_placed / bay_schedule / bay_loads) is reconstructed from
      the non-violating assignments before each pass.
      Cycle detection: if a block reappears in a second repair pass it is
      added to forced_ids, which bypasses search and uses _force_place
      (empty-bay window at (0,0)) to guarantee termination.
      Time guard: blocks whose turn comes after 90% of timelimit are also
      sent to _force_place to ensure all blocks are assigned before timeout.

  * "simple"
      Each violating block keeps its current (bay, x, y, orient) and is only
      pushed to the next empty-bay window (bay completely empty for the full
      processing duration).  Stage-4 (spatial collision) violations are also
      reset to position (0,0).

===============================================================================
SOLUTION DICT FORMAT
===============================================================================

{
    "operations": {
        "<time_int>": [           # integer time-point as string key
            {
                "type":       "EXIT",   # crane removes block from bay
                "block_id":   int,
                "bay_id":     int,
            },
            {
                "type":       "ENTRY",  # crane places block into bay
                "block_id":   int,
                "bay_id":     int,
                "x":          int,      # bottom-left x the reference point within the bay
                "y":          int,      # bottom-left y the reference point within the bay
                "orient_idx": int,      # index into block["shape"] list
            },
            ...
        ],
        ...
    }
}

At each time-point, EXIT operations always precede ENTRY operations.
Within the same type, operations are ordered so that each is feasible given
the bay state after all preceding operations at that time have completed.
entry_time = int(t_str) for ENTRY ops; exit_time = int(t_str) for EXIT ops.

Feasibility checking and objective computation: utils.check_feasibility(prob_info, solution).
"""

import math
import os
import time
from dataclasses import dataclass
from utils import Bay, Block, check_entry, check_exit, check_collisions, _resolve_layers, _bounding_box

try:
    from instrument import bimodal_start, bimodal_log, bimodal_enabled
except Exception:  # pragma: no cover - probe must never affect the solver
    def bimodal_start(*_a, **_kw):
        return False

    def bimodal_log(*_a, **_kw):
        pass

    def bimodal_enabled():
        return False


# -----------------------------------------------------------------------------
# Helpers: block bounding box (anchored, per orientation)
# -----------------------------------------------------------------------------

def _block_bbox(block_data: dict, orient_idx: int) -> tuple[float, float, float, float]:
    """Bounding box of a block in local coordinates relative to the reference
    point (first vertex of first layer = (0, 0)).  Returns (min_x, min_y, max_x, max_y)."""
    raw_layers = block_data["shape"][orient_idx]["layers"]
    layers = _resolve_layers(raw_layers)
    if not layers:
        return (0.0, 0.0, 1.0, 1.0)
    all_verts = [v for l in layers for v in l]
    return _bounding_box(all_verts)


def _block_size(block_data: dict, orient_idx: int) -> tuple[float, float]:
    """(width, height) of a block derived from its anchored bounding box."""
    bb = _block_bbox(block_data, orient_idx)
    return (bb[2] - bb[0], bb[3] - bb[1])


# -----------------------------------------------------------------------------
# Helper: time interval overlap check
# -----------------------------------------------------------------------------

def _time_overlaps(a_entry: int, a_exit: int,
                   b_entry: int, b_exit: int) -> bool:
    """True if intervals [a_entry, a_exit) and [b_entry, b_exit) overlap."""
    return a_entry < b_exit and b_entry < a_exit


def _assignment_z1(assignments: dict[int, dict], blocks_data: list[dict]) -> float:
    """Total tardiness from assignment records, independent of feasibility."""
    z1 = 0.0
    for bid, a in assignments.items():
        try:
            z1 += max(0.0, float(a["exit_time"]) - blocks_data[bid]["due_date"])
        except Exception:
            pass
    return z1


@dataclass(frozen=True)
class RepairDecision:
    """Symptom-based choice of the Phase-2 repair mode."""

    mode: str
    reason: str
    phase1_feasible: bool
    phase1_stage: int | None
    violation_count: int
    elapsed_ratio: float
    z1: float
    tardy_count: int
    tail_ratio: float


def _assignment_tardy_stats(assignments: dict[int, dict],
                            blocks_data: list[dict]) -> tuple[float, int, float, float]:
    """Return (z1, tardy_count, max_late, max_exit / max_due) for assignments."""
    z1 = 0.0
    tardy_count = 0
    max_late = 0.0
    max_exit = 0.0
    max_due = 0.0
    for bid, a in assignments.items():
        try:
            exit_t = float(a["exit_time"])
            due = float(blocks_data[bid]["due_date"])
        except Exception:
            continue
        max_exit = max(max_exit, exit_t)
        max_due = max(max_due, due)
        late = max(0.0, exit_t - due)
        if late > 0:
            tardy_count += 1
            z1 += late
            max_late = max(max_late, late)
    tail_ratio = max_exit / max(1.0, max_due)
    return z1, tardy_count, max_late, tail_ratio


def _choose_repair_mode_from_phase1(prob_info: dict,
                                    phase1_report: dict | None,
                                    assignments: dict[int, dict],
                                    elapsed_phase1: float,
                                    timelimit: float) -> RepairDecision:
    """Choose repair mode from observed Phase-1 symptoms, not instance buckets."""
    blocks_data = prob_info.get("blocks", [])
    n_blocks = len(blocks_data)
    report = phase1_report if isinstance(phase1_report, dict) else {}
    feasible = bool(report.get("feasible") and report.get("objective") is not None)
    stage = report.get("stage")
    if not isinstance(stage, int):
        stage = None
    viols = report.get("violations")
    violation_count = len(viols) if isinstance(viols, list) else 0
    z1, tardy_count, max_late, tail_ratio = _assignment_tardy_stats(assignments, blocks_data)
    elapsed_ratio = elapsed_phase1 / max(1e-9, float(timelimit))
    violation_ratio = violation_count / max(1, n_blocks)
    tardy_ratio = tardy_count / max(1, len(assignments))

    def decision(mode: str, reason: str) -> RepairDecision:
        return RepairDecision(
            mode=mode,
            reason=reason,
            phase1_feasible=feasible,
            phase1_stage=stage,
            violation_count=violation_count,
            elapsed_ratio=elapsed_ratio,
            z1=z1,
            tardy_count=tardy_count,
            tail_ratio=tail_ratio,
        )

    if feasible:
        return decision("greedy", "phase1_feasible")
    if not report:
        return decision("greedy", "phase1_unchecked")

    # Simple repair is a deadline/safety move: it serializes current placements
    # into empty windows. Use it when Phase 1 already consumed a large share of
    # the budget and the checker reports many crane/sequence failures. Avoid it
    # on tardiness blowups because it tends to push exits farther into the tail.
    tardiness_exploding = (
        z1 > max(50.0, 0.5 * n_blocks)
        and (tardy_ratio >= 0.20 or max_late >= 0.15 * max(1.0, tail_ratio * max(1, n_blocks)))
    ) or tail_ratio >= 1.35
    many_violations = violation_count >= max(6, n_blocks // 25)
    crane_or_sequence = stage in (2, 3, 5)
    spatial_many = stage == 4 and violation_count >= max(8, n_blocks // 20)

    # Auxiliary signal (goal §condition-4 permits weights as a *secondary* signal):
    # "simple" serializes placements into empty windows, BUYING feasibility by
    # PAYING tardiness.  That trade is self-defeating when tardiness dominates --
    # on a SMALL w1-dominant instance greedy repair fully recovers Z1 (train
    # prob_2 w1=29091, n=100: mid-run "simple" gave 11.3M where greedy -> ~1e4).
    #
    # BUT (variance safety, goal §priority-1 = variance reduction): greedy repair
    # is BIMODAL on LARGE dense w1-dominant instances -- train prob_18 (n=300):
    # greedy gives 49M (good) OR 922M (±20x explosion) run-to-run, whereas the
    # DETERMINISTIC simple serialization is a stable ~floor (~23.8M every run).
    # So we override toward greedy ONLY on small instances, where it reliably
    # wins; on large ones (the SAME n_blocks>=200 boundary the baseline already
    # uses to arm its verified-checkpoint safety, `enable_checkpoint`) we keep the
    # original symptom path so dense crane violations route to the stable simple
    # serialization and the ±20x explosion never happens.  The size boundary here
    # is a VARIANCE-SAFETY gate (prevent the explosion), not a quality bucket --
    # it reuses an existing structural threshold, not a train-fitted number.
    w = prob_info.get("weights", {}) if isinstance(prob_info, dict) else {}
    w1 = float(w.get("w1", 1.0)); w2 = float(w.get("w2", 1.0)); w3 = float(w.get("w3", 1.0))
    _LARGE_INSTANCE = 200  # == baseline's enable_checkpoint boundary
    tardiness_dominant = (w1 >= 4.0 * max(w2, w3, 1e-9)) and (n_blocks < _LARGE_INSTANCE)

    if elapsed_ratio >= 0.90 and violation_count > 0:
        return decision("simple", "near_deadline_complete_by_serializing")
    if not tardiness_dominant:
        if (not tardiness_exploding and crane_or_sequence
                and violation_ratio >= 0.20 and violation_count >= 20):
            return decision("simple", "dense_crane_violations")
        if not tardiness_exploding and elapsed_ratio >= 0.55 and (
                (crane_or_sequence and (many_violations or violation_ratio >= 0.06))
                or spatial_many):
            return decision("simple", "many_structural_violations_high_elapsed")
    if tardiness_exploding:
        return decision("greedy", "tardiness_tail_needs_greedy_repair")
    return decision("greedy", "default_greedy_repair")


# -----------------------------------------------------------------------------
# Helper: candidate position generation (bottom-left corner based)
# -----------------------------------------------------------------------------

def _candidate_positions(bay_w: float, bay_h: float,
                         placed_blocks: list[Block],
                         blk_bb: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    """
    Return integer (x, y) reference-point candidate positions for a new block
    using the "bottom-left fill" heuristic.

    blk_bb = (local_min_x, local_min_y, local_max_x, local_max_y) in local
    coordinates (reference point = first vertex of first layer = (0, 0)).
    A placement (x, y) is valid iff the block's world bbox stays within the bay:
      x + blk_bb[0] >= 0,  y + blk_bb[1] >= 0
      x + blk_bb[2] <= bay_w,  y + blk_bb[3] <= bay_h
    Candidates are sorted by (x, y) so the search visits left-most / bottom-most
    positions first.
    """
    lx0, ly0, lx1, ly1 = blk_bb
    # Smallest valid integer reference-point position (block's left/bottom edge at bay wall)
    xs = {max(0, math.ceil(-lx0))}
    ys = {max(0, math.ceil(-ly0))}
    for b in placed_blocks:
        bb = b.bounding_rect()
        # Reference-point x/y such that new block's left/bottom edge touches the
        # right/top edge of this placed block
        xs.add(math.ceil(bb[2] - lx0))
        ys.add(math.ceil(bb[3] - ly0))

    # OGC_GREEDY_BL_ONLY (default OFF): classic bottom-left fill -- keep only the
    # LOWEST fitting y per x, capping candidates at O(|xs|) instead of O(|xs|*|ys|).
    # Cuts the greedy Phase-1 position blow-up on large congested bays (prob_20's
    # 300x5 Phase-1 is ~124s); general (a cheaper position policy), gated for A/B.
    _bl_only = os.environ.get("OGC_GREEDY_BL_ONLY", "").strip().lower() in (
        "1", "true", "on", "yes")
    candidates = []
    for x in sorted(xs):
        for y in sorted(ys):
            if x + lx1 <= bay_w + 1e-6 and y + ly1 <= bay_h + 1e-6:
                candidates.append((int(x), int(y)))
                if _bl_only:
                    break
    return candidates


# -----------------------------------------------------------------------------
# Placement score (lower is better)
# -----------------------------------------------------------------------------

def _placement_score(tardiness: float, workload: float,
                     bay_loads: list[float], bay_id: int,
                     pref_penalty: float,
                     bay_weights: list[float],
                     w1: float, w2: float, w3: float,
                     top_y: float = 0.0, w4: float = 1e-4) -> float:
    """
    Composite score for placing a block in bay_id (lower is better).

      w1 * tardiness    -- total tardiness: max(0, exit_time - due_date).

      w2 * new_obj2     -- approximation of normalized load-balance penalty.
                          new_obj2 = max_j |u[bay_id]*new_load - u[j]*load_j|
                          where u_j = avg_bay_area / (W_j * H_j).

      w3 * pref_penalty -- preference penalty: S_i_max - S_i_bay_id.
                          0 when placed in most-preferred bay.

      w4 * top_y        -- tie-breaking: lower top edge -> tighter packing.
    """
    new_load = bay_loads[bay_id] + workload
    new_obj2 = max(
        (abs(bay_weights[bay_id] * new_load - bay_weights[j] * bay_loads[j])
         for j in range(len(bay_loads)) if j != bay_id),
        default=0.0
    )
    return w1 * tardiness + w2 * new_obj2 + w3 * pref_penalty + w4 * top_y


# -----------------------------------------------------------------------------
# Earliest feasible entry slot (aggressive -- allows time overlap)
# -----------------------------------------------------------------------------

def _find_earliest_slot(new_blk: Block,
                        bay: Bay,
                        placed_in_bay: list[Block],
                        schedule_in_bay: list[tuple[int, int]],
                        r_time: int,
                        proc: int) -> tuple[int | None, int | None]:
    """
    Return the earliest (entry, exit_t) time slot >= r_time at which new_blk
    can be crane-placed into bay without violating Stage-2 (entry) or Stage-3
    (exit) feasibility.  Returns (None, None) if no candidate entry passes
    both checks -- this means the (position, bay) combination is infeasible for
    any time and the caller should try a different position.

    -- Candidate enumeration ----------------------------------------------------
    Candidates = {r_time} | {exit_time of every already-placed block in bay}.

    -- Feasibility checks (mirror of check_feasibility Stages 2 & 3) -----------
    Stage-2 (crane entry): the crane path must not be blocked at entry_time.
      present_at_entry = blocks b_k with  a_k <= entry < e_k
      check_entry(bay, present_at_entry, new_blk, fast=True) returns True if
      ANY block in present_at_entry obstructs the crane path; fast=True exits
      on the first obstruction to avoid unnecessary Shapely work.

    Stage-3 (crane exit): the crane path must not be blocked at exit_time.
      present_at_exit  = [new_blk] + blocks b_k with  a_k < exit_t < e_k
      (new_blk itself is included because it will be present during its own exit)
      check_exit(bay, present_at_exit, new_blk, fast=True) returns True if
      ANY block in present_at_exit obstructs the crane exit path.

    Stage-4 (interior-interval): blocks whose interval is strictly inside
      [entry, exit_t) -- i.e. entry < a_k AND e_k < exit_t -- are invisible
      to the Stage-2 and Stage-3 boundary checks above.  They are present
      during new_blk's stay but not at its entry or exit moment.  A per-pair
      spatial collision check is run for these blocks to avoid producing
      Stage-4 violations that the repair loop cannot detect at placement time.
    """
    candidate_entries = sorted({r_time} | {e for _, e in schedule_in_bay if e > r_time})

    for entry_candidate in candidate_entries:
        entry  = max(r_time, entry_candidate)
        exit_t = entry + proc

        # Stage-2: blocks whose interval [a_k, e_k) contains entry_time
        present_at_entry = [
            b for b, (a, e) in zip(placed_in_bay, schedule_in_bay)
            if a <= entry < e
        ]
        if check_entry(bay, present_at_entry, new_blk, fast=True):
            continue  # crane path blocked at entry -> try next exit boundary

        # Stage-3: blocks whose interval [a_k, e_k) strictly contains exit_t
        # (a_k < exit_t AND e_k > exit_t means the block spans across exit_t)
        present_at_exit = [new_blk] + [
            b for b, (a, e) in zip(placed_in_bay, schedule_in_bay)
            if a < exit_t < e
        ]
        if check_exit(bay, present_at_exit, new_blk, fast=True):
            continue  # crane path blocked at exit -> try next exit boundary

        # Stage-4 pre-check: blocks strictly interior to [entry, exit_t).
        # These blocks are invisible to Stage-2 (not yet present at entry)
        # and Stage-3 (already gone at exit), but are physically co-present
        # during [a_k, e_k) -- a subset of [entry, exit_t).  A spatial
        # collision with any such block would cause a Stage-4 violation after
        # placement; catch it here to avoid re-triggering repair passes.
        s4_blocked = False
        for b_other, (a_other, e_other) in zip(placed_in_bay, schedule_in_bay):
            if a_other <= entry or e_other >= exit_t:
                continue  # handled by Stage-2 or Stage-3 above
            if not _time_overlaps(entry, exit_t, a_other, e_other):
                continue  # disjoint in time
            if check_collisions(bay, [new_blk, b_other]):
                s4_blocked = True
                break
        if s4_blocked:
            continue

        return entry, exit_t

    return None, None  # no valid time slot for this (position, bay) combination


# -----------------------------------------------------------------------------
# Guaranteed-feasible entry: empty-bay window
# -----------------------------------------------------------------------------

def _empty_bay_entry(schedule_in_bay: list[tuple[int, int]],
                     r_time: int, proc: int) -> int:
    """
    Return the earliest entry time >= r_time such that the bay is completely
    empty for the entire window [entry, entry + proc).

    This guarantees crane-path feasibility: when the bay is empty at both
    entry_time and exit_time, check_entry and check_exit trivially pass
    (no blocks present means no polygon obstructions).

    Algorithm -- iterative push:
      Start with entry = r_time.  Scan all existing slots (a_k, e_k).  If
      [entry, entry+proc) overlaps any slot, advance entry to e_k (the end of
      that slot) so the window no longer overlaps it.  Repeat until no
      overlaps remain.

    Convergence guarantee:
      Each iteration advances entry by at least the distance to the next
      slot endpoint.  Because the number of slots is finite, the loop
      terminates after at most len(schedule_in_bay) passes.
    """
    entry = int(r_time)
    changed = True
    pushes = 0
    while changed:
        changed = False
        exit_t = entry + proc
        for a, e in schedule_in_bay:
            if _time_overlaps(entry, exit_t, a, e):
                entry = max(entry, e)  # push past the overlapping slot
                changed = True
                pushes += 1
    if bimodal_enabled():
        bimodal_log("baseline_empty_bay_entry",
                    schedule_size=len(schedule_in_bay),
                    r_time=int(r_time), proc=int(proc),
                    entry=int(entry), exit_time=int(entry + proc),
                    pushes=pushes)
    return entry


# -----------------------------------------------------------------------------
# Main algorithm
# -----------------------------------------------------------------------------

def greedyalgorithm(prob_info: dict, timelimit: float,
                    repair_mode: str = "greedy") -> dict:
    """
    EDD + Best-Fit Greedy algorithm with post-hoc feasibility repair.

    Parameters
    ----------
    prob_info   : instance JSON dict with keys "name", "bays", "blocks", "weights"
    timelimit   : wall-clock time limit in seconds
    repair_mode : "greedy" (default), "simple", or "auto" -- see module
                  docstring for details

    Returns
    -------
    solution dict in the format described in the module docstring

    Phase 1 -- EDD greedy placement:
        Blocks sorted by (due_date, processing_time).  For each block, every
        (bay, orientation, candidate position) is tried; _find_earliest_slot
        computes the earliest crane-feasible time slot.  The combination
        minimising _placement_score is committed.  bay_placed, bay_schedule,
        and bay_loads are updated incrementally.

    Phase 2 -- Repair (see _repair and module docstring for details):
        Calls _repair which runs up to max_passes rounds of
        check_feasibility -> re-place violating blocks.
    """
    t_start = time.time()
    greedyalgorithm.last_result = None
    greedyalgorithm.last_checkpoint_result = None
    greedyalgorithm.last_phase1_result = None
    greedyalgorithm.last_repair_decision = None

    bays_data   = prob_info["bays"]
    blocks_data = prob_info["blocks"]
    n_bays      = len(bays_data)
    n_blocks    = len(blocks_data)
    inst_name   = str(prob_info.get("name", "?"))

    w1 = prob_info.get("weights", {}).get("w1", 1.0)
    w2 = prob_info.get("weights", {}).get("w2", 1.0)
    w3 = prob_info.get("weights", {}).get("w3", 1.0)

    # P1 guard: keep enough wall-clock for feasibility checks and returning a
    # verified incumbent.  The caller may pass a reduced timelimit; all guards
    # are relative to that local budget.
    check_margin = min(1.0, 2e-5 * n_blocks * n_blocks + 0.05)
    soft_stop_abs = t_start + 0.94 * timelimit
    hard_stop_abs = t_start + 0.98 * timelimit

    from utils import check_feasibility

    best_verified_sol = None
    best_verified_result = None
    best_verified_label = None
    best_verified_obj = float("inf")
    enable_checkpoint = n_blocks >= 200

    def checkpoint(label: str, cur_assignments: dict[int, dict],
                   result: dict | None = None) -> bool:
        """Verify and store the best complete feasible solution seen so far."""
        nonlocal best_verified_sol, best_verified_result
        nonlocal best_verified_label, best_verified_obj
        if not enable_checkpoint:
            return False
        if len(cur_assignments) != n_blocks:
            return False
        now = time.time()
        if result is None and now + check_margin >= hard_stop_abs:
            return False
        sol_cp = {"operations": _build_operations(list(cur_assignments.values()))}
        if result is None:
            try:
                result = check_feasibility(prob_info, sol_cp)
            except Exception:
                return False
        feasible = bool(result.get("feasible") and result.get("objective") is not None)
        obj = result.get("objective") if feasible else None
        adopted = bool(feasible and obj < best_verified_obj - 1e-9)
        if adopted:
            best_verified_sol = sol_cp
            best_verified_result = result
            best_verified_label = label
            best_verified_obj = obj
            greedyalgorithm.last_checkpoint_result = result
        if bimodal_enabled():
            bimodal_log("baseline_checkpoint",
                        label=label,
                        feasible=feasible,
                        stage=result.get("stage"),
                        objective=obj,
                        adopted=adopted,
                        best_objective=(None if best_verified_obj == float("inf")
                                        else best_verified_obj),
                        elapsed=round(time.time() - t_start, 6))
        return adopted

    bimodal_start(inst_name, instance=inst_name, component="baseline_greedy",
                  n_blocks=n_blocks, n_bays=n_bays, timelimit=float(timelimit),
                  pythonhashseed=os.environ.get("PYTHONHASHSEED"))
    if bimodal_enabled():
        bimodal_log("baseline_start", repair_mode=repair_mode,
                    w1=w1, w2=w2, w3=w3)

    print(f"[Greedy] Instance : {prob_info.get('name', '?')}")
    print(f"[Greedy] Bays     : {n_bays}  |  Blocks : {n_blocks}  |  Timelimit : {timelimit:.1f}s")
    print(f"[Greedy] Weights  : w1={w1}  w2={w2}  w3={w3}")
    print(f"[Greedy] {'-' * 56}")

    bays = [Bay.from_dict(d, i) for i, d in enumerate(bays_data)]
    for i, b in enumerate(bays):
        print(f"[Greedy]   bay[{i}]  {b.width}x{b.height}")

    # -- Phase 1: aggressive greedy --------------------------------------------
    sorted_indices = sorted(
        range(n_blocks),
        key=lambda i: (blocks_data[i]["due_date"], blocks_data[i]["processing_time"])
    )
    print(f"[Greedy] {'-' * 56}")
    print("[Greedy] Phase 1 : EDD greedy placement ...")

    bay_placed:   list[list[Block]]             = [[] for _ in range(n_bays)]
    bay_schedule: list[list[tuple[int, int]]]   = [[] for _ in range(n_bays)]
    bay_loads:    list[float]                   = [0.0] * n_bays

    assignments = _place_blocks(
        sorted_indices, blocks_data, bays,
        bay_placed, bay_schedule, bay_loads,
        w1, w2, w3, forced_ids=set(),
        t_start=t_start, log_interval=max(1, n_blocks // 10),
        phase_name="phase1",
    )

    elapsed_p1 = time.time() - t_start
    phase1_z1 = _assignment_z1(assignments, blocks_data)
    if bimodal_enabled():
        bimodal_log("baseline_phase1_done",
                    elapsed=round(elapsed_p1, 6),
                    placed=len(assignments), total=n_blocks,
                    progress_ratio=(len(assignments) / n_blocks if n_blocks else 1.0),
                    z1=phase1_z1,
                    loads=[round(v, 6) for v in bay_loads])
    loads_str = "  ".join(f"bay{i}={round(bay_loads[i])}" for i in range(n_bays))
    print(f"[Greedy] Phase 1 done  |  placed={len(assignments)}  {loads_str}  "
          f"elapsed={elapsed_p1:.2f}s")
    phase1_sol = {"operations": _build_operations(list(assignments.values()))}
    phase1_result = None
    if len(assignments) == n_blocks and time.time() + check_margin < hard_stop_abs:
        try:
            phase1_result = check_feasibility(prob_info, phase1_sol)
            greedyalgorithm.last_phase1_result = phase1_result
        except Exception:
            phase1_result = None
    checkpoint("phase1", assignments, phase1_result)

    selected_repair_mode = repair_mode
    if repair_mode == "auto":
        dec = _choose_repair_mode_from_phase1(
            prob_info, phase1_result, assignments, elapsed_p1, timelimit)
        selected_repair_mode = dec.mode
        greedyalgorithm.last_repair_decision = dec
    elif repair_mode not in ("greedy", "simple"):
        selected_repair_mode = "greedy"
        greedyalgorithm.last_repair_decision = RepairDecision(
            mode="greedy",
            reason=f"invalid_mode:{repair_mode}",
            phase1_feasible=False,
            phase1_stage=None,
            violation_count=0,
            elapsed_ratio=elapsed_p1 / max(1e-9, float(timelimit)),
            z1=phase1_z1,
            tardy_count=0,
            tail_ratio=0.0,
        )
    else:
        greedyalgorithm.last_repair_decision = RepairDecision(
            mode=selected_repair_mode,
            reason="explicit_mode",
            phase1_feasible=bool(phase1_result and phase1_result.get("feasible")),
            phase1_stage=(phase1_result.get("stage") if isinstance(phase1_result, dict) else None),
            violation_count=(len(phase1_result.get("violations", []))
                             if isinstance(phase1_result, dict)
                             and isinstance(phase1_result.get("violations"), list)
                             else 0),
            elapsed_ratio=elapsed_p1 / max(1e-9, float(timelimit)),
            z1=phase1_z1,
            tardy_count=0,
            tail_ratio=0.0,
        )
    if bimodal_enabled() and greedyalgorithm.last_repair_decision is not None:
        dec = greedyalgorithm.last_repair_decision
        bimodal_log("baseline_repair_decision",
                    requested_mode=repair_mode,
                    selected_mode=dec.mode,
                    reason=dec.reason,
                    phase1_feasible=dec.phase1_feasible,
                    phase1_stage=dec.phase1_stage,
                    violations=dec.violation_count,
                    elapsed_ratio=round(dec.elapsed_ratio, 6),
                    z1=dec.z1,
                    tardy_count=dec.tardy_count,
                    tail_ratio=round(dec.tail_ratio, 6))

    # -- Phase 2: repair infeasible assignments --------------------------------
    print(f"[Greedy] {'-' * 56}")
    print(f"[Greedy] Phase 2 : repair  mode={selected_repair_mode}"
          f"  requested={repair_mode}")
    sol = phase1_sol
    assignments = _repair(prob_info, sol, assignments, bays, blocks_data,
                          w1, w2, w3, t_start, timelimit,
                          repair_mode=selected_repair_mode,
                          checkpoint=checkpoint,
                          soft_stop_abs=soft_stop_abs,
                          hard_stop_abs=hard_stop_abs,
                          check_margin=check_margin)

    elapsed_total = time.time() - t_start
    final_sol = {"operations": _build_operations(list(assignments.values()))}

    final_result = check_feasibility(prob_info, final_sol)
    final_feasible = bool(final_result.get("feasible")
                          and final_result.get("objective") is not None)
    if final_feasible:
        checkpoint("final", assignments, final_result)

    return_sol = final_sol
    return_result = final_result
    return_label = "final"
    if best_verified_sol is not None:
        final_obj = (final_result.get("objective")
                     if final_feasible else float("inf"))
        if (not final_feasible) or best_verified_obj <= final_obj - 1e-9:
            return_sol = best_verified_sol
            return_result = best_verified_result
            return_label = f"checkpoint:{best_verified_label}"

    print(f"[Greedy] {'-' * 56}")
    print(f"[Greedy] Done  |  assigned={len(assignments)}/{n_blocks}  "
          f"elapsed={elapsed_total:.2f}s")
    if return_label != "final":
        print(f"[Greedy] Return   : {return_label}")
    if return_result["feasible"]:
        print(f"[Greedy] Objective : {return_result['objective']:.0f}  "
              f"(obj1={return_result['obj1']:.1f}  "
              f"obj2={return_result['obj2']:.1f}  "
              f"obj3={return_result['obj3']:.1f})")
    else:
        print(f"[Greedy] INFEASIBLE stage={return_result['stage']}")
        for v in return_result["violations"][:5]:
            print(f"[Greedy]   {v}")

    if bimodal_enabled():
        bimodal_log("baseline_done",
                    elapsed=round(elapsed_total, 6),
                    assigned=len(assignments), total=n_blocks,
                    feasible=bool(return_result.get("feasible")),
                    stage=return_result.get("stage"),
                    objective=return_result.get("objective"),
                    obj1=return_result.get("obj1"),
                    obj2=return_result.get("obj2"),
                    obj3=return_result.get("obj3"),
                    returned_label=return_label)

    greedyalgorithm.last_result = return_result
    return return_sol


# -----------------------------------------------------------------------------
# Force-place helper (no feasibility check -- used as phase-1 last resort)
# -----------------------------------------------------------------------------

def _force_place(bi: int,
                 blocks_data: list[dict],
                 bays: list[Bay],
                 bay_schedule: list[list[tuple[int, int]]],
                 prefs: list[float],
                 w1: float = 1.0, w2: float = 1.0, w3: float = 1.0,
                 bay_loads: list[float] | None = None,
                 bay_weights: list[float] | None = None) -> tuple:
    """
    Fallback placement: place block bi at the minimum valid position in the
    highest-preference bay whose dimensions accommodate the block, using
    an empty-bay entry window.

    When called:
      * _place_blocks found no feasible (position, bay, time-slot) combination
        during Phase-1 search (should be rare for well-formed instances).
      * bi is in forced_ids during repair -- the block has appeared in two or
        more consecutive repair passes, indicating a crane-path cycle.  Forcing
        it to an empty-bay window breaks the cycle by guaranteeing that both
        check_entry and check_exit trivially pass (bay is empty).

    Why minimum-valid position with empty-bay window is always feasible:
      _empty_bay_entry returns a time interval [entry, exit_t) during which no
      other block occupies the bay.  With the bay empty at both entry_time and
      exit_time, check_entry/check_exit have no polygon obstructions to report,
      so Stage-2 and Stage-3 always pass regardless of block shape or position.
      The minimum-valid position (max(0, ceil(-lx0)), max(0, ceil(-ly0)))
      ensures the block's bounding box starts at the bay's lower-left corner,
      so the bay boundary check also passes.

    Orientation selection: the first orientation whose footprint fits within
    the bay is used.  If no orientation fits (degenerate instance), the
    preferred bay with orientation 0 is used as an absolute last resort.

    Position selection: the minimum valid reference-point position is used,
    i.e. (max(0, ceil(-lx0)), max(0, ceil(-ly0))) derived from the block's
    local bounding box.  This ensures the block's world bounding box starts at
    the bay's lower-left corner regardless of which vertex is the reference
    point.  Placing at (0, 0) would be wrong when lx0 < 0 or ly0 < 0.
    """
    # NOTE: the force-place bay choice is left as the official pref-ordered
    # first-fitting fallback.  An experiment routing forced blocks by
    # tardiness/earliest-entry helped some congested instances but SILENTLY
    # REGRESSED others (prob_13 40M -> 924M) and was contention-dependent, because
    # it changes the greedy FLOOR (which is returned directly, un-gated, on large
    # instances).  The safe lever is instead the verified, check_feasibility-gated
    # postprocess left-shift in myalgorithm (_fixed_layout_reschedule), which can
    # only improve, plus the Phase-1 deadline that keeps enough budget for it to
    # run.  So this stays the original behaviour; w1/w2/w3/bay_loads/bay_weights
    # are accepted only for forward-compatibility and are unused here.
    blk_data = blocks_data[bi]
    r_time   = blk_data["release_time"]
    proc     = blk_data["processing_time"]
    n_bays   = len(bays)

    for bay_id in sorted(range(n_bays), key=lambda j: prefs[j], reverse=True):
        bay = bays[bay_id]
        for oi in range(len(blk_data["shape"])):
            bw, bh = _block_size(blk_data, oi)
            if bw <= bay.width + 1e-6 and bh <= bay.height + 1e-6:
                bb = _block_bbox(blk_data, oi)
                px = max(0, math.ceil(-bb[0]))
                py = max(0, math.ceil(-bb[1]))
                nb = Block(block_id=bi, block_data=blk_data,
                           x=px, y=py, orient_idx=oi)
                if not bay.contains_block(nb):
                    continue
                entry = _empty_bay_entry(bay_schedule[bay_id], r_time, proc)
                return (bay_id, px, py, oi, entry, entry + proc)

    # absolute last resort -- ignore fit
    bay_id = max(range(n_bays), key=lambda j: prefs[j])
    bb     = _block_bbox(blk_data, 0)
    px     = max(0, math.ceil(-bb[0]))
    py     = max(0, math.ceil(-bb[1]))
    entry  = _empty_bay_entry(bay_schedule[bay_id], r_time, proc)
    return (bay_id, px, py, 0, entry, entry + proc)


# -----------------------------------------------------------------------------
# Shared greedy placement kernel (used by Phase 1 and _repair)
# -----------------------------------------------------------------------------

def _place_blocks(
    block_ids: list[int],
    blocks_data: list[dict],
    bays: list[Bay],
    bay_placed: list[list[Block]],
    bay_schedule: list[list[tuple[int, int]]],
    bay_loads: list[float],
    w1: float, w2: float, w3: float,
    forced_ids: set[int],
    prev_assignments: dict[int, dict] | None = None,
    t_start: float | None = None,
    log_interval: int = 0,
    phase_name: str = "place",
    force_after: float | None = None,
) -> dict[int, dict]:
    """
    Shared placement kernel used by both Phase 1 and _repair (greedy mode).

    For each block in block_ids, finds the best (bay, x, y, orient, entry_time)
    by minimising _placement_score, then commits it to bay_placed /
    bay_schedule / bay_loads.  Returns a dict mapping block_id -> assignment.

    Search order:
      1. Repair fast-path (only when prev_assignments is provided):
         Try the block's previous (bay, x, y, orient) with _find_earliest_slot.
         If that position is still crane-feasible, record it as the initial
         best candidate.  This avoids re-solving the position search for blocks
         that only need a time adjustment.
      2. Full search (Phase-1 style):
         Iterate bays in decreasing preference order, then orientations, then
         candidate positions from _candidate_positions.  For each (bay, orient,
         pos), call _find_earliest_slot to get the earliest crane-feasible slot.
         Keep the (bay, orient, pos, slot) with the lowest _placement_score.
      3. Forced path (forced_ids or no feasible combination found):
         Blocks in forced_ids skip steps 1-2 entirely and go straight to
         _force_place.  If the full search in step 2 found nothing, _force_place
         is used as a fallback and n_fallback is incremented.

    Parameters
    ----------
    block_ids        : ordered list of block indices to place (EDD order)
    blocks_data      : raw block data list from prob_info
    bays             : Bay objects (width, height, polygon)
    bay_placed       : mutable per-bay lists of placed Block objects (updated in-place)
    bay_schedule     : mutable per-bay lists of (entry_time, exit_time) (updated in-place)
    bay_loads        : mutable per-bay cumulative workload floats (updated in-place)
    w1, w2, w3       : objective weights
    forced_ids       : block ids to bypass search and use _force_place directly
    prev_assignments : previous assignment dict (repair mode fast-path)
    t_start          : wall-clock start time (for log timestamps)
    log_interval     : print a progress line every N blocks (0 = silent)

    Returns
    -------
    dict[block_id -> assignment dict] for all blocks in block_ids
    """
    n_bays  = len(bays)
    n_total = len(block_ids)
    result: dict[int, dict] = {}
    n_forced = n_fallback = 0

    # Bay weights for normalized obj2: u_j = avg_area / (W_j * H_j)
    _bay_areas   = [bay.width * bay.height for bay in bays]
    _avg_area    = sum(_bay_areas) / n_bays
    bay_weights  = [_avg_area / a for a in _bay_areas]

    for rank, bi in enumerate(block_ids):
        blk_data = blocks_data[bi]
        r_time   = blk_data["release_time"]
        due      = blk_data["due_date"]
        proc     = blk_data["processing_time"]
        workload = blk_data["workload"]
        prefs    = blk_data["bay_preferences"]
        s_max    = max(prefs)
        n_orient = len(blk_data["shape"])

        best_score     = float("inf")
        best_placement = None
        forced_by_deadline = (
            force_after is not None and time.time() >= force_after
        )
        used_forced    = bi in forced_ids or forced_by_deadline
        force_reason   = (
            "forced_id" if bi in forced_ids
            else "deadline_guard" if forced_by_deadline
            else None
        )

        if not used_forced:
            # -- Repair fast-path: try previous (bay, x, y, orient) first -----
            if prev_assignments and bi in prev_assignments:
                pa = prev_assignments[bi]
                pb_id = pa["bay_id"]
                px, py, poi = int(pa["x"]), int(pa["y"]), pa["orient_idx"]
                prev_blk = Block(block_id=bi, block_data=blk_data,
                                 x=px, y=py, orient_idx=poi)
                if bays[pb_id].contains_block(prev_blk):
                    entry, exit_t = _find_earliest_slot(
                        prev_blk, bays[pb_id],
                        bay_placed[pb_id], bay_schedule[pb_id],
                        r_time, proc
                    )
                    if entry is not None:
                        tardiness = max(0.0, exit_t - due)
                        p_bb = _block_bbox(blk_data, poi)
                        best_score     = _placement_score(
                            tardiness, workload, bay_loads, pb_id,
                            s_max - prefs[pb_id], bay_weights, w1, w2, w3,
                            top_y=py + p_bb[3]
                        )
                        best_placement = (pb_id, px, py, poi, entry, exit_t)

            # -- Full search (Phase-1 style) -----------------------------------
            bay_order = sorted(range(n_bays), key=lambda j: prefs[j], reverse=True)
            for bay_id in bay_order:
                bay             = bays[bay_id]
                placed_in_bay   = bay_placed[bay_id]
                schedule_in_bay = bay_schedule[bay_id]

                for oi in range(n_orient):
                    blk_bb = _block_bbox(blk_data, oi)
                    bw = blk_bb[2] - blk_bb[0]
                    bh = blk_bb[3] - blk_bb[1]
                    if bw > bay.width + 1e-6 or bh > bay.height + 1e-6:
                        continue

                    active_in_bay = [
                        b for b, (a_k, e_k) in zip(placed_in_bay, schedule_in_bay)
                        if e_k > r_time
                    ]
                    candidates = _candidate_positions(
                        bay.width, bay.height, active_in_bay, blk_bb
                    )
                    for (cx, cy) in candidates:
                        new_blk = Block(block_id=bi, block_data=blk_data,
                                        x=cx, y=cy, orient_idx=oi)
                        if not bay.contains_block(new_blk):
                            continue

                        entry, exit_t = _find_earliest_slot(
                            new_blk, bay, placed_in_bay, schedule_in_bay,
                            r_time, proc
                        )
                        if entry is None:
                            continue

                        tardiness = max(0.0, exit_t - due)
                        score = _placement_score(
                            tardiness, workload, bay_loads, bay_id,
                            s_max - prefs[bay_id], bay_weights, w1, w2, w3,
                            top_y=cy + blk_bb[3]
                        )
                        if score < best_score:
                            best_score     = score
                            best_placement = (bay_id, cx, cy, oi, entry, exit_t)

        if best_placement is None:
            force_reason = force_reason or "fallback_no_candidate"
            best_placement = _force_place(bi, blocks_data, bays, bay_schedule, prefs,
                                           w1, w2, w3, bay_loads, bay_weights)
            n_fallback += 1

        if used_forced:
            n_forced += 1

        bay_id, cx, cy, oi, entry, exit_t = best_placement
        final_blk = Block(block_id=bi, block_data=blk_data, x=cx, y=cy, orient_idx=oi)
        bay_placed[bay_id].append(final_blk)
        bay_schedule[bay_id].append((entry, exit_t))
        bay_loads[bay_id] += workload

        result[bi] = {
            "block_id":   bi,
            "bay_id":     bay_id,
            "x":          int(round(cx)),
            "y":          int(round(cy)),
            "orient_idx": oi,
            "entry_time": int(round(entry)),
            "exit_time":  int(round(exit_t)),
        }

        if bimodal_enabled():
            elapsed = None if t_start is None else round(time.time() - t_start, 6)
            ev = {
                "phase": phase_name,
                "rank": rank,
                "n_done": rank + 1,
                "n_total": n_total,
                "progress_ratio": ((rank + 1) / n_total if n_total else 1.0),
                "block_id": bi,
                "bay_id": int(bay_id),
                "x": int(round(cx)),
                "y": int(round(cy)),
                "orient_idx": int(oi),
                "entry_time": int(round(entry)),
                "exit_time": int(round(exit_t)),
                "forced": force_reason is not None,
                "force_reason": force_reason,
                "fallback_count": n_fallback,
                "forced_id_count": n_forced,
                "elapsed": elapsed,
            }
            bimodal_log("baseline_placement", **ev)
            if force_reason is not None:
                bimodal_log("baseline_force_place", **ev)

        if log_interval > 0 and t_start is not None:
            n_done = rank + 1
            if n_done % log_interval == 0 or n_done == n_total:
                elapsed = time.time() - t_start
                loads_str = " ".join(f"b{i}={round(bay_loads[i])}" for i in range(n_bays))
                flag = " [forced]" if used_forced else (" [fallback]" if best_score == float("inf") else "")
                print(f"[Greedy]   {n_done:4d}/{n_total}"
                      f"  block{bi:<4d} -> bay{bay_id} ({cx},{cy}) oi={oi}"
                      f"  t=[{int(round(entry))},{int(round(exit_t))})"
                      f"  loads=[{loads_str}]"
                      f"  fallback={n_fallback}{flag}"
                      f"  {elapsed:.1f}s")

    return result


# -----------------------------------------------------------------------------
# Phase 2: repair infeasible blocks
# -----------------------------------------------------------------------------

def _repair(prob_info: dict,
            sol: dict,
            assignments: dict[int, dict],
            bays: list[Bay],
            blocks_data: list[dict],
            w1: float, w2: float, w3: float,
            t_start: float,
            timelimit: float,
            max_passes: int = 10,
            repair_mode: str = "greedy",
            checkpoint=None,
            soft_stop_abs: float | None = None,
            hard_stop_abs: float | None = None,
            check_margin: float = 0.25) -> dict[int, dict]:
    """
    Iteratively detect infeasible blocks and repair them.

    Runs up to max_passes rounds of: check_feasibility -> collect violating
    block ids -> re-place them.  Stops early if the solution becomes feasible
    or 98% of timelimit is consumed.

    -- repair_mode="greedy" (default) ------------------------------------------
    Violating blocks are removed from assignments and re-placed using the full
    Phase-1 search (all bays, orientations, positions, time-slots).  The state
    arrays (bay_placed, bay_schedule, bay_loads) are reconstructed from the
    remaining non-violating assignments before each block is re-placed, so the
    search sees the current bay state.

    Cycle detection:
      repaired_counts[bid] tracks how many repair passes have touched block bid.
      If bid appears in a second pass (count > 1) it is added to forced_ids.
      Blocks in forced_ids skip search and go straight to _force_place (empty-
      bay window), which is structurally guaranteed to produce a crane-feasible
      placement.  This breaks cycles where two blocks keep displacing each other.

    Time guard (90% threshold):
      For each block in to_repair, if wall-clock time > 90% of timelimit before
      its turn, it is added to forced_ids.  This ensures all blocks are assigned
      before timeout rather than leaving some unassigned (Stage-1 failure).

    -- repair_mode="simple" -----------------------------------------------------
    Each violating block keeps its current (bay, x, y, orient) and is only
    pushed to the next empty-bay time window via _empty_bay_entry.  Stage-4
    violations (spatial collision) are also reset to position (0, 0).
    Faster than greedy mode, but cannot improve spatial placement quality.

    Parameters
    ----------
    prob_info   : instance JSON dict
    sol         : current solution dict (operations format)
    assignments : current assignment dict (block_id -> assignment dict)
    bays        : Bay objects
    blocks_data : raw block data from prob_info
    w1,w2,w3    : objective weights
    t_start     : wall-clock start time
    timelimit   : total wall-clock time limit
    max_passes  : maximum number of repair iterations
    repair_mode : "greedy" or "simple"

    Returns
    -------
    Updated assignments dict (all blocks assigned)
    """
    from utils import check_feasibility

    repaired_counts: dict[int, int] = {}
    forced_ids:      set[int]       = set()

    for pass_idx in range(max_passes):
        now = time.time()
        if hard_stop_abs is not None and now + check_margin >= hard_stop_abs:
            break
        if time.time() - t_start > timelimit * 0.98:
            break

        result = check_feasibility(prob_info, sol)
        if result["feasible"]:
            if checkpoint is not None:
                checkpoint(f"repair_pass_{pass_idx}_start", assignments, result)
            break

        viols = result["violations"]
        elapsed_r = time.time() - t_start
        print(f"[Greedy] Repair pass {pass_idx+1}: {len(viols)} violation(s)  "
              f"stage={result['stage']}  elapsed={elapsed_r:.1f}s")
        if bimodal_enabled():
            bimodal_log("baseline_repair_pass",
                        pass_idx=pass_idx + 1,
                        violations=len(viols),
                        stage=result.get("stage"),
                        feasible=bool(result.get("feasible")),
                        objective=result.get("objective"),
                        obj1=result.get("obj1"),
                        elapsed=round(elapsed_r, 6))

        # -- Parse block ids from violation messages ---------------------------
        # Each violation string contains "block <id>" somewhere in the text.
        # Deduplicate while preserving first-occurrence order.
        to_repair: list[int] = []
        seen: set[int] = set()
        for v in viols:
            try:
                bid = int(v.split("block ")[1].split()[0])
                if bid not in seen:
                    seen.add(bid)
                    to_repair.append(bid)
            except (IndexError, ValueError):
                pass

        if not to_repair:
            break

        # Re-place in EDD order so earlier-due blocks get the best slots first
        to_repair.sort(key=lambda b: (blocks_data[b]["due_date"],
                                      blocks_data[b]["processing_time"]))
        n_repl = len(to_repair)

        if repair_mode == "simple":
            # -- Simple mode: adjust only the time window, keep position/orient -
            # Rebuild the per-bay time schedule from all current assignments so
            # that _empty_bay_entry can find a gap with no other blocks present.
            n_bays = len(bays)
            bay_schedule: list[list[tuple[int, int]]] = [[] for _ in range(n_bays)]
            for a in assignments.values():
                bay_schedule[a["bay_id"]].append((a["entry_time"], a["exit_time"]))

            for ri, bid in enumerate(to_repair):
                if hard_stop_abs is not None and time.time() + check_margin >= hard_stop_abs:
                    break
                a      = assignments[bid]
                bay_id = a["bay_id"]
                r_time = blocks_data[bid]["release_time"]
                proc   = blocks_data[bid]["processing_time"]

                # Remove the block's current slot before searching for a new one
                old_slot = (a["entry_time"], a["exit_time"])
                if old_slot in bay_schedule[bay_id]:
                    bay_schedule[bay_id].remove(old_slot)

                entry  = _empty_bay_entry(bay_schedule[bay_id], r_time, proc)
                exit_t = entry + proc

                # Stage-4 (spatial collision): also reset position to (0,0)
                # to eliminate any spatial overlap with other blocks
                x, y, oi = a["x"], a["y"], a["orient_idx"]
                if result["stage"] == 4:
                    x, y = 0, 0

                assignments[bid] = dict(a, x=x, y=y, orient_idx=oi,
                                        entry_time=int(round(entry)),
                                        exit_time=int(round(exit_t)))
                bay_schedule[bay_id].append((entry, exit_t))

                prev_t = f"[{a['entry_time']},{a['exit_time']})"
                new_t  = f"[{entry},{exit_t})"
                tag    = "[s4->(0,0)]" if result["stage"] == 4 else "[time]"
                elapsed_ri = time.time() - t_start
                print(f"[Greedy]   repair {ri+1:3d}/{n_repl}"
                      f"  block{bid:<4d} {tag}"
                      f"  bay{bay_id} ({int(x)},{int(y)})"
                      f"  {prev_t} -> {new_t}"
                      f"  elapsed={elapsed_ri:.1f}s")

        else:
            # -- Greedy mode: full Phase-1 re-search for violating blocks ------
            # Mark repeat offenders as forced before touching assignments, so
            # the flag is active when _place_blocks processes them below.
            for bid in to_repair:
                repaired_counts[bid] = repaired_counts.get(bid, 0) + 1
                if repaired_counts[bid] > 1:
                    if bimodal_enabled() and bid not in forced_ids:
                        bimodal_log("baseline_force_mark",
                                    phase="repair",
                                    reason="repeat_violation",
                                    block_id=bid,
                                    pass_idx=pass_idx + 1,
                                    repaired_count=repaired_counts[bid],
                                    elapsed=round(time.time() - t_start, 6))
                    forced_ids.add(bid)

            # Remove violating blocks from assignments so the state reconstruction
            # below does not include their (now invalid) positions/slots.
            for bid in to_repair:
                assignments.pop(bid, None)

            # Reconstruct bay_placed / bay_schedule / bay_loads from the
            # remaining valid assignments.  This gives _place_blocks an accurate
            # view of which positions and time-slots are already occupied.
            n_bays = len(bays)
            bay_placed:    list[list[Block]]            = [[] for _ in range(n_bays)]
            bay_schedule2: list[list[tuple[int, int]]]  = [[] for _ in range(n_bays)]
            bay_loads:     list[float]                  = [0.0] * n_bays

            for a in assignments.values():
                bid_a  = a["block_id"]
                bay_id = a["bay_id"]
                blk    = Block(block_id=bid_a, block_data=blocks_data[bid_a],
                               x=int(a["x"]), y=int(a["y"]), orient_idx=a["orient_idx"])
                bay_placed[bay_id].append(blk)
                bay_schedule2[bay_id].append((a["entry_time"], a["exit_time"]))
                bay_loads[bay_id] += blocks_data[bid_a]["workload"]

            for ri, bi in enumerate(to_repair):
                if hard_stop_abs is not None and time.time() + check_margin >= hard_stop_abs:
                    break
                # Time guard: switch to forced path when 90% of timelimit is used.
                # Without this, a slow repair search could exhaust the timelimit
                # before all blocks are placed, causing Stage-1 (assignment) failures.
                if time.time() - t_start > timelimit * 0.90:
                    if bimodal_enabled() and bi not in forced_ids:
                        elapsed_guard = time.time() - t_start
                        bimodal_log("baseline_force_mark",
                                    phase="repair",
                                    reason="time_guard_0.90",
                                    block_id=bi,
                                    pass_idx=pass_idx + 1,
                                    repair_rank=ri,
                                    n_repair=n_repl,
                                    progress_ratio=(ri / n_repl if n_repl else 1.0),
                                    elapsed=round(elapsed_guard, 6),
                                    timelimit=float(timelimit))
                    forced_ids.add(bi)
                if soft_stop_abs is not None and time.time() >= soft_stop_abs:
                    if bimodal_enabled() and bi not in forced_ids:
                        elapsed_guard = time.time() - t_start
                        bimodal_log("baseline_force_mark",
                                    phase="repair",
                                    reason="soft_stop_guard",
                                    block_id=bi,
                                    pass_idx=pass_idx + 1,
                                    repair_rank=ri,
                                    n_repair=n_repl,
                                    progress_ratio=(ri / n_repl if n_repl else 1.0),
                                    elapsed=round(elapsed_guard, 6),
                                    timelimit=float(timelimit))
                    forced_ids.add(bi)
                prev_a  = assignments.get(bi)
                partial = _place_blocks(
                    [bi], blocks_data, bays,
                    bay_placed, bay_schedule2, bay_loads,
                    w1, w2, w3, forced_ids,
                    prev_assignments=assignments,
                    phase_name="repair",
                )
                assignments.update(partial)
                new_a       = partial[bi]
                is_forced   = bi in forced_ids
                changed_bay = prev_a and prev_a["bay_id"] != new_a["bay_id"]
                changed_pos = prev_a and (prev_a["x"] != new_a["x"]
                                          or prev_a["y"] != new_a["y"])
                tag = ("[forced]" if is_forced
                       else "[bay]" if changed_bay
                       else "[pos]" if changed_pos
                       else "[time]")
                prev_t = (f"[{int(prev_a['entry_time'])},{int(prev_a['exit_time'])})"
                          if prev_a else "N/A")
                new_t  = f"[{int(new_a['entry_time'])},{int(new_a['exit_time'])})"
                elapsed_ri = time.time() - t_start
                print(f"[Greedy]   repair {ri+1:3d}/{n_repl}"
                      f"  block{bi:<4d} {tag}"
                      f"  bay{new_a['bay_id']} ({int(new_a['x'])},{int(new_a['y'])})"
                      f"  {prev_t} -> {new_t}"
                      f"  elapsed={elapsed_ri:.1f}s")

        sol = {"operations": _build_operations(list(assignments.values()))}
        if checkpoint is not None:
            checkpoint(f"repair_pass_{pass_idx+1}_end", assignments)

    if hard_stop_abs is not None and time.time() + check_margin >= hard_stop_abs:
        return assignments

    result = check_feasibility(prob_info, sol)
    if checkpoint is not None and result.get("feasible"):
        checkpoint("repair_done", assignments, result)
    status = "feasible" if result["feasible"] else f"INFEASIBLE stage={result['stage']}"
    obj    = f"obj={result['objective']:.0f}" if result["feasible"] else ""
    forced_note = f"  forced={len(forced_ids)}" if forced_ids else ""
    elapsed_done = time.time() - t_start
    print(f"[Greedy] Repair done  |  {status}  {obj}{forced_note}  elapsed={elapsed_done:.1f}s")
    if bimodal_enabled():
        bimodal_log("baseline_repair_done",
                    feasible=bool(result.get("feasible")),
                    stage=result.get("stage"),
                    objective=result.get("objective"),
                    obj1=result.get("obj1"),
                    obj2=result.get("obj2"),
                    obj3=result.get("obj3"),
                    forced_count=len(forced_ids),
                    forced_set=sorted(forced_ids),
                    assigned=len(assignments),
                    total=len(blocks_data),
                    progress_ratio=(len(assignments) / len(blocks_data)
                                    if blocks_data else 1.0),
                    elapsed=round(elapsed_done, 6))

    return assignments


# -----------------------------------------------------------------------------
# Build operations dict from assignments
# -----------------------------------------------------------------------------

def _build_operations(assignments: list[dict]) -> dict:
    """
    Build the "operations" dict from a flat list of assignment dicts.

    Groups operations by integer time-point into buckets, sorts each bucket
    so that EXIT operations precede ENTRY operations at the same time, and
    within each type sorts by block_id for deterministic ordering.

    Bucket tuple format: (sort_key, type_str, block_id, bay_id, x, y, orient_idx)
      sort_key = 0 for EXIT  -> sorts before
      sort_key = 1 for ENTRY -> sorts after
    The sort key ensures EXIT-before-ENTRY without explicit type-string comparison.

    The returned dict maps str(time_int) -> list of operation dicts, ordered as
    required by check_feasibility (EXIT ops first within each time-point).
    """
    buckets: dict[int, list[tuple]] = {}
    for a in assignments:
        t_entry = int(a["entry_time"])
        t_exit  = int(a["exit_time"])
        bid     = a["block_id"]
        bay     = a["bay_id"]
        buckets.setdefault(t_exit,  []).append((0, "EXIT",  bid, bay, None,    None,    None))
        buckets.setdefault(t_entry, []).append((1, "ENTRY", bid, bay, a["x"], a["y"], a["orient_idx"]))

    operations: dict[str, list[dict]] = {}
    for t in sorted(buckets):
        ops = sorted(buckets[t], key=lambda x: (x[0], x[2]))
        result = []
        for _, kind, bid, bay, x, y, orient_idx in ops:
            op: dict = {"type": kind, "block_id": bid, "bay_id": bay}
            if kind == "ENTRY":
                op["x"] = x
                op["y"] = y
                op["orient_idx"] = orient_idx
            result.append(op)
        operations[str(t)] = result
    return operations


# -----------------------------------------------------------------------------
# CLI run
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import pathlib
    from collections import defaultdict
    from utils import check_feasibility

    parser = argparse.ArgumentParser(description="EDD greedy algorithm smoke test")
    parser.add_argument("instance", help="path to instance JSON file")
    parser.add_argument("--timelimit", type=float, default=60.0,
                        help="wall-clock time limit in seconds (default: %(default)s)")
    parser.add_argument("--repair", choices=["greedy", "simple", "auto"], default="greedy",
                        help="repair mode (default: %(default)s)")
    args = parser.parse_args()

    inst_file = pathlib.Path(args.instance)

    with open(inst_file) as f:
        prob_info = json.load(f)

    t0  = time.time()
    sol = greedyalgorithm(prob_info, timelimit=args.timelimit, repair_mode=args.repair)
    elapsed = time.time() - t0

    result = check_feasibility(prob_info, sol)

    n_assigned = sum(1 for ops in sol["operations"].values()
                     for op in ops if op["type"] == "ENTRY")
    print(f"Instance : {prob_info['name']}")
    print(f"Elapsed  : {elapsed:.3f}s")
    print(f"Assigned : {n_assigned} / {len(prob_info['blocks'])} blocks")
    print(f"Feasible : {result['feasible']}  (stage={result['stage']})")
    if result["feasible"]:
        print(f"Objective: {result['objective']:.2f}  "
              f"(obj1={result['obj1']:.1f}, obj2={result['obj2']:.1f}, obj3={result['obj3']:.1f})")
    else:
        for v in result["violations"][:10]:
            print(f"  VIOLATION: {v}")
