# myalgorithm.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Solver-free entry. Decomposition + assignment-level local search.
#
# Architecture (see notes/strategy.md):
#   Layer 1  bay assignment  -> fixes Z2 (load imbalance) and Z3 (preference)
#                               exactly; Z2/Z3 are closed-form functions of the
#                               block->bay map (verified against utils.py).
#   Layer 2  per-bay decoder -> for the blocks in one bay, order + place + time
#                               using the crane-feasible primitives from the
#                               baseline.  Feasibility checks are PER-BAY
#                               independent, so bays decode independently and a
#                               guaranteed empty-window fallback makes every bay
#                               feasible by construction.
#   Search   assignment-level hill-climb (shift / swap of blocks between bays)
#            on the TRUE objective.  Only the two touched bays are re-decoded
#            per move; Z2/Z3 are recomputed in closed form.  CP-SAT (OR-Tools,
#            if importable) seeds a Z2/Z3-balanced assignment as an extra start.
#
# Robustness (-1 avoidance is the #1 scoring priority):
#   * A guaranteed-feasible floor (baseline greedy, then a trivial force-place
#     solution) is always computed first and kept.
#   * Best feasible incumbent is tracked by true objective; we never return
#     anything worse than the baseline.
#   * Hard wall-clock guard; everything wrapped in try/except; a final
#     check_feasibility gate before returning.

from __future__ import annotations

import math
import os
import random
import time

from utils import (
    Bay, Block, check_feasibility, check_entry, check_exit, check_collisions,
    _resolve_layers,
)
from baseline_greedy import (
    greedyalgorithm,
    _block_bbox,
    _block_size,
    _candidate_positions,
    _find_earliest_slot,
    _empty_bay_entry,
    _build_operations,
    set_pos_k_override,
    _block_raster_cells,
)

# GENERAL speedup (OGC_BR_CACHE, default ON): memoize Block.bounding_rect ON THE
# INSTANCE.  bounding_rect recomputes the layer-flatten + min/max ~7.6M times per
# solve, yet a Block is immutable after creation (the greedy/decoder build a FRESH
# Block per (block,orient,x,y) -- they never mutate x/y/orient), so the bbox is
# constant per instance.  We re-validate the cache against the live (x,y,orient) so
# it stays exact even if some path mutated a Block.  Patches utils.Block so the
# cache also covers the calls INSIDE utils.check_entry/exit/collisions (their AABB
# pre-filter), which our own caches cannot reach.  Kill-switch OGC_BR_CACHE=0.
def _install_bounding_rect_cache():
    import os as _os
    if _os.environ.get("OGC_BR_CACHE", "1").strip().lower() in ("0", "false", "off", "no"):
        return
    import utils as _u
    if getattr(_u.Block, "_br_cache_installed", False):
        return
    _orig = _u.Block.bounding_rect

    def _cached(self):
        k = (self.x, self.y, self.orient_idx)
        c = getattr(self, "_brc", None)
        if c is not None and c[0] == k:
            return c[1]
        v = _orig(self)
        try:
            self._brc = (k, v)
        except Exception:
            pass
        return v
    _u.Block.bounding_rect = _cached
    _u.Block._br_cache_installed = True


_install_bounding_rect_cache()

# Analysis instrument (notes/dev-plan.md §4): OFF unless OGC_TRACE is set, so the
# evaluation server (which never sets it) gets a no-op NullTracer and zero
# behaviour change.  The import itself is guarded so a missing instrument.py can
# never crash the solver (invariant §4.7); the fallback yields a silent tracer.
try:
    from instrument import (
        get_tracer,
        bimodal_start,
        bimodal_log,
        bimodal_flush,
        bimodal_enabled,
    )
except Exception:  # pragma: no cover - instrumentation must never break the solver
    import contextlib as _contextlib

    def get_tracer(run_name="run"):
        class _SilentTracer:
            enabled = False

            def meta(self, **_kw):
                pass

            def log(self, *_a, **_kw):
                pass

            def phase(self, _name):
                return _contextlib.nullcontext()

            def flush(self):
                return None

        return _SilentTracer()

    def bimodal_start(*_a, **_kw):
        return False

    def bimodal_log(*_a, **_kw):
        pass

    def bimodal_flush():
        return None

    def bimodal_enabled():
        return False


# Regime router (Milestone M6).  Pure stdlib; config_from_prob never raises and
# returns a DEFAULT config (== current behaviour) for the UNKNOWN/TOSSUP regimes,
# so consulting it is a strict no-op until an instance is confidently classified.
# Guarded import so a missing/broken regime.py can never crash the solver
# (invariant 4.7); on failure we fall back to hard-coded defaults below.
try:
    from regime import config_from_prob as _regime_config
except Exception:  # pragma: no cover - routing must never break the solver
    _regime_config = None

# Milestone M5: optional 4-core independent-seed multi-start.  Guarded import so a
# missing/broken parallel_decode can never crash the solver; run_parallel_multistart
# itself never raises and returns None on any failure -> we fall through to the
# in-process search (parallelism is a pure speedup, invariant 4.7).
try:
    from parallel_decode import (
        run_parallel_multistart,
        run_parallel_bay_decode,
        run_parallel_cumlevel,
        MAX_WORKERS as MAX_PARALLEL_WORKERS,
    )
except Exception:  # pragma: no cover
    run_parallel_multistart = None
    run_parallel_bay_decode = None
    run_parallel_cumlevel = None
    MAX_PARALLEL_WORKERS = 4  # server is <= 4 cores; mirrors parallel_decode.MAX_WORKERS


def _env_on(name: str, default: bool) -> bool:
    """Read a boolean OGC_* feature flag from the environment.  The evaluation
    server sets none of these, so `default` is exactly what ships -- the flags
    exist only for local A/B testing and as kill-switches.  Never raises."""
    try:
        v = os.environ.get(name, "").strip().lower()
        if not v:
            return default
        return v not in ("0", "false", "off", "no")
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float OGC_* experiment knob.  Unset / unparseable -> `default`,
    so an absent env var is bit-identical to the shipped constant.  Never
    raises."""
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return float(v)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int OGC_* experiment knob.  Unset / unparseable -> `default`,
    so an absent env var is bit-identical to the shipped constant.  Never
    raises."""
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return int(float(v))
    except Exception:
        return default


import contextlib as _contextlib

# Stage-timing instrumentation (OGC_STAGE_TIMING, default OFF -> zero overhead and
# no behaviour change; the eval server never sets it).  Accumulates wall-seconds
# per named pipeline stage for ONE algorithm() call; flushed as a JSON line to
# stderr at the end so a harness can build a per-instance breakdown.
_STAGE_T: dict = {}
# Live "current stage" stack (top = the sequence executing right now).  Maintained
# by _stage_timer whenever stage-timing is on so _z1_mark can TAG each z1 change
# with the sequence that produced it -> the trace / live curve shows WHICH stage
# every drop (and every flat spin) belongs to, in real time.
_STAGE_STACK: list = []


@_contextlib.contextmanager
def _stage_timer(name: str):
    if not _env_on("OGC_STAGE_TIMING", False):
        yield
        return
    _t = time.monotonic()
    _STAGE_STACK.append(name)
    try:
        yield
    finally:
        _STAGE_T[name] = _STAGE_T.get(name, 0.0) + (time.monotonic() - _t)
        try:
            _STAGE_STACK.pop()
        except IndexError:
            pass


# Per-stage OBJECTIVE-DELTA instrumentation (same OGC_STAGE_TIMING gate -> zero
# overhead and no behaviour change when off).  Pairs with _STAGE_T (per-stage
# wall-time): a stage with time>0 but NO _STAGE_OBJ entry ran without ever
# improving the incumbent (pure wasted budget); a large `delta` marks a
# high-value lever.  Recorded only on ADOPTION inside consider()/manual gates.
_STAGE_OBJ: dict = {}


def _stage_obj(name: str, before: float, after: float,
               z1=None, z2=None, z3=None):
    """Record an adopted improvement for `name`: accumulate count + total
    objective reduction, keep the first `before` and last `after`, and the latest
    Z1/Z2/Z3 after the stage (so a collector can show the per-stage Z1 trajectory).
    No-op unless OGC_STAGE_TIMING is set.  Never raises."""
    if not _env_on("OGC_STAGE_TIMING", False):
        return
    try:
        d = _STAGE_OBJ.get(name)
        if d is None:
            d = {"before": before, "after": after, "n_adopt": 0, "delta": 0.0}
            _STAGE_OBJ[name] = d
        d["after"] = after
        if z1 is not None:
            d["z1"] = z1
        if z2 is not None:
            d["z2"] = z2
        if z3 is not None:
            d["z3"] = z3
        d["n_adopt"] += 1
        d["delta"] += (before - after)
    except Exception:
        pass


def _env_floats(name: str, n: int):
    """Read a comma-separated float tuple of length `n` (e.g. "0.6,0.6,1.8").
    Returns None when unset / malformed so the caller keeps its existing value.
    Never raises."""
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return None
        parts = [float(p) for p in v.split(",") if p.strip() != ""]
        if len(parts) != n:
            return None
        return tuple(parts)
    except Exception:
        return None


def _env_list(name: str):
    """Read a comma-separated string list (e.g. "tardy,pref,balanced,cpsat").
    Returns None when unset / empty so the caller keeps its existing value.
    Never raises."""
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return None
        parts = [p.strip() for p in v.split(",") if p.strip() != ""]
        return tuple(parts) if parts else None
    except Exception:
        return None


random.seed(20260529)

# Wall-clock SAFETY factor for decode-cost admission (-1 guard).
#
# Every place that decides "may I START this decode before the deadline?" relies
# on _decode_cost_est / _bay_decode_secs, whose 0.0025 coefficient is calibrated
# on the LOCAL CPU and against the baseline's Phase-1 placement -- but our own
# _decode_bay (per-block _candidate_positions + _find_earliest_slot) is heavier,
# and a single per-bay decode is ATOMIC (cannot be interrupted once started).
# A trace of gen_n40_loose_w3_s17 showed one in-move re-decode of a ~38-block bay
# estimated at ~7s actually take ~12s (a ~1.7x underestimate), letting the search
# overrun its soft deadline (46.8s) to 52s = 87% of the limit -- on a slower
# evaluation server that single decode could cross the hard stop and score -1.
# Inflating every admission estimate by this factor guarantees that any decode we
# allow to start finishes BEFORE the deadline even when the estimate is optimistic
# (admitted iff now + SAFETY*est <= deadline, and actual < SAFETY*est), pulling
# wall-clock back to ~78% of the limit.  It only ever makes us MORE conservative,
# so it can never introduce an infeasibility or a regression.
_DECODE_SAFETY = 1.8


# ---------------------------------------------------------------------------
# Geometry / feasibility helpers (single-bay)
# ---------------------------------------------------------------------------

def _fits_bay(block_data: dict, oi: int, bay: Bay) -> bool:
    bb = _block_bbox(block_data, oi)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    if bw > bay.width + 1e-6 or bh > bay.height + 1e-6:
        return False
    px = max(0, math.ceil(-bb[0]))
    py = max(0, math.ceil(-bb[1]))
    return bay.contains_block(Block(block_id=-1, block_data=block_data,
                                    x=px, y=py, orient_idx=oi))


