# -*- coding: utf-8 -*-
import json, glob, os, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def load(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception as e: return {"_err": str(e)}

def fields(d):
    if not isinstance(d, dict):
        return f"<{type(d).__name__} len {len(d) if hasattr(d,'__len__') else '?'}>"
    out = {}
    for k in ("instance","label","tag","timelimit","feasible","stage","obj1","obj2",
              "obj3","objective","Z1","z1","elapsed","wall","n_violations"):
        if k in d: out[k] = d[k]
    if not out:
        out["_keys"] = list(d.keys())[:12]
    return out

def show(p):
    if not os.path.exists(p): print(f"  (missing) {p}"); return
    print(f"  [{os.path.getsize(p):>8}B] {p}\n        {fields(load(p))}")

print("== prob_6 time-sweep ==")
for p in ["results/tlsweep_p6_120.json","results/tlsweep_p6_300.json",
          "results/tlsweep_p6_600.json","results/tl600_p6_base.json"]: show(p)
print("== prob_20 @600 ==")
show("results/tl600_p20_coexit.json")
print("== prob_6 clean decode (Z1 1693->21) ==")
for p in ["results/clean_decode_prob6_fixed.json","results/clean_decode_prob6.json",
          "results/clean_decode_prob6_tiesep.json"]: show(p)
print("== crane re-decode prob_14 @180 ==")
show("results/crane_redecode_move_prob14_180.json")
print("== aggregates ==")
for p in ["results/z1_exp_A/results.json","results/z1_exp_B/results.json",
          "results/z1_exp_coexit/results.json"]: show(p)
print("== score files (z1_exp_coexit base vs coexit) ==")
for p in sorted(glob.glob("results/z1_exp_coexit/score_*.json")): show(p)
print("== z1_objective_safe_compare ==")
for p in sorted(glob.glob("results/**/z1_objective_safe*/*.json", recursive=True)): show(p)
