"""Isolation test of temporal-reassign lever. base solver -> _temporal_reassign.
  python notes/_z1_temporal_iso.py <prob> --base 120 --reassign 120
"""
import argparse, sys, time, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("prob")
    ap.add_argument("--base",type=float,default=120); ap.add_argument("--reassign",type=float,default=120)
    ap.add_argument("--alpha",type=float,default=0.9); ap.add_argument("--train",default="train")
    a=ap.parse_args()
    import myalgorithm as M
    from utils import check_feasibility, Bay
    prob=json.loads((ROOT/'instances'/a.train/f'{a.prob}.json').read_text(encoding='utf-8'))
    sol=M.algorithm(prob,a.base); rep=check_feasibility(prob,sol)
    print(f"[base {a.base:.0f}s] feas={rep.get('feasible')} Z1={rep.get('obj1')} obj={rep.get('objective')}",flush=True)
    if not rep.get('feasible'): return
    bays=[Bay.from_dict(d,i) for i,d in enumerate(prob['bays'])]
    blocks=prob['blocks']
    feasible_bays=M._feasible_bays(blocks,bays)
    _,results,_=M._results_from_solution(prob,sol)
    _ba=[b['width']*b['height'] for b in prob['bays']]; _avg=sum(_ba)/len(_ba)
    bay_u=[_avg/a for a in _ba]
    t=time.time()
    cand=M._temporal_reassign_redecode_verified(prob,bays,feasible_bays,results,bay_u,
              deadline=time.monotonic()+a.reassign,alpha=a.alpha)
    dt=time.time()-t
    if cand is None:
        print(f"[temporal {dt:.1f}s] None"); return
    r2=check_feasibility(prob,cand)
    ok = r2.get('feasible') and r2.get('objective') is not None and r2['objective']<rep['objective']-1e-9
    print(f"[temporal {dt:.1f}s] feas={r2.get('feasible')} Z1={r2.get('obj1')} Z2={r2.get('obj2')} Z3={r2.get('obj3')} obj={r2.get('objective')} adopt={ok}",flush=True)
    print(f"=== {a.prob}: Z1 {rep.get('obj1')} -> {r2.get('obj1')}  obj_safe={r2.get('objective')<=rep.get('objective')+1e-9 if r2.get('objective') else '?'}")
if __name__=="__main__": main()
