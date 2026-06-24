"""_profile_hot.py -- 파이프라인 핫스팟 프로파일 (numpy/비트연산 가속 대상 찾기).

그리디 + postproc(짧게) 를 cProfile 로 돌려 tottime/cumtime 상위 함수를 출력.
shapely 기하(crane/trap/collision/check_feasibility)가 정말 병목인지 = numpy/raster 로
바꿀 가치가 있는지 확인용.  ★ x-smart 등 측정 실런과 병렬 금지(코어 오염).

실행: env-python _profile_hot.py   (M1_PROBS=38, M1_PPT=90 기본)
"""
import os, sys, cProfile, pstats, io, json, time

SB = os.path.dirname(os.path.abspath(__file__))
M1BASE = os.path.join(SB, "_m1base")
sys.path.insert(0, SB)
sys.path.insert(0, M1BASE)
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1").items():
    os.environ.setdefault(k, v)
try:
    import psutil
    psutil.Process().cpu_affinity([int(c) for c in
                                   os.environ.get("PROF_CORES", "0,1,2,3").split(",")])
except Exception:
    pass

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
INST = os.environ.get("M1_PROBS", "38").split(",")[0]
TLG = float(os.environ.get("M1_TLG", "70"))
PPT = float(os.environ.get("M1_PPT", "90"))
path = f"{BASE}/instances/train/prob_{INST}.json"
data = json.load(open(path, encoding="utf-8"))

print(f"[profile] prob_{INST}  greedy TL={TLG:.0f}  postproc={PPT:.0f}s", flush=True)
prof = cProfile.Profile()
prof.enable()
res = UG.unified(data, TLG, path)[0]
sol = res["_solution"]
conv = PP.postprocess(data, sol, time.monotonic() + PPT)
prof.disable()
ev = S.global_eval(data, adapter.deserialize(data, conv))
print(f"[profile] done  greedy_obj={res.get('objective'):,}  conv_obj={ev['obj']:,}", flush=True)

s = io.StringIO()
ps = pstats.Stats(prof, stream=s)
print("\n===== TOP 30 by TOTTIME (self time) =====")
ps.sort_stats("tottime").print_stats(30)
print(s.getvalue())
s2 = io.StringIO()
ps2 = pstats.Stats(prof, stream=s2)
print("\n===== TOP 25 by CUMTIME =====")
ps2.sort_stats("cumulative").print_stats(25)
print(s2.getvalue())
