"""
test_feasibility.py -- Regression test: algorithm() must produce a feasible solution
for every generated instance under instances/gen/*.json.

Run with:
    python -m pytest tests/test_feasibility.py -v
    python -m pytest tests/test_feasibility.py -q

Each instance is its own parametrized test case so failures are reported
individually. timelimit=25 seconds keeps the full suite under ~10 minutes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

GEN_DIR = ROOT / "instances" / "gen"
TIMELIMIT = 25.0  # seconds per instance


def _get_instances() -> list[Path]:
    """Return sorted list of generated instance JSON paths."""
    paths = sorted(GEN_DIR.glob("*.json"))
    return paths


@pytest.mark.parametrize("inst_path", _get_instances(),
                         ids=lambda p: p.stem)
def test_algorithm_feasible_on_gen_instance(inst_path: Path):
    """
    algorithm() must return a feasible solution for every generated instance
    within the timelimit. This guards against regressions when myalgorithm.py
    is modified in later milestones.
    """
    from myalgorithm import algorithm
    from utils import check_feasibility

    with inst_path.open(encoding="utf-8") as f:
        prob_info = json.load(f)

    n_blocks = len(prob_info["blocks"])
    n_bays = len(prob_info["bays"])

    sol = algorithm(prob_info, TIMELIMIT)

    assert isinstance(sol, dict), (
        f"algorithm() returned {type(sol).__name__}, expected dict"
    )
    assert "operations" in sol, (
        "solution dict is missing 'operations' key"
    )

    report = check_feasibility(prob_info, sol)

    assert report["feasible"] is True, (
        f"Infeasible on {inst_path.name} "
        f"(n={n_blocks}, m={n_bays}): "
        f"stage={report['stage']}, "
        f"violations={report['violations'][:3]}"
    )

    assert report["objective"] is not None, (
        f"feasible=True but objective is None on {inst_path.name}"
    )
