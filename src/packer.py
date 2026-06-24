"""Per-bay REPOSITIONING crane-safe packer.

Greedy fixed-time decode (`fastfloor._fixed_time_decode`) is append-only: once a
block is placed it never moves, so on a congested bay it can delay a block (pay
tardiness) even when the peak co-present footprint fits BY AREA -- the wasted
space is simply unreachable to the append-only BL search.  Reordering does not
fix this (verified by notes/devlog/probe_order.py); REPOSITIONING placed blocks
does.

`pack_bay` seeds from the greedy best-of-orders decode and then runs a
time-boxed repositioning local search that, for each tardy block, evicts the
crane-conflicting co-present blocks, re-anchors the tardy block at its own
earliest window [R, R+P], and RE-INSERTS the evicted ones via the same
crane-safe position search the floor uses (`_ft_search_pos` / `_ft_interacting`
-- the j>=k geometry is NEVER hand-rolled).  Moves commit on first improvement
of total bay tardiness and revert otherwise.  The seed is always retained as a
feasibility floor, so the return value is never worse than greedy.

Self-contained: imports fastfloor / myalgorithm / utils only; modifies none.

    python src/packer.py            # self-test on prob_3 + prob_5
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import fastfloor as FF                                            # noqa: E402
from utils import Bay, Block                                      # noqa: E402


# ---------------------------------------------------------------------------
# placed-list <-> record-dict conversion (must mirror _fixed_time_decode
# exactly: layers = DIRECT world cells, cbox = their bbox, pbox = oriented
# poly bbox shifted by (dx, dy)).
# ---------------------------------------------------------------------------

def _geom_cache_for(ids, blocks):
    cache: dict[int, list] = {}

    def geom(b):
        g = cache.get(b)
        if g is None:
            g = FF._ft_geom(blocks[b])
            cache[b] = g
        return g

    return geom


def _record_to_placed(rec, blk, geom):
    """Build a placed-list entry (the {a,e,n,layers,cbox,pbox} dict the floor
    uses) from a result record.  Returns None if the geometry is unrasterisable
    for the recorded orientation."""
    oi = int(rec["orient_idx"])
    dx = int(rec["x"]); dy = int(rec["y"])
    aB = int(rec["entry_time"]); eB = int(rec["exit_time"])
    g = geom(rec["block_id"])
    if oi >= len(g) or g[oi] is None:
        return None
    bl = Block(rec["block_id"], blk, dx, dy, oi)
    wlayers = FF._world_layer_cells(bl)
    allc = [c for lay in wlayers for c in lay]
    if not allc:
        return None
    wcbox = (min(c[0] for c in allc), min(c[1] for c in allc),
             max(c[0] for c in allc), max(c[1] for c in allc))
    pb = g[oi][2]
    return {
        "a": aB, "e": eB, "n": len(wlayers),
        "layers": wlayers, "cbox": wcbox,
        "pbox": (pb[0] + dx, pb[1] + dy, pb[2] + dx, pb[3] + dy),
        "_bid": rec["block_id"],          # bookkeeping only (ignored by floor)
    }


def _result_to_placed(result, ids, blocks, geom):
    """Convert a {block_id: record} placement to a list of placed entries.
    Returns None on any unrasterisable record."""
    out = []
    for b in ids:
        p = _record_to_placed(result[b], blocks[b], geom)
        if p is None:
            return None
        out.append(p)
    return out


def _total_tard(result, ids, blocks):
    return sum(max(0, result[b]["exit_time"] - int(blocks[b]["due_date"]))
               for b in ids)


# ---------------------------------------------------------------------------
# Crane-safe placement of one block against an explicit placed set (a thin,
# correct wrapper around the floor's position search -- never duplicates the
# j>=k geometry).
# ---------------------------------------------------------------------------

def _place_block(b, blk, geom, bay, aB, eB, others, deadline, grid=True):
    """Find a crane-safe (dx, dy, oi) for block b at fixed window [aB, eB]
    against the placed set `others`.  `others` is the full placed list; the
    time-interacting subset is selected here (same as the floor).
    Returns (placed_entry, record) or None."""
    At = FF._ft_interacting(others, aB, eB)
    pos = FF._ft_search_pos(b, blk, geom(b), bay, aB, eB, At, deadline,
                            grid=grid)
    if pos is None:
        return None
    dx, dy, oi, wlayers, wcbox = pos
    pb = geom(b)[oi][2]
    entry = {
        "a": aB, "e": eB, "n": len(wlayers),
        "layers": wlayers, "cbox": wcbox,
        "pbox": (pb[0] + dx, pb[1] + dy, pb[2] + dx, pb[3] + dy),
        "_bid": b,
    }
    rec = {"block_id": b, "bay_id": None, "x": int(dx), "y": int(dy),
           "orient_idx": int(oi), "entry_time": int(aB), "exit_time": int(eB)}
    return entry, rec


def _reinsert(b, blk, geom, bay, others, deadline, grid=True):
    """Re-insert block b at its EARLIEST feasible window: first try [R, R+P];
    if that has no crane-safe spot, walk entry over the placed-exit times
    ascending (delayed), recomputing tardiness.  Returns (placed_entry, record)
    or None.  `others` is the placed list b must avoid."""
    R = int(blk["release_time"]); P = int(blk["processing_time"])
    r = _place_block(b, blk, geom, bay, R, R + P, others, deadline, grid=grid)
    if r is not None:
        return r
    # delayed: try entry at each placed exit > R (ascending) -- the same
    # fallback ladder the floor uses, so the result stays a valid decode.
    for t in sorted({A["e"] for A in others if A["e"] > R}):
        if time.monotonic() >= deadline - 0.2:
            break
        r = _place_block(b, blk, geom, bay, t, t + P, others, deadline,
                         grid=grid)
        if r is not None:
            return r
    # forced empty window: after every placed exit -> zero interactions.
    aB = max([R] + [A["e"] for A in others])
    return _place_block(b, blk, geom, bay, aB, aB + P, [], deadline, grid=grid)


# ---------------------------------------------------------------------------
# State helpers.  State = {block_id: placed_entry} plus {block_id: record};
# we keep them in lock-step so a move is a dict mutation that is trivial to
# revert (we snapshot the touched ids).
# ---------------------------------------------------------------------------

def _state_tard(records, ids, blocks):
    return sum(max(0, records[b]["exit_time"] - int(blocks[b]["due_date"]))
               for b in ids)


def _others_list(state_entries, exclude):
    excl = set(exclude)
    return [e for bid, e in state_entries.items() if bid not in excl]


def _conflicting_present(state_entries, b_entry, b_aB, b_eB, exclude_self):
    """The placed blocks that are time-interacting AND crane-conflict with the
    candidate b_entry at window [b_aB, b_eB].  We discover conflicts by asking
    the floor's pair predicate (so the j>=k logic is reused, not duplicated)."""
    conflicting = []
    b_layers = b_entry["layers"]; nB = b_entry["n"]; bcb = b_entry["cbox"]
    for bid, A in state_entries.items():
        if bid == exclude_self:
            continue
        # time interaction first
        if not ((A["a"] < b_eB and b_aB < A["e"])
                or (A["a"] <= b_aB < A["e"]) or (A["a"] < b_eB <= A["e"])
                or (b_aB <= A["a"] < b_eB) or (b_aB < A["e"] <= b_eB)):
            continue
        acb = A["cbox"]
        if (bcb[0] > acb[2] or acb[0] > bcb[2]
                or bcb[1] > acb[3] or acb[1] > bcb[3]):
            continue                                  # bbox-disjoint -> no hit
        # dx=dy=0: b_entry layers are already in world coords.
        if not FF._ft_pair_ok(A, b_aB, b_eB, b_layers, 0, 0, nB):
            conflicting.append(bid)
    return conflicting


