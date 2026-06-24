# parallel_decode.py
#
# OGC 2026 -- The Grand Shipyard Puzzle.  Milestone M5: 4-core parallelism.
#
# Independent-seed multi-start.  Several SEPARATE processes each run a full
# assignment-level local search from a different seed; the parent keeps the BEST
# (assign, obj).  This is the clean fit for our decomposition (NOT per-bay
# parallelism): the assignment-level search is the expensive, embarrassingly
# parallel part, the result that crosses the process boundary is tiny (a list of
# ints + a float), and the seeds are already diverse, so N independent searches
# explore N basins for ~the wall-clock cost of one.
#
# -1-SAFETY CONTRACT (this is why everything is wrapped):
#   * run_parallel_multistart NEVER raises.  On ANY failure -- PicklingError, a
#     spawn/start error, a worker exception, a timeout, an empty result -- it
#     returns None, and the caller falls through to the existing in-process
#     _local_search.  Parallelism is a pure speedup; correctness never depends on
#     it (dev-plan invariants section 4.4 / 4.7).
#   * The worker (_search_worker) is a MODULE-LEVEL function so it pickles under
#     Windows `spawn` (no closures / lambdas / bound methods).  Only plain
#     picklable data crosses the boundary: the raw prob_info dict, a seed
#     (list[int]), a per-worker wall-clock BUDGET in seconds (a float, NOT a
#     monotonic deadline -- time.monotonic() epochs differ across processes), and
#     scalar params.  No Bay / Block / _Decoder objects, no tracer.  The worker
#     rebuilds bays / decoder / bay_u from prob_info itself and returns
#     (assign: list[int], results: dict, obj: float) -- results included so the
#     parent never has to re-decode the winner (an unguarded re-decode = -1 risk).
#
# IMPORT-TIME SAFETY (no fork bomb): this module does NOTHING at import -- all
# process spawning is inside functions.  The entry points that ultimately call
# algorithm() (tools/run_local.py, tools/bench.py) already guard the top level
# with `if __name__ == "__main__":`, which is what makes `spawn` re-import this
# package safely instead of re-spawning a pool on every child import.

from __future__ import annotations

import math
import time

# Server is <= 4 cores (400%); never ask for more than this many processes.
MAX_WORKERS = 4

# Determinism hook: worker i seeds random with BASE_SEED + i so the multi-start
# is diverse across workers yet reproducible run-to-run (invariant section 4.9).
BASE_SEED = 20260529


def _worker_local_search(prob_info, decoder, bays, feasible_bays, bay_u,
                         assign, results, deadline):
    """Call myalgorithm._local_search, tolerating its evolving keyword args.

    M6 is adding op_weights0 / sa_temp_frac kwargs to _local_search.  We call it
    positionally only (the positional prefix is stable:
    prob_info, decoder, bays, feasible_bays, bay_u, assign, results, deadline)
    and pass tr=None, so this keeps working whether or not the new kwargs exist
    -- they all have defaults.  Returns (best_assign, best_results, best_obj)."""
    from myalgorithm import _local_search
    return _local_search(prob_info, decoder, bays, feasible_bays, bay_u,
                         assign, results, deadline, tr=None)


