# perbay_t3.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Per-bay CANDIDATE SET-PACKING (T3) placement+timing engine.
#
# This is the ALTERNATIVE to src/perbay.py.  perbay.py treats each block's
# (x, y) as FREE integer vars with pairwise NoOverlap2D disjunctions (T2 free
# placement + T6 crane-stacking hook).  T3 instead PRE-COMPUTES, per block, a
# small discrete set of DENSE bottom-left candidate placements (x, y, orient)
# and lets CP-SAT pick exactly ONE candidate per block plus the timing -- the
# spatial degrees of freedom collapse from a continuous lattice to a handful of
# columns, and the only pairwise constraints emitted are time-disjunctions
# between candidate pairs whose conservative bboxes ACTUALLY overlap (set-
# packing sparsity).  Same interface, same safety, same telemetry as perbay so
# the SAME harness (notes/_perbay_set2.py) can A/B them.
#
# It is, like perbay, a GATED best-of CANDIDATE: a separate integration in
# myalgorithm.py adopts its output only if the official `check_feasibility`
# passes AND the objective strictly improves, all wrapped in try/except.
# Therefore this engine:
#   * NEVER raises to the caller (everything wrapped in try/except),
#   * is strictly deadline-bounded (time.monotonic()), and
#   * in the worst case returns the input solution UNCHANGED (identity).
#
# Bay ASSIGNMENT stays fixed, so Z2 (load imbalance) and Z3 (preference) are
# provably invariant -- only per-bay tardiness Z1 changes.  We only touch bays
# whose current tardiness > 0 (repositioning can never push Z1 below 0).
#
# SAFETY MODEL (identical to perbay, verified from utils.py):
#   If two co-present blocks' conservative bounding boxes do NOT overlap in
#   (x,y), then no collision and no crane obstruction can fire at ANY layer.
#   Every candidate placement we generate is conservatively bbox-contained and
#   in-bounds (perbay's fixed `_orient_geom` floor/ceil formula), so a chosen-
#   candidate solution is always feasibility-safe.  For each overlapping
#   candidate pair we force time-disjointness, so bbox-separated-OR-time-
#   disjoint holds for every co-present pair (stages 2/3/4).  Conservative
#   (forbids some legal crane-stacking) but always feasible.
#
# NO-REGRESSION PER BAY: the block's CURRENT placement (from the warm-start
# sol) is always injected as one candidate, so the model can reproduce the
# existing layout exactly; we additionally gate on a STRICT improvement, so a
# bay can never get worse.

from __future__ import annotations

import math
import os
import sys
import time


# -----------------------------------------------------------------------------
# Tiny env helpers -- replicated inline (NOT imported from myalgorithm) to avoid
# importing myalgorithm at module load time (circular import).  Bit-identical to
# perbay._env_* .  All three never raise.
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
    """Stderr trace, gated by OGC_PERBAY_DEBUG (default off).  Never raises.

    Shares the SAME gate as perbay (so a single OGC_PERBAY_DEBUG lights both);
    prefixed [perbay_t3] to disambiguate which engine emitted the line."""
    try:
        if _env_on("OGC_PERBAY_DEBUG", False):
            sys.stderr.write("[perbay_t3] " + msg + "\n")
            sys.stderr.flush()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Geometry: (anchor x, y, orient o) -> conservative integer bbox in bay coords.
