"""exp_submission.py — 배포 zip(best-of) 통째 A/B: 현재(OGC_GLOBAL=0) vs 전역(OGC_GLOBAL=1).

submission_build/myalgorithm.algorithm (= 배포된 best-of(v2,원래,baseline)) 을 인스턴스마다
두 모드로 subprocess 실행 → 공식 utils.check_feasibility 로 검증·집계.
  - before = OGC_GLOBAL 미설정(=0) → 배포 zip 과 동작 동일 (전역코드 게이트 OFF)
  - after  = OGC_GLOBAL=1 → v2 엔진이 전역 Pass B
판정: full set 총 obj · feasible 40/40 · never−1 · wall≤TL (사용자 규칙).

실행(env-python 직접):
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe exp_submission.py 120 prob_21 prob_38 ...
"""
from __future__ import annotations

import os
import sys
import json
import time
import subprocess

THIS = os.path.dirname(os.path.abspath(__file__))
SB = os.path.join(THIS, "submission_build")
PY = sys.executable
TRAIN = os.path.join(THIS, "..", "instances", "train")

DRIVER = r'''
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import myalgorithm, utils
inst, tl = sys.argv[1], float(sys.argv[2])
prob = json.load(open(inst, encoding="utf-8"))
t0 = time.time()
sol = myalgorithm.algorithm(prob, tl)
wall = time.time() - t0
r = utils.check_feasibility(prob, sol)
ok = isinstance(r, dict)
print("RESULT " + json.dumps({
    "obj": r.get("objective") if ok else None,
    "z1": r.get("obj1") if ok else None, "z2": r.get("obj2") if ok else None,
    "z3": r.get("obj3") if ok else None, "stage": r.get("stage") if ok else None,
    "wall": round(wall, 1)}), flush=True)
'''


def run(inst, tl, gv):
    dp = os.path.join(SB, "_ab_driver.py")
    with open(dp, "w", encoding="utf-8") as f:
        f.write(DRIVER)
    env = dict(os.environ)
    if gv == "1":
        env["OGC_GLOBAL"] = "1"
    else:
        env.pop("OGC_GLOBAL", None)          # 미설정 = 배포 동작
    try:
        p = subprocess.run([PY, dp, inst, str(tl)], cwd=SB, env=env,
                           capture_output=True, text=True, timeout=tl + 180)
    except subprocess.TimeoutExpired:
        return {"obj": None, "wall": tl + 180, "stage": "TIMEOUT"}
    for ln in reversed(p.stdout.strip().splitlines()):
        if ln.startswith("RESULT "):
            return json.loads(ln[7:])
    return {"obj": None, "wall": None, "stage": "NO_RESULT", "err": p.stderr[-400:]}


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or ["prob_38"]
    print(f"== 배포 zip best-of A/B @TL={tl}s ==  before(global=0) vs after(global=1)", flush=True)
    sb = sa = 0.0
    wins = bothok = feas_b = feas_a = 0
    maxwall = 0.0
    for nm in names:
        inst = os.path.join(TRAIN, nm + ".json")
        data = json.load(open(inst, encoding="utf-8"))
        b = run(inst, tl, "0")
        a = run(inst, tl, "1")
        ob, oa = b.get("obj"), a.get("obj")
        feas_b += int(ob is not None)
        feas_a += int(oa is not None)
        maxwall = max(maxwall, b.get("wall") or 0, a.get("wall") or 0)
        print(f"\n[{nm}] N={len(data['blocks'])} bays={len(data['bays'])} w={data['weights']}", flush=True)
        print(f"  before(g0) obj={('%14,.0f'%ob) if ob is not None else 'INFEAS '+str(b.get('stage')):>14}"
              f"  z1={b.get('z1')} z2={b.get('z2')} z3={b.get('z3')}  wall={b.get('wall')}s", flush=True)
        print(f"  after (g1) obj={('%14,.0f'%oa) if oa is not None else 'INFEAS '+str(a.get('stage')):>14}"
              f"  z1={a.get('z1')} z2={a.get('z2')} z3={a.get('z3')}  wall={a.get('wall')}s", flush=True)
        if ob is not None and oa is not None:
            d = ob - oa
            sb += ob; sa += oa; bothok += 1; wins += int(d > 0)
            print(f"  => after {'개선' if d > 0 else '악화' if d < 0 else '동일'} {d:+,.0f} ({d/ob*100:+.2f}%)", flush=True)
            print(f"  [누적 {bothok}] before={sb:,.0f} after={sa:,.0f} Δ={sb-sa:+,.0f} "
                  f"({(sb-sa)/sb*100:+.2f}%) after승={wins}/{bothok} feas b/a={feas_b}/{feas_a} maxwall={maxwall:.0f}s", flush=True)
    print(f"\n==== TOTAL ({bothok} both-feasible / {len(names)}) ====", flush=True)
    print(f"  before(g0) 총합 = {sb:,.0f}", flush=True)
    print(f"  after (g1) 총합 = {sa:,.0f}", flush=True)
    if sb:
        print(f"  Δ = {sb-sa:+,.0f} ({(sb-sa)/sb*100:+.2f}%)   after 승 {wins}/{bothok}", flush=True)
    print(f"  feasible before/after = {feas_b}/{len(names)}  {feas_a}/{len(names)}   maxwall={maxwall:.0f}s", flush=True)


if __name__ == "__main__":
    main()
