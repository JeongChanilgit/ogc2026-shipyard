"""Direct isolation test: does perbay.improve() reduce per-bay tardiness (z1)
on a tardy instance, independent of the hybrid budget plumbing?

Run: C:/Users/peter/anaconda3/envs/ogc2025/python.exe notes/_perbay_direct.py prob_14 40
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, "src")

import myalgorithm
import perbay
from utils import check_feasibility


def run(name, leg_budget, pb_budget):
    path = os.path.join("instances", "train", name + ".json")
    with open(path, "r", encoding="utf-8") as f:
        prob = json.load(f)

    t0 = time.monotonic()
    sol_base = myalgorithm._legacy_algorithm(prob, leg_budget)
    t_leg = time.monotonic() - t0
    cb = check_feasibility(prob, sol_base)
    print(f"[{name}] legacy {leg_budget}s -> wall={t_leg:.1f}s feasible={cb.get('feasible')} "
          f"obj={cb.get('objective')} z1={cb.get('obj1')} z2={cb.get('obj2')} z3={cb.get('obj3')}",
          flush=True)

    t1 = time.monotonic()
    sol_pb = perbay.improve(prob, sol_base, pb_budget)
    t_pb = time.monotonic() - t1
    fired = sol_pb is not sol_base
    cp = check_feasibility(prob, sol_pb)
    print(f"[{name}] perbay {pb_budget}s -> wall={t_pb:.1f}s fired={fired} feasible={cp.get('feasible')} "
          f"obj={cp.get('objective')} z1={cp.get('obj1')} z2={cp.get('obj2')} z3={cp.get('obj3')}",
          flush=True)
    if fired and not cp.get("feasible"):
        viol = cp.get("violations")
        print(f"[{name}] INFEASIBLE stage={cp.get('stage')} violations[:3]={str(viol)[:400]}", flush=True)

    if cb.get("feasible") and cp.get("feasible"):
        d = cp["objective"] - cb["objective"]
        dz1 = (cp.get("obj1") or 0) - (cb.get("obj1") or 0)
        print(f"[{name}] DELTA obj={d:+.1f}  z1={dz1:+.1f}  "
              f"{'IMPROVED' if d < -1e-9 else ('NOOP' if abs(d)<1e-9 else 'REGRESS')}", flush=True)
    print("-" * 70, flush=True)


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "prob_14"
    leg = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0
    pb = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
    run(name, leg, pb)
