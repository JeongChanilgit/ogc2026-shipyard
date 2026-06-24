"""Session-wrap comparison table: all-20 across tl={100,300,1000}.
Reads results/capture/{final100,final300,final1000}. Prints per-instance
z1/z2/z3/obj at each tl side by side + totals + time-sensitivity flag.
Usage: python notes/_final_table.py
"""
import json
from pathlib import Path

CAP = Path("results/capture")
TAGS = [("100", "final100"), ("300", "final300"), ("1000", "final1000")]


def met(tag, i):
    f = CAP / tag / f"prob_{i}.json"
    if not f.exists():
        return None
    try:
        return json.load(open(f))["met"]
    except Exception:
        return None


def main():
    hdr = f"{'inst':7} |"
    for tl, _ in TAGS:
        hdr += f" {'z1@'+tl:>6} {'obj@'+tl:>11} |"
    hdr += "  obj 1000 vs 100"
    print(hdr)
    print("-" * len(hdr))
    tot = {tl: 0.0 for tl, _ in TAGS}
    feas_all = {tl: True for tl, _ in TAGS}
    for i in range(1, 21):
        row = f"prob_{i:<2} |"
        ms = {}
        for tl, tag in TAGS:
            m = met(tag, i)
            ms[tl] = m
            if m is None:
                row += f" {'--':>6} {'--':>11} |"
                continue
            if not m.get("feas"):
                feas_all[tl] = False
            tot[tl] += m["obj"]
            z1 = m["z1"]; obj = m["obj"]
            mark = "!" if z1 > 0 else " "
            row += f" {z1:>5.0f}{mark} {obj:>11,.0f} |"
        # time sensitivity
        if ms["100"] and ms["1000"] and ms["100"]["obj"]:
            d = 100.0 * (ms["1000"]["obj"] - ms["100"]["obj"]) / ms["100"]["obj"]
            tag = "TIME-GAIN" if d < -2 else ("flat" if abs(d) <= 2 else "WORSE?")
            row += f"  {d:>+6.1f}%  {tag}"
        print(row)
    print("-" * len(hdr))
    trow = f"{'TOTAL':7} |"
    for tl, _ in TAGS:
        trow += f" {'':>6} {tot[tl]:>11,.0f} |"
    print(trow)
    print()
    for tl, _ in TAGS:
        print(f"  tl={tl}: total obj = {tot[tl]:,.0f}   feasible(all,no -1) = {feas_all[tl]}")


if __name__ == "__main__":
    main()
