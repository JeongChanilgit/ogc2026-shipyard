"""build_submission.py — best-of(v2, 원래) 제출 폴더 + zip 조립 (재현가능).

구조: myalgorithm.py(래퍼) = ① v2(캡,빠름) → ② 남은시간 원래솔버 best-of → ③ baseline 폴백.
      타임아웃 안전(SAFETY 여유), 절대 −1 없음(baseline).
번들: src/*.py(원래솔버, myalgorithm.py→solver_orig.py) + v2 8모듈(import 수정·경로해킹 제거) + utils.py.

실행: <env-python> build_submission.py        → submission_build/ + submissions/v-bestof-*.zip
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile

THIS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(THIS, "..", "src")
OUT = os.path.join(THIS, "submission_build")

V2_MODULES = ["unified_greedy", "temporal_pack", "cpsat_guideline", "gridmap",
              "density_pack", "assign_search", "ptiming", "merge"]

WRAPPER = r'''"""myalgorithm.py — OGC2026 제출 엔트리. best-of(v2 패킹, 원래 gassign 솔버).

algorithm(prob_info, timelimit):
  ① v2(캡 적용·빠름)를 예산 제한으로 실행 → feasible 면 후보
  ② 남은 시간(SAFETY 여유 제외)에 원래 솔버 실행 → best-of (원래=set1 강·항상 feasible)
  ③ 둘 다 실패 시 baseline_greedy 폴백 → 절대 infeasible/−1 없음
