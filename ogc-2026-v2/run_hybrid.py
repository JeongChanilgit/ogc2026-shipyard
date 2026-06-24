"""
run_hybrid.py — 원래 솔버 패킹 이식 전/후 비교 (다중 인스턴스, 3D + 수치).

BEFORE: 원래 솔버 (T>=200 → PURE gassign 레짐, fastfloor 패킹). box 는 reserve=1s 로 격리.
AFTER : fastfloor._fixed_time_decode 를 v2 폴리곤 패커로 monkeypatch
        → v2 밀도 layout + 원래 CP-SAT 타이밍/배정. (src 수정 없음, patch/unpatch 복원)

실행: <env-python> run_hybrid.py 240 prob_37 prob_38 prob_39 prob_40
"""
from __future__ import annotations

import os

os.environ.setdefault("OGC_HYBRID_RESERVE_S", "1")     # box 굶겨 패킹 스왑만 격리

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
from assign_search import build_set, SCALE  # noqa: E402
from temporal_pack import simulate, seed_order  # noqa: E402
from run_original import ops_to_trace  # noqa: E402
from viz import write_viz  # noqa: E402
import myalgorithm  # noqa: E402  (gassign, fastfloor 체인 로드)

TRAIN = os.path.join(THIS, "..", "instances", "train")
OUT = os.path.join(THIS, "out")
_CACHE = {}
_ORIG = {}


def my_v2_decode(bay, bay_idx, ids, blocks_data, deadline, order_key="F0", use_lca=None):
    key = (bay_idx, frozenset(ids))
    if key not in _CACHE:
        sub = build_set(blocks_data, bay.width, bay.height, list(ids), SCALE)
        placed, _ = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
        _CACHE[key] = {
            p["id"]: {"block_id": p["id"], "bay_id": bay_idx,
                      "x": int(p["x"]), "y": int(p["y"]), "orient_idx": int(p["orient"]),
                      "entry_time": int(p["entry"]), "exit_time": int(p["exit"])}
            for p in placed}
    return dict(_CACHE[key]), {}


def patch():
    n = 0
    for m in list(sys.modules.values()):
        if m is not None and m.__name__ != __name__ \
                and getattr(m, "_fixed_time_decode", None) is not None:
            if m not in _ORIG:
                _ORIG[m] = m._fixed_time_decode
            try:
                m._fixed_time_decode = my_v2_decode
                n += 1
            except Exception:
                pass
    return n


def unpatch():
    for m, f in _ORIG.items():
        try:
            m._fixed_time_decode = f
        except Exception:
            pass


def run_one(data, tl, tag, patched):
    label = "AFTER(v2)" if patched else "BEFORE(orig)"
    t0 = time.time()
    try:
        sol = myalgorithm.algorithm(data, tl)
    except Exception as e:
        print(f"  {label}: 실행 에러 {e}", flush=True)
        return None
    dt = time.time() - t0
    res = utils.check_feasibility(data, sol)
    print(f"  {label}: feasible={res.get('feasible')} obj={res.get('objective')} "
          f"(z1={res.get('obj1')}, z2={res.get('obj2')}, z3={res.get('obj3')})  {dt:.0f}s", flush=True)
    try:
        tr, bay = ops_to_trace(data, sol["operations"], label, tag)
        suff = "AFTER_v2pack" if patched else "BEFORE_orig"
        write_viz(tr, os.path.join(OUT, f"hyb_{tag}_{suff}_bay{bay}.html"))
    except Exception:
        pass
    return res


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    names = sys.argv[2:] or ["prob_37", "prob_38", "prob_39", "prob_40"]
    os.makedirs(OUT, exist_ok=True)
    print(f"== 패킹 이식 전후 (gassign 레짐, @{tl}s) : {', '.join(names)} ==", flush=True)
    summary = []
    for nm in names:
        data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
        print(f"\n[{nm}]  (N={len(data['blocks'])}, {len(data['bays'])}bays, "
              f"w1={data['weights']['w1']})", flush=True)
        unpatch()
        _CACHE.clear()
        rb = run_one(data, tl, nm, patched=False)
        patch()
        ra = run_one(data, tl, nm, patched=True)
        unpatch()
        if rb and ra and rb.get("objective") and ra.get("objective"):
            b, a = rb["objective"], ra["objective"]
            print(f"  => BEFORE {b:,.0f} → AFTER {a:,.0f}  "
                  f"({'개선' if a < b else '악화'} {(b-a)/b*100:+.1f}%, "
                  f"z1 {rb.get('obj1')}→{ra.get('obj1')})", flush=True)
            summary.append((nm, b, a, rb.get('obj1'), ra.get('obj1')))
    print("\n== 요약 ==", flush=True)
    for nm, b, a, zb, za in summary:
        print(f"  {nm}: {b:,.0f} → {a:,.0f}  ({(b-a)/b*100:+.1f}%)  z1 {zb}→{za}", flush=True)


if __name__ == "__main__":
    main()
