"""exp_global.py — 전역 Pass B 실험: before(현재 2-pass) vs after(OGC_GLOBAL=1).

각 인스턴스를 두 모드로 돌려 (obj·z1·z2·z3·wall·feasible) 비교 + 양쪽 3D viz HTML 생성.
실행(반드시 env-python 직접 — conda run 은 4-worker CP-SAT 크래시):
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe exp_global.py 90 prob_38
"""
from __future__ import annotations

import os
import sys
import time
import json

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

# v2 검증 config (모듈 import 전에 — temporal_pack/_FIT 등이 import 시 읽음)
os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_DIVERSE", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")
os.environ.setdefault("OGC_TOSS", "0")
os.environ.setdefault("OGC_MERGE", "0")

import unified_greedy as ug   # noqa: E402
import viz                    # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
OUT = os.path.join(THIS, "out")


def run_mode(data, path, tl, gv):
    os.environ["OGC_GLOBAL"] = gv
    t0 = time.time()
    res, dist, ok, dt = ug.unified(data, tl, path)
    wall = time.time() - t0
    return {
        "obj": res.get("objective"), "z1": res.get("obj1"),
        "z2": res.get("obj2"), "z3": res.get("obj3"),
        "wall": wall, "dist": dist, "sol": res.get("_solution"),
        "feasible": res.get("objective") is not None,
        "stage": res.get("stage"),
    }


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    names = sys.argv[2:] or ["prob_38"]
    os.makedirs(OUT, exist_ok=True)
    print(f"== 전역 Pass B 실험 @TL={tl}s ==  (before=2-pass / after=OGC_GLOBAL=1)", flush=True)
    sb = sa = 0.0          # both-feasible 총합
    wins = bothok = 0
    feas_b = feas_a = 0
    maxwall = 0.0
    for nm in names:
        data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
        N, M = len(data["blocks"]), len(data["bays"])
        b = run_mode(data, os.path.join(TRAIN, nm + ".json"), tl, "0")
        a = run_mode(data, os.path.join(TRAIN, nm + ".json"), tl, "1")
        # 3D viz 양쪽
        htmls = {}
        for tag, r in (("before", b), ("after", a)):
            if r["sol"]:
                tr = viz.trace_from_solution(data, r["sol"], f"{nm} [{tag}] global={'1' if tag=='after' else '0'}")
                p = os.path.join(OUT, f"global_{nm}_{tag}.html")
                viz.write_viz(tr, p)
                htmls[tag] = p
        print(f"\n[{nm}] N={N} bays={M} w={data['weights']}", flush=True)
        for tag, r in (("before(2-pass)", b), ("after(global)", a)):
            if r["feasible"]:
                print(f"  {tag:16s} obj={r['obj']:>14,.0f}  z1={r['z1']:<6} z2={r['z2']:<5} "
                      f"z3={r['z3']:<6}  wall={r['wall']:.0f}s  dist={r['dist']}", flush=True)
            else:
                print(f"  {tag:16s} INFEASIBLE stage={r['stage']}  wall={r['wall']:.0f}s", flush=True)
        feas_b += int(b["feasible"])
        feas_a += int(a["feasible"])
        maxwall = max(maxwall, b["wall"], a["wall"])
        if b["feasible"] and a["feasible"]:
            d = b["obj"] - a["obj"]
            sb += b["obj"]; sa += a["obj"]; bothok += 1
            wins += int(d > 0)
            print(f"  => after {'개선' if d > 0 else '악화'} {d:+,.0f} ({d/b['obj']*100:+.1f}%)", flush=True)
        print(f"  3D: {htmls.get('before','-')}\n      {htmls.get('after','-')}", flush=True)
        # 러닝 누적 (백그라운드 부분읽기용)
        if bothok:
            print(f"  [누적 {bothok}개] before={sb:,.0f}  after={sa:,.0f}  "
                  f"Δ={sb-sa:+,.0f} ({(sb-sa)/sb*100:+.1f}%)  after승={wins}/{bothok}  "
                  f"feas b/a={feas_b}/{feas_a}  maxwall={maxwall:.0f}s", flush=True)
    print(f"\n==== TOTAL ({bothok} both-feasible) ====", flush=True)
    print(f"  before 총합 = {sb:,.0f}", flush=True)
    print(f"  after  총합 = {sa:,.0f}", flush=True)
    if sb:
        print(f"  Δ = {sb-sa:+,.0f} ({(sb-sa)/sb*100:+.1f}%)   after 승 {wins}/{bothok}", flush=True)
    print(f"  feasible before/after = {feas_b}/{len(names)}  {feas_a}/{len(names)}   maxwall={maxwall:.0f}s", flush=True)


if __name__ == "__main__":
    main()
