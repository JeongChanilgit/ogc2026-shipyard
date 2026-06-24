"""Per-bay isolation benchmark (2026-06-18).

Goal: iterate on the per-bay 4D packer (x,y,orient,entry; minimise z1) WITHOUT
full-instance noise (B1 assignment + timing).  Extract the real per-bay block
SETS B1 produced (from a saved solution), then run candidate packers on each bay
in isolation and score (z1 achieved + wall).  Correctness via the OFFICIAL
checker on a single-bay sub-instance.

Baseline = the saved solution's OWN per-bay z1 (= gassign B2+B3 output).

Usage:
  python bench.py                # runs the 5 set2 bays from gf_noperbay_120
  python bench.py <inst.json> <sol.json>
"""
from __future__ import annotations
import sys, os, json, time, copy

ROOT = r"C:\claude-develop\OGC2026"
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from utils import Bay, check_feasibility           # official, read-only
from baseline_greedy import _build_operations
import fastfloor as ff
import boxsolver as _bx


def clear_caches():
    """boxsolver._FP_CACHE/_LAYER_CACHE are keyed by (block_id, orient) which
    COLLIDES across instances (same id, different block) -> cross-instance
    poisoning -> wrong geometry -> infeasible.  MUST clear per instance."""
    try:
        _bx._FP_CACHE.clear()
    except Exception:
        pass
    try:
        _bx._LAYER_CACHE.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Extraction: per-bay block sets + per-block placement from a saved solution.
# ---------------------------------------------------------------------------
def extract_perbay(sol):
    place = {}
    for t_str, ops in sol["operations"].items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            d = place.setdefault(bid, {})
            if op["type"] == "ENTRY":
                d.update(bay=op["bay_id"], x=op["x"], y=op["y"],
                         orient=op["orient_idx"], entry=t)
            else:
                d["exit"] = t
    bays = {}
    for bid, p in place.items():
        bays.setdefault(p["bay"], []).append(bid)
    return bays, place


def z1_of(ids, place, blocks):
    return sum(max(0.0, place[b]["exit"] - blocks[b]["due_date"]) for b in ids)


# ---------------------------------------------------------------------------
# Validation: build a single-bay sub-instance and run the official checker.
# packing: {block_id: (x,y,orient,entry,exit)}.  Returns (feasible, raw z1).
# ---------------------------------------------------------------------------
def validate(prob, bay_id, ids, packing):
    blocks = prob["blocks"]
    sub_bay = copy.deepcopy(prob["bays"][bay_id])
    id_map = {old: i for i, old in enumerate(ids)}
    new_blocks = []
    for old in ids:
        nb = copy.deepcopy(blocks[old])
        nb["bay_preferences"] = [blocks[old]["bay_preferences"][bay_id]]
        new_blocks.append(nb)
    sub = {"bays": [sub_bay], "blocks": new_blocks,
           "weights": copy.deepcopy(prob.get("weights", {}))}
    assigns = []
    for old in ids:
        x, y, o, e, ex = packing[old]
        assigns.append({"block_id": id_map[old], "bay_id": 0, "x": int(x),
                        "y": int(y), "orient_idx": int(o),
                        "entry_time": int(e), "exit_time": int(ex)})
    chk = check_feasibility(sub, {"operations": _build_operations(assigns)})
    if not chk.get("feasible"):
        return False, None
    return True, chk.get("obj1")


# ---------------------------------------------------------------------------
# Packers: (prob, bay_id, ids, deadline) -> {block_id: (x,y,orient,entry,exit)}
# ---------------------------------------------------------------------------
def _ff_pack(prob, bay_id, ids, deadline, use_lca):
    bay = Bay.from_dict(prob["bays"][bay_id], bay_id)
    asgn, _ft = ff._fixed_time_decode(bay, bay_id, ids, prob["blocks"],
                                      deadline, order_key="F0", use_lca=use_lca)
    if asgn is None:
        return None
    return {b: (r["x"], r["y"], r["orient_idx"], r["entry_time"], r["exit_time"])
            for b, r in asgn.items()}


