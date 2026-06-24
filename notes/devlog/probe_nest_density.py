"""Single-bay density probe: BL (_ft_search_pos) vs LCA (_ft_search_pos_lca).

Fail-fast gate for the polygon nester (SESSION-HANDOFF 2026-06-14 step 4.5.1).
Takes each instance's CP-SAT bay map (the exact bay sets the augment constructive
targets), packs every non-trivial bay independently at FIXED times with both
placers, and reports per-bay tardiness + blocks-placed-at-release.  Lower bay
tardiness under LCA == denser co-present packing == fewer spills == lower z3.

  conda run -n ogc2025 python notes/devlog/probe_nest_density.py prob_3 prob_5 prob_11 prob_17

Pure measurement: imports only, mutates nothing, writes nothing.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import myalgorithm as M          # noqa: E402
import uconstruct as UC          # noqa: E402
from utils import Bay            # noqa: E402


def _bays_and_u(prob):
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    areas = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(nb)]
    avg = sum(areas) / nb
    return bays, [avg / a for a in areas]


def _pack(prob, bays, j, members, blocks, budget, nest):
    os.environ["OGC_UC_NEST"] = "1" if nest else "0"
    t0 = time.monotonic()
    recs, tard = UC._decode_bay(bays[j], j, members, blocks,
                                time.monotonic() + budget)
    wall = time.monotonic() - t0
    if recs is None:
        return None
    at_R = sum(1 for b, a in recs.items()
               if int(a["entry_time"]) == int(blocks[b]["release_time"]))
    tardy = sum(1 for b, a in recs.items()
                if int(a["exit_time"]) > int(blocks[b]["due_date"]))
    return dict(tard=tard, at_R=at_R, tardy=tardy, n=len(members), wall=wall)


def probe(inst, budget=20.0):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json",
                          encoding="utf-8"))
    blocks = prob["blocks"]
    bays, bay_u = _bays_and_u(prob)
    nb = len(bays)
    try:
        feas = M._feasible_bays(blocks, bays)
    except Exception:
        feas = [list(range(nb)) for _ in blocks]
    feas = [(f if f else list(range(nb))) for f in feas]
    bay_target = M._cpsat_assignment(prob, bays, feas, bay_u,
                                     time_budget=min(15.0, 0.25 * budget * nb))
    if bay_target is None:
        bay_target = [max(range(nb), key=lambda j: blocks[b]["bay_preferences"][j])
                      for b in range(len(blocks))]
    members = {j: [b for b in range(len(blocks)) if bay_target[b] == j]
               for j in range(nb)}

    print(f"\n=== {inst}  (bays={nb}, blocks={len(blocks)}) ===")
    print(f"{'bay':>4}{'n':>5}  | {'BL_tard':>9}{'BL_atR':>7}{'BL_late':>8}{'BL_s':>6}"
          f"  | {'LCA_tard':>9}{'LCA_atR':>7}{'LCA_late':>8}{'LCA_s':>6}"
          f"  | {'dtard':>9}{'datR':>6}")
    tot = dict(bl=0.0, lca=0.0, bl_atR=0, lca_atR=0, bl_late=0, lca_late=0)
    for j in range(nb):
        mem = members[j]
        if len(mem) < 2:
            continue
        bl = _pack(prob, bays, j, mem, blocks, budget, nest=False)
        lca = _pack(prob, bays, j, mem, blocks, budget, nest=True)
        if bl is None or lca is None:
            print(f"{j:>4}{len(mem):>5}  | "
                  f"{'BL fail' if bl is None else 'ok':>9}"
                  f"{'':>21}  | {'LCA fail' if lca is None else 'ok':>9}")
            continue
        tot["bl"] += bl["tard"]; tot["lca"] += lca["tard"]
        tot["bl_atR"] += bl["at_R"]; tot["lca_atR"] += lca["at_R"]
        tot["bl_late"] += bl["tardy"]; tot["lca_late"] += lca["tardy"]
        dtard = lca["tard"] - bl["tard"]
        datR = lca["at_R"] - bl["at_R"]
        mark = "  <<DENSER" if dtard < -1e-6 else ("  ..worse" if dtard > 1e-6 else "")
        print(f"{j:>4}{len(mem):>5}  | "
              f"{bl['tard']:>9.0f}{bl['at_R']:>7}{bl['tardy']:>8}{bl['wall']:>6.1f}"
              f"  | {lca['tard']:>9.0f}{lca['at_R']:>7}{lca['tardy']:>8}{lca['wall']:>6.1f}"
              f"  | {dtard:>+9.0f}{datR:>+6}{mark}")
    print(f"{'TOT':>4}{'':>5}  | {tot['bl']:>9.0f}{tot['bl_atR']:>7}{tot['bl_late']:>8}"
          f"{'':>6}  | {tot['lca']:>9.0f}{tot['lca_atR']:>7}{tot['lca_late']:>8}"
          f"{'':>6}  | {tot['lca']-tot['bl']:>+9.0f}{tot['lca_atR']-tot['bl_atR']:>+6}")
    return tot


if __name__ == "__main__":
    insts = sys.argv[1:] or ["prob_3", "prob_5", "prob_11", "prob_17"]
    budget = float(os.environ.get("PROBE_BUDGET", "20"))
    grand = dict(bl=0.0, lca=0.0)
    for inst in insts:
        t = probe(inst, budget=budget)
        grand["bl"] += t["bl"]; grand["lca"] += t["lca"]
    print("\n" + "=" * 60)
    print(f"GRAND bay-tardiness   BL={grand['bl']:.0f}   "
          f"LCA={grand['lca']:.0f}   delta={grand['lca']-grand['bl']:+.0f}")
    print("(LCA lower bay-tardiness => denser => fewer spills => lower z3)")
