"""T2 validation (handoff 2026-06-11): does OGC_DEV_DET=1 make repeated runs
bit-identical, and how much objective does it cost?

For each instance: run the solver TWICE with OGC_DEV_DET=1 (sequentially,
machine otherwise idle) and compare (z1, z2, z3, obj).  Identical -> CP-SAT
determinization works (random_seed + interleave_search at 6 sites +
parallel_decode).  The obj-loss reference is the existing final<tl> capture
(single non-det draw, +-13% band -- indicative only).

Usage:  python notes/_t2_devdet_check.py [--instances prob_6,prob_12,prob_19]
        [--timelimit 100] [--ref final100]
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"wall": round(dt, 2), "feas": bool(feas), "z1": o1, "z2": o2,
           "z3": o3, "obj": obj}, open(sys.argv[3], "w"))
'''


def run_once(inst: str, tl: float, out: Path) -> dict:
    env = dict(os.environ)
    env["OGC_DEV_DET"] = "1"
    drv = out.parent / "_t2_driver.py"
    drv.write_text(DRIVER)
    if out.exists():
        out.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN / f"{inst}.json"),
                        str(tl), str(out)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=tl + 200)
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"}
    if out.exists():
        try:
            return json.load(open(out))
        except Exception as e:
            return {"err": f"parse: {e}"}
    return {"err": "no result"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="prob_6,prob_12,prob_19")
    ap.add_argument("--timelimit", type=float, default=100.0)
    ap.add_argument("--ref", default="final100",
                    help="capture tag for the non-det obj reference")
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    outdir = ROOT / "results" / "_t2_devdet"
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for inst in insts:
        r1 = run_once(inst, a.timelimit, outdir / f"{inst}_run1.json")
        r2 = run_once(inst, a.timelimit, outdir / f"{inst}_run2.json")
        # non-det reference from the existing capture (full json.load -- the
        # capture files are a few MB; fine for a one-off three-instance check)
        ref = None
        refp = ROOT / "results" / "capture" / a.ref / f"{inst}.json"
        if refp.exists():
            try:
                ref = json.load(open(refp, encoding="utf-8")).get("met")
            except Exception:
                ref = None
        rows.append((inst, r1, r2, ref))
    print(f"\n=== T2 OGC_DEV_DET check (tl={a.timelimit}, ref={a.ref}) ===")
    all_same = True
    for inst, r1, r2, ref in rows:
        if "err" in r1 or "err" in r2:
            print(f"  {inst:9} ERR run1={r1.get('err', 'ok')} "
                  f"run2={r2.get('err', 'ok')}")
            all_same = False
            continue
        same = all(r1.get(k) == r2.get(k) for k in ("z1", "z2", "z3", "obj"))
        all_same = all_same and same
        loss = (None if not ref or not ref.get("obj")
                else round(100.0 * (r1["obj"] - ref["obj"]) / ref["obj"], 1))
        print(f"  {inst:9} same={same}  "
              f"run1 obj={r1['obj']} z1={r1['z1']} wall={r1['wall']}  "
              f"run2 obj={r2['obj']} z1={r2['z1']} wall={r2['wall']}  "
              f"ref obj={ref.get('obj') if ref else '-'}  loss%={loss}")
    print(f"\n  reproducible(all): {all_same}")
    print("  NOTE: loss% vs a SINGLE non-det draw (+-13% band) -- indicative.")
    (outdir / "summary.json").write_text(json.dumps(
        [{"inst": i, "run1": r1, "run2": r2, "ref": ref}
         for i, r1, r2, ref in rows], indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
