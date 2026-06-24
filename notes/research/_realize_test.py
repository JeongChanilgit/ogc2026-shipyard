"""Can feasspill's LOW-z3 assignment (prob_13: z3=152, z1=10) be realized at z1<10
by a STRONGER realize than boxsolver's? Closing z1 10->0 on that assignment gives
obj ~43K (beats competitor 71.8K). Tries legacy's fastfloor decode per bay on the
feasspill assignment. Saves the assignment for reuse (feasspill is ~387s).

  FS_TL=420 python notes/research/_realize_test.py prob_13
  REUSE=1 python notes/research/_realize_test.py prob_13   # skip feasspill, load saved
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA                      # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as BS                         # noqa: E402
import fastfloor as FF                         # noqa: E402
from utils import Bay, check_feasibility       # noqa: E402


def members_from_sol(sol, n, nb):
    mem = [[] for _ in range(nb)]
    for t, ops in sol.get("operations", {}).items():
        for o in ops:
            if o.get("type") == "ENTRY":
                mem[int(o["bay_id"])].append(int(o["block_id"]))
    return mem


def realize_legacy(members, blocks, bays, per_bay_s):
    """Realize a fixed assignment with legacy fastfloor decode (best-of F0-F3) per bay.
    Returns (sol, total_tard) or (None, inf)."""
    import math
    ops = {}
    tot = 0.0
    attempts = [("fixed", "F0"), ("fixed", "F1"), ("fixed", "F2"), ("fixed", "F3")]
    for j, ids in enumerate(members):
        if not ids:
            continue
        dl = time.monotonic() + per_bay_s
        best, ft = FF._decode_attempts(bays[j], j, list(ids), attempts, blocks, dl)
        if best is None or len(best) != len(ids):
            return None, math.inf
        for b, rec in best.items():
            e = int(rec["entry_time"]); x = int(rec["exit_time"])
            ops.setdefault(x, []).append({"type": "EXIT", "block_id": int(b), "bay_id": j})
            ops.setdefault(e, []).append({"type": "ENTRY", "block_id": int(b), "bay_id": j,
                                          "x": int(rec["x"]), "y": int(rec["y"]),
                                          "orient_idx": int(rec["orient_idx"])})
            tot += max(0, x - int(blocks[b]["due_date"]))
    operations = {str(int(t)): [o for o in ops[t] if o["type"] == "EXIT"]
                  + [o for o in ops[t] if o["type"] == "ENTRY"] for t in sorted(ops)}
    return {"operations": operations}, tot


def main():
    TL = float(os.environ.get("FS_TL", "420"))
    reuse = os.environ.get("REUSE", "0") not in ("0", "", "no")
    name = (sys.argv[1:] or ["prob_13"])[0]
    prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
    blocks = prob["blocks"]; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    memfile = ROOT / "notes" / "research" / f"_fs_members_{name}.json"

    if reuse and memfile.exists():
        members = json.load(open(memfile))
        print(f"[reuse] loaded feasspill assignment for {name}", flush=True)
    else:
        BS._FP_CACHE.clear()
        t0 = time.monotonic()
        r = BS._solve_feasspill(prob, blocks, bays, t0 + TL)
        if r is None:
            print("feasspill failed"); return
        obj, sol = r
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
        print(f"feasspill: obj={o:.0f} z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} "
              f"wall={time.monotonic()-t0:.1f}", flush=True)
        members = members_from_sol(sol, n, nb)
        json.dump(members, open(memfile, "w"))
        print(f"[saved] {memfile.name}", flush=True)

    # realize the SAME assignment with legacy fastfloor decode
    FF._FP_CACHE.clear() if hasattr(FF, "_FP_CACHE") else None
    t0 = time.monotonic()
    sol2, tard = realize_legacy(members, blocks, bays, per_bay_s=12.0)
    if sol2 is None:
        print(f"legacy-realize: FAILED  wall={time.monotonic()-t0:.1f}", flush=True)
        return
    chk = check_feasibility(prob, sol2)
    if not chk.get("feasible"):
        print(f"legacy-realize: INFEASIBLE stage={chk.get('stage')} "
              f"{(chk.get('violations') or ['?'])[:1]}  wall={time.monotonic()-t0:.1f}", flush=True)
        return
    feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol2)
    print(f"legacy-realize (same assign): obj={o:.0f} z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} "
          f"wall={time.monotonic()-t0:.1f}", flush=True)
    print("  target: z1<=3 beats legacy(113500); z1=0 -> ~43K beats comp(71823)", flush=True)


if __name__ == "__main__":
    main()
