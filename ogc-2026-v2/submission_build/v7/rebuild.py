"""z3-aware LBBD rebuild — isolated alternative solver.

Design: notes/rebuild-architecture-2026-06-14.html
Primitive map: notes/devlog/integration-map.md

Activated only when OGC_REBUILD=1 (default OFF => eval path byte-identical).
Per-wave flags layer on top:
  OGC_W1  ATC/Emmons-ordered constructive + z3-aware realize spill + per-bay
          exact timing (reuse) + SA polish.        [this file, default ON when REBUILD]
  OGC_W2  z3-aware crane-anticipatory placement.    (added in Wave 2)
  OGC_W3  small-bay CP-SAT exact + decoder-in-loop ALNS.
  OGC_W4  LBBD branch-and-check no-good cut loop.

Everything routes through myalgorithm's verified primitives so geometry / crane
j>=k / timing stay identical to the legacy pipeline.  solve() returns a
check_feasibility-verified solution dict, or None to fall through to legacy.

Per-sequence learning trace: every meaningful step emits a `[REBUILD_SEQ]` JSON
line on stderr (summarised by notes/devlog/seqlog.py).  This is the substrate
the operator asked for ("record every instance run and every sequence").
"""
import json
import math
import os
import random
import sys
import time

from utils import Bay, Block, check_feasibility


