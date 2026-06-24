"""Unit tests for the regime router (Milestone M6, src/regime.py).

Covers (1) classification on the three example regimes from the generated
suite, (2) the safety contract -- malformed / flat-weight / unknown-packing
inputs route to UNKNOWN and yield the DEFAULT_CONFIG that reproduces current
behaviour, and (3) the no-op guarantee that DEFAULT_CONFIG / TOSSUP carry no
behavioural override.  Pure module, no solver dependency, no I/O at import.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import regime as R  # noqa: E402


# -----------------------------------------------------------------------------
# Minimal synthetic prob_info builders (stdlib only, no instance files needed).
# -----------------------------------------------------------------------------

def _square_block(side: float):
    """A single-orientation, single-layer square block of the given side."""
    layer = [[0.0, 0.0], [side, 0.0], [side, side], [0.0, side]]
    return {
        "release_time": 0,
        "due_date": 100,
        "processing_time": 5,
        "workload": 10,
        "bay_preferences": [50, 50],
        "shape": [{"orientation": 0, "layers": [layer]}],
    }


def _prob(weights, n_blocks, n_bays, *, block_side, bay_w=100, bay_h=100):
    return {
        "name": "synthetic",
        "weights": dict(weights),
        "bays": [{"width": bay_w, "height": bay_h} for _ in range(n_bays)],
        "blocks": [_square_block(block_side) for _ in range(n_blocks)],
    }


# Density = n_blocks * side^2 / (n_bays * bay_w * bay_h).
# For 2 bays of 100x100 = 20000 total area:
#   loose: side small enough that total block area / 20000 < 0.55
#   tight: total block area / 20000 >= 0.55
LOOSE_SIDE = 10.0   # 10 blocks * 100 = 1000 -> density 0.05 (loose)
TIGHT_SIDE = 40.0   # large blocks -> high density (tight)


# -----------------------------------------------------------------------------
# Classification of the three example regimes (mirrors instances/gen suite).
# -----------------------------------------------------------------------------

def test_w2_dominant_loose_small_is_decomposition():
    # gen_n10_loose_w2_*: w2 dominant, loose packing, small n.
    prob = _prob({"w1": 7, "w2": 2667, "w3": 20}, n_blocks=10, n_bays=2,
                 block_side=LOOSE_SIDE)
    assert R.classify(prob) is R.Regime.DECOMPOSITION
    cfg = R.config_from_prob(prob)
    assert cfg.regime is R.Regime.DECOMPOSITION
    assert cfg.sa_temp_frac < R.DEFAULT_CONFIG.sa_temp_frac  # exploit


def test_w3_dominant_loose_is_decomposition():
    prob = _prob({"w1": 7, "w2": 20, "w3": 2667}, n_blocks=40, n_bays=3,
                 block_side=LOOSE_SIDE, bay_w=100, bay_h=100)
    assert R.classify(prob) is R.Regime.DECOMPOSITION


def test_w1_dominant_tight_large_is_escape():
    # gen_n120_tight_w1_*: w1 dominant, tight packing, large n -> escape hatch.
    prob = _prob({"w1": 2667, "w2": 7, "w3": 20}, n_blocks=120, n_bays=2,
                 block_side=TIGHT_SIDE)
    assert R.extract_features(prob).packing is R.Packing.TIGHT
    assert R.classify(prob) is R.Regime.ESCAPE
    cfg = R.config_from_prob(prob)
    assert cfg.use_cpsat is False
    assert cfg.sa_temp_frac > R.DEFAULT_CONFIG.sa_temp_frac  # explore
    # destroy-repair (index 2) is favoured over shift/swap in escape.
    assert cfg.op_weights[2] > cfg.op_weights[0]


def test_w1_dominant_loose_small_is_tossup():
    # w1 dominant but loose + small -> not escape, not decomposition -> tossup.
    prob = _prob({"w1": 2667, "w2": 7, "w3": 20}, n_blocks=10, n_bays=2,
                 block_side=LOOSE_SIDE)
    assert R.classify(prob) is R.Regime.TOSSUP


def test_w1_dominant_tight_small_is_tossup():
    # Tight but small n -> escape requires LARGE n, so this stays tossup.
    prob = _prob({"w1": 2667, "w2": 7, "w3": 20}, n_blocks=10, n_bays=2,
                 block_side=TIGHT_SIDE)
    assert R.extract_features(prob).packing is R.Packing.TIGHT
    assert R.classify(prob) is R.Regime.TOSSUP


# -----------------------------------------------------------------------------
# Safety contract: defaults are safe / no-op when the regime is unknown.
# -----------------------------------------------------------------------------

def test_flat_weights_route_to_unknown_default():
    prob = _prob({"w1": 1, "w2": 1, "w3": 1}, n_blocks=10, n_bays=2,
                 block_side=LOOSE_SIDE)
    assert R.classify(prob) is R.Regime.UNKNOWN
    assert R.config_from_prob(prob) == R.DEFAULT_CONFIG


def test_unknown_packing_routes_to_unknown():
    # No bays -> density None -> packing UNKNOWN -> UNKNOWN regardless of weights.
    prob = {"name": "x", "weights": {"w1": 2667, "w2": 7, "w3": 20},
            "bays": [], "blocks": [_square_block(10.0)]}
    assert R.classify(prob) is R.Regime.UNKNOWN
    assert R.config_from_prob(prob) == R.DEFAULT_CONFIG


def test_malformed_inputs_never_raise():
    for bad in (None, {}, {"weights": None}, {"weights": {"w1": "x"}},
                {"bays": "nope"}, 42, "string", []):
        # Neither classify nor config_from_prob may raise.
        reg = R.classify(bad)
        assert isinstance(reg, R.Regime)
        cfg = R.config_from_prob(bad)
        assert isinstance(cfg, R.RegimeConfig)
    # The empty/None cases specifically must give the safe default.
    assert R.config_from_prob(None) == R.DEFAULT_CONFIG
    assert R.config_from_prob({}) == R.DEFAULT_CONFIG


def test_unknown_and_tossup_configs_are_no_ops():
    # The whole point of the no-op contract: UNKNOWN == DEFAULT, and TOSSUP
    # differs from DEFAULT only in provenance (regime label + notes), never in
    # any behavioural knob.
    assert R.config_for(R.Regime.UNKNOWN) == R.DEFAULT_CONFIG
    tossup = R.config_for(R.Regime.TOSSUP)
    d = R.DEFAULT_CONFIG
    behavioural = ("seed_priority", "use_cpsat", "work_frac", "hard_stop_frac",
                   "cpsat_budget_frac", "op_weights", "sa_temp_frac", "mode")
    for fld in behavioural:
        assert getattr(tossup, fld) == getattr(d, fld), fld


def test_config_for_unexpected_value_is_default():
    assert R.config_for("not a regime") == R.DEFAULT_CONFIG  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# Purity / stdlib-only contract.
# -----------------------------------------------------------------------------

def test_module_imports_no_heavy_deps():
    # regime.py must not pull numpy / ortools / shapely into sys.modules on its
    # own (it imports only dataclasses + enum).  Guards invariant section 4.5.
    import importlib

    mod = importlib.import_module("regime")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for banned in ("import numpy", "import ortools", "import shapely",
                   "from numpy", "from ortools", "from shapely"):
        assert banned not in src, f"regime.py must not {banned}"


def test_determinism():
    prob = _prob({"w1": 2667, "w2": 7, "w3": 20}, n_blocks=120, n_bays=2,
                 block_side=TIGHT_SIDE)
    a = R.config_from_prob(prob)
    b = R.config_from_prob(prob)
    assert a == b
