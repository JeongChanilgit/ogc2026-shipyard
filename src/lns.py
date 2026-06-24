# lns.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Per-bay LARGE NEIGHBORHOOD SEARCH (LNS / ALNS) tardiness (z1) improver.
#
# This is a GATED best-of CANDIDATE, mirroring perbay.improve() / rasterpack.improve()'s
# contract.  A separate integration in myalgorithm.py adopts its output ONLY if the
# official `check_feasibility` passes AND the objective strictly improves, all wrapped in
# try/except.  Therefore this engine:
#   * NEVER raises to the caller (everything wrapped in try/except),
#   * is strictly deadline-bounded (time.monotonic()), and
#   * in the worst case returns the input solution UNCHANGED (identity).
#
# WHY LNS (the diagnosis).  Our greedy / raster / box engines all CONSTRUCT a layout
# in one forward sweep: once a block is placed it never moves.  On congested set2
# bays a block that is RELEASED early can be forced late simply because every dense
# bottom-left slot at its release time is already occupied by blocks the greedy chose
# to place there earlier -- the greedy cannot BACKTRACK to relocate those earlier
# blocks to make room.  5x time-limit barely helps (the local optimum is structural,
# not budget-bound); crane-stacking and finer-raster NOOP on these bays.  LNS is the
# remaining lever: it DESTROYS a region of the layout (removes K blocks) and REPAIRS
# it better, so an early-released-but-late block can be re-inserted at its release in a
# dense slot that the destroy operator just CLEARED.  This is the only mechanism in
# the project that can move already-placed blocks to reduce another block's tardiness.
#
# SCOPE.  We operate PER BAY with the bay ASSIGNMENT FIXED, so Z2 (load imbalance)
# and Z3 (preference) are provably invariant; only per-bay tardiness Z1 changes, and
# we only touch bays whose current tardiness > 0.  Within a bay we may change each
# block's (x, y, orientation, entry, exit).
#
# SAFETY MODEL (the non-negotiable invariant).  Every candidate placement we ACCEPT
# is validated with the SAME true-polygon raster geometry rasterpack uses (masks are
# a SUPERSET of the float footprint, so raster non-overlap => true non-overlap) AND,
# whenever stacking / footprint-overlap is involved, with the REAL official checker
# (utils.check_entry / check_exit / check_collisions over the time-overlapping sets,
# exactly as check_feasibility stages 2/3/4).  After LNS finishes a bay we run a FINAL
# full-bay REAL-checker re-validation; the bay is adopted only if it both passes and
# strictly reduces this bay's tardiness, else the ORIGINAL bay is kept verbatim.  The
# caller's check_feasibility + strict-improve gate is the ultimate backstop.
#
# RELATION TO rasterpack.  rasterpack does a one-shot EDD raster bottom-left re-decode
# of each bay (a single greedy construction).  LNS uses rasterpack's geometry helpers
# (mask rasterization, the real-checker bay validator, the block factory) but adds the
# DESTROY/REPAIR/ACCEPT outer loop -- i.e. it can iterate THOUSANDS of partial
# re-decodes, escaping the single greedy decode rasterpack is stuck at.  We REUSE
# rasterpack's helpers rather than replicate them (they are module-level and stable).

from __future__ import annotations

import math
import os
import random
import sys
import time

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy present in ogc2025 env
    _np = None

# Optional: scipy FFT correlation for the vectorized BL free-spot search.  When
# absent we fall back to a numpy integral-image (summed-area-table) scan, which
# is also fully vectorized over the (gy,gx) grid -- only the per-orientation work
# differs.  Never required; absence just picks the slower-but-still-vectorized path.
try:
    from scipy.signal import fftconvolve as _fftconvolve
    _HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _fftconvolve = None
    _HAVE_SCIPY = False

# Reuse rasterpack's geometry + real-checker helpers (module-level, stable).  These
# are imported lazily inside improve() too, but importing at module load is fine here
# because rasterpack does NOT import lns (no circular dependency), and rasterpack's
# own myalgorithm import is itself lazy.
try:
    from rasterpack import (
        _rasterize as _rp_rasterize,
        _orient_geom as _rp_orient_geom,
        _make_block as _rp_make_block,
        _bay_crane_feasible as _rp_bay_crane_feasible,
    )
    _HAVE_RP = True
except Exception:  # pragma: no cover
    _HAVE_RP = False
    _rp_rasterize = None
    _rp_orient_geom = None
    _rp_make_block = None
    _rp_bay_crane_feasible = None


# -----------------------------------------------------------------------------
# Tiny env helpers -- replicated inline (NOT imported from myalgorithm) to avoid a
# circular import at module load.  Behaviour bit-identical to perbay/rasterpack/
# myalgorithm _env_* ; all three never raise (unset/unparseable -> default).
# -----------------------------------------------------------------------------
def _env_on(name: str, default: bool) -> bool:
    try:
        v = os.environ.get(name, "").strip().lower()
        if not v:
            return default
        return v not in ("0", "false", "off", "no")
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return float(v)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return int(float(v))
    except Exception:
        return default


def _dbg(msg: str) -> None:
    """Stderr trace, gated by OGC_LNS_DEBUG (default off).  Never raises."""
    try:
        if _env_on("OGC_LNS_DEBUG", False):
            sys.stderr.write("[lns] " + msg + "\n")
            sys.stderr.flush()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Per-bay LNS state.
