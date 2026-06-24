"""myalgorithm.py — OGC2026 제출 엔트리. best-of(v2 패킹, 원래 gassign 솔버).

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
    # ─────────────────────────────────────────────────────────────────────
    # STRICTLY SEQUENTIAL 시간 흐름 (고정 비율 분할 아님):
    #   ① v2 GLOBAL(가장 빠름) 를 먼저 완주 → sol_v2.
    #   ② 원래 솔버에 남은 시간의 LION'S SHARE 부여 → sol_orig.
    #        orig_deadline = hard_deadline − PP_MIN_RESERVE (작은 reserve 뿐).
    #        원래솔버는 time-filling(CP-SAT timing → set1 z1=0)이므로 시간을 깎으면
    #        set1 이 파국 회귀한다 → 검증된 원본만큼(최소) 시간을 보장한다.
    #   ③ post-process 는 맨 마지막, 남는 시간(>20s)이 있고 best z1>0 일 때만.
    #        ①·② 예산을 절대 빼앗지 않는다. 짧은 TL(120)서 leftover≈0 → 거의 안 돎
    #        → set1 안전. 긴 TL 서 leftover 큼 → set2 polish.
    # ─────────────────────────────────────────────────────────────────────
    t0 = time.time()
    SAFETY = max(8.0, timelimit * 0.08)
    hard_deadline = t0 + timelimit - SAFETY          # wall 데드라인 (≤ timelimit)
    # post-process 전용 작은 reserve — 큰 carve-out 아님. ②의 lion's share 를 깎지 않음.
    PP_MIN_RESERVE = min(timelimit * 0.15, 60.0)
    best, best_obj = None, None

    # ① v2 GLOBAL 먼저 (가장 빠름) — Linux(서버): 하드-킬 subprocess(budget 초과시
    #    프로세스그룹 SIGKILL → 절대 타임아웃 없음). Windows(개발/테스트): in-process.
    #    v2 는 time-filling 이 아니라 일찍 완주한다 → 남는 시간은 전부 ②로 흘러간다.
    try:
        tmp = os.path.join(_HERE, "_v2_inst.json")
        with open(tmp, "w") as f:
            json.dump(prob_info, f)
        # v2 캡: 검증된 원본값(0.6) 복원 + hard_deadline 초과 금지.
        #   v2 는 보통 이보다 훨씬 일찍 끝나므로 이 캡은 안전망일 뿐 → ②가 대부분 시간 차지.
        v2_budget = max(10.0, min(timelimit * 0.6, hard_deadline - time.time()))
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

    # ② 원래 솔버 — 남은 시간의 LION'S SHARE (set1 강·항상 feasible·self-limit) best-of.
    #    orig_deadline = hard_deadline − PP_MIN_RESERVE (작은 reserve 뿐, 큰 carve-out 아님).
    #    원래솔버는 time-filling(CP-SAT timing)이라 시간을 깎으면 set1 z1=0 이 깨진다 →
    #    검증된 원본(v2_budget=0.6, orig=remaining−SAFETY)과 동등 이상 시간을 보장한다.
    #    post-process(③)는 PP_MIN_RESERVE + ②가 일찍 끝나 남는 시간에서만 돈다.
    orig_deadline = hard_deadline - PP_MIN_RESERVE
    remaining = orig_deadline - time.time()
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

    # ④ v3 crane-repack POST-PROCESS (ADDITIVE · NEVER-WORSE · FREE).
    #    post-process 는 best-of 예산을 절대 빼앗지 않는다. best-of 가 일찍 끝나
    #    자연히 남는 시간(SAFETY 여유 제외)에서만 돌린다.
    #    실행 조건: (a) 남은 시간 > ~20s  AND  (b) best 의 z1(tardiness) > 0.
    #    z1==0 이면 post-process 는 tardiness 만 깎으므로 보장된 no-op → SKIP.
    #    → set1(z1=0 ~19/20)은 post-process 를 건너뛰고 best-of 의 FULL 예산 결과를
    #      그대로 반환(byte-identical, 회귀 0). prob_20 등 z1>0 만 polish.
    #    실패하면 무조건 직전 best 로 폴백 → feasible 제출이 절대 깨지지 않음.
    try:
        pp_remaining = hard_deadline - time.time()    # ①·②가 끝나고 남은 leftover
        if os.environ.get("OGC_NO_PP") == "1":
            pp_remaining = 0.0                        # 측정/디버그: post-process 비활성
        run_pp = best is not None and pp_remaining > 20.0
        if run_pp:
            # z1-skip 가드: best 의 tardiness(z1)가 0 이면 post-process 는 no-op → SKIP.
            best_z1 = None
            try:
                import utils as _U
                r = _U.check_feasibility(prob_info, best)
                if isinstance(r, dict):
                    best_z1 = r.get("obj1")
            except Exception:
                best_z1 = None
            if best_z1 is not None and best_z1 <= 1e-9:
                run_pp = False                        # z1==0 → set1 bypass (no-op)
        if run_pp:
            import time as _t
            mono_deadline = _t.monotonic() + pp_remaining
            import postproc as _PP
            sol_pp = _PP.postprocess(prob_info, best, mono_deadline)
            # never-worse 재확인: post-process 결과가 feasible 하고 더 좋을 때만 채택
            if sol_pp is not None and sol_pp is not best:
                o = _obj(prob_info, sol_pp)
                if o is not None and (best_obj is None or o <= best_obj + 1e-6):
                    best = sol_pp
    except Exception:
        pass                                          # 실패 → 직전 best 유지

    return best