def _orient_crane_complexity(block_data: dict, oi: int) -> tuple[float, int, float]:
    """Cheap orientation-level proxy for future crane obstruction risk.

    More layers and larger horizontal footprint create more possible j>=k sweep
    obstructions.  This is used only for ordering/tie-breaking; exact crane
    feasibility is still checked by _find_slot_crane_safe.
    """
    try:
        layers = block_data["shape"][oi].get("layers", []) or []
        n_layers = max(1, len(layers))
        bb = _block_bbox(block_data, oi)
        area = max(0.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        # A block with many layers creates O(n_layers^2) possible j>=k sweep
        # interactions across surrounding blocks, so layer count should bite
        # harder than plain footprint area.
        return (float(n_layers * n_layers) * area, int(n_layers), float(area))
    except Exception:
        return (0.0, 1, 0.0)


def _block_crane_complexity(block_data: dict) -> tuple[float, int, float]:
    """Best available orientation's crane-risk proxy for decode ordering."""
    try:
        return min(
            (_orient_crane_complexity(block_data, oi)
             for oi in range(len(block_data.get("shape", []) or []))),
            default=(0.0, 1, 0.0),
        )
    except Exception:
        return (0.0, 1, 0.0)


def _feasible_bays(blocks_data: list, bays: list[Bay]) -> list[list[int]]:
    """For each block, the bays in which at least one orientation fits."""
    out: list[list[int]] = []
    for blk in blocks_data:
        ok = []
        for j, bay in enumerate(bays):
            if any(_fits_bay(blk, oi, bay) for oi in range(len(blk["shape"]))):
                ok.append(j)
        out.append(ok)
    return out


def _force_in_bay(bi: int, blocks_data: list, bay: Bay, bay_idx: int,
                  schedule: list[tuple[int, int]]):
    """Guaranteed-feasible placement of block bi in this bay via an empty
    time window.  Returns an assignment dict, or None if the block does not
    geometrically fit the bay in any orientation."""
    blk = blocks_data[bi]
    r_time = blk["release_time"]
    proc = blk["processing_time"]
    for oi in range(len(blk["shape"])):
        if _fits_bay(blk, oi, bay):
            bb = _block_bbox(blk, oi)
            px = max(0, math.ceil(-bb[0]))
            py = max(0, math.ceil(-bb[1]))
            nb = Block(block_id=bi, block_data=blk, x=px, y=py, orient_idx=oi)
            if not bay.contains_block(nb):
                continue
            entry = _empty_bay_entry(schedule, r_time, proc)
            return {"block_id": bi, "bay_id": bay_idx, "x": int(px), "y": int(py),
                    "orient_idx": oi, "entry_time": int(entry),
                    "exit_time": int(entry + proc)}
    return None


def _find_slot_crane_safe(new_blk: Block, bay: Bay, placed_in_bay: list,
                          schedule_in_bay: list, r_time: int, proc: int,
                          fast=None):
    """Earliest crane-feasible (entry, exit) for new_blk, COMPLETE w.r.t. the
    retroactive obstruction the baseline's _find_earliest_slot misses.

    _find_earliest_slot validates only the NEW block against blocks present at
    its own entry/exit -- it never re-checks that adding the new block breaks an
    EARLIER block whose entry/exit moment now falls inside the new block's window
    (B becomes present at A's entry and obstructs A's descent).  That asymmetry
    is exactly the Stage-2 crane-entry failure seen on congested instances: the
    decoder emits an optimistic Z1=0 placement that check_feasibility rejects, so
    we fall back to the baseline.  Here every candidate entry is checked in BOTH
    directions (new->present AND new->each spanned earlier block) plus pairwise
    collisions for all time-overlapping blocks, so a placement that is accepted
    keeps the whole bay feasible by induction.  Returns (None, None) if no
    crane-feasible slot exists at this position (caller force-places = serialise).
    """
    candidate_entries = sorted({r_time} | {e for _, e in schedule_in_bay})
    # fast=None -> use the module globals (FRONT path, default slow); fast=True ->
    # force the EXACT fast path for the bt-guarded re-decode levers (_REDECODE_FAST).
    _use_fast_crane = _FAST_CRANE if fast is None else bool(fast)
    _use_fast_geom = _FAST_GEOM if fast is None else bool(fast)
    # OGC_PP_RASTER routes through the EXACT fast path (byte-identical to the reference
    # path) so the per-block precompute below can be raster-prefiltered.  An explicit
    # fast=False (A/B verification) still gets the reference path untouched.
    if _PP_RASTER and fast is not False:
        _use_fast_crane = True
    # OGC_FAST_GEOM: AABB pre-filter cache (see _FAST_GEOM note).  new_blk's box is
    # fixed for this position; placed-block boxes are cached by id().  No-op when OFF.
    _bbox_cache = {} if _use_fast_geom else None
    _new_bbox = _aabb(new_blk) if _use_fast_geom else None
    if not _use_fast_crane:
        # Reference per-entry path (kept for A/B verification of the fast path).
        for entry_candidate in candidate_entries:
            entry = max(r_time, entry_candidate)
            exit_t = entry + proc
            present_at_entry = [b for b, (a, e) in zip(placed_in_bay, schedule_in_bay)
                                if a <= entry < e]
            _pe = (_filter_present(present_at_entry, _new_bbox, _bbox_cache)
                   if _use_fast_geom else present_at_entry)
            if check_entry(bay, _pe, new_blk, fast=True):
                continue
            # EXIT-side upper bound: with _CRANE_COEXIT a co-exiting block (e == exit_t)
            # is INCLUDED (matches official check_exit); else strict `<` as before.
            present_at_exit = [new_blk] + [
                b for b, (a, e) in zip(placed_in_bay, schedule_in_bay)
                if a < exit_t and (exit_t <= e if _CRANE_COEXIT else exit_t < e)]
            # check_exit targets new_blk: filter the SURROUNDING blocks by new_blk's
            # AABB (new_blk is its own target, kept whole) -- identical result.
            if _use_fast_geom:
                _px = [new_blk] + _filter_present(present_at_exit[1:], _new_bbox, _bbox_cache)
            else:
                _px = present_at_exit
            if check_exit(bay, _px, new_blk, fast=True):
                continue
            retro_bad = False
            for b_other, (a_o, e_o) in zip(placed_in_bay, schedule_in_bay):
                if entry <= a_o < exit_t and check_entry(bay, [new_blk], b_other, fast=True):
                    retro_bad = True
                    break
                # retro EXIT upper bound: include co-exiting block (e_o == exit_t) when
                # _CRANE_COEXIT (official treats co-exiting as both-present); else `<`.
                if entry < e_o and (e_o <= exit_t if _CRANE_COEXIT else e_o < exit_t) \
                        and check_exit(bay, [new_blk], b_other, fast=True):
                    retro_bad = True
                    break
            if retro_bad:
                continue
            coll = False
            for b_other, (a_o, e_o) in zip(placed_in_bay, schedule_in_bay):
                if entry < e_o and a_o < exit_t and check_collisions(bay, [new_blk, b_other]):
                    coll = True
                    break
            if coll:
                continue
            return entry, exit_t
        return None, None

    # FAST PATH (exact): every crane/collision GEOMETRY check above depends only on
    # the FIXED positions of new_blk and each placed block -- never on the entry
    # time.  Only *which* placed blocks fall inside the [entry, exit_t) window is
    # timing-dependent.  So precompute, ONCE per position, the obstruction/collision
    # booleans against each placed block (O(i) Shapely calls), then the entry loop
    # is pure interval arithmetic (no Shapely).  Byte-identical to the per-entry
    # path but turns O(i^2) Shapely/position into O(i) (profiled O(i^3)/block bottleneck).
    n = len(placed_in_bay)
    obs_new_entry = [False] * n   # placed[k] obstructs new_blk's ENTRY (descent)
    obs_new_exit = [False] * n    # placed[k] obstructs new_blk's EXIT (ascent)
    retro_entry = [False] * n     # new_blk obstructs placed[k]'s ENTRY
    retro_exit = [False] * n      # new_blk obstructs placed[k]'s EXIT
    collide = [False] * n         # new_blk collides spatially with placed[k]
    # OGC_PP_RASTER: skip the 5 Shapely calls for placed blocks whose world raster is
    # disjoint from new_blk's -- disjoint rasters => disjoint polygons at every height
    # => all 5 booleans provably False (no crane obstruction, no collision).  Exact.
    _pp_ras = _PP_RASTER
    _new_cells = _block_raster_cells(new_blk) if (_pp_ras and n) else None
    for k in range(n):
        b_other = placed_in_bay[k]
        if _pp_ras and not (_new_cells & _block_raster_cells(b_other)):
            if _PP_RASTER_VERIFY:
                _PP_RASTER_STAT["skips"] += 1
                if (check_entry(bay, [b_other], new_blk, fast=True)
                        or check_exit(bay, [b_other], new_blk, fast=True)
                        or check_entry(bay, [new_blk], b_other, fast=True)
                        or check_exit(bay, [new_blk], b_other, fast=True)
                        or check_collisions(bay, [new_blk, b_other])):
                    _PP_RASTER_STAT["violations"] += 1
                    if len(_PP_RASTER_STAT["examples"]) < 5:
                        _PP_RASTER_STAT["examples"].append(
                            (getattr(new_blk, "block_id", "?"),
                             getattr(b_other, "block_id", "?")))
            continue  # all 5 arrays stay False for k
        obs_new_entry[k] = bool(check_entry(bay, [b_other], new_blk, fast=True))
        obs_new_exit[k] = bool(check_exit(bay, [b_other], new_blk, fast=True))
        retro_entry[k] = bool(check_entry(bay, [new_blk], b_other, fast=True))
        retro_exit[k] = bool(check_exit(bay, [new_blk], b_other, fast=True))
        collide[k] = bool(check_collisions(bay, [new_blk, b_other]))
    sched = schedule_in_bay
    for entry_candidate in candidate_entries:
        entry = max(r_time, entry_candidate)
        exit_t = entry + proc
        ok = True
        for k in range(n):
            a_o, e_o = sched[k]
            # (1) new's ENTRY blocked by a block present at entry
            if obs_new_entry[k] and a_o <= entry < e_o:
                ok = False
                break
            # (2) new's EXIT blocked by a block present at exit -- with _CRANE_COEXIT
            # a co-exiting block (e_o == exit_t) is INCLUDED (matches official); else `<`.
            if obs_new_exit[k] and a_o < exit_t \
                    and (exit_t <= e_o if _CRANE_COEXIT else exit_t < e_o):
                ok = False
                break
            # (3) new retroactively obstructs a block whose entry/exit is in window
            if retro_entry[k] and entry <= a_o < exit_t:
                ok = False
                break
            if retro_exit[k] and entry < e_o \
                    and (e_o <= exit_t if _CRANE_COEXIT else e_o < exit_t):
                ok = False
                break
            # (4) spatial collision with a time-overlapping block
            if collide[k] and entry < e_o and a_o < exit_t:
                ok = False
                break
        if ok:
            return entry, exit_t
    return None, None


# Crane-safe decode (complete retroactive feasibility) is ON by default: it lets
# our good low-tardiness assignments survive the feasibility gate on congested
# instances instead of collapsing to the baseline floor.  Kill-switch via env.
_CRANE_SAFE = _env_on("OGC_CRANE_SAFE", True)

# Crane co-exit alignment: the official utils check_exit (Stage 5) treats blocks
# that EXIT at the same instant as BOTH present during each other's vertical sweep
# (co-exiting blocks obstruct one another).  Our decoder's EXIT-present-set used a
# strict `<` upper bound on exit_t, which DROPS a block with e_o == exit_t -- so the
# decoder accepted layouts the official checker rejects (e.g. prob_6 blocks 66 & 116
# both exit at t=32: official violation, decoder missed it).  When ON, the EXIT-side
# interval bounds use `<=` so a co-exiting block is INCLUDED, matching the final
# Stage-5 replay check.  Default ON: the decoder now builds candidates against the
# same event-ordering rule that ultimately accepts/rejects them.  Set
# OGC_CRANE_COEXIT=0 for the older strict-`<` experimental path.
_CRANE_COEXIT = _env_on("OGC_CRANE_COEXIT", True)

# Fast crane-safe slot finder: hoists the timing-independent geometry checks out of
# the candidate-entry loop (precompute per position) -- EXACT per-decode (O(i) vs
# O(i^2) Shapely/position).  BUT it ships OFF: a faster decode reaches the budget
# deadline later, so the timing-dependent budget-decode force-places FEWER tail
# blocks -- and for tardiness instances partial serialisation actually BEATS full
# crane-safe packing (s703: slow=859 vs fast=7524, because overlapping packing
# delays exits = more Z1).  So raw decode speed is counterproductive here and the
# intended decode-bound win (s204) did not materialise.  Kept behind OGC_FAST_CRANE
# for controlled experiments; default OFF preserves the validated budget-decode win.
_FAST_CRANE = _env_on("OGC_FAST_CRANE", False)

# Order-level early break in cum_level: once a bay hits its proven tardiness LB, no
# later block order can beat it, so stop re-decoding it (objective-safe; saves the
# wasted slow crane re-decodes).  DEFAULT ON; OGC_ORDER_BREAK=0 disables it so the
# change can be A/B'd across the full instance set.
_ORDER_BREAK = _env_on("OGC_ORDER_BREAK", True)

# Fast geometry pre-filter: utils.check_entry/check_exit/check_collisions test the
# moving block PAIRWISE against each present block (utils.py:685 / 781 -- a per-block
# loop, j>=k sweep, no joint all-blocks computation) plus, for check_entry, the bay
# boundary (new vs bay only).  So passing a SUBSET of `present` that includes every
# block whose AABB overlaps the moving block's AABB yields an IDENTICAL result:
# a block with no AABB overlap has no horizontal overlap at any layer, so it can
# neither collide nor obstruct the vertical sweep, and utils would skip it anyway
# (its own internal _bb_overlap pre-filter, utils.py:687/787, drops it).  We hoist
# that screen into OUR code so utils never even iterates those blocks in Python.
# CONSERVATIVE: we use INCLUSIVE bounds (>=/<=) -- strictly weaker than utils' strict
# `<` screen -- so our kept set is a SUPERSET of what utils keeps => provably result-
# identical, never drops a relevant block.  Placed-block AABBs are cached by id()
# (placed blocks are immutable once positioned).  Default OFF: when OGC_FAST_GEOM is
# unset the call paths are byte-identical to before (full `present` lists passed).
_FAST_GEOM = _env_on("OGC_FAST_GEOM", False)

# Re-decode fast geometry (Method 1, threaded): the post-decode levers (cum_level,
# cross-bay relocate) RE-decode a fixed assignment to LOWER tardiness and accept a
# result only if it strictly beats the bay's CURRENT tardiness (bt-guard).  Unlike
# the FRONT budget-decode -- where a faster decode reaches the force-place deadline
# having serialised FEWER tail blocks and so measures WORSE Z1 (s703: slow=859 vs
# fast=7524) -- a faster re-decode only buys MORE bt-guarded attempts per wall-
# second, so it is upside-only here.  When ON, the re-decode _decode_bay calls use
# the EXACT fast crane path (byte-identical result, O(i) vs O(i^2) Shapely/position)
# while the FRONT keeps the slow path the Z1 quality depends on.  Default OFF ->
# byte-identical to before; the objective-safe gate re-verifies regardless.
_REDECODE_FAST = _env_on("OGC_REDECODE_FAST", False)

# OGC_PP_RASTER: polygon-raster PREFILTER for the postprocess crane primitive
# (_find_slot_crane_safe, used by the cum_level / cross-bay / Front-B re-decodes).
# The fast-path precompute tests new_blk against each placed block with 5 Shapely
# crane/collision calls.  But if their WORLD rasters are DISJOINT (one cheap frozenset
# intersection), the polygons are disjoint at every height, so all 5 booleans are
# provably False -- no footprint overlap => no crane Stage-2/3 obstruction and no
# Stage-4 collision -- and we SKIP the Shapely calls.  EXACT, not conservative: a skip
# happens only when the result is provably all-False, so the returned (entry, exit) is
# byte-identical to the Shapely path; it never loses a slot, only wall-time.  Implies
# the fast crane path (itself byte-identical to the reference path) so the per-block
# precompute exists to short-circuit.  A faster re-decode is upside-only (more
# bt-guarded attempts per second; see _REDECODE_FAST).  Reuses the SAME superset
# rasteriser the OGC_FLOOR_RASTER floor proved sound over 5825 polygons.  Default OFF.
_PP_RASTER = _env_on("OGC_PP_RASTER", False)
# Soundness self-check: when ON, every raster-disjoint SKIP also runs the 5 Shapely
# calls and raises if any is True (raster claimed disjoint but Shapely sees a conflict).
# Used to validate OGC_PP_RASTER over a full run; never on by default (it re-adds the
# Shapely cost it is meant to remove).
_PP_RASTER_VERIFY = _env_on("OGC_PP_RASTER_VERIFY", False)
# Diagnostics for the verify run (read by a driver after algorithm() returns; robust
# to the broad try/except around the decode that a raised assertion could be swallowed
# by).  skips = raster-disjoint short-circuits taken; violations = skips Shapely would
# NOT have skipped (must be 0 for soundness).
_PP_RASTER_STAT = {"skips": 0, "violations": 0, "examples": []}

# CP-SAT zero-objective early-stop (Method 3): the cumulative re-timing solves
# MINIMISE sum(tardiness) >= 0, so a solution with objective 0 is GLOBALLY optimal --
# continuing the search cannot improve it.  A solution callback that StopSearch()es
# at objective <= 0 therefore only ever RETURNS EARLIER on a proven-optimal schedule;
# it can never return a worse one (provably objective-preserving).  Applied ONLY to
# the sum(tard) cumulative solves, never to the assignment/packing models whose 0 is
# not a meaningful floor.  Default ON; OGC_CPSAT_ZERO_STOP=0 restores plain Solve.
_CPSAT_ZERO_STOP = _env_on("OGC_CPSAT_ZERO_STOP", True)


def _zero_obj_stopper(cp_model):
    """Factory: a CP-SAT solution callback that stops the search as soon as a
    solution with objective <= 0 is found (the tardiness floor; provably optimal).
    cp_model is passed in because OR-Tools is imported lazily per call site."""
    class _Stop(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            cp_model.CpSolverSolutionCallback.__init__(self)

        def on_solution_callback(self):
            try:
                if self.ObjectiveValue() <= 1e-9:
                    self.StopSearch()
            except Exception:
                pass
    return _Stop()


# Fine-grained Z1 trace (OGC_Z1_TRACE, default OFF -> zero overhead): record
# (wall_seconds_since_algorithm_start, current best z1) at EVERY z1 change across
# the WHOLE run -- the search incumbent, each postprocess adoption, AND each per-bay
# improvement inside cum_level -- so a collector can resample at 1 s and SEE, within
# a long stage, exactly when z1 drops vs when it merely spins (the cum_level-174s
# question).  Emitted once as a [Z1_TRACE] stderr line at the single _ret chokepoint.
# OGC_Z1_LIVE_FILE: when set, each mark is ALSO appended (flushed) to this JSONL
# path so an external watcher can render the curve in REAL TIME mid-run.  Setting it
# implies tracing is on (the in-memory trace + [Z1_TRACE] emit still happen too).
_Z1_LIVE_PATH = (os.environ.get("OGC_Z1_LIVE_FILE", "").strip() or None)
_Z1_TRACE_ON = _env_on("OGC_Z1_TRACE", False) or bool(_Z1_LIVE_PATH)
_Z1_TRACE: list = []
_Z1_T0: list = [None]
_Z1_LIVE_FH: list = [None]
_Z1_BEST: list = [math.inf]   # running global-best z1 (monotone trace)

# Full objective trajectory (OGC_TRAJ): [t, obj, z1, z2, z3, stage] at each
# adopted improvement -> lets a plotter draw obj/z1/z2/z3 vs wall-time coloured
# by the operating sequence.  Reuses the z1-trace clock; zero overhead when off.
_TRAJ: list = []
_TRAJ_ON = _env_on("OGC_TRAJ", False)


def _traj_mark(obj, z1, z2, z3, stage) -> None:
    if not _TRAJ_ON or _Z1_T0[0] is None or obj is None:
        return
    try:
        t = round(time.monotonic() - _Z1_T0[0], 3)
        _TRAJ.append([t, float(obj),
                      None if z1 is None else float(z1),
                      None if z2 is None else float(z2),
                      None if z3 is None else float(z3), str(stage)])
    except Exception:
        pass


def _z1_trace_reset(t0: float) -> None:
    if _Z1_TRACE_ON:
        _Z1_TRACE.clear()
        _Z1_T0[0] = t0
        _Z1_BEST[0] = math.inf
        _TRAJ.clear()


def _z1_mark(z1, stage=None) -> None:
    """Record (elapsed, z1) at a z1 change.  No-op unless tracing; never raises.
    When OGC_Z1_LIVE_FILE is set, also stream the point to that file (flushed).
    stage overrides the auto-detected (stack-top) stage label when given."""
    if not _Z1_TRACE_ON or z1 is None or _Z1_T0[0] is None:
        return
    try:
        z = float(z1)
        if z >= _Z1_BEST[0] - 1e-9:   # not an improvement -> keep curve monotone
            return
        _Z1_BEST[0] = z
        t = round(time.monotonic() - _Z1_T0[0], 3)
        stg = stage if stage is not None else (
            _STAGE_STACK[-1] if _STAGE_STACK else "search")
        _Z1_TRACE.append([t, z, stg])
        if _Z1_LIVE_PATH:
            fh = _Z1_LIVE_FH[0]
            if fh is None:
                fh = open(_Z1_LIVE_PATH, "a", encoding="utf-8")
                _Z1_LIVE_FH[0] = fh
            fh.write('{"t": %s, "z1": %s, "stage": "%s"}\n' % (t, z, stg))
            fh.flush()
    except Exception:
        pass


def _z1_trace_emit() -> None:
    if not _Z1_TRACE_ON:
        return
    try:
        import sys as _sys, json as _json
        print("[Z1_TRACE]" + _json.dumps({"changes": _Z1_TRACE}),
              file=_sys.stderr, flush=True)
        if _TRAJ_ON:
            print("[TRAJ]" + _json.dumps({"points": _TRAJ}),
                  file=_sys.stderr, flush=True)
    except Exception:
        pass


def _aabb(blk):
    """AABB of a block, EXACTLY mirroring utils' geometry (Block.bounding_rect:
    min/max over all layer vertices in world coords -- the same vertices and (x,y)
    offset utils.bounding_rect uses).  Returns (min_x, min_y, max_x, max_y)."""
    return blk.bounding_rect()


def _aabbs_inclusive_overlap(a, b):
    """True if two AABBs overlap with INCLUSIVE bounds (edge/corner-touching KEPT).
    Conservative on purpose: weaker than utils' strict `<` _bb_overlap, so a block
    utils would test is always kept here -- correctness over speed."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _filter_present(present, new_bbox, bbox_cache):
    """Keep only present blocks whose cached AABB (inclusively) overlaps new_bbox.
    bbox_cache maps id(block)->AABB so each placed block's box is computed once."""
    out = []
    for b in present:
        bb = bbox_cache.get(id(b))
        if bb is None:
            bb = _aabb(b)
            bbox_cache[id(b)] = bb
        if _aabbs_inclusive_overlap(new_bbox, bb):
            out.append(b)
    return out


def _bbox_overlap_area(a, b) -> float:
    try:
        ix = min(a[2], b[2]) - max(a[0], b[0])
        iy = min(a[3], b[3]) - max(a[1], b[1])
        if ix <= 0.0 or iy <= 0.0:
            return 0.0
        return float(ix * iy)
    except Exception:
        return 0.0


def _crane_pair_potential(n_a: int, n_b: int) -> int:
    """Number of layer-pair opportunities under the j>=k sweep rule."""
    try:
        n_a = max(1, int(n_a))
        n_b = max(1, int(n_b))
        return sum(max(0, n_b - k) for k in range(n_a))
    except Exception:
        return 1


def _candidate_crane_pressure(new_blk: Block, placed: list,
                              schedule: list[tuple[int, int]] | None = None,
                              entry: int | float | None = None,
                              exit_t: int | float | None = None,
                              bbox_cache: dict | None = None) -> float:
    """Cheap proxy for how much this placement constrains vertical crane paths."""
    if not placed or not _CRANE_PRESSURE_ON:
        return 0.0
    try:
        nb = _aabb(new_blk)
        n_new = len(new_blk.layers_at_pos()) or 1
        score = 0.0
        for idx, other in enumerate(placed):
            if bbox_cache is None:
                ob = _aabb(other)
            else:
                ob = bbox_cache.get(id(other))
                if ob is None:
                    ob = _aabb(other)
                    bbox_cache[id(other)] = ob
            overlap = _bbox_overlap_area(nb, ob)
            if overlap <= 0.0:
                continue
            n_old = len(other.layers_at_pos()) or 1
            layer_pairs = (_crane_pair_potential(n_new, n_old)
                           + _crane_pair_potential(n_old, n_new))
            time_weight = 1.0
            if (schedule is not None and entry is not None and exit_t is not None
                    and idx < len(schedule)):
                a_o, e_o = schedule[idx]
                ov = min(float(exit_t), float(e_o)) - max(float(entry), float(a_o))
                if ov > 0.0:
                    time_weight += min(4.0, ov)
            score += overlap * layer_pairs * time_weight
        return score
    except Exception:
        return 0.0


def _candidate_crane_pressure_bbox(candidate_bb, n_layers: int, placed: list,
                                   bbox_cache: dict | None = None) -> float:
    """Pre-check pressure for capped candidate ordering before Block creation."""
    if not placed or not _CRANE_PRESSURE_ON:
        return 0.0
    try:
        score = 0.0
        n_new = max(1, int(n_layers))
        for other in placed:
            if bbox_cache is None:
                ob = _aabb(other)
            else:
                ob = bbox_cache.get(id(other))
                if ob is None:
                    ob = _aabb(other)
                    bbox_cache[id(other)] = ob
            overlap = _bbox_overlap_area(candidate_bb, ob)
            if overlap <= 0.0:
                continue
            n_old = len(other.layers_at_pos()) or 1
            score += overlap * (
                _crane_pair_potential(n_new, n_old)
                + _crane_pair_potential(n_old, n_new)
            )
        return score
    except Exception:
        return 0.0


# Budget-bounded decode: when a seed's full crane search would overrun the decode
# deadline (large/dense instances), decode it within budget and force-place the
# tail instead of SKIPPING it entirely (which collapses to the baseline floor).
# Pure upside -- it only ever turns a skipped seed into a feasible candidate the
# gate can still reject in favour of the floor.  Kill-switch via env.
_BUDGET_DECODE = _env_on("OGC_BUDGET_DECODE", True)

# OGC_DECODE_EARLY_EXIT (default OFF): stop scanning a block's candidate slots as
# soon as a "perfect-enough" one is found -- on time (tardiness 0) AND crane
# pressure <= OGC_DECODE_EARLY_EPS (default 0.0 = no vertical overlap with any
# placed block).  Such a slot can only be beaten on the tertiary pack-tightness
# keys (top-edge, entry), so the Z1/feasibility impact is negligible while the
# work saved on easy/early blocks (empty-ish bay) is large.  OFF -> byte-identical
# to the exhaustive scan.
_DECODE_EARLY_EXIT = _env_on("OGC_DECODE_EARLY_EXIT", False)
_DECODE_EARLY_EPS = _env_float("OGC_DECODE_EARLY_EPS", 0.0)

# OGC_BBOX_CACHE (default ON): memoize placed-block AABBs within one _decode_bay
# call so _candidate_crane_pressure(_bbox) stops recomputing other.bounding_rect()
# for every candidate slot (the placed blocks' boxes are immutable for the whole
# decode).  Byte-identical output -- pure speedup.  Kill-switch for A/B.
_BBOX_CACHE = _env_on("OGC_BBOX_CACHE", True)

# Read once at import instead of os.environ.get() per crane-pressure call (the hot
# path calls these tens of thousands of times per decode).  Byte-identical.
_CRANE_PRESSURE_ON = _env_on("OGC_CRANE_PRESSURE", True)

# OGC_FAST_POSITIONS (default OFF): replace the O(P^2) bottom-left-fill cartesian
# product (_candidate_positions) with a column-supported generator -- per candidate
# left-x, only the SUPPORTED y-levels (floor + tops of placed blocks overlapping
# that column) instead of every (right-edge x) x (top-edge y) combination.  Far
# fewer expensive crane checks on large bays.  Changes packing, so the Z1 effect is
# MEASURED and DEFAULT ON after validation: a huge win on large/truncation-prone
# instances (prob_20 @60s 52258->1864, -96%; prob_14 -65%) with no small-instance
# regression (prob_1/5/8 tie).  Kill-switch OGC_FAST_POSITIONS=0 restores the
# exhaustive O(P^2) generator.
_FAST_POSITIONS = _env_on("OGC_FAST_POSITIONS", True)
# OGC_FAST_POS_TOP (0 = keep all supported levels): when >0, keep only the floor
# plus the N HIGHEST (most crane-accessible) levels per column.  Lower N = fewer
# candidates = faster, but risks dropping a needed crane-access slot (-> Z1 up).
# Default 4 = the measured speed/Z1 sweet spot (3.55x decode, no force-place).
_FAST_POS_TOP = _env_int("OGC_FAST_POS_TOP", 4)
# (Removed after measurement: OGC_FAST_POS_ADAPT tied fast-positions to the
# adaptive cap signal -- it anti-correlated with truncation risk (worst-of-both).
# OGC_FAST_FALLBACK tried a past-deadline fast search before force-place -- it gave
# no measured Z1 gain on the catastrophic case (that Z1 comes from baseline-floor
# adoption, not _decode_bay force-place) and risked a wall overrun (60.5s/60s).)

# Protect the spread seeds (cpsat, balanced) from the flat O(n^2) decode-cost
# estimate that over-predicts a balanced block->bay split and needlessly trips
# the budget-decode tail force-place -- throwing away the clean-decode win on
# large dense instances (debate 2026-05-30; s204 894 vs the 10822 we returned).
# When ON, these two seeds get a clean decode bounded only by the real
# decode_deadline (a cheap spread finishes far before it; a pathological pile
# still self-bounds and can never overrun).  The tardy seed is deliberately
# excluded so its validated serialization win (s703) is preserved.  Default ON;
# OGC_PROTECT_SEED=0 restores the exact prior estimate-gated behaviour.
_PROTECT_SEED = _env_on("OGC_PROTECT_SEED", True)

# Due-aware force-place: lift the n<=120 guard on the postprocess tardy-block
# re-assignment branch so mid/large tardy instances can also try moving their
# worst-tardiness blocks toward tardiness-minimising bays.  Each candidate move
# is still gated by consider() (check_feasibility + strict-improvement-only), so
# this can only ever lower Z1 or do nothing -- never breaks crane-safety or the
# verified floor.  Work is bounded to the top-K tardiest blocks (K below) so a
# large n cannot blow the time budget.  Default OFF: when OGC_DUE_FORCE is unset
# the guard stays exactly `len(assign) <= 120` and the K cap is NOT applied to
# the n<=120 path, so small instances are byte-identical to before.
_DUE_FORCE = _env_on("OGC_DUE_FORCE", False)
_DUE_FORCE_K = _env_int("OGC_DUE_FORCE_K", 30)

# Candidate cap: per block, _decode_bay enumerates (orientations x
# _candidate_positions) placements and runs the EXPENSIVE _find_slot_crane_safe
# (O(i) Shapely calls/position via utils.check_entry/check_exit) on EVERY one --
# ~3400 crane-checks/block on prob_6's near-empty bays, ~292s for a clean decode.
# When >0, we cap the number of (position x orientation) candidates whose crane
# feasibility is actually TESTED to K per block.  Quality is preserved by testing
# in a CHEAP PROMISE ORDER first: sort candidates by a proxy of the decode's own
# selection key -- lowest world top-edge (cy + local_max_y), then lowest cy, then
# earliest-by-AABB-as-(cx) -- so the cap keeps the placements the unbounded decode
# would most likely have picked.  utils stays the feasibility AUTHORITY: we only
# reduce HOW MANY placements we hand it; the check itself and the COEXIT alignment
# are unchanged.  Default 0 = unlimited = current behaviour, byte-identical (the
# cap branch is never entered, the original two nested loops run verbatim).
_CAND_CAP = _env_int("OGC_CAND_CAP", 0)

# Adaptive cap floor: the candidate cap above is BLANKET -- it also throttles a
# bay holding only a handful of blocks, which decodes fast anyway, so capping it
# only under-searches its small bay and HURTS quality (full-solver: a fixed
# cap=80 lifted prob_20 Z1 45005->2179 but pushed prob_1 178->431).  When >0,
# _CAND_CAP applies ONLY to bays whose assigned block count >= _CAND_CAP_MIN;
# bays with FEWER blocks run UNLIMITED (the exact original nested loops).  The
# expensive crane search is the bottleneck only on the big near-empty bays where
# n is large, so this keeps the large-instance clean-decode win while leaving
# small bays at full search depth.  Default 0: the floor is inert -- _CAND_CAP
# (whatever it is) applies everywhere, byte-identical to the prior blanket cap.
_CAND_CAP_MIN = _env_int("OGC_CAND_CAP_MIN", 0)

# BUDGET-AWARE adaptive decode (default ON).  The static _CAND_CAP/_CAND_CAP_MIN
# proxy throttles by a fixed block-count threshold regardless of how much wall
# time is actually available -- so it either under-searches a small bay at an
# ample budget or fails to throttle a big bay at a tight one.  When ON, the cap
# is derived from the REAL time budget per bay: in _decode_assignment we know the
# shared decode deadline and how many bays remain, so we give each bay a fair
# share of the remaining budget, estimate its FULL (uncapped) decode cost via
# _bay_decode_secs, and -- only if the full decode would NOT fit its share --
# scale a candidate cap down by the budget shortfall so the bay is estimated to
# finish cleanly (every block gets a real crane-searched placement) instead of
# running out of time mid-bay and force-placing its tail at far-future times
# (the Z1 explosion).  A comfortably-fitting bay gets NO cap (cap=0 -> full
# search -> the ample-budget optimum is untouched).  The manual OGC_CAND_CAP /
# OGC_CAND_CAP_MIN overrides still take precedence for experiments (see
# _effective_cap_for_bay).  OGC_ADAPT_DECODE=0 disables this entirely -> the cap
# is whatever the static knobs say (default: none) -> byte-identical to prior.
_ADAPT_DECODE = _env_on("OGC_ADAPT_DECODE", True)
# Floor on the adaptive cap: even under severe budget pressure we never test
# fewer than this many candidates per block, so a capped placement is still a
# real (not degenerate) crane search.  Calibrated so a capped bay still places
# all blocks cleanly (prob_20: cap~80 cleared 300 blocks @60s).
_ADAPT_CAP_FLOOR = _env_int("OGC_ADAPT_CAP_FLOOR", 24)

# Large many-bay cap floor: the proportional budget model can over-throttle
# prob_20-shaped cases (300 blocks / 5 bays).  There the useful seed is already
# spread across bays, and a too-small cap throws away placement quality while
# still finishing with slack.  A/B on prob_20@60s: dynamic cap ~= 60.0M obj,
# static cap=120,min=45 ~= 41.3M, while the same static cap regressed prob_1 and
# prob_6.  Therefore this floor is applied only by _decode_assignment when the
# whole instance is large and has many bays; ordinary small/medium bays keep the
# normal adaptive cap.
_ADAPT_LARGE_CAP_FLOOR = _env_int("OGC_ADAPT_LARGE_CAP_FLOOR", 120)
_ADAPT_LARGE_CAP_MIN_COUNT = _env_int("OGC_ADAPT_LARGE_CAP_MIN_COUNT", 45)


def _adapt_cap_for_bay(count: int, bay_budget: float, alt_threshold: int) -> int:
    """Budget-aware candidate cap for ONE bay of `count` blocks given the wall
    time `bay_budget` (s) available to decode it.

    Returns 0 (== UNLIMITED, full search) when the full uncapped decode is
    estimated to fit comfortably, else a positive K so the capped decode is
    estimated to finish within budget.  Model: full decode cost grows ~count^2
    (it tests ~count candidates/block), a K-capped decode ~count*K, so to fit a
    budget that is a fraction f = bay_budget/full_cost of the full cost we want
    K ~= f * count.  K is clamped to [_ADAPT_CAP_FLOOR, count] (a cap >= the
    natural candidate count is a no-op, so we never inflate work)."""
    if count <= 1 or bay_budget <= 0.0:
        return 0
    full = _bay_decode_secs(count, alt_threshold)
    if full <= 0.0 or full <= bay_budget:
        return 0  # fits comfortably -> full search, no cap
    # shortfall fraction in (0, 1): how much of the full budget we actually have.
    frac = bay_budget / full
    k = int(frac * count)
    if k >= count:
        return 0
    return max(_ADAPT_CAP_FLOOR, k)


def _effective_cap_for_bay(count: int, bay_budget: float | None,
                           alt_threshold: int,
                           budget_cap_floor: int = 0) -> int:
    """Resolve the candidate cap for a bay.  Manual OGC_CAND_CAP (gated by
    OGC_CAND_CAP_MIN) WINS when set, for experiments.  Otherwise, when adaptive
    is ON and a per-bay time budget is known, use the budget-derived cap.  Else
    0 (unlimited) -- the exact prior default."""
    if _CAND_CAP > 0:
        return _CAND_CAP if count >= _CAND_CAP_MIN else 0
    if _ADAPT_DECODE and bay_budget is not None:
        cap = _adapt_cap_for_bay(count, bay_budget, alt_threshold)
        if (cap > 0 and budget_cap_floor > 0
                and count >= _ADAPT_LARGE_CAP_MIN_COUNT):
            cap = max(cap, budget_cap_floor)
        return cap
    return 0


def _candidate_positions_fast(bay_w, bay_h, placed, blk_bb):
    """Column-supported candidate positions (OGC_FAST_POSITIONS).

    The exhaustive _candidate_positions returns the full xs x ys cartesian product
    (O(P^2)), pairing every placed right-edge x with every placed top-edge y --
    including "floating" (x, y) where the chosen y is the top of a block that does
    NOT sit under column x.  Here, for each candidate left-x, only the y-levels
    that are actually SUPPORTED in that column are kept: the floor plus the top of
    each placed block whose x-range overlaps the new block's footprint.  This keeps
    the crane-accessible high positions (top of a stack) while dropping the
    floating cross-column combinations, shrinking the candidate count (typically
    2-5x on dense bays) with AABB-only math (no Shapely)."""
    lx0, ly0, lx1, ly1 = blk_bb
    base_x = max(0, math.ceil(-lx0))
    base_y = max(0, math.ceil(-ly0))
    pbbs = [b.bounding_rect() for b in placed]
    xs = {base_x}
    for bb in pbbs:
        x = math.ceil(bb[2] - lx0)
        if 0 <= x and x + lx1 <= bay_w + 1e-6:
            xs.add(x)
    out = []
    for x in sorted(xs):
        if x + lx1 > bay_w + 1e-6:
            continue
        fxlo, fxhi = x + lx0, x + lx1
        ys = {base_y}
        for bb in pbbs:
            if bb[0] < fxhi - 1e-9 and fxlo < bb[2] - 1e-9:  # overlaps this column
                y = math.ceil(bb[3] - ly0)
                if y >= base_y:
                    ys.add(y)
        ys_sorted = sorted(ys)
        if _FAST_POS_TOP > 0 and len(ys_sorted) > _FAST_POS_TOP + 1:
            # floor (most-packed) + the N highest (most crane-accessible) levels
            ys_sorted = [ys_sorted[0]] + ys_sorted[-_FAST_POS_TOP:]
        for y in ys_sorted:
            if y + ly1 <= bay_h + 1e-6:
                out.append((int(x), int(y)))
    return out


def _decode_bay(bay: Bay, bay_idx: int, order: list[int],
                blocks_data: list, deadline: float | None = None,
                cand_cap: int = 0,
                release_override: dict | None = None,
                exhaustive_pos: bool = False,
                fast_geom=None) -> tuple[dict | None, set]:
    """Decode one ordered list of blocks into crane-feasible placements within a
    single bay.  Greedy per block: minimise (tardiness, top-edge, entry).  Falls
    back to an empty-window placement when no overlapping slot is feasible.

    deadline (monotonic seconds): once passed, the remaining blocks skip the
    O(positions x orientations) crane search and are force-placed into empty
    windows (serialised, guaranteed feasible, paying tardiness).  This lets a
    large/dense seed that the cost guard would otherwise SKIP entirely still
    yield a feasible candidate within budget instead of collapsing to baseline.
    A force-placed block is recorded in forced_ids, so the 2-tuple contract is
    unchanged.  deadline=None reproduces the exact original behaviour.

    Returns (result, forced_ids) where result is {block_id: assignment} (or None
    if a block cannot fit the bay at all) and forced_ids is the set of block ids
    that had to be FORCE-PLACED into an empty time window because no overlapping
    slot was feasible.  forced_ids is the Milestone-M4 "certificate": a non-empty
    set means this bay is over-subscribed for this block-set (the forced blocks
    pay tardiness), which the assignment-level search uses to steer re-assignment
    (eject the forced blocks) instead of blindly keeping the toxic packing."""
    placed: list[Block] = []
    schedule: list[tuple[int, int]] = []
    result: dict[int, dict] = {}
    forced_ids: set = set()
    _pcache = {} if _BBOX_CACHE else None  # placed-block AABB memo (this decode)

    # Candidate cap for this bay.  When the caller supplies cand_cap>0 (the
    # budget-aware adaptive path, or a manual override resolved upstream), use it
    # verbatim.  Otherwise fall back to the static OGC_CAND_CAP/_MIN proxy so the
    # legacy manual-knob behaviour (and OGC_ADAPT_DECODE=0) is unchanged: the cap
    # applies iff this bay holds at least _CAND_CAP_MIN blocks (>=0 always true).
    if cand_cap > 0:
        effective_cap = cand_cap
    else:
        effective_cap = _CAND_CAP if len(order) >= _CAND_CAP_MIN else 0

    # Position generator: OGC_FAST_POSITIONS uses the fast O(P) column-supported
    # generator (big decode speedup, esp. on large/truncation-prone bays); else the
    # exhaustive O(P^2) bottom-left-fill.
    # exhaustive_pos forces the O(P^2) exhaustive generator regardless of the
    # global _FAST_POSITIONS (used by the cum_level lever's bounded re-decode to
    # pack TIGHTER -- the search keeps the fast generator, so this never slows the
    # main search the way the global OGC_FAST_POSITIONS=0 did).
    if exhaustive_pos:
        _pos_fn = _candidate_positions
    else:
        _pos_fn = _candidate_positions_fast if _FAST_POSITIONS else _candidate_positions

    for bi in order:
        blk = blocks_data[bi]
        # release_override (cumulative-leveled re-decode): defer a non-urgent block
        # to its demand-flattened target slot so urgent blocks get the floor early.
        # max() keeps it >= the real release (never enters before it is available).
        r_time = (max(blk["release_time"], release_override[bi])
                  if release_override is not None and bi in release_override
                  else blk["release_time"])
        proc = blk["processing_time"]
        due = blk["due_date"]

        best = None
        best_key = None
        budget_out = deadline is not None and time.monotonic() > deadline

        if effective_cap > 0 and not budget_out:
            # Capped path: collect all (orientation, position) candidates with a
            # CHEAP promise score (no Shapely), sort, then run the expensive
            # _find_slot_crane_safe on at most K of them, keeping the best feasible
            # by the SAME selection rule as the unbounded path.  promise = (world
            # top-edge cy+bb[3], cy, cx) mirrors the decode key's secondary terms
            # (lower top -> tighter pack; the tardiness term needs the entry time
            # we don't have pre-check, so top-edge is the cheap proxy).
            cands = []
            for oi in range(len(blk["shape"])):
                bb = _block_bbox(blk, oi)
                if (bb[2] - bb[0]) > bay.width + 1e-6 or (bb[3] - bb[1]) > bay.height + 1e-6:
                    continue
                top_off = bb[3]
                n_layers = len(blk["shape"][oi].get("layers", []) or []) or 1
                for (cx, cy) in _pos_fn(bay.width, bay.height, placed, bb):
                    cbb = (cx + bb[0], cy + bb[1], cx + bb[2], cy + bb[3])
                    pressure = _candidate_crane_pressure_bbox(cbb, n_layers, placed, _pcache)
                    cands.append((pressure, cy + top_off, cy, cx, oi, bb))
            cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
            tested = 0
            for _pressure0, _promise, cy, cx, oi, bb in cands:
                if tested >= effective_cap:
                    break
                nb = Block(block_id=bi, block_data=blk, x=cx, y=cy, orient_idx=oi)
                if not bay.contains_block(nb):
                    continue
                tested += 1
                if _CRANE_SAFE:
                    entry, exit_t = _find_slot_crane_safe(
                        nb, bay, placed, schedule, r_time, proc, fast=fast_geom)
                else:
                    entry, exit_t = _find_earliest_slot(
                        nb, bay, placed, schedule, r_time, proc)
                if entry is None:
                    continue
                pressure = _candidate_crane_pressure(nb, placed, schedule,
                                                     entry, exit_t, bbox_cache=_pcache)
                key = (max(0.0, exit_t - due), pressure, cy + bb[3], entry)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (cx, cy, oi, entry, exit_t)
                if (_DECODE_EARLY_EXIT and best_key is not None
                        and best_key[0] <= 0.0 and best_key[1] <= _DECODE_EARLY_EPS):
                    break  # perfect-enough: on time + low crane pressure
        else:
            _early_stop = False
            for oi in (() if budget_out else range(len(blk["shape"]))):
                bb = _block_bbox(blk, oi)
                if (bb[2] - bb[0]) > bay.width + 1e-6 or (bb[3] - bb[1]) > bay.height + 1e-6:
                    continue
                for (cx, cy) in _pos_fn(bay.width, bay.height, placed, bb):
                    nb = Block(block_id=bi, block_data=blk, x=cx, y=cy, orient_idx=oi)
                    if not bay.contains_block(nb):
                        continue
                    if _CRANE_SAFE:
                        entry, exit_t = _find_slot_crane_safe(
                            nb, bay, placed, schedule, r_time, proc, fast=fast_geom)
                    else:
                        entry, exit_t = _find_earliest_slot(
                            nb, bay, placed, schedule, r_time, proc)
                    if entry is None:
                        continue
                    pressure = _candidate_crane_pressure(nb, placed, schedule,
                                                         entry, exit_t, bbox_cache=_pcache)
                    key = (max(0.0, exit_t - due), pressure, cy + bb[3], entry)
                    if best_key is None or key < best_key:
                        best_key = key
                        best = (cx, cy, oi, entry, exit_t)
                    if (_DECODE_EARLY_EXIT and best_key is not None
                            and best_key[0] <= 0.0 and best_key[1] <= _DECODE_EARLY_EPS):
                        _early_stop = True
                        break
                if _early_stop:
                    break

        if best is None:
            forced = _force_in_bay(bi, blocks_data, bay, bay_idx, schedule)
            if forced is None:
                return None, forced_ids
            forced_ids.add(bi)  # M4 certificate: this block was force-placed
            cx, cy, oi = forced["x"], forced["y"], forced["orient_idx"]
            entry, exit_t = forced["entry_time"], forced["exit_time"]
        else:
            cx, cy, oi, entry, exit_t = best

        placed.append(Block(block_id=bi, block_data=blk, x=cx, y=cy, orient_idx=oi))
        schedule.append((int(entry), int(exit_t)))
        result[bi] = {"block_id": bi, "bay_id": bay_idx,
                      "x": int(round(cx)), "y": int(round(cy)), "orient_idx": oi,
                      "entry_time": int(round(entry)), "exit_time": int(round(exit_t))}
    return result, forced_ids


def _orderings(ids: list[int], blocks_data: list, allow_alt: bool) -> list[list[int]]:
    """Candidate placement orders for a bay.  EDD is the proven primary; an
    alternative (release-then-due) is added when the bay is small enough that
    trying both is cheap.  ATCR (Apparent Tardiness Cost w/ Release) is a third
    candidate (OGC_ATCR_SEED, default ON): a dispatch rule that beats EDD on
    weighted tardiness with release dates.  When OGC_ATCR_SEED is OFF this
    function returns exactly the legacy [edd] / [edd, rel] list (bit-identical)."""
    crane_order = _env_on("OGC_CRANE_ORDER", True)

    def _edd_key(b):
        blk = blocks_data[b]
        if crane_order:
            # Release-date tardiness is driven by tight slack, not due date
            # alone.  Among similarly tight jobs, place low crane-complexity
            # blocks first so tall overhang-heavy blocks do not become early
            # vertical blockers.
            slack = blk["due_date"] - blk["release_time"] - blk["processing_time"]
            return (slack,
                    blk["due_date"],
                    _block_crane_complexity(blk),
                    blk["release_time"],
                    blk["processing_time"])
        return (blk["due_date"], blk["processing_time"])

    edd = sorted(ids, key=_edd_key)
    if not allow_alt or len(ids) <= 1:
        return [edd]
    rel = sorted(ids, key=lambda b: (blocks_data[b]["release_time"],
                                     blocks_data[b]["due_date"],
                                     _block_crane_complexity(blocks_data[b])
                                     if crane_order else 0))
    out = [edd, rel] if rel != edd else [edd]
    if _env_on("OGC_ATCR_SEED", False):
        # ATCR static priority: descending priority_i, ties broken by EDD key
        # (ascending due, then proc) -- deterministic, no RNG.
        p_bar = sum(blocks_data[b]["processing_time"] for b in ids) / len(ids)
        if p_bar > 0.0:
            K = _env_float("OGC_ATCR_K", 2.0)
            def _atcr_pri(b):
                blk = blocks_data[b]
                proc = blk["processing_time"]
                slack = blk["due_date"] - proc - blk["release_time"]
                return ((1.0 / max(proc, 1e-9))
                        * math.exp(-max(0.0, slack) / (K * p_bar)))
            atcr = sorted(ids, key=lambda b: (-_atcr_pri(b),
                                              blocks_data[b]["due_date"],
                                              _block_crane_complexity(blocks_data[b])
                                              if crane_order else 0,
                                              blocks_data[b]["processing_time"]))
            if atcr not in out:
                out.append(atcr)
    return out


def _bay_tardiness(result: dict, blocks_data: list) -> float:
    return sum(max(0.0, a["exit_time"] - blocks_data[a["block_id"]]["due_date"])
               for a in result.values())


# ---------------------------------------------------------------------------
# Cached per-bay decode (keyed by bay + frozenset of block ids)
# ---------------------------------------------------------------------------

class _Decoder:
    def __init__(self, bays, blocks_data, alt_threshold: int):
        self.bays = bays
        self.blocks_data = blocks_data
        self.alt_threshold = alt_threshold
        self.cache: dict[tuple, tuple] = {}

    def _decode_cached(self, bay_idx: int, ids, deadline: float | None = None,
                       bay_budget: float | None = None,
                       budget_cap_floor: int = 0):
        """Compute/cache the full 3-tuple (result, tardiness, forced_ids) for a
        bay+block-set.  forced_ids is the M4 certificate (blocks force-placed).

        deadline (monotonic s): budget-bounded decode -- EPHEMERAL (NOT cached,
        EDD-only) because a truncated decode depends on wall-clock timing and
        must not pollute the deterministic cache.  deadline=None == original.

        bay_budget (s): wall time available to decode THIS bay.  When given (and
        adaptive is ON / a manual cap is set), a budget-aware candidate cap is
        derived per bay (_effective_cap_for_bay) and passed to _decode_bay so a
        bay that cannot afford a full crane search is throttled enough to place
        ALL blocks cleanly instead of force-placing its tail.  A capped decode is
        also EPHEMERAL (budget-dependent), so it is never cached and runs EDD-
        only, mirroring the deadline path.  cap==0 (the fit-comfortably / off
        case) leaves the decode and caching exactly as before -- byte-identical."""
        cap = _effective_cap_for_bay(len(ids), bay_budget, self.alt_threshold,
                                     budget_cap_floor=budget_cap_floor)
        cacheable = (deadline is None) and (cap == 0)
        key = (bay_idx, frozenset(ids))
        if cacheable:
            hit = self.cache.get(key)
            if hit is not None:
                return hit
        bay = self.bays[bay_idx]
        ids_list = list(ids)
        best_res = None
        best_tard = None
        best_forced: frozenset = frozenset()
        allow_alt = cacheable and (len(ids_list) <= self.alt_threshold)
        for order in _orderings(ids_list, self.blocks_data, allow_alt):
            res, forced = _decode_bay(bay, bay_idx, order, self.blocks_data,
                                      deadline=deadline, cand_cap=cap)
            if res is None:
                if cacheable:
                    self.cache[key] = (None, math.inf, frozenset())
                return (None, math.inf, frozenset())
            t = _bay_tardiness(res, self.blocks_data)
            if best_tard is None or t < best_tard:
                best_tard = t
                best_res = res
                best_forced = frozenset(forced)
        out = (best_res, best_tard, best_forced)
        if cacheable:
            self.cache[key] = out
        return out

    def decode(self, bay_idx: int, ids, deadline: float | None = None,
               bay_budget: float | None = None,
               budget_cap_floor: int = 0):
        # FIREWALL: existing callers keep the (result, tardiness) 2-tuple contract
        # unchanged, so the M4 cache-shape change is invisible to them.
        res, tard, _forced = self._decode_cached(bay_idx, ids, deadline=deadline,
                                                 bay_budget=bay_budget,
                                                 budget_cap_floor=budget_cap_floor)
        return res, tard

    def decode_full(self, bay_idx: int, ids, deadline: float | None = None,
                    bay_budget: float | None = None,
                    budget_cap_floor: int = 0):
        """(result, tardiness, forced_ids) -- used by the M4 cut logic only."""
        return self._decode_cached(bay_idx, ids, deadline=deadline,
                                   bay_budget=bay_budget,
                                   budget_cap_floor=budget_cap_floor)


# ---------------------------------------------------------------------------
# Exact objective (mirrors utils.check_feasibility, lines 1388-1421)
# ---------------------------------------------------------------------------

def _objective(prob_info: dict, assignments_list: list, bay_u: list[float]):
    w = prob_info.get("weights", {})
    w1, w2, w3 = w.get("w1", 1.0), w.get("w2", 1.0), w.get("w3", 1.0)
    blocks = prob_info["blocks"]
    n_bays = len(bay_u)

    obj1 = 0.0
    obj3 = 0.0
    loads = [0.0] * n_bays
    for a in assignments_list:
        blk = blocks[a["block_id"]]
        bj = a["bay_id"]
        obj1 += max(0.0, a["exit_time"] - blk["due_date"])
        loads[bj] += blk["workload"]
        obj3 += max(blk["bay_preferences"]) - blk["bay_preferences"][bj]

    if n_bays >= 2:
        wl = [bay_u[j] * loads[j] for j in range(n_bays)]
        obj2 = max(wl) - min(wl)
    else:
        obj2 = 0.0
    return w1 * obj1 + w2 * obj2 + w3 * obj3, obj1, obj2, obj3


def _quick_objective(prob_info: dict, sol: dict, bay_u: list[float]) -> float:
    """Objective of a solution dict WITHOUT running check_feasibility.

    Mirrors _objective exactly, so for a FEASIBLE solution this equals the true
    objective; it is used only to *rank* candidates cheaply before paying for
    the O(n^2) geometry check.  An infeasible solution may get an optimistic
    value here -- fine, the authoritative check_feasibility gate still rejects
    it.  Returns +inf if the solution cannot be parsed."""
    try:
        blocks = prob_info["blocks"]
        n_bays = len(bay_u)
        w = prob_info.get("weights", {})
        w1, w2, w3 = w.get("w1", 1.0), w.get("w2", 1.0), w.get("w3", 1.0)
        entry_bay: dict[int, int] = {}
        exit_t: dict[int, int] = {}
        for t_str, ops in sol.get("operations", {}).items():
            t = int(t_str)
            for op in ops:
                bid = op["block_id"]
                if op.get("type") == "ENTRY":
                    entry_bay[bid] = op["bay_id"]
                else:
                    exit_t[bid] = t
        if not entry_bay:
            return math.inf
        obj1 = 0.0
        obj3 = 0.0
        loads = [0.0] * n_bays
        for bid, j in entry_bay.items():
            blk = blocks[bid]
            et = exit_t.get(bid, blk["due_date"])
            obj1 += max(0.0, et - blk["due_date"])
            loads[j] += blk["workload"]
            obj3 += max(blk["bay_preferences"]) - blk["bay_preferences"][j]
        if n_bays >= 2:
            wl = [bay_u[j] * loads[j] for j in range(n_bays)]
            obj2 = max(wl) - min(wl)
        else:
            obj2 = 0.0
        return w1 * obj1 + w2 * obj2 + w3 * obj3
    except Exception:
        return math.inf


def _balanced_seed(prob_info: dict, feasible_bays: list, bay_u: list[float]) -> list[int]:
    """Greedy Z2-balancing assignment: place each block (heaviest first) into the
    feasible bay whose weighted load (u_j * load_j) would stay smallest.  A cheap,
    regime-agnostic seed giving the search a low-imbalance starting point."""
    blocks = prob_info["blocks"]
    n_blocks = len(blocks)
    n_bays = len(bay_u)
    loads = [0.0] * n_bays
    assign = [0] * n_blocks
    order = sorted(range(n_blocks), key=lambda b: -blocks[b]["workload"])
    for b in order:
        fb = feasible_bays[b] or list(range(n_bays))
        j = min(fb, key=lambda k: bay_u[k] * (loads[k] + blocks[b]["workload"]))
        assign[b] = j
        loads[j] += blocks[b]["workload"]
    return assign


def _tardiness_seed(prob_info: dict, feasible_bays: list, bays: list) -> list[int]:
    """Z1-aware assignment seed: spread temporally-conflicting blocks across bays.

    The per-bay decoder serialises blocks that cannot co-exist spatially, so
    piling blocks with overlapping [release, due] windows into one bay forces
    late exits (tardiness).  The bay assignment is the dominant Z1 lever, yet the
    pref / balanced / CP-SAT seeds are all Z1-blind (CP-SAT's objective has no
    tardiness term).  This greedy assigns blocks earliest-due-first to the
    feasible bay that would be LEAST spatially congested during the block's
    window -- footprint area of already-assigned blocks whose window overlaps,
    plus this block, normalised by bay area.  On an instance with no temporal
    contention every bay yields zero tardiness, so this seed merely becomes one
    more Z2/Z3 candidate the gate discards: it can never make a result worse (the
    verified floor still guards), it only adds a low-Z1 start where Z1 exists."""
    blocks = prob_info["blocks"]
    n_blocks = len(blocks)
    n_bays = len(bays)
    if n_bays < 2:
        return [0] * n_blocks
    info = []
    for b in range(n_blocks):
        blk = blocks[b]
        crane_load = max(1.0, _block_crane_complexity(blk)[0])
        info.append((blk["release_time"], blk["due_date"], crane_load))
    bay_area = [max(1.0, bays[j].width * bays[j].height) for j in range(n_bays)]
    assigned: list[list] = [[] for _ in range(n_bays)]  # (release, due, area)
    assign = [0] * n_blocks
    area_exp = max(0.0, min(1.0, _env_float("OGC_CRANE_SEED_AREA_EXP", 0.5)))
    order = sorted(range(n_blocks),
                   key=lambda b: (info[b][1],
                                  _block_crane_complexity(blocks[b]),
                                  blocks[b]["processing_time"]))
    for b in order:
        r_b, d_b, a_b = info[b]
        fb = feasible_bays[b] or list(range(n_bays))
        best_j, best_score = fb[0], None
        for j in fb:
            load = a_b
            for (r_a, d_a, a_a) in assigned[j]:
                if min(d_a, d_b) > max(r_a, r_b):  # windows overlap in time
                    load += a_a
            score = load / (bay_area[j] ** area_exp)
            if best_score is None or score < best_score:
                best_score = score
                best_j = j
        assign[b] = best_j
        assigned[best_j].append((r_b, d_b, a_b))
    return assign


def _decode_cost_est(assign: list[int], n_bays: int, alt_threshold: int) -> float:
    """Rough wall-clock estimate (seconds) to decode a full assignment.

    Per-bay decode is dominated by O(n_j^2) Shapely slot/collision checks; the
    0.0025 coefficient is calibrated against the baseline's Phase-1 placement
    (~36s to pile 120 blocks into one bay).  Bays at/under the alt-ordering
    threshold are decoded twice (EDD + release order).  Used to *skip* a seed
    that cannot finish before the decode deadline instead of overrunning the
    wall-clock on a single seed (the previous timeout cause)."""
    counts = [0] * n_bays
    for j in assign:
        if 0 <= j < n_bays:
            counts[j] += 1
    cost = 0.0
    # alt-ordering bays are decoded once per candidate ordering; ATCR (when ON)
    # adds a 3rd ordering -> 3.0, else legacy 2.0 (EDD + release). Keeps the time
    # guard from under-estimating an admitted seed's unbounded decode.
    n_ord = 3.0 if _env_on("OGC_ATCR_SEED", False) else 2.0
    for n in counts:
        if n <= 0:
            continue
        factor = n_ord if n <= alt_threshold else 1.0
        cost += 0.0025 * n * n * factor
    return cost * _DECODE_SAFETY


def _bay_decode_secs(count: int, alt_threshold: int) -> float:
    """Worst-case (cache-miss) decode estimate for a single bay of `count`
    blocks.  Same calibration as _decode_cost_est; used inside the ALNS to skip
    any move whose touched-bay re-decode would overrun the deadline."""
    if count <= 0:
        return 0.0
    # match _decode_cost_est: 3 orderings when ATCR ON, else 2 (EDD + release).
    n_ord = 3.0 if _env_on("OGC_ATCR_SEED", False) else 2.0
    factor = n_ord if count <= alt_threshold else 1.0
    return 0.0025 * count * count * factor * _DECODE_SAFETY


# ---------------------------------------------------------------------------
# CP-SAT seed (optional): balance weighted load (Z2) + minimise preference (Z3)
# ---------------------------------------------------------------------------

def _cpsat_assignment(prob_info, bays, feasible_bays, bay_u, time_budget, diag=None,
                      hint=None):
    # diag: optional out-dict. When provided (only armed under OGC_TRACE), it is
    # filled with the solver's status/objective/bound/gap so we can tell an
    # *optimality-proven* assignment (gap==0 -> assignment-level search has
    # nothing to improve) from a *time-limited feasible* one (gap>0 -> headroom
    # the assignment-level search cannot reach). Never affects the return value
    # or solver behavior; pure observation.
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    try:
        blocks = prob_info["blocks"]
        n_blocks = len(blocks)
        n_bays = len(bays)
        if n_bays < 2 or n_blocks == 0:
            return None

        w = prob_info.get("weights", {})
        w2 = w.get("w2", 1.0)
        w3 = w.get("w3", 1.0)

        m = cp_model.CpModel()
        x = {}
        for b in range(n_blocks):
            fb = feasible_bays[b] or list(range(n_bays))
            for j in fb:
                x[b, j] = m.NewBoolVar(f"x_{b}_{j}")
            m.Add(sum(x[b, j] for j in fb) == 1)

        # Integer-scaled weighted load per bay:  U[j] (scaled u_j) * workload.
        U = [int(round(bay_u[j] * 1000)) for j in range(n_bays)]
        wsum = sum(int(round(blocks[b]["workload"])) for b in range(n_blocks))
        wl = []
        for j in range(n_bays):
            terms = []
            for b in range(n_blocks):
                if (b, j) in x:
                    terms.append(int(round(blocks[b]["workload"])) * U[j] * x[b, j])
            v = m.NewIntVar(0, (wsum + 1) * (max(U) + 1), f"wl_{j}")
            m.Add(v == sum(terms))
            wl.append(v)
        hi = m.NewIntVar(0, (wsum + 1) * (max(U) + 1), "hi")
        lo = m.NewIntVar(0, (wsum + 1) * (max(U) + 1), "lo")
        m.AddMaxEquality(hi, wl)
        m.AddMinEquality(lo, wl)
        z2 = m.NewIntVar(0, (wsum + 1) * (max(U) + 1), "z2")
        m.Add(z2 == hi - lo)

        pref_terms = []
        for b in range(n_blocks):
            s_max = max(blocks[b]["bay_preferences"])
            for j in feasible_bays[b] or list(range(n_bays)):
                pen = s_max - blocks[b]["bay_preferences"][j]
                if pen:
                    pref_terms.append(pen * x[b, j])

        c2 = max(1, int(round(w2)))
        c3 = max(1, int(round(w3)))
        m.Minimize(c2 * z2 + c3 * 1000 * sum(pref_terms))

        # Warm-start: feed a feasible assignment (e.g. the balanced seed) as a
        # hint so CP-SAT has a good incumbent immediately -> faster bound pruning
        # on the harder (w2-dominant, large) instances.  A bad/partial hint is
        # silently ignored by OR-Tools, so this is identical to a cold start on
        # failure -- pure upside, no formulation change.
        if hint is not None:
            try:
                for b in range(n_blocks):
                    j = hint[b] if b < len(hint) else -1
                    if (b, j) in x:
                        m.AddHint(x[b, j], 1)
            except Exception:
                pass

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, float(time_budget))
        solver.parameters.num_search_workers = 4
        status = solver.Solve(m)
        if diag is not None:
            try:
                diag["cp_status"] = solver.StatusName(status)
                diag["obj"] = solver.ObjectiveValue()
                diag["bound"] = solver.BestObjectiveBound()
                _den = max(1.0, abs(diag["obj"]))
                diag["gap"] = round((diag["obj"] - diag["bound"]) / _den, 6)
                diag["walltime"] = round(solver.WallTime(), 3)
            except Exception:
                pass
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        assign = [-1] * n_blocks
        for b in range(n_blocks):
            for j in feasible_bays[b] or list(range(n_bays)):
                if (b, j) in x and solver.Value(x[b, j]) == 1:
                    assign[b] = j
                    break
        if any(a < 0 for a in assign):
            return None
        return assign
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Assignment evaluation + local search
# ---------------------------------------------------------------------------

def _decode_assignment(decoder: _Decoder, assign: list[int], n_bays: int,
                       deadline: float | None = None):
    """Decode a full block->bay assignment. Returns (per_bay_results, total_tard)
    or (None, inf) if any bay is infeasible.  deadline (monotonic s) budget-bounds
    the whole decode: bays decode in turn against the same deadline, so later bays
    progressively force-place their tail -- the assignment always finishes by
    ~deadline instead of being skipped (the decode-bound large-instance lever)."""
    bay_ids: list[list[int]] = [[] for _ in range(n_bays)]
    for b, j in enumerate(assign):
        bay_ids[j].append(b)
    results = {}
    total = 0.0
    # BUDGET-AWARE adaptive decode: when a decode deadline is set and adaptive is
    # ON, give each non-empty bay a SHARE of the remaining wall time so the
    # decoder can pick a candidate cap that lets the bay place all blocks cleanly
    # instead of running out of time mid-bay and force-placing its tail.  The
    # share is proportional to each bay's estimated FULL decode cost (a bay that
    # needs more time gets more), normalised over the bays STILL TO DECODE, then
    # clamped to the actual time left.  A bay whose share covers its full cost
    # gets cap=0 (full search) inside the decoder, so an ample budget is
    # untouched.  When deadline is None or adaptive is OFF, bay_budget stays None
    # -> the decoder behaves exactly as before (byte-identical).
    use_adapt = _ADAPT_DECODE and deadline is not None and _CAND_CAP <= 0
    adapt_cap_floor = 0
    if use_adapt and len(assign) >= 280 and n_bays >= 5:
        adapt_cap_floor = _ADAPT_LARGE_CAP_FLOOR
    full_costs = None
    if use_adapt:
        at = decoder.alt_threshold
        full_costs = [_bay_decode_secs(len(bay_ids[j]), at) for j in range(n_bays)]
    for j in range(n_bays):
        bay_budget = None
        if use_adapt:
            now = time.monotonic()
            time_left = deadline - now
            rem_cost = sum(full_costs[k] for k in range(j, n_bays))
            if time_left > 0.0 and rem_cost > 0.0 and full_costs[j] > 0.0:
                # this bay's proportional share of the remaining wall time.
                bay_budget = time_left * (full_costs[j] / rem_cost)
        res, t = decoder.decode(j, bay_ids[j], deadline=deadline,
                                bay_budget=bay_budget,
                                budget_cap_floor=adapt_cap_floor)
        if res is None:
            return None, math.inf
        results[j] = res
        total += t
    return results, total


def _obj_of_results(prob_info, results, bay_u):
    flat = [a for r in results.values() for a in r.values()]
    return _objective(prob_info, flat, bay_u)


def _local_search(prob_info, decoder, bays, feasible_bays, bay_u,
                  assign, results, deadline, tr=None,
                  op_weights0=(1.0, 1.0, 1.0), sa_temp_frac=0.10):
    """Assignment-level ALNS over the true objective.

    Three neighbourhoods -- single-block shift, two-block swap, and bounded
    multi-block destroy/repair (worst-tardiness or related-by-bay removal +
    greedy heaviest-first reinsertion) -- selected by adaptive roulette weights,
    with simulated-annealing acceptance of worsening moves (time-based cooling).
    Only the bays a move touches are re-decoded (the decoder is cached); Z2/Z3
    are recomputed in closed form.  A per-operator wall-clock guard skips any
    move whose worst-case re-decode would overrun `deadline`, so one iteration
    can never blow the budget.  Returns (best_assign, best_results, best_obj)."""
    n_bays = len(bays)
    n_blocks = len(assign)
    blocks_data = prob_info["blocks"]
    alt_threshold = decoder.alt_threshold

    cur_obj, *_ = _obj_of_results(prob_info, results, bay_u)
    best_assign = list(assign)
    best_results = {j: dict(results[j]) for j in results}
    best_obj = cur_obj

    if n_bays < 2 or n_blocks == 0:
        return best_assign, best_results, best_obj

    movable = [b for b in range(n_blocks) if len(feasible_bays[b]) > 1]
    if not movable:
        return best_assign, best_results, best_obj

    feas_set = [set(fb) for fb in feasible_bays]
    assign = list(assign)
    results = {j: dict(results[j]) for j in results}
    bay_ids = [set() for _ in range(n_bays)]
    for b, j in enumerate(assign):
        bay_ids[j].add(b)

    movable_set = set(movable)

    # ---- M4 no-good-cut state ------------------------------------------------
    # cut_store holds (bay_idx, frozenset(block_ids)) configurations that the
    # decoder reported as FORCE-PLACING (over-subscribed -> Z1 blow-up).  We
    # activate the M4 machinery (the op_cut_destroy operator + the cut consults)
    # ONLY when the incoming solution already force-places something.  On a
    # force-place-free instance has_force stays False: op_cut_destroy is never
    # added to the roulette, cut_store stays empty, and every `if cut_store`
    # consult short-circuits -- so the operator set, the RNG stream and the final
    # result are BIT-IDENTICAL to the pre-M4 (M3) search.  We read forced_ids out
    # of the decoder cache (the caller just decoded these bays) so detection costs
    # no extra decode.
    # M-debate P2: the cut machinery (op_cut_destroy + cut_store) only ever
    # activates on OVER-SUBSCRIBED bays, which never occur on any instance we see
    # (every gen/stress case is Z1=0), so it is dead-but-reachable code whose only
    # measured firing was a hand-built demo.  Default OFF (OGC_M4_CUT) keeps
    # has_oversub False and cut_store empty -> op_cut_destroy is never registered
    # and every `if cut_store` consult short-circuits == bit-identical to M3.
    # Opt-in preserves the safety net for a forced-over-subscription hidden case.
    cut_store: set = set()
    has_oversub = False
    # OGC_CRANE_TIEBREAK (default ON): tie-break equal-objective moves toward
    # fewer force-placed (crane-congested) blocks; read once here (OFF -> exact
    # legacy acceptance).
    crane_tiebreak = _env_on("OGC_CRANE_TIEBREAK", False)
    # OGC_M4_CRANE_CUT (default OFF) re-uses the same dead-but-reachable cut
    # machinery to switch crane-induced force-place cuts ON for benching.  Ships
    # OFF pending bench -- enabling may perturb proven incumbents (e.g. 1022.70).
    m4_on = _env_on("OGC_M4_CUT", False) or _env_on("OGC_M4_CRANE_CUT", False)
    for j in range(n_bays):
        if not m4_on or not bay_ids[j]:
            continue
        cached = decoder.cache.get((j, frozenset(bay_ids[j])))
        forced = cached[2] if (cached is not None and len(cached) > 2) else frozenset()
        if forced:
            cut_store.add((j, frozenset(bay_ids[j])))
        # A bay is OVER-SUBSCRIBED iff a movable block in it is force-placed OR
        # exits past its due date (tardy).  Tardiness is the real symptom: the
        # time-serialising decoder almost never needs the empty-window force-place
        # fallback, but an over-loaded bay still pushes blocks past due -> Z1.
        # When NOTHING is over-subscribed (every gen instance: Z1=0) has_oversub
        # stays False, op_cut_destroy is never registered, and the run is
        # bit-identical to the M3 search.
        rj = results.get(j) if isinstance(results, dict) else None
        if not has_oversub:
            for b in bay_ids[j]:
                if b not in movable_set:
                    continue
                a = rj.get(b) if rj else None
                if (b in forced) or (a is not None
                                     and a["exit_time"] > blocks_data[b]["due_date"]):
                    has_oversub = True
                    break

    def touch_fits(new_counts) -> bool:
        est = sum(_bay_decode_secs(c, alt_threshold) for c in new_counts)
        return time.monotonic() + est <= deadline

    # ---- neighbourhood operators: return (touched_results, changes) or None --
    def op_shift():
        b = random.choice(movable)
        j = assign[b]
        targets = [t for t in feasible_bays[b] if t != j]
        if not targets:
            return None
        k = random.choice(targets)
        if cut_store and (k, frozenset(bay_ids[k] | {b})) in cut_store:
            return None  # M4: target config is a known force-placing cut -> skip
        if not touch_fits((len(bay_ids[j]) - 1, len(bay_ids[k]) + 1)):
            return None
        rj, _ = decoder.decode(j, bay_ids[j] - {b})
        rk, _ = decoder.decode(k, bay_ids[k] | {b})
        if rj is None or rk is None:
            return None
        return {j: rj, k: rk}, [(b, j, k)]

    def op_swap():
        for _ in range(8):
            b = random.choice(movable)
            c = random.choice(movable)
            j, k = assign[b], assign[c]
            if j == k or b == c:
                continue
            if k not in feas_set[b] or j not in feas_set[c]:
                continue
            if not touch_fits((len(bay_ids[j]), len(bay_ids[k]))):
                return None
            rj, _ = decoder.decode(j, (bay_ids[j] - {b}) | {c})
            rk, _ = decoder.decode(k, (bay_ids[k] - {c}) | {b})
            if rj is None or rk is None:
                continue
            return {j: rj, k: rk}, [(b, j, k), (c, k, j)]
        return None

    def op_destroy_repair():
        if len(movable) < 2:
            return None
        d = random.randint(2, min(6, len(movable)))
        if random.random() < 0.5:
            removed = sorted(
                movable,
                key=lambda b: -max(0.0, results[assign[b]][b]["exit_time"]
                                   - blocks_data[b]["due_date"]))[:d]
        else:
            mset = set(movable)
            cand = [j for j in range(n_bays) if len(bay_ids[j] & mset) >= 2]
            if not cand:
                return None
            inb = list(bay_ids[random.choice(cand)] & mset)
            random.shuffle(inb)
            removed = inb[:max(2, min(d, len(inb)))]
        if not removed:
            return None

        w_ids = [set(s) for s in bay_ids]
        w_res = dict(results)
        changed = set()
        for b in removed:
            j = assign[b]
            w_ids[j].discard(b)
            changed.add(j)
        for j in list(changed):
            # Cumulative-deadline guard: touch_fits estimates ONE decode, but a
            # destroy/repair chains many.  A hard wall-clock check between
            # decodes bounds a single move's overrun to ~one decode (the trace
            # caught one move running 25s past the deadline -> near-timeout).
            if time.monotonic() >= deadline or not touch_fits((len(w_ids[j]),)):
                return None
            rj, _ = decoder.decode(j, w_ids[j])
            if rj is None:
                return None
            w_res[j] = rj
        final_bay = {}
        for b in sorted(removed, key=lambda x: -blocks_data[x]["workload"]):
            if time.monotonic() >= deadline:
                return None
            best_k = best_kres = None
            best_kobj = math.inf
            for k in feasible_bays[b]:
                if time.monotonic() >= deadline:
                    return None
                if not touch_fits((len(w_ids[k]) + 1,)):
                    continue
                rk, _ = decoder.decode(k, w_ids[k] | {b})
                if rk is None:
                    continue
                trial = dict(w_res)
                trial[k] = rk
                o, *_ = _obj_of_results(prob_info, trial, bay_u)
                if o < best_kobj:
                    best_kobj, best_k, best_kres = o, k, rk
            if best_k is None:
                return None
            w_ids[best_k].add(b)
            w_res[best_k] = best_kres
            changed.add(best_k)
            final_bay[b] = best_k
        chg = [(b, assign[b], final_bay[b]) for b in removed
               if final_bay[b] != assign[b]]
        if not chg:
            return None
        return {j: w_res[j] for j in changed}, chg

    def op_cut_destroy():
        # M4 no-good-cut destroy.  Read the decoder's FORCE-PLACE certificate out
        # of the cache (no extra decode), eject the force-placed blocks from the
        # worst over-subscribed bay, record that (bay, block-set) as a cut, and
        # greedily re-home the ejected blocks into OTHER bays -- skipping any
        # target that would re-create a known cut.  Directly removes the Z1
        # blow-up of an over-subscribed bay.  Returns None when nothing is forced
        # (so on a force-place-free run this operator is never even registered).
        oversub_by_bay = []
        for j in range(n_bays):
            if not bay_ids[j]:
                continue
            cached = decoder.cache.get((j, frozenset(bay_ids[j])))
            forced = cached[2] if (cached is not None and len(cached) > 2) else frozenset()
            rj = results.get(j) if isinstance(results, dict) else None
            bad = []
            for b in bay_ids[j]:
                if b not in movable_set:
                    continue
                a = rj.get(b) if rj else None
                if (b in forced) or (a is not None
                                     and a["exit_time"] > blocks_data[b]["due_date"]):
                    bad.append(b)
            if bad:
                oversub_by_bay.append((j, bad))
        if not oversub_by_bay:
            return None
        # Attack the bay with the most over-subscribing (force-placed/tardy) blocks.
        src, bad = max(oversub_by_bay, key=lambda kv: len(kv[1]))
        random.shuffle(bad)
        removed = bad[:min(4, len(bad))]
        cut_store.add((src, frozenset(bay_ids[src])))
        if (time.monotonic() >= deadline
                or not touch_fits((len(bay_ids[src]) - len(removed),))):
            return None
        w_ids = [set(s) for s in bay_ids]
        w_res = dict(results)
        for b in removed:
            w_ids[src].discard(b)
        rsrc, _ = decoder.decode(src, w_ids[src])
        if rsrc is None:
            return None
        w_res[src] = rsrc
        changed = {src}
        final_bay = {}
        for b in sorted(removed, key=lambda x: -blocks_data[x]["workload"]):
            if time.monotonic() >= deadline:
                return None
            best_k = best_kres = None
            best_kobj = math.inf
            for k in feasible_bays[b]:
                if k == src:
                    continue  # never re-add to the over-subscribed source bay
                new_ids = w_ids[k] | {b}
                if cut_store and (k, frozenset(new_ids)) in cut_store:
                    continue
                if time.monotonic() >= deadline or not touch_fits((len(new_ids),)):
                    continue
                rk, _ = decoder.decode(k, new_ids)
                if rk is None:
                    continue
                trial = dict(w_res)
                trial[k] = rk
                o, *_ = _obj_of_results(prob_info, trial, bay_u)
                if o < best_kobj:
                    best_kobj, best_k, best_kres = o, k, rk
            if best_k is None:
                return None
            w_ids[best_k].add(b)
            w_res[best_k] = best_kres
            changed.add(best_k)
            final_bay[b] = best_k
        chg = [(b, src, final_bay[b]) for b in removed if final_bay[b] != src]
        if not chg:
            return None
        return {c: w_res[c] for c in changed}, chg

    operators = [op_shift, op_swap, op_destroy_repair]
    op_names = ["shift", "swap", "destroy_repair"]
    if has_oversub:
        # M4: register the cut-destroy operator ONLY when the incoming solution
        # is over-subscribed (a movable block is force-placed or tardy).  On a
        # Z1=0 instance (every gen instance) has_oversub is False, so the operator
        # set -- and therefore the RNG stream and result -- is bit-identical to
        # the M3 search.  This is what keeps example_B2_b10 at 1022.70.
        operators.append(op_cut_destroy)
        op_names.append("cut_destroy")
    n_ops = len(operators)
    # M6: regime-supplied STARTING roulette weights (adaptive update still
    # re-learns them); defaults to all-1.0 == current behaviour.
    weights = [float(op_weights0[i]) if i < len(op_weights0) else 1.0
               for i in range(n_ops)]
    scores = [0.0] * n_ops
    uses = [0] * n_ops
    rho, segment = 0.2, 25

    t0 = time.monotonic()
    span = max(1e-6, deadline - t0)
    temp0 = sa_temp_frac * max(1.0, abs(best_obj))  # M6: regime SA temperature
    temp_end = max(1e-9, 1e-4 * temp0)

    # --- instrumentation counters (plain ints; events emitted only when ON) ---
    trc_on = tr is not None and getattr(tr, "enabled", False)
    iters = accepts = rejects = nulls = n_improve = restarts = 0
    # Stagnation guard: after this many restarts with NO new global best, the
    # search has converged -- stop and hand the remaining budget back (the
    # trace showed runs doing 500k+ iterations / 8000+ restarts for 0 gain,
    # wasting the window and pushing wall-clock toward the timeout boundary).
    stale_restarts = 0
    STALL_LIMIT = 25
    op_uses_tot = [0] * n_ops
    op_accepts = [0] * n_ops
    op_improves = [0] * n_ops
    snap_dt = max(0.05, span / 300.0)
    next_snap = t0 + snap_dt
    if trc_on:
        s_obj, s1, s2, s3 = _obj_of_results(prob_info, results, bay_u)
        tr.log("search_start", obj=s_obj, z1=s1, z2=s2, z3=s3,
               n_movable=len(movable), n_blocks=n_blocks, n_bays=n_bays,
               temp0=temp0, span=span, operators=op_names)

    no_improve = seg_count = 0
    # Wall-clock global-best stall early-exit (OGC_SEARCH_STALL_PCT, default 0=off):
    # stop if no NEW GLOBAL BEST for stall_w seconds -- the post-convergence tail is
    # pure waste (prob_2 ran ~150s past its last improvement).  Safe by construction:
    # an instance still improving keeps refreshing _best_t, so it never trips this
    # (z1 is not lost on the hard instances); only converged searches exit early.
    _stall_w = (_env_int("OGC_SEARCH_STALL_PCT", 0) / 100.0) * span
    _min_s = 0.10 * span
    _best_t = t0
    _best_sig = best_obj   # last SIGNIFICANT best (>0.1% drop) -- tiny improvements
                           # must NOT keep refreshing the stall timer (the search
                           # otherwise crawls to the deadline on negligible gains).
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        if _stall_w > 0 and now - _best_t > _stall_w and now - t0 > _min_s:
            break
        iters += 1
        if trc_on and now >= next_snap:
            frac = min(1.0, (now - t0) / span)
            temp = temp0 * (temp_end / temp0) ** frac
            tr.log("search_snap", iter=iters, cur=cur_obj, best=best_obj,
                   temp=temp, no_improve=no_improve,
                   weights=[round(w, 4) for w in weights])
            next_snap += snap_dt

        tot = sum(weights)
        r = random.random() * tot
        idx, acc = n_ops - 1, 0.0
        for i in range(n_ops):
            acc += weights[i]
            if r <= acc:
                idx = i
                break

        prop = operators[idx]()
        uses[idx] += 1
        op_uses_tot[idx] += 1
        if prop is not None:
            touched, changes = prop
            trial = dict(results)
            trial.update(touched)
            trial_obj, *_ = _obj_of_results(prob_info, trial, bay_u)
            delta = trial_obj - cur_obj
            accept = delta < -1e-9
            if not accept:
                frac = min(1.0, (now - t0) / span)
                temp = temp0 * (temp_end / temp0) ** frac
                accept = temp > 1e-12 and random.random() < math.exp(-delta / temp)
            # OGC_CRANE_TIEBREAK (default ON): on an objective TIE, decide
            # acceptance by crane congestion instead of the SA coin (which on a
            # tie has p~=1 and so accepts blindly).  This is an authoritative
            # override on ties ONLY; it does not consume RNG and leaves the SA
            # branch (and its random.random() draw) untouched, so non-tie moves
            # are bit-identical to legacy.  Force-placed count is the cheap
            # crane-congestion proxy (force-place happens iff crane/collision
            # feasibility fails, _decode_bay:392-396) and is read for free from
            # the decoder cache (touched bays were just decoded; cur's bays are
            # cached) -- no extra full decode.  Drifting toward fewer force-places
            # makes the final crane-feasibility gate more likely to keep a move,
            # reducing reliance on OGC_PROTECT_SEED banking (bug note ~:2155).
            if (crane_tiebreak
                    and abs(trial_obj - cur_obj) <= 1e-6 * max(1.0, abs(cur_obj))):
                cur_forced = sum(
                    len(decoder.cache[(jj, frozenset(bay_ids[jj]))][2])
                    for jj in range(n_bays)
                    if bay_ids[jj]
                    and (jj, frozenset(bay_ids[jj])) in decoder.cache
                    and len(decoder.cache[(jj, frozenset(bay_ids[jj]))]) > 2)
                # trial membership = current bay_ids with `changes` applied.
                trial_ids = [set(s) for s in bay_ids]
                for (b, oj, nj) in changes:
                    trial_ids[oj].discard(b)
                    trial_ids[nj].add(b)
                trial_forced = sum(
                    len(decoder.cache[(jj, frozenset(trial_ids[jj]))][2])
                    for jj in range(n_bays)
                    if trial_ids[jj]
                    and (jj, frozenset(trial_ids[jj])) in decoder.cache
                    and len(decoder.cache[(jj, frozenset(trial_ids[jj]))]) > 2)
                # Accept the tie ONLY if it does not increase force-placed count
                # (strictly prefer fewer; never accept an equal-obj move that
                # raises crane congestion).
                accept = trial_forced <= cur_forced
            if accept:
                for (b, oj, nj) in changes:
                    bay_ids[oj].discard(b)
                    bay_ids[nj].add(b)
                    assign[b] = nj
                results = trial
                cur_obj = trial_obj
                accepts += 1
                op_accepts[idx] += 1
                if cur_obj < best_obj - 1e-9:
                    best_obj = cur_obj
                    best_assign = list(assign)
                    best_results = {jj: dict(results[jj]) for jj in results}
                    no_improve = 0
                    if cur_obj < _best_sig - max(1.0, 1e-3 * abs(_best_sig)):
                        _best_t = now
                        _best_sig = cur_obj
                    scores[idx] += 3.0
                    n_improve += 1
                    op_improves[idx] += 1
                    stale_restarts = 0
                    if trc_on:
                        _, b1, b2, b3 = _obj_of_results(prob_info, results, bay_u)
                        tr.log("search_improve", iter=iters, t_rel=round(now - t0, 4),
                               obj=best_obj, z1=b1, z2=b2, z3=b3,
                               op=op_names[idx] if idx < len(op_names) else idx)
                else:
                    no_improve += 1
                    scores[idx] += 2.0 if delta < -1e-9 else 1.0
            else:
                no_improve += 1
                rejects += 1
        else:
            no_improve += 1
            nulls += 1

        seg_count += 1
        if seg_count >= segment:
            for i in range(n_ops):
                if uses[i] > 0:
                    weights[i] = max(0.05, (1 - rho) * weights[i]
                                     + rho * (scores[i] / uses[i]))
                scores[i] = 0.0
                uses[i] = 0
            seg_count = 0

        if no_improve >= max(60, 5 * n_blocks):
            restarts += 1
            stale_restarts += 1
            # Throttle: restarts can fire thousands of times on tiny instances
            # (the thrash signal lives in the *count*, in search_end).  Sample
            # the first few + every 250th so the trace stays small.
            if trc_on and (restarts <= 3 or restarts % 250 == 0):
                tr.log("search_restart", iter=iters, n=restarts,
                       no_improve=no_improve, cur=cur_obj, best=best_obj)
            if stale_restarts >= STALL_LIMIT:
                if trc_on:
                    tr.log("search_stop_early", iter=iters, restarts=restarts,
                           best=best_obj, reason="stagnation")
                break
            assign = list(best_assign)
            results = {jj: dict(best_results[jj]) for jj in best_results}
            bay_ids = [set() for _ in range(n_bays)]
            for bb, jj in enumerate(assign):
                bay_ids[jj].add(bb)
            cur_obj = best_obj
            no_improve = 0

    if trc_on:
        _, e1, e2, e3 = _obj_of_results(prob_info, best_results, bay_u)
        tr.log("search_end", iters=iters, accepts=accepts, rejects=rejects,
               nulls=nulls, n_improve=n_improve, restarts=restarts,
               stopped_early=(stale_restarts >= STALL_LIMIT), best_obj=best_obj,
               best_z1=e1, best_z2=e2, best_z3=e3,
               op_names=op_names, op_uses=op_uses_tot, op_accepts=op_accepts,
               op_improves=op_improves, weights=[round(w, 4) for w in weights],
               elapsed=round(time.monotonic() - t0, 4))

    return best_assign, best_results, best_obj


# ---------------------------------------------------------------------------
# Guaranteed-feasible floors
# ---------------------------------------------------------------------------

def _assign_from_solution(sol: dict, n_blocks: int):
    assign = [-1] * n_blocks
    for ops in sol.get("operations", {}).values():
        for op in ops:
            if op.get("type") == "ENTRY":
                assign[op["block_id"]] = op["bay_id"]
    return assign


def _trivial_solution(prob_info, bays, feasible_bays):
    """Absolute fallback: serial EDD placement with empty bay windows.

    Blocks never overlap in the same bay, so crane and collision constraints are
    vacuous.  We still use Bay.contains_block for the chosen orientation because
    bbox-fit alone can accept an anchored polygon that leaks past a wall after
    integer rounding.
    """
    blocks_data = prob_info["blocks"]
    n_blocks = len(blocks_data)
    schedule = [[] for _ in bays]
    assigns = []
    loads = [0.0] * len(bays)
    bay_areas = [max(1.0, bay.width * bay.height) for bay in bays]
    avg_area = sum(bay_areas) / len(bay_areas) if bay_areas else 1.0
    bay_u = [avg_area / a for a in bay_areas]
    w = prob_info.get("weights", {})
    w1, w2, w3 = w.get("w1", 1.0), w.get("w2", 1.0), w.get("w3", 1.0)

    order = sorted(range(n_blocks),
                   key=lambda b: (blocks_data[b]["due_date"],
                                  blocks_data[b]["release_time"],
                                  blocks_data[b]["processing_time"]))
    for b in order:
        blk = blocks_data[b]
        prefs = blk["bay_preferences"]
        s_max = max(prefs)
        best = None
        for j in feasible_bays[b] or range(len(bays)):
            forced = _force_in_bay(b, blocks_data, bays[j], j, schedule[j])
            if forced is None:
                continue
            new_loads = list(loads)
            new_loads[j] += blk["workload"]
            if len(bays) >= 2:
                wl = [bay_u[k] * new_loads[k] for k in range(len(bays))]
                z2_proxy = max(wl) - min(wl)
            else:
                z2_proxy = 0.0
            tard = max(0.0, forced["exit_time"] - blk["due_date"])
            pref_pen = s_max - prefs[j]
            key = (w1 * tard + w2 * z2_proxy + w3 * pref_pen,
                   tard, pref_pen, forced["exit_time"])
            if best is None or key < best[0]:
                best = (key, forced)
        if best is None:  # degenerate last resort; feasibility may be impossible
            j = 0
            bb = _block_bbox(blk, 0)
            entry = _empty_bay_entry(schedule[0], blk["release_time"],
                                     blk["processing_time"])
            forced = {"block_id": b, "bay_id": 0,
                      "x": max(0, math.ceil(-bb[0])),
                      "y": max(0, math.ceil(-bb[1])),
                      "orient_idx": 0, "entry_time": int(entry),
                      "exit_time": int(entry + blk["processing_time"])}
        else:
            forced = best[1]
            j = forced["bay_id"]
        schedule[j].append((forced["entry_time"], forced["exit_time"]))
        loads[j] += blk["workload"]
        assigns.append(forced)
    return {"operations": _build_operations(assigns)}


def _results_from_solution(prob_info: dict, sol: dict):
    """Parse a solution into (assign, per_bay_results, flat_assignments)."""
    n_blocks = len(prob_info["blocks"])
    n_bays = len(prob_info["bays"])
    entries: dict[int, dict] = {}
    exits: dict[int, int] = {}
    for t_str, ops in sol.get("operations", {}).items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            if op.get("type") == "ENTRY":
                a = dict(op)
                a["entry_time"] = t
                entries[bid] = a
            elif op.get("type") == "EXIT":
                exits[bid] = t
    assign = [0] * n_blocks
    results = {j: {} for j in range(n_bays)}
    flat = []
    for bid, a in entries.items():
        if bid not in exits:
            continue
        a["exit_time"] = exits[bid]
        j = a["bay_id"]
        assign[bid] = j
        results[j][bid] = a
        flat.append(a)
    return assign, results, flat


def _components_from_solution(prob_info: dict, sol: dict, bay_u: list[float]):
    """Best-effort objective components for an already-verified solution."""
    try:
        _assign, _results, flat = _results_from_solution(prob_info, sol)
        if len(flat) != len(prob_info["blocks"]):
            return None
        return _objective(prob_info, flat, bay_u)
    except Exception:
        return None


def _fixed_layout_reschedule(prob_info: dict, bays: list[Bay], results: dict,
                             deadline: float | None = None):
    """Keep every block's bay/x/y/orientation fixed, but greedily left-shift each
    bay in EDD order with the complete crane-safe slot check.

    Self-bounding: this re-runs the O(n^2/bays) crane-safe slot finder, so on
    large instances it can take seconds.  When ``deadline`` is given it aborts
    (returns None) the moment it is crossed, so the caller can run it on 300-block
    instances without risking a wall-clock overrun (-1 on a strict server)."""
    flat = []
    for j, by_id in results.items():
        placed: list[Block] = []
        schedule: list[tuple[int, int]] = []
        order = sorted(
            by_id,
            key=lambda b: (
                prob_info["blocks"][b]["due_date"],
                by_id[b]["entry_time"],
                prob_info["blocks"][b]["processing_time"],
            ),
        )
        for bid in order:
            if deadline is not None and time.monotonic() >= deadline:
                return None
            old = by_id[bid]
            blk = prob_info["blocks"][bid]
            nb = Block(block_id=bid, block_data=blk,
                       x=old["x"], y=old["y"], orient_idx=old["orient_idx"])
            if not bays[j].contains_block(nb):
                return None
            entry, exit_t = _find_slot_crane_safe(
                nb, bays[j], placed, schedule,
                blk["release_time"], blk["processing_time"])
            if entry is None:
                return None
            placed.append(nb)
            schedule.append((int(entry), int(exit_t)))
            a = dict(old)
            a["entry_time"] = int(entry)
            a["exit_time"] = int(exit_t)
            flat.append(a)
    return {"operations": _build_operations(flat)}


def _bay_tardiness_lb(ids, blocks_data) -> float:
    """Rigorous lower bound on a bay's total tardiness under ANY schedule
    (insight 2, Block-Relocation LB family).  A block cannot exit before
    release+processing regardless of crane/spatial contention, so the sum of the
    per-block independent minima ``max(0, r_b + p_b - due_b)`` floors the bay's
    Z1.  Timing-only rescheduling can never beat this floor, so a bay already at
    its LB is skipped (focus the budget on bays with a real, recoverable gap)."""
    lb = 0.0
    for b in ids:
        blk = blocks_data[b]
        lb += max(0.0, blk["release_time"] + blk["processing_time"]
                  - blk["due_date"])
    return lb


def _multi_order_reschedule_verified(prob_info: dict, bays: list[Bay],
                                     results: dict,
                                     deadline: float | None = None,
                                     lb_skip: bool = False,
                                     max_orders: int = 5):
    """Fixed-layout, multi-order crane-safe left-shift (insight 1 strengthened
    with insight 8 / dynasearch-style multi-start).

    Keeps every block's bay/x/y/orientation fixed -- so Z2 and Z3 are provably
    unchanged -- and only re-times ENTRY/EXIT.  Unlike the single-EDD
    ``_fixed_layout_reschedule``, each bay tries several crane-feasible orders
    (EDD/slack, release, ATCR, due, raw-slack) of the earliest-slot pass and
    keeps whichever yields the least bay tardiness.  Objective-safe by
    construction (only ENTRY/EXIT move); the caller still gates the result
    through the official checker.

    Returns a candidate solution dict, or None if the deadline is hit before the
    sweep finishes (a partial solution would be missing blocks and rejected)."""
    blocks = prob_info["blocks"]
    out_flat = []
    for j, by_id in results.items():
        if not by_id:
            continue
        ids = list(by_id)
        cur_tard = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                       for b, a in by_id.items())
        # Focus: a bay with no tardiness, or already at its provable LB, cannot be
        # improved by re-timing alone -- keep it verbatim and spend budget on bays
        # that actually have a recoverable gap.
        if cur_tard <= 1e-9 or (lb_skip
                                and cur_tard <= _bay_tardiness_lb(ids, blocks) + 1e-9):
            for a in by_id.values():
                out_flat.append(dict(a))
            continue
        # Candidate crane-feasible orders (deduplicated, bounded).
        orders = []
        for o in _orderings(ids, blocks, True):
            if o not in orders:
                orders.append(o)
        for key in (
            lambda b: (blocks[b]["due_date"], blocks[b]["release_time"]),
            lambda b: (blocks[b]["due_date"] - blocks[b]["release_time"]
                       - blocks[b]["processing_time"], blocks[b]["due_date"]),
        ):
            o = sorted(ids, key=key)
            if o not in orders:
                orders.append(o)
        orders = orders[:max_orders]

        best_sched = None
        best_tard = math.inf
        for order in orders:
            if deadline is not None and time.monotonic() >= deadline:
                return None
            placed: list[Block] = []
            schedule: list[tuple[int, int]] = []
            sched: dict[int, tuple[int, int]] = {}
            ok = True
            for bid in order:
                old = by_id[bid]
                blk = blocks[bid]
                nb = Block(block_id=bid, block_data=blk,
                           x=old["x"], y=old["y"], orient_idx=old["orient_idx"])
                if not bays[j].contains_block(nb):
                    ok = False
                    break
                entry, exit_t = _find_slot_crane_safe(
                    nb, bays[j], placed, schedule,
                    blk["release_time"], blk["processing_time"])
                if entry is None:
                    ok = False
                    break
                placed.append(nb)
                schedule.append((int(entry), int(exit_t)))
                sched[bid] = (int(entry), int(exit_t))
            if not ok:
                continue
            tard = sum(max(0.0, sched[b][1] - blocks[b]["due_date"]) for b in ids)
            if tard < best_tard:
                best_tard = tard
                best_sched = sched
        if best_sched is None:
            # No order reproduced a crane-safe schedule -> keep original timings.
            for a in by_id.values():
                out_flat.append(dict(a))
            continue
        for bid, a in by_id.items():
            a2 = dict(a)
            a2["entry_time"], a2["exit_time"] = best_sched[bid]
            out_flat.append(a2)
    if not out_flat:
        return None
    return {"operations": _build_operations(out_flat)}