def _search_worker(task):
    """Run ONE seeded assignment-level search in this (child) process.

    MODULE-LEVEL by design (picklable under spawn).  `task` is a plain tuple:
        (worker_index:int, prob_info:dict, seed:list[int],
         budget_secs:float, alt_threshold:int)
    Everything in it is plain picklable data.  Returns (assign:list[int],
    results:dict, obj:float) on success, or None on ANY failure (so the parent
    can ignore this worker without losing the others).  Imports are done at call
    time, inside the try/except, so a missing/broken dependency in a child
    degrades to None rather than crashing the pool."""
    try:
        worker_index, prob_info, seed, budget_secs, alt_threshold = task

        import random
        # Deterministic-yet-diverse multi-start (invariant section 4.9).
        random.seed(BASE_SEED + int(worker_index))

        from utils import Bay
        from myalgorithm import _Decoder, _decode_assignment, _obj_of_results

        bays_data = prob_info["bays"]
        blocks_data = prob_info["blocks"]
        n_bays = len(bays_data)
        n_blocks = len(blocks_data)
        if n_bays == 0 or n_blocks == 0:
            return None

        # Rebuild every heavy object from the raw dict INSIDE the child -- none of
        # these crossed the process boundary.
        bays = [Bay.from_dict(d, i) for i, d in enumerate(bays_data)]

        bay_areas = [bays_data[j]["width"] * bays_data[j]["height"]
                     for j in range(n_bays)]
        avg_area = sum(bay_areas) / n_bays
        bay_u = [avg_area / a for a in bay_areas]

        # Recompute feasible bays exactly as the parent does (necessary-condition
        # geometric filter) so the search neighbourhood matches.
        from myalgorithm import _feasible_bays
        feasible_bays = _feasible_bays(blocks_data, bays)

        decoder = _Decoder(bays, blocks_data, alt_threshold)

        # Sanitize the incoming seed: every entry must be a valid bay index.
        assign = [int(j) if (isinstance(j, int) and 0 <= int(j) < n_bays) else 0
                  for j in seed]
        if len(assign) != n_blocks:
            return None

        # Compute the absolute deadline LOCALLY from the budget (monotonic clocks
        # are per-process; a deadline from the parent would be meaningless here).
        deadline = time.monotonic() + max(0.0, float(budget_secs))

        # Use the worker-local deadline for the initial seed decode too.  The
        # parent path always budget-bounds seed decodes, which enables
        # myalgorithm's adaptive candidate cap on tight budgets.  Keeping this
        # unbounded made the parallel portfolio a different algorithm: a worker
        # could spend its whole budget on a full clean decode before local search
        # even started, or time out and return nothing.  Passing the local
        # deadline makes the portfolio obey the same time-adaptive decode policy
        # as the sequential path.
        results, _ = _decode_assignment(decoder, assign, n_bays,
                                        deadline=deadline)
        if results is None:
            return None

        best_assign, best_results, best_obj = _worker_local_search(
            prob_info, decoder, bays, feasible_bays, bay_u,
            assign, results, deadline)

        if best_results is None:
            return None
        # Recompute the objective from the returned results so the value we ship
        # is self-consistent (and a plain float, never inf packaged oddly).
        obj, *_ = _obj_of_results(prob_info, best_results, bay_u)
        if not math.isfinite(obj):
            return None
        # Return plain picklable types across the boundary, INCLUDING the per-bay
        # placement results, so the PARENT need not re-decode the winning
        # assignment.  A parent-side cache-miss re-decode of a large concentrated
        # bay can cost tens of seconds; started near the deadline it would overrun
        # the wall-clock = -1.  best_results is {bay_idx:int -> {block_id:int ->
        # {field:int}}} -- all plain ints, fully picklable.
        return [int(j) for j in best_assign], best_results, float(obj)
    except Exception:
        # Never propagate -- a dead worker must not poison the pool / parent.
        return None


