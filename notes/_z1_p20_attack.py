"""prob_20 attack: temporal-reassign (balanced assignment) THEN bbox-pack each bay.
  python notes/_z1_p20_attack.py <prob> --base 150 --reassign 60 --bbox 90"""
import argparse, sys, time, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
import myalgorithm as M
from utils import check_feasibility, Bay
ap=argparse.ArgumentParser(); ap.add_argument("prob"); ap.add_argument("--base",type=float,default=150)
ap.add_argument("--reassign",type=float,default=60); ap.add_argument("--bbox",type=float,default=90); ap.add_argument("--alpha",type=float,default=0.85)
a=ap.parse_args()
prob=json.load(open(ROOT/'instances'/'train'/f'{a.prob}.json'))
bays=[Bay.from_dict(d,i) for i,d in enumerate(prob['bays'])]
fb=M._feasible_bays(prob['blocks'],bays)
_ba=[b['width']*b['height'] for b in prob['bays']]; _avg=sum(_ba)/len(_ba); bay_u=[_avg/x for x in _ba]
sol=M.algorithm(prob,a.base); rep=check_feasibility(prob,sol)
print(f"[base] Z1={rep.get('obj1')} obj={rep.get('objective')}",flush=True)
_,results,_=M._results_from_solution(prob,sol)
# 1) bbox-pack current assignment
t=time.time(); cand=M._bbox_pack_redecode_verified(prob,bays,results,deadline=time.monotonic()+a.bbox); 
if cand: 
    r=check_feasibility(prob,cand); print(f"[bbox(cur asgn) {time.time()-t:.1f}s] Z1={r.get('obj1')} feas={r.get('feasible')}",flush=True)
# 2) temporal-reassign -> balanced assignment
t=time.time(); reas=M._temporal_reassign_redecode_verified(prob,bays,fb,results,bay_u,deadline=time.monotonic()+a.reassign,alpha=a.alpha)
if reas is None: print("[reassign] None"); sys.exit()
rr=check_feasibility(prob,reas); print(f"[reassign {time.time()-t:.1f}s] Z1={rr.get('obj1')} feas={rr.get('feasible')}",flush=True)
# 3) bbox-pack the reassigned layout
_,res2,_=M._results_from_solution(prob,reas)
t=time.time(); cand2=M._bbox_pack_redecode_verified(prob,bays,res2,deadline=time.monotonic()+a.bbox)
if cand2 is None: print("[reassign+bbox] None"); sys.exit()
r2=check_feasibility(prob,cand2)
print(f"[reassign+bbox {time.time()-t:.1f}s] Z1={r2.get('obj1')} Z2={r2.get('obj2')} Z3={r2.get('obj3')} feas={r2.get('feasible')}",flush=True)
print(f"=== {a.prob}: base {rep.get('obj1')} -> reassign+bbox {r2.get('obj1')}")
