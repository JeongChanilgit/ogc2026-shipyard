"""seq_time.py — unified() 단계별 wall 시간 측정 (OGC_STAGES 계측 사용).

각 시퀀스(① CP-SAT 가이드라인 ② 그리디/전역 배치 ③ per-bay 패킹 ④ CP-SAT 타이밍 [⑤ LNS])
가 wall 의 몇 %를 쓰는지. global 0/1 둘 다.
실행: <env-python> seq_time.py [TL] [prob]   (기본 120, prob_38)
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_DIVERSE", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")
os.environ.setdefault("OGC_GUIDE_ATLOOSE", "0")
os.environ["OGC_STAGES"] = "1"

import json   # noqa: E402
import time   # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    nm = sys.argv[2] if len(sys.argv) > 2 else "prob_38"
    path = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(path, encoding="utf-8"))
    print(f"== 단계별 시간 [{nm}] N={len(data['blocks'])} bays={len(data['bays'])} @TL={tl}s ==",
          flush=True)
    for gv in ["0", "1"]:
        os.environ["OGC_GLOBAL"] = gv
        t0 = time.time()
        res, dist, ok, dt = ug.unified(data, tl, path)
        wall = time.time() - t0
        tag = "전역 Pass B (global=1)" if gv == "1" else "현재 2-pass (global=0)"
        print(f"\n[{tag}]  wall={wall:.1f}s  obj={res.get('objective'):,}  "
              f"z1={res.get('obj1')}", flush=True)
        print(f"  {'단계':34s} {'dt(s)':>7} {'누적':>7} {'%wall':>6}", flush=True)
        acc = 0.0
        for s in ug.STAGES:
            acc = s["t"]
            print(f"  {s['name']:34s} {s['dt']:>7.1f} {s['t']:>7.1f} {100*s['dt']/wall:>5.0f}%",
                  flush=True)
        other = wall - acc
        print(f"  {'(나머지: 셋업·결과조립)':34s} {other:>7.1f} {wall:>7.1f} {100*other/wall:>5.0f}%",
              flush=True)


if __name__ == "__main__":
    main()
