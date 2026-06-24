"""Eval-faithful full-set capture with PER-INSTANCE 4-CORE CPU AFFINITY.

Rationale (2026-06-12): the old `--concurrency 3` free-for-all oversubscribes
during worker/CP-SAT bursts (3 x (main+4 workers+4 CP-SAT threads) >> 20
cores), which collapsed fastfloor quality (prob_12 3.0M vs 128K, prob_19 3.3M
vs 97K).  Pinning each instance to a dedicated 4-core mask reproduces the eval
server (4 cores/instance) exactly AND removes cross-instance interference:
5 slots x 4 cores = 20 cores.

  python notes/_capture20_aff.py --instances ALL --timelimit 100 \
        --tag fflean100_aff --env OGC_FASTFLOOR=1,OGC_FF_PRIMARY=1,...

Writes results/capture/<tag>/<inst>.json = {met:{...}, solution:{...}}
(same schema as _capture20.py).
"""
import argparse
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]
N_SLOTS = 5
CORES_PER = 4

DRIVER = r'''
import json, time, sys

SRC = r"@SRC@"
TOOLS = r"@TOOLS@"


def main():
    sys.path.insert(0, SRC); sys.path.insert(0, TOOLS)
    import ogc_analysis as A   # WARNING: prepends baseline/ dir to sys.path[0]
    # Re-pin src FIRST: spawn workers inherit the parent sys.path verbatim; if
    # baseline/ stays ahead, workers resolve the BASELINE myalgorithm and die
    # on ImportError (2026-06-12: silent pool death, prob_19 3.26M vs 97K).
    sys.path.insert(0, SRC)
    from myalgorithm import algorithm
    prob = json.load(open(sys.argv[1], encoding="utf-8"))
    t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
    feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
    json.dump({"met": {"wall": round(dt,2), "feas": bool(feas), "z1": o1, "z2": o2,
                       "z3": o3, "obj": obj},
               "solution": sol},
              open(sys.argv[3], "w"))


# CRITICAL: Windows spawn workers re-import the main module. Without this
# guard every pool worker re-runs algorithm() recursively. _capture20.py has
# the same bug family (no guard + baseline path poisoning via ogc_analysis).
if __name__ == "__main__":
    main()
'''

_slot_lock = threading.Lock()
_free_slots = list(range(N_SLOTS))


def run(inst, tl, outdir, env_extra):
    with _slot_lock:
        slot = _free_slots.pop()
    try:
        cores = list(range(slot * CORES_PER, (slot + 1) * CORES_PER))
        env = dict(os.environ)
        env.update(env_extra)
        # ABSOLUTE src/tools on PYTHONPATH: propagates to the WHOLE child tree,
        # so spawn pool workers resolve src/myalgorithm (not the baseline copy).
        # 2026-06-12 finding: without this, fastfloor workers died on
        # ImportError and the floor silently degraded (prob_19 3.26M vs 97K).
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), str(ROOT / "tools")]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        res = outdir / f"{inst}.json"
        drv = outdir / "_cap_driver.py"
        # always rewrite: a stale unguarded driver recurses
        drv.write_text(DRIVER.replace("@SRC@", str(ROOT / "src"))
                             .replace("@TOOLS@", str(ROOT / "tools")))
        if res.exists():
            res.unlink()
        # Keep the child's streams: stage/trace instrumentation ([STAGE_TIMING],
        # [STAGE_OBJ], [Z1_TRACE], [TRAJ]) is emitted on STDERR (myalgorithm.py
        # _ret chokepoint), so dumping both streams per instance preserves the
        # per-stage time/obj traces that the old DEVNULL capture discarded.
        out_fh = open(outdir / f"{inst}.stdout.txt", "w", encoding="utf-8")
        err_fh = open(outdir / f"{inst}.stderr.txt", "w", encoding="utf-8")
        try:
            p = subprocess.Popen(
                [PYEXE, str(drv), str(TRAIN / f"{inst}.json"), str(tl), str(res)],
                cwd=str(ROOT), env=env,
                stdout=out_fh, stderr=err_fh)
            try:
                # Children (spawn workers) inherit the parent's affinity mask
                # on Windows; set it before the heavy phases start.
                psutil.Process(p.pid).cpu_affinity(cores)
            except Exception:
                pass
            p.wait(timeout=tl + 200)
        except subprocess.TimeoutExpired:
            p.kill()
            return inst, {"err": "timeout"}
        except Exception as e:
            return inst, {"err": f"{type(e).__name__}: {e}"}
        if res.exists():
            try:
                return inst, json.load(open(res))["met"]
            except Exception as e:
                return inst, {"err": f"parse: {e}"}
        return inst, {"err": "no result"}
    finally:
        for _fh in (locals().get("out_fh"), locals().get("err_fh")):
            try:
                if _fh:
                    _fh.close()
            except Exception:
                pass
        with _slot_lock:
            _free_slots.append(slot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--timelimit", type=float, default=100.0)
    ap.add_argument("--tag", default="aff")
    ap.add_argument("--env", default="")
    a = ap.parse_args()
    # ALL/ALL20 = prob_1..20 (set1, has competitor table); SET2 = prob_21..40
    # (the 2026-06-14 second train set, NO competitor table); ALL40 = both.
    _SET2 = [f"prob_{i}" for i in range(21, 41)]
    _ALL40 = ALL20 + _SET2
    if a.instances in ("ALL", "ALL20"):
        insts = ALL20
    elif a.instances == "SET2":
        insts = _SET2
    elif a.instances == "ALL40":
        insts = _ALL40
    else:
        insts = a.instances.split(",")
    env_extra = {}
    for kv in a.env.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            env_extra[k.strip()] = v.strip()
    outdir = ROOT / "results" / "capture" / a.tag
    outdir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=N_SLOTS) as ex:
        futs = [ex.submit(run, i, a.timelimit, outdir, env_extra) for i in insts]
        for f in futs:
            inst, met = f.result()
            print(f"[aff] {inst}: {met}", flush=True)


if __name__ == "__main__":
    main()
