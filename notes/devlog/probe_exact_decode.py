"""Probe: does the EXACT crane-safe decoder (_decode_bay, exhaustive positions)
pack DENSER than the raster fixed-time decoder, on the z3-optimal assignment?

If exact z1 << raster z1 on the SAME (z3=0/low) assignment, then the packing
ceiling can be raised by decoding the final chosen assignment exactly -> fewer
evictions -> lower z3.  This is the decisive test for the rebuild's next lever.

  python notes/devlog/probe_exact_decode.py prob_3 [prob_5 ...]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import myalgorithm as M          # noqa: E402
import fastfloor as FF           # noqa: E402
from utils import Bay            # noqa: E402


def probe(inst):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
    blocks = prob["blocks"]
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    bay_areas = [b["width"] * b["height"] for b in prob["bays"]]
    avg = sum(bay_areas) / nb
    bay_u = [avg / a for a in bay_areas]
    fbays = M._feasible_bays(blocks, bays)
    DUE = [int(b["due_date"]) for b in blocks]

    # z3-optimal assignment (uncapped) -- maximally congested, low z3
    assign = M._cpsat_assignment(prob, bays, fbays, bay_u, time_budget=10.0)
    if assign is None:
        print(f"{inst}: no assignment"); return
    members = [[] for _ in range(nb)]
    for b, j in enumerate(assign):
        members[j].append(b)

    edd = sorted(range(len(blocks)), key=lambda i: (DUE[i], blocks[i]["release_time"]))
    pos = {i: k for k, i in enumerate(edd)}

    def tard(res):
        return sum(max(0, r["exit_time"] - DUE[b]) for b, r in res.items())

    raster_z1 = exact_z1 = 0.0
    t_r = t_e = 0.0
    dl = time.monotonic() + 600
    for j in range(nb):
        if not members[j]:
            continue
        order = sorted(members[j], key=lambda i: pos[i])
        t0 = time.monotonic()
        r_res, _ft = FF._fixed_time_decode(bays[j], j, members[j], blocks, dl, order_key=order)
        t_r += time.monotonic() - t0
        rz = tard(r_res) if r_res else 9e9
        t0 = time.monotonic()
        e_res, _fc = M._decode_bay(bays[j], j, order, blocks, deadline=dl, exhaustive_pos=True)
        t_e += time.monotonic() - t0
        ez = tard(e_res) if e_res else 9e9
        raster_z1 += rz
        exact_z1 += ez
        if abs(rz - ez) > 0.5:
            print(f"  {inst} bay{j} ({len(members[j])} blk): raster_z1={rz:.0f} exact_z1={ez:.0f}")
    print(f"{inst}: RASTER z1={raster_z1:.0f} ({t_r:.1f}s)  EXACT z1={exact_z1:.0f} ({t_e:.1f}s)  "
          f"=> exact {'BETTER' if exact_z1 < raster_z1 - 0.5 else ('same' if abs(exact_z1-raster_z1)<0.5 else 'WORSE')}")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        probe(a)
