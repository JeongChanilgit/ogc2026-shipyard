"""Collect per-instance STAGE trajectory for the HTML report.

For each instance, run the REAL algorithm with OGC_STAGE_TIMING=1 and capture the
[STAGE_TIMING] (wall-time per stage) + [STAGE_OBJ] (z1/z2/z3/obj after each adopted
stage) JSON the algorithm emits to stderr, plus the final z1/z2/z3/obj.  Saves
results/stage_trace/<tag>/<inst>.json = {final:{...}, stage_timing:{...}, stage_obj:{...}}.

  python notes/_stage_collect.py --instances ALL --timelimit 100 --concurrency 2 \
        --tag default
  python notes/_stage_collect.py --instances ALL --timelimit 100 --concurrency 2 \
        --tag raster --env OGC_FLOOR_RASTER=1,OGC_FAST_FLOOR_POS_K=3
"""
import argparse, json, os, subprocess, re
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
print("FINAL" + json.dumps({"wall": round(dt,2), "feas": bool(feas),
                            "z1": o1, "z2": o2, "z3": o3, "obj": obj}))
'''

def run(inst, tl, outdir, env_extra):
    env = dict(os.environ)
    env["OGC_STAGE_TIMING"] = "1"
    env.update(env_extra)
    drv = outdir / "_sc_driver.py"; drv.write_text(DRIVER)
    try:
        p = subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl)],
                           cwd=str(ROOT), env=env, capture_output=True, text=True,
                           timeout=tl+200)
    except Exception as e:
        return inst, {"err": f"{type(e).__name__}: {e}"}
    blob = (p.stdout or "") + "\n" + (p.stderr or "")
    rec = {}
    for tag, key in (("[STAGE_TIMING]", "stage_timing"),
                     ("[STAGE_OBJ]", "stage_obj"), ("FINAL", "final")):
        m = None
        for line in blob.splitlines():
            i = line.find(tag)
            if i >= 0:
                try:
                    m = json.loads(line[i+len(tag):])
                except Exception:
                    pass
        rec[key] = m
    (outdir / f"{inst}.json").write_text(json.dumps(rec))
    fin = rec.get("final") or {}
    return inst, fin

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--timelimit", type=float, default=100.0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--tag", default="default")
    ap.add_argument("--env", default="")
    a = ap.parse_args()
    insts = ALL20 if a.instances.strip().upper() == "ALL" else \
            [s.strip() for s in a.instances.split(",") if s.strip()]
    env_extra = {}
    for kv in a.env.split(","):
        kv = kv.strip()
        if "=" in kv:
            k, v = kv.split("=", 1); env_extra[k.strip()] = v.strip()
    outdir = ROOT / "results" / "stage_trace" / a.tag
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"collect tag={a.tag} tl={a.timelimit} conc={a.concurrency} env={env_extra}")
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = {ex.submit(run, i, a.timelimit, outdir, env_extra): i for i in insts}
        for f in futs:
            i, fin = f.result()
            print(f"[done] {i:9} z1={fin.get('z1', fin.get('err'))} "
                  f"obj={fin.get('obj','-')} wall={fin.get('wall','-')}", flush=True)
    print(f"saved -> {outdir}")

if __name__ == "__main__":
    main()
