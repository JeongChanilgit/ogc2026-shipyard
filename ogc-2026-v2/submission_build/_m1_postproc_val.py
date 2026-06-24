"""_m1_postproc_val.py -- 결정적 검증: M1 정확-z1 피드백 gain 이 production postproc 뒤에도 살아남나?

각 인스턴스: production env(greedy FIXOPT/TOSS + postproc WRONGBAY/MOVEALL/KX/FREEALL) 로
  BASE = postproc(unified no-feedback)
  M1   = postproc(unified @ lam=0.2 single, production-현실적)
최종 obj(공식 global_eval) 비교 + never-worse(best-of) + never−1.
clean -> _m1pp_ledger.md, 상세 -> stdout.
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
sys.path.insert(0, V2)
sys.path.insert(0, SB)   # SB first -> current unified_greedy/postproc

# ---- production env BEFORE imports (postproc _PP_* + unified gates) ----
for k, v in dict(OGC_GLOBAL="1", OGC_FIT="1", OGC_ORDER="blend", OGC_PLACE_W1_SCALE="1.0",
                 OGC_FIXOPT="1", OGC_TOSS="1",
                 OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1", OGC_PP_KX="16",
                 OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80").items():
    os.environ.setdefault(k, v)
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_m1pp_ledger.md")
TL = float(os.environ.get("M1_TL", "55"))        # greedy+timing per run
PPT = float(os.environ.get("M1_PPT", "60"))      # postproc deadline per run
LAM = float(os.environ.get("M1_LAM", "0.2"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "30,38,23,29,25,32").split(",")]


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def realized_pen(data, res, lam):
    w1 = data["weights"]["w1"]
    bp = adapter.deserialize(data, res["_solution"])
    pen = {}
    for j, pl in bp.items():
        for p in pl:
            r = max(0, p["exit"] - data["blocks"][p["id"]]["due_date"])
            if r > 0:
                pen.setdefault(p["id"], {})[j] = lam * w1 * r
    return pen


def pp_final(data, sol):
    fin = PP.postprocess(data, sol, time.monotonic() + PPT)
    ev = S.global_eval(data, adapter.deserialize(data, fin))
    return ev


def do(inst):
    path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(path, encoding="utf-8"))
    name = f"prob_{inst}"
    log(f"\n### {name} (w1={data['weights']['w1']:,})")

    # BASE: unified no-feedback -> postproc
    UG._REGREEDY_PEN = {}
    t = time.time(); res0 = UG.unified(data, TL, path)[0]
    g0 = res0.get("objective")
    evb = pp_final(data, res0["_solution"])
    log(f"  [BASE  greedy={fmt(g0)} -> postproc] obj={fmt(evb['obj']):>14} "
        f"z1={fmt(evb['z1'])} z3={fmt(evb['z3'])} feas={evb['feasible']} ({time.time()-t:.0f}s)")

    # M1: unified @lam -> postproc
    t = time.time()
    pen = realized_pen(data, res0, LAM)
    UG._REGREEDY_PEN = pen
    res1 = UG.unified(data, TL, path)[0]
    UG._REGREEDY_PEN = {}
    g1 = res1.get("objective")
    evm = pp_final(data, res1["_solution"])
    log(f"  [M1 l={LAM} greedy={fmt(g1)} -> postproc] obj={fmt(evm['obj']):>14} "
        f"z1={fmt(evm['z1'])} z3={fmt(evm['z3'])} feas={evm['feasible']} ({time.time()-t:.0f}s)")

    bo, mo = evb["obj"], evm["obj"]
    survived = (evm["feasible"] and mo is not None and bo is not None and mo < bo - 1e-6)
    gain_pre = (g0 - g1) if (g0 is not None and g1 is not None) else None
    gain_post = (bo - mo) if (bo is not None and mo is not None) else None
    log(f"  => greedy-stage gain={fmt(gain_pre)}  |  POST-postproc gain={fmt(gain_post)}  "
        f"survived={survived}")
    return dict(inst=name, base=bo, m1=mo, gain_post=gain_post, survived=survived,
                feas=(evb["feasible"] and evm["feasible"]))


def main():
    log(f"\n\n# ===== M1 postproc-survival  {time.strftime('%Y-%m-%d %H:%M')}  "
        f"TL={TL:.0f} PPT={PPT:.0f} LAM={LAM} =====")
    log(f"# PROBS={PROBS}  unified={UG.__file__.split(chr(92))[-2]}/  (must be submission_build)")
    assert "submission_build" in UG.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    bt = sum(r["base"] for r in rows if r.get("base") is not None)
    # best-of: keep M1 only where it survived, else base
    bestt = sum((r["m1"] if r.get("survived") else r["base"]) for r in rows
                if r.get("base") is not None)
    nsurv = sum(1 for r in rows if r.get("survived"))
    nfeas = sum(1 for r in rows if r.get("feas"))
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} feasible={nfeas} =====")
    log(f"#   BASE(postproc, no M1) total = {fmt(bt)}")
    log(f"#   best-of(BASE,M1)      total = {fmt(bestt)}  POST gain = {fmt(bt - bestt)}  "
        f"({nsurv}/{len(rows)} M1 survived postproc)")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
