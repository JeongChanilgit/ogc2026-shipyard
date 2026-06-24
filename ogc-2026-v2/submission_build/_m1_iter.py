"""_m1_iter.py -- M1 정확-z1 피드백을 **반복(fixed-point)** 으로. 제출본 코드(_m1base).

사용자 지적: 재그리디 1번(=배정 루프 2회)만으론 수렴 안 됨. 계속 반복해야.
  iter0 BASE = 1차 그리디 -> txyo 수렴
  iter k     = 현재해의 정확 z1 -> 재그리디(soft penalty) -> txyo 수렴
매 iter 현재해에서 penalty 재계산(Gauss-Seidel fixed-point).  best-of 추적(never-worse).
prob_38 집중.  clean -> _m1iter_ledger.md.
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__))
M1BASE = os.path.join(SB, "_m1base")
sys.path.insert(0, SB)
sys.path.insert(0, M1BASE)   # submission code FIRST

for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1").items():
    os.environ.setdefault(k, v)
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_m1iter_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))
T_PP = float(os.environ.get("M1_PPT", "500"))      # txyo per iter
N_ITER = int(os.environ.get("M1_ITERS", "5"))
LAM = float(os.environ.get("M1_LAM", "0.2"))
ACCUM = os.environ.get("M1_ACCUM", "0") == "1"     # 1=penalty 누적, 0=매 iter 새로
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38").split(",")]


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def penalty(data, sol, lam, base=None):
    """현재 해의 per-block 정확 z1 -> {block:{bay:lam*w1*realized}}.  base!=None 이면 누적."""
    w1 = data["weights"]["w1"]
    bp = adapter.deserialize(data, sol)
    pen = {b: dict(d) for b, d in (base or {}).items()} if ACCUM else {}
    ntardy = 0
    for j, pl in bp.items():
        for p in pl:
            r = max(0, p["exit"] - data["blocks"][p["id"]]["due_date"])
            if r > 0:
                cur = pen.setdefault(p["id"], {})
                cur[j] = cur.get(j, 0.0) + lam * w1 * r
                ntardy += 1
    return pen, ntardy


def run_arm(data, path, pen, t_pp):
    UG._REGREEDY_PEN = pen or {}
    res = UG.unified(data, TL_G, path)[0]
    UG._REGREEDY_PEN = {}
    g = res.get("objective")
    conv = PP.postprocess(data, res["_solution"], time.monotonic() + t_pp)
    ev = S.global_eval(data, adapter.deserialize(data, conv))
    return g, ev, conv


def do(inst):
    path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(path, encoding="utf-8"))
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})  iters={N_ITER} lam={LAM} "
        f"txyo/iter={T_PP:.0f}s accum={ACCUM}")
    t = time.time()
    g0, ev0, sol = run_arm(data, path, None, T_PP)
    base0 = ev0["obj"]
    log(f"  [iter0 BASE   greedy={fmt(g0):>13}] obj={fmt(base0):>14} z1={fmt(ev0['z1']):>7} "
        f"z3={fmt(ev0['z3']):>6} ({time.time()-t:.0f}s)")
    best, best_it, pen = base0, 0, None
    for it in range(1, N_ITER + 1):
        t = time.time()
        pen, ntardy = penalty(data, sol, LAM, base=pen)
        gk, evk, solk = run_arm(data, path, pen, T_PP)
        ok = evk["obj"]
        mark = "  <== NEW BEST" if (ok is not None and ok < best - 1e-6) else ""
        log(f"  [iter{it} greedy={fmt(gk):>13}] obj={fmt(ok):>14} z1={fmt(evk['z1']):>7} "
            f"z3={fmt(evk['z3']):>6} feas={evk['feasible']} pen_blocks={ntardy} "
            f"({time.time()-t:.0f}s){mark}")
        if evk["feasible"] and ok is not None and ok < best - 1e-6:
            best, best_it = ok, it
        sol = solk    # fixed-point: 다음 penalty 는 이 해에서
    log(f"  => BASE(iter0)={fmt(base0)}  BEST=iter{best_it} {fmt(best)}  "
        f"gain vs BASE={fmt(base0 - best)}")
    return dict(inst=f"prob_{inst}", base=base0, best=best, best_it=best_it)


def main():
    log(f"\n\n# ===== M1 ITERATIVE feedback (submission code)  {time.strftime('%Y-%m-%d %H:%M')} "
        f"=====")
    log(f"# PROBS={PROBS}  code=_m1base  unified={'_m1base' in UG.__file__}")
    assert "_m1base" in UG.__file__
    for inst in PROBS:
        try:
            do(inst)
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
