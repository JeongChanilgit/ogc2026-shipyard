"""_moveall_test.py [inst ...] -- compare moveall ENHANCEMENTS on set2, at two points:
  (a) RAW v2 start,  (b) CONVERGED solution (productive arsenal run ~to plateau first).
Variants: baseline (inline) / +pref(preferred-first+slack) / +destretime(free dest
co-present so dest re-times) / +both.  Each a 60s moveall layer.  Isolated, no long runs.
The key question: does DEST-RETIMING find moves the frozen-dest baseline can't (break
saturation), especially on the converged solution where the inline moveall already ran?
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)

VARIANTS = [
    ("baseline      ", dict(OGC_PP_MOVEALL_PREF="0", OGC_PP_MOVEALL_DESTRETIME="0")),
    ("+pref         ", dict(OGC_PP_MOVEALL_PREF="1", OGC_PP_MOVEALL_DESTRETIME="0")),
    ("+destretime   ", dict(OGC_PP_MOVEALL_PREF="0", OGC_PP_MOVEALL_DESTRETIME="1")),
    ("+both         ", dict(OGC_PP_MOVEALL_PREF="1", OGC_PP_MOVEALL_DESTRETIME="1")),
]


def main():
    os.environ["OGC_NO_V1"] = "1"; os.environ["OGC_PP_TRACE"] = "1"
    # productive arsenal for the converge step (incl. inline moveall); no front/cluster
    for k, v in dict(OGC_PP_DUALWIN="1", OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40",
                     OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1", OGC_PP_PURET="1",
                     OGC_PP_TOSS="1", OGC_PP_KX="16", OGC_PP_FREEALL="1",
                     OGC_PP_FREEALL_MAX="80", OGC_PP_FRONTMOVE="0", OGC_PP_CLUSTER="0").items():
        os.environ[k] = v
    try:
        import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
    except Exception:
        pass
    import myalgorithm_fix as M
    import postproc as PP
    from v3pp import adapter, seed as S
    BASE = "C:/claude-develop/OGC2026"
    insts = sys.argv[1:] or ["38", "33", "30"]
    CONV_TL = float(os.environ.get("CONV_TL", "500"))

    def run_variants(bp, base_obj, where):
        for name, env in VARIANTS:
            for k, v in env.items():
                os.environ[k] = v
            PP._STEP_TRACE.clear()
            cur = {j: list(pl) for j, pl in bp.items()}
            t = time.time()
            _c, o2, na = PP._moveall_pass(data, cur, base_obj, time.monotonic() + 60, 5)
            print(f"    [{where} {name}] Δobj={base_obj - o2:13,.0f}  accepts={na}"
                  f"  final={o2:,.0f}  ({time.time()-t:.0f}s)", flush=True)

    for inst in insts:
        data = json.load(open(f"{BASE}/instances/train/prob_{inst}.json", encoding="utf-8"))
        cache = os.path.join(V2, "out", f"_v2sol_{inst}.json")
        sol0 = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else None
        if sol0 is None:
            os.environ["OGC_NO_PP"] = "1"; os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
            sol0 = M.algorithm(data, 600.0); os.environ.pop("OGC_NO_PP", None)
            json.dump(sol0, open(cache, "w"))
        bp0 = adapter.deserialize(data, sol0); base0 = S.global_eval(data, bp0)
        nt = sum(1 for pl in bp0.values() for p in pl
                 if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))
        print(f"\n##### prob_{inst}: raw obj={base0['obj']:,.0f}  tardy={nt}  bays={len(bp0)}", flush=True)
        run_variants(bp0, base0["obj"], "RAW ")
        conv = PP.postprocess(data, sol0, time.monotonic() + CONV_TL)
        bpc = adapter.deserialize(data, conv); basec = S.global_eval(data, bpc)
        ntc = sum(1 for pl in bpc.values() for p in pl
                  if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))
        print(f"  converged (productive {CONV_TL:.0f}s): obj={basec['obj']:,.0f}  tardy={ntc}", flush=True)
        run_variants(bpc, basec["obj"], "CONV")


if __name__ == "__main__":
    main()
