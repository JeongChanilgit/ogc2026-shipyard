"""
packing_ceiling_test.py -- is our per-bay packer leaving co-location (=z1) on the table?

peak_pack showed ~33 blocks CAN co-locate at the peak (correct-geom CP-SAT lower bound)
while our solution co-locates only 27.  This tests the UNIFIED packing lever directly:
run crane_repack_bay with RICH candidates + LONG time on the z1-worst bay and see if z1
drops below current.  crane_repack is never-worse (candidate0 = current pose), so:
  z1 drops a lot  -> packing upside is real & capturable (tune the production packer)
  z1 ~ unchanged  -> we are AT our packer's ceiling (z1 floor confirmed)

run: C:/Users/peter/anaconda3/envs/ogc2025/python.exe packing_ceiling_test.py
"""
from __future__ import annotations
import os, sys, json, time

V4 = os.path.dirname(os.path.abspath(__file__))
if V4 not in sys.path:
    sys.path.insert(0, V4)

import crane_cpsat
from adapter import deserialize


def _load(prob):
    inst = os.path.normpath(os.path.join(V4, "..", "instances", "train", f"prob_{prob}.json"))
    data = json.load(open(inst, encoding="utf-8"))
    sol = json.load(open(os.path.join(V4, f"real_prob_{prob}.json"), encoding="utf-8"))
    return data, sol


def _bay_z1(data, placed):
    blocks = data["blocks"]
    return sum(max(0, p["exit"] - blocks[p["id"]].get("due_date", 0)) for p in placed)


def run(prob, time_s, nx, ny, no, use_orient, window_tardy_only):
    data, sol = _load(prob)
    bp = deserialize(data, sol)
    # worst bay by z1
    j = max(bp, key=lambda k: _bay_z1(data, bp[k]))
    z1_before = _bay_z1(data, bp[j])
    n = len(bp[j])
    print(f"  prob_{prob}: worst bay={j} blocks={n} z1_before={z1_before}", flush=True)
    t0 = time.monotonic()
    try:
        new_placed, status, wall, cinfo = crane_cpsat.crane_repack_bay(
            data, j, bp[j], time_s,
            n_xcand=nx, n_ycand=ny, n_ocand=no,
            use_orient=use_orient, window_tardy_only=window_tardy_only)
    except Exception as e:
        import traceback
        print("    " + "\n    ".join(traceback.format_exc().splitlines()[-4:]), flush=True)
        return {"prob": prob, "bay": j, "z1_before": z1_before, "error": str(e)}
    wall = time.monotonic() - t0
    if new_placed is None:
        z1_after = z1_before
    else:
        z1_after = _bay_z1(data, new_placed)
    print(f"    -> status={status} wall={wall:.0f}s z1_after={z1_after} "
          f"delta={z1_after - z1_before:+d}", flush=True)
    return {"prob": prob, "bay": j, "blocks": n, "z1_before": z1_before,
            "z1_after": z1_after, "delta": z1_after - z1_before,
            "status": str(status), "wall_s": round(wall, 1)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--probs", nargs="+", type=int, default=[38, 27, 31])
    ap.add_argument("--time", type=float, default=240.0)
    ap.add_argument("--nx", type=int, default=12)
    ap.add_argument("--ny", type=int, default=4)
    ap.add_argument("--no", type=int, default=3)
    args = ap.parse_args()

    print(f"[packing_ceiling] probs={args.probs} time={args.time} "
          f"nx={args.nx} ny={args.ny} no={args.no} (RICH candidates, full window)", flush=True)
    rows = []
    for p in args.probs:
        print(f"\n=== prob_{p} ===", flush=True)
        r = run(p, args.time, args.nx, args.ny, args.no,
                use_orient=(args.no > 0), window_tardy_only=False)
        rows.append(r)

    print("\n" + "=" * 80, flush=True)
    print(f"{'prob':>5} {'bay':>4} {'blk':>4} {'z1_before':>10} {'z1_after':>9} "
          f"{'delta':>7} {'status':>10} {'wall':>6}", flush=True)
    print("-" * 80, flush=True)
    for r in rows:
        if "error" in r:
            print(f"{r['prob']:>5}  ERROR {r['error'][:50]}", flush=True); continue
        print(f"{r['prob']:>5} {r['bay']:>4} {r['blocks']:>4} {r['z1_before']:>10} "
              f"{r['z1_after']:>9} {r['delta']:>+7} {r['status']:>10} {r['wall_s']:>5.0f}s",
              flush=True)
    print("=" * 80, flush=True)
    print("\n[VERDICT] big z1 drop => packing upside REAL (tune packer).  "
          "~0 => at packer ceiling (z1 floor).", flush=True)
    json.dump(rows, open(os.path.join(V4, "packing_ceiling_results.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved: packing_ceiling_results.json", flush=True)
