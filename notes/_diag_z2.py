"""Front-B headroom probe + Z2/Z3 assignment-LNS prototype.

Reads captured solutions (notes/_capture20.py output), and for each instance:
  - current z1/z2/z3 and w2*z2+w3*z3,
  - the UNCONSTRAINED assignment optimum of w2*z2+w3*z3 found by a relocate+swap
    hill-climb over the block->bay vector (ignores packing feasibility -> an
    UPPER bound on what Front B could capture),
  - optionally a feasibility-FILTERED variant (block may only move to a bay whose
    floor its min-bbox fits) -> a tighter, more realistic headroom.

z2/z3 are pure functions of the assignment (load_j = sum workload; u_j = avg/area;
z2 = floor(max_jk |u_j load_j - u_k load_k|); z3 = sum(max pref - pref[bay])), so
this needs no geometry decode -- thousands of moves/sec in pure Python.  This is
exactly the Front-B core; the real lever just adds consider()-gated feasibility.

  python notes/_diag_z2.py --tag base --feasfilter 1
"""
import argparse, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ogc_analysis as A  # noqa: E402

ALL20 = [f"prob_{i}" for i in range(1, 21)]


def bay_u(prob):
    bays = prob["bays"]
    areas = [b["width"] * b["height"] for b in bays]
    avg = sum(areas) / len(areas)
    return [avg / a for a in areas]


def z2_of(assign, loads0, workloads, u, n_bays):
    # loads recomputed from scratch is O(n); caller passes incremental where hot
    loads = [0.0] * n_bays
    for b, j in enumerate(assign):
        loads[j] += workloads[b]
    w = [u[j] * loads[j] for j in range(n_bays)]
    return math.floor(max(w) - min(w)), loads


def z3_of(assign, prefs, smax):
    return sum(smax[b] - prefs[b][assign[b]] for b in range(len(assign)))


def obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3):
    loads = [0.0] * n_bays
    for b, j in enumerate(assign):
        loads[j] += workloads[b]
    wl = [u[j] * loads[j] for j in range(n_bays)]
    z2 = math.floor(max(wl) - min(wl))
    z3 = sum(smax[b] - prefs[b][assign[b]] for b in range(len(assign)))
    return w2 * z2 + w3 * z3, z2, z3


def hillclimb(assign0, workloads, u, n_bays, prefs, smax, w2, w3, feas, iters=200000,
              area=None, cap=None):
    """Relocate+swap hill-climb on w2*z2+w3*z3.  If area/cap given, every bay's
    total block area must stay <= cap[j] (packing-feasibility proxy) -> a REALISTIC
    Front-B ceiling rather than the unconstrained one that overloads pref bays."""
    assign = list(assign0)
    n = len(assign)
    aload = [0.0] * n_bays
    if area is not None:
        for b in range(n):
            aload[assign[b]] += area[b]

    def cap_ok_reloc(b, oj, nj):
        if cap is None:
            return True
        return aload[nj] + area[b] <= cap[nj] + 1e-6

    def cap_ok_swap(b1, b2, j1, j2):
        if cap is None:
            return True
        return (aload[j2] - area[b2] + area[b1] <= cap[j2] + 1e-6 and
                aload[j1] - area[b1] + area[b2] <= cap[j1] + 1e-6)

    cur, _, _ = obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3)
    improved = True
    it = 0
    while improved and it < iters:
        improved = False
        for b in range(n):
            oj = assign[b]
            for nj in feas[b]:
                if nj == oj or not cap_ok_reloc(b, oj, nj):
                    continue
                assign[b] = nj
                cand, _, _ = obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3)
                if cand < cur - 1e-9:
                    cur = cand
                    if area is not None:
                        aload[oj] -= area[b]; aload[nj] += area[b]
                    oj = nj; improved = True
                else:
                    assign[b] = oj
                it += 1
        for b1 in range(n):
            for b2 in range(b1 + 1, n):
                j1, j2 = assign[b1], assign[b2]
                if j1 == j2:
                    continue
                if j2 not in feas[b1] or j1 not in feas[b2]:
                    continue
                if not cap_ok_swap(b1, b2, j1, j2):
                    continue
                assign[b1], assign[b2] = j2, j1
                cand, _, _ = obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3)
                if cand < cur - 1e-9:
                    cur = cand
                    if area is not None:
                        aload[j1] += area[b2] - area[b1]
                        aload[j2] += area[b1] - area[b2]
                    improved = True
                else:
                    assign[b1], assign[b2] = j1, j2
                it += 1
    cur, z2, z3 = obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3)
    return assign, cur, z2, z3, it


