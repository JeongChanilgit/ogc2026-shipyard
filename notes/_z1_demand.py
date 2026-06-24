"""Per-bay DEMAND-peak: if every block entered at its release_time and stayed for
processing_time, what is the peak simultaneous footprint AREA vs the bay floor?
area<=floor => Z1~0 may be reachable by placement; area>floor => waiting forced.
Usage: python notes/_z1_demand.py <prob> <solution.json>
"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"src"))
sys.stdout.reconfigure(encoding="utf-8")

def main():
    prob_name, sol_path = sys.argv[1], sys.argv[2]
    import myalgorithm as M
    from utils import Bay
    prob = json.loads((ROOT/"instances"/"train"/f"{prob_name}.json").read_text(encoding="utf-8"))
    sol = json.loads(Path(sol_path).read_text(encoding="utf-8"))
    blocks = prob["blocks"]
    assign, results, flat = M._results_from_solution(prob, sol)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    print(f"{prob_name}: DEMAND peak (all blocks enter at release)")
    worst=0
    for j, by_id in results.items():
        if not by_id: continue
        bay=bays[j]; bay_area=bay.width*bay.height
        evs=[]
        for b,a in by_id.items():
            blk=M.Block(block_id=b, block_data=blocks[b], x=a['x'],y=a['y'],orient_idx=a['orient_idx'])
            r=blk.bounding_rect(); ar=(r[2]-r[0])*(r[3]-r[1])
            R=blocks[b]['release_time']; P=blocks[b]['processing_time']
            evs.append((R,+ar)); evs.append((R+P,-ar))
        evs.sort()
        cur=0.0; peak=0.0
        for t,da in evs:
            cur+=da
            if cur>peak: peak=cur
        pct=100*peak/bay_area
        worst=max(worst,pct)
        flag="OVER" if pct>100 else "ok"
        print(f" bay{j}: floor={bay_area:.0f} demandPeakArea={peak:.0f} ({pct:.0f}% of floor) {flag}")
    print(f" => worst bay demand = {worst:.0f}% of floor  ({'serialization FORCED' if worst>100 else 'Z1~0 area-feasible'})")

if __name__=="__main__":
    main()