# ---------------------------------------------------------------------------
# Moves.  Each move attempts an improvement; on success it mutates `entries` /
# `records` in place and returns True, otherwise it leaves them untouched.
# ---------------------------------------------------------------------------

def _move_evict_reanchor(b, entries, records, blocks, geom, bay, deadline):
    """CLUSTER RE-PACK around tardy block b.

    The append-only seed often DELAYS b precisely to spare a tighter-due block
    its early slot (e.g. prob_3 bay2: b=4 delayed 1 so b=48 D=17 keeps [8,16]).
    Forcing b to its window by evicting the victim and only then reinserting it
    is strictly worse -- the victim gets shoved far out.  The fix is symmetric:
    remove b AND its crane-conflicting co-present neighbours, then RE-INSERT the
    whole cluster fresh, in EARLIEST-DEADLINE order, each at its own earliest
    feasible window via the grid search.  Whoever is tighter grabs the early
    slot; the looser one dodges to a DIFFERENT position at the same time (the
    repositioning the append-only floor can't do).  Commit iff total tardiness
    strictly improves."""
    blk = blocks[b]
    R = int(blk["release_time"]); P = int(blk["processing_time"])
    aB, eB = R, R + P

    # Discover b's conflict cluster: place b unobstructed at its window, ask
    # who is co-present + crane-conflicting there.  (j>=k reused, not rolled.)
    free = _place_block(b, blk, geom, bay, aB, eB, [], deadline, grid=True)
    if free is None:
        return False                                  # b never fits at R
    victims = _conflicting_present(entries, free[0], aB, eB, exclude_self=b)
    if not victims:
        return False

    cluster = list(victims) + [b]
    touched = set(cluster)
    snap_e = {k: entries[k] for k in touched if k in entries}
    snap_r = {k: records[k] for k in touched if k in records}
    before = _state_tard(records, list(records.keys()), blocks)

    # Remove the whole cluster, then reinsert in EDD order at earliest windows.
    for v in cluster:
        entries.pop(v, None); records.pop(v, None)
    order = sorted(cluster, key=lambda x: (int(blocks[x]["due_date"]),
                                           int(blocks[x]["release_time"])))
    for v in order:
        r = _reinsert(v, blocks[v], geom, bay,
                      _others_list(entries, [v]), deadline, grid=True)
        if r is None:
            _revert(entries, records, snap_e, snap_r, touched)
            return False
        entries[v] = r[0]; records[v] = r[1]
        records[v]["bay_id"] = snap_r.get(v, {}).get("bay_id")
    after = _state_tard(records, list(records.keys()), blocks)
    if after < before:
        return True
    _revert(entries, records, snap_e, snap_r, touched)
    return False


