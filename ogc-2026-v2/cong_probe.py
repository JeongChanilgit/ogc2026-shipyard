"""cong_probe.py — set2 인스턴스별 혼잡도(area-time demand / capacity) 빠른 계산 (solving 없음).

congestion = Σ(bbox면적·proc) / (Σ베이면적 · makespan). z1(α=0.5 실측)과 상관 → threshold 설정용.
"""
import json
import os

THIS = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(THIS, "..", "instances", "train")

# α=0.5 full set2 z1 (혼잡 지표 검증용)
Z1 = {21: 76, 22: 6, 23: 304, 24: 20, 25: 743, 26: 1032, 27: 2688, 28: 128, 29: 4,
      30: 381, 31: 429, 32: 1087, 33: 1595, 34: 197, 35: 91, 36: 110, 37: 1430,
      38: 4506, 39: 1131, 40: 3957}


def main():
    print(f"{'prob':9s} {'N':>4} {'bays':>4} {'cong':>6} {'z1':>6}", flush=True)
    rows = []
    for k in range(21, 41):
        data = json.load(open(os.path.join(TRAIN, f"prob_{k}.json"), encoding="utf-8"))
        blocks, bays = data["blocks"], data["bays"]
        mk = max((b["due_date"] for b in blocks), default=1) or 1
        dem = 0.0
        for b in blocks:
            xs = [p[0] for ly in b["shape"][0]["layers"] for p in ly]
            ys = [p[1] for ly in b["shape"][0]["layers"] for p in ly]
            a = (max(xs) - min(xs)) * (max(ys) - min(ys))
            dem += a * b.get("processing_time", 0)
        cap = sum(bb["width"] * bb["height"] for bb in bays) * mk
        cong = dem / max(1.0, cap)
        rows.append((k, cong))
        print(f"prob_{k:<4} {len(blocks):>4} {len(bays):>4} {cong:>6.2f} {Z1[k]:>6}", flush=True)
    rows.sort(key=lambda r: -r[1])
    print("\n혼잡도 순:", "  ".join(f"p{k}={c:.2f}(z1={Z1[k]})" for k, c in rows[:10]), flush=True)


if __name__ == "__main__":
    main()
