"""Win count of capture tag(s) (min obj per instance) vs the competitor table.
Usage: python notes/_wins_of_tag.py base600_r1 [base600_r2 ...]"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
comp = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json",
                      encoding="utf-8"))["competitor"]
tags = sys.argv[1:] or ["base600_r1"]
wins = 0
for i in range(1, 21):
    inst = f"prob_{i}"
    ms = []
    for t in tags:
        p = ROOT / "results" / "capture" / t / f"{inst}.json"
        if p.exists():
            m = json.load(open(p, encoding="utf-8")).get("met")
            if m and m.get("feas"):
                ms.append(m)
    t_obj = comp[inst]["obj"]
    if not ms:
        print(f"{inst:9} (pending)            vs {t_obj:>9.0f}")
        continue
    o = min(m["obj"] for m in ms)
    z3 = min(m["z3"] for m in ms)
    win = o < t_obj
    wins += win
    print(f"{inst:9} {o:>9.0f} (z3 {z3:>5.0f}) vs {t_obj:>9.0f}  "
          f"x{o / t_obj:5.2f}  {'WIN' if win else 'lose'}")
print(f"\nwins: {wins}/20 (need >=15)  tags={tags}")
