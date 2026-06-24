"""diag_z1.py i [tl] [cores] -- run v2 (arsenal) on one set1 instance, then for
each residual tardy block quantify the cost of forcing z1=0.

For every tardy block (exit>due) after v2's full pipeline:
  * report bid, current bay, preferred bay, pref gap, R/P/D, bay block count
  * LAYOUT test: aggressive crane_repack_bay on its bay (free all) -> can z1->0
    WITHOUT moving the block out (same assignment)?  => layout-bound
  * MOVE test: for each OTHER bay it can fit, seed+crane_repack (free that block)
    -> resulting global (z1, obj)  => assignment-bound / cost of z1=0

Prints a verdict per block: layout-bound | move-cheap | move-costly | hard.
"""
import os, sys, json, time

os.environ["OGC_NO_V1"] = "1"
os.environ.setdefault("OGC_TOSS", "1")
os.environ.setdefault("OGC_FIXOPT", "1")
os.environ.setdefault("OGC_V2_CAP", "250")
# scale default 1.0 (z1-best base) unless caller overrides OGC_PLACE_W1_SCALE

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
BASE = "C:/claude-develop/OGC2026"


def main():
    i = int(sys.argv[1])
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 250.0
    cores = sys.argv[3] if len(sys.argv) > 3 else None
    if cores:
        try:
            import psutil
            psutil.Process().cpu_affinity([int(c) for c in cores.split(",")])
        except Exception as e:
            print(f"[affinity-FAIL] {e}", flush=True)

    import myalgorithm_fix as M
    import utils
    from v3pp import adapter, seed as S, crane_cpsat as C
    from v3pp.bpass import _find_placed, _preferred, _seed_into_bay

    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    w = data["weights"]; w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    blocks = data["blocks"]; nbay = len(data["bays"])
    print(f"\n=== prob_{i}  N={len(blocks)} bays={nbay}  w1={w1} w2={w2} w3={w3} ===", flush=True)

    t0 = time.time()
    sol = M.algorithm(data, tl)
    r = utils.check_feasibility(data, sol)
    print(f"v2(arsenal) obj={r.get('objective'):,.0f} z1={r.get('obj1')} z2={r.get('obj2')} "
          f"z3={r.get('obj3')}  ({time.time()-t0:.0f}s)", flush=True)

    cur = adapter.deserialize(data, sol)
    base = S.global_eval(data, cur)
    if not base["feasible"]:
        print("  deserialize infeasible -> abort"); return
    base_obj = base["obj"]

    def bz1(pl):
        return sum(max(0, p["exit"] - blocks[p["id"]]["due_date"]) for p in pl)

    tardy = [(j, p) for j, pl in cur.items() for p in pl
             if p["exit"] > blocks[p["id"]]["due_date"]]
    if not tardy:
        print("  z1=0 already, nothing to diagnose"); return
    print(f"  {len(tardy)} tardy block(s).  base_obj={base_obj:,.0f}", flush=True)

    for j, p in tardy:
        bid = p["id"]
        D = blocks[bid]["due_date"]; R = blocks[bid].get("release_time", 0)
        P = blocks[bid]["processing_time"]; prefs = blocks[bid]["bay_preferences"]
        pref = _preferred(data, bid); gap = max(prefs) - prefs[j]
        late = p["exit"] - D
        ncur = len(cur[j])
        print(f"\n  block {bid}: bay={j} (pref={pref}, gap={gap}, z3cost_if_move=w3*gap={w3*gap:,})", flush=True)
        print(f"    R={R} P={P} D={D} exit={p['exit']} late={late}  bay{j} has {ncur} blocks", flush=True)

        # --- LAYOUT test: free-all crane_repack on this bay (same assignment) ---
        try:
            new_pl, st, wall, info = C.crane_repack_bay(
                data, j, cur[j], 25.0, n_xcand=14, n_ycand=14, n_ocand=4,
                use_orient=True, window_tardy_only=False)
        except TypeError:
            new_pl, st, wall, info = C.crane_repack_bay(
                data, j, cur[j], 25.0, n_xcand=14, n_ycand=14)
        if new_pl is not None:
            trial = dict(cur); trial[j] = new_pl
            ev = S.global_eval(data, trial)
            lz1 = bz1(new_pl)
            print(f"    LAYOUT repack(same bay): bay_z1 {bz1(cur[j]):.0f}->{lz1:.0f}  "
                  f"global z1={ev['z1']} obj={ev['obj']:,.0f} ({st},{wall:.0f}s)", flush=True)
            if lz1 == 0:
                print(f"    => LAYOUT-BOUND: zero-tardy IN-PLACE exists (same assignment)!", flush=True)

        # --- MOVE test: try each other bay (crane_repack the moved block free) ---
        best_move = None
        for tb in range(nbay):
            if tb == j:
                continue
            b_seed = _seed_into_bay(data, tb, p)
            placed_new = list(cur.get(tb, [])) + [b_seed]
            try:
                new_k, st2, wall2, ci = C.crane_repack_bay(
                    data, tb, placed_new, 20.0, n_xcand=10, n_ycand=6,
                    free_ids={bid})
            except Exception:
                new_k = None
            if new_k is None:
                continue
            trial = dict(cur)
            trial[j] = [q for q in cur[j] if q["id"] != bid]
            trial[tb] = new_k
            ev = S.global_eval(data, trial)
            if ev["obj"] is None:
                continue
            tag = "z1=0" if ev["z1"] == 0 else f"z1={ev['z1']}"
            dobj = ev["obj"] - base_obj
            print(f"    MOVE -> bay{tb}: global {tag} obj={ev['obj']:,.0f} (dobj={dobj:+,.0f})", flush=True)
            if best_move is None or ev["obj"] < best_move[1]:
                best_move = (tb, ev["obj"], ev["z1"], dobj)
        if best_move:
            tb, mobj, mz1, dobj = best_move
            verdict = ("MOVE-CHEAP (z1=0, obj better)" if mz1 == 0 and dobj < 0 else
                       "MOVE-COSTLY (z1=0 only by raising obj)" if mz1 == 0 else
                       "HARD (no zero-tardy bay found)")
            print(f"    => best move bay{tb}: obj={mobj:,.0f} dobj={dobj:+,.0f} z1={mz1}  [{verdict}]", flush=True)
        else:
            print(f"    => no feasible move found  [HARD or layout-only]", flush=True)


if __name__ == "__main__":
    main()
