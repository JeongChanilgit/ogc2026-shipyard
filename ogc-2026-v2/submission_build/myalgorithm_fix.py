"""myalgorithm_fix.py — FIXED variant (set2 develop experiment).

Fixes vs submitted myalgorithm.py (user-directed):
  1. v2 ABSOLUTE cap  OGC_V2_CAP (default 90s)  — NOT 0.6*TL (which ate 360s @600).
  2. solver_orig gets OGC_ORIG_FRAC of post-v2 remaining (default 0.55) — NOT the
     full lion's share to deadline-60. Leaves a real window for postproc.
  3. postproc is NOT z1-gated -> runs full-obj (xyo z1 + move/swap z3) on the
     genuinely-remaining time, never-worse gated.  (Honors original directive:
     "후처리는 z1만이 아니라 목적함수를 깎아야 해".)

Exposes algorithm(prob_info, timelimit) (eval-compatible) + module global _TRACE
with provenance (v1/v2/baseline) and per-stage objectives so we can see, per
instance, which base won and how much postproc helped.
"""
import os
import sys
import time
import json

# --- v2 config (same as submission) ---
os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_DIVERSE", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")
os.environ.setdefault("OGC_TOSS", "0")
os.environ.setdefault("OGC_PACK_SWAP", "0")
os.environ.setdefault("OGC_GUIDE_ATLOOSE", "0")
os.environ.setdefault("OGC_LNS", "0")
os.environ.setdefault("OGC_MERGE", "0")
os.environ.setdefault("OGC_GLOBAL", "1")
os.environ.setdefault("OGC_ORDER", "blend")
os.environ.setdefault("OGC_ORDER_ALPHA", "0.5")
os.environ.setdefault("OGC_FFT_MASK", "1")

import signal
import multiprocessing as _mp

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_TRACE = {}


def _obj(prob_info, sol):
    import utils
    try:
        r = utils.check_feasibility(prob_info, sol)
    except Exception:
        return None
    if isinstance(r, dict) and r.get("objective") is not None:
        return r["objective"]
    return None


def _v2_entry(prob_info, budget, tmp, q):
    try:
        os.setsid()
    except Exception:
        pass
    try:
        import unified_greedy as _ug
        res, _d, _c, _t = _ug.unified(prob_info, budget, tmp)
        q.put(res.get("_solution") if isinstance(res, dict) else None)
    except Exception:
        try:
            q.put(None)
        except Exception:
            pass


def _v2_run(prob_info, budget, tmp):
    """Run v2 global Pass B once (fork-isolated), return solution dict or None."""
    sol = None
    try:
        if hasattr(os, "fork"):
            ctx = _mp.get_context("fork")
            q = ctx.Queue()
            p = ctx.Process(target=_v2_entry, args=(prob_info, budget, tmp, q))
            p.start()
            p.join(budget + 3.0)
            if p.is_alive():
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                p.join(2.0)
            else:
                try:
                    sol = q.get_nowait()
                except Exception:
                    sol = None
        else:
            import unified_greedy as _ug
            res, _d, _c, _t = _ug.unified(prob_info, budget, tmp)
            sol = res.get("_solution") if isinstance(res, dict) else None
    except Exception:
        sol = None
    return sol


def _scale_bestof(prob_info, timelimit, scales):
    """Run v2(@M1 scale)+postproc per scale; pick per-instance best with z1=0
    PRIORITY then lowest obj.  Realizes set1 z1=0 + low z3 WITHOUT v1
    (different instances keep z1=0 at different M1 scales -> best-of)."""
    global _TRACE
    _TRACE = {"mode": "scale_bestof", "scales": scales}
    import time as _t
    import utils
    import postproc as _PP
    t0 = _t.time()
    SAFETY = max(8.0, timelimit * 0.08)
    hard = t0 + timelimit - SAFETY
    V2_CAP = float(os.environ.get("OGC_V2_CAP", "70"))
    scales = sorted(set(scales), reverse=True)        # highest (z1-safe) first
    cands = []
    for k, sc in enumerate(scales):
        os.environ["OGC_PLACE_W1_SCALE"] = str(sc)
        rem = hard - _t.time()
        if rem < 6.0:
            break
        slice_end = _t.time() + rem / (len(scales) - k)    # equal share of remaining
        tmp = os.path.join(_HERE, f"_v2fix_inst_{os.getpid()}.json")
        try:
            json.dump(prob_info, open(tmp, "w"))
        except Exception:
            pass
        v2_budget = max(8.0, min(V2_CAP, slice_end - _t.time()))
        sol = _v2_run(prob_info, v2_budget, tmp)
        try:
            os.remove(tmp)
        except Exception:
            pass
        if sol is None:
            continue
        pp_rem = slice_end - _t.time()
        if pp_rem > 8.0 and os.environ.get("OGC_NO_PP") != "1":
            try:
                sp = _PP.postprocess(prob_info, sol, _t.monotonic() + pp_rem)
                if sp is not None:
                    sol = sp
            except Exception:
                pass
        try:
            r = utils.check_feasibility(prob_info, sol)
        except Exception:
            r = None
        if r and r.get("objective") is not None:
            cands.append((r.get("obj1") or 0, r["objective"], sol, sc))
            _TRACE[f"s{sc}"] = {"obj": round(r["objective"]), "z1": r.get("obj1")}
            # z1 vs scale is NON-monotonic (sweet spot in the middle, e.g. prob_4:
            # z1=1@1.0, z1=0@0.5, z1=1@0.3).  So only stop when z1 is LARGE = clearly
            # z1-bound (set2); a small residual z1 may vanish at a lower scale.
            if (r.get("obj1") or 0) > 20:
                break
    if not cands:
        return {"operations": {}}
    cands.sort(key=lambda c: (c[0] > 0, c[0], c[1]))    # z1=0 first, then z1, then obj
    _TRACE["picked"] = cands[0][3]
    _TRACE["base_src"] = f"v2@{cands[0][3]}"
    _TRACE["base_obj"] = cands[0][1]
    return cands[0][2]