#
# IDENTICAL formula to perbay._orient_geom (copied so the two engines agree on
# every byte of geometry, which is what makes their A/B fair and their shared
# feasibility argument hold).  See perbay.py for the full derivation.  The
# CRITICAL invariant: the integer bbox we hand to CP-SAT must CONSERVATIVELY
# CONTAIN the true FLOAT polygon utils' checker measures -- FLOOR the min offset
# and CEIL the max extent so integer non-overlap => float non-overlap and
# integer in-bounds => float in-bounds.
#
# Returns (w, h, offminx, offminy) with bbox_left = anchor_x + offminx, i.e.
# anchor_x = bbox_left - offminx.
# -----------------------------------------------------------------------------
def _orient_geom(block_data: dict, o: int):
    raw_layers = block_data["shape"][o]["layers"]
    layers = [list(l) for l in raw_layers if l]
    if not layers:
        # Degenerate shape: utils falls back to a 1x1 box anchored at (x,y).
        return 1, 1, 0, 0
    ref_x, ref_y = layers[0][0]
    all_verts = [v for l in layers for v in l]
    min_x = min(v[0] for v in all_verts)
    min_y = min(v[1] for v in all_verts)
    max_x = max(v[0] for v in all_verts)
    max_y = max(v[1] for v in all_verts)
    offminx = int(math.floor(min_x - ref_x))
    offminy = int(math.floor(min_y - ref_y))
    w = int(math.ceil(max_x - ref_x)) - offminx
    h = int(math.ceil(max_y - ref_y)) - offminy
    if w <= 0:
        w = 1
    if h <= 0:
        h = 1
    return w, h, offminx, offminy


# -----------------------------------------------------------------------------
# Candidate generation: bottom-left dense placements per block.
#
# We generate candidates OURSELVES (own BL grid scan) rather than reusing
# fastfloor._ft_search_pos: that machinery returns ONE world-raster position
# (it screens with float layer cells + the j>=k crane predicate, and emits a
# single winner), whereas T3 needs a SET of K candidates expressed in the SAME
# conservative-bbox space the CP-SAT conflict model uses.  Generating them from
# `_orient_geom` keeps the geometry contract bit-identical to perbay (and hence
# the feasibility guarantee), and decouples candidate enumeration from
# fastfloor's raster/crane internals.  fastfloor reuse was rejected as too
# coupled for exactly this reason.
# -----------------------------------------------------------------------------
def _gen_candidates(blk: dict, W: int, H: int, placed_boxes, K: int,
                    cur):
    """Return up to K candidate placements for one block, each a dict
        {"o": orient_idx, "bx": bbox_left, "by": bbox_bottom,
         "w": width, "h": height, "ax": anchor_x, "ay": anchor_y}
    The candidates are DENSE (bottom-left abut against bay walls and the right/
    top edges of `placed_boxes`) and IN-BOUNDS (bbox fully inside [0,W]x[0,H]).

    `cur` is the block's CURRENT placement (o, bx, by, w, h, ax, ay) extracted
    from the warm-start sol; it is ALWAYS included as the first candidate so the
    model can reproduce the existing layout (no-regression guarantee per bay).

    `placed_boxes` is a static set of (x0, y0, x1, y1) conservative bboxes used
    only to seed bottom-left abut positions -- it does NOT constrain candidates
    (overlap is resolved by CP-SAT via time-disjunction), it just biases the
    enumeration toward dense spots.  A reasonable choice is the warm-start
    bboxes of the OTHER blocks in the bay.

    Candidates are kept sorted by (by, bx, o) (bottom-left first) and de-duped.
    Never raises -- on any error returns just [cur] so the bay can still
    reproduce its layout."""
    out = []
    seen = set()

    def _push(o, bx, by, w, h, ax, ay):
        if bx < 0 or by < 0 or bx + w > W or by + h > H:
            return
        key = (o, bx, by)
        if key in seen:
            return
        seen.add(key)
        out.append({"o": o, "bx": bx, "by": by, "w": w, "h": h,
                    "ax": ax, "ay": ay})

    try:
        # 1) ALWAYS include the current placement first (no-regression).
        _push(cur["o"], cur["bx"], cur["by"], cur["w"], cur["h"],
              cur["ax"], cur["ay"])

        O_b = len(blk["shape"])
        # Pre-seed abut x/y anchors from walls + placed-box edges.
        px_edges = sorted({pb[2] for pb in placed_boxes})  # right edges
        py_edges = sorted({pb[3] for pb in placed_boxes})  # top edges
        for o in range(O_b):
            w, h, offx, offy = _orient_geom(blk, o)
            if w > W or h > H:
                continue
            xs = {0, W - w}                      # left wall, right wall
            for e in px_edges:
                if 0 <= e <= W - w:
                    xs.add(e)
            ys = {0, H - h}                      # floor, ceiling
            for e in py_edges:
                if 0 <= e <= H - h:
                    ys.add(e)
            xs = sorted(x for x in xs if 0 <= x <= W - w)
            ys = sorted(y for y in ys if 0 <= y <= H - h)
            for by in ys:
                for bx in xs:
                    ax = bx - offx
                    ay = by - offy
                    _push(o, bx, by, w, h, ax, ay)
    except Exception:
        # On any failure, fall back to just the current placement.
        if not out:
            try:
                out = [{"o": cur["o"], "bx": cur["bx"], "by": cur["by"],
                        "w": cur["w"], "h": cur["h"],
                        "ax": cur["ax"], "ay": cur["ay"]}]
            except Exception:
                return []
        return out[:max(1, K)]

    # Bottom-left ordering; keep the K lowest-(y,x) (current is at index 0,
    # protect it by always retaining it).
    head = out[0]
    rest = out[1:]
    rest.sort(key=lambda c: (c["by"], c["bx"], c["o"]))
    kept = [head] + rest[: max(0, K - 1)]
    return kept


