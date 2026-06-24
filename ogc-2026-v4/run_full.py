"""run_full.py -- UNIFIED improvement loop: coordinate-descent (x/y/o) + cross-bay
(move/swap) in one alternating round, gated never-worse on the FULL objective.

This driver fuses two passes that were previously run alone:
  * SPATIAL  (from run_cd.py): per tardy bay, optimise one spatial axis at a time
    -- x, y, o -- via crane_repack_bay (entry times are re-solved inside every
    spatial pass; we DROP the pure-'t' axis because timing is already joint).
  * CROSS-BAY (from bpass.py): for each tardy + wrong-bay block, try_move it into
    its preferred bay; if that doesn't improve, try_swap it with a partner block
    in the preferred bay (free_ids on both bays).

Every pass is gated by the OFFICIAL checker (seed.global_eval): accept iff the
trial is feasible AND total obj strictly improves (obj < cur - 1e-6).  A whole
round (spatial + cross-bay) that accepts nothing => converged.

ADAPTIVE CP-SAT CAP  (see _pass_cap)
------------------------------------
Every crane_repack_bay call -- spatial axes AND the repacks inside try_move /
try_swap -- uses a per-pass cap from _pass_cap(n_bay_blocks, remaining,
n_active_bays).  Two ideas:
  (1) the cap GROWS with the bay's block-count -- big bays pay an ~8-9s precompute
      tax (building crane booleans, OUTSIDE the CP-SAT timer) that a fixed 20s cap
      turns into ~31% overhead; a larger cap amortizes that tax + covers the
      (~10s) solve plateau.  Small bays precompute cheaply and plateau fast, so a
      smaller cap is plenty and lets more rounds fit.
  (2) the cap is BOUNDED by the remaining budget divided over the active bays so
      one pass can't eat the whole budget -- multiple rounds still fit.

Usage: python run_full.py [prob=prob_38] [total_time_s=600] [K=5]
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter          # noqa: E402
import seed as S        # noqa: E402
import crane_cpsat as C # noqa: E402
import bpass as B       # noqa: E402


def _pass_cap(n_bay_blocks, remaining, n_active_bays):
    """Adaptive per-pass CP-SAT wall cap (seconds), replacing the old fixed 20s.

    size_cap   = min(40, max(12, 0.30 * n_bay_blocks))
                 -> ~12s @<=40 blk, ~32s @107 blk, clamped to a [12,40]s band.
                 Bigger bay => bigger cap so the ~8-9s precompute tax amortizes
                 and the ~10s solve plateau is covered.
    budget_cap = remaining / (2 * n_active_bays)
                 -> don't let one pass spend the whole remaining budget; reserve
                 room so several rounds still fit (floored at 10s so we never
                 starve a pass when remaining is large).
    Result is clamped to [8s, remaining] so we never overshoot the deadline.
    """
    size_cap = min(40.0, max(12.0, 0.30 * n_bay_blocks))
    budget_cap = remaining / max(1.0, 2.0 * n_active_bays)
    return float(max(8.0, min(size_cap, max(budget_cap, 10.0), remaining)))


def _axis_kwargs(axis: str, K: int):
    """x/y/o axis letter -> (n_xcand, n_ycand, n_ocand).  No 't' (timing is joint)."""
    if axis == "x":
        return (K, 0, 0)
    if axis == "y":
        return (0, K, 0)
    if axis == "o":
        return (0, 0, K)
    raise ValueError(f"unknown axis '{axis}' (expected one of x/y/o)")


def _bz1(data, pl):
    """Single-bay tardiness (sum of max(0, exit-due))."""
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def _preferred(data, bid):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def _z3_contrib(data, bid, cur_bay):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(prefs) - prefs[cur_bay]


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    K = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    data = json.load(open(os.path.join("..", "instances", "train", prob + ".json"),
                          encoding="utf-8"))
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"real_{prob}.json")
    if not os.path.isfile(real):
        print(f"missing {real}", flush=True)
        return
    sol = json.load(open(real, encoding="utf-8"))
    cur = adapter.deserialize(data, sol)
    base = S.global_eval(data, cur)
    cur_obj = base["obj"]

    print(f"=== {prob} RUN-FULL  (TL={tl:.0f}s K={K} cap=ADAPTIVE/pass) ===",
          flush=True)
    print(f"BEFORE obj={base['obj']} z1={base['z1']} z2={base['z2']} z3={base['z3']} "
          f"feas={base['feasible']}", flush=True)
    if not base["feasible"]:
        print("infeasible -- abort", flush=True)
        return

    # per-category ACCEPT accounting: which lever carries the gains.
    cats = ["x", "y", "o", "move", "swap"]
    acc = {c: {"n": 0, "obj_gain": 0.0} for c in cats}

    t0 = time.monotonic()
    deadline = t0 + tl
    rnd = 0

    while time.monotonic() < deadline - 1.0:
        rnd += 1
        round_accepts = 0

        # ============ SPATIAL: x/y/o coordinate descent on tardy bays ========
        bays_t = [(j, _bz1(data, pl)) for j, pl in cur.items()]
        bays_t = [(j, z) for j, z in bays_t if z > 0]
        bays_t.sort(key=lambda x: -x[1])
        n_active_bays = len(bays_t)        # tardy bays this round (budget divisor)
        for j, _z1 in bays_t:
            for axis in "xyo":
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                remaining = deadline - now
                ts = _pass_cap(len(cur[j]), remaining, n_active_bays)
                nxc, nyc, noc = _axis_kwargs(axis, K)
                z1_before = _bz1(data, cur[j])
                p0 = time.monotonic()
                try:
                    new_pl, st, wall, _info = C.crane_repack_bay(
                        data, j, cur[j], ts, n_xcand=nxc, n_ycand=nyc, n_ocand=noc)
                except TypeError:
                    new_pl, st, wall, _info = C.crane_repack_bay(
                        data, j, cur[j], ts, n_xcand=nxc, n_ycand=nyc)
                p_wall = time.monotonic() - p0
                if new_pl is None:
                    print(f"  r{rnd} bay{j}(n={len(cur[j])}) {axis} z1={int(z1_before)} "
                          f"no-sol ({st}) cap={ts:.1f}s wall={p_wall:.0f}s", flush=True)
                    continue
                trial = dict(cur)
                trial[j] = new_pl
                ev = S.global_eval(data, trial)
                obj_before = cur_obj
                accepted = (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6)
                if accepted:
                    gain = cur_obj - ev["obj"]
                    cur = trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
                    acc[axis]["n"] += 1
                    acc[axis]["obj_gain"] += gain
                    print(f"  r{rnd} bay{j}(n={len(cur[j])}) {axis} obj "
                          f"{obj_before:.0f}->{ev['obj']:.0f} ACCEPT cap={ts:.1f}s "
                          f"wall={p_wall:.0f}s ({st})", flush=True)
                else:
                    print(f"  r{rnd} bay{j}(n={len(cur[j])}) {axis} obj "
                          f"{obj_before:.0f}->"
                          f"{(ev['obj'] if ev['obj'] is not None else -1):.0f} "
                          f"reject feas={ev['feasible']} cap={ts:.1f}s "
                          f"wall={p_wall:.0f}s ({st})", flush=True)
            if time.monotonic() >= deadline - 1.0:
                break

        # ============ CROSS-BAY: move/swap on tardy + wrong-bay blocks =======
        # targets = tardy AND wrong-bay, sorted by z3 contribution desc.
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
            # destination/preferred bay drives the cap: the repack happens in the
            # bay the block is moving INTO, so size the cap by that bay's load.
            pref_bay = _preferred(data, bid)
            dest_n = len(cur.get(pref_bay, []))
            ts = _pass_cap(dest_n, remaining, max(1, n_active_bays))

            # --- try_move ---
            obj_before = cur_obj
            mp0 = time.monotonic()
            trial, _info = B.try_move(data, cur, bid, ts, n_xcand=K)
            accepted_here = False
            if trial is not None:
                ev = S.global_eval(data, trial)
                if (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6):
                    gain = cur_obj - ev["obj"]
                    cur = trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
                    acc["move"]["n"] += 1
                    acc["move"]["obj_gain"] += gain
                    accepted_here = True
                    print(f"  r{rnd} b{bid}-move(dest{pref_bay} n={dest_n}) obj "
                          f"{obj_before:.0f}->{ev['obj']:.0f} ACCEPT cap={ts:.1f}s "
                          f"wall={time.monotonic()-mp0:.0f}s", flush=True)
            if accepted_here:
                continue

            # --- try_swap (only if the move didn't improve) ---
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            ts = _pass_cap(dest_n, deadline - now, max(1, n_active_bays))
            sp0 = time.monotonic()
            s_trial, s_info = B.try_swap(data, cur, bid, ts, n_xcand=K)
            if s_trial is None:
                continue
            ev = S.global_eval(data, s_trial)
            if (ev["feasible"] and ev["obj"] is not None
                    and ev["obj"] < cur_obj - 1e-6):
                gain = cur_obj - ev["obj"]
                cur = s_trial
                cur_obj = ev["obj"]
                round_accepts += 1
                acc["swap"]["n"] += 1
                acc["swap"]["obj_gain"] += gain
                print(f"  r{rnd} b{bid}-swap(c={s_info.get('partner')} dest{pref_bay} "
                      f"n={dest_n}) obj {obj_before:.0f}->{ev['obj']:.0f} ACCEPT "
                      f"cap={ts:.1f}s wall={time.monotonic()-sp0:.0f}s", flush=True)

        if round_accepts == 0:
            print(f"round {rnd}: no accepts (spatial + cross-bay) -- converged",
                  flush=True)
            break

    after = S.global_eval(data, cur)
    d = after["obj"] - base["obj"]
    print(f"AFTER  obj={after['obj']} z1={after['z1']} z2={after['z2']} z3={after['z3']} "
          f"feas={after['feasible']}", flush=True)
    print(f"delta  {d:+.0f} ({d / base['obj'] * 100:+.2f}%)  rounds={rnd} "
          f"wall={time.monotonic() - t0:.0f}s", flush=True)
    print("by-category ACCEPTs (x/y/o = coord-descent, move/swap = cross-bay):",
          flush=True)
    for c in cats:
        print(f"  {c:>4}: {acc[c]['n']} accepts, obj_gain={acc[c]['obj_gain']:+.0f}",
              flush=True)


if __name__ == "__main__":
    main()
