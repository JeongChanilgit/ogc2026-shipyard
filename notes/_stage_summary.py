"""Summarize [STAGE_TIMING]/[STAGE_OBJ]/[Z1_TRACE] stderr dumps from a capture tag.

Usage: python notes/_stage_summary.py <tag> [inst ...]
Prints compact per-instance tables: stage seconds (sorted desc), per-stage obj
delta/adoptions, and the z1 trajectory (time, z1, stage) -- no raw JSON dumps.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(tag: str, insts):
    cap = ROOT / "results" / "capture" / tag
    for inst in insts:
        f = cap / f"{inst}.stderr.txt"
        if not f.exists():
            print(f"== {inst}: no stderr dump")
            continue
        timing = objs = z1tr = None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[STAGE_TIMING]"):
                timing = json.loads(line[len("[STAGE_TIMING]"):])
            elif line.startswith("[STAGE_OBJ]"):
                objs = json.loads(line[len("[STAGE_OBJ]"):])
            elif line.startswith("[Z1_TRACE]"):
                z1tr = json.loads(line[len("[Z1_TRACE]"):])
        print(f"\n===== {inst} =====")
        if timing:
            tot = timing.get("total_s")
            other = timing.get("search_baseline_other_s")
            print(f"total={tot}s  unattributed={other}s")
            for k, v in sorted(timing["stages"].items(), key=lambda kv: -kv[1]):
                print(f"  {k:28s} {v:8.2f}s")
        if objs:
            print(f"final_obj={objs.get('final_obj')}")
            base = objs["stages"].pop("_postproc_base", None)
            if base:
                print(f"  postproc_base: {base}")
            for k, v in sorted(objs["stages"].items(),
                               key=lambda kv: kv[1].get("delta", 0)):
                print(f"  {k:28s} n_adopt={v['n_adopt']:3d} delta={v['delta']:12.1f}"
                      f" z1={v.get('z1')} z3={v.get('z3')}")
        if z1tr:
            ch = z1tr.get("changes", [])
            print(f"z1 trajectory ({len(ch)} drops):")
            for t, z, stg in ch:
                print(f"  t={t:8.2f}s  z1={z:8.1f}  [{stg}]")


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "stagetrace_d1"
    insts = sys.argv[2:] or ["prob_14", "prob_20"]
    summarize(tag, insts)