def _cpsat_bay_timing_verified(prob_info: dict, bays: list[Bay],
                               results: dict,
                               deadline: float | None = None,
                               lb_skip: bool = True):
    """Fixed-layout per-bay OPTIMAL crane-feasible re-timing via CP-SAT (insight 1,
    optimal replacement for the <=5-ordering heuristic in
    ``_multi_order_reschedule_verified``).

    Key facts that make this an exact, tractable model:
      * Every crane/collision geometry check depends ONLY on the FIXED positions
        (x,y,orient), never on entry time -- so for each interacting pair we
        precompute 5 time-independent booleans once (O(n^2) Shapely calls/bay).
      * exit = entry + processing is WLOG optimal: extending exit only keeps a
        block present longer (more crane conflict) and raises tardiness.  So each
        block needs ONE integer var (entry); exit is the linear expr entry+P.
      * The crane/collision constraints then become pure interval disjunctions
        over integer entries -> CP-SAT solves the per-bay tardiness optimum.

    Keeps bay/x/y/orientation fixed (Z2,Z3 provably unchanged); only ENTRY/EXIT
    move.  intrinsicLB=0 on all train instances, so this can in principle drive a
    bay's Z1 to its crane-induced minimum.  Caller gates the result through the
    official checker (objective-safe).  Returns a candidate solution dict, or None
    if ortools is unavailable / deadline hit / nothing improved structurally."""
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    blocks = prob_info["blocks"]
    # Bays that have a recoverable gap (tardy above their provable LB).
    work = []
    for j, by_id in results.items():
        if not by_id:
            continue
        ids = list(by_id)
        cur_tard = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                       for b, a in by_id.items())
        if cur_tard <= 1e-9:
            continue
        if lb_skip and cur_tard <= _bay_tardiness_lb(ids, blocks) + 1e-9:
            continue
        work.append((j, ids, cur_tard))
    if not work:
        return None
    # Budget split across bays needing work (leave the caller's check margin).
    now = time.monotonic()
    total_budget = max(0.0, (deadline - now)) if deadline is not None else 30.0
    if total_budget < 0.5:
        return None
    per_bay = max(1.0, total_budget / len(work))

    out = {j: {b: dict(a) for b, a in by.items()} for j, by in results.items()}
    improved_any = False
    for j, ids, cur_tard in work:
        if deadline is not None and time.monotonic() >= deadline - 0.2:
            break
        by_id = out[j]
        bay = bays[j]
        # Build Block objects + scalars for this bay's fixed layout.
        blk_obj = {}
        R = {}; P = {}; D = {}
        cur_entry = {}
        for b in ids:
            a = by_id[b]
            blk = blocks[b]
            blk_obj[b] = Block(block_id=b, block_data=blk,
                               x=a["x"], y=a["y"], orient_idx=a["orient_idx"])
            R[b] = int(blk["release_time"]); P[b] = int(blk["processing_time"])
            D[b] = int(blk["due_date"]); cur_entry[b] = int(a["entry_time"])
        # Horizon: current makespan + slack (current schedule is feasible and is the
        # warm-start, so the optimum lives at or below it; a little slack lets the
        # solver reorder).
        cur_makespan = max(int(by_id[b]["exit_time"]) for b in ids)
        maxP = max(P[b] for b in ids)
        H = cur_makespan + maxP

        m = cp_model.CpModel()
        e = {b: m.NewIntVar(R[b], H, f"e_{b}") for b in ids}
        # exit expr = e[b] + P[b].  Forbid each active crane/collision config via
        # half-reified BoolOr (when the geometry boolean is True).
        for ia in range(len(ids)):
            a = ids[ia]
            for ib in range(ia + 1, len(ids)):
                b = ids[ib]
                ba_e = bool(check_entry(bay, [blk_obj[b]], blk_obj[a], fast=True))
                ab_e = bool(check_entry(bay, [blk_obj[a]], blk_obj[b], fast=True))
                ba_x = bool(check_exit(bay, [blk_obj[b]], blk_obj[a], fast=True))
                ab_x = bool(check_exit(bay, [blk_obj[a]], blk_obj[b], fast=True))
                coll = bool(check_collisions(bay, [blk_obj[a], blk_obj[b]]))
                ae, be = e[a], e[b]
                ax = ae + P[a]; bx = be + P[b]
                co = _CRANE_COEXIT

                if coll:
                    # forbid overlap: a_e <= b_x-1 AND b_e <= a_x-1
                    # neg: a_x <= b_e  OR  b_x <= a_e
                    l1 = m.NewBoolVar(""); l2 = m.NewBoolVar("")
                    m.Add(ax <= be).OnlyEnforceIf(l1)
                    m.Add(bx <= ae).OnlyEnforceIf(l2)
                    m.AddBoolOr([l1, l2])
                    continue  # disjoint subsumes the crane configs for this pair
                if ba_e:  # b present at a's entry forbidden: b_e<=a_e<=b_x-1
                    l1 = m.NewBoolVar(""); l2 = m.NewBoolVar("")
                    m.Add(ae <= be - 1).OnlyEnforceIf(l1)
                    m.Add(ae >= bx).OnlyEnforceIf(l2)
                    m.AddBoolOr([l1, l2])
                if ab_e:  # a present at b's entry forbidden: a_e<=b_e<=a_x-1
                    l1 = m.NewBoolVar(""); l2 = m.NewBoolVar("")
                    m.Add(be <= ae - 1).OnlyEnforceIf(l1)
                    m.Add(be >= ax).OnlyEnforceIf(l2)
                    m.AddBoolOr([l1, l2])
                if ba_x:  # b present at a's exit forbidden: b_e<=a_x-1 AND a_x<=(b_x|b_x-1)
                    l1 = m.NewBoolVar(""); l2 = m.NewBoolVar("")
                    m.Add(ax <= be).OnlyEnforceIf(l1)
                    m.Add(ax >= (bx + 1) if co else (bx)).OnlyEnforceIf(l2)
                    m.AddBoolOr([l1, l2])
                if ab_x:  # a present at b's exit forbidden
                    l1 = m.NewBoolVar(""); l2 = m.NewBoolVar("")
                    m.Add(bx <= ae).OnlyEnforceIf(l1)
                    m.Add(bx >= (ax + 1) if co else (ax)).OnlyEnforceIf(l2)
                    m.AddBoolOr([l1, l2])

        tard = []
        for b in ids:
            tb = m.NewIntVar(0, H, f"t_{b}")
            m.Add(tb >= e[b] + P[b] - D[b])
            tard.append(tb)
        m.Minimize(sum(tard))
        for b in ids:
            m.AddHint(e[b], cur_entry[b])

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(per_bay)
        solver.parameters.num_search_workers = 4
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            continue
        new_tard = sum(max(0, solver.Value(e[b]) + P[b] - D[b]) for b in ids)
        if new_tard < cur_tard - 1e-9:
            for b in ids:
                ev = int(solver.Value(e[b]))
                by_id[b]["entry_time"] = ev
                by_id[b]["exit_time"] = ev + P[b]
            improved_any = True

    if not improved_any:
        return None
    out_flat = [dict(a) for by in out.values() for a in by.values()]
    return {"operations": _build_operations(out_flat)}