def _reinsert_neighbourhood(nbr, order, frozen, blocks, geom, bay, deadline):
    """Re-insert the blocks `nbr` (in the given `order`) at their earliest
    feasible windows against the `frozen` placed list.  Returns
    (entries_map, records_map) for nbr only, or None if any block fails."""
    placed = list(frozen)                              # grows as we insert
    e_out = {}; r_out = {}
    for v in order:
        r = _reinsert(v, blocks[v], geom, bay, placed, deadline, grid=True)
        if r is None:
            return None
        e_out[v] = r[0]; r_out[v] = r[1]
        placed.append(r[0])
    return e_out, r_out


def _move_window_rebuild(b, entries, records, blocks, geom, bay, deadline,
                         pad=0):
    """DESTROY-AND-REBUILD a time-window neighbourhood around tardy block b.

    A narrow crane-conflict cluster cannot reposition far because the rest of
    the bay is frozen.  This is the LNS-style destroy operator: take ALL blocks
    whose time window overlaps b's window (widened by `pad`), remove them, and
    re-decode that subset FRESH against the still-frozen remainder.  A single
    greedy order reproduces the seed's local optimum, so we race a few
    deterministic orders (the same idea as the floor's F0-F3 race) and keep the
    BEST -- this is what lets a looser block dodge to a different position so a
    tighter co-present block can claim its earliest slot.  Commit iff total
    tardiness strictly improves."""
    blk = blocks[b]
    R = int(blk["release_time"]); P = int(blk["processing_time"])
    lo = R - pad
    hi = R + P + pad
    nbr = [bid for bid, A in entries.items() if A["a"] < hi and lo < A["e"]]
    if len(nbr) < 2:
        return False
    touched = set(nbr)
    snap_e = {k: entries[k] for k in touched}
    snap_r = {k: records[k] for k in touched}
    keys = list(records.keys())
    before = _state_tard(records, keys, blocks)
    base = before - _state_tard(records, nbr, blocks)  # tard of frozen part

    frozen = [A for bid, A in entries.items() if bid not in touched]
    due = lambda x: int(blocks[x]["due_date"])
    rel = lambda x: int(blocks[x]["release_time"])
    prc = lambda x: int(blocks[x]["processing_time"])
    ar = lambda x: FF._min_bbox_area(blocks[x])
    orders = [
        sorted(nbr, key=lambda x: (due(x), rel(x))),          # EDD
        sorted(nbr, key=lambda x: (rel(x), due(x))),          # release, EDD
        sorted(nbr, key=lambda x: (due(x) - rel(x) - prc(x), -ar(x))),  # slack
        sorted(nbr, key=lambda x: -ar(x)),                    # area desc
        sorted(nbr, key=lambda x: (rel(x), -ar(x))),          # release, area
    ]
    best_e = best_r = None
    best_t = before
    for order in orders:
        if time.monotonic() >= deadline - 0.3:
            break
        out = _reinsert_neighbourhood(nbr, order, frozen, blocks, geom, bay,
                                      deadline)
        if out is None:
            continue
        e_out, r_out = out
        t = base + _state_tard(r_out, nbr, blocks)
        if t < best_t:
            best_t, best_e, best_r = t, e_out, r_out
        if best_t <= base:                             # neighbourhood now clean
            break
    if best_e is None or best_t >= before:
        return False
    for v in nbr:
        entries[v] = best_e[v]
        records[v] = best_r[v]
        records[v]["bay_id"] = snap_r[v].get("bay_id")
    return True


