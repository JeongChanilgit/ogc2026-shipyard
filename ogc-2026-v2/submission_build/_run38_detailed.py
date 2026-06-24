"""_run38_detailed.py [PROB] [TL] -- run the ADOPTED pipeline (cap30bl) on one instance
with STEP-BY-STEP instrumentation: time + objective at each stage (v2 -> orig -> best-of
-> postproc), and within postproc the per-PASS wall + obj reduction (OGC_PP_PASSLOG).
Replicates myalgorithm's budget math (Windows in-process path).

ALL execution is under `if __name__ == "__main__"` so spawned multiprocessing workers
(parcand/parallel_decode) re-importing this module do NOT re-run the pipeline.
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, V7)
os.chdir(V7)
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1", OGC_PP_MOVEALL="1", OGC_PRECOMP_AABB="1",
                 OGC_PP_ACTIVE_CAP="30", OGC_PP_BLPROBE="3", OGC_PP_PASSLOG="1").items():
    os.environ.setdefault(k, v)

import utils                       # noqa: E402
import unified_greedy as _ug       # noqa: E402
import solver_orig as _O           # noqa: E402
import postproc as _PP             # noqa: E402

PROB = int(sys.argv[1]) if len(sys.argv) > 1 else 38
TL = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
SKIP_ORIG = os.environ.get("OGC_SKIP_ORIG") == "1"
BASE = "C:/claude-develop/OGC2026"
TAG = "_noorig" if SKIP_ORIG else ""
LOG = os.path.join(SB, f"_run{PROB}{TAG}_detailed.log")
JS = os.path.join(SB, f"_run{PROB}{TAG}_detailed.json")


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)


def obj_of(data, sol):
    try:
        r = utils.check_feasibility(data, sol)
        if isinstance(r, dict) and r.get("objective") is not None:
            return r["objective"], r.get("obj1"), r.get("obj2"), r.get("obj3")
    except Exception:
        pass
    return None, None, None, None


def main():
    try:
        import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
    except Exception:
        pass
    open(LOG, "w").close()
    data = json.load(open(f"{BASE}/instances/train/prob_{PROB}.json", encoding="utf-8"))
    W = data["weights"]
    rec = {"prob": PROB, "tl": TL, "weights": W, "stages": []}
    log(f"# ===== prob_{PROB} @ TL={TL:.0f}s (cap30bl) "
        f"w1={W['w1']:,} w2={W['w2']} w3={W['w3']} =====")
    t0 = time.time()
    SAFETY = max(8.0, TL * 0.08)
    hard_deadline = t0 + TL - SAFETY
    PP_MIN_RESERVE = min(TL * 0.15, 60.0)
    log(f"# budget: SAFETY={SAFETY:.0f}s hard_deadline=+{hard_deadline-t0:.0f}s "
        f"PP_MIN_RESERVE={PP_MIN_RESERVE:.0f}s")
    best, best_obj = None, None

    def stage(name, t_start, ot, note=""):
        o, z1, z2, z3 = ot
        rec["stages"].append({"stage": name, "dur": round(time.time() - t_start, 1),
                              "elapsed": round(time.time() - t0, 1), "obj": o, "z1": z1,
                              "z2": z2, "z3": z3, "note": note})
        log(f"\n### STAGE {name}: dur={time.time()-t_start:6.1f}s elapsed={time.time()-t0:6.1f}s "
            f"obj={o if o is None else format(o, ',.0f')} z1={z1} z3={z3} {note}")

    # STAGE 1: v2 unified_greedy
    ts = time.time()
    v2_budget = max(10.0, min(TL * 0.6, hard_deadline - time.time()))
    log(f"\n# v2 budget = {v2_budget:.0f}s")
    tmp = os.path.join(V7, "_run_inst.json")
    json.dump(data, open(tmp, "w"))
    res, _d, _c, _t = _ug.unified(data, v2_budget, tmp)
    sol_v2 = res.get("_solution") if isinstance(res, dict) else None
    ov2 = obj_of(data, sol_v2) if sol_v2 else (None, None, None, None)
    if ov2[0] is not None:
        best, best_obj = sol_v2, ov2[0]
    stage("1_v2_greedy", ts, ov2)

    # STAGE 2: orig solver (lion's share) -- SKIPPED if OGC_SKIP_ORIG=1
    oo = (None, None, None, None)
    if SKIP_ORIG:
        log(f"\n# orig SKIPPED (OGC_SKIP_ORIG=1) -> postproc gets the full leftover")
        rec["stages"].append({"stage": "2_orig_SKIPPED", "dur": 0.0,
                              "elapsed": round(time.time() - t0, 1), "obj": None,
                              "z1": None, "z2": None, "z3": None, "note": "skipped"})
    else:
        orig_deadline = hard_deadline - PP_MIN_RESERVE
        remaining = orig_deadline - time.time()
        log(f"\n# orig budget = {remaining:.0f}s (orig_deadline=+{orig_deadline-t0:.0f}s)")
        ts = time.time()
        try:
            sol_o = _O.algorithm(data, remaining)
            oo = obj_of(data, sol_o)
            if oo[0] is not None and (best is None or oo[0] < best_obj):
                best, best_obj = sol_o, oo[0]
        except Exception as e:
            log(f"  orig FAILED: {e!r}")
        stage("2_orig_solver", ts, oo)

    winner = "v2" if (ov2[0] is not None and best_obj == ov2[0]) else "orig"
    log(f"\n### BEST-OF: winner={winner} best_obj={best_obj:,.0f}")
    rec["bestof"] = {"winner": winner, "obj": best_obj}

    # STAGE 3: postproc (cap30bl) with per-pass logging
    pp_remaining = hard_deadline - time.time()
    log(f"\n# postproc leftover = {pp_remaining:.0f}s  base_obj={best_obj:,.0f}")
    rec["postproc_budget"] = round(pp_remaining, 1)
    rec["postproc_base_obj"] = best_obj
    ts = time.time()
    _bz1 = ov2[1] if winner == "v2" else oo[1]
    if best is not None and pp_remaining > 20.0 and (_bz1 or 0) > 1e-9:
        sol_pp = _PP.postprocess(data, best, time.monotonic() + pp_remaining)
        opp = obj_of(data, sol_pp)
        if opp[0] is not None and (best_obj is None or opp[0] <= best_obj + 1e-6):
            best, best_obj = sol_pp, opp[0]
        stage("3_postproc", ts, opp, note=f"(budget {pp_remaining:.0f}s)")
    else:
        stage("3_postproc", ts, (best_obj, _bz1, None, None),
              note=f"SKIPPED (z1={_bz1})")

    log(f"\n# ===== FINAL obj={best_obj:,.0f} total wall={time.time()-t0:.0f}s =====")
    rec["final_obj"] = best_obj
    rec["total_wall"] = round(time.time() - t0, 1)
    json.dump(rec, open(JS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"# detail -> {LOG} + {JS}")


if __name__ == "__main__":
    main()
