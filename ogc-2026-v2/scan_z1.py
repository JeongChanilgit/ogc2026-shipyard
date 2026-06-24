"""
scan_z1.py — 원래 솔버의 z1(tardiness)을 인스턴스별로 스캔 → 패킹병목(high-z1) 식별.

v2 내부 z1이 아니라 *원래 솔버*가 실제로 얼마나 지각하는지 본다. z1 큰 인스턴스가
패킹 이식이 이득 볼 후보 (z1≈0 이면 패킹병목 아님 → 이식 무이득).

실행: <env-python> scan_z1.py 60 prob_21 prob_22 ... (TL짧게 여러개)
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
import myalgorithm  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    names = sys.argv[2:] or [f"prob_{i}" for i in range(21, 41)]
    print(f"== 원래 솔버 z1 스캔 (TL={tl}s) — high-z1 = 패킹병목 후보 ==", flush=True)
    print(f"{'inst':<10}{'N':>4}{'bays':>5}{'w1':>8}{'obj':>14}{'z1':>8}{'z2':>8}{'z3':>8}{'t':>6}", flush=True)
    print("-" * 76, flush=True)
    rows = []
    for nm in names:
        p = os.path.join(TRAIN, nm + ".json")
        if not os.path.exists(p):
            continue
        data = json.load(open(p, encoding="utf-8"))
        t0 = time.time()
        try:
            sol = myalgorithm.algorithm(data, tl)
            res = utils.check_feasibility(data, sol)
        except Exception as e:
            print(f"{nm:<10} ERROR {e}", flush=True)
            continue
        dt = time.time() - t0
        z1 = res.get("obj1")
        rows.append((nm, z1, res.get("objective")))
        print(f"{nm:<10}{len(data['blocks']):>4}{len(data['bays']):>5}"
              f"{data['weights']['w1']:>8}{(res.get('objective') or -1):>14,.0f}"
              f"{(z1 if z1 is not None else -1):>8.0f}{(res.get('obj2') or -1):>8.0f}"
              f"{(res.get('obj3') or -1):>8.0f}{dt:>6.0f}", flush=True)
    print("-" * 76, flush=True)
    hi = sorted([r for r in rows if r[1]], key=lambda r: -r[1])[:5]
    print("high-z1 (패킹 이식 후보): " + ", ".join(f"{n}(z1={z:.0f})" for n, z, _ in hi), flush=True)


if __name__ == "__main__":
    main()
