"""Isolate what drives prob_20 (5-bay) Z1: PARALLEL cum_level? REDECODE_FAST? slab?
Runs the same instance under several configs (+ a repeat to gauge ±20x variance).
Read-only.

  python notes/_prob20_iso.py --inst prob_20 --timelimit 300 --concurrency 2
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

# (label, env) -- two "par" runs to see variance
RUNS = [
    ("default",     {}),
    ("par",         {"OGC_CUMLEVEL_PARALLEL": "1"}),
    ("par#2",       {"OGC_CUMLEVEL_PARALLEL": "1"}),
    ("par_fast",    {"OGC_CUMLEVEL_PARALLEL": "1", "OGC_REDECODE_FAST": "1"}),
    ("par_fast#2",  {"OGC_CUMLEVEL_PARALLEL": "1", "OGC_REDECODE_FAST": "1"}),
]

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"wall": round(dt,2), "feas": bool(feas), "z1": o1, "z2": o2, "z3": o3,
           "obj": obj}, open(sys.argv[3], "w"))
'''

def run(inst, label, env_extra, tl):
    env = dict(os.environ); env.update(env_extra)
    safe = label.replace("#", "_")
    res = OUT / f"_p20_{inst}_{safe}.json"
    drv = OUT / "_p20_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+150)
    except Exception as e:
        return label, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return label, json.load(open(res))
        except Exception: return label, {"err": "parse"}
    return label, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="prob_20")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=2)
    a = ap.parse_args()
    out = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, a.inst, lab, env, a.timelimit) for lab, env in RUNS]
        for f in futs:
            lab, r = f.result(); out[lab] = r
            print(f"[done] {lab:12} {r}", flush=True)
    print(f"\n=== {a.inst} config isolation ===")
    print(f"{'config':12} {'z1':>8} {'z2':>8} {'wall':>8} feas")
    for lab, _ in RUNS:
        r = out.get(lab, {})
        if "err" in r: print(f"{lab:12} ERR {r['err']}"); continue
        print(f"{lab:12} {r['z1']:>8.0f} {r['z2']:>8.0f} {r['wall']:>7.1f}s {r['feas']}")

if __name__ == "__main__":
    main()
