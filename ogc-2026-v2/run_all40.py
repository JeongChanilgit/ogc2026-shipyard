"""run_all40.py — 검증 config 로 ALL40(prob_1..40) @TL 실행. 총 obj + feasibility(절대 −1 없음) 판정.

config: fit=1(접촉-max, 로버스트) + diverse + near-접촉(D=2) + WALL_W=1 + 타이밍캡, 토스/스왑 off.
실행: <env-python> run_all40.py [TL] [fit]   (기본 TL=120, fit=1)
출력: 인스턴스별 obj/z/feasible/time + 총합. out/all40_<fit>.json 덤프.
"""
from __future__ import annotations

import os
import sys

_TL = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
_FITV = sys.argv[2] if len(sys.argv) > 2 else "1"

os.environ["OGC_FIT"] = _FITV
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_TOSS"] = "0"
os.environ["OGC_PACK_SWAP"] = "0"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ.setdefault("PYTHONUTF8", "1")

import json  # noqa: E402
import time  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    rows = []
    total, feas, minus1 = 0, 0, 0
    t_all = time.time()
    print(f"== ALL40 @ TL={_TL}s  fit={_FITV}  (diverse+near-접촉+캡, 토스/스왑 off) ==", flush=True)
    for k in range(1, 41):
        nm = f"prob_{k}"
        path = os.path.join(TRAIN, nm + ".json")
        if not os.path.exists(path):
            continue
        data = json.load(open(path, encoding="utf-8"))
        N = len(data["blocks"])
        m = len(data["bays"])
        t0 = time.time()
        try:
            res, dist, cpsat, dt = ug.unified(data, _TL, path)
            obj = res.get("objective")
        except Exception as e:
            obj, res, dist = None, {"err": str(e)[:80]}, []
        dt = time.time() - t0
        ok = obj is not None
        if ok:
            feas += 1
            total += obj
            tag = "OK"
            zz = f"z1={res.get('obj1')} z2={res.get('obj2')} z3={res.get('obj3')}"
        else:
            minus1 += 1
            tag = "INFEAS/-1"
            zz = f"stage={res.get('stage')} {res.get('err','')}"
        st = "set1" if k <= 20 else "set2"
        print(f"  [{st}] {nm:9s} N={N:3d} {m}b  {tag:9s} "
              f"obj={obj if obj is None else f'{obj:>13,.0f}'}  {zz}  dist={dist}  {dt:.0f}s", flush=True)
        rows.append({"nm": nm, "set": st, "N": N, "m": m, "obj": obj,
                     "z1": res.get("obj1"), "z2": res.get("obj2"), "z3": res.get("obj3"),
                     "dist": dist, "s": round(dt, 1)})
    set1 = sum(r["obj"] for r in rows if r["set"] == "set1" and r["obj"] is not None)
    set2 = sum(r["obj"] for r in rows if r["set"] == "set2" and r["obj"] is not None)
    print(f"\n== 총계: feasible {feas}/40, INFEAS/-1 {minus1}, "
          f"총 obj={total:,.0f} (set1={set1:,.0f} set2={set2:,.0f}), 전체 {time.time()-t_all:.0f}s ==", flush=True)
    out = {"tl": _TL, "fit": _FITV, "feasible": feas, "minus1": minus1,
           "total": total, "set1": set1, "set2": set2, "rows": rows}
    json.dump(out, open(os.path.join(THIS, "out", f"all40_fit{_FITV}.json"), "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
