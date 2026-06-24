# -*- coding: utf-8 -*-
"""WIN-13 campaign: portfolio race to flip 4 close losses (9 -> 13 wins).
Per target loss, run the candidate configs @600 ON TOP of submit_v2; the
per-instance winner = min obj over {default, raster, fbX}; a flip = winner < comp.
Levers: raster floor (FF_PRIMARY off) + aggressive Front B uncap (the proven
z3 cutter, memory -18.6%). z3-race is dead (excluded).
def @600 baselines + competitor embedded from results/_rebaseline600.
"""
import json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_win13"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"
TL = float(os.environ.get("WIN13_TL", "600"))

DEF = {15: 50783, 12: 114786, 17: 75492, 11: 45703, 14: 90963, 6: 99920, 3: 76630}
COMP = {15: 48206, 12: 94110, 17: 62070, 11: 31899, 14: 67302, 6: 72400, 3: 50642}

RASTER = {"OGC_FF_PRIMARY": "0", "OGC_FLOOR_RASTER": "1", "OGC_FAST_FLOOR_POS_K": "3"}
FBX = {"OGC_FRONTB_MULTI": "2", "OGC_FRONTB_REDECODE": "1", "OGC_FRONTB_REDECODE_K": "4",
       "OGC_FRONTB_TRIES": "60", "OGC_FRONTB_SWAP_TOP": "80", "OGC_FRONTB_STALL": "4"}
RASTERFB = dict(RASTER, **FBX)

# (prob, config_tag, env) -- easiest/highest-EV first
PLAN = [
    (15, "raster", RASTER), (15, "fbX", FBX),
    (17, "raster", RASTER), (17, "fbX", FBX),
    (12, "fbX", FBX),       (12, "rasterfb", RASTERFB),
    (11, "fbX", FBX),       (11, "rasterfb", RASTERFB),
    (14, "fbX", FBX),
]

def run(prob, tag, extra):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    name = f"p{prob}_{tag}"
    outj = OUTD / f"{name}.json"; errf = OUTD / f"{name}.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)
    env.update(extra)
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(TL),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env,
                       timeout=TL + 360)
    d = json.loads(outj.read_text(encoding="utf-8"))
    return {"prob": prob, "tag": tag, "feasible": d.get("feasible"),
            "z1": d.get("obj1"), "z3": d.get("obj3"), "obj": d.get("objective"),
            "elapsed": d.get("elapsed")}

def emit(rows):
    L = ["# WIN-13 campaign  tl=%g  %s" % (TL, time.strftime("%Y-%m-%d %H:%M")),
         "# per-run results (config ON TOP of submit_v2 default):"]
    best = {}  # prob -> best obj (start from default)
    for p in DEF:
        best[p] = DEF[p]
    for r in rows:
        o = r["obj"]; p = r["prob"]; c = COMP[p]
        tag = ""
        if o and o < DEF[p] - 1: tag += "beats-def "
        if o and o < c: tag += "WIN"
        if o and o < best[p]:
            best[p] = o
        L.append("  p%-2d %-9s z1=%-4s z3=%-5s obj=%-10s (def %d comp %d) %s" % (
            p, r["tag"], r["z1"], r["z3"], ("%.0f" % o) if o else "NA",
            DEF[p], c, tag))
    L.append("")
    L.append("# PORTFOLIO BEST per instance (min over default + tested configs):")
    flips = 0
    base_wins = 9  # current confirmed wins (prob 1,2,5,7,8,9,10,16,19)
    for p in sorted(DEF):
        c = COMP[p]; b = best[p]
        w = b < c
        if w and DEF[p] >= c:  # was a loss, now flipped
            flips += 1
        L.append("  prob_%-2d best=%-10.0f comp=%-7d %s%s" % (
            p, b, c, "WIN" if w else "lose",
            "  <-- FLIP" if (w and DEF[p] >= c) else ""))
    L.append("")
    L.append("# flips=%d  => projected total wins = %d/20 (target 13)" % (
        flips, base_wins + flips))
    SUMMARY.write_text("\n".join(L), encoding="utf-8")

def main():
    rows = []
    print("WIN-13 campaign:", [(p, t) for p, t, _ in PLAN], flush=True)
    for prob, tag, extra in PLAN:
        print(">>> p%d_%s start %s" % (prob, tag, time.strftime("%H:%M:%S")), flush=True)
        try:
            r = run(prob, tag, extra); rows.append(r)
            o = r["obj"]; c = COMP[prob]
            print("<<< p%d_%s z1=%s z3=%s obj=%s (def %d comp %d) %s t=%s" % (
                prob, tag, r["z1"], r["z3"], o, DEF[prob], c,
                "WIN" if (o and o < c) else "", r["elapsed"]), flush=True)
        except Exception as e:
            print("!!! p%d_%s FAILED %s: %s" % (prob, tag, type(e).__name__, e), flush=True)
        emit(rows)
    print("DONE. ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
