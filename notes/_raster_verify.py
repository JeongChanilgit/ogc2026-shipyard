"""Verify the POLYGON-RASTER fast floor (OGC_FLOOR_RASTER): polygon-precise,
conservative cell-set crane/collision prefilter -> fast floor + dense structure.
For prob_6, prob_14, prob_20: builds the raster floor, ASSERTS official
check_feasibility passes, reports floor wall + floor z1, then runs ONE 90s
postprocess and reports final z1.  Compares to anti-stack (prob_20: 161) and
crane-aware (prob_20: 19).
Usage: python notes/_raster_verify.py
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
os.environ["OGC_PP_ROUND_S"] = "0"
os.environ["OGC_BR_CACHE"] = "1"
import myalgorithm as M
try:
    M._install_bounding_rect_cache()
except Exception as e:
    print("BR cache install failed:", e)
from baseline_greedy import greedyalgorithm, set_pos_k_override
from utils import Bay, check_feasibility
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")
PROBS = ["prob_6", "prob_14", "prob_20"]


def z1of(prob, sol):
    return A.obj_tuple(prob, sol)[2]


def run_one(name):
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    n_bays = len(prob["bays"])
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    ba = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(n_bays)]
    avg = sum(ba) / n_bays
    bay_u = [avg / a for a in ba]
    feasible_bays = M._feasible_bays(prob["blocks"], bays)

    os.environ["OGC_FLOOR_RASTER"] = "1"
    set_pos_k_override(2)
    t0 = time.monotonic()
    floor = greedyalgorithm(prob, 200.0, repair_mode="auto")
    floor_wall = time.monotonic() - t0
    set_pos_k_override(0)
    os.environ["OGC_FLOOR_RASTER"] = "0"

    feas = check_feasibility(prob, floor)
    feasible = bool(feas.get("feasible"))
    fz1 = z1of(prob, floor)

    final_z1 = None
    pp_wall = None
    if feasible:
        t0 = time.monotonic()
        out = M._postprocess_verified_solution(
            prob, floor, feas, bays, feasible_bays, bay_u,
            deadline=time.monotonic() + 90)
        pp_wall = time.monotonic() - t0
        fin = out[0] if out else floor
        final_z1 = z1of(prob, fin)
    return {
        "name": name, "feasible": feasible, "floor_wall": floor_wall,
        "floor_z1": fz1, "final_z1": final_z1, "pp_wall": pp_wall,
        "stage": feas.get("stage"),
    }


if __name__ == "__main__":
    rows = []
    for name in PROBS:
        print(f"=== RASTER floor: {name} ===", flush=True)
        r = run_one(name)
        rows.append(r)
        fz = f"{r['floor_z1']:.0f}" if r['floor_z1'] is not None else "?"
        fin = f"{r['final_z1']:.0f}" if r['final_z1'] is not None else "n/a"
        ppw = f"{r['pp_wall']:.0f}s" if r['pp_wall'] is not None else "-"
        print(f"  feasible={r['feasible']} (stage={r['stage']})  "
              f"floor_wall={r['floor_wall']:.1f}s  floor_z1={fz}  "
              f"-> 90s pp z1={fin}  pp_wall={ppw}", flush=True)
        assert r["feasible"], f"FEASIBILITY FAILED for {name} (stage {r['stage']})"

    print("\n=== SUMMARY TABLE (OGC_FLOOR_RASTER) ===")
    print(f"{'instance':<10} {'feasible':<9} {'floor_wall':<11} {'floor_z1':<9} {'z1_after_90s_pp':<16}")
    for r in rows:
        fz = f"{r['floor_z1']:.0f}" if r['floor_z1'] is not None else "?"
        fin = f"{r['final_z1']:.0f}" if r['final_z1'] is not None else "n/a"
        print(f"{r['name']:<10} {str(r['feasible']):<9} "
              f"{r['floor_wall']:.1f}s{'':<6} {fz:<9} {fin:<16}")
    print("\nReference (prob_20): anti-stack floor 2.6s/z1 449 -> 90s -> 161 ; "
          "crane-aware floor 42s -> 90s -> 19")
