"""postproc.py -- v3 crane-repack post-process, additive & never-worse.

Wraps the v3 UNIFIED improvement loop (run_full.py) as a reusable function that
takes a finished best-of solution and polishes it within a wall-clock deadline:

  postprocess(prob_info, solution, deadline_monotonic) -> solution

Each pass is a coordinate-descent step (x/y/o crane-repack per tardy bay) or a
cross-bay move/swap, GATED never-worse on the FULL official objective
(v3pp.seed.global_eval).  A trial is accepted iff it is feasible AND total obj
strictly improves.  The loop stops when time.monotonic() >= deadline or a whole
round accepts nothing (converged).

NEVER-WORSE CONTRACT
--------------------
* The whole body is wrapped in try/except: on ANY failure (import, deserialize,
  CP-SAT crash, infeasible reconstruction, ...) we return the ORIGINAL `solution`
  unchanged.  A feasible best-of submission can never become infeasible or worse.
* The base solution is re-evaluated with the official checker first; if it is not
  feasible (shouldn't happen for a real sol) we also return the original.
* Only strictly-improving, feasible trials are ever adopted, so the returned
  serialized solution is >= the input in objective by construction.

The v3 modules live in the isolated `v3pp` package (their own temporal_pack /
gridmap / density_pack so they don't collide with the v2 solver's top-level
versions; utils is the shared official one).
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# helpers lifted verbatim from run_full.py (kept module-local)
# ---------------------------------------------------------------------------
def _pass_cap(n_bay_blocks, remaining, n_active_bays):
    """Adaptive per-pass CP-SAT wall cap (seconds) -- identical to run_full.
    OGC_PP_CAP_SCALE (default 1.0): scale the cap down for more, shorter passes
    (deadline-bound -> more attempts, never-worse keeps the best)."""
    size_cap = min(40.0, max(12.0, 0.30 * n_bay_blocks))
    budget_cap = remaining / max(1.0, 2.0 * n_active_bays)
    cap = max(8.0, min(size_cap, max(budget_cap, 10.0), remaining))
    _sc = float(os.environ.get("OGC_PP_CAP_SCALE", "1.0"))
    if _sc != 1.0:
        cap = max(3.0, min(cap * _sc, remaining))
    return float(cap)


# coordinate-descent axes per round.  Default x,y,o.  Add diagonals: "x,y,d1,d2,o".
_PP_AXES = [a for a in (os.environ.get("OGC_PP_AXES") or "x,y,o").split(",") if a]


def _axis_kwargs(axis, K):
    # returns (n_xcand, n_ycand, n_ocand, n_d1cand, n_d2cand)
    if axis == "x":
        return (K, 0, 0, 0, 0)
    if axis == "y":
        return (0, K, 0, 0, 0)
    if axis == "o":
        return (0, 0, K, 0, 0)
    if axis == "d1":          # ↗ diagonal (x and y up together)
        return (0, 0, 0, K, 0)
    if axis == "d2":          # ↘ diagonal (x up, y down)
        return (0, 0, 0, 0, K)
    raise ValueError("unknown axis '%s'" % axis)


def _bz1(data, pl):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def _preferred(data, bid):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def _z3_contrib(data, bid, cur_bay):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(prefs) - prefs[cur_bay]


# ---------------------------------------------------------------------------
def _run_loop(data, cur, cur_obj, deadline, K=5):
    """run_full.main()'s round loop, deadline-driven, quiet, gated never-worse.

    Returns (best_bays_placed, best_obj).  Only strictly-improving feasible
    trials are adopted, so (cur, cur_obj) only ever improves.
    """
    from v3pp import seed as S
    from v3pp import crane_cpsat as C
    from v3pp import bpass as B

    # OGC_PP_K: candidate count per block (default 5).  Fewer candidates ->
    # combos ∝ K^2 -> FEWER disjunctions -> smaller CP-SAT model (solve+build both ↓).
    # Quality trade-off (less search/pass) -> A/B.
    K = int(os.environ.get("OGC_PP_K", str(K)))

    while time.monotonic() < deadline - 1.0:
        round_accepts = 0

        # ---- SPATIAL: x/y/o coordinate descent on tardy bays ----
        bays_t = [(j, _bz1(data, pl)) for j, pl in cur.items()]
        bays_t = [(j, z) for j, z in bays_t if z > 0]
        bays_t.sort(key=lambda x: -x[1])
        n_active_bays = len(bays_t)
        _axes = [a for a in (os.environ.get("OGC_PP_AXES") or "x,y,o").split(",") if a]
        for j, _z1 in bays_t:
            for axis in _axes:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                remaining = deadline - now
                ts = _pass_cap(len(cur[j]), remaining, n_active_bays)
                nxc, nyc, noc, nd1, nd2 = _axis_kwargs(axis, K)
                try:
                    new_pl, st, wall, _info = C.crane_repack_bay(
                        data, j, cur[j], ts, n_xcand=nxc, n_ycand=nyc, n_ocand=noc,
                        n_d1cand=nd1, n_d2cand=nd2)
                except TypeError:
                    new_pl, st, wall, _info = C.crane_repack_bay(
                        data, j, cur[j], ts, n_xcand=nxc, n_ycand=nyc, n_ocand=noc)
                if new_pl is None:
                    continue
                trial = dict(cur)
                trial[j] = new_pl
                ev = S.global_eval(data, trial)
                _acc = (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6)
                if os.environ.get("OGC_PP_PASSLOG"):
                    print(f"[PASS] {axis}-pass bay={j} n={len(cur[j])} "
                          f"wall={time.monotonic()-now:6.1f}s "
                          f"dobj={(cur_obj-ev['obj']) if _acc else 0:>12,.0f} acc={_acc}",
                          flush=True)
                if _acc:
                    cur = trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
            if time.monotonic() >= deadline - 1.0:
                break

        # ---- CROSS-BAY: move/swap on tardy + wrong-bay blocks ----
        targets = []
        for j, placed in cur.items():
            for p in placed:
                bid = p["id"]
                due = data["blocks"][bid].get("due_date", 0)
                if p["exit"] <= due:
                    continue
                k = _preferred(data, bid)
                if k == j:
                    continue
                targets.append((bid, _z3_contrib(data, bid, j), p["exit"] - due))
        targets.sort(key=lambda t: (t[1], t[2]), reverse=True)

        for bid, z3c, _late in targets:
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            remaining = deadline - now
            pref_bay = _preferred(data, bid)
            dest_n = len(cur.get(pref_bay, []))
            ts = _pass_cap(dest_n, remaining, max(1, n_active_bays))

            # --- try_move ---
            trial, _info = B.try_move(data, cur, bid, ts, n_xcand=K)
            accepted_here = False
            if trial is not None:
                ev = S.global_eval(data, trial)
                if (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6):
                    cur = trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
                    accepted_here = True
            if accepted_here:
                continue

            # --- try_swap (only if move didn't improve) ---
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            ts = _pass_cap(dest_n, deadline - now, max(1, n_active_bays))
            s_trial, s_info = B.try_swap(data, cur, bid, ts, n_xcand=K)
            if s_trial is None:
                continue
            ev = S.global_eval(data, s_trial)
            if (ev["feasible"] and ev["obj"] is not None
                    and ev["obj"] < cur_obj - 1e-6):
                cur = s_trial
                cur_obj = ev["obj"]
                round_accepts += 1

        # ---- MOVEALL (OGC_PP_MOVEALL): move tardy block to ANY bay (z1 lever) ----
        if os.environ.get("OGC_PP_MOVEALL", "0") == "1":
            nbay = len(data["bays"])
            mv = [(p["exit"] - data["blocks"][p["id"]].get("due_date", 0), jj, p["id"])
                  for jj, pl in cur.items() for p in pl
                  if p["exit"] > data["blocks"][p["id"]].get("due_date", 0)]
            mv.sort(reverse=True)        # worst tardy first
            for _lat, jj, bid in mv:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                p = next((q for q in cur.get(jj, []) if q["id"] == bid), None)
                if p is None:
                    continue
                ts = _pass_cap(8, deadline - now, max(1, n_active_bays))
                for tb in range(nbay):
                    if tb == jj:
                        continue
                    b_seed = B._seed_into_bay(data, tb, p)
                    placed_new = list(cur.get(tb, [])) + [b_seed]
                    try:
                        new_k, _st, _w, _ci = C.crane_repack_bay(
                            data, tb, placed_new, ts, n_xcand=K, free_ids={bid})
                    except Exception:
                        new_k = None
                    if new_k is None:
                        continue
                    trial = dict(cur)
                    trial[jj] = [q for q in cur[jj] if q["id"] != bid]
                    trial[tb] = new_k
                    ev = S.global_eval(data, trial)
                    if (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6):
                        if os.environ.get("OGC_PP_PASSLOG"):
                            print(f"[PASS] moveall blk={bid} {jj}->{tb} "
                                  f"dobj={cur_obj-ev['obj']:>12,.0f} acc=True", flush=True)
                        cur, cur_obj = trial, ev["obj"]
                        round_accepts += 1
                        break

        if round_accepts == 0:
            break

    return cur, cur_obj


# ---------------------------------------------------------------------------
def postprocess(prob_info, solution, deadline_monotonic, K=5):
    """Polish a finished best-of `solution` until `deadline_monotonic`.

    ADDITIVE + NEVER-WORSE: returns either an improved-and-feasible solution or
    the ORIGINAL `solution` unchanged.  Any exception => original solution.
    """
    try:
        from v3pp import adapter
        from v3pp import seed as S

        bays_placed = adapter.deserialize(prob_info, solution)
        base = S.global_eval(prob_info, bays_placed)
        # If the reconstruction isn't feasible (shouldn't happen for a real sol),
        # don't risk returning a re-serialized version -- keep the original.
        if not base["feasible"] or base["obj"] is None:
            return solution

        best_bays, best_obj = _run_loop(
            prob_info, bays_placed, base["obj"], deadline_monotonic, K=K)

        # Only return a re-serialized solution if we STRICTLY improved AND it is
        # still feasible; otherwise hand back the untouched original.
        if best_obj < base["obj"] - 1e-6:
            final = S.global_eval(prob_info, best_bays)
            if final["feasible"] and final["obj"] is not None \
                    and final["obj"] < base["obj"] - 1e-6:
                return S.serialize(best_bays)
        return solution
    except Exception:
        return solution


__all__ = ["postprocess"]
