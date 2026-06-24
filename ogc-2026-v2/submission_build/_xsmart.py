"""_xsmart.py -- x 후보 생성 A/B: 균등분할(EVEN) vs 틈새정렬 flush(SMART).  제출본 코드(_m1base).

사용자 직관: x 후보를 기존 블록 가장자리에 붙는 '합리적 자리'로 주면 같은 후보 수로 더 좋을 것.
같은 greedy 출발해(sol0)에서 txyo 루프를 두 번 — OGC_XSMART=0 vs 1 — 돌려 x-후보 효과만 격리.
txyo 를 chunk 로 돌려 obj@t 수렴곡선 기록.  prob_38·30.  -> _xsmart_ledger.md.
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
LEDGER = os.path.join(SB, "_xsmart_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))
T_TXYO = float(os.environ.get("M1_PPT", "900"))
CHUNK = float(os.environ.get("M1_CHUNK", "300"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38,30").split(",")]


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def txyo_curve(data, sol0, total, tag):
    sol = json.loads(json.dumps(sol0))      # fresh copy per arm
    done, ev = 0.0, S.global_eval(data, adapter.deserialize(data, sol))
    while done < total - 1:
        dur = min(CHUNK, total - done)
        sol = PP.postprocess(data, sol, time.monotonic() + dur)
        done += dur
        ev = S.global_eval(data, adapter.deserialize(data, sol))
        log(f"  [{tag} t={done:>5.0f}s] obj={fmt(ev['obj']):>14} z1={fmt(ev['z1']):>7} "
            f"z3={fmt(ev['z3']):>6}")
    return ev


def do(inst):
    path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(path, encoding="utf-8"))
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})  txyo={T_TXYO:.0f}s")
    # greedy once -> shared start (XSMART irrelevant to greedy)
    os.environ["OGC_XSMART"] = "0"
    UG._REGREEDY_PEN = {}
    res = UG.unified(data, TL_G, path)[0]
    sol0 = res["_solution"]
    log(f"  [greedy start obj={fmt(res.get('objective'))}]")

    os.environ["OGC_XSMART"] = "0"
    ev_e = txyo_curve(data, sol0, T_TXYO, "EVEN ")
    os.environ["OGC_XSMART"] = "1"
    ev_s = txyo_curve(data, sol0, T_TXYO, "SMART")
    os.environ["OGC_XSMART"] = "0"

    oe, os_ = ev_e["obj"], ev_s["obj"]
    gain = (oe - os_) if (oe is not None and os_ is not None) else None
    log(f"  => prob_{inst}: EVEN={fmt(oe)} (z1={fmt(ev_e['z1'])})  "
        f"SMART={fmt(os_)} (z1={fmt(ev_s['z1'])})  gain={fmt(gain)}  "
        f"SMART<EVEN={os_ < oe if (oe and os_) else None}")
    return dict(inst=f"prob_{inst}", even=oe, smart=os_, gain=gain)


def main():
    log(f"\n\n# ===== x-candidate A/B: even vs flush-snap (submission)  "
        f"{time.strftime('%Y-%m-%d %H:%M')} =====")
    log(f"# PROBS={PROBS}  code=_m1base  unified={'_m1base' in UG.__file__}")
    assert "_m1base" in UG.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    et = sum(r["even"] for r in rows if r.get("even") is not None)
    st = sum(r["smart"] for r in rows if r.get("smart") is not None)
    nwin = sum(1 for r in rows if r.get("gain") and r["gain"] > 0)
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} =====")
    log(f"#   EVEN  total = {fmt(et)}")
    log(f"#   SMART total = {fmt(st)}   gain = {fmt(et - st)}  ({nwin}/{len(rows)} SMART wins)")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
