"""A/B cum_level search-breadth vs z1/time.  Read-only; uses existing env knobs.

cum_level dominates 70-76% of wall on z1=0 instances and runs 3 alphas x 3 orders
per tardy bay.  Hypothesis: a leaner search still reaches z1=0 but much faster.
Compares named configs on each instance (z1, feasible, wall) in isolated subprocs.

  python notes/_ab_cumlevel.py --instances prob_1,prob_3,prob_6,prob_8,prob_17 --timelimit 300 --concurrency 2
"""
import argparse, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

BASE = {"OGC_CUMLEVEL_PARALLEL": "1", "OGC_REDECODE_FAST": "1",
        "OGC_CPSAT_ZERO_STOP": "1", "OGC_EXIT_ON_Z1_ZERO": "1"}
CONFIGS = {
    "full_3x3":  {**BASE, "OGC_CUMLEVEL_ALPHAS": "90;85;80", "OGC_CUMLEVEL_ORDERS": "3"},
    "lean_1x1":  {**BASE, "OGC_CUMLEVEL_ALPHAS": "90",        "OGC_CUMLEVEL_ORDERS": "1"},
    "mid_1x2":   {**BASE, "OGC_CUMLEVEL_ALPHAS": "90",        "OGC_CUMLEVEL_ORDERS": "2"},
}

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"wall": round(dt,2), "feas": bool(feas), "z1": o1, "obj": obj}, open(sys.argv[3],"w"))
'''

def run(inst, cfg, tl):
    env = dict(os.environ); env.update(CONFIGS[cfg])
    res = OUT / f"_abc_{inst}_{cfg}.json"
    drv = OUT / "_abc_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+120)
    except Exception as e:
        return inst, cfg, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return inst, cfg, json.load(open(res))
        except Exception as e: return inst, cfg, {"err": "parse"}
    return inst, cfg, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="prob_1,prob_3,prob_6,prob_8,prob_17")
    ap.add_argument("--configs", default="full_3x3,lean_1x1,mid_1x2")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=2)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    cfgs = [s.strip() for s in a.configs.split(",") if s.strip()]
    tasks = [(i, c) for i in insts for c in cfgs]
    res = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, i, c, a.timelimit) for i, c in tasks]
        for f in futs:
            i, c, r = f.result(); res[(i, c)] = r
            print(f"[done] {i:9} {c:10} {r}", flush=True)
    print("\n=== cum_level breadth A/B  (z1 / wall s) ===")
    hdr = f"{'inst':9}"
    for c in cfgs: hdr += f" | {c:>16}"
    print(hdr)
    for i in insts:
        row = f"{i:9}"
        for c in cfgs:
            r = res.get((i, c), {})
            if "err" in r: row += f" | {('ERR '+r['err']):>16}"
            else: row += f" | z1={r.get('z1'):<4} {r.get('wall'):>6}s"
        print(row)

if __name__ == "__main__":
    main()
