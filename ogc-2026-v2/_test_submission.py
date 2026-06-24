"""격리 폴더 제출 테스트 (서버 모사). submission_build 안에서 실행 (cwd=submission_build).
import myalgorithm → algorithm(prob_info, TL) → utils.check_feasibility 검증."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INST = os.path.join(HERE, "..", "..", "instances", "train")   # 테스트 전용(제출엔 무관)


def main():
    import myalgorithm
    import utils
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    names = sys.argv[2:] or ["prob_1", "prob_25", "prob_38"]
    print(f"== 격리 제출 테스트 @TL={tl}s ==", flush=True)
    for nm in names:
        prob = json.load(open(os.path.join(INST, nm + ".json"), encoding="utf-8"))
        t0 = time.time()
        try:
            sol = myalgorithm.algorithm(prob, tl)
            dt = time.time() - t0
            r = utils.check_feasibility(prob, sol)
            ok = isinstance(r, dict) and r.get("objective") is not None
            print(f"  {nm}: {'FEASIBLE' if ok else 'INFEAS stage='+str(r.get('stage'))}  "
                  f"obj={r.get('objective')}  {dt:.0f}s  (TL={tl}, 초과={'YES!' if dt > tl else 'no'})",
                  flush=True)
        except Exception as e:
            import traceback
            print(f"  {nm}: CRASH {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    main()
