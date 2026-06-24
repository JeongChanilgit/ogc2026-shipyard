"""_m2.py -- M2: 선행블록 포함 밀도 균형 (설계문서 Part 4).  제출본 코드(_m1base).

M1(tardy 블록 자체 페널티)은 falsified.  M2는 원인을 친다:
  tardy 블록 b 는 그 시간창을 점유한 *선행블록*(earlier co-present) 때문에 늦는다.
  -> 그 선행블록들을 페널티해 포화 베이에서 빼낸다(여유 베이로 분산) -> b 가 빈 크레인창으로 당겨짐.
  penalty[predecessor][bay] += lam*w1*tardiness(b) / |preds(b)|   (downstream 지각의 blame 분배)

재그리디 메커니즘은 _REGREEDY_PEN 그대로 재사용(unified 무수정).  2-loop:
  그리디 -> txyo(측정) -> 재그리디(M2 pen) -> txyo(끝까지).
ORIGINAL 은 기록값(M1 2loop 런) 재사용 -> M2 arm 만 실행.  prob_38·30.  -> _m2_ledger.md.
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
LEDGER = os.path.join(SB, "_m2_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))
T_MEASURE = float(os.environ.get("M1_TMEAS", "300"))
T_FINAL = float(os.environ.get("M1_TFIN", "900"))
CHUNK = float(os.environ.get("M1_CHUNK", "300"))
LAM = float(os.environ.get("M1_LAM", "0.5"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38,30").split(",")]
# 기록된 ORIGINAL(그리디->txyo 수렴, M1 2loop 런) — 재실행 안 함
ORIG_REC = {38: 54658258, 30: 5330072}


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def penalty_m2(data, sol, lam, topk=None):
    """tardy 블록 b 의 *가장 막는* 선행블록 top-K(같은 베이·더 이른 entry·co-present, exit 늦은 순)에
    b 의 지각 blame 분배.  surgical: 소수 핵심 blocker 만 이동."""
    if topk is None:
        topk = int(os.environ.get("M2_TOPK", "1"))
    bp = adapter.deserialize(data, sol)
    w1 = data["weights"]["w1"]
    pen = {}
    n_tardy = 0
    for j, pl in bp.items():
        for b in pl:
            due = data["blocks"][b["id"]]["due_date"]
            r = b["exit"] - due
            if r <= 0:
                continue
            n_tardy += 1
            eb, xb = b["entry"], b["exit"]
            preds = [q for q in pl if q["id"] != b["id"]
                     and q["entry"] < eb
                     and q["entry"] < xb and q["exit"] > eb]
            if not preds:
                continue
            preds.sort(key=lambda q: q["exit"], reverse=True)   # 가장 늦게 나가는 = 가장 막음
            chosen = preds[:topk]
            share = lam * w1 * r / len(chosen)
            for q in chosen:
                d = pen.setdefault(q["id"], {})
                d[j] = d.get(j, 0.0) + share
    return pen, n_tardy, len(pen)


def greedy(data, path, pen):
    UG._REGREEDY_PEN = pen or {}
    res = UG.unified(data, TL_G, path)[0]
    UG._REGREEDY_PEN = {}
    return res


def txyo_curve(data, sol, total, tag, t0=0.0):
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
    orig = ORIG_REC.get(inst)
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})  ORIGINAL(rec)={fmt(orig)}  "
        f"measure={T_MEASURE:.0f} final={T_FINAL:.0f} lam={LAM}")
    t = time.time()
    r1 = greedy(data, path, None)
    sol_m, ev_m = txyo_curve(data, r1["_solution"], T_MEASURE, "M2.measure")
    pen, ntardy, npenblk = penalty_m2(data, sol_m, LAM)
    r2 = greedy(data, path, pen)
    log(f"  [M2 re-greedy={fmt(r2.get('objective'))}  (선행블록 {npenblk}개 페널티, "
        f"tardy {ntardy}개 원인추적, z1@measure={fmt(ev_m['z1'])})]")
    _s, ev2 = txyo_curve(data, r2["_solution"], T_FINAL, "M2.final", t0=T_MEASURE)
    mo = ev2["obj"]
    gain = (orig - mo) if (orig is not None and mo is not None) else None
    log(f"  => prob_{inst}: ORIGINAL={fmt(orig)}  M2={fmt(mo)}  z1={fmt(ev2['z1'])} z3={fmt(ev2['z3'])}  "
        f"gain={fmt(gain)}  M2<ORIG={mo < orig if (orig and mo) else None}  ({time.time()-t:.0f}s)")
    return dict(inst=f"prob_{inst}", orig=orig, m2=mo, gain=gain)


def main():
    log(f"\n\n# ===== M2 predecessor-density (submission code)  {time.strftime('%Y-%m-%d %H:%M')} =====")
    log(f"# PROBS={PROBS}  code=_m1base  lam={LAM}  unified={'_m1base' in UG.__file__}")
    assert "_m1base" in UG.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    ot = sum(r["orig"] for r in rows if r.get("orig") is not None)
    mt = sum(r["m2"] for r in rows if r.get("m2") is not None)
    nwin = sum(1 for r in rows if r.get("gain") and r["gain"] > 0)
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} =====")
    log(f"#   ORIGINAL total = {fmt(ot)}")
    log(f"#   M2       total = {fmt(mt)}   gain = {fmt(ot - mt)}  ({nwin}/{len(rows)} M2 wins)")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