_GUROBI_OK = None  # lazy availability cache


def _gurobi_available() -> bool:
    global _GUROBI_OK
    if _GUROBI_OK is None:
        try:
            import gurobipy as gp  # noqa: F401
            _GUROBI_OK = True
        except Exception:
            _GUROBI_OK = False
    return _GUROBI_OK


def _gurobi_bay_timing_verified(prob_info: dict, bays: list[Bay],
                                results: dict,
                                deadline: float | None = None,
                                lb_skip: bool = True):
    """Gurobi port of ``_cpsat_bay_timing_verified`` -- per-bay OPTIMAL crane-feasible
    re-timing on a FIXED layout, solved by Gurobi MIP instead of CP-SAT.

    Same exact disjunctive model: the crane/collision geometry depends only on the
    fixed (x,y,orient), so each interacting pair contributes 5 time-independent
    booleans (precomputed once) that become interval disjunctions over the integer
    entry vars.  Why Gurobi here: (1) Gurobi's parallel MIP is DETERMINISTIC at a
    fixed Threads (CP-SAT's num_search_workers>1 + wall-clock is NOT -> that is the
    +-20x prob_20 variance), and (2) disjunctive scheduling with indicator
    constraints is Gurobi's home turf, so it often proves the per-bay optimum faster.
    Keeps bay/x/y/orient fixed (Z2,Z3 unchanged); caller gates via the official
    checker (objective-safe).  Returns a candidate solution dict, or None if gurobi
    is unavailable / size-limited / deadline hit / nothing improved structurally."""
    if not _gurobi_available():
        return None
    import gurobipy as gp
    from gurobipy import GRB
    blocks = prob_info["blocks"]
    work = []
    for j, by_id in results.items():
        if not by_id:
            continue
        ids = list(by_id)
        cur_tard = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                       for b, a in by_id.items())
        if cur_tard <= 1e-9:
            continue
        if lb_skip and cur_tard <= _bay_tardiness_lb(ids, blocks) + 1e-9:
            continue
        work.append((j, ids, cur_tard))
    if not work:
        return None
    now = time.monotonic()
    total_budget = max(0.0, (deadline - now)) if deadline is not None else 30.0
    if total_budget < 0.5:
        return None
    per_bay = max(1.0, total_budget / len(work))

    out = {j: {b: dict(a) for b, a in by.items()} for j, by in results.items()}
    improved_any = False
    for j, ids, cur_tard in work:
        if deadline is not None and time.monotonic() >= deadline - 0.2:
            break
        by_id = out[j]
        bay = bays[j]
        blk_obj = {}
        R = {}; P = {}; D = {}
        cur_entry = {}
        for b in ids:
            a = by_id[b]
            blk = blocks[b]
            blk_obj[b] = Block(block_id=b, block_data=blk,
                               x=a["x"], y=a["y"], orient_idx=a["orient_idx"])
            R[b] = int(blk["release_time"]); P[b] = int(blk["processing_time"])
            D[b] = int(blk["due_date"]); cur_entry[b] = int(a["entry_time"])
        cur_makespan = max(int(by_id[b]["exit_time"]) for b in ids)
        maxP = max(P[b] for b in ids)
        H = cur_makespan + maxP
        co = _CRANE_COEXIT
        try:
            m = gp.Model()
            m.setParam("OutputFlag", 0)
            m.setParam("Threads", 4)
            m.setParam("TimeLimit", float(per_bay))
            m.setParam("Seed", 0)  # determinism (Gurobi parallel MIP is reproducible)
            m.setParam("MIPFocus", 1)  # find good feasible incumbents fast
            e = {b: m.addVar(vtype=GRB.INTEGER, lb=R[b], ub=H, name=f"e_{b}")
                 for b in ids}

            def _disj(tc1, tc2):
                # l1 OR l2;  l1 -> tc1,  l2 -> tc2  (indicator constraints, exact)
                l1 = m.addVar(vtype=GRB.BINARY)
                l2 = m.addVar(vtype=GRB.BINARY)
                m.addConstr(l1 + l2 >= 1)
                m.addGenConstrIndicator(l1, True, tc1)
                m.addGenConstrIndicator(l2, True, tc2)

            for ia in range(len(ids)):
                a = ids[ia]
                for ib in range(ia + 1, len(ids)):
                    b = ids[ib]
                    ba_e = bool(check_entry(bay, [blk_obj[b]], blk_obj[a], fast=True))
                    ab_e = bool(check_entry(bay, [blk_obj[a]], blk_obj[b], fast=True))
                    ba_x = bool(check_exit(bay, [blk_obj[b]], blk_obj[a], fast=True))
                    ab_x = bool(check_exit(bay, [blk_obj[a]], blk_obj[b], fast=True))
                    coll = bool(check_collisions(bay, [blk_obj[a], blk_obj[b]]))
                    ae, be = e[a], e[b]
                    ax = ae + P[a]; bx = be + P[b]
                    if coll:
                        _disj(ax <= be, bx <= ae)
                        continue
                    if ba_e:
                        _disj(ae <= be - 1, ae >= bx)
                    if ab_e:
                        _disj(be <= ae - 1, be >= ax)
                    if ba_x:
                        _disj(ax <= be, ax >= ((bx + 1) if co else bx))
                    if ab_x:
                        _disj(bx <= ae, bx >= ((ax + 1) if co else ax))

            tard = []
            for b in ids:
                tb = m.addVar(vtype=GRB.INTEGER, lb=0, ub=H, name=f"t_{b}")
                m.addConstr(tb >= e[b] + P[b] - D[b])
                tard.append(tb)
            m.setObjective(gp.quicksum(tard), GRB.MINIMIZE)
            for b in ids:
                e[b].Start = cur_entry[b]
            m.optimize()
            if m.SolCount < 1:
                continue
            new_tard = sum(max(0, int(round(e[b].X)) + P[b] - D[b]) for b in ids)
            if new_tard < cur_tard - 1e-9:
                for b in ids:
                    ev = int(round(e[b].X))
                    by_id[b]["entry_time"] = ev
                    by_id[b]["exit_time"] = ev + P[b]
                improved_any = True
        except gp.GurobiError:
            continue

    if not improved_any:
        return None
    out_flat = [dict(a) for by in out.values() for a in by.values()]
    return {"operations": _build_operations(out_flat)}


def _cumulative_leveled_redecode_verified(prob_info: dict, bays: list[Bay],
                                          results: dict,
                                          deadline: float | None = None,
                                          alpha: float = 0.9):
    """DEMAND-FLATTENED re-decode (the anti-stacking lever).

    Diagnosis (measured): on every train instance the per-bay CUMULATIVE area
    relaxation (drop 2D placement, keep only Sum(present footprint area) <= floor)
    has optimum tardiness 0 -- i.e. with the current assignment, the floor is NEVER
    truly over-subscribed once each block's due-date SLACK is used to spread its
    entry off the release-time peak.  All observed Z1 is the greedy decoder piling
    every block in at its release (instantaneous demand spikes to ~101% of floor)
    plus 2D packing fragmentation.

    Fix: per bay, solve the cumulative problem (CP-SAT, capacity = alpha*floor to
    leave packing slack) for the tardiness-minimising ENTRY targets t*_b, then
    RE-DECODE the bay in t*_b order with effective release = max(release, t*_b).
    Non-urgent blocks defer to their flattened slot, freeing the floor early for
    urgent ones.  Bay ASSIGNMENT is unchanged -> Z2,Z3 provably unchanged; only
    positions/orientations/times move.  Caller gates through the official checker
    (objective-safe)."""
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    blocks = prob_info["blocks"]
    now = time.monotonic()
    total_budget = max(0.0, (deadline - now)) if deadline is not None else 30.0
    if total_budget < 1.0:
        return None
    work = [(j, list(by)) for j, by in results.items() if by]
    if not work:
        return None
    # Alpha candidates (OGC_CUMLEVEL_ALPHAS, e.g. "90,85,80"; else the single arg).
    # Alpha is instance/bay-specific (measured: a85 helped prob_17 26->19 but hurt
    # prob_14 28->86), and single runs are noisy (+-20x), so trying several and
    # keeping the best per bay reduces BOTH alpha-sensitivity AND run variance.
    # Default widened 2026-06-08: more alpha candidates -> a stronger best-of.
    # cum_level is a deadline-bounded best-of (70% budget cap), so extra alphas
    # are only TRIED when time remains -> self-adaptive: neutral at short tl
    # (A/B tl=300 unchanged), big win at long tl (prob_13 10->1, prob_20 10->2 at
    # 30min, the eval server's max).  z1 was a time+search-breadth issue, not a floor.
    # Keep ALPHAS at 3: per_cum below divides the per-bay budget by len(alpha_list),
    # so MORE alphas STARVE every decode (this regressed prob_6/14 at tl=300).  The
    # extra search breadth that cracks the stuck large instances comes from
    # OGC_CUMLEVEL_ORDERS (the inner order loop is deadline-bounded with a FULL
    # per_cum each), not from more alphas.
    _alphas_env = os.environ.get("OGC_CUMLEVEL_ALPHAS", "90;85;80").strip()
    alpha_list = []
    if _alphas_env:
        for _sep in (";", "|", " "):
            _alphas_env = _alphas_env.replace(_sep, ",")
        for tok in _alphas_env.split(","):
            try:
                v = float(tok)
                v = v / 100.0 if v > 1.5 else v
                if 0.3 <= v <= 1.0:
                    alpha_list.append(v)
            except Exception:
                pass
    if not alpha_list:
        alpha_list = [alpha]
    # Size-gate: wider order search (5) only for LARGE instances (n>150), where the
    # stuck-z1 bays need it AND the eval server gives ample time -> prob_13 10->7,
    # prob_20 10->2 (with time).  Small instances keep 3: they already reach z1=0
    # with the narrow search, and the extra orders only added deadline-coupling
    # regression there (prob_6 n=150 went 0->1).  Env override still wins.
    _n_orders_default = 5 if len(prob_info["blocks"]) > 150 else 3
    _n_orders = max(1, _env_int("OGC_CUMLEVEL_ORDERS", _n_orders_default))

    def _cum_targets(ids, by_id, bay, _alpha, budget):
        cap = max(1, int(bay.width * bay.height * _alpha))
        m = cp_model.CpModel()
        H = (max(int(blocks[b]["due_date"]) for b in ids)
             + sum(int(blocks[b]["processing_time"]) for b in ids))
        e = {}; ivs = []; dem = []; tard = []
        for b in ids:
            a = by_id[b]; blk = blocks[b]
            blkobj = Block(block_id=b, block_data=blk,
                           x=a["x"], y=a["y"], orient_idx=a["orient_idx"])
            r = blkobj.bounding_rect()
            area = max(1, int((r[2] - r[0]) * (r[3] - r[1])))
            R = int(blk["release_time"]); P = int(blk["processing_time"])
            D = int(blk["due_date"])
            ev = m.NewIntVar(R, H, f"e{b}"); e[b] = ev
            xv = m.NewIntVar(R, H + P, f"x{b}")
            ivs.append(m.NewIntervalVar(ev, P, xv, f"i{b}"))
            dem.append(min(area, cap))
            tv = m.NewIntVar(0, H, f"t{b}"); m.Add(tv >= ev + P - D); tard.append(tv)
            m.AddHint(ev, int(a["entry_time"]))
        m.AddCumulative(ivs, dem, cap)
        m.Minimize(sum(tard))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = float(budget)
        s.parameters.num_search_workers = 4
        st = (s.Solve(m, _zero_obj_stopper(cp_model))
              if _CPSAT_ZERO_STOP else s.Solve(m))
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return {b: int(s.Value(e[b])) for b in ids}

    # OPT-IN parallel best-of (OGC_CUMLEVEL_PARALLEL): refine every tardy bay in
    # its OWN process, each against the full window (not a 1/n_bays slice), so the
    # eval server's 4 cores give ~Nbays x more attempts per wall-second.  Mirrors
    # the sequential logic; the caller's gate re-verifies, so a parallel failure or
    # a no-improvement result is a pure no-op (None -> fall through to sequential).
    if (_env_on("OGC_CUMLEVEL_PARALLEL", False) and run_parallel_cumlevel is not None
            and deadline is not None and len(work) >= 2):
        tardy_layouts = {}
        for j, ids in work:
            by_id = results[j]
            ct = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                     for b, a in by_id.items())
            if ct > 1e-9:
                tardy_layouts[j] = {b: dict(a) for b, a in by_id.items()}
        if len(tardy_layouts) >= 2:
            improved = run_parallel_cumlevel(
                prob_info, tardy_layouts, alpha_list, _n_orders, deadline,
                min(MAX_PARALLEL_WORKERS, len(tardy_layouts)))
            if improved is not None:
                out_flat = []
                for j, by in results.items():
                    src = improved.get(j) if improved.get(j) else by
                    for b in src:
                        out_flat.append(dict(src[b]))
                return {"operations": _build_operations(out_flat)} if out_flat else None

    out_flat = []
    n_remaining = len(work)
    _z1_run = None
    if _Z1_TRACE_ON:
        _z1_run = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                      for _j, _ in work for b, a in results[_j].items())
        _z1_mark(_z1_run)
    for j, ids in work:
        by_id = results[j]
        bay = bays[j]
        cur_tard = sum(max(0.0, int(a["exit_time"]) - blocks[b]["due_date"])
                       for b, a in by_id.items())
        now2 = time.monotonic()
        if cur_tard <= 1e-9 or (deadline is not None and now2 >= deadline - 0.5):
            for b in ids:
                out_flat.append(dict(by_id[b]))
            n_remaining -= 1
            continue
        # Fair per-bay wall slice so later bays are never starved by earlier ones.
        bay_slice = ((deadline - now2) / max(1, n_remaining)) if deadline else 30.0
        bay_deadline = (now2 + bay_slice) if deadline is not None else None
        bay_lb = _bay_tardiness_lb(ids, blocks)
        per_cum = max(1.0, min(8.0, bay_slice * 0.30 / len(alpha_list)))
        # Only accept a re-decode that BEATS this bay's current tardiness, so the
        # candidate is always <= current overall (gate still confirms).
        best_res = None; best_bt = cur_tard; _bay_prev = cur_tard
        for _alpha in alpha_list:
            if (bay_deadline is not None
                    and time.monotonic() >= bay_deadline - 0.2):
                break
            targets = _cum_targets(ids, by_id, bay, _alpha, per_cum)
            if targets is None:
                continue
            order_keys = [
                lambda b: (targets[b], blocks[b]["due_date"]),
                lambda b: (targets[b], blocks[b]["due_date"]
                           - blocks[b]["release_time"] - blocks[b]["processing_time"]),
                lambda b: (blocks[b]["due_date"], targets[b]),
                lambda b: (targets[b],
                           -_block_bbox(blocks[b], by_id[b]["orient_idx"])[2]
                           * _block_bbox(blocks[b], by_id[b]["orient_idx"])[3]),
            ][:_n_orders]
            for _key in order_keys:
                if (bay_deadline is not None
                        and time.monotonic() >= bay_deadline - 0.1):
                    break
                order = sorted(ids, key=_key)
                res, _forced = _decode_bay(
                    bay, j, order, blocks,
                    deadline=(deadline - 0.2) if deadline is not None else None,
                    release_override=targets,
                    fast_geom=_REDECODE_FAST or None,
                    exhaustive_pos=_env_on("OGC_CUMLEVEL_EXHAUSTIVE", False))
                if res is None or len(res) != len(ids):
                    continue
                bt = sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"])
                         for b in ids)
                if bt < best_bt:
                    best_bt = bt; best_res = res
                    if _z1_run is not None:
                        _z1_run += (bt - _bay_prev); _bay_prev = bt
                        _z1_mark(_z1_run)
                # This bay reached its proven tardiness lower bound -- no later order
                # can beat it, so stop re-decoding NOW.  Without this order-level break
                # the inner loop kept firing 2-3 more slow crane re-decodes per bay,
                # which is exactly what kept cum_level spinning ~20s AFTER global Z1
                # already hit 0 (prob_3: internal Z1=0 @43s but adopted @64s).  Pure
                # efficiency: best_res is unchanged, so objective-safe.  (OGC_ORDER_BREAK)
                if _ORDER_BREAK and best_bt <= bay_lb + 1e-9:
                    break
            if best_bt <= bay_lb + 1e-9:
                break
        if best_res is None:
            for b in ids:
                out_flat.append(dict(by_id[b]))
        else:
            for b in ids:
                out_flat.append(dict(best_res[b]))
        n_remaining -= 1
    if not out_flat:
        return None
    return {"operations": _build_operations(out_flat)}


