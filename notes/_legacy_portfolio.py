# -*- coding: utf-8 -*-
"""LEGACY portfolio test: submit_v2 regressed some instances (memory: prob_15
37,814 -> 50,783, +34%). The true portfolio is per-instance best of
{submit_v2 default, legacy (OGC_SUBMIT_V2=0)}. Test legacy on the close losses;
keep min(submit_v2_def, legacy) per instance vs competitor.
def(submit_v2) @600 + competitor embedded from results/_rebaseline600.
"""
import json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_legacyport"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"
TL = float(os.environ.get("LP_TL", "600"))

DEF = {15: 50783, 17: 75492, 12: 114786, 11: 45703, 14: 90963, 3: 76630}
COMP = {15: 48206, 17: 62070, 12: 94110, 11: 31899, 14: 67302, 3: 50642}
TARGETS = [15, 17, 12, 11, 14, 3]

def run(prob):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    outj = OUTD / f"p{prob}_legacy.json"; errf = OUTD / f"p{prob}_legacy.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)
    env["OGC_SUBMIT_V2"] = "0"   # full legacy pipeline
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(TL),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env,
                       timeout=TL + 360)
    d = json.loads(outj.read_text(encoding="utf-8"))
    return {"prob": prob, "feasible": d.get("feasible"), "z1": d.get("obj1"),
            "z3": d.get("obj3"), "obj": d.get("objective"), "elapsed": d.get("elapsed")}

def emit(rows):
    L = ["# legacy-portfolio test  tl=%g  %s" % (TL, time.strftime("%Y-%m-%d %H:%M")),
         "# prob  submit_v2_def  legacy      comp     portfolio_best  verdict"]
    flips = 0
    for r in rows:
        p = r["prob"]; lo = r["obj"]; dv = DEF[p]; c = COMP[p]
        best = min(dv, lo) if lo else dv
        win = best < c
        flip = win and dv >= c  # was loss, now win via portfolio
        if flip: flips += 1
        src = "legacy" if (lo and lo < dv) else "v2"
        L.append("  prob_%-2d  v2=%-9d  legacy=%-9s comp=%-7d  best=%-9d(%s) %s%s" % (
            p, dv, ("%.0f" % lo) if lo else "NA", c, best, src,
            "WIN" if win else "lose", "  <-- FLIP" if flip else ""))
    L.append("")
    L.append("# portfolio flips=%d => total wins = %d/20 (9 base + %d)" % (
        flips, 9 + flips, flips))
    SUMMARY.write_text("\n".join(L), encoding="utf-8")

def main():
    rows = []
    print("legacy portfolio:", TARGETS, "tl=", TL, flush=True)
    for prob in TARGETS:
        print(">>> p%d legacy start %s" % (prob, time.strftime("%H:%M:%S")), flush=True)
        try:
            r = run(prob); rows.append(r)
            lo = r["obj"]; dv = DEF[prob]; c = COMP[prob]
            best = min(dv, lo) if lo else dv
            print("<<< p%d legacy obj=%s (v2 %d comp %d) best=%d %s t=%s" % (
                prob, lo, dv, c, best, "WIN" if best < c else "lose", r["elapsed"]), flush=True)
        except Exception as e:
            print("!!! p%d FAILED %s: %s" % (prob, type(e).__name__, e), flush=True)
        emit(rows)
    print("DONE. ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
