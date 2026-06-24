"""Overnight sequential moveall-lever experiments.  See _overnight_plan.md.

Single process, strictly sequential (never parallel with real runs -> no oversubscribe).
Clean summary -> _overnight_ledger.md (only log() lines).  Verbose CP-SAT spam -> stdout
(redirect to _overnight.log when launching).  Each variant/instance is try/except wrapped
so one failure never kills the night; results are appended per-variant (partial-safe).

Knobs under test (postproc._moveall_pass, all gated, default OFF -> production untouched):
  OGC_PP_MOVEALL_PREF / OGC_PP_MOVEALL_DESTRETIME / OGC_PP_MOVEALL_ORDER(tardy|area|copres)
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
for p in (SB, V2):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---- productive-arsenal env BEFORE imports (postproc _PP_* are import-time constants) ----
os.environ["OGC_NO_V1"] = "1"
os.environ["OGC_PP_TRACE"] = "0"
os.environ.setdefault("OGC_PLACE_W1_SCALE", "1.0")
for k, v in dict(OGC_PP_DUALWIN="1", OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40",
                 OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1", OGC_PP_PURET="1",
                 OGC_PP_TOSS="1", OGC_PP_KX="16", OGC_PP_FREEALL="1",
                 OGC_PP_FREEALL_MAX="80", OGC_PP_FRONTMOVE="0", OGC_PP_CLUSTER="0").items():
    os.environ[k] = v
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import myalgorithm_fix as M          # noqa: E402
import postproc as PP                # noqa: E402
from v3pp import adapter, seed as S  # noqa: E402

BASE = "C:/claude-develop/OGC2026"
LEDGER = os.path.join(SB, "_overnight_ledger.md")
OUT = os.path.join(V2, "out")
CONV_TL = float(os.environ.get("CONV_TL", "500"))
BUILD_TL = float(os.environ.get("BUILD_TL", "400"))
FULL = (os.environ.get("FULL") or "38,33,30").split(",")
GEN = (os.environ.get("GEN") or "29,25").split(",")


def log(s):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print("LEDGER| " + s, flush=True)


def set_knobs(pref=0, dr=0, order="tardy"):
    os.environ["OGC_PP_MOVEALL_PREF"] = str(pref)
    os.environ["OGC_PP_MOVEALL_DESTRETIME"] = str(dr)
    os.environ["OGC_PP_MOVEALL_ORDER"] = order


def tardy_count(data, bp):
    return sum(1 for pl in bp.values() for p in pl
               if p["exit"] > data["blocks"][p["id"]].get("due_date", 0))


def density(data, bp):
    out = []
    for j in sorted(bp):
        pl = bp[j]
        bay = data["bays"][j]; barea = bay["width"] * bay["height"]
        evts = []
        for p in pl:
            a = (p["sh"].max_x - p["sh"].min_x) * (p["sh"].max_y - p["sh"].min_y)
            evts.append((p["entry"], 1, a)); evts.append((p["exit"], -1, -a))
        evts.sort(key=lambda e: (e[0], e[1]))   # exits(-1) before entries(+1) at same t
        ca = cc = pa = pc = 0
        for _t, dc, da in evts:
            ca += da; cc += dc
            pa = max(pa, ca); pc = max(pc, cc)
        z1 = PP._bz1(data, pl)
        util = (pa / barea) if barea else 0.0
        out.append(f"    bay{j}: n={len(pl):3d} z1={z1:9,.0f} peakcnt={int(pc):3d} "
                   f"peakarea={pa:9,.0f} bayarea={barea:9,.0f} util={util:.0%}")
    return out


def run_variant(data, point, bp, base_obj, label, pref=0, dr=0, order="tardy", budget=60.0):
    try:
        set_knobs(pref, dr, order)
        cur = {j: list(pl) for j, pl in bp.items()}
        t = time.time()
        _c, o2, na = PP._moveall_pass(data, cur, base_obj, time.monotonic() + budget, 5)
        log(f"  [{point} {label:14s}] dObj={base_obj - o2:13,.0f}  acc={na:3d}  "
            f"final={o2:14,.0f}  ({time.time()-t:4.0f}s)")
        return _c, o2, na
    except Exception as e:
        log(f"  [{point} {label:14s}] ERROR {e!r}")
        traceback.print_exc()
        return bp, base_obj, 0


def get_raw(inst, data):
    cache = os.path.join(OUT, f"_v2sol_{inst}.json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    log(f"  [build] prob_{inst}: no v2 cache -> M.algorithm(TL={BUILD_TL:.0f})")
    set_knobs(0, 0, "tardy")
    os.environ["OGC_NO_PP"] = "1"
    t = time.time()
    sol0 = M.algorithm(data, BUILD_TL)
    os.environ.pop("OGC_NO_PP", None)
    json.dump(sol0, open(cache, "w"))
    log(f"  [build] prob_{inst} done ({time.time()-t:.0f}s)")
    return sol0


def get_conv(inst, data, sol0):
    cache = os.path.join(OUT, f"_convsol_{inst}.json")
    if os.path.exists(cache):
        log(f"  [converge] prob_{inst}: loaded cache")
        return json.load(open(cache, encoding="utf-8"))
    set_knobs(0, 0, "tardy")
    t = time.time()
    conv = PP.postprocess(data, sol0, time.monotonic() + CONV_TL)
    json.dump(conv, open(cache, "w"))
    log(f"  [converge] prob_{inst}: productive {CONV_TL:.0f}s done ({time.time()-t:.0f}s)")
    return conv


def do_instance(inst, full):
    data = json.load(open(f"{BASE}/instances/train/prob_{inst}.json", encoding="utf-8"))
    sol0 = get_raw(inst, data)
    bp0 = adapter.deserialize(data, sol0); base0 = S.global_eval(data, bp0)
    log(f"\n### prob_{inst} ({'FULL' if full else 'GEN'}): raw obj={base0['obj']:,.0f} "
        f"tardy={tardy_count(data, bp0)} bays={len(bp0)}")
    conv = get_conv(inst, data, sol0)
    bpc = adapter.deserialize(data, conv); basec = S.global_eval(data, bpc)
    log(f"  CONV obj={basec['obj']:,.0f} tardy={tardy_count(data, bpc)}")

    if full:
        # EXP1-RAW (H1/H2 raw signal)
        for lbl, pf, dr in [("baseline", 0, 0), ("+pref", 1, 0),
                            ("+destretime", 0, 1), ("+both", 1, 1)]:
            run_variant(data, "RAW ", bp0, base0["obj"], lbl, pf, dr, "tardy", 60)
        # EXP1-CONV (H1/H2 core: saturation-break)
        for lbl, pf, dr in [("baseline", 0, 0), ("+pref", 1, 0),
                            ("+destretime", 0, 1), ("+both", 1, 1)]:
            run_variant(data, "CONV", bpc, basec["obj"], lbl, pf, dr, "tardy", 60)
        # EXP2-CONV budget sensitivity (H4)
        run_variant(data, "CONV", bpc, basec["obj"], "+dr@120s", 0, 1, "tardy", 120)
        run_variant(data, "CONV", bpc, basec["obj"], "+dr@180s", 0, 1, "tardy", 180)
        # EXP3-CONV ordering (H3)
        run_variant(data, "CONV", bpc, basec["obj"], "order=area", 0, 0, "area", 60)
        run_variant(data, "CONV", bpc, basec["obj"], "order=copres", 0, 0, "copres", 60)
        # EXP4-CONV iterate destretime (H5 loop/saturation)
        cur, obj, cum = bpc, basec["obj"], 0.0
        for it in range(3):
            cur, o2, _na = run_variant(data, "CONV", cur, obj,
                                       f"+dr iter{it+1}", 0, 1, "tardy", 60)
            cum += (obj - o2); obj = o2
        log(f"  [CONV +dr iterate x3 cumulative] dObj={cum:,.0f} final={obj:,.0f}")
    else:
        run_variant(data, "CONV", bpc, basec["obj"], "baseline", 0, 0, "tardy", 60)
        run_variant(data, "CONV", bpc, basec["obj"], "+destretime", 0, 1, "tardy", 60)

    log(f"  [density CONV]")
    for ln in density(data, bpc):
        log(ln)


def main():
    log(f"\n\n# ===== overnight moveall run  {time.strftime('%Y-%m-%d %H:%M')}  "
        f"CONV_TL={CONV_TL:.0f} BUILD_TL={BUILD_TL:.0f} =====")
    log(f"# FULL={FULL}  GEN={GEN}")
    for inst in FULL:
        try:
            do_instance(inst, True)
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    for inst in GEN:
        try:
            do_instance(inst, False)
        except Exception as e:
            log(f"### prob_{inst} FAILED: {e!r}")
            traceback.print_exc()
    log(f"\n# ===== overnight run COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
