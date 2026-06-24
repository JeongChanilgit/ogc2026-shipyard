"""Isolation test of the per-bay CP-SAT timing lever.
  python notes/_z1_cpsat_iso.py <prob> --base 60 --cpsat 120
Runs our solver (base seconds) to get a feasible LAYOUT, then applies
_cpsat_bay_timing_verified standalone (cpsat seconds) and reports Z1 before/after.
"""
import argparse, sys, time
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
sys.stdout.reconfigure(encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prob")
    ap.add_argument("--base", type=float, default=60)
    ap.add_argument("--cpsat", type=float, default=120)
    args = ap.parse_args()
    import myalgorithm as M
    from utils import check_feasibility, Bay
    p = ROOT/"instances"/"train"/f"{args.prob}.json"
    prob = json.loads(p.read_text(encoding="utf-8"))

    t0=time.time()
    sol = M.algorithm(prob, args.base)
    rep = check_feasibility(prob, sol)
    print(f"[base {args.base:.0f}s] feas={rep.get('feasible')} Z1={rep.get('obj1')} Z2={rep.get('obj2')} Z3={rep.get('obj3')} obj={rep.get('objective')} ({time.time()-t0:.1f}s)", flush=True)
    if not rep.get("feasible"):
        print("base infeasible, abort"); return

    assign, results, flat = M._results_from_solution(prob, sol)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    t1=time.time()
    cand = M._cpsat_bay_timing_verified(prob, bays, results,
                                        deadline=time.monotonic()+args.cpsat,
                                        lb_skip=True)
    dt=time.time()-t1
    if cand is None:
        print(f"[cpsat] no structural improvement (None) ({dt:.1f}s)"); return
    rep2 = check_feasibility(prob, cand)
    print(f"[cpsat {args.cpsat:.0f}s] feas={rep2.get('feasible')} Z1={rep2.get('obj1')} Z2={rep2.get('obj2')} Z3={rep2.get('obj3')} obj={rep2.get('objective')} ({dt:.1f}s)", flush=True)
    z1b, z1a = rep.get('obj1'), rep2.get('obj1')
    print(f"=== {args.prob}: Z1 {z1b} -> {z1a}  (delta {z1a-z1b if z1a is not None and z1b is not None else '?'}); feasible_after={rep2.get('feasible')} obj_safe={rep2.get('objective')<=rep.get('objective') if rep2.get('objective') is not None else '?'}")

if __name__=="__main__":
    main()
