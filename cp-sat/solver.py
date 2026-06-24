"""
solver.py -- the LBBD driver that ties the two CP-SAT models together.

Loop:
    1. CP-SAT MASTER  -> bay assignment + relaxed schedule (full objective).
    2. CP-SAT PER-BAY -> for each bay, the true (orient, x, y, entry, exit)
                          packing with the exact crane rule + true tardiness.
    3. CUTS           -> bay infeasible  => no-good cut (reassign);
                          true Z1 > relaxed => cardinality cut (over-packed).
    4. Keep the best grader-VERIFIED solution; warm-start the next round.

A trivial serial-per-bay layout is computed once as a feasibility FLOOR so the
solver can never return -1 even if every CP-SAT solve times out.  The floor is
the only non-CP-SAT code path and it is a safety net, not the solver.
"""

from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import utils  # noqa: E402  (official checker)

import geom            # noqa: E402
import data            # noqa: E402
import master_cp       # noqa: E402
import bay_pack_cp     # noqa: E402
import cuts            # noqa: E402


# -----------------------------------------------------------------------------
# Output assembly + verification
# -----------------------------------------------------------------------------
def place_to_ops(place: dict[int, dict]) -> dict:
    """{bid: placement} -> the grader's operations dict (EXIT before ENTRY)."""
    buckets: dict[int, list[tuple]] = {}
    for bid, p in place.items():
        te, tx = int(p["entry_time"]), int(p["exit_time"])
        buckets.setdefault(tx, []).append((0, "EXIT", bid, p["bay_id"], None, None, None))
        buckets.setdefault(te, []).append((1, "ENTRY", bid, p["bay_id"],
                                           p["x"], p["y"], p["orient_idx"]))
    ops: dict[str, list[dict]] = {}
    for t in sorted(buckets):
        row = []
        for _, kind, bid, bay, x, y, o in sorted(buckets[t], key=lambda r: (r[0], r[2])):
            d = {"type": kind, "block_id": bid, "bay_id": bay}
            if kind == "ENTRY":
                d["x"], d["y"], d["orient_idx"] = x, y, o
            row.append(d)
        ops[str(t)] = row
    return {"operations": ops}


def _verify(prob_info: dict, place: dict[int, dict]):
    """Return (ops, objective) if grader-feasible, else (None, None)."""
    ops = place_to_ops(place)
    res = utils.check_feasibility(prob_info, ops)
    if res.get("feasible"):
        return ops, res["objective"]
    return None, None


# -----------------------------------------------------------------------------
# Feasibility floor (serial per bay) -- pure, deterministic, never -1
# -----------------------------------------------------------------------------
def serial_floor(prob: data.Problem) -> dict[int, dict]:
    """Assign each block to its most-preferred fitting bay, place it bottom-left,
    and serialise blocks within a bay by EDD so none ever co-exist."""
    place: dict[int, dict] = {}
    bay_free: dict[int, int] = {j: 0 for j in range(prob.n_bays)}
    order = sorted(prob.blocks, key=lambda b: (b.D, b.R))
    for bs in order:
        # try fitting bays in preference order (highest preference = lowest z3);
        # use the first that yields an integer placement -- never crash.
        ranked = sorted(bs.fitting_bays,
                        key=lambda jj: (-(bs.prefs[jj] if jj < len(bs.prefs) else 0), jj))
        chosen = None
        for j in ranked:
            cs = geom.gen_candidates(bs.data, prob.bays[j].W, prob.bays[j].H,
                                     cap=1, nx=1, ny=1)
            if cs:
                chosen = (j, cs[0])
                break
        if chosen is None:
            # last resort (should not happen): place at origin in the first bay
            chosen = (bs.fitting_bays[0], (0, 0, 0))
        j, (o, x, y) = chosen
        entry = max(bs.R, bay_free[j])
        ex = entry + bs.P
        bay_free[j] = ex
        place[bs.bid] = {"x": x, "y": y, "orient_idx": o,
                         "entry_time": entry, "exit_time": ex, "bay_id": j}
    return place


