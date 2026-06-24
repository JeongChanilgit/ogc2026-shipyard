"""@300 gap structure analysis: where is the obj gap to competitor, and how
much z3 cut is needed per instance to flip a loss to a win.

Reads weights from instances/train/prob_N.json (weights field only matters),
our best-of @300 met across available @300 capture dirs, competitor obj.
Output is a compact table only -- no file dumps.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INST = ROOT / "instances" / "train"
CAP = ROOT / "results" / "capture"
DIRS = ["final300", "rasterforce300", "fbstrong300", "raster300", "default300"]

COMP = {k: v["obj"] for k, v in json.load(
    open(ROOT / "notes" / "competitor-2026-06-11.json", encoding="utf-8")
)["competitor"].items()}


def weights(inst):
    d = json.load(open(INST / f"{inst}.json", encoding="utf-8"))
    w = d.get("weights") or {}
    w1 = w.get("w1", d.get("w1"))
    w2 = w.get("w2", d.get("w2"))
    w3 = w.get("w3", d.get("w3"))
    return float(w1), float(w2), float(w3)


def best_met(inst):
    best = None
    for tag in DIRS:
        p = CAP / tag / f"{inst}.json"
        if not p.exists():
            continue
        try:
            m = json.load(open(p, encoding="utf-8")).get("met")
        except Exception:
            m = None
        if not m or not m.get("feas"):
            continue
        if best is None or m["obj"] < best[0]["obj"]:
            best = (m, tag)
    return best


hdr = (f"{'inst':9} {'ourObj':>9} {'compObj':>9} {'gap%':>6}  "
       f"{'w1*z1':>8} {'w2*z2':>8} {'w3*z3':>9}  {'z3':>5} "
       f"{'needZ3':>6} {'cut%':>5}  {'src':>12} {'win?':>4}")
print(hdr)
print("-" * len(hdr))
wins = 0
close = []
for i in range(1, 21):
    inst = f"prob_{i}"
    w1, w2, w3 = weights(inst)
    bm = best_met(inst)
    comp = COMP[inst]
    if bm is None:
        print(f"{inst:9} {'MISSING':>9}")
        continue
    m, tag = bm
    z1, z2, z3 = m["z1"], m["z2"], m["z3"]
    obj = m["obj"]
    c1, c2, c3 = w1 * z1, w2 * z2, w3 * z3
    gap = (obj - comp) / comp * 100.0
    win = obj < comp
    wins += win
    # z3 needed to beat comp holding z1,z2 fixed:
    need_z3 = (comp - c1 - c2) / w3
    cut = (z3 - need_z3) / z3 * 100.0 if z3 else 0.0
    flag = "" if win else (" <CLOSE" if 0 < gap <= 20 else (" <MID" if gap <= 60 else " <FAR"))
    if not win and 0 < gap <= 25:
        close.append((inst, gap, z3, need_z3))
    print(f"{inst:9} {obj:>9.0f} {comp:>9.0f} {gap:>6.1f}  "
          f"{c1:>8.0f} {c2:>8.0f} {c3:>9.0f}  {z3:>5.0f} "
          f"{need_z3:>6.0f} {cut:>5.0f}  {tag:>12} {('WIN' if win else 'lose'):>4}{flag}")

print("-" * len(hdr))
print(f"\nbest-of@300 wins: {wins}/20   (need 15)")
print(f"need to flip: {15 - wins} more")
print(f"\nCLOSE losses (gap<=25%, flippable):")
for inst, gap, z3, nz in close:
    print(f"  {inst}: gap {gap:.1f}%  z3 {z3:.0f} -> need {nz:.0f}  (cut {(z3-nz)/z3*100:.0f}%)")
print(f"\ntotal close-flippable: {len(close)}  -> if all flipped: {wins+len(close)}/20")
