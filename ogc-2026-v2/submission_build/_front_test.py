"""_front_test.py -- FIX an initial solution (cached v2-only, no PP) for prob_38
and test ONLY the C3-front pass (postproc._front_pass): time + effect, across a few
(FRONT_K, FRONT_BUDGET, FRONT_TS) settings.  No long full-algorithm runs.

  FT_INST   (default 38)    instance
  FT_V2TL   (default 600)   v2 budget when building the cache (one-time)
Cache: out/_v2sol_{INST}.json  (delete to rebuild).
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    os.environ["OGC_NO_V1"] = "1"
    os.environ["OGC_PP_TRACE"] = "1"
    try:
        import psutil
        psutil.Process().cpu_affinity([0, 1, 2, 3])
    except Exception:
        pass

    import myalgorithm_fix as M
    import postproc as PP
    from v3pp import adapter, seed as S
    BASE = "C:/claude-develop/OGC2026"
    INST = os.environ.get("FT_INST", "38")
    data = json.load(open(f"{BASE}/instances/train/prob_{INST}.json", encoding="utf-8"))

    cache = os.path.join(V2, "out", f"_v2sol_{INST}.json")
    if os.path.exists(cache):
        sol = json.load(open(cache, encoding="utf-8"))
        print(f"[cache] loaded FIXED v2 start <- {cache}", flush=True)
    else:
        os.environ["OGC_NO_PP"] = "1"
        os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")   # z1z3 start (winner)
        t = time.time()
        sol = M.algorithm(data, float(os.environ.get("FT_V2TL", "600")))
        os.environ.pop("OGC_NO_PP", None)
        json.dump(sol, open(cache, "w"))
        print(f"[cache] built FIXED v2 start ({time.time()-t:.0f}s) -> {cache}", flush=True)

    bp = adapter.deserialize(data, sol)
    base = S.global_eval(data, bp)
    ntardy = sum(1 for pl in bp.values() for p in pl
                 if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))
    print(f"FIXED start: obj={base['obj']:,.0f}  feasible={base['feasible']}  "
          f"tardy_blocks={ntardy}  bays={len(bp)}", flush=True)
    print("-" * 78, flush=True)

    # few-deep vs shallow-many (does Δobj scale with per-call ts within <1min budget?)
    settings = [(2, 50, 20), (1, 45, 30), (3, 50, 15), (2, 55, 25), (10, 50, 4), (5, 50, 8)]
    for K, bud, fts in settings:
        os.environ["OGC_PP_FRONT_K"] = str(K)
        os.environ["OGC_PP_FRONT_BUDGET"] = str(bud)
        os.environ["OGC_PP_FRONT_TS"] = str(fts)
        PP._STEP_TRACE.clear()
        cur = {j: list(pl) for j, pl in bp.items()}      # fresh copy of FIXED start
        t = time.time()
        _cur2, obj2, nacc = PP._front_pass(data, cur, base["obj"],
                                           time.monotonic() + 300, 5)
        dt = time.time() - t
        recs = list(PP._STEP_TRACE)
        accepted = [r for r in recs if r["accepted"]]
        print(f"[K={K:2} bud={bud} ts={fts}] wall={dt:5.1f}s  Δobj={base['obj']-obj2:13,.0f}"
              f"  accepts={nacc}/{len(recs)}  final={obj2:,.0f}"
              f"  {'<1min OK' if dt < 60 else 'OVER 1min!'}", flush=True)
        for r in accepted:
            print(f"      + bay{r['bay']} Δ{r['d_obj']:,.0f} ({r['dt']:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