# -----------------------------------------------------------------------------
# Main LBBD solve
# -----------------------------------------------------------------------------
def lbbd_solve(prob_info: dict, timelimit: float, verbose: bool = False) -> dict:
    t0 = time.monotonic()
    reserve = min(5.0, 0.1 * timelimit)
    deadline = t0 + max(1.0, timelimit - reserve)

    def remaining() -> float:
        return deadline - time.monotonic()

    def log(msg):
        if verbose:
            print(f"[cp-sat {time.monotonic() - t0:6.1f}s] {msg}", file=sys.stderr)

    prob = data.parse(prob_info)
    H = data.horizon(prob)

    # --- feasibility floor ---------------------------------------------------
    best_place = serial_floor(prob)
    best_ops, best_obj = _verify(prob_info, best_place)
    if best_ops is None:
        # Should never happen; emit the floor regardless so we never crash.
        log("WARNING: serial floor failed verification")
        best_ops = place_to_ops(best_place)
        best_obj = float("inf")
    log(f"floor objective = {best_obj}")

    nogoods: list[tuple[int, frozenset]] = []
    card_cuts: list[tuple[int, frozenset, int]] = []
    hint: dict | None = None
    max_iters = 12
    no_improve = 0

    for it in range(max_iters):
        if remaining() < 2.0:
            break
        m_budget = min(max(1.0, remaining() * 0.30), 20.0)
        assign, relaxed = master_cp.solve_master(
            prob, nogoods, card_cuts, H, m_budget, hint=hint)
        if assign is None:
            log(f"iter {it}: master infeasible/timeout")
            break

        groups: dict[int, list] = {}
        for bs in prob.blocks:
            groups.setdefault(assign[bs.bid], []).append(bs)

        # budget split across bays by block count
        bay_pool = max(1.0, remaining() * 0.6)
        total_blocks = sum(len(v) for v in groups.values()) or 1

        new_place: dict[int, dict] = {}
        complete = True
        added = 0
        for j, ids in groups.items():
            if remaining() < 0.7:
                complete = False
                break
            warm = {b.bid: (best_place[b.bid]["orient_idx"], best_place[b.bid]["x"],
                            best_place[b.bid]["y"], best_place[b.bid]["entry_time"])
                    for b in ids if best_place.get(b.bid, {}).get("bay_id") == j}
            b_budget = max(0.5, bay_pool * len(ids) / total_blocks)
            res, true_z1, status = bay_pack_cp.solve_bay(
                prob.bays[j], ids, H, min(b_budget, remaining() - 0.3), warm=warm)
            log(f"  bay {j}: {len(ids)} blocks budget={b_budget:.1f}s "
                f"-> {status} z1={true_z1}")
            if status == "nofit":
                nogoods.append((j, frozenset(b.bid for b in ids)))
                added += 1
                complete = False
                continue
            if status == "timeout" or res is None:
                complete = False
                continue
            new_place.update(res)
            # over-pack detection -> cardinality cut
            if true_z1 > relaxed.get(j, 0):
                clique = cuts.time_overlap_clique(res)
                if len(clique) >= 2:
                    card_cuts.append((j, frozenset(clique), len(clique) - 1))
                    added += 1

        improved = False
        if complete and len(new_place) == prob.n_blocks:
            ops, obj = _verify(prob_info, new_place)
            if ops is not None and obj < best_obj:
                best_ops, best_obj, best_place = ops, obj, dict(new_place)
                log(f"iter {it}: accepted objective = {obj}")
                improved = True
            else:
                log(f"iter {it}: complete, objective = {obj} (best {best_obj})")
            hint = dict(assign)

        no_improve = 0 if improved else no_improve + 1
        if complete and added == 0:
            log(f"iter {it}: converged (no cuts)")
            break
        if no_improve >= 2:
            log(f"iter {it}: stopping ({no_improve} non-improving iters)")
            break

    log(f"final objective = {best_obj}")
    return best_ops
