"""Compare our captured results vs the competitor screenshot table.

Scans results/capture/*/prob_*.json (met.obj), takes per-instance best (min obj
among feasible), and prints win/loss vs notes/competitor-2026-06-11.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "results" / "capture"
comp = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json",
                      encoding="utf-8"))["competitor"]

best = {}   # inst -> (obj, tag, met)
for d in sorted(CAP.iterdir()):
    if not d.is_dir():
        continue
    for f in d.glob("prob_*.json"):
        try:
            m = json.load(open(f, encoding="utf-8")).get("met")
        except Exception:
            continue
        if not m or not m.get("feas"):
            continue
        inst = f.stem
        if inst not in best or m["obj"] < best[inst][0]:
            best[inst] = (m["obj"], d.name, m)

wins = 0
rows = []
for i in range(1, 21):
    inst = f"prob_{i}"
    t = comp[inst]["obj"]
    if inst in best:
        o, tag, m = best[inst]
        win = o < t
        wins += win
        rows.append(f"{inst:9} ours {o:>10.0f} ({tag[:24]:24}) vs {t:>9.0f}"
                    f"  x{o / t:5.2f}  z3 {m.get('z3', -1):>6.0f}/{comp[inst]['z3']:<4}"
                    f"  {'WIN' if win else 'lose'}")
    else:
        rows.append(f"{inst:9} ours    (none)                   vs {t:>9.0f}")
print("\n".join(rows))
print(f"\ncurrent wins (best-ever capture, any tl/config): {wins}/20  "
      f"(need >=15)")
