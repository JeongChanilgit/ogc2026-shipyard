"""Clean full-20 baseline on the SUBMISSION-DEFAULT config (no polluting flags).
Adds only OGC_EXIT_ON_Z1_ZERO (returns at z1=0 -> same z1, faster).  Read-only.
Reports per-instance z1/z2/z3/obj/wall and the z1=0 count, so we know the REAL
current state before building quality levers.

  python notes/_clean_baseline.py --timelimit 300 --concurrency 4
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

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

def run(inst, tl):
    env = dict(os.environ); env["OGC_EXIT_ON_Z1_ZERO"] = "1"   # submission default + stop-at-0
    res = OUT / f"_clean_{inst}.json"
    drv = OUT / "_clean_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+150)
    except Exception as e:
        return inst, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return inst, json.load(open(res))
        except Exception: return inst, {"err": "parse"}
    return inst, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default=",".join(f"prob_{n}" for n in range(1, 21)))
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    res = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, i, a.timelimit) for i in insts]
        for f in futs:
            i, r = f.result(); res[i] = r
            print(f"[done] {i:9} {r}", flush=True)
    print(f"\n=== CLEAN baseline (submission default + early-exit) ===")
    print(f"{'inst':9} {'z1':>6} {'z2':>7} {'z3':>7} {'wall':>8} feas")
    zeros = []; nonzero = []
    for i in insts:
        r = res.get(i, {})
        if "err" in r:
            print(f"{i:9} ERR {r['err']}"); continue
        z1 = r["z1"]
        print(f"{i:9} {z1:>6.0f} {r['z2']:>7.0f} {r['z3']:>7.0f} {r['wall']:>7.1f}s {r['feas']}")
        (zeros if z1 <= 1e-9 else nonzero).append((i, z1))
    print(f"\nz1=0: {len(zeros)}/{len(insts)}  ->  {[i for i,_ in zeros]}")
    print(f"z1>0: {[f'{i}({int(z)})' for i,z in nonzero]}")

if __name__ == "__main__":
    main()
