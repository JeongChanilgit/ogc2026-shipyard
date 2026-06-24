"""_front_methods.py [inst ...]  -- compare cross-bay front-move METHODOLOGIES on a
FIXED v2 start, per set2 problem.  Each methodology gets a 1-minute cross-bay layer
(FRONT_BUDGET=60).  Measures which selection/destination/swap finds the most real
obj-reducing front-moves.  Isolated (single _front_pass on the fixed start) = fast
filter; the winner can then be loop-tested.

Default problems: 38 33 30 (set2).  Caches: out/_v2sol_{inst}.json (built once).
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)

METHODS = [
    ("M1 xext/any",          dict(OGC_PP_FRONT_SEL="xext",    OGC_PP_FRONT_DEST="any",   OGC_PP_FRONT_SWAP="0")),
    ("M2 overlap/any",       dict(OGC_PP_FRONT_SEL="overlap", OGC_PP_FRONT_DEST="any",   OGC_PP_FRONT_SWAP="0")),
    ("M3 overlap/slack",     dict(OGC_PP_FRONT_SEL="overlap", OGC_PP_FRONT_DEST="slack", OGC_PP_FRONT_SWAP="0")),
    ("M4 overlap/slack+swap", dict(OGC_PP_FRONT_SEL="overlap", OGC_PP_FRONT_DEST="slack", OGC_PP_FRONT_SWAP="1")),
]


def main():
    os.environ["OGC_NO_V1"] = "1"
    os.environ["OGC_PP_TRACE"] = "1"
    os.environ["OGC_PP_FRONT_K"] = "20"
    os.environ["OGC_PP_FRONT_TS"] = "5"
    os.environ["OGC_PP_FRONT_BUDGET"] = "60"
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
            os.environ["OGC_NO_PP"] = "1"
            os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
            sol = M.algorithm(data, 600.0)
            os.environ.pop("OGC_NO_PP", None)
            json.dump(sol, open(cache, "w"))
            print(f"[cache] built {cache}", flush=True)
        bp = adapter.deserialize(data, sol)
        base = S.global_eval(data, bp)
        ntardy = sum(1 for pl in bp.values() for p in pl
                     if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))
        print(f"\n##### prob_{inst}: base obj={base['obj']:,.0f}  tardy={ntardy}  bays={len(bp)}",
              flush=True)
        for name, env in METHODS:
            for k, v in env.items():
                os.environ[k] = v
            PP._STEP_TRACE.clear()
            cur = {j: list(pl) for j, pl in bp.items()}
            t = time.time()
            _c, obj2, nacc = PP._front_pass(data, cur, base["obj"], time.monotonic() + 120, 5)
            dt = time.time() - t
            recs = list(PP._STEP_TRACE)
            print(f"  [{name:22}] wall={dt:5.1f}s  Δobj={base['obj']-obj2:13,.0f}"
                  f"  accepts={nacc}/{len(recs)}  final={obj2:,.0f}", flush=True)


if __name__ == "__main__":
    main()
