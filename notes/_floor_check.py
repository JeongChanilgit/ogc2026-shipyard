"""Verify the BREAKTHROUGH: does the FULL greedy floor (pos_k default) nearly solve
prob_20 (z1~1)? Compare repair modes + pos_k, with OFFICIAL feasibility/objective.
Usage: python notes/_floor_check.py prob_20
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from baseline_greedy import greedyalgorithm
import ogc_analysis as A
from baseline_greedy import set_pos_k_override

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

if __name__ == "__main__":
    name = sys.argv[1]
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    configs = [
        ("full greedy + simple repair", None, "simple"),
        ("full greedy + auto repair",   None, "auto"),
        ("BL-only(pos_k=1) + simple",    1,    "simple"),
        ("BL-only(pos_k=1) + auto",      1,    "auto"),
    ]
    for label, posk, repair in configs:
        if posk is not None:
            set_pos_k_override(posk)
        else:
            set_pos_k_override(0)
        t0 = time.monotonic()
        try:
            sol = greedyalgorithm(prob, 200.0, repair_mode=repair)
            dt = time.monotonic() - t0
            feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
            print(f"[{label}] z1={o1} obj={obj:.0f} feas={bool(feas)} wall={dt:.1f}s", flush=True)
        except Exception as e:
            print(f"[{label}] ERROR {e}", flush=True)
        finally:
            set_pos_k_override(0)
