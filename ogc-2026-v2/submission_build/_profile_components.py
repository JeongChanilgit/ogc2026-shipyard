"""_profile_components.py -- 컴포넌트별 소요시간 (cProfile, __main__ 가드로 멀티프로세싱 오염 방지).
v7 코드, 제출 config(moveall+aabb). greedy + postproc(T) 프로파일 -> 컴포넌트별 tottime 집계.
실행: env-python _profile_components.py   (M1_PROBS=38, M1_PPT=120 기본)  ★실런과 병렬 금지.
"""
import os, sys, json, time, cProfile, pstats
from collections import defaultdict

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, V7)   # v7 first
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1", OGC_PP_MOVEALL="1", OGC_PRECOMP_AABB="1").items():
    os.environ.setdefault(k, v)

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
INST = (os.environ.get("M1_PROBS") or "38").split(",")[0]
TLG = float(os.environ.get("M1_TLG", "70"))
PPT = float(os.environ.get("M1_PPT", "120"))


def classify(fn, func):
    f = (fn.replace("\\", "/") + " " + str(func)).lower()
    if "swig_helper" in f or ("ortools" in f and "solve" in f) or "cp_model" in f:
        return "CP-SAT solve (ortools C++)"
    if "shapely" in f:
        return "shapely geometry"
    if "crane_cpsat" in f:
        return "precompute" if "_precompute" in func or "_build_candidates" in func else "crane model/extract"
    if "utils.py" in f:
        return "official checker (utils.py)"
    if "temporal_pack" in f:
        return "greedy: place/BL/contact"
    if "unified_greedy" in f:
        return "greedy: assign/marginal"
    if "ptiming" in f:
        return "timing (parallel_timing)"
    if "/seed.py" in f or "seed.py" in f:
        return "global_eval (serialize)"
    if "postproc" in f:
        return "postproc loop"
    if "/numpy/" in f or "numpy" in f:
        return "numpy"
    if "bpass" in f:
        return "cross-bay (try_move/swap)"
    return "other/stdlib"


def run():
    path = f"{BASE}/instances/train/prob_{INST}.json"
    data = json.load(open(path, encoding="utf-8"))
    res = UG.unified(data, TLG, path)[0]
    PP.postprocess(data, res["_solution"], time.monotonic() + PPT)


if __name__ == "__main__":
    print(f"[profile] prob_{INST}  greedy TL={TLG:.0f}  postproc={PPT:.0f}s  (moveall+aabb)", flush=True)
    prof = cProfile.Profile()
    prof.enable()
    run()
    prof.disable()
    st = pstats.Stats(prof)
    comp = defaultdict(float)
    total = 0.0
    for (fn, ln, func), (cc, nc, tt, ct, callers) in st.stats.items():
        comp[classify(fn, func)] += tt
        total += tt
    print(f"\n===== COMPONENT TIMING (total self-time {total:.1f}s) =====")
    for name, tt in sorted(comp.items(), key=lambda x: -x[1]):
        print(f"  {tt:8.1f}s  {100*tt/total:5.1f}%   {name}", flush=True)
