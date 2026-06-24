"""
adapter.py -- reconstruct per-bay `placed` lists from a finished solution dict.

This is the INVERSE of `seed.serialize`.  It lets the crane-aware re-pack
(`crane_cpsat.crane_repack_bay`) be applied as a post-process to ANY solver's
output -- not just v3's own seed -- by rebuilding, for every block, the exact
`placed` record that `temporal_pack.simulate` would have produced:

    placed = {id, sh, x, y, orient, entry, exit, world}

The `sh` is built via the SAME path `build_subset` uses
(`gridmap.build_shape(bid, data["blocks"][bid], orient_idx, scale)`), and the
`world` via the SAME path `temporal_pack._world` uses
(`shapely.affinity.translate(sh.layers[l].poly, xoff=x, yoff=y)` per layer), so
the reconstructed records are byte-compatible with the live solver's records.

Public API:
    deserialize(data, solution, scale=2) -> bays_placed   # {bay_id -> [placed,...]}
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
# v3pp package: cross-imports are package-relative; do NOT pollute sys.path.
from .gridmap import build_shape                       # noqa: E402
from shapely.affinity import translate as _translate  # noqa: E402


# ---------------------------------------------------------------------------
def _world(sh, x, y):
    """Layer polygons translated to (x, y) -- identical to temporal_pack._world."""
    return {l: _translate(sh.layers[l].poly, xoff=x, yoff=y)
            for l in range(sh.n_layers)}


# ---------------------------------------------------------------------------
def deserialize(data: dict, solution: dict, scale: int = 2) -> dict:
    """{"operations": {str_time: [op,...]}} -> {bay_id -> [placed,...]}.

    Inverse of seed.serialize.  For each block:
      1. read its ENTRY op (bay_id, x, y, orient_idx) + entry time (op's timestamp),
      2. read its EXIT op's timestamp = exit time,
      3. rebuild `sh` via gridmap.build_shape(...) exactly like build_subset,
      4. rebuild `world` via per-layer translate exactly like temporal_pack._world,
      5. assemble the placed record and group by bay.
    """
    ops = solution["operations"]

    # collect per block_id: entry pose + entry/exit times
    entry_info: dict[int, dict] = {}   # bid -> {bay_id, x, y, orient_idx, entry}
    exit_time: dict[int, int] = {}     # bid -> exit time

    for t_str, op_list in ops.items():
        t = int(t_str)
        for op in op_list:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                entry_info[bid] = {
                    "bay_id": int(op["bay_id"]),
                    "x": int(op["x"]),
                    "y": int(op["y"]),
                    "orient_idx": int(op["orient_idx"]),
                    "entry": t,
                }
            elif op["type"] == "EXIT":
                exit_time[bid] = t

    blocks = data["blocks"]
    bays_placed: dict[int, list] = {}

    for bid, info in entry_info.items():
        bay_id = info["bay_id"]
        x, y = info["x"], info["y"]
        orient_idx = info["orient_idx"]
        entry = info["entry"]
        exit_t = exit_time[bid]

        # rebuild shape EXACTLY like build_subset: build_shape(i, blocks[i], o, scale)
        sh = build_shape(bid, blocks[bid], orient_idx, scale)
        world = _world(sh, x, y)

        placed = {
            "id": bid,
            "sh": sh,
            "x": x,
            "y": y,
            "orient": orient_idx,
            "entry": entry,
            "exit": exit_t,
            "world": world,
        }
        bays_placed.setdefault(bay_id, []).append(placed)

    return bays_placed


__all__ = ["deserialize"]


# ---------------------------------------------------------------------------
# Inline self-check (MANDATORY guard for Windows spawn safety).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import seed
    import crane_cpsat

    inst = os.path.normpath(
        os.path.join(THIS, "..", "instances", "train", "prob_24.json"))

    print(f"[adapter check] instance = {inst}", flush=True)

    # --- (1) ROUND-TRIP: obj before == obj after -------------------------
    bp0, data = seed.make_seed(inst)
    sol = seed.serialize(bp0)
    bp1 = deserialize(data, sol)

    ev0 = seed.global_eval(data, bp0)
    ev1 = seed.global_eval(data, bp1)
    print(f"[round-trip] obj(seed)        = {ev0['obj']}", flush=True)
    print(f"[round-trip] obj(deserialize) = {ev1['obj']}", flush=True)
    print(f"[round-trip] feasible seed={ev0['feasible']} desr={ev1['feasible']}",
          flush=True)
    assert ev0["obj"] == ev1["obj"], (
        f"ROUND-TRIP MISMATCH: {ev0['obj']} != {ev1['obj']} -- sh/world recon wrong")
    print("[round-trip] PASS: objs identical", flush=True)

    # --- (2) CRANE-REPACK COMPAT on the largest-tardy bay of bp1 ----------
    blocks = data["blocks"]

    def _D(bid):
        return blocks[bid].get("due_date", 0)

    def _bay_z1(placed):
        return sum(max(0, p["exit"] - _D(p["id"])) for p in placed)

    # pick the bay with the highest single-bay z1 (tardiness)
    bay_z1 = {j: _bay_z1(pl) for j, pl in bp1.items()}
    j = max(bay_z1, key=lambda k: bay_z1[k])
    z1_before = bay_z1[j]
    print(f"\n[crane-repack] largest-tardy bay j={j}  "
          f"blocks={len(bp1[j])}  z1_before={z1_before}", flush=True)

    new_placed, status, wall, cinfo = crane_cpsat.crane_repack_bay(
        data, j, bp1[j], 15)

    if new_placed is None:
        print(f"[crane-repack] status={status} returned None "
              f"(no improving/feasible solution) -- kept original", flush=True)
        z1_after = z1_before
    else:
        z1_after = _bay_z1(new_placed)
    print(f"[crane-repack] status={status}  wall={wall:.2f}s", flush=True)
    print(f"[crane-repack] z1_before={z1_before}  z1_after={z1_after}  "
          f"delta={z1_after - z1_before:+d}", flush=True)
    assert z1_after <= z1_before, (
        f"crane repack made single-bay z1 WORSE: {z1_before} -> {z1_after}")
    print("[crane-repack] PASS: returned without exception, z1 improved-or-equal",
          flush=True)

    print("\n[adapter check] ALL CHECKS PASSED", flush=True)
