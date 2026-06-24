"""Per-sequence trace summariser for the rebuild.

Parses [REBUILD_SEQ] lines from a capture dir's <inst>.stderr.txt files and
prints a per-instance trajectory digest: construct -> z1-descent -> LBBD rounds
-> ban-cuts -> selected engine -> final.  This is the "every sequence" view the
operator asked for -- it shows WHERE each instance's effort went and where it
got stuck (residual z1, z3 explosion from over-eviction, non-convergence).

  python notes/devlog/seqlog.py <tag>            # all instances
  python notes/devlog/seqlog.py <tag> prob_3     # one instance, full trace
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse(stderr_path):
    seq = []
    try:
        for line in open(stderr_path, encoding="utf-8", errors="ignore"):
            i = line.find("[REBUILD_SEQ]")
            if i >= 0:
                try:
                    seq.append(json.loads(line[i + len("[REBUILD_SEQ]"):]))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seq


def digest(seq):
    d = {"construct": None, "phase1": None, "z1desc": 0, "lbbd_rounds": 0,
         "lbbd_best_z1": None, "bancuts": 0, "lbbd_found": None,
         "select": None, "final": None, "ff_fallback": False}
    lbbd_z1s = []
    for e in seq:
        k = e.get("k")
        if k == "construct":
            d["construct"] = (e.get("z1"), e.get("z3"))
        elif k == "phase1_done":
            d["phase1"] = (e.get("z1"), e.get("z3"))
        elif k == "z1desc":
            d["z1desc"] += 1
        elif k == "lbbd":
            d["lbbd_rounds"] += 1
            lbbd_z1s.append(e.get("z1"))
        elif k == "bancut":
            d["bancuts"] += 1
        elif k == "lbbd_done":
            d["lbbd_found"] = e.get("found")
        elif k == "ff_fallback":
            d["ff_fallback"] = True
        elif k == "select":
            d["select"] = (e.get("label"), e.get("z1"), e.get("z3"))
        elif k == "final":
            d["final"] = (e.get("feas"), e.get("z1"), e.get("z2"),
                          e.get("z3"), e.get("wall"))
    if lbbd_z1s:
        d["lbbd_best_z1"] = min(x for x in lbbd_z1s if x is not None)
    return d


def main():
    tag = sys.argv[1]
    one = sys.argv[2] if len(sys.argv) > 2 else None
    cap = ROOT / "results" / "capture" / tag
    insts = [one] if one else [f"prob_{i}" for i in range(1, 21)]
    if one:
        seq = parse(cap / f"{one}.stderr.txt")
        for e in seq:
            print(json.dumps(e, ensure_ascii=False))
        return
    print(f"{'inst':<9}{'constr(z1/z3)':>16}{'sel':>10}{'lbbd_r':>7}{'ban':>5}"
          f"{'found':>6}{'final(z1/z3)':>15}{'wall':>6}")
    for inst in insts:
        d = digest(parse(cap / f"{inst}.stderr.txt"))
        c = d["construct"]; s = d["select"]; f = d["final"]
        cs = f"{c[0]}/{c[1]}" if c else "-"
        ss = (s[0] or "-")[:9] if s else "-"
        fs = f"{f[1]}/{f[3]}" if f else "-"
        ws = f"{f[4]}" if f and f[4] is not None else "-"
        ff = "ff" if d["ff_fallback"] else ("Y" if d["lbbd_found"] else
                                            ("N" if d["lbbd_found"] is False else "-"))
        print(f"{inst:<9}{cs:>16}{ss:>10}{d['lbbd_rounds']:>7}{d['bancuts']:>5}"
              f"{ff:>6}{fs:>15}{ws:>6}")


if __name__ == "__main__":
    main()
