"""Collect [STAGE_TIMING] per-stage wall breakdown for given instances.  Read-only.

Runs each instance through the FULL algorithm (solve config) in an isolated
subprocess, captures the [STAGE_TIMING]{...} stderr line, and prints a per-stage
seconds table so we can see whether a slow instance is baseline-bound or
search/lever-bound.  Runs concurrently as ONE tracked process (no orphaned &).
"""
import argparse, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

DRIVER = r'''
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
sol = algorithm(prob, float(sys.argv[2]))
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
print("RESULT " + json.dumps({"feas": bool(feas), "z1": o1, "obj": obj}), file=sys.stderr)
'''

def run(inst, tl):
    env = dict(os.environ)
    env.update({"OGC_CUMLEVEL_PARALLEL": "1", "OGC_REDECODE_FAST": "1",
                "OGC_CPSAT_ZERO_STOP": "1", "OGC_EXIT_ON_Z1_ZERO": "1",
                "OGC_STAGE_TIMING": "1"})
    drv = ROOT / "results" / "z1traj" / "_st_driver.py"
    drv.write_text(DRIVER)
    try:
        p = subprocess.run([PYEXE, str(drv), str(TRAIN / f"{inst}.json"), str(tl)],
                           cwd=str(ROOT), env=env, capture_output=True, text=True,
                           timeout=tl + 120)
    except Exception as e:
        return inst, {"err": f"{type(e).__name__}: {e}"}
    stages = {}; result = {}
    for ln in (p.stderr or "").splitlines():
        if "[STAGE_TIMING]" in ln:
            try:
                stages = json.loads(ln.split("[STAGE_TIMING]", 1)[1])
            except Exception:
                pass
        if ln.startswith("RESULT "):
            try:
                result = json.loads(ln[7:])
            except Exception:
                pass
    return inst, {"stages": stages, "result": result}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="prob_1,prob_6,prob_17")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    out = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for inst, rec in ex.map(lambda i: run(i, a.timelimit), insts):
            out[inst] = rec
            print(f"[done] {inst}", flush=True)
    for inst in insts:
        rec = out.get(inst, {})
        if "err" in rec:
            print(f"\n### {inst}: ERR {rec['err']}")
            continue
        st = rec.get("stages", {}) or {}
        res = rec.get("result", {}) or {}
        total = st.get("total_s")
        stages = st.get("stages", {}) or {}
        print(f"\n### {inst}  total={total}s  z1={res.get('z1')} feas={res.get('feas')} "
              f"(n_blocks={st.get('n_blocks')}, n_bays={st.get('n_bays')})")
        for k, v in sorted(stages.items(), key=lambda kv: -float(kv[1] or 0)):
            pct = (100.0 * float(v) / total) if total else 0.0
            print(f"   {k:20} {float(v):8.1f}s  {pct:5.1f}%")
        other = st.get("search_baseline_other_s")
        if other is not None:
            print(f"   {'(other)':20} {float(other):8.1f}s")

if __name__ == "__main__":
    main()
