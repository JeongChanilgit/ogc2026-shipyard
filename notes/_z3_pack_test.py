"""Decode the z3-OPTIMAL assignment through the REAL packer to test whether the
z3 headroom (LB probe) is ACHIEVABLE or PACKING-BLOCKED.

For each instance: build the z3-min bay assignment (pref_seed = each block to its
most-preferred feasible bay -> z3~=0, and a workload-balanced z3-min via CP-SAT),
decode each via _decode_assignment (the real crane-safe packer), and report the
resulting z1/z2/z3/obj.  If z1 explodes / obj >> floor, the z3-optimal assignment
does NOT pack -> the LB headroom is packing-blocked (the gate rightly rejects it).

Usage: python notes/_z3_pack_test.py [prob_4,prob_12,...]
"""
import json, sys
from pathlib import Path
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import myalgorithm as M
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
CAP = ROOT / "results" / "capture" / "v7"


def z3min_assign(prob, feasible_bays, slack):
    blocks, bays = prob["blocks"], prob["bays"]
    nB, nJ = len(blocks), len(bays)
    areas = [bj["width"] * bj["height"] for bj in bays]
    tot_area, tot_wl = sum(areas), sum(b["workload"] for b in blocks)
    cap = [tot_wl * areas[j] / tot_area * (1 + slack) for j in range(nJ)]
    m = cp_model.CpModel()
    x = {(b, j): m.NewBoolVar(f"x{b}_{j}")
         for b in range(nB) for j in feasible_bays[b]}
    for b in range(nB):
        vs = [x[b, j] for j in feasible_bays[b]]
        if vs:
            m.Add(sum(vs) == 1)
    for j in range(nJ):
        terms = [blocks[b]["workload"] * x[b, j] for b in range(nB) if (b, j) in x]
        if terms:
            m.Add(sum(terms) <= int(cap[j]))
    cost = []
    for (b, j), var in x.items():
        dev = max(blocks[b]["bay_preferences"]) - blocks[b]["bay_preferences"][j]
        if dev:
            cost.append(dev * var)
    m.Minimize(sum(cost))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 10.0
    s.parameters.num_search_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    a = [0] * nB
    for b in range(nB):
        for j in feasible_bays[b]:
            if s.Value(x[b, j]):
                a[b] = j; break
    return a


def decode_report(prob, assign):
    bays = M._bays_from_prob(prob) if hasattr(M, "_bays_from_prob") else None
    blocks_data = prob["blocks"]
    # Build Bay objects the same way the algorithm does.
    bays_obj = [M.Bay(b["width"], b["height"]) for b in prob["bays"]]
    n_bays = len(bays_obj)
    bay_areas = [b["width"] * b["height"] for b in prob["bays"]]
    avg_area = sum(bay_areas) / len(bay_areas)
    bay_u = [avg_area / a for a in bay_areas]
    alt = 40 if len(blocks_data) <= 200 else 0
    dec = M._Decoder(bays_obj, blocks_data, alt)
    results, tard = M._decode_assignment(dec, assign, n_bays, deadline=None)
    if results is None:
        return None
    obj, z1, z2, z3 = M._obj_of_results(prob, results, bay_u)
    return obj, z1, z2, z3


def main():
    insts = (sys.argv[1].split(",") if len(sys.argv) > 1 else
             ["prob_4", "prob_12", "prob_14", "prob_18"])
    for i in insts:
        prob = json.load(open(TRAIN / f"{i}.json", encoding="utf-8"))
        cur = json.load(open(CAP / f"{i}.json"))["met"]
        fb = M._feasible_bays(prob["blocks"], [M.Bay(b["width"], b["height"]) for b in prob["bays"]])
        # pref seed: most preferred feasible bay (z3 ~ 0)
        pref = [max(fb[b], key=lambda j: prob["blocks"][b]["bay_preferences"][j]) if fb[b] else 0
                for b in range(len(prob["blocks"]))]
        print(f"=== {i} === floor(v7): z1={cur['z1']:.0f} z2={cur['z2']:.0f} "
              f"z3={cur['z3']:.0f} obj={cur['obj']:,.0f}")
        for name, a in [("pref(z3~0)", pref),
                        ("cpsat_s0.1", z3min_assign(prob, fb, 0.1)),
                        ("cpsat_s0.3", z3min_assign(prob, fb, 0.3))]:
            if a is None:
                print(f"    {name:12} : assign INFEASIBLE"); continue
            r = decode_report(prob, a)
            if r is None:
                print(f"    {name:12} : DECODE INFEASIBLE (does not pack)"); continue
            obj, z1, z2, z3 = r
            tag = "  <-- packs WORSE" if obj > cur["obj"] + 1 else "  <-- packs BETTER"
            print(f"    {name:12} : z1={z1:>5.0f} z2={z2:>5.0f} z3={z3:>5.0f} "
                  f"obj={obj:>10,.0f}{tag}")


if __name__ == "__main__":
    main()
