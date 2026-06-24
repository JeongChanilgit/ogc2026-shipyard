# -*- coding: utf-8 -*-
"""z3-RACE probe driver (2026-06-13). Runs run_solver_once on z1=0 high-z3
instances at @600 in two modes (OFF = shipped pipeline / ON = + OGC_Z3_RACE)
and records whether z3-race ARMED and ADOPTED (from OGC_Z3RACE_DEBUG stderr)
plus the obj/z3 delta.

OFF and ON both keep OGC_SUBMIT_V2 default ON -> ON tests z3-race ON TOP of the
real shipped pipeline (the adoption question). ON gets a generous race slice so
we learn whether the lever CAN help; slice tuning comes after.
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_z3probe"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"

TL = float(os.environ.get("PROBE_TL", "600"))
TARGETS = [int(x) for x in os.environ.get("PROBE_PROBS", "16,17,7").split(",")]

ON_ENV = {
    "OGC_Z3_RACE": "1",
    "OGC_Z3RACE_DEBUG": "1",
    "OGC_Z3RACE_MIN_T": "300",
    "OGC_Z3RACE_S": "240",          # generous slice at @600 (default 120)
    "OGC_Z3RACE_RETIME_S": "60",    # probe's winning retime (default 20)
    "OGC_Z3RACE_REPACK_MAX_S": "30",
}

def run(prob, mode):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    outj = OUTD / f"p{prob}_{mode}.json"
    errf = OUTD / f"p{prob}_{mode}.err"
    env = dict(os.environ)
    env.pop("OGC_Z3_RACE", None)
    if mode == "on":
        env.update(ON_ENV)
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(TL),
           "--out", str(outj)]
    t0 = time.time()
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef,
                       env=env, timeout=TL + 240)
    wall = time.time() - t0
    d = json.loads(outj.read_text(encoding="utf-8"))
    err = errf.read_text(encoding="utf-8", errors="ignore")
    z3lines = [ln for ln in err.splitlines() if "[Z3RACE]" in ln]
    realized = re.findall(r"realized z1=(\d+) z3=(\d+) obj=(\d+)", err)
    retimed = re.findall(r"retimed .*?obj=(\S+)", err)
    return {
        "prob": prob, "mode": mode,
        "feasible": d.get("feasible"), "z1": d.get("obj1"),
        "z2": d.get("obj2"), "z3": d.get("obj3"), "obj": d.get("objective"),
        "elapsed": d.get("elapsed"), "wall": round(wall, 1),
        "armed": bool(z3lines), "n_z3lines": len(z3lines),
        "realized": realized[-3:], "retimed": retimed[-3:],
    }

def emit(rows):
    lines = ["# z3-race probe  tl=%g  %s" % (TL, time.strftime("%Y-%m-%d %H:%M")),
             "# prob mode feas z1 z2 z3 obj elapsed armed"]
    by = {}
    for r in rows:
        by.setdefault(r["prob"], {})[r["mode"]] = r
        lines.append("%-4d %-3s feas=%s z1=%s z2=%s z3=%s obj=%s t=%.0f armed=%s%s" % (
            r["prob"], r["mode"], r["feasible"], r["z1"], r["z2"], r["z3"],
            ("%.0f" % r["obj"]) if r["obj"] is not None else "NA",
            r["elapsed"] or 0, r["armed"],
            (" zlines=%d realized=%s" % (r["n_z3lines"], r["realized"])) if r["armed"] else ""))
    lines.append("")
    lines.append("# ON vs OFF (negative dobj = z3-race helps)")
    for prob, mm in sorted(by.items()):
        if "off" in mm and "on" in mm:
            off, on = mm["off"], mm["on"]
            if off["obj"] and on["obj"]:
                dobj = on["obj"] - off["obj"]
                dz3 = (on["z3"] or 0) - (off["z3"] or 0)
                pc = 100.0 * dobj / off["obj"]
                tag = "<-- WIN" if dobj < -1 else ("(race idle)" if not on["armed"] else "(no adopt)")
                lines.append("prob_%-3d  OFF obj=%-9.0f z3=%-5s | ON obj=%-9.0f z3=%-5s armed=%s | dobj=%+.0f (%+.1f%%) dz3=%+.0f %s" % (
                    prob, off["obj"], off["z3"], on["obj"], on["z3"], on["armed"],
                    dobj, pc, dz3, tag))
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")

def main():
    rows = []
    plan = [(p, m) for p in TARGETS for m in ("off", "on")]
    print("PLAN:", plan, "tl=", TL, flush=True)
    for prob, mode in plan:
        print(f">>> prob_{prob} {mode} starting {time.strftime('%H:%M:%S')}", flush=True)
        try:
            r = run(prob, mode)
            rows.append(r)
            print(f"<<< prob_{prob} {mode}: feas={r['feasible']} z1={r['z1']} "
                  f"z3={r['z3']} obj={r['obj']} armed={r['armed']} wall={r['wall']}s", flush=True)
        except Exception as e:
            print(f"!!! prob_{prob} {mode} FAILED: {type(e).__name__}: {e}", flush=True)
        emit(rows)
    print("DONE. summary ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
