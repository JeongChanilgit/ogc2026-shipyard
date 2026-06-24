"""Fast full-set evaluation harness for the hypothesis loop.

Runs `myalgorithm.algorithm` on an instance set, reports per-instance
feasible/obj/z1/z2/z3 + totals, and (for set1) wins vs the competitor table.
Saves a JSON baseline and diffs against a saved baseline when given --vs.

  # establish/refresh a baseline
  conda run -n ogc2025 python notes/research/eval.py --set ALL40 --tl 5 --save v0

  # test the current algorithm vs a saved baseline
  conda run -n ogc2025 python notes/research/eval.py --set ALL40 --tl 5 --vs v0

For FAST variants only (runs instances sequentially in-process). Time-budgeted
variants that need parallelism should use notes/_capture20_aff.py instead.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA            # noqa: E402 (poisons path -> re-pin src)
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M              # noqa: E402

BASE = ROOT / "notes" / "research" / "baselines"
TRAIN = ROOT / "instances" / "train"
COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]   # all-40 official (supersedes 06-11)
SETS = {
    "SET1": [f"prob_{i}" for i in range(1, 21)],
    "SET2": [f"prob_{i}" for i in range(21, 41)],
    "ALL40": [f"prob_{i}" for i in range(1, 41)],
}


def run_set(insts, tl):
    out = {}
    for inst in insts:
        prob = json.load(open(TRAIN / f"{inst}.json", encoding="utf-8"))
        t0 = time.monotonic()
        try:
            sol = M.algorithm(prob, tl)
            feas, obj, z1, z2, z3 = OA.obj_tuple(prob, sol)
        except Exception as e:
            out[inst] = {"feas": False, "obj": None, "err": f"{type(e).__name__}: {e}",
                         "wall": round(time.monotonic() - t0, 2)}
            continue
        out[inst] = {"feas": bool(feas), "obj": obj, "z1": z1, "z2": z2, "z3": z3,
                     "wall": round(time.monotonic() - t0, 2)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="ALL40", choices=list(SETS))
    ap.add_argument("--tl", type=float, default=5.0)
    ap.add_argument("--save", default=None, help="save result as baselines/<name>.json")
    ap.add_argument("--vs", default=None, help="diff against baselines/<name>.json")
    a = ap.parse_args()
    insts = SETS[a.set]
    res = run_set(insts, a.tl)

    base = None
    if a.vs:
        p = BASE / f"{a.vs}.json"
        if p.exists():
            base = json.load(open(p))

    infeas = [i for i in insts if not res[i]["feas"]]
    tot = sum(res[i]["obj"] for i in insts if res[i]["feas"] and res[i]["obj"] is not None)
    wins = improved = regressed = 0
    print(f"{'inst':<9}{'feas':>6}{'obj':>15}{'z1':>9}{'z3':>7}{'wall':>6}"
          + (f"{'Δvs':>15}" if base else "")
          + ("  comp/win" if True else ""))
    for inst in insts:
        r = res[inst]
        comp = COMP.get(inst, {}).get("obj")
        win = (r["feas"] and r["obj"] is not None and comp is not None and r["obj"] < comp)
        wins += 1 if win else 0
        d = ""
        if base and inst in base and base[inst].get("obj") is not None and r.get("obj") is not None:
            delta = r["obj"] - base[inst]["obj"]
            if delta < -1e-6: improved += 1
            elif delta > 1e-6: regressed += 1
            d = f"{delta:>+15.0f}"
        cw = ""
        if comp is not None:
            cw = f"  {('WIN' if win else 'loss')}"
        objs = f"{r['obj']:.0f}" if r.get("obj") is not None else "INFEAS"
        z1s = f"{r['z1']:.0f}" if r.get("z1") is not None else "-"
        z3s = f"{r['z3']:.0f}" if r.get("z3") is not None else "-"
        print(f"{inst:<9}{str(r['feas']):>6}{objs:>15}{z1s:>9}{z3s:>7}{r['wall']:>6.1f}{d}{cw}")
    print("-" * 70)
    print(f"feasible={len(insts)-len(infeas)}/{len(insts)}  infeasible={infeas or 'none'}")
    print(f"total_obj={tot:.0f}  wins_vs_competitor(set1 only)={wins}")
    if base:
        print(f"vs {a.vs}: improved={improved} regressed={regressed}")

    if a.save:
        BASE.mkdir(parents=True, exist_ok=True)
        json.dump(res, open(BASE / f"{a.save}.json", "w"), indent=0)
        print(f"[saved] baselines/{a.save}.json")


if __name__ == "__main__":
    main()
