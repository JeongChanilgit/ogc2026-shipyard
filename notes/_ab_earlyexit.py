"""A/B: z1=0 early-exit vs submission default.  Read-only.  SEQUENTIAL cum_level
(NO OGC_CUMLEVEL_PARALLEL -- that flag is the polluting budget-spin).

default  = pure submission (no behavior flags) -> runs full pipeline + search.
earlyexit = + OGC_EXIT_ON_Z1_ZERO=1 -> returns the moment Z1 hits 0.

For each instance reports wall / z1 / obj for both, so we can confirm early-exit
saves time WITHOUT changing the objective (the post-Z1=0 search must be pure waste).

  python notes/_ab_earlyexit.py --instances prob_1,prob_6,prob_8,prob_17 --timelimit 300 --concurrency 3
"""
import argparse, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

CONFIGS = {
    "default":   {},                              # pure submission
    "earlyexit": {"OGC_EXIT_ON_Z1_ZERO": "1"},    # stop at z1=0
}

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

def run(inst, cfg, tl):
    env = dict(os.environ); env.update(CONFIGS[cfg])
    res = OUT / f"_abe_{inst}_{cfg}.json"
    drv = OUT / "_abe_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+120)
    except Exception as e:
        return inst, cfg, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return inst, cfg, json.load(open(res))
        except Exception: return inst, cfg, {"err": "parse"}
    return inst, cfg, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="prob_1,prob_6,prob_8,prob_17")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    tasks = [(i, c) for i in insts for c in CONFIGS]
    res = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, i, c, a.timelimit) for i, c in tasks]
        for f in futs:
            i, c, r = f.result(); res[(i, c)] = r
            print(f"[done] {i:9} {c:10} {r}", flush=True)
    print("\n=== early-exit A/B  (SEQUENTIAL cum_level) ===")
    print(f"{'inst':9} | {'default wall':>12} {'early wall':>11} {'saved':>7} | "
          f"{'def obj':>10} {'early obj':>10} | obj 동일?")
    for i in insts:
        d = res.get((i, "default"), {}); e = res.get((i, "earlyexit"), {})
        if "err" in d or "err" in e:
            print(f"{i:9} | ERR d={d.get('err','-')} e={e.get('err','-')}"); continue
        dw, ew = d["wall"], e["wall"]
        saved = (1 - ew/dw) * 100 if dw else 0
        same = abs(d["obj"] - e["obj"]) < 1e-6
        verdict = "YES" if same else "NO d_obj={} e_obj={} z1={}/{}".format(
            d["obj"], e["obj"], d["z1"], e["z1"])
        print("{:9} | {:>12.1f} {:>11.1f} {:>5.0f}% | {:>10.0f} {:>10.0f} | {}".format(
            i, dw, ew, saved, d["obj"], e["obj"], verdict))

if __name__ == "__main__":
    main()
