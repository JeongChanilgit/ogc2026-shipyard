"""Run the solver with OGC_TRAJ=1 on each instance and save the objective
trajectory (time series of obj/z1/z2/z3 tagged by operating sequence) for
notes/_plot_traj.py.

  python notes/_capture_traj.py --instances prob_4,prob_10 --timelimit 200 --concurrency 3
  python notes/_capture_traj.py --instances ALL --timelimit 200

Writes results/traj/<inst>.json = {"instance","tl","final":{...},"points":[[t,obj,z1,z2,z3,stage],...]}.
The solver prints one line `[TRAJ]{"points":[...]}` on stderr when OGC_TRAJ=1.
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
sol = algorithm(prob, float(sys.argv[2]))
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
sys.stderr.write("[FINAL]" + json.dumps({"feas": bool(feas), "obj": obj,
                 "z1": o1, "z2": o2, "z3": o3}) + "\n")
sys.stderr.flush()
'''


def run(inst, tl):
    env = dict(os.environ)
    env["OGC_TRAJ"] = "1"
    env["OGC_Z1_TRACE"] = "1"
    env["OGC_STAGE_TIMING"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    drv = OUT / "_traj_driver.py"
    drv.write_text(DRIVER)
    try:
        p = subprocess.run([PYEXE, str(drv), str(TRAIN / f"{inst}.json"), str(tl)],
                           cwd=str(ROOT), env=env, capture_output=True, text=True,
                           timeout=tl + 200)
    except Exception as e:
        return inst, {"err": f"{type(e).__name__}: {e}"}
    traj = None
    final = None
    for line in (p.stderr or "").splitlines():
        if line.startswith("[TRAJ]"):
            try:
                traj = json.loads(line[len("[TRAJ]"):])
            except Exception:
                pass
        elif line.startswith("[FINAL]"):
            try:
                final = json.loads(line[len("[FINAL]"):])
            except Exception:
                pass
    if traj is None:
        return inst, {"err": "no [TRAJ] line", "stderr_tail": (p.stderr or "")[-400:]}
    rec = {"instance": inst, "tl": tl, "final": final,
           "points": traj.get("points", [])}
    (OUT / f"{inst}.json").write_text(json.dumps(rec))
    return inst, {"n": len(rec["points"]), "final": final}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--timelimit", type=float, default=200.0)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    insts = ALL20 if a.instances.upper() == "ALL" else \
            [s.strip() for s in a.instances.split(",")]
    print(f"traj capture tl={a.timelimit} conc={a.concurrency} n={len(insts)}")
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = {ex.submit(run, i, a.timelimit): i for i in insts}
        for f in futs:
            i, r = f.result()
            print(f"[done] {i:9} {r}", flush=True)


if __name__ == "__main__":
    main()
