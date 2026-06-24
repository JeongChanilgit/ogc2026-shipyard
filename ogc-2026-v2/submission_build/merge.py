"""merge.py — 결합블록(forced 인터록 페어링) 사전 탐색.

겹침 큰 블록쌍 (A=아래/base, B=위/overhang) 을 찾아, 작은 오프셋 그리드에서
B 를 A 위에 올렸을 때 crane-feasible·무충돌·overlap>0 인 최적 인터록 구성을 구한다.
타이밍(case1/2·LIFO)은 CP-SAT 가 처리하므로, 여기선 *공간* 인터록만 본다.

find_pairs(blocks, ids, scale) → {base_id: (partner_id, dx, dy, oA, oB, overlap_area)}
  (greedy 매칭, 블록당 ≤1 파트너). 진단: <env-python> merge.py prob_25
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import numpy as np  # noqa: E402

from gridmap import build_shape  # noqa: E402

SCALE = 2
OFF = int(os.environ.get("OGC_MERGE_OFF", "3"))   # 오프셋 탐색 반경(월드)
MIN_OV = float(os.environ.get("OGC_MERGE_MINOV", "2.0"))  # 최소 인터록 셀수


def _mov(m1, r1, c1, m2, r2, c2):
    """마스크 m1@(r1,c1), m2@(r2,c2) 의 셀 겹침 수 (numpy, shapely 없음)."""
    h1, w1 = m1.shape
    h2, w2 = m2.shape
    rr0, cc0 = max(r1, r2), max(c1, c2)
    rr1, cc1 = min(r1 + h1, r2 + h2), min(c1 + w1, c2 + w2)
    if rr1 <= rr0 or cc1 <= cc0:
        return 0
    a = m1[rr0 - r1:rr1 - r1, cc0 - c1:cc1 - c1]
    b = m2[rr0 - r2:rr1 - r2, cc0 - c2:cc1 - c2]
    return int(np.logical_and(a, b).sum())


def _has_overhang(sh):
    """위층이 아래층과 다른 영역(오버행) 존재? (인터록 host 전제)."""
    if sh.n_layers < 2:
        return False
    return any(sh.layers[l].mask.shape != sh.layers[0].mask.shape
               or not np.array_equal(sh.layers[l].mask, sh.layers[0].mask)
               for l in range(1, sh.n_layers))


def best_interlock(shA, shB):
    """A(base) 위에 B 를 올리는 최적 인터록(orient0) → (overlap, dx, dy) | None.
    충돌(같은층 겹침)=0 이고 인터록(B 위층 over A 아래층)>0 인 오프셋 중 최대."""
    Acells = [(la, sh.off_cy, sh.off_cx, sh.mask) for la, sh in enumerate(shA.layers)]
    Bcells = [(lb, sh.off_cy, sh.off_cx, sh.mask) for lb, sh in enumerate(shB.layers)]
    best = None
    for dy in range(-OFF, OFF + 1):
        for dx in range(-OFF, OFF + 1):
            coll = inter = 0
            for (la, ay, ax, am) in Acells:
                for (lb, byo, bxo, bm) in Bcells:
                    ov = _mov(am, ay, ax, bm, dy * SCALE + byo, dx * SCALE + bxo)
                    if not ov:
                        continue
                    if la == lb:
                        coll += ov
                    elif lb > la:
                        inter += ov
                if coll:
                    break
            if coll == 0 and inter >= MIN_OV and (best is None or inter > best[0]):
                best = (inter, dx, dy)
    return best


def find_pairs(blocks, ids, scale, windows_ok=True):
    shapes = {i: build_shape(i, blocks[i], 0, scale) for i in ids}    # orient 0
    oh = {i: _has_overhang(shapes[i]) for i in ids}
    meta = {i: (blocks[i].get("release_time", 0), blocks[i].get("processing_time", 0),
                blocks[i].get("due_date", 0)) for i in ids}
    cand = []  # (overlap, A, B, dx, dy)
    for A in ids:
        for B in ids:
            if A == B or not (oh[A] or oh[B]):      # 오버행 없으면 인터록 불가
                continue
            if windows_ok:                          # 시간창 호환 (B 가 A 체류에 nest)
                rA, _, dA = meta[A]
                rB, _, dB = meta[B]
                if not (rB <= dA and rA <= dB):
                    continue
            r = best_interlock(shapes[A], shapes[B])
            if r:
                cand.append((r[0], A, B, r[1], r[2]))
    cand.sort(key=lambda c: -c[0])
    used, pairs = set(), {}
    for (ov, A, B, dx, dy) in cand:
        if A in used or B in used:
            continue
        used.add(A)
        used.add(B)
        pairs[A] = (B, dx, dy, ov)
    return pairs, len(cand)


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_25"
    data = json.load(open(os.path.join(THIS, "..", "instances", "train", nm + ".json"),
                          encoding="utf-8"))
    blocks = data["blocks"]
    ids = list(range(len(blocks)))           # 전체(베이 무관, 인터록 잠재력 측정)
    import time
    t0 = time.time()
    pairs, ncand = find_pairs(blocks, ids, SCALE)
    dt = time.time() - t0
    ovs = sorted((v[3] for v in pairs.values()), reverse=True)
    print(f"[{nm}] N={len(ids)}: 인터록 후보쌍 {ncand}개 → greedy 매칭 {len(pairs)}쌍 "
          f"({2*len(pairs)}/{len(ids)} 블록 결합)  [{dt:.1f}s]", flush=True)
    print(f"  매칭 overlap 셀수: max={ovs[0] if ovs else 0:.0f} "
          f"median={ovs[len(ovs)//2] if ovs else 0:.0f} 분포={[round(x) for x in ovs[:12]]}...",
          flush=True)


if __name__ == "__main__":
    main()
