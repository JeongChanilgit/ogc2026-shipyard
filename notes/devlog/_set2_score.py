"""Score a capture tag vs competitor (set2 focus). Usage:
    python notes/devlog/_set2_score.py <tag> [<tag2> ...]
Reads results/capture/<tag>/prob_*.json, compares obj/z1 to
notes/competitor-2026-06-15.json. Prints per-instance + set2 total + win count +
feasibility. Multiple tags => best-of per instance (min obj among feasible) for the
combined column, plus each tag's own total.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]
SET2 = [f"prob_{i}" for i in range(21, 41)]


def load(tag):
    d = ROOT / "results" / "capture" / tag
    out = {}
    for inst in SET2:
        f = d / f"{inst}.json"
        if f.exists():
            try:
                out[inst] = json.load(open(f, encoding="utf-8"))["met"]
            except Exception as e:
                out[inst] = {"err": str(e)}
    return out


def main():
    tags = sys.argv[1:]
    if not tags:
        print("usage: _set2_score.py <tag> [tag2 ...]")
        return
    caps = {t: load(t) for t in tags}
    comp_tot = ours_tot = 0.0
    wins = feas = present = 0
    print(f"{'inst':9}{'best_obj':>15}{'comp_obj':>15}{'ratio':>8}"
          f"{'z1':>9}{'comp_z1':>9}  feas  W/L  ({'  '.join(tags)})")
    for inst in SET2:
        c = COMP[inst]["obj"]
        comp_tot += c
        # best across tags among feasible
        best = None
        per = []
        for t in tags:
            m = caps[t].get(inst)
            if m and m.get("feas") and "obj" in m:
                per.append(f"{m['obj']:,.0f}")
                if best is None or m["obj"] < best["obj"]:
                    best = m
            else:
                per.append(str(m.get("err", "MISSING") if m else "MISSING"))
        if best is None:
            print(f"{inst:9}{'INFEASIBLE/MISSING':>15}{c:>15,.0f}"
                  f"  --  ({'  '.join(per)})")
            continue
        present += 1
        feas += 1
        o = best["obj"]
        ours_tot += o
        w = o < c
        wins += w
        print(f"{inst:9}{o:>15,.0f}{c:>15,.0f}{o/c:>7.1f}x"
              f"{best.get('z1', -1):>9,.0f}{COMP[inst]['z1']:>9,.0f}"
              f"   {'Y' if best.get('feas') else 'N'}  {'WIN' if w else 'loss'}"
              f"  ({'  '.join(per)})")
    print("-" * 90)
    print(f"set2 present={present}/20 feasible={feas}  wins={wins}/{present}")
    print(f"set2 TOTAL  ours(best)={ours_tot:>18,.0f}  comp={comp_tot:>18,.0f}"
          f"  ratio={ours_tot/comp_tot:.2f}x  gap={ours_tot-comp_tot:,.0f}")
    if ours_tot < comp_tot:
        print("*** SET2 BEATS COMPETITOR ***")
    # per-tag standalone totals
    for t in tags:
        tt = sum(m["obj"] for m in caps[t].values()
                 if m and m.get("feas") and "obj" in m)
        nf = sum(1 for m in caps[t].values() if m and m.get("feas"))
        print(f"  tag {t}: feasible {nf}/20  total {tt:,.0f}")


if __name__ == "__main__":
    main()