SAFETY 여유로 타임아웃 없음. 모든 경로 상대 import (실행폴더 루트).
"""
import os
import sys
import time
import json

# --- 검증된 v2 config 주입 (모듈 import 전) ---
os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_DIVERSE", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")
os.environ.setdefault("OGC_TOSS", "0")
os.environ.setdefault("OGC_PACK_SWAP", "0")
os.environ.setdefault("OGC_GUIDE_ATLOOSE", "0")
os.environ.setdefault("OGC_LNS", "0")
os.environ.setdefault("OGC_MERGE", "0")
os.environ.setdefault("OGC_GLOBAL", "1")        # ★ 전역 Pass B (이번 세션 엔진 — 필수)
os.environ.setdefault("OGC_ORDER", "blend")     # ★ 채택 순서: R+0.5P (set2 +9.2% vs EDD)
os.environ.setdefault("OGC_ORDER_ALPHA", "0.5")
os.environ.setdefault("OGC_FFT_MASK", "1")      # ★ 속도: FFT 마스크 (큰 베이 3×)
# OGC_STACK 미설정 → 기본 no-stack (크레인 EXIT feasibility)

import signal
import multiprocessing as _mp

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _obj(prob_info, sol):
    import utils
    try:
        r = utils.check_feasibility(prob_info, sol)
    except Exception:
        return None
    if isinstance(r, dict) and r.get("objective") is not None:
        return r["objective"]
    return None


def _v2_entry(prob_info, budget, tmp, q):
    """v2 를 자식 프로세스서 실행 (자체 프로세스그룹 → 워커풀까지 한번에 kill 가능)."""
    try:
        os.setsid()
    except Exception:
        pass
    try:
        import unified_greedy as _ug
        res, _d, _c, _t = _ug.unified(prob_info, budget, tmp)
        q.put(res.get("_solution") if isinstance(res, dict) else None)
    except Exception:
        try:
            q.put(None)
        except Exception:
            pass


def algorithm(prob_info, timelimit=60):
    t0 = time.time()
    SAFETY = max(8.0, timelimit * 0.08)
    best, best_obj = None, None

    # ① v2 — Linux(서버): 하드-킬 subprocess(budget 초과시 프로세스그룹 SIGKILL → 절대 타임아웃 없음).
    #         Windows(개발/테스트): in-process (서버는 Linux 이므로 무관).
    try:
        tmp = os.path.join(_HERE, "_v2_inst.json")
        with open(tmp, "w") as f:
            json.dump(prob_info, f)
        # v2 먼저(우선) but 캡 → 원래솔버가 set1용 시간 확보(best-of). v2 일찍 끝나면 원래솔버가 더 받음.
        v2_budget = max(10.0, min(timelimit * 0.6, timelimit - SAFETY))
        sol = None
        if hasattr(os, "fork"):
            ctx = _mp.get_context("fork")
            q = ctx.Queue()
            p = ctx.Process(target=_v2_entry, args=(prob_info, v2_budget, tmp, q))
            p.start()
            p.join(v2_budget + 3.0)                 # 하드 데드라인
            if p.is_alive():
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                p.join(2.0)
            else:
                try:
                    sol = q.get_nowait()
                except Exception:
                    sol = None
        else:
            import unified_greedy as _ug          # Windows 폴백 (in-process)
            res, _d, _c, _t = _ug.unified(prob_info, v2_budget, tmp)
            sol = res.get("_solution") if isinstance(res, dict) else None
        if sol is not None:
            o = _obj(prob_info, sol)
            if o is not None:
                best, best_obj = sol, o
    except Exception:
        pass

    # ② 남은 시간 → 원래 솔버 (set1 강·항상 feasible·self-limit) best-of
    remaining = timelimit - (time.time() - t0) - SAFETY
    if remaining > 5.0:
        try:
            import solver_orig as _O
            sol_o = _O.algorithm(prob_info, remaining)
            o = _obj(prob_info, sol_o)
            if o is not None and (best is None or o < best_obj):
                best, best_obj = sol_o, o
        except Exception:
            pass

    # ③ 최후 폴백: baseline (절대 feasible) → 절대 −1 없음
    if best is None:
        try:
            import baseline_greedy as _B
            rem = max(5.0, timelimit - (time.time() - t0) - 1.0)
            best = _B.greedyalgorithm(prob_info, rem)
        except Exception:
            best = {"operations": {}}
    return best
'''


def _fix_v2(text):
    text = text.replace("from myalgorithm import", "from solver_orig import")
    # ../src 경로해킹 제거 (서버는 전부 루트 평면)
    out = []
    skip = 0
    for ln in text.splitlines():
        if skip > 0:
            skip -= 1
            continue
        s = ln.strip()
        if s.startswith("_SRC = os.path.join(THIS"):
            continue
        if s == "if _SRC not in sys.path:":
            skip = 1                      # 다음 줄(insert) 도 제거
            continue
        if 'sys.path.insert(0, os.path.join(THIS, "..", "src"))' in ln:
            continue
        out.append(ln)
    return "\n".join(out) + "\n"


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    # 1) src/*.py → OUT (myalgorithm.py → solver_orig.py, v2와 겹치는 lns.py 는 src것 유지)
    for fn in os.listdir(SRC):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        dst = "solver_orig.py" if fn == "myalgorithm.py" else fn
        shutil.copy(os.path.join(SRC, fn), os.path.join(OUT, dst))

    # 2) v2 8모듈 → OUT (import 수정 + 경로해킹 제거). lns.py(v2)는 제외(LNS off, src/lns 충돌 회피)
    for m in V2_MODULES:
        txt = open(os.path.join(THIS, m + ".py"), encoding="utf-8").read()
        open(os.path.join(OUT, m + ".py"), "w", encoding="utf-8").write(_fix_v2(txt))

    # 3) 전 모듈 일괄 치환: 원래 myalgorithm → solver_orig (래퍼 제외)
    for fn in os.listdir(OUT):
        if not fn.endswith(".py"):
            continue
        p = os.path.join(OUT, fn)
        t = open(p, encoding="utf-8").read()
        t2 = t.replace("from myalgorithm import", "from solver_orig import")
        t2 = re.sub(r"(?m)^(\s*)import myalgorithm as (\w+)",
                    r"\1import solver_orig as \2", t2)              # import myalgorithm as M
        t2 = re.sub(r"(?m)^(\s*)import myalgorithm[ \t]*(#.*)?$",
                    r"\1import solver_orig as myalgorithm", t2)     # import myalgorithm (alias 유지)
        if t2 != t:
            open(p, "w", encoding="utf-8").write(t2)

    # 4) 래퍼
    open(os.path.join(OUT, "myalgorithm.py"), "w", encoding="utf-8").write(WRAPPER)

    # 5) 잔존 절대경로/문제 import 점검
    issues = []
    for fn in os.listdir(OUT):
        if not fn.endswith(".py"):
            continue
        t = open(os.path.join(OUT, fn), encoding="utf-8").read()
        for pat in ['"..", "src"', "'..', 'src'", "from myalgorithm import"]:
            if pat in t:
                issues.append(f"{fn}: {pat}")
    n = len([f for f in os.listdir(OUT) if f.endswith('.py')])
    print(f"조립: {OUT}  ({n} .py)  잔존이슈={issues or 'none'}", flush=True)

    # 6) zip (myalgorithm.py 루트, 테스트/temp 제외, ≤15MB)
    sub_dir = os.path.join(THIS, "..", "submissions")
    os.makedirs(sub_dir, exist_ok=True)
    zpath = os.path.join(sub_dir, "v-bestof-v2orig.zip")
    inc = []
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(OUT)):
            if fn.startswith("_") or not fn.endswith(".py"):
                continue                      # 테스트/temp(_*)·비.py 제외
            z.write(os.path.join(OUT, fn), fn)   # 루트 평면
            inc.append(fn)
    size = os.path.getsize(zpath)
    has_entry = "myalgorithm.py" in inc
    print(f"zip: {zpath}", flush=True)
    print(f"  {len(inc)} files, {size/1024:.0f} KB  "
          f"[myalgorithm.py 루트={'OK' if has_entry else '없음!'}, "
          f"≤15MB={'OK' if size < 15e6 else '초과!'}]", flush=True)


if __name__ == "__main__":
    main()
