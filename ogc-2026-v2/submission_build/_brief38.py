"""_brief38.py -- run v2+v3 (with the NEW pure-t pass) on prob_38 for 10 min,
capture per-step trace (postproc._STEP_TRACE) + stage trace (myalgorithm_fix._TRACE),
dump to out/brief38.json.  Single-scale (no scale-bestof) for a clean instrument run.

env knobs are set below; run with env python directly (conda run crashes 4-worker CP-SAT).
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    # --- adopted v2+v3 config + NEW pure-t + instrumentation ---
    os.environ["OGC_NO_V1"] = "1"
    os.environ.setdefault("OGC_PLACE_W1_SCALE", "0.5")  # launch env overrides (greedy-start lever: 0=z3-only, 1.0=z1z3)
    os.environ["OGC_PP_WRONGBAY"] = "1"
    os.environ["OGC_TOSS"] = "1"
    os.environ["OGC_FIXOPT"] = "1"
    os.environ["OGC_PP_KX"] = "16"
    os.environ["OGC_PP_FREEALL"] = "1"
    os.environ["OGC_PP_FREEALL_MAX"] = "80"
    os.environ["OGC_PP_MOVEALL"] = "1"
    os.environ["OGC_PP_PURET"] = "1"             # <-- the new lever
    os.environ["OGC_PP_TRACE"] = "1"             # <-- step instrumentation
    os.environ["OGC_V2_CAP"] = "90"
    os.environ.pop("OGC_SCALE_BESTOF", None)
    # window mode for the axis passes (launch env may override these)
    os.environ.setdefault("OGC_PP_WINDOW", "x")  # x | t | xt
    os.environ.setdefault("OGC_PP_TMARGIN", "0")

    # 4-core affinity to mirror the eval server (best-effort)
    try:
        import psutil
        psutil.Process().cpu_affinity([0, 1, 2, 3])
    except Exception:
        pass

    import myalgorithm_fix as M
    import postproc as PP
    import utils
    BASE = "C:/claude-develop/OGC2026"
    INST = os.environ.get("BRIEF_INST", "38")
    TL = float(os.environ.get("BRIEF_TL", "600"))
    data = json.load(open(f"{BASE}/instances/train/prob_{INST}.json", encoding="utf-8"))

    fixed = os.environ.get("BRIEF_FIXED_START")
    if fixed and not os.path.isabs(fixed):
        fixed = os.path.join(V2, fixed)
    if fixed:
        # FIXED-START A/B: load (or build once) a v2-only solution, then run ONLY
        # postproc on it for TL seconds.  Both A/B configs share the same start ->
        # clean isolation of the postproc change (no v2 nondeterminism confound).
        from v3pp import adapter as _AD, seed as _S
        if os.path.exists(fixed):
            sol0 = json.load(open(fixed, encoding="utf-8"))
            print(f"[fixed] loaded start <- {fixed}", flush=True)
        else:
            os.environ["OGC_NO_PP"] = "1"
            sol0 = M.algorithm(data, float(os.environ.get("BRIEF_V2TL", "600")))
            os.environ.pop("OGC_NO_PP", None)
            os.makedirs(os.path.dirname(fixed), exist_ok=True)
            json.dump(sol0, open(fixed, "w"))
            print(f"[fixed] built start -> {fixed}", flush=True)
        bp0 = _AD.deserialize(data, sol0)
        base0 = _S.global_eval(data, bp0)
        import time as _t
        t0 = time.time()
        sol = PP.postprocess(data, sol0, _t.monotonic() + TL)
        wall = time.time() - t0
        M._TRACE = {"base_obj": base0["obj"], "v2_obj": base0["obj"],
                    "pp_budget": TL, "pp_wall": round(wall, 1), "fixed_start": fixed}
    else:
        t0 = time.time()
        sol = M.algorithm(data, TL)
        wall = time.time() - t0
    r = utils.check_feasibility(data, sol)

    out = {
        "instance": f"prob_{INST}", "tl": TL, "wall": wall,
        "objective": r.get("objective"), "z1": r.get("obj1"),
        "z2": r.get("obj2"), "z3": r.get("obj3"),
        "feasible": r.get("objective") is not None,
        "config": {"window": os.environ.get("OGC_PP_WINDOW"),
                   "tmargin": os.environ.get("OGC_PP_TMARGIN"),
                   "ts_cap": os.environ.get("OGC_PP_TS_CAP", "40"),
                   "w1scale": os.environ.get("OGC_PLACE_W1_SCALE"),
                   "dualwin": os.environ.get("OGC_PP_DUALWIN", "0")},
        "mtrace": dict(M._TRACE),
        "steps": list(PP._STEP_TRACE),
    }
    _bo = os.environ.get("BRIEF_OUT")
    outp = (_bo if (_bo and os.path.isabs(_bo)) else
            os.path.join(V2, _bo) if _bo else os.path.join(V2, "out", "brief38.json"))
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump(out, open(outp, "w"), indent=1)
    n = len(out["steps"]); acc = sum(1 for s in out["steps"] if s["accepted"])
    print(f"DONE prob_{INST}  obj={out['objective']}  z1={out['z1']} z3={out['z3']}  "
          f"wall={wall:.1f}s  steps={n} accepts={acc}  -> {outp}", flush=True)
    # quick per-step rollup to stdout
    agg = {}
    for s in out["steps"]:
        a = agg.setdefault(s["step"], [0, 0, 0.0, 0.0])
        a[0] += 1; a[1] += 1 if s["accepted"] else 0
        a[2] += s["dt"]; a[3] += s["d_obj"]
    for k, (c, ac, dt, dobj) in sorted(agg.items(), key=lambda kv: -kv[1][3]):
        print(f"   {k:12} calls={c:5} acc={ac:4} wall={dt:7.1f}s  dObj={dobj:13,.0f}", flush=True)


if __name__ == "__main__":
    main()
