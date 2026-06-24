# -*- coding: utf-8 -*-
"""prob_20 z1-close breakthrough probe. prob_20 is +337,757 vs competitor =
64% of our entire @600 gap, almost all of it z1 penalty (z1=12 x w1=26,667 =
320K). Two decisive questions:
  (1) does MORE TIME close z1?  -> @1200, @1800 (eval gives big instances ~30min)
  (2) does the z1-REPAIR LOOP (wired but never fires: reserve default 0) close
      it within the @600 goal budget?  -> OGC_Z1_REPAIR_LOOP=1 + reserve.
Single instance, ordered so the @600 repair signal lands first.
"""
import json, os, re, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_prob20bt"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"
INST = str(ROOT / "instances" / "train" / "prob_20.json")
COMP = 91096

REPAIR = {"OGC_Z1_REPAIR_LOOP": "1", "OGC_Z1_REPAIR_RESERVE_S": "150",
          "OGC_Z1_REPAIR_BAY_CAP": "16"}
REPAIR2 = {"OGC_Z1_REPAIR_LOOP": "1", "OGC_Z1_REPAIR_RESERVE_S": "220",
           "OGC_Z1_REPAIR_BAY_CAP": "24", "OGC_Z1_REPAIR_RESERVE_PCT": "30"}

# (tag, timelimit, extra_env)
VARIANTS = [
    ("rep600",  600,  REPAIR),
    ("def600",  600,  {}),       # paired variance baseline
    ("rep600b", 600,  REPAIR2),
    ("def1200", 1200, {}),
    ("def1800", 1800, {}),
]

def run(tag, tl, extra):
    outj = OUTD / f"{tag}.json"
    errf = OUTD / f"{tag}.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)
    env.update(extra)
    cmd = [PY, RUNNER, INST, "--solver", "our", "--timelimit", str(tl),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env,
                       timeout=tl + 360)
    d = json.loads(outj.read_text(encoding="utf-8"))
    err = errf.read_text(encoding="utf-8", errors="ignore")
    repair_fired = "z1_repair" in err or "z1repair" in err.lower()
    return {"tag": tag, "tl": tl, "feasible": d.get("feasible"),
            "z1": d.get("obj1"), "z2": d.get("obj2"), "z3": d.get("obj3"),
            "obj": d.get("objective"), "elapsed": d.get("elapsed"),
            "repair_fired": repair_fired}

def emit(rows):
    L = ["# prob_20 z1-close breakthrough  comp_obj=%d  %s" % (
        COMP, time.strftime("%Y-%m-%d %H:%M")),
        "# tag      tl    feas  z1   z2     z3    obj         vs_comp     repair_fired"]
    for r in rows:
        o = r["obj"]
        vs = ("%+.0f" % (o - COMP)) if o else "NA"
        win = "WIN" if (o and o < COMP) else ""
        L.append("%-9s %-5d %-5s z1=%-4s z2=%-5s z3=%-5s obj=%-11s %-10s %s %s" % (
            r["tag"], r["tl"], r["feasible"], r["z1"], r["z2"], r["z3"],
            ("%.0f" % o) if o else "NA", vs, win,
            ("repair=YES" if r["repair_fired"] else "")))
    SUMMARY.write_text("\n".join(L), encoding="utf-8")

def main():
    rows = []
    print("prob_20 breakthrough: %s" % [v[0] for v in VARIANTS], flush=True)
    for tag, tl, extra in VARIANTS:
        print(">>> %s tl=%d start %s" % (tag, tl, time.strftime("%H:%M:%S")), flush=True)
        try:
            r = run(tag, tl, extra); rows.append(r)
            print("<<< %s z1=%s z3=%s obj=%s (comp %d) repair=%s t=%s" % (
                tag, r["z1"], r["z3"], r["obj"], COMP, r["repair_fired"],
                r["elapsed"]), flush=True)
        except Exception as e:
            print("!!! %s FAILED %s: %s" % (tag, type(e).__name__, e), flush=True)
        emit(rows)
    print("DONE. ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