def feasible_bays(prob, feasfilter):
    blocks = prob["blocks"]; bays = prob["bays"]; n_bays = len(bays)
    out = []
    for b in blocks:
        if not feasfilter:
            out.append(list(range(n_bays))); continue
        g = A.block_min_area_orient(b)  # smallest bbox
        ok = []
        for j, bay in enumerate(bays):
            # fits if some orient's bbox fits the bay floor (either rotation)
            fits = False
            for o in b["shape"]:
                gg = A.orient_geometry(o)
                if gg["bbox_w"] <= bay["width"] and gg["bbox_h"] <= bay["height"]:
                    fits = True; break
            if fits:
                ok.append(j)
        out.append(ok or list(range(n_bays)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="base")
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--feasfilter", type=int, default=1)
    ap.add_argument("--cap", type=float, default=0.0,
                    help="if >0, constrain each bay's total block bbox-area <= cap*bay_area "
                         "(packing-feasible Front-B ceiling). 0 = unconstrained.")
    a = ap.parse_args()
    insts = ALL20 if a.instances.upper() == "ALL" else \
            [s.strip() for s in a.instances.split(",")]
    capdir = ROOT / "results" / "capture" / a.tag
    print(f"=== Front-B headroom (tag={a.tag}, feasfilter={a.feasfilter}) ===")
    print(f"{'inst':9} {'z1':>5} {'z2cur':>6} {'z3cur':>6} {'O23cur':>9} "
          f"{'z2opt':>6} {'z3opt':>6} {'O23opt':>9} {'redu%':>6}")
    tot_cur = tot_opt = 0.0
    for inst in insts:
        p = capdir / f"{inst}.json"
        if not p.exists():
            print(f"{inst:9}  (no capture)"); continue
        d = json.load(open(p))
        prob = A.load_instance(inst); sol = d["solution"]; met = d["met"]
        rec = A.assignments(prob, sol)
        n = len(prob["blocks"]); n_bays = len(prob["bays"])
        assign = [0] * n
        for b in range(n):
            assign[b] = rec[b]["bay"] if rec.get(b) and rec[b]["bay"] is not None else 0
        workloads = [prob["blocks"][b]["workload"] for b in range(n)]
        prefs = [prob["blocks"][b]["bay_preferences"] for b in range(n)]
        smax = [max(prefs[b]) for b in range(n)]
        u = bay_u(prob)
        w = prob.get("weights", {}); w2 = w.get("w2", 1.0); w3 = w.get("w3", 1.0)
        feas = feasible_bays(prob, a.feasfilter)
        area = cap = None
        if a.cap > 0:
            area = [A.block_min_area_orient(prob["blocks"][b])["bbox_area"]
                    for b in range(n)]
            cap = [a.cap * prob["bays"][j]["width"] * prob["bays"][j]["height"]
                   for j in range(n_bays)]
        o_cur, z2c, z3c = obj23(assign, workloads, u, n_bays, prefs, smax, w2, w3)
        _, o_opt, z2o, z3o, iters = hillclimb(
            assign, workloads, u, n_bays, prefs, smax, w2, w3, feas,
            area=area, cap=cap)
        redu = 100.0 * (o_cur - o_opt) / o_cur if o_cur > 0 else 0.0
        tot_cur += o_cur; tot_opt += o_opt
        flag = "  <<<" if redu > 5 and met.get("z1", 1) == 0 else \
               ("  (z1>0)" if met.get("z1", 0) > 0 else "")
        print(f"{inst:9} {met.get('z1',0):>5.0f} {z2c:>6.0f} {z3c:>6.0f} "
              f"{o_cur:>9.0f} {z2o:>6.0f} {z3o:>6.0f} {o_opt:>9.0f} "
              f"{redu:>5.1f}%{flag}")
    print(f"\n  TOTAL w2z2+w3z3: cur={tot_cur:.0f} opt(unconstr-reassign)={tot_opt:.0f} "
          f"reducible={100*(tot_cur-tot_opt)/tot_cur if tot_cur else 0:.1f}%")
    print("  <<< = z1=0 instance with >5% assignment-reducible z2/z3 (Front-B target)")
    print("  NOTE: opt ignores packing feasibility beyond bbox-fit -> UPPER bound on capture.")


if __name__ == "__main__":
    main()
