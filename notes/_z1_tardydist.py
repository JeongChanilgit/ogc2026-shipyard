import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
import myalgorithm as M
prob=json.load(open(ROOT/'instances'/'train'/f'{sys.argv[1]}.json'))
sol=json.load(open(sys.argv[2]))
blocks=prob['blocks']
_,results,flat=M._results_from_solution(prob,sol)
lates=[]
for a in flat:
    b=a['block_id']; late=a['exit_time']-blocks[b]['due_date']
    if late>0: lates.append((late,b,a['bay_id'],a['entry_time'],a['exit_time'],blocks[b]['release_time'],blocks[b]['due_date']))
lates.sort(reverse=True)
tot=sum(l[0] for l in lates)
print(f'total Z1={tot}, n_tardy={len(lates)} of {len(flat)} blocks')
for l in lates[:15]: print(f'  late={l[0]:5d} blk{l[1]:3d} bay{l[2]} entry={l[3]} exit={l[4]} rel={l[5]} due={l[6]} slack(due-rel-P)={l[6]-l[5]-(l[4]-l[3])}')
ls=[l[0] for l in lates]
import statistics
print(f'max={max(ls)} median={statistics.median(ls)} top5={sum(ls[:5])}({100*sum(ls[:5])/tot:.0f}%) top10={sum(ls[:10])}({100*sum(ls[:10])/tot:.0f}%) n_late>50={sum(1 for x in ls if x>50)} n_late>100={sum(1 for x in ls if x>100)}')
