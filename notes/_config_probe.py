# -*- coding: utf-8 -*-
"""Final lever test: config PORTFOLIO vs submit_v2 default, on the two failure
modes. The raster/pos_k floor knobs live in the `not _ff_primary` branch
(myalgorithm.py:5825), so submit_v2 (FF_PRIMARY=1) skips them -> must override.
  - prob_20 (structural z1=7): does more position search (pos_k=5) help?
  - prob_18 / prob_13 (z3 losses): does the raster floor path cut z3?
def @600 baselines (results/_rebaseline600 + _prob20bt): prob_20~303392(z1=7),
prob_18 98240, prob_13 113500. competitor: 20=91096,18=40206,13=76685.
"""
import json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_configprobe"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"

DEF = {20: (303392, 7, 847), 18: (98240, 0, 704), 13: (113500, 0, 805)}  # def obj,z1,z3
COMP = {20: 91096, 18: 40206, 13: 76685}

RASTER = {"OGC_FF_PRIMARY": "0", "OGC_FLOOR_RASTER": "1", "OGC_FAST_FLOOR_POS_K": "3"}
# (tag, prob, tl, env)
VARIANTS = [
    ("p20_ffk5",   20, 600, {"OGC_FAST_FLOOR_POS_K": "5"}),
    ("p18_raster", 18, 600, RASTER),
    ("p13_raster", 13, 600, RASTER),
    ("p20_raster", 20, 600, RASTER),
]

def run(tag, prob, tl, extra):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    outj = OUTD / f"{tag}.json"; errf = OUTD / f"{tag}.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)
    env.update(extra)
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(tl),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env,
                       timeout=tl + 360)
    d = json.loads(outj.read_text(encoding="utf-8"))
    return {"tag": tag, "prob": prob, "feasible": d.get("feasible"),
            "z1": d.get("obj1"), "z2": d.get("obj2"), "z3": d.get("obj3"),
            "obj": d.get("objective"), "elapsed": d.get("elapsed")}

def emit(rows):
    L = ["# config-portfolio probe  %s" % time.strftime("%Y-%m-%d %H:%M"),
         "# tag        prob feas z1   z3    obj        def_obj    comp    vs_def    vs_comp"]
    for r in rows:
        p = r["prob"]; o = r["obj"]; dobj = DEF[p][0]; c = COMP[p]
        vd = ("%+.0f" % (o - dobj)) if o else "NA"
        vc = ("%+.0f" % (o - c)) if o else "NA"
        tag = ""
        if o and o < dobj - 1: tag = "<-- beats def"
        if o and o < c: tag += " WIN"
        L.append("%-11s %-4d %-4s z1=%-4s z3=%-5s obj=%-10s def=%-10d comp=%-7d %-9s %-9s %s" % (
            r["tag"], p, r["feasible"], r["z1"], r["z3"],
            ("%.0f" % o) if o else "NA", dobj, c, vd, vc, tag))
    SUMMARY.write_text("\n".join(L), encoding="utf-8")

def main():
    rows = []
    print("config probe:", [v[0] for v in VARIANTS], flush=True)
    for tag, prob, tl, extra in VARIANTS:
        print(">>> %s start %s" % (tag, time.strftime("%H:%M:%S")), flush=True)
        try:
            r = run(tag, prob, tl, extra); rows.append(r)
            print("<<< %s z1=%s z3=%s obj=%s (def %d comp %d) t=%s" % (
                tag, r["z1"], r["z3"], r["obj"], DEF[prob][0], COMP[prob],
                r["elapsed"]), flush=True)
        except Exception as e:
            print("!!! %s FAILED %s: %s" % (tag, type(e).__name__, e), flush=True)
        emit(rows)
    print("DONE. ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
