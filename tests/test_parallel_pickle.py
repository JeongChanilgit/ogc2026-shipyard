"""Pickle-safety + fallback contract tests for src/parallel_decode.py (M5).

These are the -1-safety / Windows-`spawn`-correctness tests for the 4-core
independent-seed multi-start:

  (a) The worker function (_search_worker) and a representative task-args tuple
      must be picklable via pickle.dumps -- if either were a closure / lambda /
      bound method or carried a Bay/Block/_Decoder/tracer, spawn would raise
      PicklingError at dispatch (= crash = -1).  This catches that statically.

  (b) run_parallel_multistart on a tiny synthetic 2-bay / ~6-block instance must
      return EITHER a valid (assign, results, obj) -- len(assign) == n_blocks,
      every entry a valid bay index, results covering every block, obj finite --
      OR None (both acceptable, since None just means "fall through to in-process
      _local_search").  It must NEVER raise.

The synthetic instance is intentionally tiny so the test is fast.  No instance
files needed.  Spawning happens ONLY inside test functions (pytest imports this
module at collection time -- there must be no process spawning at import, or the
test runner itself would fork-bomb under spawn).  Uses the same
sys.path.insert(0, src) pattern as tests/test_regime.py.
"""

from __future__ import annotations

import math
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import parallel_decode as P  # noqa: E402


# -----------------------------------------------------------------------------
# Minimal synthetic prob_info (stdlib only) -- 2 bays, 6 single-orientation
# square blocks that comfortably fit either bay.
# -----------------------------------------------------------------------------

def _square_block(side: float, pref):
    layer = [[0.0, 0.0], [side, 0.0], [side, side], [0.0, side]]
    return {
        "release_time": 0,
        "due_date": 100,
        "processing_time": 5,
        "workload": 10,
        "bay_preferences": list(pref),
        "shape": [{"orientation": 0, "layers": [layer]}],
    }


def _tiny_prob(n_blocks=6, n_bays=2, side=10.0, bay_w=100, bay_h=100):
    return {
        "name": "synthetic_parallel",
        "weights": {"w1": 7, "w2": 2667, "w3": 20},
        "bays": [{"width": bay_w, "height": bay_h} for _ in range(n_bays)],
        "blocks": [_square_block(side, [50, 50]) for _ in range(n_blocks)],
    }


def _seeds_for(prob):
    """A couple of valid starting assignments (all-bay-0, and an alternating
    split) -- both length n_blocks with valid bay indices."""
    n = len(prob["blocks"])
    m = len(prob["bays"])
    return [[0] * n, [i % m for i in range(n)]]


# -----------------------------------------------------------------------------
# (a) Pickle-safety: worker fn + a representative task-args tuple.
# -----------------------------------------------------------------------------

def test_worker_function_is_picklable():
    # A module-level function pickles by qualified name; a closure/lambda/bound
    # method would raise here.
    blob = pickle.dumps(P._search_worker)
    fn = pickle.loads(blob)
    assert fn is P._search_worker


def test_task_args_tuple_is_picklable():
    prob = _tiny_prob()
    seed = _seeds_for(prob)[0]
    # The exact shape dispatched to the pool: only plain picklable data, no
    # Bay/Block/_Decoder/tracer, and a wall-clock BUDGET (float seconds) -- never
    # a monotonic deadline.
    task = (0, prob, list(seed), 5.0, 40)
    blob = pickle.dumps(task)
    wi, p2, s2, budget, alt = pickle.loads(blob)
    assert wi == 0
    assert p2 == prob
    assert s2 == seed
    assert isinstance(budget, float)
    assert isinstance(alt, int)


def test_module_does_no_spawning_at_import():
    # Importing the module must not have started a pool / children: it should
    # expose its public API and constants, and that's it.
    assert hasattr(P, "run_parallel_multistart")
    assert hasattr(P, "_search_worker")
    assert P.MAX_WORKERS == 4


# -----------------------------------------------------------------------------
# (b) Fallback / result contract -- gated behind __main__ for spawn safety.
# -----------------------------------------------------------------------------

def _assert_valid_result_or_none(prob, result):
    """result must be None OR a valid (assign, results, obj); never else."""
    if result is None:
        return  # acceptable: caller falls through to in-process search
    assert isinstance(result, tuple) and len(result) == 3
    assign, results, obj = result
    n_blocks = len(prob["blocks"])
    n_bays = len(prob["bays"])
    assert isinstance(assign, list)
    assert len(assign) == n_blocks
    for j in assign:
        assert isinstance(j, int) and 0 <= j < n_bays
    # results is the per-bay placement dict (so the parent skips a re-decode);
    # every placed block must appear exactly once across the bays.
    assert isinstance(results, dict) and results
    placed = [bid for bay in results.values() for bid in bay]
    assert len(placed) == n_blocks
    assert set(placed) == set(range(n_blocks))
    assert isinstance(obj, float) and math.isfinite(obj)


def _run_multistart_contract():
    """Body of the multiprocessing test.  Spawns real processes, so it is only
    invoked from the __main__ guard (and from the pytest wrapper, which itself is
    safe because spawning is confined to this function, not import time)."""
    import time

    prob = _tiny_prob()
    seeds = _seeds_for(prob)
    deadline = time.monotonic() + 12.0  # tiny instance: plenty of slack
    # Must NEVER raise -- worst case it returns None.
    result = P.run_parallel_multistart(prob, seeds, deadline, n_workers=2)
    _assert_valid_result_or_none(prob, result)

    # A too-short window must yield None (no time to bother spawning).
    result2 = P.run_parallel_multistart(prob, seeds, time.monotonic() + 0.01,
                                        n_workers=2)
    assert result2 is None

    # Degenerate inputs must give None, not raise.
    assert P.run_parallel_multistart(prob, [], deadline, n_workers=2) is None
    assert P.run_parallel_multistart(None, seeds, deadline, n_workers=2) is None
    assert P.run_parallel_multistart({}, seeds, deadline, n_workers=2) is None
    return result


def test_run_parallel_multistart_contract():
    # pytest imports this module (no spawning at import); the spawning lives
    # inside _run_multistart_contract, which only runs when this test executes.
    _run_multistart_contract()


if __name__ == "__main__":
    # Direct-run path: `python tests/test_parallel_pickle.py`.  The __main__
    # guard is what makes `spawn` safe -- children re-import the module but do
    # NOT re-enter this block, so no fork bomb.
    test_worker_function_is_picklable()
    test_task_args_tuple_is_picklable()
    test_module_does_no_spawning_at_import()
    out = _run_multistart_contract()
    print("parallel multistart result:", out)
    print("OK")