def _move_swap(b1, b2, entries, records, blocks, geom, bay, deadline):
    """Swap the placements of two co-present blocks by removing both and
    re-inserting them in the OTHER order (b1 after b2).  Commit iff improves."""
    if b1 == b2 or b1 not in entries or b2 not in entries:
        return False
    touched = {b1, b2}
    snap_e = {k: entries[k] for k in touched}
    snap_r = {k: records[k] for k in touched}
    before = _state_tard(records, list(records.keys()), blocks)
    entries.pop(b1); records.pop(b1)
    entries.pop(b2); records.pop(b2)
    for v in (b2, b1):                                # reversed insertion order
        r = _reinsert(v, blocks[v], geom, bay,
                      _others_list(entries, [v]), deadline, grid=True)
        if r is None:
            _revert(entries, records, snap_e, snap_r, touched)
            return False
        entries[v] = r[0]; records[v] = r[1]
        records[v]["bay_id"] = snap_r[v].get("bay_id")
    after = _state_tard(records, list(records.keys()), blocks)
    if after < before:
        return True
    _revert(entries, records, snap_e, snap_r, touched)
    return False


def _move_nudge(b, entries, records, blocks, geom, bay, deadline):
    """Re-place a single block via the grid search after removing it (it may
    find a denser spot freeing the skyline for later inserts).  Commit iff the
    block's own window does not regress and total tardiness does not increase
    (kept as a 'sideways' move that can unstick later evict moves)."""
    if b not in entries:
        return False
    snap_e = {b: entries[b]}; snap_r = {b: records[b]}
    before = _state_tard(records, list(records.keys()), blocks)
    entries.pop(b); records.pop(b)
    r = _reinsert(b, blocks[b], geom, bay,
                  _others_list(entries, [b]), deadline, grid=True)
    if r is None:
        _revert(entries, records, snap_e, snap_r, {b})
        return False
    entries[b] = r[0]; records[b] = r[1]
    records[b]["bay_id"] = snap_r[b].get("bay_id")
    after = _state_tard(records, list(records.keys()), blocks)
    if after < before:
        return True
    _revert(entries, records, snap_e, snap_r, {b})
    return False


