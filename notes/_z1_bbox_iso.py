import sys, json, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
import myalgorithm as M
from utils import check_feasibility, Bay
name=sys.argv[1]; solp=sys.argv[2]
prob=json.load(open(ROOT/'instances'/'train'/f'{name}.json'))
sol=json.load(open(ROOT/solp))
rep=check_feasibility(prob,sol)
print(f"[base] feas={rep.get('feasible')} Z1={rep.get('obj1')} obj={rep.get('objective')}",flush=True)
bays=[Bay.from_dict(d,i) for i,d in enumerate(prob['bays'])]
_,results,_=M._results_from_solution(prob,sol)
t=time.time()
cand=M._bbox_pack_redecode_verified(prob,bays,results,deadline=time.monotonic()+90)
dt=time.time()-t
if cand is None:
    print(f"[bbox_pack {dt:.1f}s] None"); sys.exit()
r2=check_feasibility(prob,cand)
ok=r2.get('feasible') and r2.get('objective') is not None and r2['objective']<rep['objective']-1e-9
print(f"[bbox_pack {dt:.1f}s] feas={r2.get('feasible')} Z1={r2.get('obj1')} Z2={r2.get('obj2')} Z3={r2.get('obj3')} obj={r2.get('objective')} adopt={ok}")
print(f"=== {name}: Z1 {rep.get('obj1')} -> {r2.get('obj1')} feasible={r2.get('feasible')}")
