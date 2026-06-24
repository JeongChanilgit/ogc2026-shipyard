"""_levctl.py PROB BUDGET [CORES] -- VARIANCE-CONTROLLED postproc-lever A/B.

ONE instance per process.  Computes the postproc BASE ONCE (shared v2 greedy =
production base for set2) and runs each ARM's postproc from that SAME base for
BUDGET seconds, so the base-solver variance CANCELS and only the lever's marginal
postproc effect remains.  Reports per-arm final + delta vs prod.

This is the CORRECT design (the paired _levfull was swamped by base variance).
Judge = sum of (arm_final - prod_final) over instances; negative = lever helps.

env: C:/Users/peter/anaconda3/envs/ogc2025/python.exe   out: _levctl_<prob>.log
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, V7)
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1", OGC_PP_MOVEALL="1", OGC_PRECOMP_AABB="1").items():
    os.environ.setdefault(k, v)

PROB = int(sys.argv[1]) if len(sys.argv) > 1 else 38
BUDGET = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
CORES = sys.argv[3] if len(sys.argv) > 3 else "0,1,2,3"
TLG = float(os.environ.get("M1_TLG", "70"))
try:
    import psutil; psutil.Process().cpu_affinity([int(c) for c in CORES.split(",")])
except Exception:
    pass

import unified_greedy as UG            # noqa: E402
import postproc as PP                  # noqa: E402
from v3pp import adapter, seed as S     # noqa: E402
import utils                            # noqa: E402
assert "v7" in UG.__file__.replace("\\", "/") and "v7" in PP.__file__.replace("\\", "/")

BASE = "C:/claude-develop/OGC2026"
LOG = os.path.join(SB, f"_levctl_{PROB}.log")
RES = os.path.join(SB, f"_levctl_res_{PROB}.json")

_LEVER_KEYS = ["OGC_PP_ACTIVE_CAP", "OGC_PP_ACTIVE_MODE", "OGC_PP_MEMO",
               "OGC_PP_K", "OGC_PP_BLPROBE", "OGC_XSMART", "OGC_PP_TIGHTEN"]
_ARMSETS = {
    "cap": {
        "prod":  {},
        "cap20": {"OGC_PP_ACTIVE_CAP": "20"},
        "cap30": {"OGC_PP_ACTIVE_CAP": "30"},
    },
    "final": {
        "prod":    {},
        "cap20":   {"OGC_PP_ACTIVE_CAP": "20"},
        "cap30bl": {"OGC_PP_ACTIVE_CAP": "30", "OGC_PP_BLPROBE": "3"},
    },
    "other": {
        "prod":     {},
        "blocker":  {"OGC_PP_ACTIVE_MODE": "blocker"},
        "xsmart":   {"OGC_XSMART": "1"},
        "blprobe3": {"OGC_PP_BLPROBE": "3"},
        "tighten":  {"OGC_PP_TIGHTEN": "1"},
        "cap30bl":  {"OGC_PP_ACTIVE_CAP": "30", "OGC_PP_BLPROBE": "3"},
    },
}
ARMS = _ARMSETS[os.environ.get("OGC_ARMSET", "cap")]


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)


def offobj(data, sol):
    r = utils.check_feasibility(data, sol)
    return (r.get("objective"), r.get("obj1")) if isinstance(r, dict) else (None, None)


def main():
    log(f"\n# ==== CONTROLLED postproc A/B prob_{PROB} budget={BUDGET:.0f}s "
        f"cores={CORES} {time.strftime('%H:%M')} ====")
    path = f"{BASE}/instances/train/prob_{PROB}.json"
    data = json.load(open(path, encoding="utf-8"))
    for k in _LEVER_KEYS:
        os.environ.pop(k, None)
    UG._REGREEDY_PEN = {}
    t0 = time.time()
    res = UG.unified(data, TLG, path)[0]
    base_sol = res["_solution"]
    base_obj, base_z1 = offobj(data, base_sol)
    log(f"# base(v2 greedy) obj={base_obj:,.0f} z1={base_z1} ({time.time()-t0:.0f}s) "
        f"w1={data['weights']['w1']:,}")
    out = {"prob": PROB, "budget": BUDGET, "base_obj": base_obj, "arms": {}}
    for arm, env in ARMS.items():
        for k in _LEVER_KEYS:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
        sol = json.loads(json.dumps(base_sol))
        t = time.time()
        try:
            sol = PP.postprocess(data, sol, time.monotonic() + BUDGET)
            o, z1 = offobj(data, sol)
        except Exception as e:
            log(f"  {arm} FAILED {e!r}"); traceback.print_exc(); o, z1 = None, None
        out["arms"][arm] = {"obj": o, "z1": z1}
        ostr = f"{o:,.0f}" if o else str(o)
        log(f"  {arm:<7} final obj={ostr} z1={z1} ({time.time()-t:.0f}s)")
    p = out["arms"].get("prod", {}).get("obj")
    for arm in [a for a in ARMS if a != "prod"]:
        o = out["arms"].get(arm, {}).get("obj")
        if p and o:
            d = o - p
            log(f"  delta {arm}-prod = {d:+,.0f}  "
                f"{'(helps)' if d < 0 else '(hurts)' if d > 0 else '(tie)'}")
    json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"# DONE prob_{PROB}")


if __name__ == "__main__":
    main()
