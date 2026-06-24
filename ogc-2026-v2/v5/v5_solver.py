"""v5_solver.py -- user design (2026-06-23 revised): greedy(v2)-place + CP-SAT-refine loop.

  STEP 1   z2+z3 최소 베이 배정 (CP-SAT)               = cpsat_guideline
  greedy   배정대로 베이별 v2 배치(place_one, 공식 게이트) → 초기 feasible 해
  STEP 2   베이별 xyot CP-SAT 2회 (crane_repack_bay)    = 위치/방향/시각 정제
  STEP 3   전역: tardi 아닌 블록 고정. tardi 블록 적출 → z2+z3로 재배정(CP-SAT, non-tardy fixed)
  greedy   새 베이로 이동한(tardi) 블록을 고정 non-tardy 위에 v2 배치(place_one)
  loop     STEP2 → STEP3 → moved-greedy → STEP2 → ...  시간이 다할 때까지 (best 추적, never-worse 반환)

canonical per-bay 표현 = list of {id,x,y,orient,entry,exit}.  sh/world 는 필요 시 재구성.
"""
import os
import sys
import time
import json

_SB = r"C:/claude-develop/OGC2026/ogc-2026-v2/submission_build"
if _SB not in sys.path:
    sys.path.insert(0, _SB)
_V5DIR = os.path.dirname(os.path.abspath(__file__))

import utils                                  # official checker (submission_build copy)
from gridmap import build_shape               # noqa
from temporal_pack import place_one, _world   # v2 greedy placer (official-gated)
from assign_search import build_set
from unified_greedy import _cm                # exact common-masks fn for place_one
import cpsat_guideline as cg                  # STEP1 / STEP3 assignment
from v3pp import adapter as _ad               # solution -> v3pp placed
from v3pp import crane_cpsat as _C            # STEP2 xyot CP-SAT

SCALE = 2


# ---------------------------------------------------------------------------
def to_ops(bays_recs):
    # bucket ops by time, then emit time keys ASCENDING (check_feasibility iterates
    # in dict-insertion order and only matches an EXIT to a block whose ENTRY was
    # already seen -> keys MUST be time-sorted).  Within a bucket put EXIT before
    # ENTRY (official crane rule: exits processed before entries at the same time).
    ent, ext = {}, {}
    for j, recs in bays_recs.items():
        for r in recs:
            et, xt = int(r["entry"]), int(r["exit"])
            ent.setdefault(et, []).append(
                {"type": "ENTRY", "block_id": int(r["id"]), "bay_id": int(j),
                 "x": int(r["x"]), "y": int(r["y"]), "orient_idx": int(r["orient"])})
            ext.setdefault(xt, []).append(
                {"type": "EXIT", "block_id": int(r["id"]), "bay_id": int(j)})
    ops = {}
    for t in sorted(set(ent) | set(ext)):
        ops[str(t)] = ext.get(t, []) + ent.get(t, [])
    return {"operations": ops}


def evalu(data, bays_recs):
    sol = to_ops(bays_recs)
    try:
        r = utils.check_feasibility(data, sol)
    except Exception:
        return None, None
    viol = r.get("violations") or []
    obj = r.get("objective") if (not viol and r.get("objective") is not None) else None
    return obj, r


def _clone(br):
    return {j: [dict(r) for r in recs] for j, recs in br.items()}


# ---------------------------------------------------------------------------
def greedy_bay(data, W, H, fixed_recs, new_ids, shapes_map, ml):
    """Place new_ids into bay (W,H) on top of fixed_recs via v2 place_one (official-gated).
    shapes_map[bid] = list of oriented shapes (built ONCE, kept alive -> _cm id-cache stable).
    Returns canonical recs list (fixed + newly placed)."""
    blocks = data["blocks"]
    if not (fixed_recs or new_ids):
        return []
    shapes = shapes_map
    bay_obj = utils.Bay(width=W, height=H)
    placed = []
    for r in fixed_recs:
        sh = shapes[r["id"]][r["orient"]]
        placed.append({"id": r["id"], "sh": sh, "x": r["x"], "y": r["y"],
                       "orient": r["orient"], "entry": r["entry"], "exit": r["exit"],
                       "world": _world(sh, r["x"], r["y"])})
    last_entry = max((p["entry"] for p in placed), default=0)
    order = sorted(new_ids, key=lambda i: blocks[i]["due_date"])
    for bid in order:
        R = blocks[bid].get("release_time", 0)
        P = blocks[bid]["processing_time"]
        D = blocks[bid]["due_date"]
        rec = place_one(bid, W, H, ml, SCALE, placed, last_entry, shapes[bid], _cm,
                        (R, P, D), blocks, bay_obj, True, False)
        if rec is not None:
            placed.append(rec)
            last_entry = max(last_entry, rec["entry"])
    return [{"id": p["id"], "x": p["x"], "y": p["y"], "orient": p["orient"],
             "entry": p["entry"], "exit": p["exit"]} for p in placed]


