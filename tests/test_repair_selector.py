"""Unit tests for symptom-based baseline repair selection."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import baseline_greedy as B  # noqa: E402


def _prob(n_blocks: int = 100, *, weights=None):
    return {
        "name": "selector_synthetic",
        "weights": dict(weights or {"w1": 1, "w2": 1, "w3": 1}),
        "bays": [{"width": 100, "height": 100}],
        "blocks": [
            {
                "release_time": 0,
                "due_date": 100,
                "processing_time": 5,
                "workload": 1,
                "bay_preferences": [100],
                "shape": [],
            }
            for _ in range(n_blocks)
        ],
    }


def _assignments(prob, *, exit_time=20):
    return {
        i: {
            "block_id": i,
            "bay_id": 0,
            "x": 0,
            "y": 0,
            "orient_idx": 0,
            "entry_time": 0,
            "exit_time": exit_time,
        }
        for i in range(len(prob["blocks"]))
    }


def test_phase1_feasible_keeps_greedy():
    prob = _prob()
    dec = B._choose_repair_mode_from_phase1(
        prob,
        {"feasible": True, "stage": 5, "objective": 123, "violations": []},
        _assignments(prob),
        elapsed_phase1=3.0,
        timelimit=60.0,
    )

    assert dec.mode == "greedy"
    assert dec.reason == "phase1_feasible"


def test_many_crane_violations_at_high_elapsed_choose_simple():
    prob = _prob()
    report = {
        "feasible": False,
        "stage": 2,
        "objective": None,
        "violations": [f"block {i} blocked" for i in range(12)],
    }

    dec = B._choose_repair_mode_from_phase1(
        prob, report, _assignments(prob), elapsed_phase1=40.0, timelimit=60.0)

    assert dec.mode == "simple"
    assert dec.reason == "many_structural_violations_high_elapsed"


def test_tardiness_tail_explosion_prefers_greedy_repair():
    prob = _prob()
    report = {
        "feasible": False,
        "stage": 2,
        "objective": None,
        "violations": [f"block {i} blocked" for i in range(12)],
    }

    dec = B._choose_repair_mode_from_phase1(
        prob, report, _assignments(prob, exit_time=500),
        elapsed_phase1=40.0, timelimit=60.0)

    assert dec.mode == "greedy"
    assert dec.reason == "tardiness_tail_needs_greedy_repair"


def test_tardiness_dominant_avoids_self_defeating_serialization():
    # goal §condition-4 forbids *train-shaped* (n_blocks/n_bays) buckets but
    # explicitly permits weights "보조 신호로만 사용" (as an auxiliary signal).
    # "simple" repair serializes -> pays tardiness to buy feasibility; that trade
    # is self-defeating when w1 dominates.  Same symptoms, but the w1-dominant
    # instance must NOT serialize (it falls through to greedy repair) while the
    # tardiness-cheap instance still may.  This is the corrected behaviour that
    # cured the train prob_2 regression (mid-run "simple" -> 4.1M vs greedy 1e4).
    report = {
        "feasible": False,
        "stage": 2,
        "objective": None,
        "violations": [f"block {i} blocked" for i in range(25)],
    }
    prob_low = _prob(weights={"w1": 1, "w2": 10, "w3": 100})
    prob_high = _prob(weights={"w1": 30000, "w2": 10, "w3": 100})

    dec_low = B._choose_repair_mode_from_phase1(
        prob_low, report, _assignments(prob_low), elapsed_phase1=40.0, timelimit=60.0)
    dec_high = B._choose_repair_mode_from_phase1(
        prob_high, report, _assignments(prob_high), elapsed_phase1=40.0, timelimit=60.0)

    assert dec_low.mode == "simple"
    assert dec_high.mode == "greedy"


def test_large_w1_dominant_keeps_stable_simple_repair():
    # Variance safety (goal §priority-1): greedy repair is BIMODAL on large dense
    # w1-dominant instances (train prob_18 n=300: 49M good vs 922M ±20x explosion),
    # so the selector must NOT force greedy there -- dense crane violations route
    # to the deterministic simple serialization (stable ~floor).  Small w1-dominant
    # instances DO get greedy (test_tardiness_dominant_avoids_self_defeating_...).
    report = {
        "feasible": False, "stage": 2, "objective": None,
        "violations": [f"block {i} blocked" for i in range(60)],
    }
    prob = _prob(n_blocks=300, weights={"w1": 30000, "w2": 10, "w3": 100})
    dec = B._choose_repair_mode_from_phase1(
        prob, report, _assignments(prob), elapsed_phase1=40.0, timelimit=60.0)
    assert dec.mode == "simple"


def test_selector_does_not_use_train_shape_buckets():
    # The forbidden thing (goal §condition-4) is branching on instance SHAPE for
    # the GENERAL symptom path.  With identical symptoms and non-w1-dominant
    # weights, two instances of very different size must get the SAME decision.
    # (The ONLY size dependence is the w1-dominant variance-safety gate above,
    # which is exercised by test_large_w1_dominant_keeps_stable_simple_repair.)
    report = {
        "feasible": False,
        "stage": 2,
        "objective": None,
        "violations": [f"block {i} blocked" for i in range(40)],
    }
    prob_small = _prob(n_blocks=40, weights={"w1": 1, "w2": 10, "w3": 100})
    prob_large = _prob(n_blocks=300, weights={"w1": 1, "w2": 10, "w3": 100})

    dec_small = B._choose_repair_mode_from_phase1(
        prob_small, report, _assignments(prob_small), elapsed_phase1=40.0, timelimit=60.0)
    dec_large = B._choose_repair_mode_from_phase1(
        prob_large, report, _assignments(prob_large), elapsed_phase1=40.0, timelimit=60.0)

    assert dec_small.mode == dec_large.mode


def test_main_entry_uses_auto_selector_not_weight_bucket():
    src = (SRC / "myalgorithm.py").read_text(encoding="utf-8")

    assert "simple_repair_floor" not in src
    assert 'repair_mode = "auto"' in src