def run_parallel_multistart(prob_info, seeds, deadline_monotonic, n_workers):
    """Run independent seeded searches in separate processes; return the best.

    Parameters
    ----------
    prob_info : dict
        The raw instance dict (sent verbatim to each worker -- must be picklable;
        it is plain JSON-derived data, so it is).
    seeds : list[list[int]]
        Candidate starting assignments (each a length-n_blocks list of bay
        indices).  One worker is dispatched per seed, capped at n_workers.
    deadline_monotonic : float
        Absolute time.monotonic() value by which the PARENT wants results.  Each
        worker is given a wall-clock BUDGET (seconds) derived from this minus a
        small spawn/serialization margin; the parent waits at most until this
        deadline and then terminates any stragglers.
    n_workers : int
        Desired worker count; clamped to [1, MAX_WORKERS] and to len(seeds).

    Returns
    -------
    (best_assign: list[int], best_results: dict, best_obj: float) | None
        The best (lowest-objective) result across all workers that finished in
        time, or None if anything went wrong (no seeds, no time, spawn failure,
        all workers errored/empty, timeout with nothing finished).  best_results
        is the decoded per-bay placement dict so the parent can build the final
        solution WITHOUT an unguarded re-decode.  The caller MUST treat None as
        "fall through to in-process _local_search".

    Never raises.
    """
    try:
        if not prob_info or not seeds:
            return None
        blocks_data = prob_info.get("blocks") or []
        bays_data = prob_info.get("bays") or []
        n_blocks = len(blocks_data)
        n_bays = len(bays_data)
        if n_blocks == 0 or n_bays < 2:
            return None

        now = time.monotonic()
        budget = deadline_monotonic - now
        # Reserve a margin for spawn + import + result serialization on the
        # child; if there is not enough time to bother, decline (caller falls
        # back to the in-process search, which can use the remaining time).
        spawn_margin = 2.0
        worker_budget = budget - spawn_margin
        if worker_budget < 3.0:
            return None

        # Same alt-ordering threshold the parent's _Decoder uses (myalgorithm
        # algorithm(): 40 for n<=200, else 0) so worker decode cost matches.
        alt_threshold = 40 if n_blocks <= 200 else 0

        try:
            n_workers = int(n_workers)
        except Exception:
            n_workers = 1
        n = max(1, min(MAX_WORKERS, n_workers, len(seeds)))
        chosen = seeds[:n]

        tasks = [
            (i, prob_info, list(seed), float(worker_budget), int(alt_threshold))
            for i, seed in enumerate(chosen)
        ]

        import multiprocessing as mp
        # Explicit `spawn`: correct on Windows (no fork) and safe on the Linux
        # server too -- avoids inheriting parent state / locks.
        ctx = mp.get_context("spawn")

        pool = None
        try:
            pool = ctx.Pool(processes=n)
            async_res = pool.map_async(_search_worker, tasks)
            # Wait at most until the parent's deadline, then take whatever is
            # ready; terminate so no worker runs past the wall-clock budget.
            timeout = max(0.0, deadline_monotonic - time.monotonic())
            try:
                outputs = async_res.get(timeout=timeout)
            except mp.TimeoutError:
                outputs = None
            finally:
                # terminate() (not close()/join()) so a straggler cannot overrun
                # the deadline; close+join after to reap children cleanly.
                try:
                    pool.terminate()
                except Exception:
                    pass
                try:
                    pool.join()
                except Exception:
                    pass
        except Exception:
            # Pool creation / dispatch failure (e.g. PicklingError) -> fall back.
            if pool is not None:
                try:
                    pool.terminate()
                    pool.join()
                except Exception:
                    pass
            return None

        if not outputs:
            return None

        best = None
        for out in outputs:
            if out is None:
                continue
            try:
                assign, results, obj = out
            except Exception:
                continue
            if (not isinstance(assign, list) or len(assign) != n_blocks
                    or not all(isinstance(j, int) and 0 <= j < n_bays
                               for j in assign)):
                continue
            if not isinstance(results, dict) or not results:
                continue
            try:
                fobj = float(obj)
            except Exception:
                continue
            if not math.isfinite(fobj):
                continue
            if best is None or fobj < best[2]:
                best = (assign, results, fobj)

        return best
    except Exception:
        # Absolute backstop: the parent must always be able to fall back.
        return None


