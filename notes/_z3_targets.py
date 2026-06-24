"""Per-instance: weights (w1,w2,w3), preference stats, and the z3 we must hit
to beat the competitor (holding our current best z1/z2)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
comp = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json",
                      encoding="utf-8"))["competitor"]
CAP = ROOT / "results" / "capture"

# locate instance files
inst_dir = None
for cand in (ROOT / "instances", ROOT / "instances" / "prob"):
    if cand.exists():
        hits = list(cand.rglob("prob_1.json"))
        if hits:
            inst_dir = hits[0].parent
            break
print("instance dir:", inst_dir)

best = {}
for d in CAP.iterdir():
    if not d.is_dir():
        continue
    for f in d.glob("prob_*.json"):
        try:
            m = json.load(open(f, encoding="utf-8")).get("met")
        except Exception:
            continue
        if not m or not m.get("feas"):
            continue
        if f.stem not in best or m["obj"] < best[f.stem][0]:
            best[f.stem] = (m["obj"], m)

print(f"{'inst':9} {'w1':>5} {'w2':>5} {'w3':>6} {'#blk':>5} "
      f"{'ourz2':>6} {'ourz3':>6} {'compz3':>6} {'z3win':>7}  note")
for i in range(1, 21):
    inst = f"prob_{i}"
    p = inst_dir / f"{inst}.json"
    d = json.load(open(p, encoding="utf-8"))
    # weights: look for common key shapes
    w = d.get("weights") or {k: d[k] for k in ("w1", "w2", "w3") if k in d}
    if isinstance(w, dict):
        w1 = w.get("w1") or w.get("tardiness") or 0
        w2 = w.get("w2") or w.get("workload") or 0
        w3 = w.get("w3") or w.get("preference") or 0
    elif isinstance(w, (list, tuple)):
        w1, w2, w3 = w
    else:
        w1 = w2 = w3 = None
    nblk = len(d.get("blocks", d.get("block", {})) or [])
    o, m = best.get(inst, (None, {}))
    ourz2, ourz3 = m.get("z2"), m.get("z3")
    t = comp[inst]["obj"]
    # z3 needed to beat target with our current z1(=assume same)/z2:
    need = None
    if w3 and ourz2 is not None:
        z1term = (m.get("z1") or 0) * (w1 or 0)
        need = (t - z1term - (w2 or 0) * ourz2) / w3
    print(f"{inst:9} {w1!s:>5} {w2!s:>5} {w3!s:>6} {nblk:>5} "
          f"{ourz2!s:>6} {ourz3!s:>6} {comp[inst]['z3']:>6} "
          f"{need if need is None else round(need):>7}")