# ── env helpers (mirror myalgorithm's, kept local to avoid import cycle) ──────
def _on(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _i(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


_TRACE = None  # set per-run: instance name, for [REBUILD_SEQ] lines
_SEQ_ON = False


def _seq(kind, **kw):
    """Emit one per-sequence trace line on stderr (JSON)."""
    if not _SEQ_ON:
        return
    try:
        rec = {"inst": _TRACE, "k": kind}
        rec.update(kw)
        print("[REBUILD_SEQ]" + json.dumps(rec, ensure_ascii=False),
              file=sys.stderr, flush=True)
    except Exception:
        pass


# ── geometry helpers ─────────────────────────────────────────────────────────
def _bbox_dims(sh):
    """(w, h) bounding box of an orientation's layers."""
    xs = []; ys = []
    for layer in sh.get("layers", []):
        for (x, y) in layer:
            xs.append(x); ys.append(y)
    if not xs:
        return None
    return (max(xs) - min(xs), max(ys) - min(ys))


def _block_fits_bay(blk_data, bay):
    """True if SOME orientation's bbox fits inside the bay bounds.

    bbox-based (not contains_block at (0,0)): polygon coords may not be
    origin-normalised, so contains_block(x=0,y=0) spuriously rejects bays the
    block actually fits when shifted -- which over-restricts the feasible set
    and inflates z3 (observed prob_1 z3=94 vs achievable 2)."""
    W, H = bay.width, bay.height
    for sh in blk_data.get("shape", []):
        d = _bbox_dims(sh)
        if d is None:
            continue
        bw, bh = d
        if bw <= W and bh <= H:
            return True
    return False


# ── core solver ────────────────────────────────────────────────────────────--
def solve(prob_info, T, t_start, bays, bay_u):
    """Entry point called from myalgorithm.algorithm() under OGC_REBUILD.

    prob_info : full instance dict
    T         : timelimit (s)
    t_start   : run start (time.monotonic())
    bays      : list[utils.Bay]
    bay_u     : list[float] bay weights
    Returns a verified solution dict {"operations": ...} or None.
    """
    global _TRACE, _SEQ_ON
    _TRACE = str(prob_info.get("name", "run"))
    _SEQ_ON = _on("OGC_REBUILD_SEQ", _on("OGC_Z1_TRACE", False))

    import solver_orig as M  # deferred => no import cycle
    import fastfloor as FF   # fast raster decoder for the inner loop
    try:
        import packer as PK   # repositioning packer (SSP density lever)
    except Exception:
        PK = None

    blocks = prob_info["blocks"]
    n = len(blocks)
    nb = len(bays)
    if n == 0 or nb == 0:
        return None
    w = prob_info.get("weights", {})
    w1 = float(w.get("w1", 1.0)); w2 = float(w.get("w2", 1.0)); w3 = float(w.get("w3", 1.0))

    # wall budget: leave margin for the final check_feasibility (done by 0.85T)
    deadline = t_start + _f("OGC_REBUILD_DEADLINE_FRAC", 0.85) * T

    def now():
        return time.monotonic()

    # ── UNIFIED engine (OGC_REBUILD_UNIFIED) — the big structural change ──────
    # CP-SAT-guided crane-aware greedy constructive (src/uconstruct.py): decides
    # (bay, position, time) jointly per block, crane-feasible BY CONSTRUCTION
    # (no realize barrier), inheriting CP-SAT's global z2+z3 via bay-target.
    # Owns the run when ON (self-verified); falls through to the LBBD if it fails.
    if _on("OGC_REBUILD_UNIFIED", False):
        try:
            import uconstruct as UC
            _us = UC.solve_unified(prob_info, T, t_start, bays, bay_u)
            if _us is not None:
                _seq("unified_done", wall=round(now() - t_start, 1))
                return _us
        except Exception as _ue:
            print(f"[REBUILD] unified fell through: {type(_ue).__name__}: {_ue}",
                  file=sys.stderr, flush=True)

    # ── per-block static data ────────────────────────────────────────────────
    R = [int(b.get("release_time", 0)) for b in blocks]
    P = [int(b.get("processing_time", 0)) for b in blocks]
    DUE = [int(b.get("due_date", 0)) for b in blocks]
    WL = [float(b.get("workload", 0.0)) for b in blocks]
    PREF = [list(b.get("bay_preferences", [0.0] * nb)) for b in blocks]
    PMAX = [max(p) if p else 0.0 for p in PREF]

    # feasible bays per block (geometry only)
    feas = [[j for j in range(nb) if _block_fits_bay(blocks[i], bays[j])]
            for i in range(n)]
    for i in range(n):
        if not feas[i]:
            feas[i] = list(range(nb))  # let decode force it; never strand a block

    # ── closed-form z2/z3 (independent of x/y/timing) ────────────────────────
    def z3_of(assign):
        return sum(PMAX[i] - PREF[i][assign[i]] for i in range(n))

    def z2_of(assign):
        load = [0.0] * nb
        for i in range(n):
            load[assign[i]] += WL[i]
        ul = [bay_u[j] * load[j] for j in range(nb)]
        return (max(ul) - min(ul)) if nb >= 2 else 0.0

    AREA = [_min_area(blocks[i]) for i in range(n)]   # min-bbox footprint area

    # ── per-bay decode (cached on membership set; EDD order) ─────────────────
    edd = sorted(range(n), key=lambda i: (DUE[i], R[i], -WL[i]))
    edd_pos = {i: k for k, i in enumerate(edd)}
    _cache = {}

    _ndec = [0]  # decode-call counter (for budget telemetry)
    _W2 = _on("OGC_W2", False)
    # Exact oracle: the EXACT crane-safe _decode_bay SEQUENCES entry times
    # (entry = earliest crane-safe slot, not fixed R), so it clears 25-35% more
    # geometric z1 than the raster fixed-time decoder => fewer evictions => lower
    # z3.  This is the architecture's intended oracle; raster was a speed proxy.
    _exact = _on("OGC_REBUILD_EXACT", False)
    _exhaustive = _on("OGC_REBUILD_EXHAUSTIVE", False)
    # Repositioning packer (src/packer.py): LNS window-rebuild fits more co-present
    # blocks than the append-only greedy on packing-wasteful bays (8/13 congested
    # bays improved in self-test) => fewer evictions => lower z3.  Slower per call,
    # so gate it + small per-bay budget; only fires on bays the raster leaves tardy.
    _packer = _on("OGC_REBUILD_PACKER", False) and PK is not None
    _packer_bud = _f("OGC_REBUILD_PACKER_BUD", 0.8)
    # W2: per-bay placement-order portfolio.  A congested bay's fixed-time
    # tardiness depends heavily on placement order (crane j>=k coexistence is
    # order-sensitive); trying several orders and keeping the tightest packing
    # lets a bay absorb more co-present blocks => fewer forced serialisations =>
    # less spill needed => lower z3.  Reuses the raster decoder, no new geometry.
    _W2_ORDERS = ["F0", "F1", "F2", "F3"]

    def decode_bay(j, members, dl, pf=False):
        """Return (result|None, bay_tardiness, late_set). cached on (set, pf).

        Fast raster fixed-time decode (~100x faster than the exact Shapely
        _decode_bay) so the loops can run thousands of evals.  pf=True activates
        the W2 order portfolio (extra placement orders, kept when a bay is tardy)
        -- used in the z3 phase / finalize, NOT in the fast z1-clearing phase
        which must stay cheap.  Output is the crane-safe record format."""
        key = (j, frozenset(members), pf)
        if key in _cache:
            return _cache[key]
        edd_order = sorted(members, key=lambda i: edd_pos[i])
        _ndec[0] += 1
        if _exact:
            try:
                res, _forced = M._decode_bay(bays[j], j, edd_order, blocks,
                                             deadline=dl, exhaustive_pos=_exhaustive)
            except Exception:
                res = None
            if res is None:
                _cache[key] = (None, math.inf, set())
                return _cache[key]
            t = sum(max(0, rec["exit_time"] - DUE[bid]) for bid, rec in res.items())
            late = {bid for bid, rec in res.items()
                    if rec["exit_time"] - DUE[bid] > 0}
            _cache[key] = (res, t, late)
            return _cache[key]
        # EDD first; W2 portfolio (explicit area/slack orders + seeded shuffles)
        # only when EDD leaves the bay tardy -- packing is order-sensitive, and
        # a different order sometimes fully clears a bay EDD can't (probe: prob_5
        # bay2 23->0).  Keep the tightest packing.
        best_res, best_t = None, math.inf
        try:
            res, ft = FF._fixed_time_decode(bays[j], j, members, blocks, dl,
                                            order_key=edd_order)
            if res is not None:
                best_res, best_t = res, float(ft.get("ft_tard", 0.0)) if ft else 0.0
        except Exception:
            pass
        if pf and _W2 and best_t > 1e-9 and len(members) > 1:
            mem = list(members)
            extra = [
                sorted(mem, key=lambda i: -AREA[i]),                       # area desc
                sorted(mem, key=lambda i: (DUE[i] - R[i] - P[i], -AREA[i])),  # slack,area
                sorted(mem, key=lambda i: (0 if DUE[i] - R[i] - P[i] <= 0 else 1,
                                           DUE[i] - R[i] - P[i], -AREA[i])),  # tight first
            ] + list(_W2_ORDERS)
            rng = random.Random(1009 * j + len(mem))
            for _ in range(_i("OGC_REBUILD_W2_SHUF", 8)):
                sh = mem[:]; rng.shuffle(sh); extra.append(sh)
            for ok in extra:
                if best_t <= 1e-9 or now() >= dl:
                    break
                try:
                    res, ft = FF._fixed_time_decode(bays[j], j, members, blocks,
                                                    dl, order_key=ok)
                except Exception:
                    res, ft = None, None
                if res is None:
                    continue
                t = float(ft.get("ft_tard", 0.0)) if ft else 0.0
                if t < best_t:
                    best_res, best_t = res, t
        # repositioning packer: only on bays the raster left tardy (cost is
        # concentrated there); guaranteed <= raster (packer falls back to its seed)
        if _packer and best_t > 1e-9 and len(members) > 1 and now() < dl - 0.2:
            try:
                pr, pt = PK.pack_bay(bays[j], j, list(members), blocks,
                                     min(dl, now() + _packer_bud + 0.2),
                                     time_budget=_packer_bud)
                if pr is not None and pt < best_t - 1e-9:
                    best_res, best_t = pr, pt
            except Exception:
                pass
        if best_res is None:
            _cache[key] = (None, math.inf, set())
            return _cache[key]
        late = {bid for bid, rec in best_res.items()
                if rec["exit_time"] - DUE[bid] > 0}
        _cache[key] = (best_res, best_t, late)
        return _cache[key]

    def members_of(assign):
        m = [[] for _ in range(nb)]
        for i in range(n):
            m[assign[i]].append(i)
        return m

    def full_decode(assign, dl, pf=False):
        """Decode every bay; return (per_bay_results|None, total_tard)."""
        m = members_of(assign)
        per_bay = {}
        tot = 0.0
        for j in range(nb):
            if not m[j]:
                continue
            res, tard, _fc = decode_bay(j, m[j], dl, pf)
            if res is None:
                return None, math.inf
            per_bay[j] = res
            tot += tard
        return per_bay, tot

    def obj_of(assign, dl, pf=False):
        per_bay, z1 = full_decode(assign, dl, pf)
        if per_bay is None:
            return math.inf, (math.inf, 0, 0), None
        z2 = z2_of(assign); z3 = z3_of(assign)
        total = w1 * z1 + w2 * z2 + w3 * z3
        return total, (z1, z2, z3), per_bay

    # ── W1.1 constructive: ATC/Emmons-ordered, preference-greedy w/ load guard ─
    # Each block to its most-preferred FEASIBLE bay, but a soft area-time cap
    # discourages gross over-subscription (cheap z1 proxy at construction time).
    cap_alpha = _f("OGC_REBUILD_CAP", 0.0)  # 0 => off (pure preference)
    bay_area = [bays[j].width * bays[j].height for j in range(nb)]

    # ATC urgency order: smallest slack first (most urgent placed first)
    atc = sorted(range(n), key=lambda i: (DUE[i] - P[i] - R[i], -WL[i]))
    assign = [0] * n
    used_area_time = [0.0] * nb  # sum of (block area * P) committed to bay
    for i in atc:
        best_j, best_sc = None, math.inf
        for j in feas[i]:
            zg = PMAX[i] - PREF[i][j]               # z3 cost of this bay
            pen = 0.0
            if cap_alpha > 0 and bay_area[j] > 0:
                # rough congestion penalty: area-time load vs capacity*window
                ut = used_area_time[j] / (bay_area[j] * max(1, P[i]))
                if ut > cap_alpha:
                    pen = (ut - cap_alpha) * _f("OGC_REBUILD_CAP_PEN", 50.0)
            sc = w3 * zg + pen
            if sc < best_sc:
                best_sc, best_j = sc, j
        assign[i] = best_j if best_j is not None else feas[i][0]
        # crude footprint area for the cap proxy (min-orientation bbox)
        try:
            ar = _min_area(blocks[i])
        except Exception:
            ar = WL[i]
        used_area_time[best_j] += ar * max(1, P[i])

    base_total, base_comp, base_pb = obj_of(assign, deadline)
    _seq("construct", z1=round(base_comp[0], 1), z2=round(base_comp[1], 1),
         z3=round(base_comp[2], 1), total=round(base_total, 1))
    if base_pb is None:
        # construct decode failed (a bay can't raster-place a block whose bbox
        # fit).  DON'T abandon -- the LBBD engine (CP-SAT feasible_bays) and the
        # fastfloor fallback handle it.  Engine A no-ops (best_pb stays None).
        _seq("construct_fail", note="base decode None; continue to LBBD/fallback")

    # candidate registry: prefer z1==0, then min total.
    candidates = []  # (label, assign, per_bay, comp3=(z1,z2,z3), total)

    def _register(label, a_, pb_, comp_, total_):
        if pb_ is not None and comp_ is not None and comp_[0] != math.inf:
            candidates.append((label, list(a_), pb_, comp_, total_))

    base_assign = assign[:]

    # ── ENGINE A — constructive (OGC_W1): z1-descent then z3 SA ───────────────
    if _on("OGC_W1", True):
        best_assign = assign[:]
        best_total, best_comp, best_pb = base_total, base_comp, base_pb
        # PHASE 1 — z1 clearing (greedy monotone z1-descent, cheapest-z3 spills)
        z1_dl = min(deadline, t_start + _f("OGC_REBUILD_REALIZE_FRAC", 0.45) * T)
        NALTS = _i("OGC_REBUILD_SPILL_ALTS", 4)
        KG = _i("OGC_REBUILD_SPILL_K", 40)
        stall = 0
        while best_comp[0] > 1e-9 and now() < z1_dl and stall < 3:
            m = members_of(best_assign)
            cur_z1 = best_comp[0]
            cands = []
            for j in range(nb):
                if not m[j]:
                    continue
                res, tard, late = decode_bay(j, m[j], z1_dl)
                if res is None or tard <= 1e-9:
                    continue
                for i in late:
                    lt = res[i]["exit_time"] - DUE[i]
                    cands.append((PMAX[i] - PREF[i][j], -lt, i, j))
            if not cands:
                break
            cands.sort()
            applied = False
            for _zc, _nl, i, jf in cands[:KG]:
                if now() >= z1_dl:
                    break
                alts = sorted((j for j in feas[i] if j != jf),
                              key=lambda j: (PMAX[i] - PREF[i][j], len(m[j])))
                for jt in alts[:NALTS]:
                    best_assign[i] = jt
                    nt, nc, npb = obj_of(best_assign, z1_dl)
                    if nc[0] < cur_z1 - 1e-9:
                        best_total, best_comp, best_pb = nt, nc, npb
                        _seq("z1desc", blk=i, frm=jf, to=jt, z1=round(nc[0], 1),
                             z3=round(nc[2], 1), ndec=_ndec[0])
                        applied = True
                        break
                    best_assign[i] = jf
                if applied:
                    break
            stall = 0 if applied else stall + 1
        _seq("phase1_done", z1=round(best_comp[0], 1), z3=round(best_comp[2], 1),
             total=round(best_total, 1), ndec=_ndec[0], wall=round(now() - t_start, 1))
        # PHASE 2 — z3 descent within z1=0.  Skip when the LBBD engine will run
        # (it gets the budget; a single final SA polish handles z3 for the
        # winner) -- otherwise construct's SA starves LBBD (prob_3 bug).
        if best_comp[0] <= 1e-9 and not _on("OGC_W3", True) \
                and _on("OGC_REBUILD_SA", True) and now() < deadline:
            bt, bc, bpb = obj_of(best_assign, deadline, pf=True)
            if bpb is not None and bc[0] <= 1e-9:
                best_total, best_comp, best_pb = bt, bc, bpb
            best_assign, best_total, best_comp, best_pb = _sa(
                best_assign, best_total, best_comp, best_pb, obj_of, feas,
                deadline, now, seed=_i("OGC_REBUILD_SEED", 0), pf=_W2)
        _register("construct", best_assign, best_pb, best_comp, best_total)

    # ── ENGINE B — LBBD branch-and-check (OGC_W3 cap-cut + OGC_W4 ban-cut) ─────
    # CP-SAT master minimises (c2*z2 + c3*1000*pref); the decode oracle realises
    # each assignment.  When bay j realises tardy:
    #   W3 (cap-cut): shrink j's area-time cap   -- a relaxation cut (weak: the
    #       area proxy is necessary-not-sufficient for crane j>=k feasibility).
    #   W4 (ban-cut): ban the cheapest-z3-to-evict tardy block from j  -- the
    #       COMBINATORIAL no-good cut that actually breaks the crane over-
    #       subscription (a per-(block,bay) exclusion via feasible_bays).
    # The master re-solves with the cut.  First z1=0 hit = fewest cuts = lowest
    # z3.  This is the realize-barrier crossing the architecture is built on.
    if _on("OGC_W3", True) and nb >= 2 and now() < deadline:
        try:
            fbays0 = M._feasible_bays(blocks, bays)
        except Exception:
            fbays0 = [list(range(nb)) for _ in range(n)]
        fbays0 = [fb or list(range(nb)) for fb in fbays0]
        lbbd_dl = min(deadline, t_start + _f("OGC_REBUILD_LBBD_FRAC", 0.80) * T)
        rounds = _i("OGC_REBUILD_LBBD_ROUNDS", 24)
        shrink = _f("OGC_REBUILD_LBBD_SHRINK", 0.82)
        cap0 = _f("OGC_REBUILD_LBBD_CAP0", 1.0)
        capfloor = _f("OGC_REBUILD_LBBD_CAPFLOOR", 0.35)
        use_w3 = _on("OGC_W3", True)
        use_w4 = _on("OGC_W4", True)
        use_timing = _on("OGC_W3_TIMING", True)
        timing_thresh = _f("OGC_REBUILD_TIMING_THRESH", 80.0)
        # PCAP: packer-calibrated capacity.  When a bay realises tardy, set its
        # cap to the MEASURED crane-safe peak area-util of its ON-TIME blocks
        # (the true capacity) instead of a blind shrink -- so CP-SAT offloads
        # exactly the overflow at minimal z3 in one shot (no ban-cut overshoot).
        use_pcap = _on("OGC_REBUILD_PCAP", False)
        cap_margin = _f("OGC_REBUILD_CAP_MARGIN", 0.97)

        def _peak_util(j, res):
            """peak co-present min-bbox-area utilisation of the ON-TIME blocks
            in a bay's decoded result = realised crane-safe capacity ratio."""
            ba = bays[j].width * bays[j].height
            if ba <= 0 or not res:
                return 1.0
            evts = []
            for bid, rec in res.items():
                if rec["exit_time"] - DUE[bid] > 0:   # skip tardy = the overflow
                    continue
                evts.append((rec["entry_time"], AREA[bid]))
                evts.append((rec["exit_time"], -AREA[bid]))
            if not evts:
                return capfloor
            evts.sort()
            cur = peak = 0.0
            for _t, d in evts:
                cur += d
                if cur > peak:
                    peak = cur
            return peak / ba
        best_true_z1 = math.inf
        no_improve = 0
        cap = [cap0] * nb
        banned = {}   # block -> set(bays banned)  (the combinatorial cut store)
        hint = base_assign
        found = False
        for r in range(rounds):
            if now() >= lbbd_dl:
                break
            fbays_r = [[j for j in fbays0[b] if j not in banned.get(b, ())]
                       or fbays0[b] for b in range(n)]
            per_round = max(1.5, (lbbd_dl - now()) / max(1, rounds - r))
            try:
                a2 = M._cpsat_assignment(prob_info, bays, fbays_r, bay_u,
                                         time_budget=per_round, hint=hint,
                                         cap_alpha=(list(cap) if use_w3 else None))
            except Exception:
                a2 = None
            if a2 is None:
                break
            tot2, comp2, pb2 = obj_of(a2, lbbd_dl, pf=_W2)
            _seq("lbbd", r=r, z1=round(comp2[0], 1), z2=round(comp2[1], 1),
                 z3=round(comp2[2], 1), total=round(tot2, 1),
                 nban=sum(len(v) for v in banned.values()), ndec=_ndec[0])
            if pb2 is None:
                break
            if comp2[0] <= 1e-9:
                _register("lbbd", a2, pb2, comp2, tot2)
                found = True
                break  # fewest cuts => minimal z3; done
            # --- timing-in-loop: realise TRUE z1 via the per-bay timing oracle
            # (entry staggering) BEFORE cutting, so we only evict bays that stay
            # tardy under OPTIMAL timing.  Fixed-time (entry=R) tardiness over-
            # counts => over-eviction => z3 explosion (the W4 z3 blow-up).
            cut_pb = pb2
            if use_timing and 0 < comp2[0] <= timing_thresh and now() < lbbd_dl - 1.0:
                try:
                    tbud = min(_f("OGC_REBUILD_TIMING_BUD", 8.0), lbbd_dl - now() - 0.5)
                    timed = M._cpsat_bay_timing_verified(
                        prob_info, bays, pb2, deadline=now() + tbud, lb_skip=True)
                except Exception:
                    timed = None
                if timed is not None:
                    try:
                        _ta, tpb, _tf = M._results_from_solution(prob_info, timed)
                    except Exception:
                        tpb = None
                    if tpb:
                        tz1 = sum(max(0, rec["exit_time"] - DUE[bid])
                                  for rr in tpb.values() for bid, rec in rr.items())
                        _seq("lbbd_timing", r=r, fixed_z1=round(comp2[0], 1),
                             true_z1=round(tz1, 1))
                        if tz1 <= 1e-9:
                            _register("lbbd", a2, pb2, (0.0, comp2[1], comp2[2]),
                                      w2 * comp2[1] + w3 * comp2[2])
                            found = True
                            break
                        cut_pb = tpb
            # early-abort if true z1 has stopped improving (return budget to FF)
            eff_z1 = sum(max(0, rec["exit_time"] - DUE[bid])
                         for rr in cut_pb.values() for bid, rec in rr.items())
            if eff_z1 < best_true_z1 - 1e-9:
                best_true_z1 = eff_z1
                no_improve = 0
            else:
                no_improve += 1
            if no_improve >= _i("OGC_REBUILD_LBBD_PATIENCE", 5):
                break
            # generate cuts from cut_pb's tardy bays (timed if available)
            tardy_bays = []
            for j, rr in cut_pb.items():
                t = sum(max(0, rec["exit_time"] - DUE[bid]) for bid, rec in rr.items())
                if t > 1e-9:
                    late = {bid for bid, rec in rr.items()
                            if rec["exit_time"] - DUE[bid] > 0}
                    tardy_bays.append((t, j, late, rr))
            if not tardy_bays:
                break
            tardy_bays.sort(key=lambda x: x[0], reverse=True)
            changed = False
            # cap-cut (soft) on tardy bays
            if use_w3:
                for tard, j, late, res in tardy_bays:
                    if use_pcap:
                        # set cap to the MEASURED true crane-safe capacity
                        nc_ = max(capfloor, min(cap[j], _peak_util(j, res) * cap_margin))
                    else:
                        nc_ = max(capfloor, cap[j] * shrink)
                    if nc_ < cap[j] - 1e-9:
                        cap[j] = nc_
                        changed = True
            # ban-cut (hard, costs z3): evict cheapest-z3 tardy block.  MINIMAL by
            # default -- one eviction per round from the worst bay -- so the ban
            # set (=> z3) grows as slowly as possible while still clearing z1.
            if use_w4:
                one_cut = _on("OGC_REBUILD_ONE_CUT", False)
                for tard, j, late, res in tardy_bays:
                    if not late:
                        continue

                    def _evcost(b, _j=j):
                        alts = [PREF[b][k] for k in fbays0[b]
                                if k != _j and k not in banned.get(b, ())]
                        best_alt = max(alts) if alts else (PREF[b][_j] - 1)
                        return PREF[b][_j] - best_alt   # >=0, smaller = cheaper

                    b = min(late, key=_evcost)
                    if len([k for k in fbays0[b] if k not in banned.get(b, ())]) > 1:
                        banned.setdefault(b, set()).add(j)
                        _seq("bancut", blk=b, bay=j, evcost=round(_evcost(b), 2))
                        changed = True
                        if one_cut:
                            break
            hint = a2
            if not changed:
                break
        _seq("lbbd_done", found=found, nban=sum(len(v) for v in banned.values()),
             wall=round(now() - t_start, 1))

    # ── final SA polish on the best z1=0 candidate (single, shared) ───────────
    if candidates and _on("OGC_REBUILD_SA", True) and now() < deadline:
        z0 = [c for c in candidates if c[3][0] <= 1e-9]
        if z0:
            base_c = min(z0, key=lambda c: c[4])
            _l, ca, cpb, cc, ct = base_c
            sa_a, sa_t, sa_c, sa_pb = _sa(ca, ct, cc, cpb, obj_of, feas, deadline,
                                          now, seed=_i("OGC_REBUILD_SEED", 0), pf=_W2)
            _register("sa_polish", sa_a, sa_pb, sa_c, sa_t)

    # ── select best candidate (z1=0 preferred, then min total) ────────────────
    chosen = None
    if candidates:
        chosen = min(candidates, key=lambda c: (0 if c[3][0] <= 1e-9 else 1, c[4]))
    _seq("select", n=len(candidates),
         label=(chosen[0] if chosen else None),
         z1=(round(chosen[3][0], 1) if chosen else None),
         z3=(round(chosen[3][2], 1) if chosen else None))

    # ── finalize chosen: exact per-bay timing + verify ────────────────────────
    sol = None
    chosen_z1 = math.inf
    if chosen is not None:
        _l, ca, cpb, cc, ct = chosen
        flat = [a for r in cpb.values() for a in r.values()]
        sol = {"operations": M._build_operations(flat)}
        chosen_z1 = cc[0]
        try:
            timed = M._cpsat_bay_timing_verified(prob_info, bays, cpb,
                                                 deadline=deadline, lb_skip=True)
            if timed is not None:
                comp = M._components_from_solution(prob_info, timed, bay_u)
                if comp is not None and comp[1] <= cc[0] + 1e-9:
                    sol = timed
                    chosen_z1 = comp[1]
        except Exception:
            pass

    # ── fastfloor fallback: if no z1=0 candidate, the proven floor builder ─────
    if (sol is None or chosen_z1 > 1e-9) and _on("OGC_REBUILD_FF_FALLBACK", True) \
            and now() < deadline:
        try:
            ff_bud = min(_f("OGC_REBUILD_FF_S", 40.0), max(8.0, deadline - now() - 2.0))
            ff_sol, _st = FF.build_fast_floor(prob_info, timelimit=ff_bud)
            if ff_sol is not None:
                ffc = M._components_from_solution(prob_info, ff_sol, bay_u)
                if ffc is not None:
                    better = (sol is None
                              or (ffc[1] <= 1e-9 and chosen_z1 > 1e-9)
                              or (((ffc[1] <= 1e-9) == (chosen_z1 <= 1e-9))
                                  and ffc[0] < (M._components_from_solution(
                                      prob_info, sol, bay_u) or (math.inf,))[0]))
                    if better:
                        sol = ff_sol
                        _seq("ff_fallback", z1=round(ffc[1], 1), z3=round(ffc[3], 1),
                             total=round(ffc[0], 1))
        except Exception:
            pass

    if sol is None:
        return None
    # final feasibility gate
    try:
        comp = M._components_from_solution(prob_info, sol, bay_u)
    except Exception:
        comp = None
    feas_ok = False
    try:
        chk = check_feasibility(prob_info, sol)
        feas_ok = chk[0] if isinstance(chk, (list, tuple)) else bool(chk)
    except Exception:
        feas_ok = False
    _seq("final", feas=bool(feas_ok),
         z1=(round(comp[1], 1) if comp else None),
         z2=(round(comp[2], 1) if comp else None),
         z3=(round(comp[3], 1) if comp else None),
         total=(round(comp[0], 1) if comp else None),
         wall=round(now() - t_start, 1))
    if not feas_ok:
        return None
    return sol


def _min_area(blk_data):
    """Smallest bounding-box area over orientations (cheap congestion proxy)."""
    best = math.inf
    for sh in blk_data.get("shape", []):
        xs = []; ys = []
        for layer in sh.get("layers", []):
            for (x, y) in layer:
                xs.append(x); ys.append(y)
        if xs:
            best = min(best, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    return best if best != math.inf else float(blk_data.get("workload", 1.0))


def _sa(assign, total, comp, per_bay, obj_of, feas, deadline, now, seed=0, pf=False):
    """Simulated annealing over the assignment, true objective.  Neighbour =
    single-block relocate.  Keeps the best-seen; accepts worse by temperature."""
    rng = random.Random(seed)
    n = len(assign)
    movable = [i for i in range(n) if len(feas[i]) > 1]
    if not movable:
        return assign, total, comp, per_bay
    best = assign[:]; best_total, best_comp = total, comp
    cur = assign[:]; cur_total, cur_comp = total, comp
    T0 = max(1.0, abs(total) * _f("OGC_REBUILD_SA_T0", 0.05))
    Tend = T0 * 0.01
    iters = 0
    max_iter = _i("OGC_REBUILD_SA_ITERS", 4000)
    while now() < deadline and iters < max_iter:
        iters += 1
        frac = iters / max_iter
        temp = T0 * ((Tend / T0) ** frac)
        i = rng.choice(movable)
        jf = cur[i]
        jt = rng.choice([j for j in feas[i] if j != jf])
        cur[i] = jt
        nt, nc, npb = obj_of(cur, deadline, pf)
        d = nt - cur_total
        if d < 0 or rng.random() < math.exp(-min(60.0, d / max(1e-9, temp))):
            cur_total, cur_comp = nt, nc
            # only record best in the z1=0 manifold (z1>0 is dominated)
            if nc[0] <= 1e-9 and nt < best_total - 1e-9:
                best, best_total, best_comp = cur[:], nt, nc
        else:
            cur[i] = jf
    _seq("sa", iters=iters, z1=round(best_comp[0], 1), z2=round(best_comp[1], 1),
         z3=round(best_comp[2], 1), total=round(best_total, 1))
    return best, best_total, best_comp, _decode_for(best, obj_of, deadline, pf)


def _decode_for(assign, obj_of, deadline, pf=False):
    _t, _c, pb = obj_of(assign, deadline, pf)
    return pb
