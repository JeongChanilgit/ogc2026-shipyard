"""Aggregate run_compare_suite summaries across time limits.

Reads several results/<dir>/summary.json produced by tools/run_compare_suite.py
and prints, per time limit, the per-instance objective (baseline vs our) plus the
competition R-nb score (R=2 teams: feasible & better-or-tie = 2, feasible & worse
= 1, infeasible/timeout/crash = -1).

Usage:
    python tools/compare_timelimits.py <label>=<dir> [<label>=<dir> ...]
e.g.
    python tools/compare_timelimits.py 30=results/compare_tl30_20260602 \
        60=results/compare_FINAL_20260602 120=results/compare_tl120_20260602
"""
import json
import sys
import collections

EPS = 1e-9


def load(d):
    s = json.load(open(f"{d}/summary.json"))
    by = collections.defaultdict(dict)
    for j in s["results"]:
        by[j["instance"]][j["solver"]] = j
    return by


def obj(x):
    if not x:
        return None
    if x.get("ok") and x.get("feasible") and x.get("objective") is not None:
        return x["objective"]
    return None


def inst_key(s):
    digits = "".join(c for c in s if c.isdigit())
    return int(digits or 0)


def score(mine, other):
    """R-nb with R=2. mine/other are objectives or None (infeasible)."""
    if mine is None:
        return -1
    nb = 1 if (other is not None and other < mine - EPS) else 0
    return 2 - nb


def main(args):
    labels = []
    data = {}
    for a in args:
        lab, d = a.split("=", 1)
        labels.append(lab)
        data[lab] = load(d)
    instances = sorted({i for lab in labels for i in data[lab]}, key=inst_key)

    for lab in labels:
        by = data[lab]
        print(f"\n================  TIME LIMIT = {lab}s  ================")
        print(f"{'inst':<9}{'baseline':>16}{'our':>16}  {'our/base':>9}  "
              f"{'b_sc':>5}{'o_sc':>5}  result")
        tot_b = tot_o = 0
        wins = ties = worse = onlyus = 0
        for inst in instances:
            b = obj(by.get(inst, {}).get("baseline"))
            o = obj(by.get(inst, {}).get("our"))
            sb, so = score(b, o), score(o, b)
            tot_b += sb
            tot_o += so
            if b is None and o is None:
                res = "both FAIL"
            elif b is None:
                res = "our ONLY feasible"; onlyus += 1
            elif o is None:
                res = "*** our FAIL ***"
            elif o < b - EPS:
                res = "our better"; wins += 1
            elif o > b + EPS:
                res = "our worse"; worse += 1
            else:
                res = "tie"; ties += 1
            ratio = (f"{o / b:.2f}x" if (b and o and b > 0) else "-")
            bs = f"{b:,.0f}" if b is not None else "FAIL"
            os_ = f"{o:,.0f}" if o is not None else "FAIL"
            print(f"{inst:<9}{bs:>16}{os_:>16}  {ratio:>9}  {sb:>5}{so:>5}  {res}")
        nb_ok = sum(1 for i in instances if obj(by.get(i, {}).get("baseline")) is not None)
        no_ok = sum(1 for i in instances if obj(by.get(i, {}).get("our")) is not None)
        print(f"{'-'*72}")
        print(f"{'TOTAL SCORE':<9}{'':>16}{'':>16}  {'':>9}  {tot_b:>5}{tot_o:>5}  "
              f"(our better={wins} tie={ties} worse={worse} only-feasible={onlyus})")
        print(f"{'feasible':<9}{'baseline '+str(nb_ok)+'/'+str(len(instances)):>32}"
              f"{'our '+str(no_ok)+'/'+str(len(instances)):>27}")

    # Trend summary
    print(f"\n================  SCORE TREND  ================")
    print(f"{'timelimit':<12}{'baseline':>10}{'our':>10}{'max(2N)':>10}")
    for lab in labels:
        by = data[lab]
        tb = sum(score(obj(by.get(i, {}).get("baseline")),
                       obj(by.get(i, {}).get("our"))) for i in instances)
        to = sum(score(obj(by.get(i, {}).get("our")),
                       obj(by.get(i, {}).get("baseline"))) for i in instances)
        print(f"{lab+'s':<12}{tb:>10}{to:>10}{2*len(instances):>10}")


if __name__ == "__main__":
    main(sys.argv[1:])
