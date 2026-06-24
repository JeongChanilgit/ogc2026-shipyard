"""_m1_2loop.py -- 사용자 설계: [그리디->txyo] x2 그 다음 txyo 끝까지.  제출본 코드(_m1base).

  ORIGINAL = 그리디 -> txyo(끝까지)                         (= 원래 제출본 v2 경로)
  2LOOP    = 그리디 -> txyo(측정,짧게) -> 재그리디 -> txyo(끝까지)
두 arm 동일 wall 예산.  txyo 는 chunk 로 돌려 수렴 곡선(obj@t) 기록.  공식 global_eval 비교.
prob_38·30.  clean -> _m12loop_ledger.md.
"""
import os, sys, json, time, traceback

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
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_m12loop_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))
T_MEASURE = float(os.environ.get("M1_TMEAS", "300"))   # loop-1 txyo (z1 측정)
T_FINAL = float(os.environ.get("M1_TFIN", "900"))      # 재그리디 후 끝까지 txyo
CHUNK = float(os.environ.get("M1_CHUNK", "300"))
LAM = float(os.environ.get("M1_LAM", "0.2"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38,30").split(",")]


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def penalty(data, sol, lam):
    w1 = data["weights"]["w1"]
    bp = adapter.deserialize(data, sol)
    pen, ntardy = {}, 0
    for j, pl in bp.items():
        for p in pl:
            r = max(0, p["exit"] - data["blocks"][p["id"]]["due_date"])
            if r > 0:
                pen.setdefault(p["id"], {})[j] = lam * w1 * r
                ntardy += 1
    return pen, ntardy


def greedy(data, path, pen):
    UG._REGREEDY_PEN = pen or {}
    res = UG.unified(data, TL_G, path)[0]
    UG._REGREEDY_PEN = {}
    return res


def txyo_curve(data, sol, total, tag, t0=0.0):
    """postproc 를 CHUNK 단위로 돌려 obj@t 곡선 기록.  마지막 ev 반환."""
    done, ev = 0.0, S.global_eval(data, adapter.deserialize(data, sol))
    while done < total - 1:
        dur = min(CHUNK, total - done)
        sol = PP.postprocess(data, sol, time.monotonic() + dur)
        done += dur
        ev = S.global_eval(data, adapter.deserialize(data, sol))
        log(f"  [{tag} t={t0+done:>5.0f}s] obj={fmt(ev['obj']):>14} z1={fmt(ev['z1']):>7} "
            f"z3={fmt(ev['z3']):>6}")
    return sol, ev


def do(inst):
    path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(path, encoding="utf-8"))
    T_TXYO = T_MEASURE + T_FINAL
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})  measure={T_MEASURE:.0f} "
        f"final={T_FINAL:.0f} total_txyo={T_TXYO:.0f} lam={LAM}")

    # ---- ORIGINAL: greedy -> txyo(끝까지) ----  (M1_ORIG_REF 주면 재실행 skip, 기록값 사용)
    _ref = os.environ.get("M1_ORIG_REF")
    if _ref:
        ev_o = {"obj": float(_ref), "z1": None}
        log(f"  [ORIG = recorded {fmt(float(_ref))} (skipped re-run)]")
    else:
        t = time.time()
        r = greedy(data, path, None)
        log(f"  [ORIG greedy={fmt(r.get('objective'))}]")
        _so, ev_o = txyo_curve(data, r["_solution"], T_TXYO, "ORIG")
        log(f"  ORIGINAL final = {fmt(ev_o['obj'])} z1={fmt(ev_o['z1'])} ({time.time()-t:.0f}s)")

    # ---- 2LOOP: greedy -> txyo(측정) -> 재그리디 -> txyo(끝까지) ----
    t = time.time()
    r1 = greedy(data, path, None)
    sol_m, ev_m = txyo_curve(data, r1["_solution"], T_MEASURE, "2L.measure")
    pen, ntardy = penalty(data, sol_m, LAM)
    r2 = greedy(data, path, pen)
    log(f"  [2L re-greedy={fmt(r2.get('objective'))}  (fed back {ntardy} tardy from t={T_MEASURE:.0f} z1={fmt(ev_m['z1'])})]")
    _sm, ev_m2 = txyo_curve(data, r2["_solution"], T_FINAL, "2L.final", t0=T_MEASURE)
    log(f"  2LOOP final = {fmt(ev_m2['obj'])} z1={fmt(ev_m2['z1'])} ({time.time()-t:.0f}s)")

    oo, mo = ev_o["obj"], ev_m2["obj"]
    gain = (oo - mo) if (oo is not None and mo is not None) else None
    log(f"  => prob_{inst}: ORIGINAL={fmt(oo)}  2LOOP={fmt(mo)}  gain={fmt(gain)}  "
        f"2LOOP<ORIG={mo < oo if (oo and mo) else None}")
    return dict(inst=f"prob_{inst}", orig=oo, m1=mo, gain=gain)


def main():
    log(f"\n\n# ===== M1 2-LOOP vs ORIGINAL (submission code)  {time.strftime('%Y-%m-%d %H:%M')} =====")
    log(f"# PROBS={PROBS}  code=_m1base  unified={'_m1base' in UG.__file__}")
    assert "_m1base" in UG.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    ot = sum(r["orig"] for r in rows if r.get("orig") is not None)
    mt = sum(r["m1"] for r in rows if r.get("m1") is not None)
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} =====")
    log(f"#   ORIGINAL total = {fmt(ot)}")
    log(f"#   2LOOP    total = {fmt(mt)}   gain = {fmt(ot - mt)}")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