#
# A "placement" of block b is the tuple (o, gx, gy, entry).  We carry the derived
# (mask, w_cells, h_cells, exit, anchor_x, anchor_y) alongside so collision tests,
# the real-checker, and the final record build are O(1).  The bay layout is the dict
# {b: placement}.  Everything is on the integer raster grid `g` (default 1).
# -----------------------------------------------------------------------------
class _BayLNS:
    """All the geometry + cost machinery for ONE bay.  Never raises out of its public
    methods (callers treat a None/False as 'cannot place' / 'infeasible')."""

    def __init__(self, W, H, ids, recs, blocks, g, bay_obj):
        self.W = int(W); self.H = int(H)
        self.g = max(1, int(g))
        self.Wc = int(math.ceil(self.W / self.g))
        self.Hc = int(math.ceil(self.H / self.g))
        self.ids = list(ids)
        self.recs = recs
        self.blocks = blocks
        self.bay_obj = bay_obj
        # scalars
        self.P = {}; self.R = {}; self.D = {}
        # per-block per-orient: (mask, w, h, offminx, offminy)
        self.masks = {}
        for b in self.ids:
            blk = blocks[b]
            self.P[b] = int(blk["processing_time"])
            self.R[b] = int(blk["release_time"])
            self.D[b] = int(blk["due_date"])
            O_b = len(blk["shape"])
            ml = []
            for o in range(O_b):
                mask, (w, h, offx, offy) = _rp_rasterize(blk, o, self.g)
                ml.append((mask, w, h, offx, offy))
            self.masks[b] = ml
        # Per-block per-orient cached helpers for the VECTORIZED BL search:
        #   - msum: number of True cells (correlation == 0 <=> no collision)
        #   - mflip: 180-rotated mask (correlation kernel for fftconvolve)
        #   - mf:    float32 view of the mask (for fast correlation / SAT use)
        self.msum = {}
        self.mflip = {}
        self.mf = {}
        for b in self.ids:
            ml = self.masks[b]
            sl = []; fl = []; ff = []
            for (mask, w, h, offx, offy) in ml:
                if mask is None:
                    sl.append(0); fl.append(None); ff.append(None)
                    continue
                mf = mask.astype(_np.float32)
                sl.append(int(mask.sum()))
                fl.append(mf[::-1, ::-1].copy())  # 180-rot kernel for fftconvolve
                ff.append(mf)
            self.msum[b] = sl
            self.mflip[b] = fl
            self.mf[b] = ff
        # horizon bound so entry walks always terminate
        cur_makespan = max(int(recs[b]["exit_time"]) for b in self.ids)
        max_due = max(self.D[b] for b in self.ids)
        maxP = max(self.P[b] for b in self.ids)
        self.Hmax = max(cur_makespan, max_due) + maxP + 1

    # -- placement <-> record conversion --------------------------------------
    def placement_from_record(self, b):
        """Seed a placement (o, gx, gy, entry) from the block's ORIGINAL record.
        Returns None if the original orientation's mask is unavailable."""
        rec = self.recs[b]
        ml = self.masks[b]
        o0 = int(rec["orient_idx"])
        if o0 < 0 or o0 >= len(ml):
            o0 = 0
        mask, w, h, offx, offy = ml[o0]
        if mask is None:
            return None
        gx0 = (int(rec["x"]) + offx) // self.g
        gy0 = (int(rec["y"]) + offy) // self.g
        return (o0, int(gx0), int(gy0), int(rec["entry_time"]))

    def exit_of(self, b, entry):
        return int(entry) + self.P[b]

    def tard_of(self, b, entry):
        return max(0, self.exit_of(b, entry) - self.D[b])

    def cost(self, layout):
        """Total tardiness of a full-bay layout {b:(o,gx,gy,entry)}."""
        return sum(self.tard_of(b, layout[b][3]) for b in layout)

    def record_for(self, b, placement):
        o, gx, gy, entry = placement
        mask, w, h, offx, offy = self.masks[b][o]
        anchor_x = gx * self.g - offx
        anchor_y = gy * self.g - offy
        rec = self.recs[b]
        return {
            "block_id": b,
            "bay_id": rec["bay_id"],
            "x": int(anchor_x),
            "y": int(anchor_y),
            "orient_idx": int(o),
            "entry_time": int(entry),
            "exit_time": int(self.exit_of(b, entry)),
        }

    # -- raster occupancy ------------------------------------------------------
    def blocked_grid(self, layout, skip, entry, exit_t):
        """Bool (Hc x Wc) OR-mask of every placed block in `layout` (except ids in
        `skip`) whose [entry',exit') overlaps [entry,exit_t).  Used as the free-space
        oracle for a bottom-left scan -- raster non-overlap => true non-overlap."""
        grid_b = _np.zeros((self.Hc, self.Wc), dtype=bool)
        for ob, pl in layout.items():
            if ob in skip:
                continue
            po, pgx, pgy, pe = pl
            px = self.exit_of(ob, pe)
            if exit_t <= pe or entry >= px:
                continue  # time-disjoint
            pmask, pw, ph, _ox, _oy = self.masks[ob][po]
            y0 = pgy; y1 = pgy + pmask.shape[0]
            x0 = pgx; x1 = pgx + pmask.shape[1]
            if y0 < 0: y0 = 0
            if x0 < 0: x0 = 0
            if y1 > self.Hc: y1 = self.Hc
            if x1 > self.Wc: x1 = self.Wc
            if y0 >= y1 or x0 >= x1:
                continue
            sub = pmask[y0 - pgy: y1 - pgy, x0 - pgx: x1 - pgx]
            grid_b[y0:y1, x0:x1] |= sub
        return grid_b

    def bl_fit(self, grid_b, b):
        """Bottom-left fit of any orientation of block b into the free space of
        grid_b.  Returns (o, gx, gy) of the first (BL) collision-free spot, else
        None.

        VECTORIZED (the throughput lever).  The old version triple-looped
        (gy x gx x orient) in pure Python with a numpy slice + .any() per cell --
        O(Hc*Wc*orients) Python iterations, each paying numpy call overhead, so
        ~10 iters/s on a 100-block bay.  Here we instead compute, PER ORIENTATION,
        the 2D cross-correlation of the occupancy grid with the block mask in ONE
        numpy/scipy call: corr[gy,gx] = number of (mask AND grid) overlap cells at
        top-left (gy,gx).  corr == 0  <=>  collision-free placement (raster mask is
        a SUPERSET of the polygon, so raster non-overlap => true non-overlap, exact
        same correctness as the per-cell test).  We then take the lowest-(gy,gx)
        zero across orientations -- identical BL tie-break (rows, then cols, then
        orient order) to the scalar version."""
        ml = self.masks[b]
        Hc, Wc = self.Hc, self.Wc
        best = None  # (gy, gx, o)
        gridf = None  # lazy float view (only built if any orient fits the bay)
        for o in range(len(ml)):
            mask, w, h, offx, offy = ml[o]
            if mask is None:
                continue
            mh, mw = mask.shape
            if mh > Hc or mw > Wc:
                continue  # orientation cannot fit the bay at all
            valid_h = Hc - mh + 1
            valid_w = Wc - mw + 1
            if valid_h <= 0 or valid_w <= 0:
                continue
            msum = self.msum[b][o]
            if msum <= 0:
                # Degenerate empty mask -> any in-bounds top-left is "free".
                gy, gx = 0, 0
            else:
                if gridf is None:
                    gridf = grid_b.astype(_np.float32)
                # corr (valid region) = # overlapping True cells at each top-left.
                if _HAVE_SCIPY:
                    corr = _fftconvolve(gridf, self.mflip[b][o], mode="valid")
                    free = corr < 0.5  # ==0 (float round); collision-free spots
                else:
                    free = self._corr_free_sat(grid_b, self.mf[b][o],
                                               valid_h, valid_w)
                # earliest (lowest gy, then gx) zero -- the BL spot for this orient.
                ys, xs = _np.nonzero(free[:valid_h, :valid_w])
                if ys.size == 0:
                    continue
                # argmin over (gy, gx): rows dominate, then cols.
                lin = ys.astype(_np.int64) * valid_w + xs.astype(_np.int64)
                k = int(_np.argmin(lin))
                gy = int(ys[k]); gx = int(xs[k])
            cand = (gy, gx, o)
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best is None:
            return None
        gy, gx, o = best
        return (o, gx, gy)

    @staticmethod
    def _corr_free_sat(grid_b, maskf, valid_h, valid_w):
        """Fallback (no scipy) vectorized correlation==0 map via an explicit
        sliding-window accumulate over the mask's True cells only.  Returns a bool
        array (>= valid_h x valid_w) True where the placement is collision-free.
        Vectorized over the whole (gy,gx) grid per mask cell, so it costs
        O(#mask_true_cells) numpy ops rather than O(Hc*Wc) Python iterations."""
        mh, mw = maskf.shape
        acc = _np.zeros((valid_h, valid_w), dtype=_np.float32)
        ys, xs = _np.nonzero(maskf > 0.5)
        for dy, dx in zip(ys.tolist(), xs.tolist()):
            acc += grid_b[dy:dy + valid_h, dx:dx + valid_w]
        return acc < 0.5

    def candidate_entries(self, b, layout, skip):
        """Ascending entry times to try: release first (zero tardiness), then every
        OTHER placed block's exit at/after release (a footprint may clear then)."""
        base = self.R[b]
        cand = {base}
        for ob, pl in layout.items():
            if ob in skip or ob == b:
                continue
            px = self.exit_of(ob, pl[3])
            if px >= base:
                cand.add(px)
        cand = sorted(t for t in cand if t <= self.Hmax)
        return cand or [base]

    # -- real-checker validation (stacking + final bay) ------------------------
    def bay_real_feasible(self, layout):
        """Full-bay REAL crane/collision re-validation via rasterpack's helper.
        Returns True iff the official checker would accept this bay.  Conservative
        (False on any failure / missing bay_obj)."""
        if self.bay_obj is None:
            return False
        pls = []
        for b, pl in layout.items():
            o, gx, gy, entry = pl
            mask, w, h, offx, offy = self.masks[b][o]
            ax = gx * self.g - offx
            ay = gy * self.g - offy
            obj = _rp_make_block(self.blocks, b, ax, ay, o)
            if obj is None:
                return False
            pls.append((b, obj, int(entry), int(self.exit_of(b, entry))))
        return bool(_rp_bay_crane_feasible(self.bay_obj, pls))

    def try_stack(self, b, o, gx, gy, entry, layout, skip):
        """Try to place b at (o,gx,gy,entry) as a STACKED/co-present block (footprint
        overlaps some placed block) and VALIDATE with the REAL checker, biasing
        [entry,exit) toward a LIFO nest.  Returns entry_used or None.  Mirrors
        rasterpack._try_stack semantics (real-checker is the oracle)."""
        if self.bay_obj is None:
            return None
        mask, w, h, offx, offy = self.masks[b][o]
        ax = gx * self.g - offx
        ay = gy * self.g - offy
        cand_obj = _rp_make_block(self.blocks, b, ax, ay, o)
        if cand_obj is None:
            return None
        # LIFO bias: nest inside footprint-overlapping placed blocks' intervals.
        mh, mw = mask.shape
        ov = []
        for ob, pl in layout.items():
            if ob in skip or ob == b:
                continue
            po, pgx, pgy, pe = pl
            pmask, pw, ph, _ox, _oy = self.masks[ob][po]
            ox0 = max(gx, pgx); oy0 = max(gy, pgy)
            ox1 = min(gx + mw, pgx + pmask.shape[1])
            oy1 = min(gy + mh, pgy + pmask.shape[0])
            if ox0 >= ox1 or oy0 >= oy1:
                continue
            sa = mask[oy0 - gy: oy1 - gy, ox0 - gx: ox1 - gx]
            sb = pmask[oy0 - pgy: oy1 - pgy, ox0 - pgx: ox1 - pgx]
            if _np.logical_and(sa, sb).any():
                ov.append(self.exit_of(ob, pe))  # not strictly the entry, but bias up
        entries_to_try = [entry]
        if ov:
            lo = max(ov)
            if lo > entry:
                entries_to_try.append(lo)
        # build the (existing - skip) placement set once, append candidate per entry.
        base_pls = []
        for ob, pl in layout.items():
            if ob in skip or ob == b:
                continue
            po, pgx, pgy, pe = pl
            pmask, pw, ph, pofx, pofy = self.masks[ob][po]
            pax = pgx * self.g - pofx
            pay = pgy * self.g - pofy
            pobj = _rp_make_block(self.blocks, ob, pax, pay, po)
            if pobj is None:
                return None
            base_pls.append((ob, pobj, int(pe), int(self.exit_of(ob, pe))))
        for et in entries_to_try:
            if et < self.R[b]:
                et = self.R[b]
            xt = self.exit_of(b, et)
            pls = list(base_pls)
            pls.append((b, cand_obj, int(et), int(xt)))
            if _rp_bay_crane_feasible(self.bay_obj, pls):
                return int(et)
        return None

    def best_insert(self, b, layout, skip, deadline, stack_on, stack_tries):
        """Find the MIN-TARDINESS crane-feasible placement of block b given the
        current layout minus `skip`.  Returns a placement (o,gx,gy,entry) or None.

        Strategy = rasterpack's repair, per block: walk candidate entries ascending
        (release first); at each entry do a bottom-left raster fit against the
        time-overlap occupancy.  The FIRST entry with a non-overlap BL spot wins
        (earliest entry => minimal tardiness).  At the earliest (release) entry, if
        no clean spot exists, optionally try crane-LIFO STACKING (real-checker
        validated) so a delayed block can still enter at/near release."""
        cents = self.candidate_entries(b, layout, skip)
        for ei, entry in enumerate(cents):
            if time.monotonic() >= deadline:
                return None
            exit_t = self.exit_of(b, entry)
            grid_b = self.blocked_grid(layout, skip, entry, exit_t)
            fit = self.bl_fit(grid_b, b)
            if fit is not None:
                o, gx, gy = fit
                return (o, gx, gy, entry)
            # v2 crane-safe stacking, only at the earliest (release) entry where the
            # block would otherwise be DELAYED.
            if stack_on and self.bay_obj is not None and ei == 0 and stack_tries > 0:
                tries = 0
                ml = self.masks[b]
                for gy in range(0, self.Hc):
                    if tries >= stack_tries:
                        break
                    if time.monotonic() >= deadline:
                        return None
                    for gx in range(0, self.Wc):
                        if tries >= stack_tries:
                            break
                        for o in range(len(ml)):
                            mask, w, h, offx, offy = ml[o]
                            mh, mw = mask.shape
                            if gx + mw > self.Wc or gy + mh > self.Hc:
                                continue
                            sub = grid_b[gy:gy + mh, gx:gx + mw]
                            if not (mask & sub).any():
                                continue  # clean spot already tried by bl_fit
                            tries += 1
                            et = self.try_stack(b, o, gx, gy, entry, layout, skip)
                            if et is not None:
                                return (o, gx, gy, et)
                            if tries >= stack_tries:
                                break
        return None


