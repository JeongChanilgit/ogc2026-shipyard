"""prof_place.py — v2 전역 Pass B 배치의 시간을 cProfile 로 분해 (어디서 새나).

배치(place_one)는 in-process → 프로파일됨. CP-SAT 타이밍은 워커프로세스라 안 잡힘(무관, 빠름).
실행: <env-python> prof_place.py [prob]   (기본 prob_34)
"""
from __future__ import annotations

import os
import sys
import cProfile
import pstats
import io
import json

os.environ["OGC_FIT"] = "1"
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_GLOBAL"] = "1"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_34"
    data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
    path = os.path.join(TRAIN, nm + ".json")
    pr = cProfile.Profile()
    pr.enable()
    ug.unified(data, 120.0, path)
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s)
    print(f"== [{nm}] 전역 Pass B 프로파일 — TOTTIME(자기시간) 상위 18 ==", flush=True)
    ps.sort_stats("tottime").print_stats(18)
    out = s.getvalue()
    # 헤더 + 상위 라인만
    lines = out.splitlines()
    for ln in lines:
        if "function calls" in ln or "Ordered by" in ln:
            print(ln, flush=True)
    started = False
    cnt = 0
    for ln in lines:
        if ln.strip().startswith("ncalls"):
            print(ln, flush=True)
            started = True
            continue
        if started and ln.strip():
            print(ln, flush=True)
            cnt += 1
            if cnt >= 18:
                break


if __name__ == "__main__":
    main()
