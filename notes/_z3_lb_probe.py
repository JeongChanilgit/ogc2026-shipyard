"""z3 headroom probe (confidence-gate for CP-SAT global bay-reassignment).

For each instance, solve the RELAXED bay-assignment problem:
  minimize  z3 = sum_b (Smax_b - pref_b[j]) for chosen bay j      (preference dev)
  s.t.      each block in exactly one FEASIBLE bay (bbox fits some orientation)
            per-bay workload <= capacity (bay-area-proportional, * (1+slack))
This IGNORES exact 2D packing/time, so it is a LOWER BOUND on achievable z3
(real feasibility is stricter -> real z3 >= this).  Compare to the current
shipped z3 (from results/capture/v7).  If current z3 is already ~= this LB,
reassignment has no headroom; if current z3 >> LB, a global reassignment can
plausibly cut z3 (the CP-SAT build is justified).

Usage: python notes/_z3_lb_probe.py [prob_4,prob_12,...]
"""
import json, sys
from pathlib import Path
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
CAP = ROOT / "results" / "capture" / "v7"


def bbox_fits(shape, bw, bh):
    """True if SOME orientation's footprint bbox fits within (bw, bh)."""
    for ori in shape:
        xs, ys = [], []
        for layer in ori["layers"]:
            for x, y in layer:
                xs.append(x); ys.append(y)
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if (w <= bw + 1e-6 and h <= bh + 1e-6) or (h <= bw + 1e-6 and w <= bh + 1e-6):
            return True
    return False


def solve_lb(prob, slack):
    blocks, bays = prob["blocks"], prob["bays"]
    w3 = prob["weights"]["w3"]
    nB, nJ = len(blocks), len(bays)
    areas = [bj["width"] * bj["height"] for bj in bays]
    tot_area = sum(areas)
    tot_wl = sum(b["workload"] for b in blocks)
    cap = [tot_wl * areas[j] / tot_area * (1.0 + slack) for j in range(nJ)]
    feas = [[bbox_fits(b["shape"], bays[j]["width"], bays[j]["height"])
             for j in range(nJ)] for b in blocks]
    m = cp_model.CpModel()
    x = {(b, j): m.NewBoolVar(f"x{b}_{j}")
         for b in range(nB) for j in range(nJ) if feas[b][j]}
    for b in range(nB):
        vs = [x[b, j] for j in range(nJ) if (b, j) in x]
        if vs:
            m.Add(sum(vs) == 1)
    for j in range(nJ):
        terms = [blocks[b]["workload"] * x[b, j] for b in range(nB) if (b, j) in x]
        if terms:
            m.Add(sum(terms) <= int(cap[j]))
    cost = []
    for (b, j), var in x.items():
        smax = max(blocks[b]["bay_preferences"])
        dev = smax - blocks[b]["bay_preferences"][j]
        if dev:
            cost.append(dev * var)
    m.Minimize(sum(cost))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 10.0
    s.parameters.num_search_workers = 4
    st = s.Solve(m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return int(round(s.ObjectiveValue())), w3, ("OPT" if st == cp_model.OPTIMAL else "feas")
    return None, w3, "INFEAS"


def main():
    insts = (sys.argv[1].split(",") if len(sys.argv) > 1 else
             ["prob_4", "prob_7", "prob_9", "prob_12", "prob_14", "prob_16", "prob_18"])
    print(f"{'inst':9} {'cur z3':>7} {'LB z3(s=.1/.3/.5)':>22} {'w3':>4} "
          f"{'cur w3z3':>9} {'LB headroom (best)':>20}")
    print("-" * 80)
    for i in insts:
        prob = json.load(open(TRAIN / f"{i}.json", encoding="utf-8"))
        cur = json.load(open(CAP / f"{i}.json"))["met"]
        cz3 = cur["z3"]; w3 = prob["weights"]["w3"]
        lbs = []
        for sl in (0.1, 0.3, 0.5):
            z3lb, _, st = solve_lb(prob, sl)
            lbs.append(z3lb if z3lb is not None else None)
        valid = [v for v in lbs if v is not None]
        best_lb = min(valid) if valid else None
        if best_lb is not None:
            head = (cz3 - best_lb) * w3
            hpct = 100.0 * (cz3 - best_lb) / cz3 if cz3 else 0
            print(f"{i:9} {cz3:>7.0f} {str(lbs):>22} {w3:>4} {cz3*w3:>9,.0f} "
                  f"  {head:>9,.0f} ({hpct:.0f}% z3)")
        else:
            print(f"{i:9} {cz3:>7.0f} {'INFEAS at all slack':>22}")


if __name__ == "__main__":
    main()
