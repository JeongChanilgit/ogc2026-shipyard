"""_speedtest.py -- 15min txyo: ORIG vs OPT(AABB + cap_scale + diagonals).  제출본(_m1base).

같은 greedy 출발해(sol0)에서 txyo 루프를 두 번:
  ORIG = x,y,o          cap_scale=1.0  AABB off   (원래 파이프라인)
  OPT  = x,y,d1,d2,o    cap_scale=0.3  AABB on    (속도+대각선)
deadline-bound 라 "더 빠르면 같은 15분에 더 많이 수렴".  300s chunk 곡선.  prob_38·30.
-> _speedtest_ledger.md.
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__))
M1BASE = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, M1BASE)   # v7 FIRST

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
LEDGER = os.path.join(SB, "_speedtest_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))
T_TXYO = float(os.environ.get("M1_PPT", "900"))
CHUNK = float(os.environ.get("M1_CHUNK", "300"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38,30").split(",")]

# AABB on/off, everything else = submission config (moveall on, x,y,o, cap1)
ARMS = {
    "AABBoff": dict(OGC_PP_AXES="x,y,o", OGC_PP_CAP_SCALE="1.0", OGC_PRECOMP_AABB="0",
                    OGC_PP_MOVEALL="1"),
    "AABBon ": dict(OGC_PP_AXES="x,y,o", OGC_PP_CAP_SCALE="1.0", OGC_PRECOMP_AABB="1",
                    OGC_PP_MOVEALL="1"),
}


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def txyo_curve(data, sol0, total, tag, env):
    for k, v in env.items():
        os.environ[k] = v
    sol = json.loads(json.dumps(sol0))
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
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})  txyo={T_TXYO:.0f}s/arm")
    for k in ("OGC_PP_AXES", "OGC_PP_CAP_SCALE", "OGC_PRECOMP_AABB", "OGC_PP_MOVEALL"):
        os.environ.pop(k, None)
    UG._REGREEDY_PEN = {}
    res = UG.unified(data, TL_G, path)[0]
    sol0 = res["_solution"]
    log(f"  [greedy start obj={fmt(res.get('objective'))}]")
    out = {}
    for tag, env in ARMS.items():
        t = time.time()
        ev = txyo_curve(data, sol0, T_TXYO, tag, env)
        out[tag.strip()] = ev["obj"]
        log(f"  {tag} final = {fmt(ev['obj'])} z1={fmt(ev['z1'])} ({time.time()-t:.0f}s)")
    o, p = out.get("AABBoff"), out.get("AABBon")
    gain = (o - p) if (o is not None and p is not None) else None
    log(f"  => prob_{inst}: AABBoff={fmt(o)}  AABBon={fmt(p)}  diff={fmt(gain)}  "
        f"(AABB는 동일출력 기대 -- 차이=속도효과+노이즈)")
    return dict(inst=f"prob_{inst}", orig=o, opt=p, gain=gain)


def main():
    log(f"\n\n# ===== AABB on/off (submission config: moveall on, x,y,o, cap1)  "
        f"{time.strftime('%Y-%m-%d %H:%M')} =====")
    log(f"# PROBS={PROBS}  code={'v7' if '/v7/' in UG.__file__.replace(chr(92),'/') else '???'}")
    assert "v7" in UG.__file__ and "v7" in PP.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    ot = sum(r["orig"] for r in rows if r.get("orig") is not None)
    pt = sum(r["opt"] for r in rows if r.get("opt") is not None)
    nwin = sum(1 for r in rows if r.get("gain") and r["gain"] > 0)
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} =====")
    log(f"#   AABBoff total = {fmt(ot)}")
    log(f"#   AABBon  total = {fmt(pt)}   diff = {fmt(ot - pt)}  ({nwin}/{len(rows)} AABBon <= off)")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
