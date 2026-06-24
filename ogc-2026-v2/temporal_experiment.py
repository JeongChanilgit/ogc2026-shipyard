"""
temporal_experiment.py — 시간축 Z1 측정 (밀도→지각 전환 + overhang스택 + 진입순서 탐색).

비교 (prob_29 혼잡 베이, 전부 폴리곤 기하):
  no-wait LB          : Σ max(0, R+P−D)  — 혼잡 0 가정 하한
  POLY  no-stack EDD  : 시간재사용만, overhang 스택 금지
  POLY  stack    EDD  : overhang 스택 허용 (exit_top<=exit_bottom 가드)
  POLY  stack + search: 진입순서 멀티스타트+스왑 (4코어) best-of

각 모드의 Z1 + 내부검증(공존 같은-층 무겹침 + 크레인 exit LIFO) 보고. best → 진입/퇴출
트레이스 viz (블록 들고남 애니메이션).

실행: <env-python> temporal_experiment.py
"""
from __future__ import annotations

import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from temporal_pack import build_subset, simulate, seed_order, search  # noqa: E402

try:
    from viz import write_viz
except Exception:
    write_viz = None

INST = os.path.join(THIS, "..", "instances", "train", "prob_29.json")
SCALE = 2
OUT = os.path.join(THIS, "out")
BUDGET = 80          # 워커당 스왑 시도 수 (속도/탐색 균형)


def no_wait_lb(sub):
    return sum(max(0, R + P - D) for (R, P, D) in sub["meta"].values())


def selfcheck(sub, placed):
    """공존 같은-층 무겹침 + 크레인 exit(나갈 때 위에 블록 없음) 내부 검증."""
    from shapely.affinity import translate
    shapes = sub["shapes"]
    P = []
    for (bid, x, y, oi, en, ex) in placed:
        sh = next(s for s in shapes[bid] if s.orient_idx == oi)
        wp = {l: translate(sh.layers[l].poly, xoff=x, yoff=y) for l in range(sh.n_layers)}
        P.append({"id": bid, "wp": wp, "en": en, "ex": ex})
    max_ov = 0.0
    crane_bad = 0
    for a in range(len(P)):
        A = P[a]
        for b in range(len(P)):
            if a == b:
                continue
            B = P[b]
            # 시간 공존?
            if not (A["en"] < B["ex"] and B["en"] < A["ex"]):
                continue
            # 같은-층 충돌
            if b > a:
                for l in A["wp"].keys() & B["wp"].keys():
                    max_ov = max(max_ov, A["wp"][l].intersection(B["wp"][l]).area)
        # 크레인 exit: A 나갈 때(te) 위에 얹힌 B 가 A보다 *늦게* 나가면 위반.
        # (B.ex == te 동시퇴출은 EXIT 순서로 위→아래 빼면 되므로 OK)
        te = A["ex"]
        for b in range(len(P)):
            if a == b:
                continue
            B = P[b]
            if not (B["en"] <= te - 1e-9 and B["ex"] > te + 1e-9):  # B 가 A보다 늦게까지 존재
                continue
            for la in A["wp"].keys():
                for lb in B["wp"].keys():
                    if lb > la and B["wp"][lb].intersection(A["wp"][la]).area > 1e-7:
                        crane_bad += 1
    return max_ov, crane_bad


def run_mode(sub, order, allow_stack, label):
    t0 = time.time()
    placed, z1 = simulate(sub, order, allow_stack)
    dt = time.time() - t0
    pl = [(p["id"], p["x"], p["y"], p["orient"], p["entry"], p["exit"]) for p in placed]
    ov, crane = selfcheck(sub, pl)
    return {"label": label, "z1": z1, "n": len(placed), "time": dt,
            "max_ov": ov, "crane_bad": crane, "placed": pl}


def make_trace(sub, placed, label):
    import json
    data = json.load(open(INST, encoding="utf-8"))
    blocks = data["blocks"]
    tr = {"instance": "prob_29",
          "bay": {"id": sub["bay_id"], "width": sub["W"], "height": sub["H"],
                  "max_layer": sub["max_layer"]},
          "blocks": {}, "events": [],
          "stats": {"mode": label, "n": len(placed)}}
    for (bid, x, y, oi, en, ex) in placed:
        lr = blocks[bid]["shape"][oi]["layers"]
        tr["blocks"][str(bid)] = {
            "orient_idx": oi,
            "layers": [[[float(px), float(py)] for px, py in lyr] for lyr in lr],
            "release": blocks[bid].get("release_time", 0),
            "due": blocks[bid].get("due_date", 0),
            "proc": blocks[bid].get("processing_time", 0)}
        tr["events"].append({"t": int(en), "type": "ENTRY", "block_id": bid, "x": x, "y": y})
        tr["events"].append({"t": int(ex), "type": "EXIT", "block_id": bid})
    tr["events"].sort(key=lambda e: (e["t"], 0 if e["type"] == "EXIT" else 1))
    return tr


def main():
    os.makedirs(OUT, exist_ok=True)
    sub = build_subset(INST, None, SCALE)
    print(f"== temporal Z1 (prob_29 bay {sub['bay_id']} {sub['W']}x{sub['H']}, "
          f"{len(sub['subset'])} blocks) ==\n")

    lb = no_wait_lb(sub)
    edd = seed_order(sub, "edd")
    print(f"no-wait LB (Σmax(0,R+P−D))        Z1 = {lb}")

    rows = []
    rows.append(run_mode(sub, edd, False, "POLY no-stack / EDD"))
    rows.append(run_mode(sub, edd, True, "POLY stack    / EDD"))

    t0 = time.time()
    best, results = search(INST, None, SCALE,
                           seeds=["edd", "area", "height", "release"],
                           allow_stack=True, budget=BUDGET, workers=4)
    wall = time.time() - t0
    ov, crane = selfcheck(sub, best["placed"])
    rows.append({"label": "POLY stack + search", "z1": best["z1"],
                 "n": len(best["placed"]), "time": wall,
                 "max_ov": ov, "crane_bad": crane, "placed": best["placed"]})

    print(f"\n{'모드':<26}{'Z1':>10}{'배치':>6}{'겹침':>8}{'크레인위반':>10}{'시간':>8}")
    print("-" * 70)
    for r in rows:
        print(f"{r['label']:<26}{r['z1']:>10}{r['n']:>6}{r['max_ov']:>8.4f}"
              f"{r['crane_bad']:>10}{r['time']:>8.1f}")
    print("-" * 70)
    print(f"search seed별 Z1: " +
          ", ".join(f"{x['seed_key']}={x['z1']}" for x in results) +
          f"  (wall {wall:.1f}s, best seed={best['seed_key']})")

    base = rows[0]["z1"]
    bz = rows[-1]["z1"]
    print(f"\n=> no-stack EDD {base} → stack+search {bz} "
          f"({'−' if bz<base else '+'}{abs(base-bz)}), LB={lb}")

    if write_viz is not None:
        out = os.path.join(OUT, f"prob_29_bay{sub['bay_id']}_temporal.html")
        write_viz(make_trace(sub, rows[-1]["placed"], rows[-1]["label"]), out)
        print(f"viz (진입/퇴출 애니메이션): {out}")

    print("\n== 끝 ==")


if __name__ == "__main__":
    main()
