"""T1 probe (handoff 2026-06-11 / F1): measure on prob_13 @ tl=300, sequentially,
(A) the DEFAULT path  -- greedy floor obj/z1, per-stage walls, adoption deltas,
(B) the RASTER-FORCED path (OGC_FAST_FLOOR_FRAC=0) -- raw raster floor obj/z1,
    raster-floor build wall, and what a FULL pp window on the raster base reaches
    (= the long-tl race ceiling at T=300).

Decides the T1 design: if the raw raster floor already beats the default final
(330,342), a cheap "build + gate-candidate" race suffices; otherwise the race
needs a reserved postprocess window (selective arming).

Usage:  python notes/_t1_probe13.py [--timelimit 300] [--inst prob_13]
Output: compact summary lines only (no dumps).
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
TRACE_DIR = ROOT / "results" / "traces"


def run_one(tag: str, inst: str, tl: float, extra_env: dict) -> dict:
    env = dict(os.environ)
    # OGC_Z1_TRACE arms the trace clock; OGC_TRAJ then records EVERY postprocess
    # adoption as [t, obj, z1, z2, z3, stage] -> the U2 adoption timeline
    # (emitted once as a [TRAJ] stderr line at _ret).
    env.update({"OGC_STAGE_TIMING": "1", "OGC_TRACE": "1",
                "OGC_Z1_TRACE": "1", "OGC_TRAJ": "1"})
    env.update(extra_env)
    before = set(glob.glob(str(TRACE_DIR / f"trace_{inst}_*.json")))
    t0 = time.monotonic()
    p = subprocess.run(
        [PYEXE, str(ROOT / "tools" / "run_solver_once.py"),
         str(ROOT / "instances" / "train" / f"{inst}.json"),
         "--solver", "our", "--timelimit", str(tl),
         "--out", str(ROOT / "results" / f"_t1_probe_{tag}.json")],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        timeout=tl + 240)
    wall = time.monotonic() - t0
    out: dict = {"tag": tag, "driver_wall": round(wall, 1)}
    # final result line (stdout JSON)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
        out["final"] = {k: res.get(k) for k in
                        ("objective", "obj1", "obj2", "obj3", "elapsed",
                         "feasible")}
        if res.get("error"):
            out["final"]["error"] = res["error"]
            out["final"]["traceback_tail"] = (res.get("traceback") or "")[-400:]
    except Exception as e:
        out["final_err"] = f"{type(e).__name__}: {e}; stdout_tail={p.stdout[-300:]!r}"
    # [STAGE_TIMING] / [STAGE_OBJ] from stderr
    for line in p.stderr.splitlines():
        if line.startswith("[STAGE_TIMING]"):
            try:
                out["stage_timing"] = json.loads(line[len("[STAGE_TIMING]"):])
            except Exception:
                pass
        elif line.startswith("[STAGE_OBJ]"):
            try:
                out["stage_obj"] = json.loads(line[len("[STAGE_OBJ]"):])
            except Exception:
                pass
        elif line.startswith("[TRAJ]"):
            try:
                out["traj"] = json.loads(line[len("[TRAJ]"):]).get("points")
            except Exception:
                pass
    # newest trace file created by this run
    after = set(glob.glob(str(TRACE_DIR / f"trace_{inst}_*.json")))
    new = sorted(after - before, key=os.path.getmtime)
    if new:
        try:
            tr = json.load(open(new[-1], encoding="utf-8"))
            ev = tr.get("events", [])
            out["trace_file"] = os.path.basename(new[-1])
            out["candidates"] = [
                {"t": e.get("t"), "label": e.get("label"),
                 "status": e.get("status"), "obj": e.get("obj")}
                for e in ev if e.get("kind") == "candidate"]
            out["gate"] = [
                {"t": e.get("t"), "kind": e.get("kind"),
                 **{k: e.get(k) for k in ("label", "feasible", "objective",
                                          "reason", "returned_label")
                    if k in e}}
                for e in ev if e.get("kind") in
                ("gate_check", "gate_reject", "gate_skip", "final", "ladder")]
            out["race"] = [
                {"t": e.get("t"), "kind": e.get("kind"),
                 **{k: e.get(k) for k in ("budget", "window", "floor_z1",
                                          "obj", "adopted", "error", "why",
                                          "z1", "raw", "floor")
                    if k in e}}
                for e in ev if e.get("kind") in
                ("race_arm", "race_result", "race_error",
                 "race_refund", "race_hopeless")]
            # phase walls from phase events if present
            out["phases"] = [
                {"t": e.get("t"), "name": e.get("name"), "dt": e.get("seconds")}
                for e in ev if e.get("kind") in ("phase", "phase_end")][:20]
        except Exception as e:
            out["trace_err"] = f"{type(e).__name__}: {e}"
    return out


def brief(d: dict) -> None:
    print(f"=== {d['tag']} (driver wall {d.get('driver_wall')}s) ===")
    f = d.get("final")
    if f:
        print(f"  final: obj={f.get('objective')} z1={f.get('obj1')} "
              f"z2={f.get('obj2')} z3={f.get('obj3')} "
              f"elapsed={f.get('elapsed')} feas={f.get('feasible')}")
    st = d.get("stage_timing")
    if st:
        stages = st.get("stages", {})
        big = sorted(stages.items(), key=lambda kv: -kv[1])[:8]
        print(f"  stage walls: total={st.get('total_s')} "
              + " ".join(f"{k}={v}" for k, v in big)
              + f" other={st.get('search_baseline_other_s')}")
    so = d.get("stage_obj")
    if so:
        base = so.get("stages", {}).get("_postproc_base")
        if base:
            print(f"  pp entry incumbent: obj={base.get('obj')} "
                  f"z1={base.get('obj1')} z2={base.get('obj2')} "
                  f"z3={base.get('obj3')}")
        for k, v in so.get("stages", {}).items():
            if k == "_postproc_base":
                continue
            print(f"  lever {k}: n_adopt={v.get('n_adopt')} "
                  f"delta={v.get('delta')} after={v.get('after')} "
                  f"z1={v.get('z1')}")
    tj = d.get("traj")
    if tj:
        # U2: adoption timeline.  Trajectory is monotone (only adoptions are
        # recorded), so the earliest point at the final value = plateau start.
        fin = tj[-1][1]
        t_fin = next((p[0] for p in tj if abs(p[1] - fin) < 1e-6), None)
        stages: dict = {}
        for p in tj:
            stages[p[5]] = stages.get(p[5], 0) + 1
        print(f"  traj: n={len(tj)} floor_entry(t,obj)={tj[0][:2]} "
              f"last_adopt(t,obj)={tj[-1][:2]} plateau_from_t={t_fin}")
        print(f"  traj stages: {stages}")
        show = tj[:4] + (tj[-4:] if len(tj) > 8 else [])
        for p in show:
            print(f"    t={p[0]:>8.1f} obj={p[1]:>11.1f} z1={p[2]} stage={p[5]}")
    for r in d.get("race", []) or []:
        print(f"  race t={r['t']}: {r}")
    for c in d.get("candidates", []) or []:
        print(f"  cand t={c['t']}: {c['label']} {c['status']} obj={c['obj']}")
    for g in d.get("gate", []) or []:
        print(f"  gate t={g['t']}: {g}")
    for e in ("final_err", "trace_err"):
        if d.get(e):
            print(f"  !! {e}: {d[e]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--inst", default="prob_13")
    ap.add_argument("--skip-default", action="store_true",
                    help="only run the raster-forced probe")
    ap.add_argument("--skip-raster", action="store_true",
                    help="only run the default-path probe")
    ap.add_argument("--race", action="store_true",
                    help="also run a leg with the T1 race armed "
                         "(OGC_LONGTL_RACE=1)")
    a = ap.parse_args()
    runs = []
    if not a.skip_default:
        runs.append(("default", {}))
    if not a.skip_raster:
        runs.append(("raster", {"OGC_FAST_FLOOR_FRAC": "0"}))
    if a.race:
        runs.append(("race", {"OGC_LONGTL_RACE": "1"}))
    results = []
    for tag, env in runs:
        results.append(run_one(f"{a.inst}_{tag}{int(a.timelimit)}",
                               a.inst, a.timelimit, env))
    print()
    for d in results:
        brief(d)
    # persist the full parse for later inspection without re-running
    # (legs in the name so default-only / raster-only runs don't overwrite)
    legs = "_".join(tag for tag, _ in runs)
    outp = ROOT / "results" / (
        f"_t1_probe_summary_{a.inst}_{int(a.timelimit)}_{legs}.json")
    outp.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nsummary -> {outp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