def _bay_decode_worker(task):
    """Decode ONE bay cleanly in a child process.

    The worker deliberately runs the full CRANE-safe decoder (`deadline=None`).
    The parent owns the wall-clock guard and terminates stragglers.  Returning a
    partial/force-budgeted bay here would create a low-Z1-looking candidate that
    can later lose objective through forced late exits; if a clean bay cannot
    finish in time, the whole candidate is simply skipped by the parent.
    """
    try:
        bay_idx, prob_info, ids, alt_threshold = task
        ids = list(ids or [])
        if not ids:
            return int(bay_idx), {}, 0.0, 0

        from utils import Bay
        from myalgorithm import _decode_bay, _orderings, _bay_tardiness

        bay = Bay.from_dict(prob_info["bays"][bay_idx], int(bay_idx))
        blocks_data = prob_info["blocks"]
        allow_alt = len(ids) <= int(alt_threshold)

        best_res = None
        best_tard = math.inf
        best_forced = 0
        for order in _orderings(ids, blocks_data, allow_alt):
            res, forced = _decode_bay(
                bay, int(bay_idx), list(order), blocks_data,
                deadline=None, cand_cap=0)
            if res is None:
                continue
            tard = _bay_tardiness(res, blocks_data)
            if tard < best_tard:
                best_res = res
                best_tard = tard
                best_forced = len(forced or ())

        if best_res is None or not math.isfinite(best_tard):
            return None
        return int(bay_idx), best_res, float(best_tard), int(best_forced)
    except Exception:
        return None


def run_parallel_bay_decode(prob_info, assign, deadline_monotonic, n_workers):
    """Clean-decode all bays for an existing assignment in parallel.

    Returns {bay_idx: {block_id: assignment_dict}} only when every non-empty bay
    completed before the parent deadline.  On timeout, worker error, malformed
    input, or an incomplete result set it returns None.  This is a pure candidate
    generator: final feasibility/objective adoption remains the caller's job.
    """
    try:
        if not prob_info or not assign:
            return None
        blocks_data = prob_info.get("blocks") or []
        bays_data = prob_info.get("bays") or []
        n_blocks = len(blocks_data)
        n_bays = len(bays_data)
        if n_blocks == 0 or n_bays < 2 or len(assign) != n_blocks:
            return None

        now = time.monotonic()
        budget = float(deadline_monotonic) - now
        spawn_margin = 2.0
        if budget <= spawn_margin + 1.0:
            return None

        bay_ids = [[] for _ in range(n_bays)]
        for b, j in enumerate(assign):
            try:
                jj = int(j)
            except Exception:
                return None
            if jj < 0 or jj >= n_bays:
                return None
            bay_ids[jj].append(int(b))

        non_empty = [(j, ids) for j, ids in enumerate(bay_ids) if ids]
        if not non_empty:
            return {j: {} for j in range(n_bays)}

        # Same default as myalgorithm._Decoder.  Large bays get EDD-only clean
        # decode; small bays also try release/ATCR alternatives.
        alt_threshold = 40 if n_blocks <= 200 else 0

        try:
            n_workers = int(n_workers)
        except Exception:
            n_workers = 1
        n = max(1, min(MAX_WORKERS, n_workers, len(non_empty)))

        # Longest bays first so the critical path starts immediately.
        non_empty.sort(key=lambda item: len(item[1]), reverse=True)
        tasks = [(j, prob_info, ids, alt_threshold) for j, ids in non_empty]

        import multiprocessing as mp
        ctx = mp.get_context("spawn")

        pool = None
        try:
            pool = ctx.Pool(processes=n)
            async_res = pool.map_async(_bay_decode_worker, tasks)
            timeout = max(0.0, float(deadline_monotonic) - time.monotonic())
            try:
                outputs = async_res.get(timeout=timeout)
            except mp.TimeoutError:
                outputs = None
            finally:
                try:
                    pool.terminate()
                except Exception:
                    pass
                try:
                    pool.join()
                except Exception:
                    pass
        except Exception:
            if pool is not None:
                try:
                    pool.terminate()
                    pool.join()
                except Exception:
                    pass
            return None

        if not outputs or len(outputs) != len(tasks):
            return None

        results = {j: {} for j in range(n_bays)}
        seen = set()
        for out in outputs:
            if out is None:
                return None
            try:
                j, res, _tard, _forced = out
            except Exception:
                return None
            if not isinstance(j, int) or j < 0 or j >= n_bays or j in seen:
                return None
            if not isinstance(res, dict):
                return None
            seen.add(j)
            results[j] = res

        if seen != {j for j, _ids in non_empty}:
            return None
        return results
    except Exception:
        return None


