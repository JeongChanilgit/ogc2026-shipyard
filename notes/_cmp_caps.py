"""Compare two capture tags per-instance: obj/z1/z2/z3 delta + totals.
Usage: python notes/_cmp_caps.py <base_tag> <new_tag> [inst1,inst2,...]
Reads results/capture/<tag>/<inst>.json {met:{...}}. Flags regressions
(new obj > base obj) and wins. Token-light: prints only numbers.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "results" / "capture"
ALL = [f"prob_{i}" for i in range(1, 21)]


def met(tag, inst):
    f = CAP / tag / f"{inst}.json"
    if not f.exists():
        return None
    try:
        return json.load(open(f))["met"]
    except Exception:
        return None


def main():
    base, new = sys.argv[1], sys.argv[2]
    insts = (sys.argv[3].split(",") if len(sys.argv) > 3 else ALL)
    print(f"BASE={base}  NEW={new}\n")
    print(f"{'inst':9} | {'z1':>4}->{'z1':>4} | {'z3':>5}->{'z3':>5} | "
          f"{'objBASE':>10} {'objNEW':>10} {'d%':>7}  flag")
    print("-" * 84)
    tb = tn = 0.0
    wins = reg = 0
    for i in insts:
        mb, mn = met(base, i), met(new, i)
        if not mb or not mn:
            print(f"{i:9} | missing ({'base' if not mb else ''}{'new' if not mn else ''})")
            continue
        ob, on = mb["obj"], mn["obj"]
        tb += ob; tn += on
        d = 100.0 * (on - ob) / ob if ob else 0.0
        flag = ""
        if on < ob - 1e-6:
            flag = f"WIN {ob-on:,.0f}"; wins += 1
        elif on > ob + 1e-6:
            flag = f"REGRESS +{on-ob:,.0f}"; reg += 1
        z1b, z1n = mb["z1"], mn["z1"]
        z1flag = "  z1!" if z1n > z1b else ""
        print(f"{i:9} | {z1b:>4.0f}->{z1n:>4.0f} | {mb['z3']:>5.0f}->{mn['z3']:>5.0f} | "
              f"{ob:>10,.0f} {on:>10,.0f} {d:>6.1f}%  {flag}{z1flag}")
    print("-" * 84)
    print(f"TOTAL obj  BASE={tb:,.0f}  NEW={tn:,.0f}  "
          f"delta={tn-tb:+,.0f} ({100*(tn-tb)/tb:+.2f}%)")
    print(f"wins={wins}  regress={reg}")


if __name__ == "__main__":
    main()
