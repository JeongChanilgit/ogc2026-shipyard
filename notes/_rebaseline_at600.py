# -*- coding: utf-8 -*-
"""Full-20 @600 RE-BASELINE of the CURRENT shipped pipeline (submit_v2 default,
z3-race OFF). The 2026-06-11 'base600' table that the progress report used was a
pre-submit_v2 'base' config; the probe showed the real pipeline is much stronger
(prob_16/7 are actually WINS, not losses). This run gives the TRUE current
standing vs the competitor and the TRUE remaining losses to target.

Single mode = exact shipped default (no OGC_* overrides). Sequential @600.
Writes incremental summary so partial progress is usable.
"""
import json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")
OUTD = ROOT / "results" / "_rebaseline600"
OUTD.mkdir(parents=True, exist_ok=True)
SUMMARY = OUTD / "summary.txt"
TL = float(os.environ.get("RB_TL", "600"))

# competitor official obj @600 (notes/competitor-2026-06-11.json)
COMP = {1:9785,2:6624,3:50642,4:16917,5:70580,6:72400,7:86021,8:12908,9:80034,
        10:98957,11:31899,12:94110,13:76685,14:67302,15:48206,16:50047,17:62070,
        18:40206,19:72951,20:91096}

# run order: known losses / high-value first so the decisive deltas land early
ORDER = [17,13,20,3,4,5,6,11,12,14,18,19,16,7,9,10,1,2,8,15]

def run(prob):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    outj = OUTD / f"p{prob}.json"
    errf = OUTD / f"p{prob}.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)           # exact shipped default
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(TL),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef,
                       env=env, timeout=TL + 300)
    d = json.loads(outj.read_text(encoding="utf-8"))
    return {"prob": prob, "feasible": d.get("feasible"), "z1": d.get("obj1"),
            "z2": d.get("obj2"), "z3": d.get("obj3"), "obj": d.get("objective"),
            "w1": d.get("w1"), "w2": d.get("w2"), "w3": d.get("w3"),
            "elapsed": d.get("elapsed")}

def emit(rows):
    L = ["# full-20 re-baseline (current shipped default)  tl=%g  %s" % (
        TL, time.strftime("%Y-%m-%d %H:%M")),
        "# prob  ours_obj   comp_obj   verdict   z1  z2     z3    (w1/w2/w3)  t"]
    wins = losses = ties = z1zero = feas = 0
    tot_ours = tot_comp = 0
    for r in sorted(rows, key=lambda x: x["prob"]):
        p = r["prob"]; c = COMP[p]; o = r["obj"]
        if o is None or not r["feasible"]:
            L.append("%-5d  INFEASIBLE/None  comp=%d" % (p, c)); continue
        feas += 1
        if (r["z1"] or 0) <= 1e-9: z1zero += 1
        v = "WIN " if o < c - 1e-9 else ("tie " if abs(o-c) <= 1 else "lose")
        if v == "WIN ": wins += 1
        elif v == "lose": losses += 1
        else: ties += 1
        tot_ours += o; tot_comp += c
        L.append("%-5d  %-9.0f  %-9d  %s    z1=%-3s z2=%-5s z3=%-5s (%s/%s/%s) t=%.0f" % (
            p, o, c, v, r["z1"], r["z2"], r["z3"], r["w1"], r["w2"], r["w3"],
            r["elapsed"] or 0))
    done = wins + losses + ties
    L.append("")
    L.append("# TOTALS (measured %d/20): WIN=%d  lose=%d  tie=%d  | z1=0: %d/%d  feas: %d/%d" % (
        done, wins, losses, ties, z1zero, done, feas, done))
    if done:
        L.append("# sum ours=%.0f  sum comp=%.0f  (measured subset)" % (tot_ours, tot_comp))
        # remaining losses ranked by gap
        gl = sorted(((r["prob"], r["obj"]-COMP[r["prob"]]) for r in rows
                     if r["obj"] and r["feasible"] and r["obj"] > COMP[r["prob"]]+1),
                    key=lambda x: -x[1])
        if gl:
            L.append("# remaining losses by gap: " + ", ".join(
                "prob_%d(+%.0f)" % (p, g) for p, g in gl))
    SUMMARY.write_text("\n".join(L), encoding="utf-8")

def main():
    rows = []
    print("REBASELINE full-20 @%.0f order=%s" % (TL, ORDER), flush=True)
    for prob in ORDER:
        print(">>> prob_%d start %s" % (prob, time.strftime("%H:%M:%S")), flush=True)
        try:
            r = run(prob); rows.append(r)
            c = COMP[prob]; o = r["obj"]
            v = "WIN" if (o and o < c) else "lose"
            print("<<< prob_%d obj=%s comp=%d %s z1=%s z3=%s t=%s" % (
                prob, o, c, v, r["z1"], r["z3"], r["elapsed"]), flush=True)
        except Exception as e:
            print("!!! prob_%d FAILED %s: %s" % (prob, type(e).__name__, e), flush=True)
        emit(rows)
    print("DONE. ->", SUMMARY, flush=True)

if __name__ == "__main__":
    main()
