"""A/B: greedy baseline ON vs OFF (OGC_SKIP_BASELINE).  Read-only experiment.

For each instance, run config A (baseline ON) and B (baseline OFF) in isolated
subprocesses (env python direct -> concurrency-safe), verify each result with the
official checker via ogc_analysis, and print a head-to-head table.  Does NOT touch
the dashboard.  Usage:
  python notes/_ab_baseline.py --instances prob_3,prob_8,prob_5,prob_7 --timelimit 180 --concurrency 4
"""
import argparse, json, os, subprocess, sys, time, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
OUT.mkdir(parents=True, exist_ok=True)
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

COMMON = {
    "OGC_CUMLEVEL_PARALLEL": "1", "OGC_REDECODE_FAST": "1",
    "OGC_CPSAT_ZERO_STOP": "1", "OGC_EXIT_ON_Z1_ZERO": "1",
}
CONFIGS = {"A_base_on": dict(COMMON),
           "B_base_off": {**COMMON, "OGC_SKIP_BASELINE": "1"}}

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
tl = float(sys.argv[2]); out = sys.argv[3]
t0 = time.monotonic(); sol = algorithm(prob, tl); dt = time.monotonic() - t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"wall": round(dt, 2), "feasible": bool(feas), "z1": o1,
           "z2": o2, "z3": o3, "obj": obj}, open(out, "w"))
'''

def run_one(inst, cfg, tl):
    env = dict(os.environ); env.update(CONFIGS[cfg])
    res = OUT / f"_ab_{inst}_{cfg}.json"
    if res.exists():
        res.unlink()
    drv = OUT / f"_ab_driver_{inst}_{cfg}.py"
    drv.write_text(DRIVER)
    t0 = time.perf_counter()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN / f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=tl + 120)
    except Exception as e:
        return inst, cfg, {"err": f"{type(e).__name__}: {e}",
                           "wall": round(time.perf_counter() - t0, 2)}
    if res.exists():
        try:
            return inst, cfg, json.load(open(res))
        except Exception as e:
            return inst, cfg, {"err": f"parse: {e}"}
    return inst, cfg, {"err": "no result file"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="prob_3,prob_8,prob_5,prob_7")
    ap.add_argument("--timelimit", type=float, default=180.0)
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    tasks = [(i, c) for i in insts for c in CONFIGS]
    results = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run_one, i, c, a.timelimit) for i, c in tasks]
        for f in futs:
            inst, cfg, rec = f.result()
            results[(inst, cfg)] = rec
            print(f"[done] {inst:9} {cfg:11} {rec}", flush=True)
    print("\n=== A/B  baseline ON vs OFF  (timelimit={:.0f}s) ===".format(a.timelimit))
    print(f"{'inst':9} | {'A z1':>6} {'A feas':>6} {'A wall':>7} | "
          f"{'B z1':>6} {'B feas':>6} {'B wall':>7} | verdict")
    for i in insts:
        A_ = results.get((i, "A_base_on"), {})
        B_ = results.get((i, "B_base_off"), {})
        az1, af, aw = A_.get("z1"), A_.get("feasible"), A_.get("wall")
        bz1, bf, bw = B_.get("z1"), B_.get("feasible"), B_.get("wall")
        if "err" in B_:
            verdict = "B ERR: " + str(B_["err"])[:40]
        elif not bf:
            verdict = "B INFEASIBLE (-1!) -> baseline load-bearing"
        elif az1 is not None and bz1 is not None:
            if bz1 <= az1 + 1e-9:
                verdict = "B ties/beats A -> baseline maybe removable"
            else:
                verdict = f"B worse z1 ({bz1} vs {az1}) -> baseline helps"
        else:
            verdict = "?"
        def fmt(v): return f"{v:.1f}" if isinstance(v, (int, float)) else str(v)
        print(f"{i:9} | {fmt(az1):>6} {str(af):>6} {fmt(aw):>7} | "
              f"{fmt(bz1):>6} {str(bf):>6} {fmt(bw):>7} | {verdict}")

if __name__ == "__main__":
    main()
