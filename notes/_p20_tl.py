"""prob_20 time-limit sweep (default submission config): does MORE time keep
lowering Z1, or does it plateau?  Read-only.

  python notes/_p20_tl.py --inst prob_20 --tls 300,600,1200 --concurrency 3
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
    env = dict(os.environ)  # pure submission default
    res = OUT / f"_p20tl_{inst}_{int(tl)}.json"
    drv = OUT / "_p20tl_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+200)
    except Exception as e:
        return tl, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return tl, json.load(open(res))
        except Exception: return tl, {"err": "parse"}
    return tl, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", default="prob_20")
    ap.add_argument("--tls", default="300,600,1200")
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    tls = [float(x) for x in a.tls.split(",")]
    out = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for tl, r in ex.map(lambda t: run(a.inst, t), tls):
            out[tl] = r
            print(f"[done] tl={int(tl)}s {r}", flush=True)
    print(f"\n=== {a.inst} time-limit sweep (default config) ===")
    print(f"{'timelimit':>10} {'z1':>9} {'obj':>14} {'wall':>8}")
    for tl in tls:
        r = out.get(tl, {})
        if "err" in r: print(f"{int(tl):>9}s ERR {r['err']}"); continue
        print(f"{int(tl):>9}s {r['z1']:>9.0f} {r['obj']:>14.0f} {r['wall']:>7.1f}s")

if __name__ == "__main__":
    main()