def pack_bl(prob, bay_id, ids, deadline):       # plain bottom-left = B2
    return _ff_pack(prob, bay_id, ids, deadline, use_lca=False)


def pack_lca(prob, bay_id, ids, deadline):      # dense-greedy v0 = contact-area
    return _ff_pack(prob, bay_id, ids, deadline, use_lca=True)


PACKERS = {"BL(B2)": pack_bl, "LCA(dense-v0)": pack_lca}


# ---------------------------------------------------------------------------
def bench_instance(inst_path, sol_path, packers=PACKERS, per_bay_budget=15.0):
    clear_caches()
    prob = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_path, encoding="utf-8"))
    if "solution" in sol:
        sol = sol["solution"]
    blocks = prob["blocks"]
    bays, place = extract_perbay(sol)
    name = os.path.basename(inst_path).replace(".json", "")

    # multi-block bays only (where packing matters)
    multi = {j: ids for j, ids in bays.items() if len(ids) >= 2}
    base_tot = sum(z1_of(ids, place, blocks) for ids in multi.values())

    print(f"\n=== {name}  ({len(bays)} bays, {len(multi)} multi-block, "
          f"{sum(len(v) for v in multi.values())} blocks) ===")
    print(f"  {'packer':16s} {'z1(sum)':>14s} {'wall':>7s} {'feas':>10s}  vs base")
    print(f"  {'BASELINE(B2+B3)':16s} {base_tot:14,.0f} {'-':>7s} {'-':>10s}")

    for pname, pf in packers.items():
        tot = 0.0
        wall = 0.0
        nfeas = 0
        nbay = 0
        for j, ids in multi.items():
            nbay += 1
            t0 = time.monotonic()
            try:
                packing = pf(prob, j, ids, time.monotonic() + per_bay_budget)
            except Exception as e:
                packing = None
            wall += time.monotonic() - t0
            if packing is None or any(b not in packing for b in ids):
                tot = float("inf")
                continue
            feas, z1 = validate(prob, j, ids, packing)
            if not feas:
                tot = float("inf")
                continue
            nfeas += 1
            tot += z1
        delta = (tot - base_tot)
        dpct = (delta / base_tot * 100) if base_tot else 0.0
        print(f"  {pname:16s} {tot:14,.0f} {wall:6.1f}s {nfeas:>4d}/{nbay:<5d}  "
              f"{delta:+,.0f} ({dpct:+.1f}%)")
    return base_tot


