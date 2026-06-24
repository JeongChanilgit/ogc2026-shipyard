"""Ad-hoc: parse a run_compare_suite summary.json into a baseline-vs-ours table."""
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
s = json.load(open(summary_path, encoding="utf-8"))

by = {}  # instance -> {solver -> row}
for r in s["results"]:
    by.setdefault(r["instance"], {})[r["solver"]] = r


def inst_key(name):
    # sort prob_N numerically
    import re
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)) if m else 0, name)


print(f"timelimit={s['timelimit']}s  solvers={s['solvers']}  n_instances={s['n_instances']}")
print()
hdr = (f"{'instance':<10} {'n':>4} {'m':>3} "
       f"{'base_feas':>9} {'base_obj':>14} "
       f"{'our_feas':>8} {'our_obj':>14} "
       f"{'delta_%':>9} {'winner':>7}")
print(hdr)
print("-" * len(hdr))

n_base_feas = n_our_feas = 0
n_our_better = n_base_better = n_tie = 0
sum_improv = 0.0
n_improv = 0

for inst in sorted(by, key=inst_key):
    b = by[inst].get("baseline")
    o = by[inst].get("our")
    bn = b["n_blocks"] if b else (o["n_blocks"] if o else 0)
    bm = b["n_bays"] if b else (o["n_bays"] if o else 0)
    bf = b and b.get("feasible")
    of = o and o.get("feasible")
    bobj = b.get("objective") if (b and bf) else None
    oobj = o.get("objective") if (o and of) else None
    if bf:
        n_base_feas += 1
    if of:
        n_our_feas += 1
    delta = ""
    winner = ""
    if bobj is not None and oobj is not None:
        d = (bobj - oobj) / bobj * 100 if abs(bobj) > 1e-9 else 0.0
        delta = f"{d:+.2f}"
        sum_improv += d
        n_improv += 1
        if oobj < bobj - 1e-6:
            winner = "OURS"
            n_our_better += 1
        elif oobj > bobj + 1e-6:
            winner = "base"
            n_base_better += 1
        else:
            winner = "tie"
            n_tie += 1
    elif of and not bf:
        winner = "OURS*"
    elif bf and not of:
        winner = "base*"

    def fo(v):
        return f"{v:,.0f}" if v is not None else "INFEAS"
    print(f"{inst:<10} {bn:>4} {bm:>3} "
          f"{str(bool(bf)):>9} {fo(bobj):>14} "
          f"{str(bool(of)):>8} {fo(oobj):>14} "
          f"{delta:>9} {winner:>7}")

print("-" * len(hdr))
print(f"feasible:  baseline {n_base_feas}/{s['n_instances']}   ours {n_our_feas}/{s['n_instances']}")
print(f"head-to-head (both feasible): OURS better {n_our_better}, baseline better {n_base_better}, tie {n_tie}")
if n_improv:
    print(f"mean objective improvement (ours vs base): {sum_improv/n_improv:+.2f}%  (positive = ours lower/better)")
