"""Global reachability: single virtual bay = total floor area, all blocks, choose
each block's MIN-area orientation. cumulative LB on this is the best-case Z1 over
ANY assignment+orientation (a relaxation). LB~0 => some assignment can reach ~0;
LB>>20 => even the best assignment can't (global temporal demand > total floor)."""
import sys, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
sys.stdout.reconfigure(encoding="utf-8")
from ortools.sat.python import cp_model
import myalgorithm as M
name=sys.argv[1]
prob=json.load(open(ROOT/'instances'/'train'/f'{name}.json'))
blocks=prob['blocks']; bays=prob['bays']
total_floor=sum(b['width']*b['height'] for b in bays)
def min_area(b):
    best=1e18
    for sh in b['shape']:
        # bbox of orientation 0 layer footprint
        import math
        xs=[]; ys=[]
        for ly in sh['layers']:
            for poly in (ly if isinstance(ly,list) else [ly]):
                pass
    return None
# simpler: use Block bbox per orientation
from utils import Block
def area_of(bi, oi):
    blk=Block(block_id=bi, block_data=blocks[bi], x=0,y=0,orient_idx=oi)
    r=blk.bounding_rect(); return (r[2]-r[0])*(r[3]-r[1])
for alpha in [1.0,0.95,0.9]:
    cap=int(total_floor*alpha)
    m=cp_model.CpModel()
    H=max(b['due_date'] for b in blocks)+sum(b['processing_time'] for b in blocks)
    ivs=[];dem=[];tard=[]
    for bi,b in enumerate(blocks):
        ar=int(min(area_of(bi,oi) for oi in range(len(b['shape']))))
        R=int(b['release_time']);P=int(b['processing_time']);D=int(b['due_date'])
        e=m.NewIntVar(R,H,f'e{bi}'); x=m.NewIntVar(R,H+P,f'x{bi}')
        ivs.append(m.NewIntervalVar(e,P,x,f'i{bi}')); dem.append(min(ar,cap))
        t=m.NewIntVar(0,H,f't{bi}'); m.Add(t>=e+P-D); tard.append(t)
    m.AddCumulative(ivs,dem,cap); m.Minimize(sum(tard))
    s=cp_model.CpSolver(); s.parameters.max_time_in_seconds=20; s.parameters.num_search_workers=8
    st=s.Solve(m)
    print(f"{name} GLOBAL alpha={alpha} total_floor={total_floor} bestZ1>={int(s.BestObjectiveBound())} found={int(s.ObjectiveValue()) if st in (cp_model.OPTIMAL,cp_model.FEASIBLE) else -1} {s.StatusName(st)}")
