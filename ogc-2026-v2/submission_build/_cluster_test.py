"""_cluster_test.py [inst ...] -- isolated C3-CLUSTER test on FIXED v2 starts, per
set2 problem.  Bulk-evict the worst tardy block's x-overlap predecessor cluster ->
other bays + re-time.  Tries cmax in {4,8,12}.  1-minute budget per cluster layer.
Compares against single-block frontmove M2 (overlap) for reference.
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
    insts = sys.argv[1:] or ["38", "33", "30"]

    for inst in insts:
        data = json.load(open(f"{BASE}/instances/train/prob_{inst}.json", encoding="utf-8"))
        cache = os.path.join(V2, "out", f"_v2sol_{inst}.json")
        if os.path.exists(cache):
            sol = json.load(open(cache, encoding="utf-8"))
        else:
            os.environ["OGC_NO_PP"] = "1"; os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
            sol = M.algorithm(data, 600.0); os.environ.pop("OGC_NO_PP", None)
            json.dump(sol, open(cache, "w"))
        bp = adapter.deserialize(data, sol)
        base = S.global_eval(data, bp)
        ntardy = sum(1 for pl in bp.values() for p in pl
                     if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))
        print(f"\n##### prob_{inst}: base obj={base['obj']:,.0f}  tardy={ntardy}  bays={len(bp)}", flush=True)

        # reference: single-block frontmove (overlap)
        for k, v in dict(OGC_PP_FRONT_SEL="overlap", OGC_PP_FRONT_DEST="slack",
                         OGC_PP_FRONT_SWAP="0", OGC_PP_FRONT_K="20",
                         OGC_PP_FRONT_TS="5", OGC_PP_FRONT_BUDGET="60").items():
            os.environ[k] = v
        PP._STEP_TRACE.clear(); cur = {j: list(pl) for j, pl in bp.items()}; t = time.time()
        _c, o2, na = PP._front_pass(data, cur, base["obj"], time.monotonic() + 120, 5)
        print(f"  [single overlap     ] wall={time.time()-t:5.1f}s  Δobj={base['obj']-o2:13,.0f}  accepts={na}", flush=True)

        # cluster, cmax variants
        os.environ["OGC_PP_CLUSTER_TS"] = "4"; os.environ["OGC_PP_CLUSTER_BUDGET"] = "60"
        for cmax in (4, 8, 12):
            os.environ["OGC_PP_CLUSTER_MAX"] = str(cmax)
            PP._STEP_TRACE.clear(); cur = {j: list(pl) for j, pl in bp.items()}; t = time.time()
            _c, o2, na = PP._cluster_pass(data, cur, base["obj"], time.monotonic() + 120, 5)
            dt = time.time() - t
            accepted = [r for r in PP._STEP_TRACE if r["accepted"]]
            print(f"  [cluster cmax={cmax:2}     ] wall={dt:5.1f}s  Δobj={base['obj']-o2:13,.0f}"
                  f"  accepts={na}/{len(PP._STEP_TRACE)}  final={o2:,.0f}", flush=True)
            for r in accepted:
                print(f"        + bay{r['bay']} Δ{r['d_obj']:,.0f}", flush=True)


if __name__ == "__main__":
    main()
