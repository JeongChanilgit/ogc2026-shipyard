"""_v2v3_viz.py i [i ...]  -- run v2+v3 (OGC_NO_V1=1) on the given set1 instances
and render each with the interactive Three.js viewer (ogc-2026-v2/viz.py).

NOTE: all execution is under __main__ so that worker processes spawned by
unified_greedy / postproc (Windows spawn re-imports __main__) do NOT re-run the
whole viz loop (that caused nested, contaminated runs).

env: OGC_PLACE_W1_SCALE (default 0.4), VIZTL (default 180), + standard v2+v3 knobs.
"""
import sys
import os

SB = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(SB)
for _p in (SB, V2):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    import json
    import subprocess
    BASE = "C:/claude-develop/OGC2026"
    os.environ["OGC_NO_V1"] = "1"
    os.environ.setdefault("OGC_PLACE_W1_SCALE", "0.4")
    os.environ.setdefault("OGC_PP_WRONGBAY", "1")
    os.environ.setdefault("OGC_TOSS", "1")
    os.environ.setdefault("OGC_FIXOPT", "1")
    os.environ.setdefault("OGC_PP_KX", "16")
    os.environ.setdefault("OGC_PP_FREEALL", "1")
    os.environ.setdefault("OGC_PP_MOVEALL", "1")
    os.environ.setdefault("OGC_V2_CAP", "110")

    import myalgorithm_fix as M
    import utils
    from viz import trace_from_solution, write_viz

    TL = float(os.environ.get("VIZTL", "180"))
    ids = [int(a) for a in sys.argv[1:]] or [20, 13, 14]
    out_html = []
    for i in ids:
        data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
        sol = M.algorithm(data, TL)
        r = utils.check_feasibility(data, sol)
        obj = r.get("objective")
        name = (f"prob_{i}  z1={r.get('obj1')} z3={r.get('obj3')} obj={obj:,.0f}"
                if obj is not None else f"prob_{i} INFEASIBLE")
        trace = trace_from_solution(data, sol, instance_name=name)
        out = os.path.join(V2, "out", f"viz_v2v3_prob_{i}.html")
        write_viz(trace, out)
        out_html.append(out)
        print(f"wrote {out}  z1={r.get('obj1')} z3={r.get('obj3')} obj={obj}", flush=True)

    for o in out_html:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "", o], shell=False)


if __name__ == "__main__":
    main()