def _cumlevel_bay_worker(task):
    """One bay's demand-flattened best-of re-decode, in a child process.

    Mirrors myalgorithm._cumulative_leveled_redecode_verified's per-bay logic
    (cumulative CP-SAT entry targets per alpha -> multi-order flattened re-decode,
    keep the lowest-tardiness placement).  Returns (bay_idx, best_res|None, best_bt)
    or None on error.  CP-SAT runs single-worker here because the BAYS run in
    parallel (one core each), matching the 4-core eval server.  best_bt is seeded
    to the bay's CURRENT tardiness so a bay is never made worse (the parent gate
    still re-verifies the whole solution)."""
    try:
        import math as _math, time as _t, os as _os
        (bay_idx, prob_info, layout, alpha_list, n_orders, budget) = task
        # Method (1): the parallel cum_level re-decode is bt-guarded, so the EXACT
        # fast crane geometry is upside-only here (more attempts/wall-sec, no
        # regression).  Mirror the parent's OGC_REDECODE_FAST flag (env propagates to
        # spawned children).  None -> module globals (slow, default); True -> fast.
        _redecode_fast = (_os.environ.get("OGC_REDECODE_FAST", "").strip().lower()
                          in ("1", "true", "on", "yes")) or None
        from ortools.sat.python import cp_model
        from utils import Bay, Block
        from myalgorithm import _decode_bay, _bay_tardiness_lb, _block_bbox

        blocks = prob_info["blocks"]
        bay = Bay.from_dict(prob_info["bays"][int(bay_idx)], int(bay_idx))
        by_id = {int(b): a for b, a in layout.items()}
        ids = list(by_id)
        if not ids:
            return int(bay_idx), None, 0.0
        cur_tard = sum(max(0.0, int(by_id[b]["exit_time"]) - blocks[b]["due_date"])
                       for b in ids)
        if cur_tard <= 1e-9:
            return int(bay_idx), None, 0.0
        bay_lb = _bay_tardiness_lb(ids, blocks)
        deadline = _t.monotonic() + float(budget)
        per_cum = max(1.0, min(8.0, float(budget) * 0.30 / max(1, len(alpha_list))))

        def _targets(alpha):
            cap = max(1, int(bay.width * bay.height * alpha))
            m = cp_model.CpModel()
            H = (max(int(blocks[b]["due_date"]) for b in ids)
                 + sum(int(blocks[b]["processing_time"]) for b in ids))
            e = {}; ivs = []; dem = []; tard = []
            for b in ids:
                a = by_id[b]; blk = blocks[b]
                bo = Block(block_id=b, block_data=blk, x=a["x"], y=a["y"],
                           orient_idx=a["orient_idx"])
                r = bo.bounding_rect(); area = max(1, int((r[2] - r[0]) * (r[3] - r[1])))
                R = int(blk["release_time"]); P = int(blk["processing_time"])
                D = int(blk["due_date"])
                ev = m.NewIntVar(R, H, f"e{b}"); e[b] = ev
                xv = m.NewIntVar(R, H + P, f"x{b}")
                ivs.append(m.NewIntervalVar(ev, P, xv, f"i{b}")); dem.append(min(area, cap))
                tv = m.NewIntVar(0, H, f"t{b}"); m.Add(tv >= ev + P - D); tard.append(tv)
                m.AddHint(ev, int(a["entry_time"]))
            m.AddCumulative(ivs, dem, cap); m.Minimize(sum(tard))
            s = cp_model.CpSolver()
            s.parameters.max_time_in_seconds = float(per_cum)
            s.parameters.num_search_workers = 1
            if _os.environ.get("OGC_DEV_DET", "").strip().lower() \
                    not in ("", "0", "false", "off", "no"):
                # Dev-only reproducibility (mirrors myalgorithm._dev_det):
                # fixed seed; interleave is moot at a single worker.
                s.parameters.random_seed = 20260611
            st = s.Solve(m)
            if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None
            return {b: int(s.Value(e[b])) for b in ids}

        best_res = None; best_bt = cur_tard
        for alpha in alpha_list:
            if _t.monotonic() >= deadline - 0.2:
                break
            targets = _targets(alpha)
            if targets is None:
                continue
            okeys = [
                lambda b: (targets[b], blocks[b]["due_date"]),
                lambda b: (targets[b], blocks[b]["due_date"]
                           - blocks[b]["release_time"] - blocks[b]["processing_time"]),
                lambda b: (blocks[b]["due_date"], targets[b]),
                lambda b: (targets[b], -_block_bbox(blocks[b], by_id[b]["orient_idx"])[2]
                           * _block_bbox(blocks[b], by_id[b]["orient_idx"])[3]),
            ][:int(n_orders)]
            for k in okeys:
                if _t.monotonic() >= deadline - 0.1:
                    break
                order = sorted(ids, key=k)
                res, _f = _decode_bay(bay, int(bay_idx), order, blocks,
                                      deadline=deadline, release_override=targets,
                                      fast_geom=_redecode_fast)
                if res is None or len(res) != len(ids):
                    continue
                bt = sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"]) for b in ids)
                if bt < best_bt:
                    best_bt = bt; best_res = res
                # Bay hit its proven LB -> no order beats it; stop the extra slow
                # re-decodes (order-level twin of the alpha-level break below).  Keeps
                # a parallel bay worker from spinning ~20s past Z1=0.
                if best_bt <= bay_lb + 1e-9:
                    break
            if best_bt <= bay_lb + 1e-9:
                break
        return int(bay_idx), best_res, float(best_bt)
    except Exception:
        return None