def _pass_cap(n_blocks, remaining, n_active_bays):
    """Adaptive per-axis CP-SAT wall cap -- ported from the submission's fast v3
    postproc.  Bounded by BOTH bay size and remaining-budget/(2*active bays)."""
    size_cap = min(40.0, max(12.0, 0.30 * n_blocks))
    budget_cap = remaining / max(1.0, 2.0 * n_active_bays)
    return float(max(8.0, min(size_cap, max(budget_cap, 10.0), max(1.0, remaining))))


def _bz1(data, recs):
    return sum(max(0, r["exit"] - data["blocks"][r["id"]]["due_date"]) for r in recs)


def step2_bay(data, j, recs, deadline, n_active=1, iters=None):
    """Per-bay xyo coordinate-descent CP-SAT refine, structured like the FAST
    submission v3 postproc: window_tardy_only (free only tardy-window blocks,
    freeze rest -> tiny model) + _pass_cap adaptive time + K=5.  Entry time (t) is
    optimized jointly in every axis solve.  Called ONLY on tardy bays."""
    if not recs:
        return recs
    bp = _ad.deserialize(data, to_ops({j: recs}))
    cur = bp.get(j) or []
    if not cur:
        return recs
    if iters is None:
        iters = int(os.environ.get("OGC_V5_ITERS", "3"))   # xyoxyoxyo sweeps
    K = int(os.environ.get("OGC_V5_KX", "5"))
    axes = [(K, 0, 0, False), (0, K, 0, False), (0, 0, K, True)]   # x, y, orient
    # window-only (default, like v3) = fast.  free-all only if env raises the
    # threshold (thorough strongX relayout, worth it only on small bays).
    free_all = len(cur) <= int(os.environ.get("OGC_V5_FREEALL_MAX", "0"))
    win_only = not free_all
    ts_cap = float(os.environ.get("OGC_V5_TS_AXIS", "30"))
    for _ in range(iters):
        for (nx, ny, no, uo) in axes:
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            ts = min(ts_cap, _pass_cap(len(cur), deadline - now, n_active))
            try:
                new_pl, st, wall, info = _C.crane_repack_bay(
                    data, j, cur, ts, n_xcand=nx, n_ycand=ny, n_ocand=no,
                    use_orient=uo, window_tardy_only=win_only)
            except TypeError:
                new_pl, st, wall, info = _C.crane_repack_bay(
                    data, j, cur, ts, n_xcand=nx, n_ycand=ny)
            if new_pl:
                cur = new_pl
        if time.monotonic() >= deadline - 1.0:
            break
    out = []
    for p in cur:
        out.append({"id": p["id"], "x": p["x"], "y": p["y"],
                    "orient": p.get("orient", p.get("orient_idx")),
                    "entry": p["entry"], "exit": p["exit"]})
    return out


# ---------------------------------------------------------------------------
def from_ops(data, sol):
    """solution operations dict -> canonical {bay: [{id,x,y,orient,entry,exit}]}."""
    recs = {}
    for tstr, ops in sol.get("operations", {}).items():
        t = int(tstr)
        for op in ops:
            bid = op["block_id"]
            if op.get("type") == "ENTRY":
                recs.setdefault(bid, {}).update(
                    {"bay": op["bay_id"], "x": op["x"], "y": op["y"],
                     "orient": op["orient_idx"], "entry": t})
            elif op.get("type") == "EXIT":
                recs.setdefault(bid, {})["exit"] = t
    bays_recs = {}
    for bid, r in recs.items():
        if "entry" in r and "exit" in r:
            bays_recs.setdefault(r["bay"], []).append(
                {"id": bid, "x": r["x"], "y": r["y"], "orient": r["orient"],
                 "entry": r["entry"], "exit": r["exit"]})
    return bays_recs


