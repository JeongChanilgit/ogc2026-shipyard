"""Faithful full-set capture: run the REAL submission path (NO OGC_EXIT_ON_Z1_ZERO)
and SAVE the solution dict + metrics per instance, so downstream diagnostics
(per-bay tardiness LB gap, Z2/Z3 headroom) can run instantly without re-solving.

  python notes/_capture20.py --instances prob_11,prob_12,prob_13,prob_20 \
        --timelimit 300 --concurrency 3 --tag base
  python notes/_capture20.py --instances ALL --timelimit 300 --tag xbatch \
        --env OGC_XBAY_BATCH=1

Writes results/capture/<tag>/<inst>.json = {met:{...}, solution:{...}}.
Env overrides via --env K=V,K=V (faithful: nothing forced; you pass exactly the
flags the candidate config uses).  conc 3 = eval-faithful (3x4=12 cores).
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

ALL20 = [f"prob_{i}" for i in range(1, 21)]

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"met": {"wall": round(dt,2), "feas": bool(feas), "z1": o1, "z2": o2,
                   "z3": o3, "obj": obj},
           "solution": sol},
          open(sys.argv[3], "w"))
'''

def run(inst, tl, outdir, env_extra):
    env = dict(os.environ); env.update(env_extra)
    res = outdir / f"{inst}.json"
    drv = outdir / "_cap_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=tl+200)
    except Exception as e:
        return inst, {"err": f"{type(e).__name__}: {e}"}
    if res.exists():
        try: return inst, json.load(open(res))["met"]
        except Exception as e: return inst, {"err": f"parse: {e}"}
    return inst, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--tag", default="base")
    ap.add_argument("--env", default="")
    a = ap.parse_args()
    insts = ALL20 if a.instances.strip().upper() == "ALL" else \
            [s.strip() for s in a.instances.split(",") if s.strip()]
    env_extra = {}
    for kv in a.env.split(","):
        kv = kv.strip()
        if "=" in kv:
            k, v = kv.split("=", 1); env_extra[k.strip()] = v.strip()
    outdir = ROOT / "results" / "capture" / a.tag
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"capture tag={a.tag} tl={a.timelimit} conc={a.concurrency} "
          f"env={env_extra} n={len(insts)}")
    res = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = {ex.submit(run, i, a.timelimit, outdir, env_extra): i for i in insts}
        for f in futs:
            i, m = f.result(); res[i] = m
            print(f"[done] {i:9} z1={m.get('z1', m.get('err'))} "
                  f"obj={m.get('obj','-')} wall={m.get('wall','-')}", flush=True)
    print("\n=== capture summary (tag=%s) ===" % a.tag)
    feas_all = True; z1pos = []
    for i in insts:
        m = res.get(i, {})
        if "err" in m: print(f"  {i:9} ERR {m['err']}"); feas_all = False; continue
        if not m.get("feas"): feas_all = False
        tag = ""
        if m.get("z1", 0) > 0: z1pos.append((i, m["z1"])); tag = "  <-- z1>0"
        print(f"  {i:9} z1={m['z1']:>5} z2={m['z2']:>6} z3={m['z3']:>7} "
              f"obj={m['obj']:>9} wall={m['wall']:>6}{tag}")
    print(f"\n  feasible(all, no -1): {feas_all}")
    print(f"  z1>0: {z1pos}")
    print(f"  saved solutions -> {outdir}")

if __name__ == "__main__":
    main()
