"""DECISIVE prob_38 z1-floor test for the optimized lns.py.

  1. micro-bench: iters/s of bl_fit on the BIGGEST work bay, scalar vs vectorized.
  2. BOX base via boxsolver (z1 ~ 6161).
  3. OGC_LNS_SA=1 lns.improve(prob_38, base, 600); report iters/accepts/per-bay/wall,
     base z1/obj -> LNS z1/obj, feasible.
  4. THE QUESTION: does prob_38 z1 drop below 6002 / toward 4934?
  5. set1 sanity prob_14 @120.

Run with the ogc2025 env python directly (NOT conda run -- 4-worker CP-SAT crashes).
"""
import os, sys, json, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import numpy as np  # noqa: E402


def load(name):
    with open(os.path.join(ROOT, "instances", "train", name + ".json"),
              encoding="utf-8") as f:
        return json.load(f)


def z1_obj(prob_info, sol):
    import myalgorithm
    from utils import check_feasibility
    rep = check_feasibility(prob_info, sol)
    return rep["feasible"], rep["obj1"], rep["obj2"], rep["obj3"], rep["objective"], rep["stage"]


# ---------------------------------------------------------------------------
# 1. MICRO-BENCH: scalar vs vectorized bl_fit on the biggest work bay of prob_38.
# ---------------------------------------------------------------------------
def microbench(prob_38, base):
    import lns
    import myalgorithm
    blocks = prob_38["blocks"]; bays = prob_38["bays"]
    _a, results, _f = myalgorithm._results_from_solution(prob_38, base)
    # pick the largest bay by #blocks
    work = sorted(results.items(), key=lambda kv: -len(kv[1]))
    j, by_id = work[0]
    ids = list(by_id)
    W = int(bays[j]["width"]); H = int(bays[j]["height"])
    try:
        from utils import Bay as _Bay
        bay_obj = _Bay.from_dict(bays[j], j)
    except Exception:
        bay_obj = None
    st = lns._BayLNS(W, H, ids, by_id, blocks, 1, bay_obj)
    cur = {b: st.placement_from_record(b) for b in ids}
    cur = {b: pl for b, pl in cur.items() if pl is not None}

    # Build a realistic occupancy grid: drop ~half the blocks, then time-overlap.
    import random as _r
    rng = _r.Random(1)
    sample_blocks = [b for b in ids if rng.random() < 0.5][:60] or ids[:30]
    # Use a representative entry/exit window (median entry).
    entries = sorted(st.R[b] for b in ids)
    entry = entries[len(entries)//2]
    test_b = ids[len(ids)//2]
    exit_t = st.exit_of(test_b, entry)
    layout = {b: cur[b] for b in ids}
    grid_b = st.blocked_grid(layout, {test_b}, entry, exit_t)

    # scalar reference bl_fit (the OLD implementation, inlined)
    def scalar_bl_fit(grid_b, b):
        ml = st.masks[b]; Hc, Wc = st.Hc, st.Wc
        for gy in range(Hc):
            for gx in range(Wc):
                for o in range(len(ml)):
                    mask, w, h, ox, oy = ml[o]
                    mh, mw = mask.shape
                    if gx + mw > Wc or gy + mh > Hc:
                        continue
                    if not (mask & grid_b[gy:gy+mh, gx:gx+mw]).any():
                        return (o, gx, gy)
        return None

    # warm + time scalar
    N = 200
    t0 = time.perf_counter()
    for _ in range(N):
        scalar_bl_fit(grid_b, test_b)
    t_scalar = (time.perf_counter() - t0) / N

    t0 = time.perf_counter()
    for _ in range(N):
        st.bl_fit(grid_b, test_b)
    t_vec = (time.perf_counter() - t0) / N

    print(f"[microbench] biggest work bay j={j}  n_blocks={len(ids)}  grid={st.Hc}x{st.Wc}")
    print(f"[microbench] scalar bl_fit : {t_scalar*1e3:8.3f} ms/call  -> {1.0/max(t_scalar,1e-12):8.1f} calls/s")
    print(f"[microbench] vector bl_fit : {t_vec*1e3:8.3f} ms/call  -> {1.0/max(t_vec,1e-12):8.1f} calls/s")
    print(f"[microbench] SPEEDUP       : {t_scalar/max(t_vec,1e-12):.1f}x")
    print(f"[microbench] (equal result: {scalar_bl_fit(grid_b, test_b)} == {st.bl_fit(grid_b, test_b)})")
    return j


# ---------------------------------------------------------------------------
# 2/3. BOX base + LNS, with per-bay telemetry.
# ---------------------------------------------------------------------------
def main():
    prob_38 = load("prob_38")
    print(f"prob_38: {len(prob_38['bays'])} bays, {len(prob_38['blocks'])} blocks, "
          f"weights={prob_38.get('weights')}")

    # ---- BOX base ----
    os.environ["OGC_BOXDECOMP"] = "1"
    os.environ["OGC_FEASSPILL"] = "0"
    import boxsolver
    t0 = time.perf_counter()
    base = boxsolver.algorithm(prob_38, 120)
    t_base = time.perf_counter() - t0
    fb, b1, b2, b3, bobj, bst = z1_obj(prob_38, base)
    print(f"\n[BOX base] wall={t_base:.1f}s feasible={fb} stage={bst}")
    print(f"[BOX base] z1={b1:.0f} z2={b2:.2f} z3={b3:.0f} obj={bobj:,.0f}")

    # ---- microbench on this base ----
    print()
    microbench(prob_38, base)

    # ---- LNS with SA, telemetry on ----
    import lns
    logpath = os.path.join(ROOT, "notes", "_lns_p38_tel.jsonl")
    try:
        os.remove(logpath)
    except OSError:
        pass
    os.environ["OGC_LNS_SA"] = "1"
    os.environ["OGC_PERBAY_LOG"] = logpath
    os.environ["OGC_LNS_MAXN"] = "300"   # don't skip prob_38's big bays
    print("\n[LNS] OGC_LNS_SA=1  budget=600s  maxn=300 ...")
    t0 = time.perf_counter()
    out = lns.improve(prob_38, base, 600)
    t_lns = time.perf_counter() - t0
    fo, o1, o2, o3, oobj, ost = z1_obj(prob_38, out)
    print(f"\n[LNS] wall={t_lns:.1f}s feasible={fo} stage={ost}")
    print(f"[LNS] z1={o1:.0f} z2={o2:.2f} z3={o3:.0f} obj={oobj:,.0f}")
    print(f"[LNS] delta z1 = {o1 - b1:+.0f}   delta obj = {oobj - bobj:+,.0f}")

    # ---- telemetry: total iters/accepts + per-bay ----
    tot_iters = tot_accepts = 0
    perbay = []
    if os.path.exists(logpath):
        with open(logpath, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("event") != "lns_improve":
                    continue
                tot_iters += int(rec.get("iters", 0))
                tot_accepts += int(rec.get("accepts", 0))
                for bb in rec.get("bays", []):
                    perbay.append(bb)
    print(f"\n[LNS] TOTAL iters={tot_iters}  accepts={tot_accepts}")
    print("[LNS] per-bay (sorted by n_blocks desc):")
    for bb in sorted(perbay, key=lambda d: -int(d.get("n_blocks", 0))):
        n = bb.get("n_blocks"); wall = bb.get("wall", 0.0) or 0.0
        it = bb.get("iters", 0); ac = bb.get("accepts", 0)
        ips = it / wall if wall > 0.01 else 0.0
        print(f"    bay {bb.get('bay'):>3} n={n:>4} cur_tard={bb.get('cur_tard'):>8} "
              f"new_tard={bb.get('new_tard')!s:>8} status={bb.get('status'):>10} "
              f"iters={it:>7} ({ips:7.1f}/s) accepts={ac:>5} wall={wall:5.1f}s")

    # ---- VERDICT ----
    print("\n" + "=" * 70)
    print(f"VERDICT prob_38:  BOX z1={b1:.0f}  ->  LNS z1={o1:.0f}")
    if o1 < 5800:
        print(f"  z1 dropped MEANINGFULLY below 5800 -> floor was THROUGHPUT-MASKED, lever ALIVE.")
    elif o1 <= b1 - 1:
        print(f"  z1 dropped a little but still ~6100 -> mostly REAL floor.")
    else:
        print(f"  z1 did NOT drop despite {tot_iters} iters -> floor is REAL (not a throughput artifact).")
    print("=" * 70)

    # ---- set1 sanity prob_14 @120 ----
    print("\n[sanity] prob_14 @120 (BOX base + LNS), check no regression ...")
    prob_14 = load("prob_14")
    t0 = time.perf_counter()
    base14 = boxsolver.algorithm(prob_14, 120)
    fb14, b1_14, b2_14, b3_14, bobj14, _ = z1_obj(prob_14, base14)
    out14 = lns.improve(prob_14, base14, 60)
    fo14, o1_14, o2_14, o3_14, oobj14, _ = z1_obj(prob_14, out14)
    print(f"[sanity] prob_14 BOX  feasible={fb14} z1={b1_14:.0f} obj={bobj14:,.0f}")
    print(f"[sanity] prob_14 LNS  feasible={fo14} z1={o1_14:.0f} obj={oobj14:,.0f}  "
          f"delta_obj={oobj14-bobj14:+,.0f}  wall={time.perf_counter()-t0:.1f}s")
    if oobj14 <= bobj14 + 1e-6 and fo14:
        print("[sanity] prob_14 OK: no regression (obj not worse, feasible).")
    else:
        print("[sanity] prob_14 WARNING: obj worse or infeasible!")


if __name__ == "__main__":
    main()
