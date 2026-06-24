"""Paired full-20 gate comparison: new tag pair vs baseline tag pair.

Usage: python notes/_gate_compare.py gate_rc_r1 gate_rc_r2 gate_v2_r1 gate_v2_r2
Prints per-instance paired-worst z1 / best obj for both pairs + verdict lines.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "results" / "capture"


def load(tag):
    out = {}
    for i in range(1, 21):
        f = CAP / tag / f"prob_{i}.json"
        if f.exists():
            try:
                out[f"prob_{i}"] = json.load(open(f))["met"]
            except Exception:
                out[f"prob_{i}"] = None
        else:
            out[f"prob_{i}"] = None
    return out


def main():
    b1, b2, n1, n2 = sys.argv[1:5]
    B1, B2, N1, N2 = load(b1), load(b2), load(n1), load(n2)
    hdr = (f"{'inst':9s} {'base z1(r1/r2)':>15s} {'new z1(r1/r2)':>15s} "
           f"{'base obj best':>14s} {'new obj best':>14s} {'d_obj':>10s}  flag")
    print(hdr)
    base_zero = new_zero = 0
    tot_b = tot_n = 0.0
    regress = []
    for i in range(1, 21):
        k = f"prob_{i}"
        vb1, vb2, vn1, vn2 = B1[k], B2[k], N1[k], N2[k]
        if not all([vb1, vb2, vn1, vn2]):
            print(f"{k:9s}  MISSING DATA b={vb1 is not None},{vb2 is not None}"
                  f" n={vn1 is not None},{vn2 is not None}")
            continue
        bz = max(vb1["z1"], vb2["z1"])
        nz = max(vn1["z1"], vn2["z1"])
        bo = min(vb1["obj"], vb2["obj"])
        no = min(vn1["obj"], vn2["obj"])
        feas = all(v["feas"] for v in (vn1, vn2))
        if bz <= 1e-9:
            base_zero += 1
        if nz <= 1e-9:
            new_zero += 1
        tot_b += bo
        tot_n += no
        flag = ""
        if not feas:
            flag = "INFEAS!"
        elif nz > bz + 1e-9:
            flag = "Z1-REGRESS"
            regress.append(k)
        elif no > bo * 1.05 + 1e-9:
            flag = "obj-regress>5%"
            regress.append(k)
        elif nz < bz - 1e-9:
            flag = "z1 IMPROVED"
        print(f"{k:9s} {vb1['z1']:>7.0f}/{vb2['z1']:<7.0f} "
              f"{vn1['z1']:>7.0f}/{vn2['z1']:<7.0f} "
              f"{bo:>14,.0f} {no:>14,.0f} {no-bo:>+10,.0f}  {flag}")
    print(f"\npaired z1=0: base {base_zero}/20 -> new {new_zero}/20")
    print(f"total obj (best-of-pair sum): {tot_b:,.0f} -> {tot_n:,.0f} "
          f"({(tot_n-tot_b)/tot_b*100:+.1f}%)")
    print(f"regressions: {regress if regress else 'NONE'}")


if __name__ == "__main__":
    main()
