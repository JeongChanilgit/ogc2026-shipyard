"""viz_run.py — 현재 통합 파이프라인 결과를 3D viz HTML 로 띄운다.

실행: <env-python> viz_run.py <tl> <prob>
  ex) viz_run.py 120 prob_25  → out/viz_<prob>.html 생성 + 브라우저 오픈(Windows)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug  # noqa: E402
from viz import trace_from_solution, write_viz  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    nm = sys.argv[2] if len(sys.argv) > 2 else "prob_25"
    suffix = sys.argv[3] if len(sys.argv) > 3 else ""   # 출력 파일명 구분 (예: _swap)
    path = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(path, encoding="utf-8"))

    res, dist, cpsat, dt = ug.unified(data, tl, path)
    sol = res.get("_solution") if isinstance(res, dict) else None
    print(f"[{nm}] obj={res.get('objective')} z1={res.get('obj1')} z2={res.get('obj2')} "
          f"z3={res.get('obj3')} dist={dist} ({dt:.0f}s)", flush=True)
    if not sol:
        print(f"  솔루션 없음 (stage={res.get('stage')}) — viz 생략", flush=True)
        return

    trace = trace_from_solution(data, sol, instance_name=nm + suffix)
    out = os.path.join(THIS, "out", f"viz_{nm}{suffix}.html")
    write_viz(trace, out)
    print(f"  wrote {out}  (placed={trace['stats']['n_blocks_placed']}, "
          f"tardy={trace['stats']['n_tardy']})", flush=True)
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


if __name__ == "__main__":
    main()
