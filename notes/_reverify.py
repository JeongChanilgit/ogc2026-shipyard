"""Re-verify partial-data hypotheses across ALL 20 instances.  Read-only.
SEQUENTIAL (submission) config.

configs:
  ee        = submission default (order-break ON, slab ON) + early-exit   [authoritative z1]
  no_ob_ee  = ee but OGC_ORDER_BREAK=0   -> order-break z1-safety (ee.z1 == no_ob_ee.z1 ?)
  bestof_ee = ee + OGC_SLAB_BESTOF=1     -> best-of FULL-20 effect (regresses easy?)
  noEE      = submission default, NO early-exit (full) -> early-exit obj-safety (ee.obj == noEE.obj on z1=0 ?)

  python notes/_reverify.py --timelimit 300 --concurrency 4
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

CONFIGS = {
    "ee":        {"OGC_EXIT_ON_Z1_ZERO": "1"},
    "no_ob_ee":  {"OGC_EXIT_ON_Z1_ZERO": "1", "OGC_ORDER_BREAK": "0"},
    "bestof_ee": {"OGC_EXIT_ON_Z1_ZERO": "1", "OGC_SLAB_BESTOF": "1"},
    "noEE":      {},
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
    res = OUT / f"_rv_{inst}_{cfg}.json"
    drv = OUT / "_rv_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+160)
    except Exception as e:
        return inst, cfg, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return inst, cfg, json.load(open(res))
        except Exception: return inst, cfg, {"err": "parse"}
    return inst, cfg, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default=",".join(f"prob_{n}" for n in range(1, 21)))
    ap.add_argument("--configs", default="ee,no_ob_ee,bestof_ee,noEE")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    cfgs = [s.strip() for s in a.configs.split(",") if s.strip()]
    tasks = [(i, c) for i in insts for c in cfgs]
    R = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, i, c, a.timelimit) for i, c in tasks]
        for f in futs:
            i, c, r = f.result(); R[(i, c)] = r
            print(f"[done] {i:9} {c:10} z1={r.get('z1', r.get('err'))}", flush=True)

    def g(i, c, k):
        r = R.get((i, c), {}); return None if "err" in r else r.get(k)

    print("\n=== authoritative z1 (config=ee) ===")
    z0 = [i for i in insts if (g(i,"ee","z1") or 0) <= 1e-9]
    print(f"z1=0: {len(z0)}/{len(insts)} -> {z0}")
    print("z1>0:", [(i, g(i,"ee","z1")) for i in insts if (g(i,"ee","z1") or 1) > 1e-9])

    print("\n=== H:order-break  (ee.z1 vs no_ob_ee.z1; want EQUAL) ===")
    diff = [(i, g(i,"ee","z1"), g(i,"no_ob_ee","z1")) for i in insts
            if g(i,"ee","z1") is not None and g(i,"no_ob_ee","z1") is not None
            and abs(g(i,"ee","z1")-g(i,"no_ob_ee","z1"))>1e-6]
    print("mismatches:", diff or "NONE -> order-break objective-safe across 20")

    print("\n=== H:early-exit obj-safety  (ee.obj vs noEE.obj; want EQUAL on z1=0) ===")
    rows=[]
    for i in insts:
        eo, no = g(i,"ee","obj"), g(i,"noEE","obj")
        ez = g(i,"ee","z1")
        if eo is None or no is None: continue
        if abs(eo-no) > 1e-6:
            rows.append((i, ez, eo, no, "EE worse" if eo>no else "EE better"))
    print("obj differences:", rows or "NONE -> early-exit loses no objective")

    print("\n=== H:best-of full-20  (ee.z1 vs bestof_ee.z1) ===")
    print(f"{'inst':9} {'ee':>6} {'bestof':>7}")
    ez0=bz0=0
    for i in insts:
        ez, bz = g(i,"ee","z1"), g(i,"bestof_ee","z1")
        if ez is None or bz is None: print(f"{i:9}  (err)"); continue
        ez0+=(ez<=1e-9); bz0+=(bz<=1e-9)
        mark = "*" if bz<ez-1e-9 else ("x" if bz>ez+1e-9 else "")
        print(f"{i:9} {ez:>6.0f} {bz:>6.0f}{mark}")
    print(f"z1=0: ee={ez0}  bestof={bz0}   (* better, x worse)")

if __name__ == "__main__":
    main()
