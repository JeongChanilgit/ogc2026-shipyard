"""Isolation test of the anti-stacking chain: base layout -> cumulative-leveled
re-decode -> CP-SAT optimal timing.  Reports Z1 after each stage (all gated for
feasibility + objective-safety by check_feasibility).
  python notes/_z1_cumlevel_iso.py <prob> --base 240 --cum 60 --alpha 0.9
"""
import argparse, sys, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
sys.stdout.reconfigure(encoding="utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("prob"); ap.add_argument("--base",type=float,default=240)
    ap.add_argument("--cum",type=float,default=60); ap.add_argument("--alpha",type=float,default=0.9)
    a=ap.parse_args()
    import myalgorithm as M
    from utils import check_feasibility, Bay
    prob=json.loads((ROOT/"instances"/"train"/f"{a.prob}.json").read_text(encoding="utf-8"))
    sol=M.algorithm(prob, a.base)
    rep=check_feasibility(prob, sol)
    print(f"[base {a.base:.0f}s] feas={rep.get('feasible')} Z1={rep.get('obj1')} obj={rep.get('objective')}", flush=True)
    if not rep.get("feasible"): print("infeasible base"); return
    bays=[Bay.from_dict(d,i) for i,d in enumerate(prob["bays"])]
    base_obj=rep.get("objective"); cur_sol=sol; cur_obj=base_obj; cur_z1=rep.get('obj1')

    # stage 1: cumulative-leveled redecode
    _,results,_=M._results_from_solution(prob,cur_sol)
    t=time.time()
    cand=M._cumulative_leveled_redecode_verified(prob,bays,results,deadline=time.monotonic()+a.cum,alpha=a.alpha)
    dt=time.time()-t
    if cand is not None:
        r2=check_feasibility(prob,cand)
        ok = r2.get('feasible') and r2.get('objective') is not None and r2['objective']<cur_obj-1e-9
        print(f"[cum_level a={a.alpha} {dt:.1f}s] feas={r2.get('feasible')} Z1={r2.get('obj1')} obj={r2.get('objective')} adopt={ok}", flush=True)
        if ok: cur_sol=cand; cur_obj=r2['objective']; cur_z1=r2.get('obj1')
    else:
        print(f"[cum_level {dt:.1f}s] None")

    # stage 2: CP-SAT optimal timing on the (possibly new) layout
    _,results,_=M._results_from_solution(prob,cur_sol)
    t=time.time()
    cand=M._cpsat_bay_timing_verified(prob,bays,results,deadline=time.monotonic()+30,lb_skip=True)
    dt=time.time()-t
    if cand is not None:
        r3=check_feasibility(prob,cand)
        ok = r3.get('feasible') and r3.get('objective') is not None and r3['objective']<cur_obj-1e-9
        print(f"[cpsat_timing {dt:.1f}s] feas={r3.get('feasible')} Z1={r3.get('obj1')} obj={r3.get('objective')} adopt={ok}", flush=True)
        if ok: cur_z1=r3.get('obj1'); cur_obj=r3['objective']
    else:
        print(f"[cpsat_timing {dt:.1f}s] None")
    print(f"=== {a.prob}: Z1 {rep.get('obj1')} -> {cur_z1}  (target<20)  obj_safe={cur_obj<=base_obj+1e-9}")

if __name__=="__main__": main()
