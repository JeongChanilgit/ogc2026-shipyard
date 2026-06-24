import sys, json, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
import myalgorithm as M
from utils import Bay
name=sys.argv[1]; solp=sys.argv[2]
prob=json.load(open(ROOT/'instances'/'train'/f'{name}.json'))
sol=json.load(open(ROOT/solp))
bays=[Bay.from_dict(d,i) for i,d in enumerate(prob['bays'])]
_,results,_=M._results_from_solution(prob,sol)
blocks=prob['blocks']
for j,by in results.items():
    if not by: continue
    ids=list(by)
    n=len(ids)
    ct=sum(max(0,int(by[b]['exit_time'])-blocks[b]['due_date']) for b in ids)
    warm={b:by[b] for b in ids}
    t=time.time()
    res=M._bbox_pack_bay(prob,bays[j],j,ids,12.0,warm=warm)
    dt=time.time()-t
    nt=sum(max(0,res[b]['exit_time']-blocks[b]['due_date']) for b in ids) if res else -1
    print(f"bay{j}: n={n} WxH={bays[j].width}x{bays[j].height} cur_tard={ct} -> bbox_tard={nt}  time={dt:.2f}s {'(None)' if res is None else ''}")
