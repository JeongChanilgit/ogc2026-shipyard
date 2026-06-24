"""_levrep.py PROB BUDGET [CORES] -- NOISE-CONTROLLED postproc-lever A/B.

Like _levctl but runs each arm REPS times (default 3) from the SAME shared base,
reporting per-arm MEDIAN + min/max so CP-SAT postproc nondeterminism (the
"<300K = noise" the handoff warns about) is separated from real signal.

env: ogc2025 python.  out: _levrep_<prob>.json + log.
"""
import os, sys, json, time, traceback, statistics

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
REPS = int(os.environ.get("LR_REPS", "3"))
TLG = float(os.environ.get("M1_TLG", "70"))
try:
    import psutil; psutil.Process().cpu_affinity([int(c) for c in CORES.split(",")])
except Exception:
    pass

import unified_greedy as UG            # noqa: E402
import postproc as PP                  # noqa: E402
from v3pp import adapter, seed as S     # noqa: E402
import utils                            # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LOG = os.path.join(SB, f"_levrep_{PROB}.log")
RES = os.path.join(SB, f"_levrep_res_{PROB}.json")
_KEYS = ["OGC_PP_ACTIVE_CAP", "OGC_PP_ACTIVE_MODE", "OGC_PP_MEMO", "OGC_PP_K",
         "OGC_PP_BLPROBE", "OGC_XSMART", "OGC_PP_TIGHTEN", "OGC_PP_CAP_MIN_BAY"]
ARMS = {
    "prod":   {},
    "cap20":  {"OGC_PP_ACTIVE_CAP": "20"},
    "xsmart": {"OGC_XSMART": "1"},
    "cap30bl": {"OGC_PP_ACTIVE_CAP": "30", "OGC_PP_BLPROBE": "3"},
}


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)


def offobj(data, sol):
    r = utils.check_feasibility(data, sol)
    return r.get("objective") if isinstance(r, dict) else None


def main():
    log(f"\n# === NOISE-CTRL A/B prob_{PROB} budget={BUDGET:.0f}s reps={REPS} "
        f"cores={CORES} {time.strftime('%H:%M')} ===")
    path = f"{BASE}/instances/train/prob_{PROB}.json"
    data = json.load(open(path, encoding="utf-8"))
    for k in _KEYS:
        os.environ.pop(k, None)
    UG._REGREEDY_PEN = {}
    res = UG.unified(data, TLG, path)[0]
    base_sol = res["_solution"]
    base_obj = offobj(data, base_sol)
    log(f"# base obj={base_obj:,.0f} w1={data['weights']['w1']:,}")
    out = {"prob": PROB, "budget": BUDGET, "reps": REPS, "base": base_obj, "arms": {}}
    for arm, env in ARMS.items():
        vals = []
        for rep in range(REPS):
            for k in _KEYS:
                os.environ.pop(k, None)
            for k, v in env.items():
                os.environ[k] = v
            sol = json.loads(json.dumps(base_sol))
            try:
                sol = PP.postprocess(data, sol, time.monotonic() + BUDGET)
                vals.append(offobj(data, sol))
            except Exception as e:
                log(f"  {arm} rep{rep} FAIL {e!r}"); traceback.print_exc()
        vals = [v for v in vals if v]
        med = statistics.median(vals) if vals else None
        out["arms"][arm] = {"median": med, "min": min(vals) if vals else None,
                            "max": max(vals) if vals else None, "all": vals}
        if vals:
            vs = ", ".join(f"{v:,.0f}" for v in vals)
            log(f"  {arm:<8} median={med:,.0f} spread={max(vals)-min(vals):,.0f}  [{vs}]")
        else:
            log(f"  {arm:<8} (no vals)")
    pm = out["arms"]["prod"]["median"]
    for arm in ARMS:
        if arm == "prod":
            continue
        m = out["arms"][arm]["median"]
        if pm and m:
            log(f"  Δmedian {arm}-prod = {m-pm:+,.0f}")
    json.dump(out, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"# DONE prob_{PROB}")


if __name__ == "__main__":
    main()
