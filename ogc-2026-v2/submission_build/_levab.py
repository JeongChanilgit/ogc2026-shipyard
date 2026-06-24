"""_levab.py PROB [CORES] -- deadline-bound convergence A/B of repack levers.

ONE instance per process (launch several in parallel on disjoint cores).  Shared
greedy start (sol0) across all arms so the only difference is the lever env; each
arm runs postproc.postprocess for a fixed total budget in CHUNK steps, logging
the obj convergence curve.  The question: does a cheaper pass (smaller model)
buy MORE rounds and thus a LOWER final obj within the same wall budget?

Judge = final obj per arm (lower better).  Never-worse is guaranteed by postproc
(gated additive), so no arm can be worse than the greedy start; the A/B is purely
"how much does each arm improve in the same budget".

env: C:/Users/peter/anaconda3/envs/ogc2025/python.exe   out: _levab_<prob>.log
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, V7)
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1").items():
    os.environ.setdefault(k, v)

PROB = int(sys.argv[1]) if len(sys.argv) > 1 else 38
CORES = sys.argv[2] if len(sys.argv) > 2 else "0,1,2,3"
try:
    import psutil; psutil.Process().cpu_affinity([int(c) for c in CORES.split(",")])
except Exception:
    pass

import unified_greedy as UG            # noqa: E402
import postproc as PP                  # noqa: E402
from v3pp import adapter, seed as S    # noqa: E402
assert "v7" in UG.__file__.replace("\\", "/") and "v7" in PP.__file__.replace("\\", "/")

BASE = "C:/claude-develop/OGC2026"
LOG = os.path.join(SB, f"_levab_{PROB}.log")
TLG = float(os.environ.get("M1_TLG", "70"))
TOTAL = float(os.environ.get("M1_PPT", "240"))
CHUNK = float(os.environ.get("M1_CHUNK", "80"))

# all lever knobs popped before each arm so arms don't leak into each other
_LEVER_KEYS = ["OGC_PP_ACTIVE_CAP", "OGC_PP_ACTIVE_MODE", "OGC_PP_MEMO",
               "OGC_PP_K", "OGC_PP_BLPROBE", "OGC_XSMART", "OGC_PP_TIGHTEN"]

ARMS = {
    "prod    ": {},                                           # production (all off)
    "cap20   ": {"OGC_PP_ACTIVE_CAP": "20"},                  # P1① cap
    "cap40   ": {"OGC_PP_ACTIVE_CAP": "40"},                  # P1① cap
    "cap20mem": {"OGC_PP_ACTIVE_CAP": "20", "OGC_PP_MEMO": "1"},  # +P1③ memo
    "K3      ": {"OGC_PP_K": "3"},                            # P1② fewer candidates
}


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)


def fmt(x):
    return "-" if x is None else f"{x:,.0f}"


def curve(data, sol0, env, tag):
    for k in _LEVER_KEYS:
        os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = v
    sol = json.loads(json.dumps(sol0))
    done = 0.0
    ev = S.global_eval(data, adapter.deserialize(data, sol))
    start = ev["obj"]
    while done < TOTAL - 1:
        dur = min(CHUNK, TOTAL - done)
        sol = PP.postprocess(data, sol, time.monotonic() + dur)
        done += dur
        ev = S.global_eval(data, adapter.deserialize(data, sol))
        log(f"    [{tag} t={done:>4.0f}s] obj={fmt(ev['obj']):>14} "
            f"z1={fmt(ev['z1']):>8} z3={fmt(ev['z3']):>6}")
    return start, ev["obj"]


def main():
    log(f"\n\n# ===== LEVER A/B  prob_{PROB}  cores={CORES}  "
        f"TLG={TLG:.0f} budget={TOTAL:.0f}s/arm  {time.strftime('%H:%M')} =====")
    path = f"{BASE}/instances/train/prob_{PROB}.json"
    data = json.load(open(path, encoding="utf-8"))
    for k in _LEVER_KEYS:
        os.environ.pop(k, None)
    UG._REGREEDY_PEN = {}
    t0 = time.time()
    res = UG.unified(data, TLG, path)[0]
    sol0 = res["_solution"]
    g = S.global_eval(data, adapter.deserialize(data, sol0))
    log(f"# greedy {time.time()-t0:.0f}s  start obj={fmt(g['obj'])} "
        f"z1={fmt(g['z1'])} (w1={data['weights']['w1']:,})")
    out = {}
    for tag, env in ARMS.items():
        t = time.time()
        try:
            start, final = curve(data, sol0, env, tag)
            out[tag.strip()] = final
            log(f"  {tag} FINAL = {fmt(final)}  (improved {fmt(start-final)} "
                f"in {time.time()-t:.0f}s)")
        except Exception as e:
            log(f"  {tag} FAILED: {e!r}")
            traceback.print_exc()
    base = out.get("prod")
    log(f"\n# --- prob_{PROB} summary (vs prod={fmt(base)}) ---")
    for tag, val in sorted(out.items(), key=lambda kv: kv[1]):
        d = (base - val) if (base is not None and val is not None) else None
        log(f"#   {tag:<9} {fmt(val):>14}  delta={fmt(d):>12} "
            f"{'(better)' if d and d > 0 else '(worse)' if d and d < 0 else ''}")
    log(f"# ===== prob_{PROB} DONE {time.strftime('%H:%M')} =====")


if __name__ == "__main__":
    main()