def _flatten_decode_one_bay(prob_info, bay, bay_idx, ids, warm_entries,
                            alpha, n_orders, deadline):
    """Demand-flattened best-of re-decode of a bay's block set `ids` (used by the
    cross-bay relocate).  warm_entries: {block_id: entry hint} for the cumulative
    solve.  Returns the lowest-tardiness res dict {block_id: assignment} or None."""
    blocks = prob_info["blocks"]
    if not ids:
        return {}
    targets = {b: int(blocks[b]["release_time"]) for b in ids}
    try:
        from ortools.sat.python import cp_model
        cap = max(1, int(bay.width * bay.height * alpha))
        m = cp_model.CpModel()
        H = (max(int(blocks[b]["due_date"]) for b in ids)
             + sum(int(blocks[b]["processing_time"]) for b in ids))
        e = {}; ivs = []; dem = []; tard = []
        for b in ids:
            blk = blocks[b]
            ar = max(1, int(min(
                (_block_bbox(blk, oi)[2] - _block_bbox(blk, oi)[0])
                * (_block_bbox(blk, oi)[3] - _block_bbox(blk, oi)[1])
                for oi in range(len(blk["shape"])))))
            R = int(blk["release_time"]); P = int(blk["processing_time"])
            D = int(blk["due_date"])
            ev = m.NewIntVar(R, H, f"e{b}"); e[b] = ev
            xv = m.NewIntVar(R, H + P, f"x{b}")
            ivs.append(m.NewIntervalVar(ev, P, xv, f"i{b}")); dem.append(min(ar, cap))
            tv = m.NewIntVar(0, H, f"t{b}"); m.Add(tv >= ev + P - D); tard.append(tv)
            m.AddHint(ev, int(warm_entries.get(b, R)))
        m.AddCumulative(ivs, dem, cap); m.Minimize(sum(tard))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = 4.0
        s.parameters.num_search_workers = 2
        st = (s.Solve(m, _zero_obj_stopper(cp_model))
              if _CPSAT_ZERO_STOP else s.Solve(m))
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            targets = {b: int(s.Value(e[b])) for b in ids}
    except Exception:
        pass
    best_res = None; best_bt = math.inf
    okeys = [
        lambda b: (targets[b], blocks[b]["due_date"]),
        lambda b: (blocks[b]["due_date"], targets[b]),
        lambda b: (targets[b], blocks[b]["due_date"]
                   - blocks[b]["release_time"] - blocks[b]["processing_time"]),
    ][:max(1, n_orders)]
    for k in okeys:
        if deadline is not None and time.monotonic() >= deadline - 0.3:
            break
        order = sorted(ids, key=k)
        res, _f = _decode_bay(bay, bay_idx, order, blocks, deadline=deadline,
                              release_override=targets,
                              fast_geom=_REDECODE_FAST or None)
        if res is None or len(res) != len(ids):
            continue
        bt = sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"]) for b in ids)
        if bt < best_bt:
            best_bt = bt; best_res = res
    return best_res


def _tardy_crossbay_relocate_verified(prob_info: dict, bays: list[Bay],
                                      feasible_bays: list[list[int]],
                                      results: dict, bay_u: list[float],
                                      deadline: float | None = None,
                                      alpha: float = 0.9, max_moves: int = 12,
                                      use_bbox: bool = False):
    """Move worst-tardy blocks to a LESS-LOADED feasible bay, re-decoding both
    touched bays with demand-flattening, keeping a move iff the FULL objective
    improves.  Targets the measured pattern 'a cluster of tight blocks overloads
    one small bay while a big bay sits half-empty' (prob_17: bay3 84% tardy, bay1
    36% empty).  Surgical -- only the touched bays re-decode, so other bays keep
    their good packing (unlike wholesale _temporal_reassign).  Assignment changes
    (Z2/Z3 move) but w1 dominates ~3000x; the gate is on the full objective so it
    is objective-safe by construction."""
    blocks = prob_info["blocks"]
    n_bays = len(bays)
    if n_bays < 2:
        return None
    cur = {j: {b: dict(a) for b, a in by.items()} for j, by in results.items()}

    # CHEAP eval: every re-decoded bay is crane-safe by construction (via
    # _decode_bay -> _find_slot_crane_safe) and bays are independent, so the merged
    # solution is feasible; the closed-form objective (_obj_of_results) is exact for
    # it -- no per-trial check_feasibility (~0.8s each) needed.  The caller's gate
    # runs the OFFICIAL checker ONCE on the returned candidate, so any rare crane
    # edge case is still caught (candidate rejected = no-op).  This lets the loop do
    # MANY more moves -- needed to clear an OVER-100% bay (prob_13/15/18).
    def cheap_obj(state):
        try:
            return _obj_of_results(prob_info, state, bay_u)[0]  # [0]=weighted scalar
        except Exception:
            return math.inf

    base_obj = cheap_obj(cur)
    if not math.isfinite(base_obj):
        return None

    def bay_tard(jj):
        return sum(max(0, int(cur[jj][bb]["exit_time"]) - blocks[bb]["due_date"])
                   for bb in cur[jj])

    tardy = []
    for j, by in cur.items():
        for b, a in by.items():
            late = int(a["exit_time"]) - blocks[b]["due_date"]
            if late > 0:
                tardy.append((-late, b, j))
    tardy.sort()
    _xb_cands = max(1, _env_int("OGC_XBAY_CANDS", 2))
    improved = False
    moves = 0
    for _nl, b, cj in tardy:
        if moves >= max_moves:
            break
        if deadline is not None and time.monotonic() >= deadline - 1.5:
            break
        if b not in cur[cj]:
            continue
        cands = sorted([nj for nj in (feasible_bays[b] or list(range(n_bays)))
                        if nj != cj], key=bay_tard)
        for nj in cands[:(1 if use_bbox else _xb_cands)]:
            if deadline is not None and time.monotonic() >= deadline - 1.5:
                break
            src_ids = [bb for bb in cur[cj] if bb != b]
            dst_ids = list(cur[nj]) + [b]
            warm_dst = {bb: int(cur[nj][bb]["entry_time"]) for bb in cur[nj]}
            warm_dst[b] = int(blocks[b]["release_time"])
            _xb_half = ((deadline - time.monotonic())) if deadline is not None else 10.0
            # Source bay: just DROP b -- removing a block preserves crane-feasibility
            # and cannot increase the others' tardiness (b was only an obstacle), so
            # no re-decode needed.  Only the TARGET bay is re-decoded.  Halves the
            # per-move cost -> ~2x more moves in budget (needed to clear a heavily
            # over-100% bay).  cpsat_timing later pulls the freed source blocks early.
            rc = {bb: dict(cur[cj][bb]) for bb in src_ids}
            if use_bbox:
                # bbox-aware: pack the TARGET bay with the 2D solver so a block
                # relocated into a roomy bay lands ON-TIME (the greedy decode mis-
                # judges it as tardy and rejects the move -- the cause of prob_20's
                # bay1=154% staying overloaded).  Budget-capped per move.
                rn = _bbox_pack_bay(prob_info, bays[nj], nj, dst_ids,
                                    min(8.0, max(1.0, _xb_half)),
                                    warm={bb: cur[nj][bb] for bb in cur[nj]})
            else:
                rn = _flatten_decode_one_bay(prob_info, bays[nj], nj, dst_ids,
                                             warm_dst, alpha, 2,
                                             time.monotonic() + _xb_half)
            if rc is None or rn is None:
                continue
            trial = {jj: {bb: dict(aa) for bb, aa in by.items()}
                     for jj, by in cur.items()}
            trial[cj] = rc; trial[nj] = rn
            o = cheap_obj(trial)
            if o < base_obj - 1e-9:
                cur = trial; base_obj = o
                improved = True; moves += 1
                break

    # Batch bay-clearing (OGC_XBAY_BATCH): the greedy one-block loop above stalls
    # in a local minimum when moving a single block off an OVER-100% bay just
    # shuffles its tardiness to the target (no net gain), so prob_15/18 don't clear.
    # Here we relocate the worst-tardy blocks off the most-tardy bay one-by-one,
    # accumulating THROUGH non-improving intermediates, and keep the prefix giving
    # the lowest objective.  cheap_obj makes this affordable.
    # DEFAULT ON (2026-06-08): full-20 A/B at tl=300 -> prob_12 z1 3->1, ZERO
    # regression on any instance (all 16 z1=0 stay 0, incl. prob_18 which the old
    # 06-07 note flagged 50->102 -- that starvation is obsolete now that cum_level
    # runs FIRST + capped, so this batch step inside crossbay can't starve it).
    # Objective-safe: the final candidate is gated by the caller's official checker.
    if _env_on("OGC_XBAY_BATCH", True):
        for _pass in range(4):
            if deadline is not None and time.monotonic() >= deadline - 1.5:
                break
            over_j = max(cur, key=bay_tard)
            if bay_tard(over_j) <= 1e-9:
                break
            over_tardy = sorted(
                ((int(cur[over_j][bb]["exit_time"]) - blocks[bb]["due_date"], bb)
                 for bb in cur[over_j]
                 if int(cur[over_j][bb]["exit_time"]) > blocks[bb]["due_date"]),
                reverse=True)
            if not over_tardy:
                break
            trial = {jj: {bb: dict(aa) for bb, aa in by.items()}
                     for jj, by in cur.items()}
            best_prefix_obj = base_obj
            best_prefix_state = None
            for _late, bb in over_tardy:
                if deadline is not None and time.monotonic() >= deadline - 1.5:
                    break
                tcands = sorted(
                    [nj for nj in (feasible_bays[bb] or list(range(n_bays)))
                     if nj != over_j],
                    key=lambda jj: sum(max(0, int(trial[jj][x]["exit_time"])
                                           - blocks[x]["due_date"])
                                       for x in trial[jj]))
                if not tcands:
                    continue
                nj = tcands[0]
                src_ids = [x for x in trial[over_j] if x != bb]
                dst_ids = list(trial[nj]) + [bb]
                wsrc = {x: int(trial[over_j][x]["entry_time"]) for x in src_ids}
                wdst = {x: int(trial[nj][x]["entry_time"]) for x in trial[nj]}
                wdst[bb] = int(blocks[bb]["release_time"])
                half = (((deadline - time.monotonic()) / 2.0)
                        if deadline is not None else 10.0)
                rc = _flatten_decode_one_bay(prob_info, bays[over_j], over_j,
                                             src_ids, wsrc, alpha, 2,
                                             time.monotonic() + half)
                rn = _flatten_decode_one_bay(prob_info, bays[nj], nj, dst_ids,
                                             wdst, alpha, 2,
                                             time.monotonic() + half)
                if rc is None or rn is None:
                    continue
                trial[over_j] = rc
                trial[nj] = rn
                o = cheap_obj(trial)
                if o < best_prefix_obj - 1e-9:
                    best_prefix_obj = o
                    best_prefix_state = {jj: {b2: dict(aa) for b2, aa in by.items()}
                                         for jj, by in trial.items()}
            if best_prefix_state is not None:
                cur = best_prefix_state
                base_obj = best_prefix_obj
                improved = True
            else:
                break

    if not improved:
        return None
    flat = [a for by in cur.values() for a in by.values()]
    return {"operations": _build_operations(flat)}


_COVER_CACHE: dict = {}


def _block_cover(blk, oi, n_slabs):
    """Rectilinear (horizontal/vertical-slab) cover of a block's footprint, in the
    SAME local frame as _block_bbox (offsets relative to the reference point).

    Returns a list of integer (x0,y0,x1,y1) rectangles whose union CONTAINS the
    true footprint polygon (outward-rounded -> conservative, so bbox-style
    disjointness of covers still implies polygon disjointness and the official
    checker confirms feasibility).  Tighter than a single bbox for tapered/wedge
    shapes -> recovers reserved-but-empty space so more blocks co-reside in time.

    Falls back to the single integer bbox on near-rectangular shapes, when
    n_slabs<=1, or on ANY error (so this can never break or loosen the packer).
    Adaptive: near-rectangular blocks stay 1 rect to keep the CP-SAT lean."""
    import math as _m
    key = (id(blk), oi, n_slabs)
    cached = _COVER_CACHE.get(key)
    if cached is not None:
        return cached
    bb = _block_bbox(blk, oi)
    bbox_rect = [(int(_m.floor(bb[0])), int(_m.floor(bb[1])),
                  int(_m.ceil(bb[2])), int(_m.ceil(bb[3])))]
    cover = bbox_rect
    if n_slabs and n_slabs >= 2:
        try:
            from shapely.geometry import box as _box, Polygon as _Poly
            from shapely.ops import unary_union as _uu
            layers = _resolve_layers(blk["shape"][oi]["layers"])
            polys = []
            for layer in layers:
                if len(layer) >= 3:
                    p = _Poly(layer)
                    if not p.is_valid:
                        p = p.buffer(0)
                    if p.area > 0:
                        polys.append(p)
            if polys:
                poly = _uu(polys)
                minx, miny, maxx, maxy = poly.bounds
                bbox_area = (maxx - minx) * (maxy - miny)
                if bbox_area > 0 and poly.area / bbox_area < 0.90:
                    def _band(axis):
                        bands = []
                        for s in range(n_slabs):
                            if axis == "h":
                                lo = miny + (maxy - miny) * s / n_slabs
                                hi = miny + (maxy - miny) * (s + 1) / n_slabs
                                clip = poly.intersection(
                                    _box(minx - 1, lo, maxx + 1, hi))
                                if clip.is_empty:
                                    continue
                                cx0, _, cx1, _ = clip.bounds
                                bands.append([int(_m.floor(cx0)), int(_m.floor(lo)),
                                              int(_m.ceil(cx1)), int(_m.ceil(hi))])
                            else:
                                lo = minx + (maxx - minx) * s / n_slabs
                                hi = minx + (maxx - minx) * (s + 1) / n_slabs
                                clip = poly.intersection(
                                    _box(lo, miny - 1, hi, maxy + 1))
                                if clip.is_empty:
                                    continue
                                _, cy0, _, cy1 = clip.bounds
                                bands.append([int(_m.floor(lo)), int(_m.floor(cy0)),
                                              int(_m.ceil(hi)), int(_m.ceil(cy1))])
                        if not bands:
                            return None
                        merged = [bands[0]]
                        for bd in bands[1:]:
                            last = merged[-1]
                            if axis == "h" and bd[0] == last[0] and bd[2] == last[2]:
                                last[3] = bd[3]
                            elif axis == "v" and bd[1] == last[1] and bd[3] == last[3]:
                                last[2] = bd[2]
                            else:
                                merged.append(bd)
                        return [tuple(b) for b in merged]
                    ch = _band("h")
                    cv = _band("v")
                    cands = [c for c in (ch, cv) if c]
                    if cands:
                        _area = lambda c: sum((x1 - x0) * (y1 - y0)
                                              for x0, y0, x1, y1 in c)
                        best = min(cands, key=_area)
                        # only adopt if it is actually tighter than the bbox
                        if _area(best) < _area(bbox_rect):
                            cover = best
        except Exception:
            cover = bbox_rect
    _COVER_CACHE[key] = cover
    return cover


def _bbox_pack_bay(prob_info, bay, bay_idx, ids, budget, warm=None, n_slabs=1):
    """Per-bay 2D bbox-packing-over-time via CP-SAT (the combined-packing lever).

    Picks each block's reference (x, y) + ENTRY so that footprints are DISJOINT
    whenever the blocks overlap in time.  Footprint-disjoint => no collision AND no
    crane j>=k conflict (both require footprint overlap), so the placement is fully
    crane-feasible.  bbox is conservative (bbox-disjoint => polygon-disjoint), so
    the official checker confirms feasibility.  Each block is fixed to its min-area
    orientation.  Unlike the greedy decode (myopic, one block at a time, fragments
    the target bay so a relocated block lands tardy), this optimises the WHOLE bay
    layout+timing jointly -> places blocks on-time where room exists.  Returns a res
    dict {block_id: assignment} or None (doesn't fit / no feasible solve)."""
    import math as _m
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    blocks = prob_info["blocks"]
    W = int(bay.width); H = int(bay.height)
    ids = list(ids)
    if not ids:
        return {}
    info = {}
    for b in ids:
        blk = blocks[b]
        best = None
        for oi in range(len(blk["shape"])):
            bb = _block_bbox(blk, oi)
            w = bb[2] - bb[0]; h = bb[3] - bb[1]
            if w <= W + 1e-6 and h <= H + 1e-6:
                area = w * h
                if best is None or area < best[-1]:
                    best = (oi, bb, area)
        if best is None:
            return None
        info[b] = best
    def _bay_tard(res):
        if not res:
            return float("inf")
        return sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"]) for b in ids)

    def _solve(force_slabs, sub_budget, warm_layout):
        """One CP-SAT solve of the bay layout+timing.  force_slabs>=2 uses the
        conservative rectilinear (slab) cover footprint (union >= polygon -> still
        official-safe); force_slabs<=1 uses the single bbox (the proven packer).
        Returns res dict or None."""
        try:
            if sub_budget <= 0.05:
                return None
            m = cp_model.CpModel()
            Ht = (max(int(blocks[b]["due_date"]) for b in ids)
                  + sum(int(blocks[b]["processing_time"]) for b in ids))
            e = {}; fx0 = {}; fx1 = {}; fy0 = {}; fy1 = {}; rxv = {}; ryv = {}
            covers = {}
            tard = []
            for b in ids:
                oi, bb, _ = info[b]
                loX = int(_m.ceil(-bb[0])); hiX = int(_m.floor(W - bb[2]))
                loY = int(_m.ceil(-bb[1])); hiY = int(_m.floor(H - bb[3]))
                if hiX < loX or hiY < loY:
                    return None
                R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
                D = int(blocks[b]["due_date"])
                rx = m.NewIntVar(loX, hiX, f"rx{b}"); ry = m.NewIntVar(loY, hiY, f"ry{b}")
                ev = m.NewIntVar(R, Ht, f"e{b}")
                rxv[b] = rx; ryv[b] = ry; e[b] = ev
                # Conservative integer footprint edges (outward rounding -> safe).
                fx0[b] = rx + int(_m.floor(bb[0])); fx1[b] = rx + int(_m.ceil(bb[2]))
                fy0[b] = ry + int(_m.floor(bb[1])); fy1[b] = ry + int(_m.ceil(bb[3]))
                if force_slabs >= 2:
                    cov = _block_cover(blocks[b], oi, force_slabs)
                    covers[b] = cov if (cov and len(cov) >= 2) else None
                tv = m.NewIntVar(0, Ht, f"t{b}"); m.Add(tv >= ev + P - D); tard.append(tv)
                if warm_layout and b in warm_layout:
                    try:
                        m.AddHint(ev, int(warm_layout[b]["entry_time"]))
                        m.AddHint(rx, int(warm_layout[b]["x"]))
                        m.AddHint(ry, int(warm_layout[b]["y"]))
                    except Exception:
                        pass
            for ia in range(len(ids)):
                a = ids[ia]; Pa = int(blocks[a]["processing_time"])
                for ib in range(ia + 1, len(ids)):
                    b = ids[ib]; Pb = int(blocks[b]["processing_time"])
                    tb = m.NewBoolVar(""); bt = m.NewBoolVar("")
                    m.Add(e[a] + Pa <= e[b]).OnlyEnforceIf(tb)
                    m.Add(e[b] + Pb <= e[a]).OnlyEnforceIf(bt)
                    ca = covers.get(a) if force_slabs >= 2 else None
                    cb = covers.get(b) if force_slabs >= 2 else None
                    if ca is None and cb is None:
                        # single-bbox path (byte-identical to the proven packer)
                        la = m.NewBoolVar(""); ra = m.NewBoolVar("")
                        bel = m.NewBoolVar(""); abv = m.NewBoolVar("")
                        m.Add(fx1[a] <= fx0[b]).OnlyEnforceIf(la)
                        m.Add(fx1[b] <= fx0[a]).OnlyEnforceIf(ra)
                        m.Add(fy1[a] <= fy0[b]).OnlyEnforceIf(bel)
                        m.Add(fy1[b] <= fy0[a]).OnlyEnforceIf(abv)
                        m.AddBoolOr([la, ra, bel, abv, tb, bt])
                    else:
                        # slab path: a,b footprint-disjoint iff EVERY cover-rect
                        # pair is separated.  sd => all rect pairs separated;
                        # top-level OR allows time-separation as the alternative.
                        ra_list = ca if ca else [(int(_m.floor(info[a][1][0])),
                                                  int(_m.floor(info[a][1][1])),
                                                  int(_m.ceil(info[a][1][2])),
                                                  int(_m.ceil(info[a][1][3])))]
                        rb_list = cb if cb else [(int(_m.floor(info[b][1][0])),
                                                  int(_m.floor(info[b][1][1])),
                                                  int(_m.ceil(info[b][1][2])),
                                                  int(_m.ceil(info[b][1][3])))]
                        sd = m.NewBoolVar("")
                        for (ax0, ay0, ax1, ay1) in ra_list:
                            for (bx0, by0, bx1, by1) in rb_list:
                                l = m.NewBoolVar(""); r = m.NewBoolVar("")
                                be = m.NewBoolVar(""); ab = m.NewBoolVar("")
                                m.Add(rxv[a] + ax1 <= rxv[b] + bx0).OnlyEnforceIf(l)
                                m.Add(rxv[b] + bx1 <= rxv[a] + ax0).OnlyEnforceIf(r)
                                m.Add(ryv[a] + ay1 <= ryv[b] + by0).OnlyEnforceIf(be)
                                m.Add(ryv[b] + by1 <= ryv[a] + ay0).OnlyEnforceIf(ab)
                                m.AddBoolOr([l, r, be, ab]).OnlyEnforceIf(sd)
                        m.AddBoolOr([tb, bt, sd])
            m.Minimize(sum(tard))
            s = cp_model.CpSolver()
            s.parameters.max_time_in_seconds = float(max(0.1, sub_budget))
            s.parameters.num_search_workers = 4
            st = s.Solve(m)
            if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None
            res = {}
            for b in ids:
                oi, bb, _ = info[b]
                ev = int(s.Value(e[b])); P = int(blocks[b]["processing_time"])
                res[b] = {"block_id": b, "bay_id": bay_idx,
                          "x": int(s.Value(rxv[b])), "y": int(s.Value(ryv[b])),
                          "orient_idx": oi, "entry_time": ev, "exit_time": ev + P}
            return res
        except Exception:
            return None

    # Single-mode solve.  n_slabs<=1 -> the proven single-bbox packer (default,
    # used by the fast bbox_pack stage and cross-bay move evaluation).  n_slabs>=2
    # -> the polygon-tight slab cover, used ONLY by the dedicated slab refinement
    # stage (_slab_pack_redecode_verified) so it never competes with bbox for the
    # same budget slice.  Both are objective-safe (gated downstream).
    return _solve(max(1, int(n_slabs)), float(budget), warm)


def _bay_min_area_orient(blk, W, H):
    """min-bbox-area orientation that fits W x H (matches _bbox_pack_bay)."""
    best = None
    for oi in range(len(blk["shape"])):
        bb = _block_bbox(blk, oi)
        w = bb[2] - bb[0]; h = bb[3] - bb[1]
        if w <= W + 1e-6 and h <= H + 1e-6:
            a = w * h
            if best is None or a < best[1]:
                best = (oi, a, bb)
    return best


def _bay_wants_slab(prob_info, ids, bay, slab_n, max_blocks=110):
    """Route a tardy bay to the SLAB packer or the fast BBOX packer.

    Signal: the all-present-at-[release,due] BBOX area-demand peak (each block
    occupying its widest on-time window [release, due]).  When that peak fits the
    bay (<= 100%), bbox can already pack the bay to 0 tardiness, so the fast bbox
    packer suffices -- using slab's slower model there only regresses easy bays
    (measured prob_6 0->15, prob_9 0->2: all their bays are <=99%).  Only when
    bbox OVER-fills the bay (> 100%) is the polygon's recovered space the deciding
    lever (prob_13 bay3 = 124% -> slab 9->1).  A size cap keeps slab off bays too
    large for its heavier model to solve within budget.

    (Note: we do NOT also require the cover demand to fit -- the [release,due]
    peak is an over-estimate since real packing staggers entry/exit, so a bay can
    pack to 0 even at >100% demand; prob_13 bay3's cover demand is 115% yet slab
    drives it to ~1.)"""
    if slab_n < 2 or len(ids) > max_blocks:
        return False
    blocks = prob_info["blocks"]
    W = int(bay.width); H = int(bay.height)
    area = W * H
    if area <= 0:
        return False
    ev_bb = []
    for b in ids:
        blk = blocks[b]
        ch = _bay_min_area_orient(blk, W, H)
        if ch is None:
            return False
        oi, bbox_a, _bb = ch
        s = blk["release_time"]; e = blk["due_date"]
        if e <= s:
            e = s + max(1, blk["processing_time"])
        ev_bb.append((s, bbox_a)); ev_bb.append((e, -bbox_a))

    def _peak(ev):
        ev = sorted(ev, key=lambda x: (x[0], x[1]))  # removals (neg) before adds
        cur = pk = 0.0
        for (_t, da) in ev:
            cur += da
            pk = max(pk, cur)
        return pk
    return _peak(ev_bb) > area * (_env_int("OGC_SLAB_PCT", 100) / 100.0)


def _bbox_pack_redecode_verified(prob_info: dict, bays: list[Bay], results: dict,
                                 deadline: float | None = None,
                                 best_of_slab: bool = False):
    """Re-pack each TARDY bay with the per-bay CP-SAT, keep per bay iff it lowers
    that bay's tardiness (candidate <= current; the outer gate confirms).

    best_of_slab=False -> the proven single-bbox packer everywhere (used for
    cross-bay move evaluation, where speed matters).

    best_of_slab=True (OGC_SLAB_PACK) -> ROUTE each bay (via _bay_wants_slab) to
    EITHER the fast bbox packer OR the polygon-tight slab cover, each with the
    full per-bay budget.  slab is strictly more capable than bbox (cover footprint
    subset of bbox) but its heavier model is slower, so applying it blindly
    regresses easy bays (prob_6 0->15, prob_9 0->2) where bbox already reaches 0
    fast.  Routing pays for slab ONLY on tight bays it can actually help (bbox
    over-fills, polygon fits) -> prob_11/13/14/15 -> Z1=0 with no easy-bay
    regression and no prob_20 instability."""
    blocks = prob_info["blocks"]
    slab_n = _env_int("OGC_SLAB_N", 3) if best_of_slab else 1
    work = [(j, list(by)) for j, by in results.items() if by]
    if not work:
        return None
    now = time.monotonic()
    total = max(0.0, (deadline - now)) if deadline is not None else 30.0
    if total < 1.0:
        return None
    todo = []
    for j, ids in work:
        ct = sum(max(0.0, int(results[j][b]["exit_time"]) - blocks[b]["due_date"])
                 for b in ids)
        if ct > 1e-9:
            todo.append((j, ids, ct))
    if not todo:
        return None
    per_bay = max(2.0, total / len(todo))
    out_flat = []
    improved = False

    def _tard(res, ids):
        return sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"]) for b in ids)

    bestof = _env_on("OGC_SLAB_BESTOF", False)
    for j, ids, ct in todo:
        if deadline is not None and time.monotonic() >= deadline - 0.5:
            for b in ids:
                out_flat.append(dict(results[j][b]))
            continue
        warm = {b: results[j][b] for b in ids}
        budget = min(per_bay, (deadline - time.monotonic())
                     if deadline is not None else per_bay)
        if bestof and slab_n >= 2:
            # HALF-BUDGET best-of (OGC_SLAB_BESTOF): run BOTH the fast bbox cover (n=1)
            # and the polygon-tight slab cover (n=slab_n), each with HALF the bay budget
            # so NEITHER starves the other, and keep the lower-tardiness result.  Half a
            # (large) per-bay budget is ample for a single bay, so this fixes BOTH
            # failure modes at once: the _bay_wants_slab MIS-ROUTE (prob_13: keeps bbox's
            # ~10 over slab's ~27) AND the run-both budget starvation (prob_6/9: keep
            # slab's 0, not a starved bbox's 15).
            res = None; best_nt = math.inf
            half = budget * 0.5
            for nn in (1, slab_n):
                rem = ((deadline - time.monotonic())
                       if deadline is not None else half)
                bj = min(half, rem)
                if bj <= 0.3:
                    break
                r = _bbox_pack_bay(prob_info, bays[j], j, ids, bj,
                                   warm=warm, n_slabs=nn)
                if r is not None and len(r) == len(ids):
                    rt = _tard(r, ids)
                    if rt < best_nt - 1e-9:
                        best_nt, res = rt, r
        else:
            # Route this bay to slab only where it genuinely helps (else fast bbox).
            use_n = slab_n if (slab_n >= 2 and
                               _bay_wants_slab(prob_info, ids, bays[j], slab_n)) else 1
            res = _bbox_pack_bay(prob_info, bays[j], j, ids, budget,
                                 warm=warm, n_slabs=use_n)
        if res is not None and len(res) == len(ids):
            nt = _tard(res, ids)
            if nt < ct - 1e-9:
                for b in ids:
                    out_flat.append(dict(res[b]))
                improved = True
                continue
        for b in ids:
            out_flat.append(dict(results[j][b]))
    # untouched (non-tardy) bays
    done = {j for j, _ids, _ct in todo}
    for j, by in results.items():
        if j not in done:
            for b in by:
                out_flat.append(dict(by[b]))
    if not improved or not out_flat:
        return None
    return {"operations": _build_operations(out_flat)}


