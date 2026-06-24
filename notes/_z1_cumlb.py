"""Per-bay CUMULATIVE area lower bound on Z1 (relaxation: drop 2D placement, keep
only Sum(footprint area of present blocks) <= alpha*floor). CP-SAT minimizes total
tardiness. This LB <= any achievable Z1 for the GIVEN assignment+orientation.
If LB~0 -> demand-flattening placement could reach Z1~0; if LB>>20 -> reassignment
also needed.  Usage: python notes/_z1_cumlb.py <prob> <solution.json> [alpha]
"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
sys.stdout.reconfigure(encoding="utf-8")

def main():
    prob_name, sol_path = sys.argv[1], sys.argv[2]
    alpha = float(sys.argv[3]) if len(sys.argv)>3 else 1.0
    import myalgorithm as M
    from utils import Bay
    from ortools.sat.python import cp_model
    prob = json.loads((ROOT/"instances"/"train"/f"{prob_name}.json").read_text(encoding="utf-8"))
    sol = json.loads(Path(sol_path).read_text(encoding="utf-8"))
    blocks = prob["blocks"]
    assign, results, flat = M._results_from_solution(prob, sol)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    total_lb=0
    for j, by_id in results.items():
        if not by_id: continue
        bay=bays[j]; cap=int(bay.width*bay.height*alpha)
        ids=list(by_id)
        m=cp_model.CpModel()
        H=max(blocks[b]['due_date'] for b in ids)+sum(blocks[b]['processing_time'] for b in ids)
        e={}; ivs=[]; dem=[]; tard=[]
        for b in ids:
            a=by_id[b]
            blk=M.Block(block_id=b, block_data=blocks[b], x=a['x'],y=a['y'],orient_idx=a['orient_idx'])
            r=blk.bounding_rect(); area=int((r[2]-r[0])*(r[3]-r[1]))
            R=int(blocks[b]['release_time']); P=int(blocks[b]['processing_time']); D=int(blocks[b]['due_date'])
            ev=m.NewIntVar(R,H,f"e{b}"); e[b]=ev
            xv=m.NewIntVar(R,H+P,f"x{b}")
            iv=m.NewIntervalVar(ev,P,xv,f"i{b}")
            ivs.append(iv); dem.append(min(area,cap))
            tv=m.NewIntVar(0,H,f"t{b}"); m.Add(tv>=ev+P-D); tard.append(tv)
        m.AddCumulative(ivs,dem,cap)
        m.Minimize(sum(tard))
        s=cp_model.CpSolver(); s.parameters.max_time_in_seconds=25; s.parameters.num_search_workers=4
        st=s.Solve(m)
        lb=int(s.BestObjectiveBound()); best=int(s.ObjectiveValue()) if st in (cp_model.OPTIMAL,cp_model.FEASIBLE) else -1
        total_lb+=lb
        print(f" bay{j}: n={len(ids)} cap={cap} cumLB>={lb} cumBest={best} status={s.StatusName(st)}")
    print(f"=== {prob_name} alpha={alpha}: total cumulative LB(Z1) >= {total_lb}  (if >>20, reassignment needed; if ~0, placement can reach 0)")

if __name__=="__main__":
    main()
