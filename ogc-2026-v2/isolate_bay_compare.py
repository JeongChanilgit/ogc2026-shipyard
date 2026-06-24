"""
isolate_bay_compare.py — 미어터진(high-z1) 베이를 격리해 패킹만 공정 비교.

각 격리 베이를 단일-베이 mini 문제로 만들어:
  BEFORE = algorithm(mini)              → 원래 fastfloor 패킹 + CP-SAT 타이밍
  AFTER  = algorithm(mini, v2 patched)  → v2 패킹 + (같은) CP-SAT 타이밍
단일 베이라 배정 자명·z3=0 → 순수 패킹→z1 비교. 3D + interlock 지표 + z1.

실행: <env-python> isolate_bay_compare.py 200 prob_38 prob_37
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
import myalgorithm  # noqa: E402
from run_hybrid import patch, unpatch, _CACHE  # noqa: E402  (v2 monkeypatch)
from run_original import ops_to_trace  # noqa: E402
from pack_compare_3d import interlock_metrics  # noqa: E402
from viz import write_viz  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
OUT = os.path.join(THIS, "out")


def parse_bays(data, sol):
    """full 솔루션 → {bay_idx: {ids, z1, W, H}} (per-bay tardiness)."""
    blocks, bays = data["blocks"], data["bays"]
    ent, ext = {}, {}
    for t, opl in sol["operations"].items():
        for o in opl:
            if o["type"] == "ENTRY":
                ent[o["block_id"]] = o["bay_id"]
            else:
                ext[o["block_id"]] = int(t)
    out = {}
    for bid, bj in ent.items():
        d = out.setdefault(bj, {"ids": [], "z1": 0,
                                "W": bays[bj]["width"], "H": bays[bj]["height"]})
        d["ids"].append(bid)
        d["z1"] += max(0, ext.get(bid, 0) - blocks[bid]["due_date"])
    return out


def make_mini(data, ids):
    """단일-베이 mini (블록 0..k-1 재인덱싱, 선호=[100]→z3=0)."""
    blocks = []
    for i in ids:
        b = dict(data["blocks"][i])
        b["bay_preferences"] = [100]
        blocks.append(b)
    return blocks


def layout_from_ops(blocks, ops):
    lay = {}
    ext = {}
    for t, opl in ops.items():
        for o in opl:
            if o["type"] == "EXIT":
                ext[o["block_id"]] = int(t)
    for t, opl in ops.items():
        for o in opl:
            if o["type"] == "ENTRY":
                lay[o["block_id"]] = {"x": o.get("x", 0), "y": o.get("y", 0),
                                      "orient_idx": o.get("orient_idx", 0),
                                      "entry_time": int(t),
                                      "exit_time": ext.get(o["block_id"], int(t))}
    return lay


def run_mini(mini_prob, tl):
    sol = myalgorithm.algorithm(mini_prob, tl)
    res = utils.check_feasibility(mini_prob, sol)
    return sol, res


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 200.0
    insts = sys.argv[2:] or ["prob_38", "prob_37"]
    os.makedirs(OUT, exist_ok=True)

    # 1) full 원래 솔버 → per-bay z1 → 미어터진 베이 수집
    cand = []   # (z1, inst, bay_idx, ids, W, H)
    for nm in insts:
        data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
        print(f"[full] {nm} @ {tl}s ...", flush=True)
        unpatch()
        sol, res = run_mini(data, tl)        # full instance (mini_prob == data)
        print(f"   feasible={res.get('feasible')} obj={res.get('objective')} z1={res.get('obj1')}", flush=True)
        for bj, d in parse_bays(data, sol).items():
            cand.append((d["z1"], nm, bj, d["ids"], d["W"], d["H"], data))
            print(f"   bay {bj}: {len(d['ids'])} blocks, z1={d['z1']}", flush=True)
    cand.sort(key=lambda c: -c[0])
    top = cand[:3]
    print(f"\n미어터진 top-3 베이: " +
          ", ".join(f"{c[1]}.bay{c[2]}(z1={c[0]})" for c in top), flush=True)

    # 2) 각 격리 베이: BEFORE(fastfloor) vs AFTER(v2), 둘 다 CP-SAT 타이밍
    print(f"\n{'='*70}", flush=True)
    for (z1f, nm, bj, ids, W, H, data) in top:
        tag = f"{nm}_bay{bj}"
        mini_blocks = make_mini(data, ids)
        mini = {"name": tag, "bays": [{"width": W, "height": H}],
                "blocks": mini_blocks, "weights": data["weights"]}
        print(f"\n[격리 {tag}] {len(ids)} blocks, {W}x{H}, full-z1={z1f}", flush=True)

        unpatch(); _CACHE.clear()
        sb, rb = run_mini(mini, tl)
        patch()
        sa, ra = run_mini(mini, tl)
        unpatch()

        lb = layout_from_ops(mini_blocks, sb["operations"])
        la = layout_from_ops(mini_blocks, sa["operations"])
        mb = interlock_metrics(mini_blocks, lb)
        ma = interlock_metrics(mini_blocks, la)

        print(f"  {'':<18}{'BEFORE(fastfloor)':>20}{'AFTER(v2)':>14}", flush=True)
        print(f"  {'feasible':<18}{str(rb.get('feasible')):>20}{str(ra.get('feasible')):>14}", flush=True)
        print(f"  {'z1 (CP-SAT timed)':<18}{(rb.get('obj1') or -1):>20.0f}{(ra.get('obj1') or -1):>14.0f}", flush=True)
        print(f"  {'interlock 쌍':<18}{mb['interlock']:>20}{ma['interlock']:>14}", flush=True)
        print(f"  {'동시공존 쌍':<18}{mb['copresent']:>20}{ma['copresent']:>14}", flush=True)
        for sol, res, suf in [(sb, rb, "BEFORE_fastfloor"), (sa, ra, "AFTER_v2")]:
            try:
                tr, _b = ops_to_trace(mini, sol["operations"], suf, tag)
                write_viz(tr, os.path.join(OUT, f"iso_{tag}_{suf}.html"))
            except Exception as e:
                print(f"    viz {suf} 실패: {e}", flush=True)
        z1b, z1a = rb.get('obj1'), ra.get('obj1')
        if z1b is not None and z1a is not None:
            print(f"  => 패킹만의 z1 효과: {z1b:.0f} → {z1a:.0f} "
                  f"({'v2 개선' if z1a < z1b else 'v2 악화/동률'} {z1b-z1a:+.0f})", flush=True)

    print(f"\n3D: out/iso_*_{{BEFORE_fastfloor,AFTER_v2}}.html", flush=True)


if __name__ == "__main__":
    main()
