# -*- coding: utf-8 -*-
"""Rebuild measurement harness: run the solver across instances at multiple
time limits (default 100 & 300) and report objective + competitor win-count per
tl, plus the @100-vs-@300 convergence ratio. This is the gate for the structural
rebuild: ≤100s should give a reasonable obj, ≤300s the best.

Usage:
  python tools/eval_targets.py [--tls 100,300] [--probs all|1,5,20]
                               [--env OGC_REBUILD=1,OGC_FOO=2] [--out DIR]
Env flags after --env are applied to the solver subprocess (config under test).
Records results/<out>/p<prob>_<tl>.json + summary.txt (incremental).
"""
import argparse, json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
RUNNER = str(ROOT / "tools" / "run_solver_once.py")

# competitor official obj @600 (notes/competitor-2026-06-11.json)
COMP = {1:9785,2:6624,3:50642,4:16917,5:70580,6:72400,7:86021,8:12908,9:80034,
        10:98957,11:31899,12:94110,13:76685,14:67302,15:48206,16:50047,17:62070,
        18:40206,19:72951,20:91096}

def run(prob, tl, env_extra, outd):
    inst = str(ROOT / "instances" / "train" / f"prob_{prob}.json")
    outj = outd / f"p{prob}_{int(tl)}.json"; errf = outd / f"p{prob}_{int(tl)}.err"
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("OGC_"):
            env.pop(k)
    env.update(env_extra)
    cmd = [PY, RUNNER, inst, "--solver", "our", "--timelimit", str(tl),
           "--out", str(outj)]
    with open(errf, "w", encoding="utf-8") as ef:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=ef, env=env,
                       timeout=tl + 360)
    d = json.loads(outj.read_text(encoding="utf-8"))
    return {"prob": prob, "tl": tl, "feasible": d.get("feasible"),
            "z1": d.get("obj1"), "z2": d.get("obj2"), "z3": d.get("obj3"),
            "obj": d.get("objective"), "elapsed": d.get("elapsed")}

def emit(rows, tls, summary):
    by = {}
    for r in rows:
        by.setdefault(r["prob"], {})[r["tl"]] = r
    L = ["# eval_targets  tls=%s  %s" % (tls, time.strftime("%Y-%m-%d %H:%M")),
         "# per-instance obj by tl (W=win vs competitor):"]
    hdr = "# prob  " + "  ".join("@%-9d" % t for t in tls) + "  comp       conv@%d/%d" % (
        tls[0], tls[-1]) if len(tls) >= 2 else "# prob  obj  comp"
    L.append(hdr)
    wins = {t: 0 for t in tls}; feas = {t: 0 for t in tls}; tot = {t: 0 for t in tls}
    for p in sorted(by):
        cells = []
        for t in tls:
            r = by[p].get(t)
            if r and r["obj"] and r["feasible"]:
                feas[t] += 1; tot[t] += r["obj"]
                w = r["obj"] < COMP[p]
                if w: wins[t] += 1
                cells.append("%-9.0f%s" % (r["obj"], "W" if w else " "))
            else:
                cells.append("NA        ")
        conv = ""
        if len(tls) >= 2:
            a = by[p].get(tls[0], {}).get("obj"); b = by[p].get(tls[-1], {}).get("obj")
            if a and b and b > 0:
                conv = "%.2fx" % (a / b)
        L.append("  p%-3d  %s  %-9d  %s" % (p, "  ".join(cells), COMP[p], conv))
    L.append("")
    for t in tls:
        L.append("# @%-4d : WIN %2d/%d  feasible %2d  sum_obj %.0f" % (
            t, wins[t], feas[t], feas[t], tot[t]))
    if len(tls) >= 2:
        a, b = tls[0], tls[-1]
        if tot[b] > 0:
            L.append("# @%d/@%d obj ratio = %.3f  (closer to 1.0 = @%d already near-best)" % (
                a, b, tot[a] / tot[b] if tot[b] else 0, a))
    summary.write_text("\n".join(L), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tls", default="100,300")
    ap.add_argument("--probs", default="all")
    ap.add_argument("--env", default="")
    ap.add_argument("--out", default="_eval")
    a = ap.parse_args()
    tls = [float(x) for x in a.tls.split(",")]
    probs = list(range(1, 21)) if a.probs == "all" else [int(x) for x in a.probs.split(",")]
    env_extra = {}
    for kv in a.env.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1); env_extra[k] = v
    outd = ROOT / "results" / a.out
    outd.mkdir(parents=True, exist_ok=True)
    summary = outd / "summary.txt"
    rows = []
    print("eval: probs=%s tls=%s env=%s -> %s" % (probs, tls, env_extra, outd), flush=True)
    # tl-major so partial summaries compare apples-to-apples per tl
    for tl in tls:
        for p in probs:
            print(">>> p%d @%g %s" % (p, tl, time.strftime("%H:%M:%S")), flush=True)
            try:
                r = run(p, tl, env_extra, outd); rows.append(r)
                print("<<< p%d @%g obj=%s z1=%s z3=%s (comp %d) %s" % (
                    p, tl, r["obj"], r["z1"], r["z3"], COMP[p],
                    "WIN" if (r["obj"] and r["obj"] < COMP[p]) else ""), flush=True)
            except Exception as e:
                print("!!! p%d @%g FAILED %s: %s" % (p, tl, type(e).__name__, e), flush=True)
            emit(rows, tls, summary)
    print("DONE. ->", summary, flush=True)

if __name__ == "__main__":
    main()
