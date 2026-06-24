"""
viz_ours.py -- render OUR actual v3 solution as ONE 3D viz HTML with ALL bays
laid out side-by-side, colored by a 5-status scheme
(red=late-from-placement / yellow=late-mid-process / purple=late+wrong_bay /
 blue=wrong_bay-on-time / green=ok).

CLI:
    python viz_ours.py [prob=prob_38] [sol_file=real_<prob>.json]

  - rebuild every bay's placed records from adapter.deserialize,
  - emit viz.py's NATIVE multi-bay trace: a `bays` list (each bay its own
    width/height/max_layer/id) + every block tagged with its `bay` index.
    viz.py itself lays the bays out along +X (bayOffset = cumulative widths +
    GAP) and draws a wireframe box + grid + "bay <id>" label per bay, so we do
    NOT pre-shift event x here -- coordinates stay LOCAL to each bay.
  - stamp each block with `wrong_bay = (assigned_bay != preferred_bay)` and
    carry `entry`/`exit`/`due` so the JS can split tardy by WHEN it became late,
  - title it with the global obj/z1/z2/z3 from seed.global_eval,
  - write a single `viz_<prob>_all.html` and print the 5-way counts.
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import adapter                       # noqa: E402
import seed                          # noqa: E402
from viz import write_viz           # noqa: E402

TRAIN = os.path.normpath(os.path.join(THIS, "..", "instances", "train"))


def _multibay_trace(blocks, bays, bay_layouts, pref, label):
    """Build viz.py's NATIVE multi-bay trace.

    bay_layouts = {bay_id: {bid: {x,y,orient_idx,entry_time,exit_time}}}

    Emits a `bays` list (one entry per instance bay, with its own
    width/height/max_layer/id) and a `blocks` map where each block carries its
    integer `bay` index. Event x/y stay LOCAL to the bay -- viz.py adds the
    bay's x-offset at render time, draws each bay's wireframe box + grid +
    label, and places every block in its correct bay. Each block is stamped
    with `wrong_bay`, `entry`, `exit`, `due` for the 5-status color scheme.
    """
    tr = {
        "instance": label,
        "bays": [],
        "blocks": {},
        "events": [],
        "stats": {"mode": label, "n": 0},
    }
    # Per-bay max layer count, derived from placed blocks.
    max_layer_per_bay = {}
    n = 0
    for bay_id in sorted(bay_layouts.keys()):
        for bid, rec in bay_layouts[bay_id].items():
            oi = rec["orient_idx"]
            lr = blocks[bid]["shape"][oi]["layers"]
            max_layer_per_bay[bay_id] = max(max_layer_per_bay.get(bay_id, 0), len(lr))
            en, ex = int(rec["entry_time"]), int(rec["exit_time"])
            tr["blocks"][str(bid)] = {
                "bay": int(bay_id),
                "orient_idx": oi,
                "layers": [[[float(px), float(py)] for px, py in ly] for ly in lr],
                "release": blocks[bid].get("release_time", 0),
                "due": blocks[bid].get("due_date", 0),
                "proc": blocks[bid].get("processing_time", 0),
                "entry": en,
                "exit": ex,
                "wrong_bay": bool(bay_id != pref[bid]),
            }
            tr["events"].append({"t": en, "type": "ENTRY", "block_id": bid,
                                 "x": int(round(rec["x"])),
                                 "y": int(round(rec["y"]))})
            tr["events"].append({"t": ex, "type": "EXIT", "block_id": bid})
            n += 1
    # Native bays list: every instance bay with its own footprint.
    for j, b in enumerate(bays):
        tr["bays"].append({
            "id": j,
            "width": b["width"],
            "height": b["height"],
            "max_layer": max(1, max_layer_per_bay.get(j, 1)),
        })
    tr["stats"]["n"] = n
    tr["events"].sort(key=lambda e: (e["t"], 0 if e["type"] == "EXIT" else 1))
    return tr


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    sol_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        THIS, f"real_{prob}.json")
    inst_path = os.path.join(TRAIN, f"{prob}.json")

    data = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_file, encoding="utf-8"))
    blocks = data["blocks"]
    bays = data["bays"]
    m = len(bays)

    # preferred bay per block = argmax bay_preferences
    pref = [
        max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
        for i in range(len(blocks))
    ]

    bays_placed = adapter.deserialize(data, sol)

    ev = seed.global_eval(data, bays_placed)
    obj_str = (f"obj={ev['obj']} z1={ev['z1']} z2={ev['z2']} z3={ev['z3']} "
               f"feasible={ev['feasible']}")
    print(f"[{prob}] {obj_str}", flush=True)

    # Per-bay layout dicts (only bays holding >=1 block).
    bay_layouts = {}
    for j in sorted(bays_placed.keys()):
        placed = bays_placed[j]
        if not placed:
            continue
        bay_layouts[j] = {
            p["id"]: {
                "x": p["x"], "y": p["y"], "orient_idx": p["orient"],
                "entry_time": p["entry"], "exit_time": p["exit"],
            }
            for p in placed
        }

    label = f"{prob} — ALL bays  |  {obj_str}"
    tr = _multibay_trace(blocks, bays, bay_layouts, pref, label)

    # 5-way counts by the SAME priority viz.py's statusColor uses:
    #   tardy & wrong          -> purple
    #   tardy & entry > due     -> red    (late from placement)
    #   tardy (entry<=due<exit) -> yellow (late mid-process)
    #   wrong_bay (on-time)     -> blue
    #   else                    -> green
    red = yellow = purple = blue = green = 0
    for bay_id, layout in bay_layouts.items():
        for bid, rec in layout.items():
            due = blocks[bid].get("due_date")
            entry = rec["entry_time"]
            exit_ = rec["exit_time"]
            tardy = (due is not None and exit_ > due)
            wrong = tr["blocks"][str(bid)]["wrong_bay"]
            if tardy:
                if wrong:
                    purple += 1
                elif due is not None and entry > due:
                    red += 1
                else:
                    yellow += 1
            elif wrong:
                blue += 1
            else:
                green += 1

    # Per-bay block counts (proof all bays render).
    per_bay = {bay_id: len(layout) for bay_id, layout in sorted(bay_layouts.items())}
    n_blocks = sum(per_bay.values())

    out = os.path.join(THIS, f"viz_{prob}_all.html")
    write_viz(tr, out)
    total = red + yellow + purple + blue + green
    print(f"  ALL bays: {len(bay_layouts)} bays, {n_blocks} blocks  "
          f"red(late@place)={red} yellow(late@mid)={yellow} "
          f"purple(late+wrong)={purple} blue(wrong_bay)={blue} green(ok)={green} "
          f"(sum={total})", flush=True)
    print(f"  per-bay block counts: "
          + "  ".join(f"bay{bid}={cnt}" for bid, cnt in per_bay.items()), flush=True)
    sz = os.path.getsize(out)
    print(f"    -> {out}  ({sz} bytes)", flush=True)


if __name__ == "__main__":
    main()