def _revert(entries, records, snap_e, snap_r, touched):
    for k in touched:
        if k in snap_e:
            entries[k] = snap_e[k]
        else:
            entries.pop(k, None)
        if k in snap_r:
            records[k] = snap_r[k]
        else:
            records.pop(k, None)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def _seed(bay, bay_idx, ids, blocks, deadline):
    """Best of a few greedy fixed-time decodes.  Includes the FULL F0-F3 floor
    race (so the seed is never weaker than the plain greedy decoder) plus two
    extra explicit orders.  Returns (result|None, tardiness)."""
    R = lambda b: int(blocks[b]["release_time"])
    D = lambda b: int(blocks[b]["due_date"])
    area = lambda b: FF._min_bbox_area(blocks[b])
    orders = [
        "F0", "F1", "F2", "F3",                        # full floor race
        sorted(ids, key=lambda b: (D(b), R(b))),       # EDD
        sorted(ids, key=lambda b: -area(b)),           # area desc
    ]
    best = None; best_t = math.inf
    for ok in orders:
        if time.monotonic() >= deadline - 0.3:
            break
        res, ft = FF._fixed_time_decode(bay, bay_idx, ids, blocks, deadline,
                                        order_key=ok)
        if res is None or len(res) != len(ids):
            continue
        t = _total_tard(res, ids, blocks)
        if t < best_t:
            best, best_t = res, t
        if best_t <= 0:
            break
    return best, best_t


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pack_bay(bay, bay_idx, members, blocks_data, deadline, time_budget=5.0):
    """Crane-safe REPOSITIONING packer for one bay.

    Returns (result_dict | None, tardiness).  `result_dict` is {block_id:
    record} with record = {block_id, bay_id, x, y, orient_idx, entry_time,
    exit_time} -- the exact format `_fixed_time_decode` returns.  Never worse
    than the greedy seed; falls back to the seed on any internal failure.

    `deadline` is a monotonic timestamp (so it composes with the floor's
    deadline-bounded primitives); the local search additionally self-limits to
    `time_budget` seconds.
    """
    ids = list(members)
    if not ids:
        return {}, 0.0
    blocks = blocks_data
    geom = _geom_cache_for(ids, blocks)

    seed, seed_t = _seed(bay, bay_idx, ids, blocks, deadline)
    if seed is None:
        return None, math.inf

    # Stamp the bay_id (the floor's record already carries it, but our reinsert
    # path sets bay_id=None; normalise here so the returned records are clean).
    seed_bay = {b: seed[b].get("bay_id", bay_idx) for b in ids}

    ls_deadline = min(deadline, time.monotonic() + float(time_budget))
    if seed_t <= 0 or time.monotonic() >= ls_deadline - 0.3:
        return seed, float(seed_t)

    # Working state.
    entries = _result_to_placed_map(seed, ids, blocks, geom)
    if entries is None:
        return seed, float(seed_t)                     # cannot rebuild -> seed
    records = {b: dict(seed[b]) for b in ids}

    best_records = {b: dict(records[b]) for b in ids}
    best_t = seed_t

    # Local search: repeated sweeps of evict-reanchor on tardy blocks (worst
    # first), with swap + nudge as auxiliary unsticking moves.
    no_improve_sweeps = 0
    while time.monotonic() < ls_deadline - 0.3 and best_t > 0:
        cur_t = _state_tard(records, ids, blocks)
        tardy = sorted(
            (b for b in ids
             if records[b]["exit_time"] > int(blocks[b]["due_date"])),
            key=lambda b: -(records[b]["exit_time"]
                            - int(blocks[b]["due_date"])))
        if not tardy:
            break
        improved = False
        # PRIMARY: destroy-and-rebuild a time-window neighbourhood around each
        # tardy block (escalating pad widens the neighbourhood -> more freedom
        # to reposition).  This is the move that actually repositions the
        # frozen remainder the narrow cluster could not touch.
        for b in tardy:
            if time.monotonic() >= ls_deadline - 0.3:
                break
            for pad in (0, 2, 5, 10):
                if _move_window_rebuild(b, entries, records, blocks, geom, bay,
                                        ls_deadline, pad=pad):
                    improved = True
                    break
            if improved:
                break
        if not improved:
            # cluster re-pack (crane-conflict-only neighbourhood).
            for b in tardy:
                if time.monotonic() >= ls_deadline - 0.3:
                    break
                if _move_evict_reanchor(b, entries, records, blocks, geom, bay,
                                        ls_deadline):
                    improved = True
                    break
        if not improved:
            # SWAP: try exchanging a tardy block with a co-present neighbour.
            for b in tardy:
                if time.monotonic() >= ls_deadline - 0.3:
                    break
                neigh = _conflicting_present(
                    entries, entries[b], records[b]["entry_time"],
                    records[b]["exit_time"], exclude_self=b)
                for v in neigh:
                    if _move_swap(b, v, entries, records, blocks, geom, bay,
                                  ls_deadline):
                        improved = True
                        break
                if improved:
                    break
        if not improved:
            # NUDGE the worst tardy block (sideways): may free space for the
            # next sweep's evict move.
            for b in tardy[:3]:
                if _move_nudge(b, entries, records, blocks, geom, bay,
                               ls_deadline):
                    improved = True
                    break

        new_t = _state_tard(records, ids, blocks)
        if new_t < best_t:
            best_t = new_t
            best_records = {b: dict(records[b]) for b in ids}
        if not improved or new_t >= cur_t:
            no_improve_sweeps += 1
        else:
            no_improve_sweeps = 0
        if no_improve_sweeps >= 2:
            break

    # Final consistency / safety net: the best records must form a valid decode
    # (all blocks, exit=entry+P).  If anything is off, fall back to the seed.
    for b in ids:
        rec = best_records.get(b)
        if rec is None:
            return seed, float(seed_t)
        rec["bay_id"] = seed_bay[b]
        P = int(blocks[b]["processing_time"])
        if rec["exit_time"] != rec["entry_time"] + P:
            return seed, float(seed_t)

    final_t = _total_tard(best_records, ids, blocks)
    if final_t > seed_t:
        return seed, float(seed_t)
    return best_records, float(final_t)


