"""Per-instance packing-vs-assignment diagnostic.

For a cached solution, run the polygon-tight SLAB per-bay packer on EACH bay's
currently-assigned blocks and sum the minimum tardiness it can achieve.  This is
the best Z1 reachable WITHOUT changing the bay assignment (pure repacking +
retiming).  Interpretation:
  * slab_best == 0  -> the instance is PACKING-limited; slab packing alone can
    reach Z1=0 under the current assignment.
  * slab_best  > 0  -> ASSIGNMENT-limited; some block must move to another bay
    (the bay is genuinely over-capacity even at polygon density) -> the lever is
    cross-bay reassignment, not better packing.

Run: conda run -n ogc2025 python notes/_slab_bayfeas.py prob_13 [per_bay_budget]
Reuses the single-bay packer from _slab_pack_1bay.py.
"""
import sys
sys.path.insert(0, "tools")
sys.path.insert(0, "notes")
import ogc_analysis as A
from _slab_pack_1bay import pack_bay


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "prob_13"
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
    sol_path = sys.argv[3] if len(sys.argv) > 3 else f"results/_z0_{name}.json"
    prob = A.load_instance(name)
    sol = A.load_solution(sol_path)
    rec = A.assignments(prob, sol)
    n_bays = len(prob["bays"])
    cur_total = slab_total = 0.0
    rows = []
    for j in range(n_bays):
        ids = sorted(b for b, r in rec.items() if r["bay"] == j)
        if not ids:
            continue
        bay = prob["bays"][j]
        W, H = int(bay["width"]), int(bay["height"])
        cur = sum(max(0, rec[b]["exit"] - rec[b]["due"]) for b in ids)
        out = pack_bay(prob, ids, W, H, "slab", budget)
        slab_t = (out[0] if out else None)
        opt = (out[1] if out else False)
        cur_total += cur
        if slab_t is not None:
            slab_total += slab_t
        rows.append((j, len(ids), cur, slab_t, opt))
    print(f"{name}: current_Z1={cur_total:.0f}  slab_best_under_current_assign="
          f"{slab_total:.0f}")
    print(f"  {'bay':>3} {'nblk':>4} {'cur_t':>6} {'slab_t':>7} {'opt':>4}")
    for (j, n, cur, slab_t, opt) in rows:
        print(f"  {j:>3} {n:>4} {cur:>6.0f} {str(slab_t):>7} {str(opt):>4}")
    verdict = ("PACKING-limited (slab alone -> 0 possible)" if slab_total == 0
               else "ASSIGNMENT-limited (some block must change bay)")
    print(f"  verdict: {verdict}")


if __name__ == "__main__":
    main()
