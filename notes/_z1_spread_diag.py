"""Spatial-reuse diagnostic. Given a saved solution, per bay measure how much
tardiness comes from FLOOR-SPOT REUSE (a block waits for a prior occupant of an
overlapping footprint to clear) vs unavoidable peak concurrency. Run AFTER a
solution is saved. Usage:
  python notes/_z1_spread_diag.py <prob> <solution.json>
"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
sys.stdout.reconfigure(encoding="utf-8")

def main():
    prob_name, sol_path = sys.argv[1], sys.argv[2]
    import myalgorithm as M
    from utils import Bay, check_feasibility
    prob = json.loads((ROOT/"instances"/"train"/f"{prob_name}.json").read_text(encoding="utf-8"))
    sol = json.loads(Path(sol_path).read_text(encoding="utf-8"))
    blocks = prob["blocks"]
    assign, results, flat = M._results_from_solution(prob, sol)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    print(f"{prob_name}: bays={len(bays)}")
    for j, by_id in results.items():
        if not by_id: continue
        ids = list(by_id)
        bay = bays[j]
        # peak simultaneous footprint area vs bay area (concurrency pressure)
        events = []
        for b,a in by_id.items():
            events.append((int(a['entry_time']), +1, b))
            events.append((int(a['exit_time']), -1, b))
        events.sort()
        cur=set(); peak=0; peak_area=0
        import collections
        bay_area = bay.width*bay.height
        # block footprint area
        def area(b,a):
            blk=M.Block(block_id=b, block_data=blocks[b], x=a['x'],y=a['y'],orient_idx=a['orient_idx'])
            r=blk.bounding_rect(); return (r[2]-r[0])*(r[3]-r[1])
        for t,d,b in events:
            if d>0: cur.add(b)
            else: cur.discard(b)
            if len(cur)>peak:
                peak=len(cur); peak_area=sum(area(bb,by_id[bb]) for bb in cur)
        tard=sum(max(0,int(a['exit_time'])-blocks[b]['due_date']) for b,a in by_id.items())
        lb=M._bay_tardiness_lb(ids,blocks)
        print(f" bay{j}: n={len(ids)} W*H={bay.width}x{bay.height}={bay_area} peakConc={peak} peakFootArea={peak_area} ({100*peak_area/bay_area:.0f}% of floor) tard={tard} LB={lb}")
    rep=check_feasibility(prob,sol)
    print(f"TOTAL Z1={rep.get('obj1')} feasible={rep.get('feasible')}")

if __name__=="__main__":
    main()