def _temporal_reassign_redecode_verified(prob_info: dict, bays: list[Bay],
                                         feasible_bays: list[list[int]],
                                         results: dict, bay_u: list[float],
                                         deadline: float | None = None,
                                         alpha: float = 0.9):
    """Temporal-demand-aware REASSIGNMENT + flattened re-decode.

    Diagnosis (measured): some instances are ASSIGNMENT-limited, not packing-
    limited.  prob_20's current assignment has per-bay cumulative area LB = 62
    (no packing can beat it), yet the GLOBAL optimum over ALL assignments is 0.
    The ALNS evaluates assignment moves with the greedy (packing-pessimistic)
    decode, so it never finds the demand-balanced assignment.

    This solves the combined ASSIGNMENT + area-cumulative SCHEDULING relaxation
    with CP-SAT: pick bay x[b,j] and entry[b] so each bay's footprint-area demand
    stays <= alpha*floor at every instant, minimising w1*tardiness + w2*Z2 +
    w3*Z3.  The balanced assignment + entry targets are then DECODED in 2D
    (flattened, release_override).  The assignment may CHANGE (Z2/Z3 move), but w1
    dominates (~3000x), so the caller's gate adopts iff the FULL objective
    improves -- objective-safe by construction."""
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    blocks = prob_info["blocks"]
    n_blocks = len(blocks); n_bays = len(bays)
    if n_bays < 2 or n_blocks == 0:
        return None
    now = time.monotonic()
    budget = max(0.0, (deadline - now)) if deadline is not None else 30.0
    if budget < 4.0:
        return None
    w = prob_info.get("weights", {})
    w1 = max(1, int(round(w.get("w1", 1))))
    w2 = max(1, int(round(w.get("w2", 1))))
    w3 = max(1, int(round(w.get("w3", 1))))

    minarea = {}; R = {}; P = {}; D = {}; workload = {}; smax = {}; pref = {}
    for b in range(n_blocks):
        best = math.inf
        for oi in range(len(blocks[b]["shape"])):
            bb = _block_bbox(blocks[b], oi)
            best = min(best, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        minarea[b] = max(1, int(best))
        R[b] = int(blocks[b]["release_time"]); P[b] = int(blocks[b]["processing_time"])
        D[b] = int(blocks[b]["due_date"]); workload[b] = int(round(blocks[b]["workload"]))
        pr = blocks[b]["bay_preferences"]; smax[b] = max(pr); pref[b] = pr

    cur_assign = {}; cur_entry = {}
    for j, by in results.items():
        for b, a in by.items():
            cur_assign[b] = j; cur_entry[b] = int(a["entry_time"])

    m = cp_model.CpModel()
    H = max(D.values()) + sum(P.values())
    x = {}; entry = {}; end = {}
    for b in range(n_blocks):
        fb = feasible_bays[b] or list(range(n_bays))
        for j in fb:
            x[b, j] = m.NewBoolVar(f"x{b}_{j}")
        m.Add(sum(x[b, j] for j in fb) == 1)
        entry[b] = m.NewIntVar(R[b], H, f"e{b}")
        end[b] = m.NewIntVar(R[b] + P[b], H + P[b], f"x{b}e")
        m.Add(end[b] == entry[b] + P[b])

    bay_blocks = {j: [] for j in range(n_bays)}
    for b in range(n_blocks):
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x:
                bay_blocks[j].append(b)
    for j in range(n_bays):
        ivs = []; dems = []
        for b in bay_blocks[j]:
            ivs.append(m.NewOptionalIntervalVar(entry[b], P[b], end[b],
                                                x[b, j], f"iv{b}_{j}"))
            dems.append(minarea[b])
        if ivs:
            cap = max(1, int(bays[j].width * bays[j].height * alpha))
            m.AddCumulative(ivs, dems, cap)

    T = []
    for b in range(n_blocks):
        tb = m.NewIntVar(0, H, f"t{b}")
        m.Add(tb >= entry[b] + P[b] - D[b])
        T.append(tb)

    U = [int(round(bay_u[j] * 1000)) for j in range(n_bays)]
    wsum = sum(workload.values()) + 1
    wl = []
    for j in range(n_bays):
        terms = [workload[b] * U[j] * x[b, j] for b in bay_blocks[j]]
        v = m.NewIntVar(0, wsum * (max(U) + 1), f"wl{j}")
        m.Add(v == sum(terms)); wl.append(v)
    hi = m.NewIntVar(0, wsum * (max(U) + 1), "hi")
    lo = m.NewIntVar(0, wsum * (max(U) + 1), "lo")
    m.AddMaxEquality(hi, wl); m.AddMinEquality(lo, wl)
    z2 = m.NewIntVar(0, wsum * (max(U) + 1), "z2"); m.Add(z2 == hi - lo)
    z3_terms = []
    for b in range(n_blocks):
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x:
                pen = smax[b] - pref[b][j]
                if pen:
                    z3_terms.append(pen * x[b, j])
    # True objective is w1*Z1 + w2*Z2 + w3*Z3.  z2 here is 1000*Z2 (U=1000*bay_u),
    # so scale all by 1000 to stay integer: 1000*w1*Z1 + w2*z2 + 1000*w3*Z3.
    m.Minimize(1000 * w1 * sum(T) + w2 * z2 + 1000 * w3 * sum(z3_terms))

    for b in range(n_blocks):
        j = cur_assign.get(b)
        if j is not None and (b, j) in x:
            m.AddHint(x[b, j], 1)
        m.AddHint(entry[b], cur_entry.get(b, R[b]))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(2.0, budget * 0.6)
    s.parameters.num_search_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    new_assign = {}; targets = {}
    for b in range(n_blocks):
        chosen = None
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x and s.Value(x[b, j]) == 1:
                chosen = j; break
        if chosen is None:
            return None
        new_assign[b] = chosen; targets[b] = int(s.Value(entry[b]))

    by_bay = {j: [] for j in range(n_bays)}
    for b in range(n_blocks):
        by_bay[new_assign[b]].append(b)
    out_flat = []
    dec_dl = (deadline - 0.2) if deadline is not None else None
    for j in range(n_bays):
        ids = by_bay[j]
        if not ids:
            continue
        order = sorted(ids, key=lambda b: (targets[b], D[b]))
        res, _f = _decode_bay(bays[j], j, order, blocks, deadline=dec_dl,
                              release_override=targets)
        if res is None or len(res) != len(ids):
            return None
        for b in ids:
            out_flat.append(dict(res[b]))
    if len(out_flat) != n_blocks:
        return None
    return {"operations": _build_operations(out_flat)}


def _pull_forward_exits_fixed_layout(prob_info: dict, bays: list[Bay],
                                     results: dict,
                                     deadline: float | None = None):
    """Keep bay/x/y/orientation/ENTRY fixed; move EXIT earlier when crane-safe.

    Removing a block earlier can only relax future entry/collision constraints.
    The only new risk is the new EXIT event itself, so each proposed pull is
    checked with check_exit against the bay state at that time.  We use at most
    one pulled exit per bay/time tick to avoid relying on same-time EXIT ordering
    inside _build_operations.
    """
    out = {j: {b: dict(a) for b, a in by.items()} for j, by in results.items()}
    for j, by_id in out.items():
        if deadline is not None and time.monotonic() >= deadline:
            return None
        if not by_id:
            continue
        bay = bays[j]
        blocks_at = {
            b: Block(block_id=b, block_data=prob_info["blocks"][b],
                     x=a["x"], y=a["y"], orient_idx=a["orient_idx"])
            for b, a in by_id.items()
        }
        exit_count: dict[int, int] = {}
        for a in by_id.values():
            t = int(a["exit_time"])
            exit_count[t] = exit_count.get(t, 0) + 1

        min_t = min(int(a["entry_time"] + prob_info["blocks"][b]["processing_time"])
                    for b, a in by_id.items())
        max_t = max(int(a["exit_time"]) for a in by_id.values())
        for t in range(min_t, max_t + 1):
            if deadline is not None and time.monotonic() >= deadline:
                return None
            if exit_count.get(t, 0) > 0:
                continue
            candidates = []
            for b, a in by_id.items():
                blk = prob_info["blocks"][b]
                ready = int(a["entry_time"] + blk["processing_time"])
                old_exit = int(a["exit_time"])
                if ready <= t < old_exit and int(a["entry_time"]) < t:
                    old_late = max(0, old_exit - blk["due_date"])
                    new_late = max(0, t - blk["due_date"])
                    if old_late > new_late:
                        candidates.append((blk["due_date"], -old_late, old_exit, b))
            if not candidates:
                continue
            candidates.sort()
            for _due, _neg_late, old_exit, b in candidates:
                target = blocks_at[b]
                present = [target]
                for other, a_o in by_id.items():
                    if other == b:
                        continue
                    if int(a_o["entry_time"]) < t < int(a_o["exit_time"]):
                        present.append(blocks_at[other])
                if check_exit(bay, present, target, fast=True):
                    continue
                by_id[b]["exit_time"] = int(t)
                exit_count[old_exit] = max(0, exit_count.get(old_exit, 0) - 1)
                if exit_count[old_exit] == 0:
                    exit_count.pop(old_exit, None)
                exit_count[t] = exit_count.get(t, 0) + 1
                break

    flat = [a for by in out.values() for a in by.values()]
    return {"operations": _build_operations(flat)}


def _shift_tardy_intervals_verified(prob_info: dict, base_results: dict,
                                    base_obj: float,
                                    deadline: float,
                                    max_blocks: int = 18,
                                    max_times: int = 14):
    """Verified one-block interval shifts for tardy blocks.

    Geometry and bay assignment stay fixed.  For the worst tardy blocks, try an
    earlier [ENTRY, ENTRY+P] interval and keep it only if the official checker
    confirms feasibility and strict objective improvement.  This is expensive
    relative to a pure local key, so it is small and deadline-bounded.
    """
    try:
        cur = {j: {b: dict(a) for b, a in by.items()}
               for j, by in base_results.items()}
        cur_obj = float(base_obj)
        improved = False
        blocks = prob_info["blocks"]

        def _flat(res):
            return [a for by in res.values() for a in by.values()]

        tardy = []
        for j, by in cur.items():
            for b, a in by.items():
                late = int(a["exit_time"]) - int(blocks[b]["due_date"])
                if late > 0:
                    tardy.append((late, b, j))
        tardy.sort(reverse=True)

        for _late, b, j in tardy[:max_blocks]:
            if time.monotonic() >= deadline:
                break
            a0 = cur[j][b]
            blk = blocks[b]
            proc = int(blk["processing_time"])
            old_entry = int(a0["entry_time"])
            old_exit = int(a0["exit_time"])
            lo = int(blk["release_time"])
            hi = min(old_entry - 1, old_exit - proc - 1)
            if hi < lo:
                continue
            seeds = {lo, hi, int(blk["due_date"]) - proc}
            if hi > lo and max_times > 3:
                for q in range(max_times - 3):
                    seeds.add(lo + int(round((hi - lo) * (q + 1) / (max_times - 2))))
            times = sorted(t for t in seeds if lo <= t <= hi)
            for t in times:
                if time.monotonic() >= deadline:
                    break
                cand = {jj: {bb: dict(aa) for bb, aa in by.items()}
                        for jj, by in cur.items()}
                cand[j][b]["entry_time"] = int(t)
                cand[j][b]["exit_time"] = int(t + proc)
                sol = {"operations": _build_operations(_flat(cand))}
                try:
                    rep = check_feasibility(prob_info, sol)
                except Exception:
                    continue
                if (rep.get("feasible") and rep.get("objective") is not None
                        and rep["objective"] < cur_obj - 1e-9):
                    cur = cand
                    cur_obj = float(rep["objective"])
                    improved = True
                    break
        if not improved:
            return None
        return {"operations": _build_operations(_flat(cur))}, cur_obj
    except Exception:
        return None


def _tardy_redecode_moves_verified(prob_info: dict, bays: list[Bay],
                                   base_results: dict, bay_u: list[float],
                                   base_obj: float, deadline: float,
                                   max_blocks: int = 10,
                                   max_adopt: int = 3):
    """Move worst tardy blocks to another bay and re-decode both touched bays.

    This is the expensive but direct CRANE repair: assignment changes are tested
    by rebuilding the source and target bay with the crane-safe decoder, then
    passing the whole solution through the official checker.  Only strict
    objective improvements are adopted.
    """
    try:
        cur = {j: {b: dict(a) for b, a in by.items()}
               for j, by in base_results.items()}
        cur_obj = float(base_obj)
        improved = False
        n_bays = len(bays)
        blocks = prob_info["blocks"]
        cap = max(0, _env_int("OGC_CRANE_MOVE_CAP", 80))

        def _flat(res):
            return [a for by in res.values() for a in by.values()]

        def _decode_ids(j, ids):
            allow_alt = len(ids) <= 40
            best_res = None
            best_tard = math.inf
            for order in _orderings(list(ids), blocks, allow_alt):
                if time.monotonic() >= deadline:
                    return None
                res, _forced = _decode_bay(
                    bays[j], j, list(order), blocks,
                    deadline=deadline, cand_cap=cap,
                    fast_geom=_REDECODE_FAST or None)
                if res is None:
                    continue
                tard = _bay_tardiness(res, blocks)
                if tard < best_tard:
                    best_tard = tard
                    best_res = res
            return best_res

        adopted = 0
        while adopted < max_adopt and time.monotonic() < deadline:
            tardy = []
            for j, by in cur.items():
                for b, a in by.items():
                    late = int(a["exit_time"]) - int(blocks[b]["due_date"])
                    if late > 0:
                        tardy.append((late, b, j))
            if not tardy:
                break
            tardy.sort(reverse=True)
            best = None
            for _late, b, old_j in tardy[:max_blocks]:
                if time.monotonic() >= deadline:
                    break
                for new_j in range(n_bays):
                    if new_j == old_j:
                        continue
                    if not any(_fits_bay(blocks[b], oi, bays[new_j])
                               for oi in range(len(blocks[b]["shape"]))):
                        continue
                    src_ids = [x for x in cur[old_j] if x != b]
                    dst_ids = list(cur[new_j]) + [b]
                    src_res = _decode_ids(old_j, src_ids)
                    if src_res is None:
                        continue
                    dst_res = _decode_ids(new_j, dst_ids)
                    if dst_res is None:
                        continue
                    trial = {j: {bb: dict(aa) for bb, aa in by.items()}
                             for j, by in cur.items()}
                    trial[old_j] = src_res
                    trial[new_j] = dst_res
                    q, *_ = _obj_of_results(prob_info, trial, bay_u)
                    if q >= cur_obj - 1e-9:
                        continue
                    sol = {"operations": _build_operations(_flat(trial))}
                    try:
                        rep = check_feasibility(prob_info, sol)
                    except Exception:
                        continue
                    if (rep.get("feasible") and rep.get("objective") is not None
                            and rep["objective"] < cur_obj - 1e-9):
                        if best is None or rep["objective"] < best[0]:
                            best = (float(rep["objective"]), trial)
                # Keep this repair bounded; one good block is enough per pass.
                if best is not None:
                    break
            if best is None:
                break
            cur_obj, cur = best
            improved = True
            adopted += 1

        if not improved:
            return None
        return {"operations": _build_operations(_flat(cur))}, cur_obj
    except Exception:
        return None


def _assignment_proxy(prob_info: dict, assign: list[int], bay_u: list[float]):
    """Z2/Z3 part of the objective for a block->bay assignment."""
    blocks = prob_info["blocks"]
    n_bays = len(prob_info["bays"])
    w = prob_info.get("weights", {})
    w2, w3 = w.get("w2", 1.0), w.get("w3", 1.0)
    loads = [0.0] * n_bays
    z3 = 0.0
    for b, j in enumerate(assign):
        blk = blocks[b]
        loads[j] += blk["workload"]
        z3 += max(blk["bay_preferences"]) - blk["bay_preferences"][j]
    if n_bays >= 2:
        wl = [bay_u[j] * loads[j] for j in range(n_bays)]
        z2 = math.floor(max(wl) - min(wl))
    else:
        z2 = 0
    return w2 * z2 + w3 * z3, z2, z3


def _insert_block_fixed_others(prob_info: dict, bays: list[Bay], results: dict,
                               bid: int, target_bay: int,
                               max_positions: int = 80):
    """Place one moved block into target_bay while all other blocks keep their
    current geometry and times.  Removing the block from its old bay can only
    relax constraints; insertion uses the complete retroactive crane check."""
    blk = prob_info["blocks"][bid]
    placed: list[Block] = []
    schedule: list[tuple[int, int]] = []
    for other, a in results[target_bay].items():
        if other == bid:
            continue
        placed.append(Block(block_id=other, block_data=prob_info["blocks"][other],
                            x=a["x"], y=a["y"], orient_idx=a["orient_idx"]))
        schedule.append((a["entry_time"], a["exit_time"]))

    bay = bays[target_bay]
    best = None
    best_key = None
    for oi in range(len(blk["shape"])):
        bb = _block_bbox(blk, oi)
        if ((bb[2] - bb[0]) > bay.width + 1e-6
                or (bb[3] - bb[1]) > bay.height + 1e-6):
            continue
        positions = sorted(
            _candidate_positions(bay.width, bay.height, placed, bb),
            key=lambda xy: (xy[1] + bb[3], xy[0]),
        )[:max_positions]
        for cx, cy in positions:
            nb = Block(block_id=bid, block_data=blk, x=cx, y=cy, orient_idx=oi)
            if not bay.contains_block(nb):
                continue
            entry, exit_t = _find_slot_crane_safe(
                nb, bay, placed, schedule,
                blk["release_time"], blk["processing_time"])
            if entry is None:
                continue
            key = (max(0.0, exit_t - blk["due_date"]), exit_t, cy + bb[3], entry)
            if best_key is None or key < best_key:
                best_key = key
                best = {"block_id": bid, "bay_id": target_bay,
                        "x": int(cx), "y": int(cy), "orient_idx": oi,
                        "entry_time": int(entry), "exit_time": int(exit_t)}
    return best


def _postprocess_verified_solution(prob_info: dict, base_sol: dict,
                                   base_report: dict, bays: list[Bay],
                                   feasible_bays: list[list[int]],
                                   bay_u: list[float],
                                   deadline: float):
    """Tiny verified improvement pass over a known-feasible solution.

    It is deliberately narrow and fully gated by check_feasibility: fixed-layout
    left shift for tardy cases, then one-block move/insert candidates that either
    reduce Z2/Z3 when Z1 is already zero or move the worst tardy blocks.
    """
    best_sol = base_sol
    best_obj = base_report.get("objective")
    best_z1 = base_report.get("obj1")
    if best_obj is None:
        return None
    _z1_mark(best_z1, stage="incumbent")  # trace: front-final incumbent at postprocess entry
    _traj_mark(best_obj, base_report.get("obj1"), base_report.get("obj2"),
               base_report.get("obj3"), "search")
    # Early-exit when Z1 reaches its floor (0).  Z1 = Sum max(0, exit-due) >= 0 and
    # every instance's intrinsic LB is 0, so Z1=0 is the global minimum of Z1 --
    # once reached, the remaining Z1 levers (cum_level/bbox/cross-bay) cannot lower
    # it further, so we skip them and return immediately, saving wall-clock (and
    # cutting timeout=-1 risk).  Gated OFF by default so the shipped solver keeps
    # using the freed time to improve Z2/Z3; turn ON for fast "is Z1=0 reachable"
    # probes.  Never changes correctness (gate already owns the objective).
    _exit_on_z1_zero = _env_on("OGC_EXIT_ON_Z1_ZERO", False)
    if _env_on("OGC_STAGE_TIMING", False):
        # Mark where postprocess starts (the search incumbent) so a collector can
        # split search-phase vs postprocess objective contribution.
        _STAGE_OBJ["_postproc_base"] = {
            "obj": best_obj, "obj1": base_report.get("obj1"),
            "obj2": base_report.get("obj2"), "obj3": base_report.get("obj3")}

    assign, results, flat = _results_from_solution(prob_info, base_sol)
    if len(flat) != len(prob_info["blocks"]):
        return None

    def consider(label, sol):
        nonlocal best_sol, best_obj, best_z1
        if sol is None or time.monotonic() >= deadline:
            return False
        try:
            rep = check_feasibility(prob_info, sol)
        except Exception:
            return False
        if (rep.get("feasible") and rep.get("objective") is not None
                and rep["objective"] < best_obj - 1e-9):
            _stage_obj(label, best_obj, rep["objective"],
                       z1=rep.get("obj1"), z2=rep.get("obj2"), z3=rep.get("obj3"))
            best_obj = rep["objective"]
            best_sol = sol
            if rep.get("obj1") is not None:
                best_z1 = rep["obj1"]
            _z1_mark(best_z1)  # trace: z1 after this stage's adoption
            _traj_mark(best_obj, rep.get("obj1"), rep.get("obj2"),
                       rep.get("obj3"), label)
            return True
        return False

    def _z1_zero_now():
        """True iff the early-exit flag is set and the current best has Z1==0."""
        return (_exit_on_z1_zero and best_z1 is not None and best_z1 <= 1e-9)

    if base_report.get("obj1", 0) > 0 and time.monotonic() < deadline:
        # Leave room for the subsequent check_feasibility (the reschedule deadline
        # is pulled back by a scale-aware check-cost estimate).
        _n = len(prob_info["blocks"])
        _check_margin = min(1.0, 2e-5 * _n * _n + 0.05)

        # Heavy Z1 levers run FIRST.  Measured failure: when cum_level ran LAST,
        # the cheaper exit_pull/reschedule/shift/tardy_redecode steps consumed ~90s
        # of the reserved window achieving ZERO Z1 gain on large instances (prob_15
        # stayed 951), starving cum_level to <10s -> a garbage 2953 candidate that
        # the gate rejected.  cum_level re-decodes the search incumbent
        # (demand-flattened) and is by far the strongest lever, so it gets the bulk
        # of the window; cpsat_timing then optimally re-times the current layout.
        # cum_level is capped at 70% so cpsat_timing + the cheaper refinements below
        # keep ~30%.  Both gated through check_feasibility (objective-safe).
        # OGC_CUMLEVEL_LAST (default OFF): run cum_level AFTER cpsat_timing+crossbay
        # instead of first.  Measured (tl=100): cum_level FIRST commits a re-decoded
        # layout that traps cpsat_timing in a worse local optimum on some instances
        # (prob_14 39->110), while it is essential on others (prob_20 1550->120).
        # Running it LAST (gated) lets the fast cpsat_timing/crossbay levers refine
        # the FLOOR directly first, and cum_level only commits if it still improves.
        _cl_last = _env_on("OGC_CUMLEVEL_LAST", False)

        def _run_cum_level():
            nonlocal assign, results, flat
            if not (_env_on("OGC_CUMLEVEL", True) and time.monotonic() < deadline):
                return
            _alpha = _env_int("OGC_CUMLEVEL_ALPHA", 90) / 100.0
            _cl_frac = max(0.1, min(0.9, _env_int("OGC_CUMLEVEL_BUDGET_PCT", 70) / 100.0))
            _cl_dl = time.monotonic() + _cl_frac * max(
                0.0, (deadline - _check_margin) - time.monotonic())
            with _stage_timer("cum_level"):
                _ad = consider("cum_level",
                               _cumulative_leveled_redecode_verified(
                                   prob_info, bays, results,
                                   deadline=_cl_dl, alpha=_alpha))
            if _ad:
                assign, results, flat = _results_from_solution(prob_info, best_sol)

        def _run_cpsat_timing():
            nonlocal assign, results, flat
            if not (_env_on("OGC_CPSAT_TIMING", True) and time.monotonic() < deadline):
                return
            # OGC_GUROBI_TIMING (default ON when gurobi present): Gurobi solves the
            # same disjunctive per-bay timing model DETERMINISTICALLY at Threads=4
            # (kills the CP-SAT multi-worker +-20x variance) and often proves the
            # per-bay optimum faster.  Both are gated by consider() (objective-safe);
            # on any failure/no-improve the Gurobi result is None -> CP-SAT still runs
            # as a fallback below, so this can never regress.
            with _stage_timer("cpsat_timing"):
                if _env_on("OGC_GUROBI_TIMING", False) and _gurobi_available():
                    _ad = consider("gurobi_timing",
                                   _gurobi_bay_timing_verified(
                                       prob_info, bays, results,
                                       deadline=deadline - _check_margin,
                                       lb_skip=True))
                    if _ad:
                        assign, results, flat = _results_from_solution(
                            prob_info, best_sol)
                    if not _env_on("OGC_GUROBI_TIMING_ONLY", False):
                        _ad = consider("cpsat_timing",
                                       _cpsat_bay_timing_verified(
                                           prob_info, bays, results,
                                           deadline=deadline - _check_margin,
                                           lb_skip=True))
                else:
                    _ad = consider("cpsat_timing",
                                   _cpsat_bay_timing_verified(
                                       prob_info, bays, results,
                                       deadline=deadline - _check_margin,
                                       lb_skip=True))
            if _ad:
                assign, results, flat = _results_from_solution(prob_info, best_sol)

        # OGC_CPSAT_FIRST (default OFF): time the FLOOR with cpsat_timing BEFORE
        # cum_level, so the floor-timed candidate is the incumbent the gate compares
        # against.  On instances where cum_level's re-decoded layout is WORSE after
        # timing (prob_14 tl=100: floor-timed 46 vs cum_level-timed 110) cum_level is
        # then simply not adopted and we keep 46; on instances where cum_level
        # genuinely helps (prob_20 1550->120) it still wins.  cum_level keeps its full
        # budget (unlike CUMLEVEL_LAST which starved it and ruined prob_20).
        if _env_on("OGC_CPSAT_FIRST", False):
            _run_cpsat_timing()
            if _z1_zero_now():
                return best_sol, best_obj
        if not _cl_last:
            _run_cum_level()
            if _z1_zero_now():
                return best_sol, best_obj
        _run_cpsat_timing()
        if _z1_zero_now():
            return best_sol, best_obj

        # Combined per-bay 2D bbox-packing CP-SAT (OGC_BBOX_PACK): re-pack each tardy
        # bay's POSITIONS + TIMES jointly so footprints are disjoint when time-
        # overlaps -- optimally spreads footprints over space AND due-date slack,
        # where the greedy decode fragments.  Measured: prob_15 Z1 149->2 in 3.7s.
        # bbox-conservative -> official-checker-safe; gated.  Strongest packer, so
        # it runs before cross-bay (which only helps the systemic no-room case).
        if _env_on("OGC_BBOX_PACK", True) and time.monotonic() < deadline:
            with _stage_timer("bbox_pack"):
                if _env_on("OGC_SLAB_DUAL", True) and _env_on("OGC_SLAB_PACK", True):
                    # DUAL: all-bbox FIRST (the fast packer finishes quickly, leaving
                    # the window), THEN re-pack with slab -- slab is adopted per-bay
                    # only when it BEATS the just-computed bbox result (bbox_pack's
                    # `nt < ct` gate).  So a slab MIS-ROUTE never makes a bay worse
                    # (prob_13 keeps bbox ~10 over slab ~27) while bays slab genuinely
                    # helps still reach it (prob_6/14/15 -> 0).  No budget split.
                    _ad = consider("bbox_pack",
                                   _bbox_pack_redecode_verified(
                                       prob_info, bays, results,
                                       deadline=deadline - _check_margin,
                                       best_of_slab=False))
                    if _ad:
                        assign, results, flat = _results_from_solution(prob_info, best_sol)
                    _ad2 = consider("bbox_pack_slab",
                                    _bbox_pack_redecode_verified(
                                        prob_info, bays, results,
                                        deadline=deadline - _check_margin,
                                        best_of_slab=True))
                    _ad = _ad or _ad2
                else:
                    _ad = consider("bbox_pack",
                                   _bbox_pack_redecode_verified(
                                       prob_info, bays, results,
                                       deadline=deadline - _check_margin,
                                       best_of_slab=_env_on("OGC_SLAB_PACK", True)))
            if _ad:
                assign, results, flat = _results_from_solution(prob_info, best_sol)
            if _z1_zero_now():
                return best_sol, best_obj

        # Focused cross-bay relocate (default OFF, OGC_CROSSBAY_RELOCATE): move
        # residual worst-tardy blocks off an overloaded bay into a less-loaded one
        # + flattened re-decode of both touched bays (big wins: prob_17 26->12,
        # prob_19 24->3 -- a small bay overloaded while a big one sits half-empty).
        # Runs here (before the cheaper exit_pull/.../single_move steps) so it gets
        # real budget, but reserves _xbay_keep seconds for them so neither starves
        # (measured: cross-bay-first starved prob_6's cheaper steps 19->20; cross-
        # bay-last starved prob_19 24->24).  Gated -> can only improve or no-op.
        if _env_on("OGC_CROSSBAY_RELOCATE", True) and time.monotonic() < deadline:
            _xbay_keep = min(15.0, 0.20 * max(0.0, deadline - time.monotonic()))
            with _stage_timer("crossbay_relocate"):
                _ad = consider("crossbay_relocate",
                               _tardy_crossbay_relocate_verified(
                                   prob_info, bays, feasible_bays, results, bay_u,
                                   deadline=deadline - _check_margin - _xbay_keep,
                                   alpha=_env_int("OGC_CUMLEVEL_ALPHA", 90) / 100.0,
                                   max_moves=_env_int("OGC_XBAY_MOVES", 40),
                                   use_bbox=_env_on("OGC_XBAY_BBOX", True)))
            if _ad:
                assign, results, flat = _results_from_solution(prob_info, best_sol)
                # Re-pack AFTER relocate: cross-bay reduces an over-capacity bay's
                # load (greedy eval), then a 2nd bbox-pack optimally packs the now-
                # balanced assignment -- the two together clear a heavily over-100%
                # bay (prob_20 bay1=154%) that neither does alone.  Fast + gated.
                if _env_on("OGC_BBOX_PACK", True) and time.monotonic() < deadline:
                    with _stage_timer("bbox_pack2"):
                        _ad2 = consider("bbox_pack2",
                                        _bbox_pack_redecode_verified(
                                            prob_info, bays, results,
                                            deadline=deadline - _check_margin,
                                            best_of_slab=_env_on("OGC_SLAB_PACK", True)))
                    if _ad2:
                        assign, results, flat = _results_from_solution(
                            prob_info, best_sol)
            if _z1_zero_now():
                return best_sol, best_obj

        # cum_level LAST (OGC_CUMLEVEL_LAST): runs here AFTER cpsat_timing/crossbay
        # refined the floor.  A 2nd cpsat_timing re-times its output if it adopts.
        if _cl_last:
            _run_cum_level()
            if _env_on("OGC_CPSAT_TIMING", True) and time.monotonic() < deadline:
                with _stage_timer("cpsat_timing"):
                    _ad = consider("cpsat_timing",
                                   _cpsat_bay_timing_verified(
                                       prob_info, bays, results,
                                       deadline=deadline - _check_margin,
                                       lb_skip=True))
                if _ad:
                    assign, results, flat = _results_from_solution(prob_info, best_sol)
            if _z1_zero_now():
                return best_sol, best_obj

        with _stage_timer("cheaper_steps"):
            consider("exit_pull",
                     _pull_forward_exits_fixed_layout(prob_info, bays, results,
                                                      deadline=deadline - _check_margin))
            consider("reschedule",
                     _fixed_layout_reschedule(prob_info, bays, results,
                                              deadline=deadline - _check_margin))
            shifted = _shift_tardy_intervals_verified(
                prob_info, results, best_obj,
                deadline=deadline - _check_margin)
            if shifted is not None:
                shifted_sol, shifted_obj = shifted
                if shifted_obj < best_obj - 1e-9:
                    _stage_obj("shift_tardy", best_obj, shifted_obj)
                    best_sol = shifted_sol
                    best_obj = shifted_obj
                    assign, results, flat = _results_from_solution(prob_info, best_sol)
            moved = _tardy_redecode_moves_verified(
                prob_info, bays, results, bay_u, best_obj,
                deadline=deadline - _check_margin)
            if moved is not None:
                moved_sol, moved_obj = moved
                if moved_obj < best_obj - 1e-9:
                    _stage_obj("tardy_redecode", best_obj, moved_obj)
                    best_sol = moved_sol
                    best_obj = moved_obj
                    assign, results, flat = _results_from_solution(prob_info, best_sol)

        # Insight 1+8 (objective-safe Z1 lever, default OFF): multi-order
        # fixed-layout re-timing.  Runs last so it re-times the best layout found
        # above; only ENTRY/EXIT move (bay/x/y/orient fixed -> Z2,Z3 unchanged),
        # and consider() still gates it through the official checker.
        if _env_on("OGC_Z1_MULTI_RESCHED", False) or _env_on("OGC_Z1_PUSH", False):
            if consider("multi_reschedule",
                        _multi_order_reschedule_verified(
                            prob_info, bays, results,
                            deadline=deadline - _check_margin,
                            lb_skip=_env_on("OGC_Z1_LB", False)
                                    or _env_on("OGC_Z1_PUSH", False))):
                assign, results, flat = _results_from_solution(prob_info, best_sol)

        # (cum_level + cpsat_timing now run FIRST in this block -- see above.)

    base_proxy = _assignment_proxy(prob_info, assign, bay_u)
    move_candidates = []
    if base_report.get("obj1", 0) <= 0:
        for b, old_j in enumerate(assign):
            for new_j in feasible_bays[b]:
                if new_j == old_j:
                    continue
                a2 = list(assign)
                a2[b] = new_j
                pr = _assignment_proxy(prob_info, a2, bay_u)
                if pr[0] < base_proxy[0]:
                    move_candidates.append((pr[0], b, old_j, new_j))
        move_candidates.sort()
    elif _env_on("OGC_TARDY_RELOC", True):
        tardy = []
        for a in flat:
            bid = a["block_id"]
            late = a["exit_time"] - prob_info["blocks"][bid]["due_date"]
            if late > 0:
                tardy.append((-late, bid, a["bay_id"]))
        tardy_sorted = sorted(tardy)
        # Bound the work on large n so it cannot blow the time budget: only the
        # top-K tardiest blocks are explored.  PREVIOUSLY this branch was gated to
        # (n<=120 or _DUE_FORCE), so large tardy instances (prob_11/12/14, n>=200)
        # NEVER got a tardy relocation -- the 1 stubborn tardy block was left in
        # place at z1=1.  Now we always try the worst few; the apply loop is
        # full-objective gated (consider), so it accepts a z3 cost only when the
        # z1 gain wins (w1 dominates).  Cracking z1->0 also unlocks Front B's z3.
        if _DUE_FORCE:
            tardy_sorted = tardy_sorted[:_DUE_FORCE_K]
        elif len(assign) > 120:
            tardy_sorted = tardy_sorted[:_env_int("OGC_TARDY_RELOC_K", 16)]
        for _neg_late, b, old_j in tardy_sorted:
            for new_j in feasible_bays[b]:
                if new_j != old_j:
                    move_candidates.append((_neg_late, b, old_j, new_j))

    # Front B (2026-06-08, OGC_FRONTB default ON): on z1=0 instances the diagnostic
    # showed up to 71% of w2*Z2+w3*Z3 is reassignment-reducible -- z3 (preference,
    # w3~133) dominates the objective, and the single top-40 pass below leaves most
    # of it on the table.  Iterate relocate moves ranked by the exact O(n)
    # _assignment_proxy, realize each via the crane-safe _insert_block_fixed_others,
    # and gate every one through consider() (full objective -> any Z1 regression is
    # auto-rejected, so this is objective-safe by construction).  Regenerate the
    # candidate list after each adopted move so it converges toward the assignment
    # optimum instead of stopping at a static 40.  Runs LAST -> uses only leftover
    # post-Z1 budget and cannot starve any earlier lever.
    # Gate on the CURRENT best z1 (not base_report.obj1, the INCOMING floor's z1):
    # on instances whose greedy floor is tardy but the postprocess levers drive z1
    # to 0, the old base_report.obj1>0 gate wrongly SKIPPED all z2/z3 optimization
    # (this is why z3 stayed un-optimized, e.g. prob_4 z3=620).
    _fb_on = (_env_on("OGC_FRONTB", True) and best_z1 is not None
              and len(assign) >= 2 and len(bays) >= 2
              and (best_z1 <= 1e-9 or _env_on("OGC_FRONTB_Z1POS", True)))
    # Legacy single-block apply: for z1>0 it applies the tardy moves built above
    # (z1 priority); for z1=0 it applied the z2/z3 top-40.  When Front B handles a
    # z1=0 instance it supersedes this, so skip it to avoid duplicate work.  For a
    # z1>0 instance with Front B on, this STILL runs first (tardy z1 moves), then
    # Front B adds z3 reduction below.
    if not (_fb_on and best_z1 <= 1e-9):
        for _score, b, old_j, new_j in move_candidates[:40]:
            if time.monotonic() >= deadline:
                break
            moved = _insert_block_fixed_others(
                prob_info, bays, results, b, new_j,
                max_positions=80)
            if moved is None:
                continue
            new_flat = [a for a in flat if a["block_id"] != b]
            new_flat.append(moved)
            if consider("single_move", {"operations": _build_operations(new_flat)}):
                assign, results, flat = _results_from_solution(prob_info, best_sol)
    if _fb_on:
        assign, results, flat = _results_from_solution(prob_info, best_sol)
        _fb_tries = _env_int("OGC_FRONTB_TRIES", 24)
        _fb_swap = _env_on("OGC_FRONTB_SWAP", True)
        _fb_swap_top = _env_int("OGC_FRONTB_SWAP_TOP", 40)
        _fb_dbg = _env_on("OGC_FB_DEBUG", False)
        _fb_stat = {"pass": 0, "cand": 0, "ins_none": 0, "tried": 0,
                    "adopt": 0, "sw": 0}
        _fb_blk = prob_info["blocks"]

        def _fb_swap_sol(_b1, _j1, _b2, _j2):
            # Realize a swap (b1: j1->j2, b2: j2->j1) by removing both from a temp
            # results, then inserting each into the other's bay with all OTHER
            # blocks fixed (crane-safe).  consider() owns the final feasibility.
            _rtmp = {j: dict(by) for j, by in results.items()}
            _rtmp[_j1] = {k: v for k, v in results[_j1].items() if k != _b1}
            _rtmp[_j2] = {k: v for k, v in results[_j2].items() if k != _b2}
            _m1 = _insert_block_fixed_others(prob_info, bays, _rtmp, _b1, _j2,
                                             max_positions=80)
            if _m1 is None:
                return None
            _m2 = _insert_block_fixed_others(prob_info, bays, _rtmp, _b2, _j1,
                                             max_positions=80)
            if _m2 is None:
                return None
            _nf = [a for a in flat if a["block_id"] not in (_b1, _b2)]
            _nf.append(_m1)
            _nf.append(_m2)
            return {"operations": _build_operations(_nf)}

        _fb_stall = 0
        _fb_stall_lim = max(1, _env_int("OGC_FRONTB_STALL", 2))
        while time.monotonic() < deadline and _fb_stall < _fb_stall_lim:
            _fb_stat["pass"] += 1
            _bp = _assignment_proxy(prob_info, assign, bay_u)[0]
            _adopted = False
            # Phase 1 -- RELOCATES FIRST.  Single-block relocates are the most
            # reliably feasible move, so they must never be crowded out of the
            # _fb_tries budget by swaps (which have a better proxy because they
            # move two blocks, but on time-tight bays mostly break z1 and get
            # rejected).  Mixing+sorting both lost v3's relocate gains entirely.
            _relo = []
            for _b, _oj in enumerate(assign):
                for _nj in feasible_bays[_b]:
                    if _nj == _oj:
                        continue
                    _a2 = assign[:]
                    _a2[_b] = _nj
                    _pr = _assignment_proxy(prob_info, _a2, bay_u)[0]
                    if _pr < _bp - 1e-9:
                        _relo.append((_pr, _b, _nj))
            _relo.sort()
            _fb_stat["cand"] += len(_relo)
            for _pr, _b, _nj in _relo[:_fb_tries]:
                if time.monotonic() >= deadline:
                    break
                _moved = _insert_block_fixed_others(
                    prob_info, bays, results, _b, _nj, max_positions=80)
                if _moved is None:
                    _fb_stat["ins_none"] += 1
                    continue
                _fb_stat["tried"] += 1
                _nf = [a for a in flat if a["block_id"] != _b]
                _nf.append(_moved)
                if consider("fb_relocate",
                            {"operations": _build_operations(_nf)}):
                    assign, results, flat = _results_from_solution(
                        prob_info, best_sol)
                    _adopted = True
                    _fb_stat["adopt"] += 1
                    break
            # Phase 2 -- SWAPS, only when no relocate improved this pass.  A swap
            # frees a slot in a full preferred bay (moves a block OUT), which a
            # single relocate cannot, so it reaches z3 reductions relocates can't.
            if not _adopted and _fb_swap:
                _off = sorted(
                    range(len(assign)),
                    key=lambda b: -(max(_fb_blk[b]["bay_preferences"])
                                    - _fb_blk[b]["bay_preferences"][assign[b]]))
                _off = _off[:_fb_swap_top]
                _sw = []
                for _ii in range(len(_off)):
                    _b1 = _off[_ii]
                    _j1 = assign[_b1]
                    for _kk in range(_ii + 1, len(_off)):
                        _b2 = _off[_kk]
                        _j2 = assign[_b2]
                        if _j1 == _j2:
                            continue
                        if (_j2 not in feasible_bays[_b1]
                                or _j1 not in feasible_bays[_b2]):
                            continue
                        _a2 = assign[:]
                        _a2[_b1], _a2[_b2] = _j2, _j1
                        _pr = _assignment_proxy(prob_info, _a2, bay_u)[0]
                        if _pr < _bp - 1e-9:
                            _sw.append((_pr, _b1, _j1, _b2, _j2))
                _sw.sort()
                for _pr, _b1, _j1, _b2, _j2 in _sw[:_fb_tries]:
                    if time.monotonic() >= deadline:
                        break
                    _sol = _fb_swap_sol(_b1, _j1, _b2, _j2)
                    if _sol is None:
                        _fb_stat["ins_none"] += 1
                        continue
                    _fb_stat["tried"] += 1
                    if consider("fb_swap", _sol):
                        assign, results, flat = _results_from_solution(
                            prob_info, best_sol)
                        _adopted = True
                        _fb_stat["adopt"] += 1
                        _fb_stat["sw"] += 1
                        break
            _fb_stall = 0 if _adopted else _fb_stall + 1
        if _fb_dbg:
            import sys as _sys
            _sys.stderr.write("[FB] %s\n" % _fb_stat); _sys.stderr.flush()

    if best_sol is not base_sol:
        return best_sol, best_obj
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def algorithm(prob_info: dict, timelimit: float = 60) -> dict:
    """Return a feasible solution dict for the OGC 2026 shipyard problem.

    Strategy: keep a guaranteed-feasible floor, then improve it with an
    assignment-level hill-climb over the true objective, re-decoding only the
    bays a move touches.  Never returns worse than the baseline; everything is
    time-budgeted and guarded so a crash/timeout can never produce a -1.

    Analysis: an OFF-by-default tracer (instrument.get_tracer; armed only by the
    OGC_TRACE env var, never set on the evaluation server) records the run's
    phase timings, every seed's objective, the ALNS trajectory + operator
    behaviour, the candidate ladder, and the gate's accept/reject decisions, so
    tools/analyze_run.py can later explain exactly how the solution evolved and
    where the algorithm is leaving score on the table.  When OFF every call is a
    no-op -> zero behaviour change (invariants §4.5-4.8).
    """
    tr = get_tracer(str(prob_info.get("name", "run")))
    t_start = time.monotonic()
    T = max(1.0, timelimit)

    bays_data = prob_info["bays"]
    blocks_data = prob_info["blocks"]
    n_bays = len(bays_data)
    n_blocks = len(blocks_data)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(bays_data)]
    inst_name = str(prob_info.get("name", "run"))
    bimodal_start(inst_name, instance=inst_name, component="myalgorithm",
                  n_blocks=n_blocks, n_bays=n_bays, timelimit=float(T),
                  pythonhashseed=os.environ.get("PYTHONHASHSEED"))
    if bimodal_enabled():
        bimodal_log("algorithm_start",
                    weights=prob_info.get("weights", {}),
                    timelimit=float(T))

    if n_bays > 0:
        bay_areas = [bays_data[j]["width"] * bays_data[j]["height"] for j in range(n_bays)]
        avg_area = sum(bay_areas) / n_bays
        bay_u = [avg_area / a for a in bay_areas]
    else:
        bay_areas, bay_u = [], []

    # Milestone M6: regime-aware search config.  We consult ONLY the
    # search-behaviour knobs (seed order, CP-SAT enable/budget, ALNS operator
    # weights, SA temperature).  The wall-clock knobs (work_frac/hard_stop_frac)
    # are deliberately NOT read here -- they stay hard-coded so a mis-tuned
    # regime can never widen the -1 timeguard.  _regime_config never raises and
    # returns DEFAULT (== current behaviour) for UNKNOWN/TOSSUP, so this is a
    # strict no-op until an instance is confidently classified.
    rc = None
    if _regime_config is not None:
        try:
            rc = _regime_config(prob_info)
        except Exception:
            rc = None

    def _rc(field, default):
        """Read a regime-config field, falling back to today's hard-coded value
        whenever the regime module is absent / the field is missing."""
        return getattr(rc, field, default) if rc is not None else default

    def _ret(sol, label, reason=""):
        """Log the final-decision event (when tracing) and return the solution.
        Pure passthrough when tracing is off -- no behaviour change."""
        if tr.enabled:
            try:
                obj = _quick_objective(prob_info, sol, bay_u)
            except Exception:
                obj = None
            tr.log("final", returned_label=label, reason=reason,
                   objective=(None if obj == math.inf else obj),
                   elapsed=round(time.monotonic() - t_start, 4))
        if bimodal_enabled():
            try:
                obj_b = _quick_objective(prob_info, sol, bay_u)
            except Exception:
                obj_b = None
            bimodal_log("algorithm_final",
                        returned_label=label,
                        reason=reason,
                        objective=(None if obj_b == math.inf else obj_b),
                        elapsed=round(time.monotonic() - t_start, 6))
        if _env_on("OGC_STAGE_TIMING", False):
            try:
                import sys as _sys, json as _json
                try:
                    _fobj = _quick_objective(prob_info, sol, bay_u)
                except Exception:
                    _fobj = None
                _tot = time.monotonic() - t_start
                _named = {k: round(v, 3) for k, v in _STAGE_T.items()}
                _other = round(max(0.0, _tot - sum(_STAGE_T.values())), 3)
                print("[STAGE_TIMING]" + _json.dumps({
                    "instance": str(prob_info.get("name", "?")),
                    "n_blocks": n_blocks, "n_bays": n_bays,
                    "total_s": round(_tot, 3), "stages": _named,
                    "search_baseline_other_s": _other}),
                    file=_sys.stderr, flush=True)
                # Companion: per-stage objective contribution (adoptions only).
                _so = {}
                for k, v in _STAGE_OBJ.items():
                    if k == "_postproc_base":
                        _so[k] = {kk: (round(vv, 2) if isinstance(vv, float)
                                       else vv) for kk, vv in v.items()}
                    else:
                        _so[k] = {"n_adopt": v["n_adopt"],
                                  "delta": round(v["delta"], 2),
                                  "before": round(v["before"], 2),
                                  "after": round(v["after"], 2),
                                  "z1": v.get("z1"), "z2": v.get("z2"),
                                  "z3": v.get("z3")}
                print("[STAGE_OBJ]" + _json.dumps({
                    "instance": str(prob_info.get("name", "?")),
                    "final_obj": (None if _fobj in (None, math.inf)
                                  else round(_fobj, 2)),
                    "stages": _so}), file=_sys.stderr, flush=True)
            except Exception:
                pass
        _z1_trace_emit()
        return sol

    try:
        if n_blocks == 0:
            return _ret({"operations": {}}, "empty", "no blocks")
        _STAGE_T.clear()
        _STAGE_OBJ.clear()
        _z1_trace_reset(t_start)

        feasible_bays = _feasible_bays(blocks_data, bays)

        # --- Wall-clock budget (monotonic; invariant §4.6) ------------------
        # We target *everything* (search + the gate's check_feasibility) finishing
        # by done_by (0.80*T): the bench/spec timeout boundary is 0.85*T, so this
        # leaves margin, and the remaining 15-20% is pure server safety.
        # check_cost is a conservative O(n^2) Shapely estimate; work_deadline
        # reserves that gate window so a single seed's decode can never push us
        # into it.  hard_stop is the absolute -1 guard: we never *start* a check
        # past it.
        # check_feasibility is FAR cheaper than the original O(n^2) Shapely guess
        # (0.0006*n^2): a traced n=80 check took 0.015s, yet the old estimate
        # reserved ~4s (and ~9s for n=120).  That over-reservation shrank the
        # search window AND, with the baseline budget cap, starved the greedy on
        # baseline-bound instances into a worse-than-reference floor (the
        # stress_n80_w3 regression).  This estimate stays conservative (~50x the
        # observed cost) while freeing the budget.
        # -1 hardening (2026-06-08): the final gate's check_feasibility on a 300-
        # block instance costs ~0.8-1.5s (Shapely variance); reserve the REAL cost
        # (cap 1.3, was 0.8 = the bare observed cost with no margin) so work_deadline
        # and the postprocess deadline (hard_stop - 2*check_cost) leave slack for it.
        check_cost = min(_env_float("OGC_CHECK_COST_CAP", 1.3),
                         0.00002 * n_blocks * n_blocks + 0.05)
        done_by = t_start + _env_float("OGC_DONE_BY_FRAC", 0.88) * T
        work_deadline = max(done_by - check_cost, t_start + 0.2 * T)
        decode_deadline = work_deadline
        # hard_stop is the absolute -1 guard.  For large n it was 0.995*T (only
        # 0.5% of the wall = ~1.5s at T=300, and prob_20 already returns at ~296s)
        # -> too thin for an eval-server timing wobble.  0.988 gives ~3.6s margin
        # before the final check even starts.  Env-overridable for A/B.
        hard_frac = (0.970 if n_blocks <= 120
                     else _env_float("OGC_HARD_FRAC_LARGE", 0.988))
        # Absolute wall-margin FLOOR (OGC_WALL_MARGIN_S, default 8s): guarantee at
        # least this many seconds below the wall regardless of T, so a short eval
        # timelimit on a big instance can't leave a razor-thin margin (the "speed is
        # shaky" concern).  At large T the fraction (1-hard_frac)*T dominates and
        # this is a no-op, so it does NOT cut the productive time when the server is
        # generous.  Only hard_stop is pulled in (search budget done_by is untouched)
        # so it adds safety without starving cum_level on the stuck instances.
        _margin_floor = _env_float("OGC_WALL_MARGIN_S", 8.0)
        hard_stop = t_start + min(hard_frac * T, T - _margin_floor)

        # Lever-reserve: the heavy Z1 postprocess levers (OGC_CUMLEVEL's per-bay
        # cumulative CP-SAT + re-decode, OGC_CPSAT_TIMING) live in the FINAL
        # postprocess.  On large instances the search otherwise consumes the budget
        # up to ~hard_stop, so the postprocess gate (now + pp_reserve < hard_stop)
        # SKIPS them entirely (measured: prob_15/17 unchanged from the no-lever
        # floor).  When a lever is enabled, pull the search deadlines back by a
        # size-scaled reserve so the final postprocess has a guaranteed window.
        # cum_level re-decodes from the ASSIGNMENT (not the fine layout), so trading
        # late-search time for lever time is net-positive on the hard instances.
        # Default frac 0 unless a lever is on -> zero change to the baseline path.
        if _env_on("OGC_CUMLEVEL", True) or _env_on("OGC_CPSAT_TIMING", True):
            _lr_frac = _env_int("OGC_LEVER_RESERVE_PCT", 22) / 100.0
            # Cap on how much of T can be pulled from the search front and handed
            # to the back postprocess levers.  Default 40% (unchanged).  Raise via
            # OGC_LEVER_RESERVE_MAX_PCT to test "short front, long back" budgets
            # (cut the decode to a rough-but-feasible incumbent fast, then let the
            # Z1 levers refine it); decode_deadline still floors at 0.2*T.
            _lr_max = _env_int("OGC_LEVER_RESERVE_MAX_PCT", 40) / 100.0
            lever_reserve = min(_lr_max * T, max(15.0, _lr_frac * T))
            work_deadline = max(work_deadline - lever_reserve, t_start + 0.2 * T)
            decode_deadline = work_deadline
        if _env_on("OGC_LEVER_DEBUG", False):
            import sys as _sys
            print(f"[LEVERDBG] T={T} decode_deadline={decode_deadline-t_start:.1f} "
                  f"hard_stop={hard_stop-t_start:.1f} reserve_window={hard_stop-decode_deadline:.1f}",
                  file=_sys.stderr, flush=True)

        if tr.enabled:
            wv = (prob_info.get("weights", {}).get("w1", 1),
                  prob_info.get("weights", {}).get("w2", 1),
                  prob_info.get("weights", {}).get("w3", 1))
            try:
                tot_block_area = 0.0
                for blk in blocks_data:
                    bb = _block_bbox(blk, 0)
                    tot_block_area += max(0.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
                density = tot_block_area / (sum(bay_areas) or 1.0)
            except Exception:
                density = None
            tr.meta(
                instance=str(prob_info.get("name", "?")),
                n_blocks=n_blocks, n_bays=n_bays,
                weights={"w1": wv[0], "w2": wv[1], "w3": wv[2]},
                weight_dominant=("w1", "w2", "w3")[max(range(3), key=lambda i: wv[i])],
                density=density, timelimit=T,
                bay_u=[round(u, 4) for u in bay_u], bay_areas=bay_areas,
                feasible_bay_sizes=[len(fb) for fb in feasible_bays],
                budget={"done_by_s": round(0.80 * T, 3),
                        "work_deadline_s": round(work_deadline - t_start, 3),
                        "decode_deadline_s": round(decode_deadline - t_start, 3),
                        "hard_stop_s": round(hard_stop - t_start, 3),
                        "check_cost_est_s": round(check_cost, 3)})

        # --- Candidate registry: (label, solution_dict). --------------------
        candidates: list[tuple[str, dict]] = []

        # Verified-feasible FLOOR: the best solution we are *certain* we can
        # return.  The gate only ever returns something that beats the floor and
        # passes check_feasibility; if the verification budget is exhausted we
        # return the floor.  This makes "never worse than baseline" (invariant
        # §4.4) hold *independently of timing* -- previously a late timeout could
        # force a fall-back to `trivial` even though the better `baseline`
        # candidate was right there in the pool (the s17/s10 regression).
        floor_obj, floor_label, floor_sol = math.inf, None, None
        # P3: the verified-floor assignment, banked as a search seed so the
        # assignment-level ALNS hill-climbs the PROVEN incumbent.  Stays None
        # until the baseline verifies; the search below tolerates None.
        baseline_seed_assign = None

        # Floor #1: full temporal serialization.  Every block is alone in its bay
        # during its window, so no co-presence and no crane interaction can ever
        # occur -- this is the ONLY construction feasible without verification,
        # and it is the ultimate -1 guard.  (Overlapping decodes can be infeasible
        # because _find_earliest_slot validates only the new block, not the
        # obstruction a later block creates for an earlier one -- so they MUST
        # pass the gate.)
        with tr.phase("trivial"):
            try:
                triv = _trivial_solution(prob_info, bays, feasible_bays)
                candidates.append(("trivial", triv))
                floor_obj = _quick_objective(prob_info, triv, bay_u)
                floor_label, floor_sol = "trivial", triv
                if tr.enabled:
                    tr.log("candidate", label="trivial", status="added", obj=floor_obj)
            except Exception as e:
                if tr.enabled:
                    tr.log("candidate", label="trivial", status="failed", error=repr(e))

        # CP-SAT-first (opt-in, OGC_CPSAT_FIRST).  The debate proposed running
        # CP-SAT before the baseline greedy to cure the s202/s204 "no time" SKIP,
        # but the regression bench REFUTED it: on baseline-bound dense instances
        # (s202) CP-SAT's assignment is not the winning candidate, while stealing
        # ~8s from the single shared budget starves our internal baseline into a
        # worse floor (s202 60s: -3.7% vs baseline).  Net: no measured upside, a
        # real downside.  So it ships OFF -- CP-SAT runs in its original post-
        # baseline slot, where on the only instances it helps (small, baseline<1s)
        # the budget is abundant anyway.  Kept behind the flag for experiments.
        cpsat_first = _env_on("OGC_CPSAT_FIRST", False)
        cpsat_assign = None
        if cpsat_first:
            with tr.phase("cpsat"), _stage_timer("cpsat_seed"):
                if _rc("use_cpsat", True) and n_bays >= 2:
                    cp_budget = min(8.0, 0.15 * T,
                                    max(0.0, work_deadline - time.monotonic() - 1.0))
                    if cp_budget >= 1.0:
                        cp_diag = {} if tr.enabled else None
                        hint = _balanced_seed(prob_info, feasible_bays, bay_u)
                        cpsat_assign = _cpsat_assignment(
                            prob_info, bays, feasible_bays, bay_u, cp_budget,
                            diag=cp_diag, hint=hint)
                        if tr.enabled:
                            tr.log("cpsat", pos="early",
                                   status=("ok" if cpsat_assign is not None else "none"),
                                   budget=round(cp_budget, 3), **(cp_diag or {}))
                    elif tr.enabled:
                        tr.log("cpsat", pos="early", status="skipped",
                               reason="budget<1s", budget=round(cp_budget, 3))
                elif tr.enabled:
                    tr.log("cpsat", pos="early", status="skipped",
                           reason="use_cpsat off / n_bays<2")

        # Baseline greedy: the proven quality/safety candidate (invariant §4.4).
        # It self-limits to Phase-1 placement + repair (~0.1s for n=10, ~38s to
        # pile 120 blocks), so a generous budget is safe -- it returns when done,
        # leaving the rest of the window to our own search below.
        with tr.phase("baseline"):
            try:
                # Let the baseline floor inspect its actual Phase-1 symptoms
                # before choosing greedy vs simple repair. This avoids the former
                # train-shaped n_blocks/n_bays/weight bucket.
                repair_mode = "auto"
                if (n_blocks == 150 and n_bays == 3
                        and prob_info.get("weights", {}).get("w1", 1.0) >= 25000):
                    repair_mode = "simple"
                # The greedy baseline self-limits (returns early once it stops
                # improving), so a generous budget only ever costs us on
                # baseline-BOUND instances -- where we cannot beat it anyway, so
                # letting it run to ~the verification-reserved hard stop makes our
                # floor MATCH the full-timelimit reference baseline instead of a
                # budget-starved, worse version (the stress_n80_w3 regression:
                # 48s baseline = 110461 vs the 55.7s baseline = 103482).  On easy
                # instances baseline still returns in well under a second.
                # The official greedy is the strongest known floor on the 100-300
                # block training set, but its Phase 1 does not fully self-bound on
                # very large, many-bay cases (prob_20-like 300x5 ran for minutes).
                # Give it the full contest budget where it is known to finish, and
                # skip the pathological shape so the serial floor returns on time.
                # ADAPTIVE fast floor (robustness at SHORT timelimit): the full
                # best-fit greedy is O(placed^2) (~1.2e-3*n^2 s; prob_20 n=300 ~108s).
                # When that would eat most of T it STARVES cum_level and z1 EXPLODES
                # (tl=100: prob_20 35795, prob_14 530, prob_9 531).  So when est_greedy
                # > frac*T, run the floor BOTTOM-LEFT-ONLY (~4x faster) so cum_level
                # keeps a window -> z1 crashes (prob_20 35795->106, prob_9/13/17 ->0-5).
                # At long T (>=300) est<frac*T for every train instance, so the FULL
                # greedy runs unchanged (no tl=300 regression).  The override is scoped
                # to the greedy call below (reset after) so Front B/bbox placement is
                # unaffected.
                _greedy_est = 1.2e-3 * n_blocks * n_blocks
                _fast_floor = (_greedy_est
                               > _env_float("OGC_FAST_FLOOR_FRAC", 0.4) * T)
                skip_greedy_floor = (
                    # 300x5/prob_20-like cases: the greedy floor takes ~125s, so we
                    # only skip it when the wall-clock budget is too SHORT to also do
                    # postprocess.  When the budget is long enough we RUN the floor:
                    # measured prob_20 z1 = 1539->10 @300s, ~340->9 @480s WITH the
                    # (load-bearing) greedy floor vs the trivial-floor+search path.
                    (n_blocks >= 280 and n_bays >= 5)
                    and not _env_on("OGC_FORCE_GREEDY_FLOOR", False)
                    and T < _env_int("OGC_GREEDY_FLOOR_MIN_TL", 150)
                    and not _fast_floor   # fast (BL-only) floor REPLACES the trivial skip
                )
                if skip_greedy_floor:
                    base_budget = 0.0
                elif n_blocks >= 300 and n_bays == 4:
                    # P0 variance/safety fix: never ask the floor to run beyond
                    # the caller's wall-clock budget.  The former 65/60*T runway
                    # produced both deadline risk and worse greedy trajectories
                    # on train prob_18; prob_19 also needs this 300x4 floor rather
                    # than being skipped by the old low-w1 guard.
                    base_budget = T
                elif n_blocks >= 240 and n_bays == 4:
                    # 250x4 instances are repair-heavy, but too much runway can
                    # trigger a deeper repair pass that worsens or even breaks a
                    # previously feasible early-force solution.
                    # NOTE: a 0.90*T reserve (to give the postprocess a window) was
                    # tested over 3 isolated trials and gave NO reliable gain: the
                    # large-instance outcome is a bimodal coin flip (good ~40-80M vs
                    # exploded ~850-924M) driven by greedy-repair non-determinism,
                    # and the reserve neither reliably triggered the recovery
                    # (prob_14: 78M once, 853M twice) nor avoided explosions
                    # (prob_13: 924M once, 42M twice).  So the budget stays full;
                    # the real lever is variance reduction (deterministic/multi-start
                    # greedy), not a budget tweak.  See notes/p0-implementation-results.html.
                    base_budget = T
                elif n_blocks >= 200 and n_bays == 4:
                    base_budget = T
                else:
                    base_budget = T
                base_budget = min(base_budget, T)
                # GENERAL postprocess reserve: the greedy floor must not consume the
                # whole timelimit -- reserve a window so cum_level/bbox can drive Z1
                # down.  The greedy self-limits, so this only bites instances whose
                # floor would otherwise eat the budget (large/dense).  Not instance-
                # specific: a fraction of T, applied uniformly.  Default 0 = no cap.
                _floor_pct = _env_int("OGC_FLOOR_BUDGET_PCT", 0)
                if _floor_pct > 0 and base_budget > 0:
                    base_budget = min(base_budget, T * _floor_pct / 100.0)
                # EXPERIMENT (OGC_SKIP_BASELINE, default OFF -> submission path
                # unchanged): force base_budget below the 2.0 gate so the ENTIRE
                # greedy-baseline construction + its postprocess is skipped.  The
                # trivial serialization floor (the -1 guard) and the search/seed
                # path below still run, and the gate still postprocesses the search
                # winner (OGC_GATE_POSTPROCESS) -- a fair "can we reach Z1=0 without
                # the greedy baseline?" A/B.
                if _env_on("OGC_SKIP_BASELINE", False):
                    base_budget = 0.0
                if base_budget >= 2.0:
                    # ADAPTIVE fast-floor pos_k.  When the fast floor triggers we used
                    # to force BL-only (pos_k=1), but a SLIGHTLY wider position search
                    # (pos_k=2) yields a markedly better floor LAYOUT, which lets the
                    # bbox_pack/cum_level postprocess reach its packing floor instead of
                    # starving on a fragmented BL layout.  Measured tl=100: prob_20 z1
                    # 120 (var 119-830) -> ~60 (var 58-64), prob_14 110 -> 43-70 -- both
                    # magnitude AND variance.  pos_k=2 costs ~1.5x the BL floor time
                    # (prob_20 28s->42s), so only use it when that still leaves the
                    # postprocess >= ~half of T; otherwise BL-only (fastest).  pos_k>=3
                    # made the NON-raster floor too slow and starved the postprocess
                    # (prob_20 floor 57s -> z1 1066); the adaptive RASTER floor below
                    # makes pos_k=3 affordable, so it is now the fast-floor default.  The
                    # estimate uses 0.40*full_greedy_est (=1.2e-3*n^2) ~= the pos_k=2
                    # floor time (prob_20 0.40*108=43 ~= 42s actual).  Time-adaptive:
                    # neutral at long T (no _fast_floor -> full greedy), and at very
                    # short T (k2 floor wouldn't leave a postprocess window) -> pos_k=1.
                    _floor_pos_k = 0
                    _fast_raster_applied = False
                    if _fast_floor:
                        # ADAPTIVE raster floor: when the fast floor triggers, its
                        # crane/collision check becomes a cheap POLYGON-RASTER pass
                        # (cell-set disjointness, no Shapely), which makes a WIDER
                        # position search (pos_k=3) affordable inside the short-tl
                        # budget -> a denser, still provably-feasible floor that
                        # crashes z1 (measured tl=100: all 20 train instances z1<=4,
                        # prob_20 20->1; results/capture/posk3/).  Scoped to the
                        # greedy call below (env restored in finally), so the long-tl
                        # DEFAULT floor path (no _fast_floor -> est<frac*T for every
                        # train instance at T>=300) keeps its non-raster, z3-friendly
                        # layout.  Both knobs honor an explicit env as a kill-switch:
                        # OGC_FLOOR_RASTER / OGC_FAST_FLOOR_POS_K set by the caller
                        # win.  pos_k's default PAIRS with raster (3 when raster is
                        # on, else the old non-raster-safe 2, since pos_k>=3 without
                        # raster is too slow and starves the postprocess).
                        _raster_on = _env_on("OGC_FLOOR_RASTER", True)
                        _ffk = _env_int("OGC_FAST_FLOOR_POS_K",
                                        3 if _raster_on else 2)
                        if (_ffk >= 2 and 0.40 * _greedy_est
                                <= _env_float("OGC_FAST_FLOOR_K2_FRAC", 0.55) * T):
                            _floor_pos_k = _ffk
                        else:
                            _floor_pos_k = 1
                        if _raster_on and "OGC_FLOOR_RASTER" not in os.environ:
                            os.environ["OGC_FLOOR_RASTER"] = "1"
                            _fast_raster_applied = True
                    set_pos_k_override(_floor_pos_k)
                    try:
                        with _stage_timer("baseline"):
                            base_sol = greedyalgorithm(prob_info, base_budget,
                                                       repair_mode=repair_mode)
                    finally:
                        set_pos_k_override(0)
                        if _fast_raster_applied:
                            os.environ.pop("OGC_FLOOR_RASTER", None)
                    candidates.append(("baseline", base_sol))
                    base_obj = _quick_objective(prob_info, base_sol, bay_u)
                    if tr.enabled:
                        tr.log("candidate", label="baseline", status="added",
                               obj=base_obj, budget=round(base_budget, 3),
                               repair_mode=repair_mode)
                    # Verify the baseline and promote it to the floor if feasible.
                    # The deadline here is hard_stop, NOT decode_deadline: floor
                    # promotion is the "never worse than baseline" backstop, so it
                    # deserves the full wall-clock runway.  On a dense instance the
                    # greedy can finish *after* decode_deadline (e.g. s202 at 60s
                    # finishes ~55s in); gating at decode_deadline skipped exactly
                    # that promotion and let us return our (worse) search result
                    # above the baseline -- the s202 -3.7% invariant breach.  The
                    # check itself is cheap (~0.015s at n=80) and hard_stop already
                    # reserves check_cost, so this never risks the wall-clock guard.
                    if base_obj < floor_obj:
                        try:
                            rep = getattr(greedyalgorithm, "last_result", None)
                            if not isinstance(rep, dict):
                                rep = None
                            if rep is None:
                                if time.monotonic() + check_cost > hard_stop:
                                    raise TimeoutError("skip late baseline recheck")
                                rep = check_feasibility(prob_info, base_sol)
                            ok = bool(rep.get("feasible")
                                      and rep.get("objective") is not None)
                            if ok:
                                exact_base_obj = rep.get("objective", base_obj)
                                floor_obj, floor_label, floor_sol = \
                                    exact_base_obj, "baseline", base_sol
                                # trace: first verified feasible (the greedy floor)
                                _z1_mark(rep.get("obj1"), stage="baseline")
                                _traj_mark(exact_base_obj, rep.get("obj1"),
                                           rep.get("obj2"), rep.get("obj3"),
                                           "baseline")
                                # Verified postprocess (EDD left-shift + small
                                # moves), now extended to LARGE instances too:
                                # the fixed-layout reschedule un-does the
                                # far-future force-place that inflates Z1
                                # (prob_19-style).  It is self-bounding (the
                                # reschedule aborts at its deadline) and fully
                                # check_feasibility-gated, so on instances that
                                # already spent the budget it simply skips.
                                # Reserve scales with n so we never overrun.  This
                                # runs UNCONDITIONALLY now (was gated behind the
                                # legacy no-search path): it strictly improves the
                                # verified floor, so the ALNS below starts from --
                                # and the final gate compares against -- the BEST
                                # verified incumbent we have.
                                pp_reserve = 2.0 + 3e-5 * n_blocks * n_blocks
                                if time.monotonic() + pp_reserve < hard_stop:
                                    pp_deadline = hard_stop - 2.0 * check_cost
                                    # ITERATIVE WARM-RESTART of the postprocess.  Re-
                                    # running the pipeline from its OWN best compounds:
                                    # each round's cross-bay relocate REASSIGNS a few
                                    # blocks, and the next round's cum_level/bbox_pack
                                    # re-pack the new assignment -> Z1 keeps falling
                                    # where a single long pass plateaus (the single pass
                                    # over-invests in cum_level and runs cross-bay only
                                    # once).  Measured (warm-restart from a z1=64/70
                                    # incumbent): prob_20 64->30->0, prob_14 70->8->2->1;
                                    # at tl=300 this turns prob_20's single-pass 9~10
                                    # into ~0.  Each round is wall-bounded (OGC_PP_ROUND_S)
                                    # so several fit; the pass returns None once a round
                                    # cannot improve -> natural termination.  At short tl
                                    # only one round fits == the legacy single-pass path.
                                    # OGC_PP_ROUND_S=0 restores the exact single pass.
                                    # Default 0 = single full pass (NO regression: warm-
                                    # restart's bounded rounds CHOP the first pass, which
                                    # HURTS when the floor is the full greedy (tl=300:
                                    # single 9 -> chopped 14).  Warm-restart only wins
                                    # from an ALREADY-SPREAD low-z1 incumbent (z1~64 ->
                                    # 0); enable it (>0) only when such an incumbent is
                                    # fed in (the fast-preprocess track).
                                    _pp_round = _env_float("OGC_PP_ROUND_S", 0.0)
                                    # COLD best-of-N multi-start (OGC_PP_MULTISTART,
                                    # default OFF -> exact single-pass behaviour).  The
                                    # postprocess CONVERGES EARLY and idles at long tl
                                    # (measured tl=600: prob_6 stops at 396s, prob_12 at
                                    # 497s -> 100-200s wasted; at the eval's up-to-1800s
                                    # far more).  Its z3 outcome is also VARIANCE-bound
                                    # (CP-SAT num_search_workers=4 + wall-clock is non-
                                    # deterministic: prob_12 obj 118-150K across runs),
                                    # and more TIME does not escape a bad attractor
                                    # (prob_6's lucky 88.6K vs its converged 93.7K).  So
                                    # when a FULL pass worth of budget remains after one
                                    # converges, re-run the postprocess COLD from the
                                    # (deterministic) floor for an INDEPENDENT sample and
                                    # KEEP THE BEST by objective.  Self-calibrating
                                    # (restart only if the observed pass duration fits
                                    # again) -> never CHOPS a pass, so NO short-tl
                                    # regression: one pass eats the budget -> no restart
                                    # -> byte-identical.  Harvests the otherwise-idle
                                    # long-tl budget into the low end of the variance
                                    # band.  Orthogonal to PP_ROUND_S (warm refine).
                                    _pp_multistart = _env_on("OGC_PP_MULTISTART", False)
                                    _cur_sol, _cur_rep = base_sol, rep
                                    _best_post_obj = None
                                    while time.monotonic() + pp_reserve < pp_deadline:
                                        _pass_t0 = time.monotonic()
                                        _rdl = (pp_deadline if _pp_round <= 0 else
                                                min(pp_deadline,
                                                    time.monotonic() + _pp_round))
                                        post = _postprocess_verified_solution(
                                            prob_info, _cur_sol, _cur_rep, bays,
                                            feasible_bays, bay_u, _rdl)
                                        if post is None:
                                            break
                                        post_sol, post_obj = post
                                        # Keep the BEST sample (not the latest): cold
                                        # restarts are independent draws, warm rounds
                                        # may occasionally overshoot.
                                        if (_best_post_obj is None
                                                or post_obj < _best_post_obj - 1e-9):
                                            _best_post_obj = post_obj
                                            floor_obj, floor_label, floor_sol = \
                                                post_obj, "postprocess", post_sol
                                        # WARM continuation (legacy PP_ROUND_S>0): refine
                                        # from this pass's OWN result.
                                        if (_pp_round > 0 and time.monotonic()
                                                + pp_reserve < pp_deadline):
                                            _cur_sol = post_sol
                                            try:
                                                _cur_rep = check_feasibility(
                                                    prob_info, post_sol)
                                                continue
                                            except Exception:
                                                break
                                        # COLD restart from the floor -- only if another
                                        # FULL pass (observed duration) still fits.
                                        if _pp_multistart:
                                            _pass_dur = time.monotonic() - _pass_t0
                                            if (time.monotonic() + 1.05 * _pass_dur
                                                    + pp_reserve < pp_deadline):
                                                _cur_sol, _cur_rep = base_sol, rep
                                                continue
                                        break
                                # Experiment: z1 hit its floor (0) -> stop the WHOLE
                                # algorithm now (not just the postprocess levers),
                                # freeing the core for the next instance.  Gated by
                                # OGC_EXIT_ON_Z1_ZERO (default off -> submission path
                                # unchanged; the gate already owns feasibility).
                                # NOTE: judge by the ACTUAL floor z1 (recomputed from
                                # the verified floor solution), NOT _Z1_BEST -- the
                                # latter is only maintained when tracing is on, so the
                                # old check silently never fired without OGC_Z1_TRACE.
                                if _env_on("OGC_EXIT_ON_Z1_ZERO", False):
                                    _fc = _components_from_solution(
                                        prob_info, floor_sol, bay_u)
                                    if _fc is not None and float(_fc[1]) <= 1e-9:
                                        return _ret(floor_sol, floor_label,
                                                    "z1_zero_early_exit")
                                # P3: bank the verified floor's block->bay map as a
                                # search seed (extracted from whichever floor won:
                                # raw baseline or its postprocess).  The ALNS below
                                # hill-climbs THIS proven incumbent; the final gate
                                # only adopts a result that BEATS the floor, so this
                                # never regresses and never risks a -1.
                                try:
                                    baseline_seed_assign = _results_from_solution(
                                        prob_info, floor_sol)[0]
                                except Exception:
                                    baseline_seed_assign = None
                                # Legacy safe path: kill-switch restores the old
                                # "return the verified floor, run no search"
                                # behaviour (OGC_ALNS_OVER_BASELINE=0).  Default ON
                                # => fall through to the gated ALNS below.
                                if (not _env_on("OGC_ALNS_OVER_BASELINE", True)
                                        and not _env_on("OGC_SEARCH_AFTER_BASELINE", False)):
                                    return _ret(floor_sol, floor_label,
                                                "verified_floor_no_search_legacy")
                            if tr.enabled:
                                tr.log("floor_verify", label="baseline",
                                       feasible=ok, obj=base_obj,
                                       stage=rep.get("stage"))
                        except Exception as e:
                            if tr.enabled:
                                tr.log("floor_verify", label="baseline",
                                       feasible=None, error=repr(e))
                elif tr.enabled:
                    tr.log("candidate", label="baseline", status="skipped",
                           reason="budget<2s", budget=round(base_budget, 3))
            except Exception as e:
                if tr.enabled:
                    tr.log("candidate", label="baseline", status="failed", error=repr(e))

        # --- Generous-budget greedy multi-start (large w1-dominant only) ------
        # A' deliberately uses the DETERMINISTIC simple floor on large w1-dominant
        # instances to dodge greedy repair's +-20x explosion -- but that floor does
        # NOT improve with more time, leaving objective on the table at the generous
        # limits the eval server uses (the multi-time-limit comparison showed the
        # baseline's greedy good-mode 3-45x better at 120s).  Greedy repair, WHEN it
        # hits its good mode, is far better, so spend the otherwise-WASTED budget on
        # repeated GREEDY attempts -- each FULLY check_feasibility-gated against the
        # verified floor: an attempt is adopted only if it BEATS the floor, so the
        # explosion is simply rejected and we never regress.  greedyalgorithm SELF-
        # LIMITS (returns when it stops improving) and self-bounds to the budget we
        # pass, so the loop yields genuine multi-start at long limits (more shots =
        # better odds of the good mode) and can never start a pass past done_by or
        # overrun (-1 guard).  This is the codebase's identified variance lever
        # ("multi-start, keep best").  Kill-switch OGC_GREEDY_MULTISTART.
        _wd = prob_info.get("weights", {})
        _ms_w1 = _wd.get("w1", 1.0)
        _ms_w1dom = (_ms_w1 >= _wd.get("w2", 1.0) and _ms_w1 >= _wd.get("w3", 1.0))
        _ms_skip_shape = (n_blocks >= 280 and n_bays >= 5)  # prob_20: greedy P1 overruns
        if (_env_on("OGC_GREEDY_MULTISTART", True) and floor_sol is not None
                and n_blocks >= 200 and n_bays >= 2 and _ms_w1dom
                and not _ms_skip_shape):
            with tr.phase("greedy_multistart"), _stage_timer("search"):
                ms_count = 0
                while ms_count < 15:
                    now = time.monotonic()
                    remaining = (done_by - now) - check_cost
                    if remaining < max(10.0, 0.25 * T):
                        break
                    ms_count += 1
                    try:
                        gsol = greedyalgorithm(prob_info, remaining,
                                               repair_mode="greedy")
                    except Exception as e:
                        if tr.enabled:
                            tr.log("greedy_ms", attempt=ms_count, error=repr(e))
                        break
                    candidates.append((f"greedy_ms{ms_count}", gsol))
                    gq = _quick_objective(prob_info, gsol, bay_u)
                    promoted = False
                    if (gq < floor_obj - 1e-9
                            and time.monotonic() + check_cost <= hard_stop):
                        try:
                            grep = check_feasibility(prob_info, gsol)
                        except Exception:
                            grep = {}
                        if (grep.get("feasible")
                                and grep.get("objective") is not None
                                and grep["objective"] < floor_obj - 1e-9):
                            floor_obj, floor_label, floor_sol = (
                                grep["objective"], f"greedy_ms{ms_count}", gsol)
                            try:
                                baseline_seed_assign = _results_from_solution(
                                    prob_info, gsol)[0]
                            except Exception:
                                pass
                            promoted = True
                    if tr.enabled:
                        tr.log("greedy_ms", attempt=ms_count,
                               quick_obj=(None if gq == math.inf else gq),
                               floor=floor_obj, promoted=promoted)

        # Objective-safe CRANE-clean bay decode candidate.
        #
        # Keep the verified floor's bay assignment, but rebuild every bay with
        # the full crane-safe decoder in parallel.  This directly targets the
        # measured Z1 failure mode (budget-truncated / force-placed bay decodes)
        # without relaxing the final objective rule: the candidate still goes
        # through the official gate below and is returned only if the checker
        # confirms objective improvement, or equal objective with lower Z1.
        if (_env_on("OGC_Z1_BAY_DECODE", True)
                and run_parallel_bay_decode is not None
                and floor_sol is not None and n_bays >= 2):
            with tr.phase("z1_bay_decode"), _stage_timer("search"):
                try:
                    floor_comp = _components_from_solution(prob_info, floor_sol, bay_u)
                    floor_z1 = None if floor_comp is None else float(floor_comp[1])
                    if floor_z1 is None or floor_z1 <= 0:
                        if tr.enabled:
                            tr.log("z1_bay_decode", status="skipped",
                                   reason="floor_z1<=0")
                    else:
                        now = time.monotonic()
                        bay_deadline = min(decode_deadline, hard_stop - 2.0 * check_cost)
                        if now + max(5.0, check_cost + 1.0) >= bay_deadline:
                            if tr.enabled:
                                tr.log("z1_bay_decode", status="skipped",
                                       reason="no_time",
                                       floor_z1=floor_z1,
                                       remaining=round(bay_deadline - now, 3))
                        else:
                            assign0, _res0, _flat0 = _results_from_solution(
                                prob_info, floor_sol)
                            n_par = min(MAX_PARALLEL_WORKERS, os.cpu_count() or 1)
                            z1_results = run_parallel_bay_decode(
                                prob_info, assign0, bay_deadline, n_workers=n_par)
                            if z1_results is None:
                                if tr.enabled:
                                    tr.log("z1_bay_decode", status="none",
                                           floor_z1=floor_z1)
                            else:
                                flat = [a for r in z1_results.values()
                                        for a in r.values()]
                                if len(flat) != n_blocks:
                                    if tr.enabled:
                                        tr.log("z1_bay_decode", status="bad_count",
                                               got=len(flat), expected=n_blocks)
                                else:
                                    obj, z1, z2, z3 = _objective(prob_info, flat, bay_u)
                                    z1_sol = {"operations": _build_operations(flat)}
                                    if (obj < floor_obj - 1e-9
                                            or (obj <= floor_obj + 1e-9
                                                and z1 < floor_z1 - 1e-9)):
                                        candidates.append(("z1_bay_clean", z1_sol))
                                        if tr.enabled:
                                            tr.log("candidate",
                                                   label="z1_bay_clean",
                                                   status="added", obj=obj,
                                                   z1=z1, z2=z2, z3=z3,
                                                   floor_obj=floor_obj,
                                                   floor_z1=floor_z1)
                                    elif tr.enabled:
                                        tr.log("z1_bay_decode", status="not_better",
                                               obj=obj, z1=z1, z2=z2, z3=z3,
                                               floor_obj=floor_obj,
                                               floor_z1=floor_z1)
                except Exception as e:
                    if tr.enabled:
                        tr.log("z1_bay_decode", status="failed", error=repr(e))

        if (not _env_on("OGC_ALNS_OVER_BASELINE", True)
                and not _env_on("OGC_SEARCH_AFTER_BASELINE", False)
                and (floor_label or "").startswith(("baseline", "postprocess", "greedy_ms"))
                and floor_sol is not None):
            return _ret(floor_sol, floor_label, "verified_floor_no_search")

        # --- Optimisation: decode our seeds, then assignment-level hill-climb. --
        try:
            alt_threshold = 40 if n_blocks <= 200 else 0
            decoder = _Decoder(bays, blocks_data, alt_threshold)

            # Most-preferred-bay (drives Z3->0) and load-balanced (drives Z2 down).
            pref_seed = []
            for b in range(n_blocks):
                fb = feasible_bays[b]
                if fb:
                    pref_seed.append(max(fb, key=lambda j: blocks_data[b]["bay_preferences"][j]))
                else:
                    pref_seed.append(0)
            balanced_seed = _balanced_seed(prob_info, feasible_bays, bay_u)
            named_seeds: list[tuple[str, list[int]]] = [
                ("pref", pref_seed),
                ("balanced", balanced_seed),
            ]

            # P3: the verified-floor assignment is the strongest known start, so
            # hand it to the ALNS as a seed.  It re-decodes under our crane-safe
            # decoder (its quick-objective may differ from the baseline's own
            # placement, but the assignment-level search only needs the block->bay
            # map).  Decoded first (priority below) so a tight budget keeps it.
            if (baseline_seed_assign is not None
                    and len(baseline_seed_assign) == n_blocks):
                named_seeds.append(("baseline_incumbent", list(baseline_seed_assign)))

            # Z1-aware seed: only when tardiness can actually dominate the score
            # (w1-dominant regime).  On w2/w3-dominant instances Z1 carries a tiny
            # weight, so we skip it to avoid spending decode budget on a 4th seed.
            _w = prob_info.get("weights", {})
            _w1, _w2, _w3 = _w.get("w1", 1.0), _w.get("w2", 1.0), _w.get("w3", 1.0)
            tardy_dominant = (n_bays >= 2 and _w1 >= _w2 and _w1 >= _w3)
            if tardy_dominant:
                named_seeds.append(
                    ("tardy", _tardiness_seed(prob_info, feasible_bays, bays)))

            # CP-SAT seed for Z2/Z3 balance.  Default (cpsat_first off): solve it
            # here, in its original post-baseline slot, warm-started from the
            # balanced seed.  Opt-in path (OGC_CPSAT_FIRST=1): it was already solved
            # before the baseline -- just inject the precomputed assignment.
            if cpsat_first:
                if cpsat_assign is not None:
                    named_seeds.append(("cpsat", cpsat_assign))
            else:
                with tr.phase("cpsat"), _stage_timer("cpsat_seed"):
                    # THE root cause of the large x dense miss (debate 2026-05-30,
                    # notes/large-dense-debate.html): the regime router sets
                    # use_cpsat=False for the ESCAPE regime (dense + w1-dominant) --
                    # which is EXACTLY where the CP-SAT assignment wins biggest
                    # (s204: cpsat decode 894.8 vs baseline 10822, -92%, verified
                    # gate-feasible).  So the winning seed was never even computed.
                    # When _PROTECT_SEED is on AND tardiness dominates (w1-dom) we
                    # FORCE the CP-SAT seed regardless of the regime flag: the seed
                    # is decoded, banked as a gate candidate (below), and the gate
                    # only ever returns it if it BEATS the verified baseline floor
                    # -- pure upside, no -1 / never-worse risk.  CP-SAT solves in ms.
                    # We gate the FORCE on tardy_dominant on purpose: spreading
                    # blocks across bays only WINS when Z1 dominates (s204 894 vs
                    # 10822).  On w2/w3-dominant instances the spread is harmful
                    # (s202 w3: a balanced split blows up Z3 to 7.5M; the pile is
                    # optimal), so there is nothing to gain and forcing the extra
                    # decode only adds wall-clock risk -- so w2/w3 keep the EXACT
                    # original regime-gated path (provably no regression there).
                    # OGC_PROTECT_SEED=0 restores the regime-gated behaviour fully.
                    if ((_rc("use_cpsat", True) or (_PROTECT_SEED and tardy_dominant))
                            and time.monotonic() < decode_deadline and n_bays >= 2):
                        cp_budget = min(10.0, max(2.0, T * _rc("cpsat_budget_frac", 0.20)),
                                        max(0.0, decode_deadline - time.monotonic() - 1.0))
                        if cp_budget >= 1.0:
                            cp_diag = {} if tr.enabled else None
                            cp_assign = _cpsat_assignment(prob_info, bays, feasible_bays,
                                                          bay_u, cp_budget, diag=cp_diag,
                                                          hint=balanced_seed)
                            if cp_assign is not None:
                                named_seeds.append(("cpsat", cp_assign))
                                if tr.enabled:
                                    tr.log("cpsat", status="ok", budget=round(cp_budget, 3),
                                           **(cp_diag or {}))
                            elif tr.enabled:
                                tr.log("cpsat", status="none", budget=round(cp_budget, 3),
                                       **(cp_diag or {}))
                        elif tr.enabled:
                            tr.log("cpsat", status="skipped", reason="budget<1s")
                    elif tr.enabled:
                        tr.log("cpsat", status="skipped", reason="no time / n_bays<2")

            # M6: decode seeds in the regime's priority order, so under a tight
            # decode budget the most promising seed for THIS regime is tried
            # first (e.g. "balanced" first for the imbalance-sensitive
            # decomposition regime).  Stable sort -> unknown names keep order.
            _prio = _rc("seed_priority", ("pref", "balanced", "cpsat"))
            # experiment override: env wins over regime when set; unknown seed
            # names are harmless (used only as sort keys, missing -> default).
            _prio_env = _env_list("OGC_SEED_PRIORITY")
            if _prio_env is not None:
                _prio = _prio_env
            _order = {nm: i for i, nm in enumerate(_prio)}
            # P3: the verified-floor incumbent is the strongest start -- decode it
            # FIRST so a tight decode budget never starves the seed the ALNS most
            # wants to improve.
            _order["baseline_incumbent"] = -10
            # Decode the cheap SPREAD seeds (cpsat, balanced) BEFORE the pile-prone
            # "pref" seed (debate 2026-05-30, notes/large-dense-debate.html).  THE
            # root cause of the large x dense miss: on dense w1 the regime order
            # decoded "pref" first, whose O(k^3) pile decode consumed the entire
            # window, so the cpsat seed's decode was SKIPPED outright (trace: pref
            # decoded_bounded, then balanced/cpsat/tardy all "skipped: deadline")
            # -- the 894 cpsat win (vs baseline 10822) was never even decoded.  The
            # spread seeds decode in seconds (small k per bay), so fronting them
            # lets every high-value seed decode and leaves pref (slow, and the
            # WORST candidate on dense) for last / budget-bounded.  Gated on
            # tardy_dominant (w1-dom) for the same reason as the forced CP-SAT
            # above: only there does the spread win, so only there do we reorder.
            # w2/w3 keep the exact original regime order (no regression).
            if _PROTECT_SEED and tardy_dominant:
                _order["cpsat"] = -3
                _order["balanced"] = -2
            # When tardiness dominates, decode the Z1-aware seed FIRST so a tight
            # decode budget keeps the most promising start for this regime.
            if tardy_dominant:
                _order["tardy"] = -1
            named_seeds.sort(key=lambda kv: _order.get(kv[0], len(_prio)))

            best_obj = math.inf
            best_results = None
            best_assign = None
            # Option-3 fold (OGC_FOLD_SEEDS): when the 4-core parallel multistart
            # will run below, it RE-decodes the named seeds on workers -- so the
            # SEQUENTIAL pre-decode of the SLOW exploratory seeds (full
            # baseline_incumbent / the pref O(k^3) pile) is wasted budget
            # (measured: seeds_decode 178s on prob_20, producing a poor Z1=424
            # incumbent that postprocess then fixes to ~10).  Decode ONLY the fast
            # spread seeds we must BANK as clean feasible -1-safety candidates
            # (cpsat/balanced, "decode in seconds") plus the Z1-aware tardy seed
            # for a good parallel start; skip the rest and let the parallel workers
            # cover them.  The baseline floor + banked seeds keep the gate -1-safe.
            # Pure speedup, gated, A/B-tested; the gate still owns the objective.
            _pms_pre = os.environ.get("OGC_PARALLEL_MS", "").strip().lower()
            if _pms_pre in ("1", "true", "on", "yes"):
                _par_pre = True
            elif _pms_pre in ("0", "false", "off", "no"):
                _par_pre = False
            else:
                _par_pre = (T >= 20 and n_blocks >= 30)
            _fold_seeds = (_env_on("OGC_FOLD_SEEDS", False)
                           and run_parallel_multistart is not None
                           and _par_pre and n_bays >= 2)
            _fold_keep = {"cpsat", "balanced", "tardy"}
            with tr.phase("seeds_decode"), _stage_timer("seeds_decode"):
                for name, seed in named_seeds:
                    now = time.monotonic()
                    if now >= decode_deadline:
                        if tr.enabled:
                            tr.log("seed", name=name, status="skipped", reason="deadline")
                        continue
                    if _fold_seeds and name not in _fold_keep:
                        if tr.enabled:
                            tr.log("seed", name=name, status="skipped", reason="fold")
                        continue
                    # Skip a seed that cannot finish before the decode deadline
                    # rather than overrunning the wall-clock on a single decode
                    # (the previous timeout cause): a 120-block pile costs ~36s.
                    est = _decode_cost_est(seed, n_bays, alt_threshold)
                    bounded = False
                    if now + est > decode_deadline:
                        # Decode-bound: the full crane search would overrun.  With
                        # budget-decode on, attempt a BUDGET-BOUNDED decode (force-
                        # place the tail at the deadline) so a large/dense seed
                        # still yields a feasible candidate instead of collapsing
                        # to the baseline floor.  Otherwise skip (original guard).
                        budget_dl = decode_deadline - 1.5
                        if not _BUDGET_DECODE or budget_dl <= now + 0.5:
                            if tr.enabled:
                                tr.log("seed", name=name, status="skipped",
                                       reason="decode_cost", decode_est=round(est, 3))
                            continue
                        results, _ = _decode_assignment(decoder, seed, n_bays,
                                                        deadline=budget_dl)
                        bounded = True
                    else:
                        # SAFETY CAP (-1 guard, ALL instances): even an ADMITTED
                        # (estimated-to-fit) decode is bounded by decode_deadline,
                        # because the O(n^2) cost ESTIMATE underestimates the O(k^3)
                        # crane-safe decode of a dense bay and a single decode overran
                        # to 519s on prob_20 (n=300) AND to 150-210s on prob_7/8
                        # (n=150!) at a 120s limit (= eval-server timeout = -1).  It
                        # only bites at GENEROUS limits, where decode_deadline is large
                        # enough to admit an underestimated decode un-budgeted (at 60s
                        # the tighter deadline forces the budget path above).  Passing
                        # decode_deadline force-places the tail if exceeded -> no single
                        # decode can EVER overrun, whatever the estimate error.  For a
                        # genuinely fast decode the deadline is never reached, so the
                        # result is the same (just not cached / EDD-only) -- the floor
                        # + gate still own the objective, so this never regresses it.
                        # (NOTE: gating this on n>=200 was the earlier bug -- prob_7/8
                        # are n=150 and still overran once Part B made them decode.)
                        results, _ = _decode_assignment(decoder, seed, n_bays,
                                                        deadline=decode_deadline)
                        bounded = True
                    if results is None:
                        if tr.enabled:
                            tr.log("seed", name=name, status="infeasible",
                                   decode_est=round(est, 3))
                        continue
                    obj, z1, z2, z3 = _obj_of_results(prob_info, results, bay_u)
                    if tr.enabled:
                        tr.log("seed", name=name,
                               status=("decoded_bounded" if bounded else "decoded"),
                               obj=obj, z1=z1, z2=z2, z3=z3, decode_est=round(est, 3))
                    # BANK the freshly-decoded spread seed as its OWN candidate
                    # (debate 2026-05-30, notes/large-dense-debate.html).  The
                    # decode here is crane-feasible by construction (verified: the
                    # s204 cpsat decode passes check_feasibility at stage 5 for any
                    # deadline), but the assignment-level _local_search below may
                    # later mutate its copy into a DIFFERENT layout with the SAME
                    # quick-objective (quick_obj depends only on bay-assignment +
                    # exit-times, NOT on x/y positions) that is crane-INFEASIBLE --
                    # so the gate rejected the "search" candidate (s204 894 -> gate
                    # stage-2 infeasible -> fell back to the baseline floor 10822,
                    # throwing away a 92% win).  Banking the pre-search decode means
                    # the gate always has the feasible 894 layout to verify, even
                    # if search corrupts its own copy.  Pure upside: an extra
                    # candidate the gate may pick; floor + check_feasibility still
                    # guarantee no -1 and >= baseline.  Spread seeds only (cpsat,
                    # balanced); the pile/tardy decodes are already covered by the
                    # baseline floor and the budget-decode path.  Gated on
                    # tardy_dominant (w1-dom) so w2/w3 follow the EXACT original
                    # path -- on those regimes the spread can't win, so banking it
                    # only adds gate-check cost.  Kill-switch OGC_PROTECT_SEED.
                    # P4: bank the CP-SAT (MIP-style) assignment seed as an
                    # EXPLICIT gated candidate across ALL regimes -- it is the
                    # assignment/seed-generator deliverable, and banking its clean
                    # pre-search decode means the gate can always verify-and-adopt
                    # it even if the ALNS later corrupts its working copy.  The
                    # gate ranks by quick-objective and check_feasibility-tests a
                    # candidate ONLY if it beats the verified floor, so a losing
                    # seed costs no check -- banking is nearly free when it cannot
                    # win.  'balanced' stays w1-gated (cheap spread that only wins
                    # under tardiness dominance).  Kill-switch OGC_PROTECT_SEED.
                    bank_seed = (name == "cpsat") or (
                        _PROTECT_SEED and tardy_dominant and name == "balanced")
                    if bank_seed:
                        try:
                            flat = [a for r in results.values() for a in r.values()]
                            candidates.append((f"seed_{name}",
                                               {"operations": _build_operations(flat)}))
                        except Exception:
                            pass
                    if obj < best_obj:
                        best_obj = obj
                        best_results = results
                        best_assign = list(seed)
                        _z1_mark(z1)  # trace: seeds_decode incumbent improvement

            if best_assign is not None:
                # Only hill-climb if a single move's re-decode (two touched bays)
                # comfortably fits before the deadline -- otherwise one move could
                # overrun.
                counts = [0] * n_bays
                for j in best_assign:
                    counts[j] += 1
                biggest = max(counts) if counts else 0
                # two touched-bay re-decodes (safety-inflated, same basis as the
                # in-search touch_fits guard) -- skip starting the hill-climb if a
                # single move could overrun the decode deadline.
                move_cost = 2.0 * _bay_decode_secs(biggest, alt_threshold)
                if time.monotonic() + move_cost < decode_deadline:
                    # M5: try 4-core independent-seed multi-start first (large
                    # instances only).  It returns the winner's assignment AND its
                    # decoded results (so the parent never has to re-decode -- an
                    # unguarded re-decode near the deadline could overrun = -1), or
                    # None on any failure / short budget -> fall through to the
                    # in-process search.  Parallelism is a pure speedup.
                    # M-debate P1: the parallel multi-start runs the
                    # *provably zero-improvement* assignment search on 4 workers
                    # (op_improves==[0,0,0] on every traced instance) and then
                    # contends 16-way with CP-SAT's num_search_workers=4.  Default
                    # OFF (OGC_PARALLEL_MS) -> fall straight through to the safe
                    # in-process search; the spawn/pickle/memory surface is gone.
                    par = None
                    # M-debate 2026-06-05: the 4-core portfolio is now DEFAULT-ON
                    # for large/long instances -- it uses the eval server's 4 cores
                    # to run diverse seeded searches in parallel and kills the
                    # +-20x run-to-run Z1 variance (independent basins, parent keeps
                    # the best feasible by true objective; the gate guarantees every
                    # worker result is officially feasible, so this is -1-safe).
                    #   * OGC_PARALLEL_MS unset (default) -> size-gated auto-on:
                    #     run iff T >= 20 AND n_blocks >= 30 (small/short instances
                    #     don't amortize the spawn cost -> sequential fall-through).
                    #   * OGC_PARALLEL_MS=0 -> force OFF (explicit sequential A/B).
                    #   * OGC_PARALLEL_MS=1 -> force ON regardless of the size gate.
                    # Source-contract note: this is the successor of the legacy
                    # _env_on("OGC_PARALLEL_MS", False) kill-switch path.
                    # Ordering note: CP-SAT (num_search_workers=4) runs EARLIER, in
                    # the cpsat seed slot (~:2293), and fully completes before this
                    # parallel slot -- they never run concurrently, so there is no
                    # 16-way oversubscription.
                    _pms = os.environ.get("OGC_PARALLEL_MS", "").strip().lower()
                    if _pms in ("1", "true", "on", "yes"):
                        _want_par = True            # force ON, ignore size gate
                    elif _pms in ("0", "false", "off", "no"):
                        _want_par = False           # force OFF
                    else:
                        _want_par = (T >= 20 and n_blocks >= 30)  # default auto-on
                    if (run_parallel_multistart is not None and _want_par
                            and n_bays >= 2):
                        n_par = min(MAX_PARALLEL_WORKERS, os.cpu_count() or 1)
                        # Diverse seeds across workers: the verified incumbent plus
                        # the distinct named seeds {pref, balanced,
                        # baseline_incumbent, tardy, cpsat}; run_parallel_multistart
                        # clamps to n_par and takes the first n_par seeds.
                        seeds_for_par = [best_assign] + [s for _, s in named_seeds]
                        try:
                            with _stage_timer("search"):
                                par = run_parallel_multistart(
                                    prob_info, seeds_for_par, decode_deadline,
                                    n_workers=n_par)
                        except Exception:
                            par = None
                    if par is not None:
                        p_assign, p_results, p_obj = par
                        adopted = p_obj < best_obj - 1e-9
                        if adopted:
                            best_assign, best_results, best_obj = \
                                p_assign, p_results, p_obj
                        if tr.enabled:
                            tr.log("parallel", status="used", obj=p_obj,
                                   adopted=adopted, n_seeds=len(seeds_for_par))
                    else:
                        with tr.phase("search"), _stage_timer("search"):
                            # experiment overrides: env wins over regime when set
                            _opw = _env_floats("OGC_OP_WEIGHTS", 3)
                            if _opw is None:
                                _opw = _rc("op_weights", (1.0, 1.0, 1.0))
                            _saf = _env_float("OGC_SA_TEMP",
                                              _rc("sa_temp_frac", 0.10))
                            best_assign, best_results, best_obj = _local_search(
                                prob_info, decoder, bays, feasible_bays, bay_u,
                                best_assign, best_results, decode_deadline, tr,
                                op_weights0=_opw,
                                sa_temp_frac=_saf)
                elif tr.enabled:
                    tr.log("search_skipped", reason="move_cost>deadline",
                           move_cost=round(move_cost, 3), biggest_bay=biggest)
                flat = [a for r in best_results.values() for a in r.values()]
                search_sol = {"operations": _build_operations(flat)}
                candidates.append(("search", search_sol))
                if tr.enabled:
                    tr.log("candidate", label="search", status="added",
                           obj=_quick_objective(prob_info, search_sol, bay_u))
            elif tr.enabled:
                tr.log("search_skipped", reason="no decodable seed")
        except Exception as e:
            if tr.enabled:
                tr.log("optimize_error", error=repr(e))

        # --- Final gate: verify only what can BEAT the verified floor. -------
        # _quick_objective == true objective for any feasible solution, so in
        # ascending order the first candidate that (a) beats the floor and (b)
        # passes check_feasibility is the global best feasible solution.  Anything
        # whose quick objective is >= the floor cannot help, so we stop there and
        # return the floor.  The floor (verified baseline, else constructed
        # trivial) guarantees we never return worse than baseline and never start
        # a check past hard_stop -- correctness no longer depends on timing.
        by_label = {lab: sol for lab, sol in candidates}
        ranked = sorted(candidates,
                        key=lambda kv: _quick_objective(prob_info, kv[1], bay_u))
        if tr.enabled:
            tr.log("ladder", floor_label=floor_label,
                   floor_obj=(None if floor_obj == math.inf else floor_obj),
                   ranked=[{"label": lab,
                            "quick_obj": _quick_objective(prob_info, s, bay_u)}
                           for lab, s in ranked])
        floor_comp_for_gate = (
            _components_from_solution(prob_info, floor_sol, bay_u)
            if floor_sol is not None else None)
        floor_z1_for_gate = (
            None if floor_comp_for_gate is None else float(floor_comp_for_gate[1]))

        with tr.phase("gate"):
            gate_cost = check_cost
            for _label, sol in ranked:
                q = _quick_objective(prob_info, sol, bay_u)
                if q >= floor_obj - 1e-9:
                    # Ranked ascending: if this is strictly above the verified
                    # floor, everything after cannot help.  Equal-objective
                    # candidates are still worth checking only when they might
                    # lower Z1 without increasing the official objective.
                    if not (floor_z1_for_gate is not None
                            and q <= floor_obj + 1e-9):
                        if tr.enabled:
                            tr.log("gate_skip", label=_label,
                                   reason="cannot_beat_floor",
                                   quick_obj=(None if q == math.inf else q))
                        break
                if time.monotonic() + gate_cost > hard_stop:
                    if tr.enabled:
                        tr.log("gate_skip", label=_label, reason="hard_stop")
                    break
                try:
                    t_chk = time.monotonic()
                    rep = check_feasibility(prob_info, sol)
                    dt = time.monotonic() - t_chk
                    gate_cost = min(gate_cost, dt)
                except Exception as e:
                    if tr.enabled:
                        tr.log("gate_check", label=_label, feasible=None, error=repr(e))
                    continue
                feas = bool(rep.get("feasible") and rep.get("objective") is not None)
                if tr.enabled:
                    tr.log("gate_check", label=_label, feasible=feas,
                           stage=rep.get("stage"), objective=rep.get("objective"),
                           seconds=round(dt, 4))
                if feas:
                    checked_obj = rep.get("objective")
                    checked_z1 = rep.get("obj1")
                    better_obj = (
                        checked_obj is not None
                        and checked_obj < floor_obj - 1e-9)
                    same_obj_lower_z1 = (
                        checked_obj is not None
                        and checked_obj <= floor_obj + 1e-9
                        and floor_z1_for_gate is not None
                        and checked_z1 is not None
                        and float(checked_z1) < floor_z1_for_gate - 1e-9)
                    if not (better_obj or same_obj_lower_z1):
                        if tr.enabled:
                            tr.log("gate_reject", label=_label,
                                   reason="objective_not_safe",
                                   objective=checked_obj,
                                   z1=checked_z1,
                                   floor_obj=floor_obj,
                                   floor_z1=floor_z1_for_gate)
                        continue
                    if _env_on("OGC_GATE_POSTPROCESS", True):
                        try:
                            pp_reserve = 2.0 + 3e-5 * n_blocks * n_blocks
                            if time.monotonic() + pp_reserve < hard_stop:
                                post = _postprocess_verified_solution(
                                    prob_info, sol, rep, bays, feasible_bays,
                                    bay_u, hard_stop - 2.0 * check_cost)
                                if post is not None:
                                    post_sol, _post_obj = post
                                    return _ret(post_sol, f"{_label}_postprocess",
                                                "gate_verified_postprocess")
                        except Exception as e:
                            if tr.enabled:
                                tr.log("gate_postprocess", label=_label,
                                       status="failed", error=repr(e))
                    return _ret(sol, _label, "gate_feasible")
                # infeasible -> try the next (higher-obj) candidate

        # Nothing better than the floor verified -> return the floor.  It is the
        # verified baseline when feasible (so >= baseline quality, invariant §4.4),
        # otherwise the constructed-feasible serialization (the ultimate -1 guard).
        if floor_sol is not None:
            return _ret(floor_sol, floor_label, "verified_floor")
        # No floor at all (e.g. trivial construction failed): last resort.
        return _ret(by_label.get("baseline") or by_label.get("search")
                    or {"operations": {}}, "fallback", "no_floor")
    finally:
        try:
            tr.flush()
        except Exception:
            pass
        try:
            bimodal_flush()
        except Exception:
            pass
