"""_m1_full15.py -- M1 정확-z1 피드백, FULL 파이프라인, 문제당 arm 15분.

사용자 설계 그대로:
  BASE = 1차 그리디 -> txyo 루프(postproc, productive arsenal) 수렴  (prob_38 ~54M 도달)
  z1   = 그 수렴해의 *정확한* per-block z1 (txyo 후)
  M1   = 정확z1로 2차 그리디(soft penalty) -> txyo 루프 수렴
각 arm 에 ~15분(greedy + postproc deadline).  공식 global_eval 로 최종 obj 비교.  never-worse + never-1.
clean -> _m1full_ledger.md, 상세 -> stdout.
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
sys.path.insert(0, V2)
sys.path.insert(0, SB)   # SB first -> current unified_greedy/postproc

# ---- env BEFORE imports: greedy gates + productive arsenal (=54M 수렴 설정, tonight's run) ----
for k, v in dict(OGC_GLOBAL="1", OGC_FIT="1", OGC_ORDER="blend", OGC_PLACE_W1_SCALE="1.0",
                 OGC_PP_DUALWIN="1", OGC_PP_PURET="1", OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40",
                 OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1", OGC_PP_KX="16",
                 OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80",
                 OGC_PP_FRONTMOVE="0", OGC_PP_CLUSTER="0").items():
    os.environ.setdefault(k, v)
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S   # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_m1full_ledger.md")
TL_G = float(os.environ.get("M1_TLG", "70"))       # greedy+timing budget
T_PP = float(os.environ.get("M1_PPT", "800"))      # txyo/postproc deadline (~13min) -> arm ~15min
LAM = float(os.environ.get("M1_LAM", "0.2"))
PROBS = [int(x) for x in (os.environ.get("M1_PROBS") or "38,30,23,29").split(",")]


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def pen_from_solution(data, sol, lam):
    """수렴해(post-txyo)의 per-block 정확 z1 -> {block:{bay:lam*w1*realized}}."""
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


def arm(data, path, pen, tag):
    UG._REGREEDY_PEN = pen or {}
    t = time.time()
    res = UG.unified(data, TL_G, path)[0]
    UG._REGREEDY_PEN = {}
    g = res.get("objective")
    conv = PP.postprocess(data, res["_solution"], time.monotonic() + T_PP)
    ev = S.global_eval(data, adapter.deserialize(data, conv))
    log(f"  [{tag} greedy={fmt(g):>13} -> txyo] obj={fmt(ev['obj']):>14} "
        f"z1={fmt(ev['z1']):>8} z3={fmt(ev['z3']):>7} feas={ev['feasible']} ({time.time()-t:.0f}s)")
    return ev, conv


def do(inst):
    path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(path, encoding="utf-8"))
    log(f"\n### prob_{inst} (w1={data['weights']['w1']:,})")
    ev0, conv0 = arm(data, path, None, "BASE          ")
    pen, ntardy = pen_from_solution(data, conv0, LAM)
    log(f"  (txyo-converged tardy blocks fed back: {ntardy}, lam={LAM})")
    ev1, conv1 = arm(data, path, pen, f"M1 lam={LAM}     ")
    bo, mo = ev0["obj"], ev1["obj"]
    gain = (bo - mo) if (bo is not None and mo is not None) else None
    survived = bool(ev1["feasible"] and mo is not None and bo is not None and mo < bo - 1e-6)
    log(f"  => POST-txyo gain={fmt(gain)}  M1<BASE={survived}")
    return dict(inst=f"prob_{inst}", base=bo, m1=mo, gain=gain, survived=survived,
                feas=(ev0["feasible"] and ev1["feasible"]))


def main():
    log(f"\n\n# ===== M1 FULL-pipeline (15min/arm)  {time.strftime('%Y-%m-%d %H:%M')}  "
        f"TLg={TL_G:.0f} Tpp={T_PP:.0f} lam={LAM} =====")
    log(f"# PROBS={PROBS}  arsenal=productive(dualwin/puret/wrongbay/moveall/freeall)  "
        f"unified={'submission_build' in UG.__file__}")
    assert "submission_build" in UG.__file__
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    bt = sum(r["base"] for r in rows if r.get("base") is not None)
    bestt = sum((r["m1"] if r.get("survived") else r["base"]) for r in rows
                if r.get("base") is not None)
    nsurv = sum(1 for r in rows if r.get("survived"))
    nfeas = sum(1 for r in rows if r.get("feas"))
    log(f"\n# ===== SUMMARY done={len(rows)}/{len(PROBS)} feasible={nfeas} =====")
    log(f"#   BASE(txyo-converged) total = {fmt(bt)}")
    log(f"#   best-of(BASE,M1)     total = {fmt(bestt)}  gain = {fmt(bt - bestt)}  "
        f"({nsurv}/{len(rows)} M1 beat BASE after txyo)")
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