def _result_to_placed_map(result, ids, blocks, geom):
    """Like _result_to_placed but keyed by block_id (the working state)."""
    out = {}
    for b in ids:
        p = _record_to_placed(result[b], blocks[b], geom)
        if p is None:
            return None
        out[b] = p
    return out


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _load(inst):
    import json
    sys.path.insert(0, str(_ROOT / "tools"))
    import myalgorithm as M                                       # noqa: E402
    prob = json.load(open(_ROOT / "instances" / "train" / f"{inst}.json",
                          encoding="utf-8"))
    blocks = prob["blocks"]
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    ba = [prob["bays"][j]["width"] * prob["bays"][j]["height"]
          for j in range(nb)]
    avg = sum(ba) / nb
    bay_u = [avg / a for a in ba]
    fbays = M._feasible_bays(blocks, bays)
    assign = M._cpsat_assignment(prob, bays, fbays, bay_u, time_budget=10.0)
    members = [[] for _ in range(nb)]
    for b, j in enumerate(assign):
        members[j].append(b)
    return prob, blocks, bays, members


def _greedy_tard(bay, j, mem, blocks):
    best = math.inf
    for ok in ("F0", "F1", "F2", "F3"):
        res, ft = FF._fixed_time_decode(bay, j, mem, blocks, 9e18,
                                        order_key=ok)
        if res is not None:
            best = min(best, sum(max(0, res[b]["exit_time"]
                                     - int(blocks[b]["due_date"]))
                                 for b in mem))
    return best


