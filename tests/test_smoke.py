"""Smoke test: baseline algorithm runs on example instance and produces a feasible solution."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

EXAMPLE = ROOT / "instances" / "example" / "example_B2_b10.json"


def test_example_instance_exists():
    assert EXAMPLE.exists(), f"Example instance missing: {EXAMPLE}"


def test_algorithm_returns_dict():
    from myalgorithm import algorithm
    prob_info = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    sol = algorithm(prob_info, 30.0)
    assert isinstance(sol, dict)
    assert "operations" in sol
    assert isinstance(sol["operations"], dict)


def test_algorithm_produces_feasible_solution_within_timelimit():
    """Baseline must produce a feasible solution on the example within 60s."""
    from myalgorithm import algorithm
    from utils import check_feasibility

    prob_info = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    sol = algorithm(prob_info, 60.0)
    elapsed = time.perf_counter() - t0

    assert elapsed < 90.0, f"Baseline exceeded 90s wall-clock: {elapsed:.1f}s"

    report = check_feasibility(prob_info, sol)
    assert report["feasible"], (
        f"Baseline infeasible: stage={report['stage']}, "
        f"violations={report['violations'][:3]}"
    )
    assert report["objective"] is not None
    assert report["objective"] >= 0