def algorithm(prob_info, timelimit=60):
    _SB = os.environ.get("OGC_SCALE_BESTOF", "")
    if _SB and os.environ.get("OGC_NO_V1") == "1":
        try:
            return _scale_bestof(prob_info, timelimit, [float(s) for s in _SB.split(",")])
        except Exception:
            pass
    global _TRACE
    _TRACE = {}
    t0 = time.time()
    SAFETY = max(8.0, timelimit * 0.08)
    hard_deadline = t0 + timelimit - SAFETY
    V2_CAP = float(os.environ.get("OGC_V2_CAP", "90"))
    ORIG_FRAC = float(os.environ.get("OGC_ORIG_FRAC", "0.55"))
    best, best_obj, best_src = None, None, None

    # ① v2 GLOBAL — ABSOLUTE cap (not 0.6*TL)
    try:
        tmp = os.path.join(_HERE, f"_v2fix_inst_{os.getpid()}.json")  # PID-unique: no parallel race
        with open(tmp, "w") as f:
            json.dump(prob_info, f)
        v2_budget = max(10.0, min(V2_CAP, hard_deadline - time.time()))
        sol = None
        if hasattr(os, "fork"):
            ctx = _mp.get_context("fork")
            q = ctx.Queue()
            p = ctx.Process(target=_v2_entry, args=(prob_info, v2_budget, tmp, q))
            p.start()
            p.join(v2_budget + 3.0)
            if p.is_alive():
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                p.join(2.0)
            else:
                try:
                    sol = q.get_nowait()
                except Exception:
                    sol = None
        else:
            import unified_greedy as _ug
            res, _d, _c, _t = _ug.unified(prob_info, v2_budget, tmp)
            sol = res.get("_solution") if isinstance(res, dict) else None
        if sol is not None:
            o = _obj(prob_info, sol)
            _TRACE["v2_obj"] = o
            _TRACE["v2_wall"] = round(time.time() - t0, 1)
            if o is not None:
                best, best_obj, best_src = sol, o, "v2"
    except Exception:
        pass

    # ② solver_orig — OGC_ORIG_FRAC of post-v2 remaining (leaves window for postproc)
    remaining = hard_deadline - time.time()
    orig_budget = remaining * ORIG_FRAC
    _TRACE["orig_budget"] = round(orig_budget, 1)
    if os.environ.get("OGC_NO_V1") != "1" and orig_budget > 5.0:
        try:
            import solver_orig as _O
            ot = time.time()
            sol_o = _O.algorithm(prob_info, orig_budget)
            _TRACE["orig_wall"] = round(time.time() - ot, 1)
            o = _obj(prob_info, sol_o)
            _TRACE["orig_obj"] = o
            if o is not None and (best is None or o < best_obj):
                best, best_obj, best_src = sol_o, o, "v1"
        except Exception:
            pass

    # baseline fallback
    if best is None:
        try:
            import baseline_greedy as _B
            rem = max(5.0, timelimit - (time.time() - t0) - 1.0)
            best = _B.greedyalgorithm(prob_info, rem)
            best_obj = _obj(prob_info, best)
            best_src = "baseline"
        except Exception:
            best = {"operations": {}}
            best_src = "empty"

    _TRACE["base_src"] = best_src
    _TRACE["base_obj"] = best_obj

    # ④ postproc — full-obj (xyo + move/swap), NOT z1-gated, remaining time, never-worse
    try:
        pp_remaining = hard_deadline - time.time()
        _TRACE["pp_budget"] = round(pp_remaining, 1)
        if best is not None and pp_remaining > 20.0 and os.environ.get("OGC_NO_PP") != "1":
            import time as _t
            mono_deadline = _t.monotonic() + pp_remaining
            import postproc as _PP
            pt = time.time()
            sol_pp = _PP.postprocess(prob_info, best, mono_deadline)
            _TRACE["pp_wall"] = round(time.time() - pt, 1)
            if sol_pp is not None and sol_pp is not best:
                o = _obj(prob_info, sol_pp)
                _TRACE["pp_obj"] = o
                if o is not None and (best_obj is None or o <= best_obj + 1e-6):
                    if best_obj is not None and o < best_obj - 1e-6:
                        _TRACE["pp_improved"] = True
                    best, best_obj = sol_pp, o
    except Exception:
        pass

    _TRACE["final_obj"] = best_obj
    _TRACE["final_src"] = (best_src or "?") + ("+pp" if _TRACE.get("pp_improved") else "")
    return best
