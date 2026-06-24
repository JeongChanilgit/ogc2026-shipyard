"""debug_feas.py — stage-5 infeasible 인스턴스의 *정확한 위반 op* 추적.

검증 config 로 지정 인스턴스를 여러 번 돌려, 실현불가 나오면 stage + violations 출력.
실행: <env-python> debug_feas.py prob_3 [trials]
"""
from __future__ import annotations

import os

os.environ["OGC_FIT"] = "1"
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_TOSS"] = "0"
os.environ["OGC_PACK_SWAP"] = "0"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ.setdefault("PYTHONUTF8", "1")

import json  # noqa: E402
import sys  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_3"
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    path = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(path, encoding="utf-8"))
    for tr in range(trials):
        res, dist, cpsat, dt = ug.unified(data, 120.0, path)
        obj = res.get("objective")
        if obj is None:
            print(f"[{nm}] trial {tr}: INFEAS stage={res.get('stage')} dist={dist}", flush=True)
            vs = res.get("violations", [])
            print(f"  위반 {len(vs)}건:", flush=True)
            for v in vs[:10]:
                print(f"    {v}", flush=True)
            return
        print(f"[{nm}] trial {tr}: OK obj={obj:,.0f} ({dt:.0f}s)", flush=True)
    print(f"[{nm}] {trials}회 전부 feasible (비결정적)", flush=True)


if __name__ == "__main__":
    main()