# -----------------------------------------------------------------------------
# Per-bay T3 candidate set-packing CP-SAT solve.
# -----------------------------------------------------------------------------
def _solve_bay(W, H, ids, recs, blocks, cur_bay_tard, Hmax, bay_budget,
               deadline_for_bay, info=None):
    """Re-place one bay's blocks by selecting ONE dense candidate per block plus
    the timing, to minimize this bay's total tardiness, subject to conservative
    time-disjunction on every overlapping candidate pair (the rule that
    guarantees feasibility).  Warm-started from the current layout.

    Returns a dict {block_id: record} for the WHOLE bay if a strictly lower bay
    tardiness was found, else None.  Never raises (returns None on any error).

    `info` (optional, telemetry-only): same contract as perbay._solve_bay --
    stamps "status" (one of "improved"/"noop"/"skipped_oob"/"error"),
    "new_tard" (int or None), "err" (str or None) into the passed dict without
    affecting the return value.  When `info` is None this is bit-identical."""
    def _rec(status, new_tard=None, err=None):
        try:
            if info is not None:
                info["status"] = status
                info["new_tard"] = new_tard
                info["err"] = err
        except Exception:
            pass
    try:
        from ortools.sat.python import cp_model
    except Exception:
        _rec("error", err="ortools cp_model import failed")
        return None
    try:
        K = _env_int("OGC_T3_CANDS", 12)
        if K < 1:
            K = 1

        idl = list(ids)

        # ---- Build the warm-start "current placement" for each block + sanity.
        cur_place = {}      # b -> dict(o, bx, by, w, h, ax, ay)
        P = {}; R = {}; D = {}
        for b in idl:
            blk = blocks[b]
            P[b] = int(blk["processing_time"])
            R[b] = int(blk["release_time"])
            D[b] = int(blk["due_date"])
            O_b = len(blk["shape"])
            rec = recs[b]
            ro = int(rec["orient_idx"])
            if ro < 0 or ro >= O_b:
                ro = 0
            rw, rh, roffx, roffy = _orient_geom(blk, ro)
            rbx = int(round(rec["x"])) + roffx
            rby = int(round(rec["y"])) + roffy
            # SANITY: the warm-start layout is feasible, so its conservative
            # bbox MUST lie in [0,W] x [0,H].  If not, our offset formula is
            # wrong -> bail (caller falls back to the unchanged solution).
            if not (0 <= rbx and rbx + rw <= W and 0 <= rby and rby + rh <= H):
                _dbg(f"    _solve_bay: warm-start block {b} conservative bbox "
                     f"({rbx},{rby})+({rw},{rh}) out of bay {W}x{H} -> skip bay")
                _rec("skipped_oob",
                     err=f"warm-start block {b} bbox out of bay {W}x{H}")
                return None
            cur_place[b] = {"o": ro, "bx": rbx, "by": rby, "w": rw, "h": rh,
                            "ax": int(round(rec["x"])),
                            "ay": int(round(rec["y"]))}

        # ---- Per-block candidate generation (dense BL, current always in).
        # Seed abut edges from the OTHER blocks' warm-start bboxes.
        all_boxes = [(cur_place[b]["bx"], cur_place[b]["by"],
                      cur_place[b]["bx"] + cur_place[b]["w"],
                      cur_place[b]["by"] + cur_place[b]["h"]) for b in idl]
        cands = {}          # b -> list of candidate dicts
        cur_idx = {}        # b -> index of the current placement in cands[b]
        for ix, b in enumerate(idl):
            others = all_boxes[:ix] + all_boxes[ix + 1:]
            cl = _gen_candidates(blocks[b], W, H, others, K, cur_place[b])
            if not cl:
                # Should never happen (current is always in), but guard.
                cl = [dict(cur_place[b])]
            cands[b] = cl
            # The current placement is generated first -> index 0.  Confirm by
            # matching (o, bx, by) in case ordering changed.
            ci = 0
            for i, c in enumerate(cl):
                if (c["o"] == cur_place[b]["o"]
                        and c["bx"] == cur_place[b]["bx"]
                        and c["by"] == cur_place[b]["by"]):
                    ci = i
                    break
            cur_idx[b] = ci

        # ---- CP-SAT model: select-one candidate + timing.
        m = cp_model.CpModel()
        yv = {}             # (b, c) -> BoolVar  (candidate c of block b chosen)
        entry = {}; tard = {}
        for b in idl:
            cl = cands[b]
            yb = [m.NewBoolVar(f"y_{b}_{c}") for c in range(len(cl))]
            for c in range(len(cl)):
                yv[(b, c)] = yb[c]
            m.Add(sum(yb) == 1)                  # exactly one candidate
            entry[b] = m.NewIntVar(R[b], Hmax, f"e_{b}")
            tard[b] = m.NewIntVar(0, Hmax, f"t_{b}")
            m.Add(tard[b] >= entry[b] + P[b] - D[b])

        # ---- Conflict constraints: only for candidate pairs whose conservative
        # bboxes ACTUALLY overlap (set-packing sparsity).  For each such pair,
        # selecting BOTH forces the two blocks to be time-disjoint.
        n_conf = 0
        for i in range(len(idl)):
            a = idl[i]
            ca = cands[a]
            ea = entry[a]; pa = P[a]
            for k in range(i + 1, len(idl)):
                b = idl[k]
                cb = cands[b]
                eb = entry[b]; pb = P[b]
                for ci, cda in enumerate(ca):
                    ax0 = cda["bx"]; ax1 = cda["bx"] + cda["w"]
                    ay0 = cda["by"]; ay1 = cda["by"] + cda["h"]
                    for di, cdb in enumerate(cb):
                        # Conservative bbox overlap test (open-interval touch is
                        # NOT overlap: abutting boxes share an edge only).
                        if (ax1 <= cdb["bx"] or cdb["bx"] + cdb["w"] <= ax0
                                or ay1 <= cdb["by"]
                                or cdb["by"] + cdb["h"] <= ay0):
                            continue  # non-overlapping pair: no constraint
                        # Overlapping spatial pair -> if BOTH chosen, disjoint.
                        ya = yv[(a, ci)]; yb_ = yv[(b, di)]
                        both = m.NewBoolVar("")
                        m.AddBoolAnd([ya, yb_]).OnlyEnforceIf(both)
                        m.AddBoolOr([ya.Not(), yb_.Not()]).OnlyEnforceIf(
                            both.Not())
                        # Reified time-disjunction (a before b OR b before a).
                        st_ab = m.NewBoolVar("")
                        st_ba = m.NewBoolVar("")
                        m.Add(eb >= ea + pa).OnlyEnforceIf(st_ab)
                        m.Add(ea >= eb + pb).OnlyEnforceIf(st_ba)
                        m.AddBoolOr([st_ab, st_ba]).OnlyEnforceIf(both)
                        n_conf += 1

        _dbg(f"    _solve_bay: n={len(idl)} K~{K} conflict_pairs={n_conf}")

        m.Minimize(sum(tard[b] for b in idl))

        # Warm-start hints: current candidate + current entry == the existing
        # feasible layout, so CP-SAT only polishes (never reports worse).
        for b in idl:
            m.AddHint(yv[(b, cur_idx[b])], 1)
            m.AddHint(entry[b], int(recs[b]["entry_time"]))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(max(0.5, bay_budget))
        solver.parameters.num_search_workers = _env_int("OGC_PERBAY_WORKERS", 4)
        solver.parameters.random_seed = 12345  # determinism (A/B stability)
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            _rec("noop", new_tard=None,
                 err=f"solver status {solver.StatusName(status)}")
            return None

        new_tard = sum(max(0, int(solver.Value(entry[b])) + P[b] - D[b])
                       for b in idl)
        if new_tard >= cur_bay_tard - 1e-9:
            _rec("noop", new_tard=new_tard)
            return None  # no strict improvement -> reject

        out = {}
        for b in idl:
            cl = cands[b]
            chosen = cur_idx[b]
            for c in range(len(cl)):
                if solver.Value(yv[(b, c)]) == 1:
                    chosen = c
                    break
            cd = cl[chosen]
            ev = int(solver.Value(entry[b]))
            rec = recs[b]
            out[b] = {
                "block_id": b,
                "bay_id": rec["bay_id"],
                "x": int(cd["ax"]),
                "y": int(cd["ay"]),
                "orient_idx": int(cd["o"]),
                "entry_time": ev,
                "exit_time": ev + P[b],
            }
        _rec("improved", new_tard=new_tard)
        return out
    except Exception as e:
        if _env_on("OGC_PERBAY_DEBUG", False):
            import traceback
            sys.stderr.write("[perbay_t3] EXCEPTION in _solve_bay():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _rec("error", err=str(e)[:200])
        return None


# -----------------------------------------------------------------------------
# Public contract (interface IDENTICAL to perbay.improve / perbay.algorithm).
# -----------------------------------------------------------------------------
def improve(prob_info: dict, sol: dict, time_budget: float) -> dict:
    """Polish a feasible solution by re-placing blocks within each bay using
    candidate set-packing (T3): each block picks ONE of K dense bottom-left
    candidate placements and the model re-times to minimize bay tardiness (bay
    assignment FIXED, so z2/z3 are invariant; only per-bay tardiness z1
    changes).  Returns an improved solution dict if some bay strictly reduced
    its tardiness, else returns the SAME `sol` object (identity) unchanged.
    NEVER raises.  Deadline-bounded by time_budget seconds from entry."""
    t_enter = time.monotonic()
    deadline = t_enter + float(time_budget)

    # ---- Telemetry (additive, best-effort) -- SAME schema/env as perbay so the
    # SAME harness (notes/_perbay_set2.py) measures this engine unchanged.
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
    if _log_path:
        try:
            _tel_n_blocks_total = len(prob_info.get("blocks", {}))
            _tel_n_bays_total = len(prob_info.get("bays", {}))
        except Exception:
            pass

    def _emit_log(fired_flag):
        """Append one JSON line; failure here NEVER affects the return value.

        event="perbay_improve" (UNCHANGED from perbay) so the harness keys it
        identically -- the engine identity is carried by the file path the
        caller routes each engine's log to, not the event name."""
        if not _log_path:
            return
        try:
            record = {
                "event": "perbay_improve",
                "time_budget": float(time_budget),
                "n_blocks_total": int(_tel_n_blocks_total),
                "n_bays_total": int(_tel_n_bays_total),
                "n_work_bays": int(_tel_n_work_bays),
                "fired": bool(fired_flag),
                "total_wall": float(time.monotonic() - t_enter),
                "z1_before": float(_tel_z1_before),
                "z1_after": float(_tel_z1_after),
                "bays": _tel_bays,
            }
            import json as _json
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(record) + "\n")
                _f.flush()
        except Exception:
            if _env_on("OGC_PERBAY_DEBUG", False):
                import traceback
                sys.stderr.write("[perbay_t3] EXCEPTION in _emit_log():\n")
                traceback.print_exc()
                sys.stderr.flush()

    try:
        # Lazy import to avoid a circular import at module load (myalgorithm
        # imports the perbay engines).
        from myalgorithm import _results_from_solution
        from baseline_greedy import _build_operations

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
                continue  # cannot reduce z1 below 0 by repositioning
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

        # T3 candidate-pair count grows with K^2 * pairs; OGC_T3_MAXN bounds the
        # bay size (default 100, matching perbay's OGC_PERBAY_MAXN intent).
        maxn = _env_int("OGC_T3_MAXN", 100)
        bay_cap = _env_float("OGC_T3_BAY_S", 20.0)
        _dbg(f"OGC_T3_MAXN={maxn}  OGC_T3_BAY_S={bay_cap}  "
             f"OGC_T3_CANDS={_env_int('OGC_T3_CANDS', 12)}  "
             f"budget={time_budget:.1f}s")

        # Skip bays that are too large for the candidate-pair model.
        kept = [(j, ids, ct) for (j, ids, ct) in work if len(ids) <= maxn]
        for (j, ids, ct) in work:
            if len(ids) > maxn:
                _dbg(f"  bay {j}: SKIP n={len(ids)} > maxn={maxn} (cur_tard={ct})")
                if _log_path:
                    _tel_bays.append({
                        "bay": int(j), "n_blocks": len(ids),
                        "cur_tard": float(ct), "new_tard": None,
                        "wall": 0.0, "status": "skipped_maxn", "err": None,
                    })
        work = kept
        if not work:
            _dbg("all work bays filtered by maxn -> return sol (NOOP)")
            _emit_log(False)
            return sol

        improved_any = False
        new_results = None
        remaining_bays = len(work)

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
                        })
                break
            per_bay = (deadline - now) / max(1, remaining_bays)
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
                    })
                    _tel_done_bays.add(j)
                continue

            by_id = results[j]
            W = int(bays[j]["width"]); H = int(bays[j]["height"])
            cur_makespan = max(int(by_id[b]["exit_time"]) for b in ids)
            max_due = max(int(blocks[b]["due_date"]) for b in ids)
            maxP = max(int(blocks[b]["processing_time"]) for b in ids)
            Hmax = max(cur_makespan, max_due) + maxP

            bay_deadline = now + per_bay
            _dbg(f"  bay {j}: SOLVE n={len(ids)} cur_tard={cur_tard} "
                 f"per_bay={per_bay:.1f}s W={W} H={H}")
            _bay_info = {} if _log_path else None
            _bay_t0 = time.monotonic()
            res = _solve_bay(W, H, ids, by_id, blocks, cur_tard, Hmax,
                             per_bay, bay_deadline, info=_bay_info)
            _bay_wall = time.monotonic() - _bay_t0
            if res:
                if new_results is None:
                    new_results = {jj: dict(bb) for jj, bb in results.items()}
                new_results[j] = res
                improved_any = True
                _dbg(f"  bay {j}: IMPROVED")
            else:
                _dbg(f"  bay {j}: no improvement (None)")
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
        if _env_on("OGC_PERBAY_DEBUG", False):
            import traceback
            sys.stderr.write("[perbay_t3] EXCEPTION in improve():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _emit_log(False)
        return sol


def algorithm(prob_info: dict, timelimit: float) -> dict:
    """Isolated-testing entry: build a baseline via myalgorithm._legacy_algorithm,
    then polish it with improve().  Minimal and never-raises (fallback: return the
    baseline solution, or whatever we have)."""
    t0 = time.monotonic()
    sol = None
    try:
        import myalgorithm
        sol = myalgorithm._legacy_algorithm(prob_info, timelimit * 0.6)
    except Exception:
        sol = None
    if sol is None:
        return {"operations": {}}
    try:
        remaining = max(0.0, timelimit - (time.monotonic() - t0))
        return improve(prob_info, sol, remaining)
    except Exception:
        return sol
