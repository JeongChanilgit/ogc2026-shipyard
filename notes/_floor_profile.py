"""Profile WHERE the greedy floor's time goes (for Part 2: can we make it <=10s?).
Wraps check_entry/check_exit/check_collisions (crane geometry) to measure their
share, and reports total floor wall + crane-check time + count.
Usage: python notes/_floor_profile.py prob_20 [pos_k]
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import utils as U
import baseline_greedy as BG
from baseline_greedy import greedyalgorithm, set_pos_k_override
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

STAT = {"ce": 0.0, "ce_n": 0, "cx": 0.0, "cx_n": 0, "cc": 0.0, "cc_n": 0}

def _wrap(name, key):
    orig = getattr(U, name)
    def w(*a, **k):
        t0 = time.perf_counter(); r = orig(*a, **k)
        STAT[key] += time.perf_counter() - t0; STAT[key + "_n"] += 1
        return r
    setattr(U, name, w)
    # baseline_greedy imported these by name -> patch its references too
    if hasattr(BG, name):
        setattr(BG, name, w)

_wrap("check_entry", "ce"); _wrap("check_exit", "cx"); _wrap("check_collisions", "cc")

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "prob_20"
    posk = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    set_pos_k_override(posk)
    t0 = time.monotonic()
    sol = greedyalgorithm(prob, 200.0, repair_mode="auto")
    dt = time.monotonic() - t0
    set_pos_k_override(0)
    z1 = A.obj_tuple(prob, sol)[2]
    crane = STAT["ce"] + STAT["cx"] + STAT["cc"]
    cn = STAT["ce_n"] + STAT["cx_n"] + STAT["cc_n"]
    print(f"\n=== floor profile {name} pos_k={posk} ===", flush=True)
    print(f"floor wall={dt:.1f}s  z1={z1:.0f}", flush=True)
    print(f"crane checks total={crane:.1f}s ({100*crane/dt:.0f}% of floor) over {cn} calls", flush=True)
    print(f"  check_entry {STAT['ce']:.1f}s/{STAT['ce_n']}  check_exit {STAT['cx']:.1f}s/{STAT['cx_n']}  check_collisions {STAT['cc']:.1f}s/{STAT['cc_n']}", flush=True)
    print(f"other (placement/loop)={dt-crane:.1f}s", flush=True)
