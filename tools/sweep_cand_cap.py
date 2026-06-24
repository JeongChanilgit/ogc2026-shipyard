#!/usr/bin/env python3
"""sweep_cand_cap.py -- measure OGC_CAND_CAP on prob_6 clean per-bay decode.

For each K in the sweep set, time the clean per-bay decode (OGC_CRANE_SAFE=1,
OGC_CRANE_COEXIT=1, OGC_ATCR_SEED=1), assemble + tie-separate, run the OFFICIAL
check_feasibility, and report wall(s) | feasible | Z1 | objective.

Reuses validate_clean_decode.py's decode/assemble/repair/feasibility helpers so
the measurement path is identical to the validated clean-decode tool -- only the
OGC_CAND_CAP env knob varies between runs.

To keep total runtime sane the K=0 (unlimited) baseline is run on bay 0 + bay 2
only (the two big bays) and extrapolated for WALL TIME, while every K>0 (fast)
is run on the FULL instance to get official feasibility + Z1.  Pass --full-unlim
to also time K=0 on all bays (slow, ~292s).
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("OGC_ATCR_SEED", "1")
os.environ.setdefault("OGC_CRANE_SAFE", "1")
os.environ.setdefault("OGC_CRANE_COEXIT", "1")  # the validated-feasible alignment


def run_one(K, only_bays=None):
    """Run a clean decode for OGC_CAND_CAP=K. Returns dict of metrics.

    only_bays: if given, decode only those bay indices (for fast wall-time
    timing of the slow unlimited case) -- feasibility/Z1 are then partial and
    flagged as such.
    """
    os.environ["OGC_CAND_CAP"] = str(K)
    # fresh import each run so the module-level _CAND_CAP picks up the new env
    for m in ("myalgorithm", "baseline_greedy", "utils"):
        sys.modules.pop(m, None)
    from utils import Bay, check_feasibility
    import validate_clean_decode as V
    # re-bind V's globals to the freshly-imported myalgorithm
    import myalgorithm
    V._decode_bay = myalgorithm._decode_bay
    V._orderings = myalgorithm._orderings
    V._bay_tardiness = myalgorithm._bay_tardiness

    prob_info = json.loads(V.INST_PATH.read_text())
    base_sol = json.loads(V.SOL_PATH.read_text())
    blocks_data = prob_info["blocks"]
    bays = [Bay.from_dict(d, j) for j, d in enumerate(prob_info["bays"])]

    rec = V.load_solution_blocks(base_sol)
    by_bay = {}
    for bid, r in rec.items():
        if "bay" not in r:
            continue
        by_bay.setdefault(r["bay"], []).append(bid)

    target_bays = sorted(by_bay) if only_bays is None else only_bays
    t0 = time.monotonic()
    per_bay = []
    per_bay_wall = {}
    z1_clean = 0       # sum of per-bay _bay_tardiness from the (uncapped/capped) decode
    n_forced = 0
    failed = False
    for bidx in target_bays:
        ids = by_bay[bidx]
        bt0 = time.monotonic()
        res, tard, label, nf = V.clean_decode_bay(bays[bidx], bidx, ids, blocks_data)
        per_bay_wall[bidx] = time.monotonic() - bt0
        if res is None:
            failed = True
            break
        per_bay.append(res)
        z1_clean += tard
        n_forced += nf
    wall = time.monotonic() - t0

    out = {"K": K, "wall": wall, "per_bay_wall": per_bay_wall,
           "bays": target_bays, "n_bays_total": len(by_bay),
           "z1_clean": z1_clean, "n_forced": n_forced,
           "partial": only_bays is not None}
    if failed:
        out.update(feasible=None, z1=None, objective=None, note="DECODE FAILED")
        return out
    if only_bays is not None:
        out.update(feasible=None, z1=None, objective=None,
                   note="partial bays -- wall+z1_clean only")
        return out

    placements = V.results_to_placements(per_bay)
    rep, _stats = V.separate_tied_exits(placements, blocks_data)
    rep_sol = V.assemble_from_placements(rep)
    rr = check_feasibility(prob_info, rep_sol)
    out.update(feasible=bool(rr["feasible"]),
               z1=rr.get("obj1"), objective=rr.get("objective"),
               stage=rr.get("stage"),
               viol=(rr["violations"][:2] if not rr["feasible"] else None),
               z1_local=V.z1_of(rep, blocks_data))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", default="0,300,150,80,40")
    ap.add_argument("--full-unlim", action="store_true",
                    help="time K=0 on ALL bays (slow ~292s) instead of bays 0+2")
    args = ap.parse_args()
    ks = [int(x) for x in args.ks.split(",")]

    rows = []
    for K in ks:
        if K == 0 and not args.full_unlim:
            # time the two big bays only, extrapolate is informational
            r = run_one(0, only_bays=[0, 2])
        else:
            r = run_one(K)
        rows.append(r)
        pbw = "  ".join(f"b{b}={r['per_bay_wall'].get(b, 0):.1f}s"
                        for b in r["bays"])
        print(f"K={K:>5} wall={r['wall']:7.1f}s feasible={r['feasible']} "
              f"Z1clean={r.get('z1_clean')} forced={r.get('n_forced')} "
              f"obj={r['objective']} stage={r.get('stage')} "
              f"[{pbw}] {r.get('note','')}", flush=True)
        if r.get("viol"):
            for v in r["viol"]:
                print("        viol:", v, flush=True)

    print("\n" + "=" * 78)
    print(f"{'K':>6} | {'wall(s)':>8} | {'Z1clean':>8} | {'forced':>6} | "
          f"{'feasible':>9} | {'objective':>12}")
    print("-" * 78)
    for r in rows:
        K = "unlim" if r["K"] == 0 else r["K"]
        feas = r["feasible"] if r["feasible"] is not None else "(part)"
        z1c = r.get("z1_clean")
        z1c = f"{z1c:.0f}" if z1c is not None else "-"
        obj = f"{r['objective']:.0f}" if r["objective"] is not None else "-"
        print(f"{str(K):>6} | {r['wall']:>8.1f} | {z1c:>8} | "
              f"{str(r.get('n_forced')):>6} | {str(feas):>9} | {obj:>12}")
    print("=" * 78)


if __name__ == "__main__":
    main()
