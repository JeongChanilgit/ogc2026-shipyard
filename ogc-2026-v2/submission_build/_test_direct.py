import sys
import os
import json
import time


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import myalgorithm
    import utils
    for nm in ("prob_1", "prob_14", "prob_27", "prob_38"):
        data = json.load(open(os.path.join("..", "..", "instances", "train", nm + ".json"), encoding="utf-8"))
        t0 = time.time()
        sol = myalgorithm.algorithm(data, 120.0)
        wall = time.time() - t0
        r = utils.check_feasibility(data, sol)
        obj = r.get("objective") if isinstance(r, dict) else None
        st = "set1" if int(nm.split("_")[1]) <= 20 else "set2"
        print(f"[{st}] {nm:9s} obj={obj}  z1={r.get('obj1')} z2={r.get('obj2')} z3={r.get('obj3')}  "
              f"wall={wall:.1f}s {'⚠TL초과' if wall > 123 else 'OK'}", flush=True)


if __name__ == "__main__":      # ★ Windows spawn 워커 재실행 방지 (가드)
    main()
