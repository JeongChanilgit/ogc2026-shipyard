"""_m1_regreedy.py -- M1 정확-z1 피드백 re-greedy A/B on set2 (prob_21..40).

각 인스턴스:
  R0 = unified() no-feedback  (= "원래거" baseline; 별도 재실행 아니라 피드백 루프의 1라운드)
  R1 = unified() with soft penalty  sc += lam * w1 * realized_tardy[block]  (그 블록의 현 베이에만)
       realized_tardy 는 R0 의 타이밍 오라클이 마감한 *정확한* z1 (adapter 역직렬화).
  lam 여러 값 race -> best-of by objective (never-worse, feasible 필수).

기록 베이스라인(재실행 안 함, 참조선): notes/gassign-set2-120.json (프로덕션 gassign @TL120).
clean 요약 -> _m1_ledger.md, 상세 -> stdout(_m1.log).
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
# SB must be FIRST so the current (Jun-24, _REGREEDY_PEN-patched) unified_greedy wins over the
# stale parent ogc-2026-v2/unified_greedy.py.
sys.path.insert(0, V2)
sys.path.insert(0, SB)

os.environ.setdefault("OGC_GLOBAL", "1")
os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_ORDER", "blend")
os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG            # noqa: E402
from v3pp import adapter, seed as S     # noqa: E402  (S unused but mirrors runner pattern)

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_m1_ledger.md")
TL = float(os.environ.get("M1_TL", "70"))
LAMS = [float(x) for x in (os.environ.get("M1_LAMS") or "1.0,2.0").split(",")]
PROBS = [int(x) for x in (os.environ.get("M1_PROBS")
                          or ",".join(str(i) for i in range(21, 41))).split(",")]

GB = json.load(open(f"{BASE}/notes/gassign-set2-120.json", encoding="utf-8"))
GBI = {r["instance"]: r for r in GB["instances"]}


def fmt(x):
    return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def run_unified(data, inst_label, tl):
    return UG.unified(data, tl, inst_label)[0]   # check_feasibility dict (+_solution)


def realized_pen(data, res, lam):
    """R0 timed 해 -> {block_i: {bay0: lam*w1*realized_tardy}} (tardy 블록만)."""
    w1 = data["weights"]["w1"]
    bp = adapter.deserialize(data, res["_solution"])
    pen, ntardy = {}, 0
    for j, pl in bp.items():
        for p in pl:
            due = data["blocks"][p["id"]]["due_date"]
            r = max(0, p["exit"] - due)
            if r > 0:
                pen.setdefault(p["id"], {})[j] = lam * w1 * r
                ntardy += 1
    return pen, ntardy


def info(res):
    return (res.get("objective"), bool(res.get("feasible")),
            res.get("obj1"), res.get("obj3"))


def do(inst):
    inst_path = f"{BASE}/instances/train/prob_{inst}.json"
    data = json.load(open(inst_path, encoding="utf-8"))
    name = f"prob_{inst}"
    gobj = GBI.get(name, {}).get("gassign_obj")
    w1 = data["weights"]["w1"]
    log(f"\n### {name} (w1={w1:,}): gassign_ref={fmt(gobj)}")

    UG._REGREEDY_PEN = {}
    t = time.time(); res0 = run_unified(data, inst_path, TL)
    o0, f0, z1_0, z3_0 = info(res0)
    log(f"  [R0 baseline ] obj={fmt(o0):>14} z1={fmt(z1_0):>9} z3={fmt(z3_0):>7} "
        f"feas={f0} ({time.time()-t:4.0f}s)")
    best = (o0 if f0 else None, "R0")

    for lam in LAMS:
        try:
            pen, ntardy = realized_pen(data, res0, lam)
            UG._REGREEDY_PEN = pen
            t = time.time(); res1 = run_unified(data, inst_path, TL)
            UG._REGREEDY_PEN = {}
            o1, f1, z1_1, z3_1 = info(res1)
            d = (o0 - o1) if (o0 is not None and o1 is not None) else None
            log(f"  [R1 lam={lam:<4}] obj={fmt(o1):>14} z1={fmt(z1_1):>9} z3={fmt(z3_1):>7} "
                f"feas={f1} dObj={fmt(d):>12} tardy={ntardy} ({time.time()-t:4.0f}s)")
            if f1 and o1 is not None and (best[0] is None or o1 < best[0]):
                best = (o1, f"lam={lam}")
        except Exception as e:
            UG._REGREEDY_PEN = {}
            log(f"  [R1 lam={lam}] ERROR {e!r}")
            traceback.print_exc()

    bobj, bsrc = best
    vs0 = (o0 - bobj) if (o0 is not None and bobj is not None) else None
    log(f"  [BEST {bsrc:>9}] obj={fmt(bobj):>14}  feedback_gain(vs R0)={fmt(vs0)}")
    return dict(inst=name, r0=o0, feas0=f0, best=bobj, src=bsrc, gassign=gobj)


def main():
    log(f"\n\n# ===== M1 re-greedy z1-feedback  {time.strftime('%Y-%m-%d %H:%M')}  "
        f"TL={TL:.0f} LAMS={LAMS} =====")
    log(f"# PROBS={PROBS}  baseline_ref=gassign-set2-120 (recorded, not re-run)")
    log(f"# unified_greedy from: {UG.__file__}  (must be submission_build)")
    assert "submission_build" in UG.__file__, "WRONG unified_greedy loaded!"
    rows = []
    for inst in PROBS:
        try:
            rows.append(do(inst))
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    # ---- summary ----
    r0t = sum(r["r0"] for r in rows if r.get("r0") is not None)
    bt = sum(r["best"] for r in rows if r.get("best") is not None)
    gt = sum(r["gassign"] for r in rows if r.get("gassign") is not None)
    nfeas = sum(1 for r in rows if r.get("feas0"))
    helped = sum(1 for r in rows
                 if r.get("r0") is not None and r.get("best") is not None and r["best"] < r["r0"] - 1e-6)
    log(f"\n# ===== SUMMARY  done={len(rows)}/{len(PROBS)}  feasible(R0)={nfeas} =====")
    log(f"#   R0(baseline v2) total = {fmt(r0t)}")
    log(f"#   BEST(M1 feedback) total= {fmt(bt)}   feedback_gain = {fmt(r0t - bt)}  "
        f"({helped}/{len(rows)} instances improved)")
    log(f"#   gassign ref total      = {fmt(gt)}  (production; v2 known weaker on set2)")
    log(f"# ===== M1 run COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