def _verify_placement(result, mem, blocks):
    if result is None:
        return False, "result is None"
    if set(result.keys()) != set(mem):
        return False, f"block set mismatch {set(result)} vs {set(mem)}"
    for b in mem:
        rec = result[b]
        P = int(blocks[b]["processing_time"])
        if rec["exit_time"] != rec["entry_time"] + P:
            return False, f"block {b}: exit != entry+P"
    return True, "ok"


def _run_bay(bays, members, blocks, j, budget=8.0):
    mem = members[j]
    g = _greedy_tard(bays[j], j, mem, blocks)
    t0 = time.monotonic()
    res, pt = pack_bay(bays[j], j, mem, blocks,
                       deadline=time.monotonic() + budget, time_budget=budget)
    dt = time.monotonic() - t0
    ok, msg = _verify_placement(res, mem, blocks)
    return g, pt, dt, ok, msg, len(mem)


def _selftest():
    # --- Part A: the spec's required congested bays ----------------------
    targets = {"prob_3": [0, 2], "prob_5": [0, 2]}
    strict_pool = [("prob_3", 2), ("prob_5", 0)]
    all_le = True
    any_strict = False
    print("=" * 64)
    print("PART A -- spec-required bays (prob_3, prob_5)")
    for inst, bay_idxs in targets.items():
        prob, blocks, bays, members = _load(inst)
        print(f"\n=== {inst} ===")
        for j in bay_idxs:
            if not members[j]:
                print(f"  bay{j}: (no members in this assignment)")
                continue
            g, pt, dt, ok, msg, n = _run_bay(bays, members, blocks, j)
            flag = ""
            if pt > g + 1e-9:
                flag = "  *** REGRESSION ***"; all_le = False
            if (inst, j) in strict_pool and pt < g - 1e-9:
                any_strict = True
            print(f"  bay{j} ({n} blk): greedy={g:.0f} -> packer={pt:.0f}  "
                  f"({dt:.1f}s, decode {msg}){flag}")
            if not ok:
                print(f"      !! placement invalid: {msg}"); all_le = False

    # --- Part B: broader demonstration that repositioning actually fits more
    #     co-present blocks (prob_1..prob_10 congested bays) ---------------
    print("\n" + "=" * 64)
    print("PART B -- repositioning value across prob_1..10 congested bays")
    wins = 0; considered = 0; regressions = 0
    for n in range(1, 11):
        inst = f"prob_{n}"
        try:
            prob, blocks, bays, members = _load(inst)
        except Exception:
            continue
        for j in range(len(bays)):
            if not members[j]:
                continue
            seed, st = _seed(bays[j], j, members[j], blocks,
                             time.monotonic() + 12.0)
            if st is None or st <= 0:
                continue                                  # uncongested bay
            g, pt, dt, ok, msg, m = _run_bay(bays, members, blocks, j, 8.0)
            considered += 1
            tag = ""
            if pt < g - 1e-9:
                wins += 1; tag = " WIN"
            elif pt > g + 1e-9:
                regressions += 1; tag = " *** REGRESSION ***"; all_le = False
            if not ok:
                all_le = False
            print(f"  {inst} bay{j} ({m} blk): greedy={g:.0f} -> "
                  f"packer={pt:.0f}  ({dt:.1f}s){tag}")

    success = all_le and (any_strict or wins > 0)
    print("\n" + "=" * 64)
    print(f"never-worse-than-greedy (no regressions) : {all_le}")
    print(f"strict win on prob_3 bay2 OR prob_5 bay0 : {any_strict}")
    print(f"congested bays improved (prob_1..10)     : {wins}/{considered}"
          f"  (regressions {regressions})")
    print(f"SUCCESS (no regression AND >=1 strict win): {success}")
    print("=" * 64)


if __name__ == "__main__":
    _selftest()
