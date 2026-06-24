# regime.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Milestone M6: instance regime routing.
#
# This module is a PURE, STDLIB-ONLY classifier.  It reads three cheap features
# of a `prob_info` dict -- the weight ratio (w1:w2:w3), the packing density
# (block area / bay area), and the instance size (n_blocks, n_bays) -- and emits
# a small, structured `RegimeConfig` describing how `algorithm()` should spend
# its time budget: which seeds to prioritise, what fraction of the wall-clock to
# give to construction vs. search, how to bias the ALNS operator roulette, and
# the simulated-annealing starting-temperature hint.
#
# Design contract (notes/dev-plan.md section 4 invariants + section 5.4):
#   * imports nothing beyond the standard library -- no numpy, no ortools, no
#     shapely.  It therefore CANNOT raise an ImportError on the evaluation
#     server and CANNOT crash the solver.  All public functions are pure and
#     deterministic (no RNG, no clock, no I/O).
#   * every field of the returned config has a value that REPRODUCES the current
#     hard-coded behaviour of algorithm().  When the regime is UNKNOWN (or any
#     feature is missing / malformed) the defaults are returned unchanged, so
#     wiring this module into algorithm() is a strict no-op until the per-regime
#     hints are actually consulted.  This protects invariant section 4.4 ("never
#     worse than baseline") and section 4.6/4.7 (timeguard / crash-free): a buggy
#     or mis-tuned regime can only ever fall back to today's verified behaviour.
#   * fully self-contained and unit-testable (see tests/test_regime.py).
#
# -----------------------------------------------------------------------------
# Regime map  (strategy.md section 5 "instance regime routing" table)
# -----------------------------------------------------------------------------
# strategy.md section 5 defines three coarse regimes by (w1:w2:w3) x packing
# density x n.  We refine that 3-row table into the cross product
#   dominant-weight {w1, w2, w3}  x  packing {loose, tight}  x  size {small, large}
# and map each cell back to one of strategy.md's three named strategies:
#
#   "decomposition"  (strategy.md: "decomposition clearly dominant" --
#                      w2/w3-dominant, loose packing, small n)
#       Layer 1 already nails Z2/Z3 nearly optimally and Layer 2 decodes almost
#       unchanged; the no-good-cut loop converges fast.  -> prioritise the
#       balanced / preference / CP-SAT assignment seeds, give MOST of the budget
#       to the cheap assignment-level search, and bias the ALNS roulette toward
#       cheap combinatorial moves (shift / swap) over destroy-repair.  Low SA
#       temperature: the landscape is well-conditioned, exploit it.
#
#   "tossup"         (strategy.md: "toss-up" -- mid n, w1-dominant)
#       Packing tightness decides; run the hybrid cut loop.  -> balanced seed mix,
#       even budget split, balanced operator weights, medium SA temperature.
#       This is the DEFAULT regime and reproduces current behaviour exactly.
#
#   "escape"         (strategy.md: "single-ALNS escape hatch dominant" --
#                      largest + tightest packing + w1-dominant)
#       Assignment and geometry must co-evolve; Layer 1 only seeds a shared
#       monolithic path.  -> prioritise a fast guaranteed-feasible floor, spend
#       LESS time decoding many seeds (the big piles are expensive) and MORE on
#       the destroy-repair neighbourhood that can re-route overflow blocks, with
#       a higher SA temperature to escape the deep local minima of tight packing.
#       This is exactly the cell strategy.md section 6.4 flags as the "common
#       remaining fear" (cut loop may not converge in 30 min).
#
# Every hint is ADVISORY: algorithm() reads them but its hard safety rails
# (verified floor, timeguard, check_feasibility gate, try/except) are untouched.
"""Instance regime classifier for OGC 2026 (Milestone M6).

Public API
----------
classify(prob_info) -> Regime
    Pure feature extraction + bucketing.  Never raises; returns Regime.UNKNOWN
    (the safe default carrier) when features are missing or malformed.

config_for(regime) -> RegimeConfig
config_from_prob(prob_info) -> RegimeConfig
    Map a Regime (or a prob_info directly) to a RegimeConfig.  The UNKNOWN regime
    yields DEFAULT_CONFIG, which reproduces algorithm()'s current behaviour, so
    consulting this module is a no-op until the per-regime hints are wired in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


# -----------------------------------------------------------------------------
# Feature thresholds (single source of truth; tune here, not in algorithm()).
# -----------------------------------------------------------------------------
# A weight is "dominant" when it is at least this multiple of the next largest.
# The generated suite uses ratios like 2667 : 20 : 7 (dominant >= ~130x), while a
# flat 1:1:1 instance has ratio 1.0 -> never dominant -> UNKNOWN/tossup.
_DOMINANCE_RATIO = 3.0

# Packing density (sum block bbox area / sum bay area) above this is "tight".
# Mirrors the density estimate algorithm() already computes (myalgorithm.py
# ~L853-856): orientation-0 bbox areas over total bay area.
_TIGHT_DENSITY = 0.55

# Block-count buckets.  "large" piles are where per-bay decode throughput and
# the cut-loop convergence fear (strategy.md 6.4) dominate.
_SMALL_N = 20
_LARGE_N = 80


class Dominant(str, Enum):
    """Which objective weight dominates the weighted sum."""

    W1 = "w1"   # tardiness-dominant   (Z1)
    W2 = "w2"   # imbalance-dominant   (Z2)
    W3 = "w3"   # preference-dominant  (Z3)
    NONE = "none"  # no single weight is >= _DOMINANCE_RATIO x the next


class Packing(str, Enum):
    LOOSE = "loose"
    TIGHT = "tight"
    UNKNOWN = "unknown"


class Size(str, Enum):
    SMALL = "small"
    MID = "mid"
    LARGE = "large"


class Regime(str, Enum):
    """Coarse strategy bucket (strategy.md section 5).

    The three named strategies plus an explicit UNKNOWN safe-default carrier.
    """

    DECOMPOSITION = "decomposition"   # Layer1-dominant, cut loop converges fast
    TOSSUP = "tossup"                 # hybrid; current default behaviour
    ESCAPE = "escape"                 # co-evolve / monolithic escape hatch
    UNKNOWN = "unknown"               # features missing -> DEFAULT_CONFIG


@dataclass(frozen=True)
class Features:
    """Cheap, pure features extracted from prob_info."""

    dominant: Dominant = Dominant.NONE
    dominance_ratio: float = 1.0
    packing: Packing = Packing.UNKNOWN
    density: float | None = None
    size: Size = Size.MID
    n_blocks: int = 0
    n_bays: int = 0


@dataclass(frozen=True)
class RegimeConfig:
    """Advisory search configuration for one regime.

    Every default below reproduces algorithm()'s CURRENT behaviour, so a caller
    that reads these fields but is handed DEFAULT_CONFIG behaves identically to
    today.  Fields are plain Python scalars / tuples so the config is trivially
    serialisable and pickle-safe (relevant once M5 parallelism lands).

    Fields
    ------
    regime
        The Regime this config was built for (provenance / logging).
    seed_priority
        Ordered tuple of seed names to *decode first* when the decode budget is
        tight.  Names match algorithm()'s seeds: "pref", "balanced", "cpsat".
        ("trivial"/"baseline" floors are always built regardless.)  The default
        order matches the current named_seeds insertion order.
    use_cpsat
        Whether the CP-SAT assignment seed is worth its time box for this regime
        (default True == current behaviour).  Escape/large-tight regimes may turn
        it off to spend that budget on search instead.
    work_frac
        Fraction of timelimit at which to STOP search (the `done_by` knob).
        algorithm() currently hard-codes 0.80; the default preserves that.
    hard_stop_frac
        Absolute fraction past which no new check_feasibility may START.
        algorithm() currently hard-codes 0.93; default preserves it.
    cpsat_budget_frac
        Fraction of timelimit offered to the CP-SAT seed (capped by algorithm()'s
        own 10s / remaining-window guards).  Current code uses 0.20.
    op_weights
        Initial ALNS roulette weights (shift, swap, destroy_repair).  algorithm()
        currently starts all operators at 1.0; the default preserves that.  These
        are STARTING weights only -- the adaptive roulette still re-learns them.
    sa_temp_frac
        Starting SA temperature as a fraction of |best_obj|.  algorithm() uses
        0.10; the default preserves it.  Higher == more exploration (escape),
        lower == more exploitation (decomposition).
    mode
        Coarse search mode label for logging / future co-evolve branch:
        "decomposition" (assignment-level only, current behaviour) vs
        "escape" (reserve budget for a monolithic co-evolve path; not yet
        implemented -- treated as decomposition until that branch exists).
    notes
        Human-readable provenance string (which strategy.md row).
    """

    regime: Regime = Regime.UNKNOWN
    seed_priority: tuple[str, ...] = ("pref", "balanced", "cpsat")
    use_cpsat: bool = True
    work_frac: float = 0.80
    hard_stop_frac: float = 0.93
    cpsat_budget_frac: float = 0.20
    op_weights: tuple[float, float, float] = (1.0, 1.0, 1.0)
    sa_temp_frac: float = 0.10
    mode: str = "decomposition"
    notes: str = "default (reproduces current behaviour)"


# The canonical safe default.  Returned for Regime.UNKNOWN and used as the base
# that every other regime config is derived from via dataclasses.replace, so any
# field NOT explicitly overridden inherits the current verified behaviour.
DEFAULT_CONFIG = RegimeConfig()


# -----------------------------------------------------------------------------
# Feature extraction (pure, never raises).
# -----------------------------------------------------------------------------

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _weight_dominance(weights) -> tuple[Dominant, float]:
    """Return (which weight dominates, ratio largest/second-largest).

    A weight dominates iff it is >= _DOMINANCE_RATIO times the next largest.
    Ratio defaults to 1.0 (no dominance) when weights are missing/degenerate.
    """
    try:
        w1 = float(weights.get("w1", 1.0))
        w2 = float(weights.get("w2", 1.0))
        w3 = float(weights.get("w3", 1.0))
    except (AttributeError, TypeError, ValueError):
        return Dominant.NONE, 1.0

    triples = [(Dominant.W1, w1), (Dominant.W2, w2), (Dominant.W3, w3)]
    triples.sort(key=lambda kv: kv[1], reverse=True)
    top_name, top = triples[0]
    second = triples[1][1]
    if top <= 0:
        return Dominant.NONE, 1.0
    ratio = top / second if second > 0 else float("inf")
    if ratio >= _DOMINANCE_RATIO:
        return top_name, ratio
    return Dominant.NONE, ratio


def _density(prob_info) -> float | None:
    """Sum of orientation-0 layer-0 bbox areas / sum of bay areas.

    Mirrors the density estimate algorithm() computes for tracing
    (myalgorithm.py ~L853-856) but stdlib-only.  Returns None if it cannot be
    computed (no bays, malformed shapes) -- the caller treats None as UNKNOWN
    packing, which routes to the safe default.
    """
    try:
        bays = prob_info.get("bays") or []
        total_bay = 0.0
        for bay in bays:
            total_bay += float(bay["width"]) * float(bay["height"])
        if total_bay <= 0:
            return None
        total_block = 0.0
        for blk in prob_info.get("blocks") or []:
            shape = blk.get("shape") or []
            if not shape:
                continue
            layers = shape[0].get("layers") or []
            if not layers:
                continue
            layer0 = layers[0]
            xs = [float(p[0]) for p in layer0]
            ys = [float(p[1]) for p in layer0]
            if not xs or not ys:
                continue
            total_block += max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))
        return total_block / total_bay
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _size_bucket(n_blocks: int) -> Size:
    if n_blocks <= _SMALL_N:
        return Size.SMALL
    if n_blocks >= _LARGE_N:
        return Size.LARGE
    return Size.MID


def extract_features(prob_info) -> Features:
    """Pure feature extraction.  Never raises; returns conservative defaults on
    any malformed input so classify() can still route to UNKNOWN safely."""
    if not isinstance(prob_info, dict):
        return Features()
    weights = prob_info.get("weights") or {}
    dominant, ratio = _weight_dominance(weights)

    density = _density(prob_info)
    if density is None:
        packing = Packing.UNKNOWN
    elif density >= _TIGHT_DENSITY:
        packing = Packing.TIGHT
    else:
        packing = Packing.LOOSE

    n_blocks = len(prob_info.get("blocks") or [])
    n_bays = len(prob_info.get("bays") or [])
    return Features(
        dominant=dominant,
        dominance_ratio=ratio,
        packing=packing,
        density=density,
        size=_size_bucket(n_blocks),
        n_blocks=n_blocks,
        n_bays=n_bays,
    )


# -----------------------------------------------------------------------------
# Classification: features -> Regime (strategy.md section 5 mapping).
# -----------------------------------------------------------------------------

def classify(prob_info) -> Regime:
    """Bucket an instance into one of strategy.md section 5's regimes.

    Decision rule (conservative -- only the confidently-classifiable cells leave
    UNKNOWN):

      * UNKNOWN  if no weight dominates (>= 3x next) OR packing density is
                 unknown.  -> DEFAULT_CONFIG (current behaviour).  This is the
                 deliberate no-op safety net.
      * ESCAPE   if w1-dominant AND tight packing AND large n.  This is exactly
                 strategy.md's "single-ALNS escape hatch dominant" cell (largest
                 + tightest + w1-dominant).
      * DECOMPOSITION if (w2- or w3-dominant) AND loose packing.  strategy.md's
                 "decomposition clearly dominant" cell (Z2/Z3-dominant, loose).
                 Small n strengthens this but is not required.
      * TOSSUP   everything else that is classifiable (mid sizes, w1-dominant but
                 not large+tight, dominant weight on a non-clear packing, etc.).
                 strategy.md's "toss-up" row.  TOSSUP's config == DEFAULT_CONFIG.
    """
    f = extract_features(prob_info)

    if f.dominant is Dominant.NONE or f.packing is Packing.UNKNOWN:
        return Regime.UNKNOWN

    if (f.dominant is Dominant.W1
            and f.packing is Packing.TIGHT
            and f.size is Size.LARGE):
        return Regime.ESCAPE

    if f.dominant in (Dominant.W2, Dominant.W3) and f.packing is Packing.LOOSE:
        return Regime.DECOMPOSITION

    return Regime.TOSSUP


# -----------------------------------------------------------------------------
# Regime -> RegimeConfig.
# -----------------------------------------------------------------------------
# Each non-default config is built by overriding only the fields that differ
# from DEFAULT_CONFIG, so any field not named here inherits today's verified
# value.  This guarantees the "wiring is a no-op until tuned" property.

_CONFIGS: dict[Regime, RegimeConfig] = {
    # strategy.md section 5, row "decomposition clearly dominant".
    # Z2/Z3 are closed-form and Layer 1 nearly nails them; exploit a
    # well-conditioned landscape with cheap combinatorial moves.
    Regime.DECOMPOSITION: replace(
        DEFAULT_CONFIG,
        regime=Regime.DECOMPOSITION,
        seed_priority=("balanced", "pref", "cpsat"),
        use_cpsat=True,
        work_frac=0.80,
        cpsat_budget_frac=0.25,
        op_weights=(1.3, 1.3, 0.6),   # favour shift/swap over destroy-repair
        sa_temp_frac=0.05,            # exploit: low temperature
        mode="decomposition",
        notes="strategy.md s5: decomposition clearly dominant "
              "(w2/w3-dom, loose); Layer1 nails Z2/Z3, cut loop converges fast.",
    ),
    # strategy.md section 5, row "toss-up".  Identical to the default so this
    # regime is, by construction, a no-op relative to current behaviour.
    Regime.TOSSUP: replace(
        DEFAULT_CONFIG,
        regime=Regime.TOSSUP,
        notes="strategy.md s5: toss-up (mid n, w1-dom); hybrid cut loop "
              "== current default behaviour.",
    ),
    # strategy.md section 5, row "single-ALNS escape hatch dominant".
    # Largest + tightest + w1-dominant: get a feasible floor fast, decode fewer
    # seeds, lean on destroy-repair to re-route overflow, raise SA temperature to
    # escape the deep minima of tight packing (the 6.4 "cut loop may not
    # converge in 30 min" fear lives exactly here).
    Regime.ESCAPE: replace(
        DEFAULT_CONFIG,
        regime=Regime.ESCAPE,
        seed_priority=("balanced", "pref"),  # skip cpsat -- spend it on search
        use_cpsat=False,
        work_frac=0.82,
        cpsat_budget_frac=0.0,
        op_weights=(0.8, 0.8, 1.6),   # lean on destroy-repair
        sa_temp_frac=0.20,            # explore: high temperature
        mode="escape",
        notes="strategy.md s5: single-ALNS escape hatch dominant "
              "(largest + tightest + w1-dom); co-evolve, destroy-repair heavy.",
    ),
    Regime.UNKNOWN: DEFAULT_CONFIG,
}


def config_for(regime: Regime) -> RegimeConfig:
    """Return the RegimeConfig for a Regime.  Unknown / unexpected values fall
    back to DEFAULT_CONFIG (current behaviour) -- never raises."""
    return _CONFIGS.get(regime, DEFAULT_CONFIG)


def config_from_prob(prob_info) -> RegimeConfig:
    """Convenience: classify(prob_info) then config_for(...).  Pure, never
    raises -- on any failure returns DEFAULT_CONFIG so callers are always safe.

    This is the single entry point algorithm() should call.
    """
    try:
        return config_for(classify(prob_info))
    except Exception:
        return DEFAULT_CONFIG
