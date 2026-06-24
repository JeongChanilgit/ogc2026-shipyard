"""General scorer vs competitor. Usage:
    python notes/devlog/_score.py <set1|set2|all40> <tag> [tag2 ...]
Best-of across tags per instance (min obj among feasible). Prints per-instance,
group total, win count vs competitor (competitor-2026-06-15.json, obj_official).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]
GROUPS = {"set1": range(1, 21), "set2": range(21, 41), "all40": range(1, 41)}


def load(tag):
    d = ROOT / "results" / "capture" / tag
    out = {}
    for f in d.glob("prob_*.json"):
        try:
            out[f.stem] = json.load(open(f, encoding="utf-8"))["met"]
        except Exception:
            pass
    return out


def main():
    grp = sys.argv[1]
    tags = sys.argv[2:]
    rng = GROUPS[grp]
    caps = {t: load(t) for t in tags}
    comp_tot = ours_tot = 0.0
    wins = feas = present = 0
    miss = []
    for i in rng:
        inst = f"prob_{i}"
        c = COMP[inst]["obj"]
        comp_tot += c
        best = None
        for t in tags:
            m = caps[t].get(inst)
            if m and m.get("feas") and "obj" in m:
                if best is None or m["obj"] < best["obj"]:
                    best = m
        if best is None:
            miss.append(inst)
            continue
        present += 1
        feas += 1
        ours_tot += best["obj"]
        w = best["obj"] < c
        wins += w
        flag = "WIN " if w else "loss"
        over = " OVER" if best.get("wall", 0) > 121 else ""
        print(f"{inst:8} {best['obj']:>15,.0f} vs {c:>15,.0f}  {best['obj']/c:>5.2f}x"
              f"  z1={best.get('z1', -1):>8,.0f}/{COMP[inst]['z1']:<7.0f} {flag}"
              f"  w{best.get('wall', 0):.0f}{over}")
    print("-" * 84)
    print(f"{grp}: present={present}/{len(list(rng))} feasible={feas} wins={wins}/{present}"
          f"  MISSING={miss}")
    print(f"{grp} TOTAL ours={ours_tot:>16,.0f}  comp={comp_tot:>16,.0f}"
          f"  ratio={ours_tot/max(1,comp_tot):.3f}x  gap={ours_tot-comp_tot:+,.0f}")
    if ours_tot < comp_tot:
        print(f"*** {grp} BEATS COMPETITOR ***")


if __name__ == "__main__":
    main()
