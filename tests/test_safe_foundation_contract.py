"""Source-level safety contracts for candidate-generator plumbing.

These tests lock the architectural invariant from notes/safe-foundation-goal.md:
newer search/seed/postprocess logic may create candidates, but final return is
controlled by the verified incumbent + check_feasibility gate.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _src() -> str:
    return (SRC / "myalgorithm.py").read_text(encoding="utf-8")


def test_final_gate_checks_candidate_before_returning_it():
    src = _src()
    check_pos = src.index("rep = check_feasibility(prob_info, sol)")
    feas_pos = src.index('return _ret(sol, _label, "gate_feasible")')
    floor_pos = src.index('return _ret(floor_sol, floor_label, "verified_floor")')

    assert check_pos < feas_pos < floor_pos
    assert "if q >= floor_obj - 1e-9:" in src
    assert "if time.monotonic() + gate_cost > hard_stop:" in src


def test_gate_postprocess_is_verified_and_disableable():
    src = _src()
    gate_pos = src.index("rep = check_feasibility(prob_info, sol)")
    pp_pos = src.index('if _env_on("OGC_GATE_POSTPROCESS", True):')
    call_pos = src.index("_postprocess_verified_solution(", pp_pos)
    ret_pos = src.index('"gate_verified_postprocess"', call_pos)

    assert gate_pos < pp_pos < call_pos < ret_pos
    assert "post is not None" in src
    assert "time.monotonic() + pp_reserve < hard_stop" in src


def test_lns_and_cpsat_only_feed_candidate_pool():
    src = _src()
    search_call = src.index("best_assign, best_results, best_obj = _local_search(")
    search_candidate = src.index('candidates.append(("search", search_sol))')
    cpsat_seed = src.index('named_seeds.append(("cpsat", cp_assign))')
    seed_candidate = src.index('candidates.append((f"seed_{name}",')
    gate_pos = src.index("with tr.phase(\"gate\"):")

    assert cpsat_seed < gate_pos
    assert seed_candidate < gate_pos
    assert search_call < search_candidate < gate_pos
    assert 'return _ret(search_sol' not in src
    assert 'return _ret(seed_' not in src


def test_candidate_generators_have_rollback_or_kill_switches():
    src = _src()

    assert "except Exception:" in src
    assert "return None" in src[src.index("def _cpsat_assignment"):]
    assert 'OGC_GATE_POSTPROCESS' in src
    assert 'OGC_PARALLEL_MS", False' in src
    assert 'OGC_CPSAT_FIRST", False' in src
    assert 'OGC_SEARCH_AFTER_BASELINE", False' in src
    # P3 ALNS-over-baseline ships ON by default but stays disableable: setting
    # OGC_ALNS_OVER_BASELINE=0 restores the legacy verified-floor-no-search path.
    assert 'OGC_ALNS_OVER_BASELINE", True' in src
