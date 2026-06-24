"""Parallel CANDIDATE runner (2026-06-17 CP-SAT cleanup / time-reduction loop).

Runs box-decomp and gassign as SEPARATE PROCESSES IN PARALLEL, each on ~the full
remaining budget, instead of the SEQUENTIAL slices that starve them (the stage
profile found box/gassign win with only 67-74s while legacy hogs ~130s and is
discarded).  Running them concurrently on the 4-core server lets each get the
full budget in the SAME wall-clock -> realizes e.g. gassign's prob_39 win that
the starved slice could not.

-1-SAFETY CONTRACT (mirrors parallel_decode.py):
  * run_parallel_candidates NEVER raises.  On ANY failure (spawn/pickle/timeout/
    worker crash / empty) it returns [] and the caller keeps its sequential
    legacy solution.  Parallelism is a pure best-of ADD; correctness never
    depends on it.
  * Workers are MODULE-LEVEL functions (picklable under `spawn`).  Only plain
    picklable data crosses the boundary: the raw prob_info dict, a float budget
    (seconds, NOT a monotonic deadline -- epochs differ across processes), an int
    CP-SAT worker count, and the returned (name, sol_dict, obj_float).
  * Each candidate's CP-SAT worker count is REDUCED (parent passes ~2) so two
    CP-SAT processes share the 4-core server without oversubscription.
  * Does NOTHING at import (no fork bomb); all spawning is inside functions.  The
    entry points that reach algorithm() guard the top level with
    `if __name__ == "__main__":`, so `spawn` re-imports safely.
"""
from __future__ import annotations

MAX_PROC = 4


def _box_worker(prob_info, budget_s, workers):
    try:
        import os
        os.environ["OGC_BOXDECOMP"] = "1"
        os.environ["OGC_FEASSPILL"] = "0"
        os.environ["OGC_FEASSPILL_WORKERS"] = str(int(workers))
        os.environ["OGC_BD_WORKERS"] = str(int(workers))
        import boxsolver as _bs
        from utils import check_feasibility
        sol = _bs.algorithm(prob_info, float(budget_s))
        if sol is None:
            return None
        fc = check_feasibility(prob_info, sol)
        if not fc.get("feasible") or fc.get("objective") is None:
            return None
        return ("box", sol, float(fc["objective"]))
    except Exception:
        return None


def _gassign_worker(prob_info, budget_s, workers):
    try:
        import os
        os.environ["OGC_GASSIGN_WORKERS"] = str(int(workers))
        import gassign as _ga
        from utils import check_feasibility
        sol = _ga.algorithm(prob_info, float(budget_s))
        if sol is None:
            return None
        fc = check_feasibility(prob_info, sol)
        if not fc.get("feasible") or fc.get("objective") is None:
            return None
        return ("gassign", sol, float(fc["objective"]))
    except Exception:
        return None


_WORKERS = {"box": _box_worker, "gassign": _gassign_worker}


def _dispatch(task):
    """Top-level dispatch (picklable). task=(name, prob_info, budget_s, workers)."""
    try:
        name, prob_info, budget_s, workers = task
        fn = _WORKERS.get(name)
        if fn is None:
            return None
        return fn(prob_info, budget_s, workers)
    except Exception:
        return None


def run_parallel_candidates(prob_info, names, budget_s, workers_each):
    """Spawn each candidate in `names` (subset of {'box','gassign'}) in parallel,
    each with `budget_s` seconds and `workers_each` CP-SAT workers.

    Returns a list of (name, sol_dict, obj_float) for the FEASIBLE results, or []
    on any failure.  Never raises; the caller treats [] as "keep the sequential
    solution".
    """
    try:
        if not prob_info or not names:
            return []
        try:
            budget_s = float(budget_s)
        except Exception:
            return []
        if budget_s < 3.0:
            return []
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        tasks = [(str(nm), prob_info, budget_s, int(workers_each)) for nm in names]
        n = max(1, min(MAX_PROC, len(tasks)))
        pool = None
        outputs = None
        try:
            pool = ctx.Pool(processes=n)
            async_res = pool.map_async(_dispatch, tasks)
            # Parent waits at most the per-worker budget + a spawn/import/serialize
            # margin, then takes whatever finished and terminates stragglers so no
            # child overruns the wall-clock.
            timeout = budget_s + 20.0
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
            return []
        if not outputs:
            return []
        res = []
        for out in outputs:
            if out is None:
                continue
            try:
                nm, sol, obj = out
            except Exception:
                continue
            if not isinstance(sol, dict) or "operations" not in sol:
                continue
            try:
                fobj = float(obj)
            except Exception:
                continue
            if fobj != fobj:  # NaN
                continue
            res.append((str(nm), sol, fobj))
        return res
    except Exception:
        return []
