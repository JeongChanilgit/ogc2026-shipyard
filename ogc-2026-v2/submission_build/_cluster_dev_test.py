"""_cluster_dev_test.py [inst ...] -- evaluate the DEVELOPED cluster (v2: window-aware
selection + adaptive size) at TWO points per set2 problem:
  (a) on the RAW v2 start  -> does v2 beat v1 (Δ173K/0/2K)?  does adaptive break the
      saturated prob_33 zero?
  (b) on the CONVERGED solution (productive arsenal run to ~plateau first)  -> the real
      integration question: does cluster add value the high-efficiency passes can't,
      WITHOUT competing for their budget?
Isolated (single _cluster_pass), 1-minute cluster layer.  No long full runs.
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    os.environ["OGC_NO_V1"] = "1"
    os.environ["OGC_PP_TRACE"] = "1"
    # productive arsenal ON; cluster/frontmove OFF (so converge uses only productive)
    for k, v in dict(OGC_PP_DUALWIN="1", OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40",
                     OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1", OGC_PP_PURET="1",
                     OGC_PP_TOSS="1", OGC_PP_KX="16", OGC_PP_FREEALL="1",
                     OGC_PP_FREEALL_MAX="80", OGC_PP_FRONTMOVE="0", OGC_PP_CLUSTER="0").items():
        os.environ[k] = v
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
    CONV_TL = float(os.environ.get("CONV_TL", "500"))
    cl_env = dict(OGC_PP_CLUSTER_MAX="6", OGC_PP_CLUSTER_TS="4",
                  OGC_PP_CLUSTER_BUDGET="60", OGC_PP_CLUSTER_ADAPT="1")

    def _ntardy(bp):
        return sum(1 for pl in bp.values() for p in pl
                   if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))

    def _cluster(bp, base_obj, tag):
        for k, v in cl_env.items():
            os.environ[k] = v
        PP._STEP_TRACE.clear()
        cur = {j: list(pl) for j, pl in bp.items()}
        t = time.time()
        _c, o2, na = PP._cluster_pass(data, cur, base_obj, time.monotonic() + 120, 5)
        print(f"  {tag}: Δobj={base_obj - o2:13,.0f}  accepts={na}/{len(PP._STEP_TRACE)}"
              f"  final={o2:,.0f}  ({time.time()-t:.0f}s)", flush=True)

    for inst in insts:
        data = json.load(open(f"{BASE}/instances/train/prob_{inst}.json", encoding="utf-8"))
        cache = os.path.join(V2, "out", f"_v2sol_{inst}.json")
        if os.path.exists(cache):
            sol0 = json.load(open(cache, encoding="utf-8"))
        else:
            os.environ["OGC_NO_PP"] = "1"; os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
            sol0 = M.algorithm(data, 600.0); os.environ.pop("OGC_NO_PP", None)
            json.dump(sol0, open(cache, "w"))
        bp0 = adapter.deserialize(data, sol0)
        base0 = S.global_eval(data, bp0)
        print(f"\n##### prob_{inst}: raw v2 obj={base0['obj']:,.0f}  tardy={_ntardy(bp0)}  bays={len(bp0)}",
              flush=True)
        _cluster(bp0, base0["obj"], "(a) cluster on RAW      ")

        conv = PP.postprocess(data, sol0, time.monotonic() + CONV_TL)
        bpc = adapter.deserialize(data, conv)
        basec = S.global_eval(data, bpc)
        print(f"  converged (productive {CONV_TL:.0f}s): obj={basec['obj']:,.0f}  tardy={_ntardy(bpc)}",
              flush=True)
        _cluster(bpc, basec["obj"], "(b) cluster on CONVERGED")


if __name__ == "__main__":
    main()