def run_parallel_cumlevel(prob_info, layouts, alpha_list, n_orders,
                          deadline_monotonic, n_workers):
    """Demand-flattened best-of re-decode for every tardy bay IN PARALLEL.

    layouts: {bay_idx: {block_id: assignment_dict}} for the bays to refine.  Each
    bay runs in its own process against the SHARED deadline (so each gets the full
    window, not a 1/n_bays slice -- the parallelism is the speedup).  Returns
    {bay_idx: best_res_dict} only for bays that improved; bays absent/None keep
    their current layout (caller's job).  Returns None on spawn failure/timeout so
    the caller falls back to the sequential path.  Never raises."""
    try:
        if not prob_info or not layouts:
            return None
        now = time.monotonic()
        budget = float(deadline_monotonic) - now
        if budget <= 3.0:
            return None
        items = [(int(j), lay) for j, lay in layouts.items() if lay]
        if not items:
            return None
        try:
            n_workers = int(n_workers)
        except Exception:
            n_workers = 1
        n = max(1, min(MAX_WORKERS, n_workers, len(items)))
        # Longest bays first so the critical path starts immediately.
        items.sort(key=lambda it: len(it[1]), reverse=True)
        tasks = [(j, prob_info, {int(b): a for b, a in lay.items()},
                  list(alpha_list), int(n_orders), float(budget) - 0.5)
                 for j, lay in items]

        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        pool = None
        try:
            pool = ctx.Pool(processes=n)
            async_res = pool.map_async(_cumlevel_bay_worker, tasks)
            timeout = max(0.0, float(deadline_monotonic) - time.monotonic())
            try:
                outputs = async_res.get(timeout=timeout)
            except mp.TimeoutError:
                outputs = None
            finally:
                try:
                    pool.terminate()
                except Exception:
                    pass
                try:
                    pool.join()
                except Exception:
                    pass
        except Exception:
            if pool is not None:
                try:
                    pool.terminate(); pool.join()
                except Exception:
                    pass
            return None

        if not outputs:
            return None
        improved = {}
        for out in outputs:
            if out is None:
                continue
            try:
                j, res, _bt = out
            except Exception:
                continue
            if isinstance(j, int) and isinstance(res, dict) and res:
                improved[j] = res
        return improved
    except Exception:
        return None