def bench_bay(inst_path, sol_path, bay_id, per_bay_budget=20.0):
    """Detailed single-bay benchmark: baseline + each ff packer with placement
    stats (at-R / delayed / forced)."""
    clear_caches()
    prob = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_path, encoding="utf-8"))
    if "solution" in sol:
        sol = sol["solution"]
    blocks = prob["blocks"]
    bays, place = extract_perbay(sol)
    bay_id = int(bay_id)
    ids = bays[bay_id]
    bd = prob["bays"][bay_id]
    base_z1 = z1_of(ids, place, blocks)
    base_tardy = sum(1 for b in ids if place[b]["exit"] > blocks[b]["due_date"])
    name = os.path.basename(inst_path).replace(".json", "")
    print(f"\n=== {name} bay {bay_id}: {len(ids)} blocks, "
          f"W×H={bd['width']}×{bd['height']} ===")
    print(f"  BASELINE (B2+B3): z1={base_z1:,.0f}  tardy={base_tardy}/{len(ids)}")
    print(f"  {'packer':16s} {'z1':>12s} {'wall':>7s} {'feas':>5s}  "
          f"{'atR':>4s} {'dly':>4s} {'frc':>4s}")
    bay = Bay.from_dict(bd, bay_id)
    _greedy = [] if os.environ.get("PB_SKIP_GREEDY") else [("BL(B2)", False), ("LCA(dense-v0)", True)]
    for pname, lca in _greedy:
        t0 = time.monotonic()
        asgn, ft = ff._fixed_time_decode(bay, bay_id, ids, blocks,
                                         t0 + per_bay_budget, order_key="F0",
                                         use_lca=lca)
        wall = time.monotonic() - t0
        if asgn is None:
            print(f"  {pname:16s} {'FAIL':>12s} {wall:6.1f}s")
            continue
        packing = {b: (r["x"], r["y"], r["orient_idx"], r["entry_time"],
                       r["exit_time"]) for b, r in asgn.items()}
        feas, z1 = validate(prob, bay_id, ids, packing)
        print(f"  {pname:16s} {(z1 if feas else -1):12,.0f} {wall:6.1f}s "
              f"{str(feas):>5s}  {ft['placed_at_R']:>4d} {ft['delayed']:>4d} "
              f"{ft['forced']:>4d}")

    # windowed (rolling) 4D CP-SAT, orientation fixed to baseline's choice
    import packers_cpsat as pc
    orient_of = {b: place[b]["orient"] for b in ids}
    _Ks = [] if os.environ.get("PB_SKIP_CPSAT") else \
        [int(x) for x in os.environ.get("PB_K", "8").split(",")]
    for K in _Ks:
        t0 = time.monotonic()
        try:
            packing = pc.pack_windowed_cpsat(
                prob, bay_id, ids, t0 + float(os.environ.get("PB_BUDGET", "60")),
                orient_of, K=K, batch_s=float(os.environ.get("PB_BATCH_S", "3")))
        except Exception as e:
            packing = None
            print("   cpsat exc:", repr(e)[:120])
        wall = time.monotonic() - t0
        if packing is None or any(b not in packing for b in ids):
            print(f"  {'WIN-CPSAT K=%d' % K:16s} {'FAIL/None':>12s} {wall:6.1f}s")
            continue
        feas, z1 = validate(prob, bay_id, ids, packing)
        ntardy = sum(1 for b in ids
                     if packing[b][4] > blocks[b]["due_date"])
        print(f"  {'WIN-CPSAT K=%d' % K:16s} {(z1 if feas else -1):12,.0f} "
              f"{wall:6.1f}s {str(feas):>5s}  tardy={ntardy}")

    # ALNS: improve a seed placement via destroy/repair (default seed = baseline)
    if os.environ.get("PB_ALNS"):
        init = {b: (place[b]["x"], place[b]["y"], place[b]["orient"],
                    place[b]["entry"], place[b]["exit"]) for b in ids}
        t0 = time.monotonic()
        res, st = pc.pack_alns(
            prob, bay_id, ids, t0 + float(os.environ.get("PB_ALNS_BUDGET", "60")),
            init, orient_of, subset=int(os.environ.get("PB_SUBSET", "12")),
            nwin=int(os.environ.get("PB_NWIN", "8")),
            repair_s=float(os.environ.get("PB_REPAIR_S", "2")))
        wall = time.monotonic() - t0
        if res is None:
            print(f"  {'ALNS':16s} {'None':>12s} {wall:6.1f}s")
        else:
            feas, z1 = validate(prob, bay_id, ids, res)
            print(f"  {'ALNS(seed=base)':16s} {(z1 if feas else -1):12,.0f} "
                  f"{wall:6.1f}s {str(feas):>5s}  iters={st[0]} acc={st[1]}")


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "bay":
        bench_bay(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) >= 3:
        bench_instance(sys.argv[1], sys.argv[2])
    else:
        CAP = os.path.join(ROOT, "results", "capture", "gf_noperbay_120")
        for p in ["prob_26", "prob_27", "prob_31", "prob_35", "prob_39"]:
            ip = os.path.join(ROOT, "instances", "train", p + ".json")
            sp = os.path.join(CAP, p + ".json")
            if os.path.exists(sp):
                bench_instance(ip, sp)