def _v2_init(data, budget):
    """Borrow v2's z1-AWARE global Pass B (unified_greedy) as the initial solution.
    v5 STEP1=z2+z3 ignores z1 -> over-packs congested bays; v2's marginal includes
    w1*tardy so its emergent assignment + placement is z1-aware (less over-pack)."""
    try:
        for k, v in {"OGC_GLOBAL": "1", "OGC_GUIDE": "1", "OGC_FIT": "1",
                     "OGC_DIVERSE": "1", "OGC_ORDER": "blend",
                     "OGC_ORDER_ALPHA": "0.5", "OGC_FFT_MASK": "1"}.items():
            os.environ.setdefault(k, v)
        import unified_greedy as ug
        tmp = os.path.join(_V5DIR, f"_v5_v2init_{os.getpid()}.json")
        json.dump(data, open(tmp, "w", encoding="utf-8"))
        try:
            res, _d, _c, _t = ug.unified(data, max(20.0, budget), tmp)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        sol = res.get("_solution") if isinstance(res, dict) else None
        if not sol:
            return None
        br = from_ops(data, sol)
        return br or None
    except Exception as e:
        print(f"[v5] v2_init failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None


# ---------------------------------------------------------------------------
def algorithm(prob_info, timelimit=120.0):
    t0 = time.monotonic()
    deadline = t0 + float(timelimit)
    data = prob_info
    blocks = data["blocks"]
    bays = data["bays"]
    N, m = len(blocks), len(bays)
    dim = [(b["width"], b["height"]) for b in bays]
    due = [blocks[i]["due_date"] for i in range(N)]

    def remaining():
        return deadline - time.monotonic()

    # ---- INIT modes: z2z3 (default) | v2 (borrow Pass B) | best (best-of both).
    #      v2 Pass B is z1-aware (wins congested); z2+z3+greedy wins low-congestion
    #      (prob_4 optimal).  "best" STEP2-refines BOTH and keeps the better start.
    #      _v2_init runs BEFORE building SHAPES so unified_greedy's transient shapes
    #      are GC'd before ours populate _cm. ----
    INIT = os.environ.get("OGC_V5_INIT", "z2z3")
    cand_v2 = None
    if INIT in ("v2", "best"):
        cand_v2 = _v2_init(data, remaining() * float(os.environ.get("OGC_V5_INIT_FRAC", "0.30")))

    import unified_greedy as _ug
    _ug._CM.clear()
    SHAPES = {i: [build_shape(i, blocks[i], o, SCALE)
                  for o in range(len(blocks[i]["shape"]))] for i in range(N)}
    ML = max(max(s.n_layers for s in SHAPES[i]) for i in range(N))

    # ---- per-step objective trajectory ----
    TRAJ = []

    def traj(label, br, extra=""):
        obj, r = evalu(data, br)
        TRAJ.append({"step": label, "obj": obj, "z1": (r or {}).get("obj1"),
                     "z2": (r or {}).get("obj2"), "z3": (r or {}).get("obj3"),
                     "t": round(time.monotonic() - t0, 1)})
        print(f"[v5] {label:>14} obj={obj} z1={(r or {}).get('obj1')} "
              f"z3={(r or {}).get('obj3')} {extra} ({time.monotonic()-t0:.0f}s)",
              file=sys.stderr, flush=True)
        return obj, r

    def z2z3_init():
        g = cg.cpsat_guideline(data, time_s=min(12.0, max(3.0, timelimit * 0.12)))
        assign = list(g)
        br = {}
        for j in range(m):
            ids_j = [i for i in range(N) if assign[i] == j]
            if ids_j:
                br[j] = greedy_bay(data, dim[j][0], dim[j][1], [], ids_j, SHAPES, ML)
        return br

    # ---- STEP 2: refine ONLY tardy bays (z1>0), worst-first — like the fast v3.
    #      Zero-tardy bays skipped (big speed win on multi-bay sets). ----
    def step2_all(br):
        tardy_bays = [j for j in br if br[j] and _bz1(data, br[j]) > 0]
        if not tardy_bays:
            return br
        tardy_bays.sort(key=lambda jj: -_bz1(data, br[jj]))
        n_active = len(tardy_bays)
        for j in tardy_bays:
            if remaining() < 4.0:
                break
            br[j] = step2_bay(data, j, br[j], deadline, n_active)
        return br

    # ---- build the initial solution per INIT mode ----
    if INIT == "best":
        a = step2_all(z2z3_init()); oa, _ = evalu(data, a)
        if cand_v2:
            b = step2_all(cand_v2); ob, _ = evalu(data, b)
            use_b = ob is not None and (oa is None or ob < oa)
            bays_recs = b if use_b else a
            traj(f"best_init[{'v2' if use_b else 'z2z3'}]", bays_recs, extra=f"z2z3={oa} v2={ob}")
        else:
            bays_recs = a
            traj("best_init[z2z3]", bays_recs)
    elif INIT == "v2":
        bays_recs = cand_v2 or z2z3_init()
        traj("init(v2)", bays_recs)
        bays_recs = step2_all(bays_recs)
    else:
        bays_recs = z2z3_init()
        traj("STEP1+greedy", bays_recs)
        bays_recs = step2_all(bays_recs)

    best_obj, best_r = traj("STEP2_init", bays_recs)
    best = _clone(bays_recs)

    # ---- STEP 3 + loop ----
    # OGC_V5_TARDY_K>0: each round move only the WORST-K tardy blocks (rotating window)
    #   instead of ALL -> small perturbation (mass-reshuffle destroys congested layouts).
    # OGC_V5_NEVERWORSE=1: if a round doesn't beat best, revert working state to best
    #   (no drift to worse states).
    NEVERWORSE = os.environ.get("OGC_V5_NEVERWORSE", "0") == "1"
    TARDY_K = int(os.environ.get("OGC_V5_TARDY_K", "0"))
    rounds = 0
    while remaining() > 4.0:
        rounds += 1
        tlist = sorted(((r["exit"] - due[r["id"]], r["id"])
                        for j in bays_recs for r in bays_recs[j] if r["exit"] > due[r["id"]]),
                       reverse=True)
        if not tlist:
            break
        if TARDY_K > 0 and len(tlist) > TARDY_K:
            start = ((rounds - 1) * TARDY_K) % len(tlist)
            sel = (tlist + tlist)[start:start + TARDY_K]      # rotating window (wraps)
            tardy = [bid for (_lt, bid) in sel]
        else:
            tardy = [bid for (_lt, bid) in tlist]
        tset = set(tardy)
        non_tardy_assign = {r["id"]: j for j in bays_recs for r in bays_recs[j]
                            if r["id"] not in tset}
        g2 = cg.cpsat_guideline(data, fixed=non_tardy_assign,
                                time_s=min(6.0, max(2.0, remaining() * 0.08)))
        new_bay = {bid: g2[bid] for bid in tardy}
        trial = {j: [dict(r) for r in bays_recs.get(j, []) if r["id"] not in tset]
                 for j in range(m)}
        for j in range(m):
            movers = [bid for bid in tardy if new_bay[bid] == j]
            if movers:
                trial[j] = greedy_bay(data, dim[j][0], dim[j][1], trial[j], movers, SHAPES, ML)
        traj(f"r{rounds}_STEP3", trial, extra=f"k={len(tardy)}")
        trial = step2_all(trial)
        obj, r = traj(f"r{rounds}_STEP2", trial, extra=f"best={best_obj}")
        improved = obj is not None and (best_obj is None or obj < best_obj)
        if improved:
            best_obj, best_r, best = obj, r, _clone(trial)
        if obj is not None and (improved or not NEVERWORSE):
            bays_recs = trial
        else:
            bays_recs = _clone(best)

    print(f"[v5] DONE best={best_obj} rounds={rounds} ({time.monotonic()-t0:.0f}s)",
          file=sys.stderr, flush=True)
    _tp = os.environ.get("OGC_V5_TRAJ")
    if _tp:
        try:
            json.dump({"inst": os.environ.get("OGC_V5_INST", ""), "best": best_obj,
                       "rounds": rounds, "traj": TRAJ},
                      open(_tp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return to_ops(best)


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_4"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    if not nm.startswith("prob_"):
        nm = "prob_" + nm
    data = json.load(open(f"C:/claude-develop/OGC2026/instances/train/{nm}.json", encoding="utf-8"))
    t0 = time.time()
    sol = algorithm(data, tl)
    r = utils.check_feasibility(data, sol)
    print(f"{nm}  obj={r.get('objective')}  z1={r.get('obj1')} z2={r.get('obj2')} "
          f"z3={r.get('obj3')}  feasible={r.get('objective') is not None}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