# -----------------------------------------------------------------------------
# Per-bay ALNS outer loop.
# -----------------------------------------------------------------------------
def _lns_bay(W, H, ids, recs, blocks, cur_bay_tard, grid, bay_deadline,
             bay_obj, k_lo, k_hi, use_sa, rng, info=None):
    """Run LNS on one bay until bay_deadline.  Returns (out_records, n_iters,
    n_accepts) where out_records is {b: record} ONLY if a strictly lower bay
    tardiness AND a real-checker-feasible layout was found, else None.  Never
    raises (returns (None, iters, accepts) on error)."""
    def _rec(status, new_tard=None, err=None):
        try:
            if info is not None:
                info["status"] = status
                info["new_tard"] = new_tard
                info["err"] = err
        except Exception:
            pass

    n_iters = 0
    n_accepts = 0
    if _np is None or not _HAVE_RP:
        _rec("error", err="numpy/rasterpack unavailable")
        return None, n_iters, n_accepts
    try:
        st = _BayLNS(W, H, ids, recs, blocks, grid, bay_obj)

        # ---- Seed = original layout (guaranteed feasible) -------------------
        cur = {}
        for b in ids:
            pl = st.placement_from_record(b)
            if pl is None:
                _rec("error", err=f"seed placement for block {b} failed")
                return None, n_iters, n_accepts
            cur[b] = pl
        cur_cost = st.cost(cur)
        best = dict(cur)
        best_cost = cur_cost
        # The seed reproduces the ORIGINAL crane-feasible layout, so we already
        # know a feasible incumbent exists; we only ever ADOPT a layout we re-
        # validate below, so we never need to trust the seed's geometry blindly.

        stack_on = _env_on("OGC_RP_STACK", True)
        stack_tries = _env_int("OGC_LNS_STACK_TRIES", 12)

        # ---- ALNS destroy-operator weights (adaptive) ----------------------
        # 0 = worst-removal, 1 = related-removal, 2 = random-removal,
        # 3 = TIME-SHIFT removal (remove a tardy block AND everything occupying
        #     its desired earlier window so room is actually freed -- the
        #     backtracking move the greedy can't make; see op==3 below).
        NOPS = 4
        op_w = [1.0] * NOPS
        op_score = [0.0] * NOPS
        op_use = [0] * NOPS
        reaction = 0.2  # weight smoothing

        # ---- SA temperature schedule (only if use_sa) ----------------------
        # Start temp ~ a few % of the seed cost (a worsening of a few cost units
        # is accepted with ~e^-1 prob early on) and cool GEOMETRICALLY to ~0 over
        # the budget so late iterations are nearly greedy.  The prior schedule
        # (linear cool to 0.1, window = cur+t_start) accepted almost nothing
        # because most repair worsenings exceed a tiny t_start; we widen the
        # acceptance window and start hotter so SA actually explores.
        sa_frac = _env_float("OGC_LNS_SA_FRAC", 0.05)   # start temp = frac*cost
        t_start = max(2.0, sa_frac * max(1.0, cur_cost))
        t_end = max(1e-3, _env_float("OGC_LNS_SA_TEND", 0.05))
        cool = (t_end / t_start)  # geometric cooling target ratio
        t_enter = time.monotonic()
        total_span = max(1e-6, bay_deadline - t_enter)

        order_by_due = sorted(ids, key=lambda b: (st.D[b], st.R[b], b))
        n_best_improves = 0  # global-best updates (kept distinct from accepts)
        K_BOOST = _env_float("OGC_LNS_K_BOOST", 1.0)  # multiplies adaptive K hi

        while time.monotonic() < bay_deadline:
            n_iters += 1
            # ---- choose destroy size K (adaptive within [k_lo,k_hi]) --------
            # More AGGRESSIVE destroy: scale the upper bound with bay size (a
            # 100-block bay needs to free more than 8 blocks to relocate a wedged
            # one) and with K_BOOST.  Still bounded by len(ids)-1.
            k_hi_eff = max(k_hi, int(round(k_hi * K_BOOST)))
            k_hi_eff = max(k_hi_eff, min(len(ids) - 1, max(k_hi, len(ids) // 6)))
            k_max = min(k_hi_eff, len(ids) - 1) if len(ids) > 1 else 1
            k_max = max(k_lo, k_max)
            K = rng.randint(min(k_lo, k_max), k_max)

            # ---- choose destroy operator (roulette) ------------------------
            tot_w = sum(op_w)
            r = rng.random() * tot_w
            op = 0
            acc = 0.0
            for i in range(NOPS):
                acc += op_w[i]
                if r <= acc:
                    op = i
                    break
            op_use[op] += 1

            # tardy blocks in the CURRENT layout (targets for worst/related).
            tardy = [b for b in ids if st.tard_of(b, cur[b][3]) > 0]

            removed = set()
            if op == 0:
                # worst-removal: the K most-tardy blocks.
                cand = sorted(tardy, key=lambda b: st.tard_of(b, cur[b][3]),
                              reverse=True)
                for b in cand[:K]:
                    removed.add(b)
                # top up with random if too few tardy.
                if len(removed) < K:
                    pool = [b for b in ids if b not in removed]
                    rng.shuffle(pool)
                    for b in pool[:K - len(removed)]:
                        removed.add(b)
            elif op == 1:
                # related-removal: a seed tardy block + blocks whose footprint/time
                # neighborhood overlaps the seed's DESIRED earlier window (they are
                # what blocks it from entering at release).
                if tardy:
                    seed = rng.choice(tardy)
                else:
                    seed = rng.choice(ids)
                removed.add(seed)
                so, sgx, sgy, _se = cur[seed]
                smask, sw, sh, _sox, _soy = st.masks[seed][so]
                smh, smw = smask.shape
                want_entry = st.R[seed]
                want_exit = want_entry + st.P[seed]
                rel = []
                for ob in ids:
                    if ob == seed:
                        continue
                    oo, ogx, ogy, oe = cur[ob]
                    ox = st.exit_of(ob, oe)
                    # time-overlap with the seed's DESIRED early window?
                    if want_exit <= oe or want_entry >= ox:
                        continue
                    omask, ow, oh, _o1, _o2 = st.masks[ob][oo]
                    omh, omw = omask.shape
                    # footprint bbox overlap with the seed's CURRENT footprint?
                    bx0 = max(sgx, ogx); by0 = max(sgy, ogy)
                    bx1 = min(sgx + smw, ogx + omw)
                    by1 = min(sgy + smh, ogy + omh)
                    if bx0 < bx1 and by0 < by1:
                        rel.append(ob)
                rng.shuffle(rel)
                for ob in rel[:max(0, K - 1)]:
                    removed.add(ob)
                if len(removed) < K:
                    pool = [b for b in ids if b not in removed]
                    rng.shuffle(pool)
                    for b in pool[:K - len(removed)]:
                        removed.add(b)
            elif op == 2:
                # random-removal.
                pool = list(ids)
                rng.shuffle(pool)
                for b in pool[:K]:
                    removed.add(b)
            else:
                # ---- TIME-SHIFT removal (op == 3) --------------------------
                # Pick a tardy block and remove it together with EVERYTHING that
                # is currently spatially+temporally occupying the [release, want_
                # exit) window it WANTS to move into.  Unlike related-removal
                # (which only frees footprint-bbox neighbours of the seed's
                # CURRENT spot), this clears the seed's DESIRED EARLIER footprint
                # column across its whole wanted interval, so on repair the seed
                # can actually enter at/near release.  This is the backtracking
                # the forward greedy cannot do: it removes the blocks that boxed
                # the tardy block out of its early slot and re-packs them all.
                if tardy:
                    seed = rng.choice(tardy)
                else:
                    seed = rng.choice(ids)
                removed.add(seed)
                so, sgx, sgy, _se = cur[seed]
                smask, sw, sh, _sox, _soy = st.masks[seed][so]
                smh, smw = smask.shape
                want_entry = st.R[seed]
                want_exit = want_entry + st.P[seed]
                cl = []
                for ob in ids:
                    if ob == seed:
                        continue
                    oo, ogx, ogy, oe = cur[ob]
                    ox = st.exit_of(ob, oe)
                    # overlaps the seed's DESIRED EARLY window in TIME?
                    if want_exit <= oe or want_entry >= ox:
                        continue
                    omask, ow, oh, _o1, _o2 = st.masks[ob][oo]
                    omh, omw = omask.shape
                    # any X-column overlap with the seed's footprint band?  (We
                    # are generous in Y: clearing the whole column lets the seed
                    # drop to a BL spot inside it.)
                    if ogx + omw <= sgx or ogx >= sgx + smw:
                        continue
                    cl.append((ob, st.tard_of(ob, oe)))
                # prefer to evict NON-tardy occupiers first (they can absorb a
                # small delay more cheaply); cap at K so repair stays tractable.
                cl.sort(key=lambda t: t[1])
                for ob, _t in cl[:max(0, K - 1)]:
                    removed.add(ob)
                if len(removed) < 2 and cl:
                    removed.add(cl[0][0])

            if not removed:
                continue

            # ---- REPAIR: re-insert removed blocks, EDD order ----------------
            trial = {b: cur[b] for b in ids if b not in removed}
            ins_order = sorted(removed, key=lambda b: (st.D[b], st.R[b], b))
            ok = True
            for b in ins_order:
                if time.monotonic() >= bay_deadline:
                    ok = False
                    break
                pl = st.best_insert(b, trial, set(), bay_deadline,
                                    stack_on, stack_tries)
                if pl is None:
                    ok = False
                    break
                trial[b] = pl
            if not ok or len(trial) != len(ids):
                # could not rebuild a complete bay this iteration -> discard.
                # (decay the operator weight a touch so a chronically-failing
                # operator is used less.)
                op_w[op] = max(0.05, (1 - reaction) * op_w[op]
                               + reaction * 0.1)
                continue

            trial_cost = st.cost(trial)

            # ---- ACCEPT -----------------------------------------------------
            accept = False
            improved = trial_cost < cur_cost - 1e-9
            if improved:
                accept = True
            elif use_sa:
                # SA: accept ANY worsening with prob exp(-delta/temp).  Temp cools
                # GEOMETRICALLY from t_start to ~t_end over the budget so early
                # iterations explore (escape local optima) and late ones exploit.
                # (No t_start clamp on the window -- a big worsening just gets a
                # tiny accept prob, which is the correct SA behaviour and is what
                # lets the search climb OUT of a deep greedy basin.)
                frac = (time.monotonic() - t_enter) / total_span
                if frac > 1.0:
                    frac = 1.0
                temp = max(t_end, t_start * (cool ** frac))
                delta = trial_cost - cur_cost
                try:
                    if rng.random() < math.exp(-delta / max(1e-6, temp)):
                        accept = True
                except Exception:
                    accept = False

            # ALNS reward: new global best > improved-current > accepted.
            reward = 0.0
            if trial_cost < best_cost - 1e-9:
                reward = 3.0
            elif improved:
                reward = 1.0
            elif accept:
                reward = 0.3
            op_score[op] += reward
            # smooth the operator weight toward its average reward.
            avg = (op_score[op] / op_use[op]) if op_use[op] else 0.0
            op_w[op] = max(0.05, (1 - reaction) * op_w[op] + reaction
                           * (0.1 + avg))

            if accept:
                cur = trial
                cur_cost = trial_cost
                n_accepts += 1  # any move adopted as the new current
                if cur_cost < best_cost - 1e-9:
                    best = dict(cur)
                    best_cost = cur_cost
                    n_best_improves += 1

        _dbg(f"    bay loop: iters={n_iters} accepts={n_accepts} "
             f"best_improves={n_best_improves} "
             f"best_cost={int(best_cost)} (was {int(cur_bay_tard)}) "
             f"op_use={op_use}")

        # ---- Evaluate best vs current bay tardiness ------------------------
        if best_cost >= cur_bay_tard - 1e-9:
            _rec("noop", new_tard=int(best_cost))
            return None, n_iters, n_accepts

        # ---- FINAL full-bay REAL-checker re-validation ---------------------
        # Per-insertion checks are necessary but not globally sufficient (a later
        # block can box an earlier one in), so re-validate the whole accepted bay.
        if not st.bay_real_feasible(best):
            _rec("noop", err="final bay real-checker re-validation failed",
                 new_tard=int(best_cost))
            return None, n_iters, n_accepts

        out = {b: st.record_for(b, best[b]) for b in ids}
        _rec("improved", new_tard=int(best_cost))
        return out, n_iters, n_accepts
    except Exception as e:
        if _env_on("OGC_LNS_DEBUG", False):
            import traceback
            sys.stderr.write("[lns] EXCEPTION in _lns_bay():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _rec("error", err=str(e)[:200])
        return None, n_iters, n_accepts


# -----------------------------------------------------------------------------
# Public contract (mirrors perbay.improve() / rasterpack.improve()).
# -----------------------------------------------------------------------------
def improve(prob_info: dict, sol: dict, time_budget: float) -> dict:
    """LNS over the full solution, minimizing total tardiness (z1) within each bay
    (assignment FIXED => z2/z3 invariant).  Returns an improved solution dict if
    some bay strictly reduced its tardiness (and the bay re-validates with the real
    checker), else returns the SAME `sol` object (identity).  NEVER raises.
    Deadline-bounded by time_budget seconds from entry."""
    t_enter = time.monotonic()
    deadline = t_enter + float(time_budget)

    # ---- Telemetry (additive, best-effort; same schema as rasterpack) -------
    _log_path = ""
    try:
        _log_path = os.environ.get("OGC_PERBAY_LOG", "").strip()
    except Exception:
        _log_path = ""
    _tel_bays = []
    _tel_z1_before = 0.0
    _tel_z1_after = 0.0
    _tel_n_blocks_total = 0
    _tel_n_bays_total = 0
    _tel_n_work_bays = 0
    _tel_iters = 0
    _tel_accepts = 0
    if _log_path:
        try:
            _tel_n_blocks_total = len(prob_info.get("blocks", {}))
            _tel_n_bays_total = len(prob_info.get("bays", {}))
        except Exception:
            pass

    def _emit_log(fired_flag):
        if not _log_path:
            return
        try:
            record = {
                "event": "lns_improve",
                "time_budget": float(time_budget),
                "n_blocks_total": int(_tel_n_blocks_total),
                "n_bays_total": int(_tel_n_bays_total),
                "n_work_bays": int(_tel_n_work_bays),
                "fired": bool(fired_flag),
                "total_wall": float(time.monotonic() - t_enter),
                "z1_before": float(_tel_z1_before),
                "z1_after": float(_tel_z1_after),
                "iters": int(_tel_iters),
                "accepts": int(_tel_accepts),
                "bays": _tel_bays,
            }
            import json as _json
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(record) + "\n")
                _f.flush()
        except Exception:
            if _env_on("OGC_LNS_DEBUG", False):
                import traceback
                sys.stderr.write("[lns] EXCEPTION in _emit_log():\n")
                traceback.print_exc()
                sys.stderr.flush()

    try:
        if _np is None or not _HAVE_RP:
            _dbg("numpy/rasterpack unavailable -> return sol (NOOP)")
            _emit_log(False)
            return sol

        # Lazy import to avoid a circular import at module load.
        from myalgorithm import _results_from_solution
        from baseline_greedy import _build_operations
        try:
            from utils import Bay as _Bay
        except Exception:
            _Bay = None

        blocks = prob_info["blocks"]
        bays = prob_info["bays"]

        _assign, results, _flat = _results_from_solution(prob_info, sol)

        # Per-bay current tardiness; keep only bays with a recoverable gap.
        work = []  # (bay_idx, ids, cur_tard)
        for j, by_id in results.items():
            if not by_id:
                continue
            ids = list(by_id)
            cur_tard = sum(
                max(0, int(by_id[b]["exit_time"]) - int(blocks[b]["due_date"]))
                for b in ids
            )
            if cur_tard <= 0:
                continue  # cannot reduce z1 below 0 by re-packing
            work.append((j, ids, cur_tard))

        _dbg(f"work bays (cur_tard>0): {len(work)} -> "
             f"{[(j, len(ids), ct) for (j, ids, ct) in work]}")
        _tel_n_work_bays = len(work)
        if _log_path:
            _tel_z1_before = float(sum(ct for (_j, _ids, ct) in work))
            _tel_z1_after = _tel_z1_before
        if not work:
            _dbg("no work bays found -> return sol (NOOP)")
            _emit_log(False)
            return sol

        # Biggest payoff first.
        work.sort(key=lambda t: t[2], reverse=True)

        maxn = _env_int("OGC_LNS_MAXN", 200)
        bay_cap = _env_float("OGC_LNS_BAY_S", 0.0)  # 0 => no per-bay cap
        grid = _env_int("OGC_RP_GRID", 1)
        k_lo = _env_int("OGC_LNS_K_LO", 3)
        k_hi = _env_int("OGC_LNS_K", 8)  # OGC_LNS_K = adaptive upper bound
        if k_hi < k_lo:
            k_hi = k_lo
        use_sa = _env_on("OGC_LNS_SA", False)
        seed = _env_int("OGC_LNS_SEED", 12345)
        _dbg(f"OGC_LNS_MAXN={maxn} OGC_LNS_BAY_S={bay_cap} grid={grid} "
             f"K=[{k_lo},{k_hi}] SA={use_sa} budget={time_budget:.1f}s")

        # Skip bays too large for the BL scan.
        kept = [(j, ids, ct) for (j, ids, ct) in work if len(ids) <= maxn]
        for (j, ids, ct) in work:
            if len(ids) > maxn:
                _dbg(f"  bay {j}: SKIP n={len(ids)} > maxn={maxn} (cur_tard={ct})")
                if _log_path:
                    _tel_bays.append({
                        "bay": int(j), "n_blocks": len(ids),
                        "cur_tard": float(ct), "new_tard": None,
                        "wall": 0.0, "status": "skipped_maxn", "err": None,
                        "iters": 0, "accepts": 0,
                    })
        work = kept
        if not work:
            _dbg("all work bays filtered by maxn -> return sol (NOOP)")
            _emit_log(False)
            return sol

        improved_any = False
        new_results = None
        remaining_bays = len(work)
        rng = random.Random(seed)

        _tel_done_bays = set()
        for (j, ids, cur_tard) in work:
            now = time.monotonic()
            if deadline - now < 1.0:
                _dbg(f"  bay {j}: SKIP deadline ({deadline - now:.2f}s left < 1.0)")
                if _log_path:
                    for (jj, iids, cct) in work:
                        if jj in _tel_done_bays:
                            continue
                        _tel_bays.append({
                            "bay": int(jj), "n_blocks": len(iids),
                            "cur_tard": float(cct), "new_tard": None,
                            "wall": 0.0, "status": "noop",
                            "err": "deadline reached before solve",
                            "iters": 0, "accepts": 0,
                        })
                break
            per_bay = (deadline - now) / max(1, remaining_bays)
            if bay_cap > 0:
                per_bay = min(per_bay, bay_cap)
            remaining_bays -= 1
            if per_bay < 0.5:
                _dbg(f"  bay {j}: SKIP per_bay={per_bay:.2f}s < 0.5")
                if _log_path:
                    _tel_bays.append({
                        "bay": int(j), "n_blocks": len(ids),
                        "cur_tard": float(cur_tard), "new_tard": None,
                        "wall": 0.0, "status": "noop",
                        "err": f"per_bay budget {per_bay:.2f}s < 0.5s",
                        "iters": 0, "accepts": 0,
                    })
                    _tel_done_bays.add(j)
                continue

            by_id = results[j]
            W = int(bays[j]["width"]); H = int(bays[j]["height"])
            bay_deadline = now + per_bay
            bay_obj = None
            if _Bay is not None:
                try:
                    bay_obj = _Bay.from_dict(bays[j], j)
                except Exception:
                    try:
                        bay_obj = _Bay(width=W, height=H, id=j)
                    except Exception:
                        bay_obj = None
            _dbg(f"  bay {j}: LNS n={len(ids)} cur_tard={cur_tard} "
                 f"per_bay={per_bay:.1f}s W={W} H={H}")
            _bay_info = {} if _log_path else None
            _bay_t0 = time.monotonic()
            res, n_it, n_ac = _lns_bay(
                W, H, ids, by_id, blocks, cur_tard, grid, bay_deadline,
                bay_obj, k_lo, k_hi, use_sa, rng, info=_bay_info)
            _bay_wall = time.monotonic() - _bay_t0
            _tel_iters += n_it
            _tel_accepts += n_ac
            if res:
                if new_results is None:
                    new_results = {jj: dict(bb) for jj, bb in results.items()}
                new_results[j] = res
                improved_any = True
                _dbg(f"  bay {j}: IMPROVED (iters={n_it} accepts={n_ac})")
            else:
                _dbg(f"  bay {j}: no improvement (iters={n_it} accepts={n_ac})")
            if _log_path:
                _status = (_bay_info or {}).get("status", "noop")
                _new_tard = (_bay_info or {}).get("new_tard", None)
                _err = (_bay_info or {}).get("err", None)
                if _status == "improved" and _new_tard is not None:
                    _tel_z1_after += float(_new_tard) - float(cur_tard)
                _tel_bays.append({
                    "bay": int(j), "n_blocks": len(ids),
                    "cur_tard": float(cur_tard),
                    "new_tard": (None if _new_tard is None else float(_new_tard)),
                    "wall": float(_bay_wall), "status": _status, "err": _err,
                    "iters": int(n_it), "accepts": int(n_ac),
                })
                _tel_done_bays.add(j)

        if not improved_any:
            _dbg("no bay improved -> return sol (NOOP)")
            _emit_log(False)
            return sol

        new_flat = [dict(a) for by in new_results.values() for a in by.values()]
        _emit_log(True)
        return {"operations": _build_operations(new_flat)}
    except Exception:
        if _env_on("OGC_LNS_DEBUG", False):
            import traceback
            sys.stderr.write("[lns] EXCEPTION in improve():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _emit_log(False)
        return sol


def algorithm(prob_info: dict, timelimit: float) -> dict:
    """Isolated-testing entry: build a baseline via myalgorithm._legacy_algorithm,
    then polish it with improve().  Minimal and never-raises (fallback: return the
    baseline solution, or an empty-ish well-formed solution)."""
    t0 = time.monotonic()
    sol = None
    try:
        import myalgorithm
        sol = myalgorithm._legacy_algorithm(prob_info, timelimit * 0.5)
    except Exception:
        sol = None
    if sol is None:
        return {"operations": {}}
    try:
        remaining = max(0.0, timelimit - (time.monotonic() - t0))
        return improve(prob_info, sol, remaining)
    except Exception:
        return sol
