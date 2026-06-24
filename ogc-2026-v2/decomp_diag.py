"""decomp_diag.py — 가설 검증: 베이의 배치 블록이 XY 풋프린트 겹침 기준으로
독립 연결성분(=독립 서브베이)으로 분해되는가?

(A) 점유-풋프린트 겹침 그래프: node=배치블록, edge=풋프린트 XY 교차(면적>0).
    연결성분 = 공간·크레인·시간 전부 독립인 클러스터(무손실 분해 단위).
출력: 베이별 블록수 → 연결성분 수 + 성분 크기 분포. (분해가 클수록 타이밍 분할 이득.)

실행: <env-python> decomp_diag.py <tl> <prob ...>
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

import unified_greedy as ug  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def footprint(blk, orient, x, y):
    polys = []
    shp = blk["shape"]
    o = orient if 0 <= orient < len(shp) else 0
    for ring in shp[o]["layers"]:
        if len(ring) >= 3:
            polys.append(Polygon([(px + x, py + y) for px, py in ring]))
    if not polys:
        return None
    u = unary_union(polys)
    return u if u.area > 1e-9 else None


def components(foots, spans=None):
    """foots: list[(bid, polygon)] → 연결성분.
    spans=None → XY 풋프린트 겹침만(시간무시).
    spans={bid:(entry,exit)} → 시공간: 풋프린트 겹침 AND 시간구간 겹침일 때만 edge."""
    n = len(foots)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    geoms = [f[1] for f in foots]
    tree = STRtree(geoms)
    for i in range(n):
        bi = foots[i][0]
        for j in tree.query(geoms[i]):
            j = int(j)
            if j <= i:
                continue
            if geoms[i].intersection(geoms[j]).area <= 1e-9:
                continue
            if spans is not None:
                e1, x1 = spans[bi]
                e2, x2 = spans[foots[j][0]]
                if not (e1 < x2 and e2 < x1):   # 시간구간 비겹침 → 비커플링
                    continue
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb
    comp = {}
    for i in range(n):
        comp.setdefault(find(i), []).append(foots[i][0])
    return list(comp.values())


def analyze(data, sol, label):
    """sol 의 베이별 공존(시공간) 구조 출력 + 최대동시공존수."""
    by_bay, spans = {}, {}
    for st, ops in sol["operations"].items():
        for op in ops:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                j = int(op["bay_id"])
                f = footprint(data["blocks"][bid], int(op.get("orient_idx", 0)),
                              op.get("x", 0), op.get("y", 0))
                if f is not None:
                    by_bay.setdefault(j, []).append((bid, f))
                spans[bid] = [float(st), None]
            elif bid in spans:
                spans[bid][1] = float(st)
    spans = {b: (e, x if x is not None else e + 1) for b, (e, x) in spans.items()}
    for j in sorted(by_bay):
        nb = len(by_bay[j])
        c_xy = components(by_bay[j])
        c_st = components(by_bay[j], spans)
        s_st = sorted((len(c) for c in c_st), reverse=True)
        # 최대 동시공존 블록수 (시간축 스위프)
        evs = []
        for bid, _ in by_bay[j]:
            e, x = spans[bid]
            evs.append((e, 1))
            evs.append((x, -1))
        evs.sort()
        cur = mx = 0
        for _, d in evs:
            cur += d
            mx = max(mx, cur)
        print(f"  [{label}] bay{j}: {nb}블록 | XY성분{len(c_xy)} | 시공간성분{len(c_st)}(최대{s_st[0]})"
              f" | 최대동시공존={mx}", flush=True)


def diag(nm, tl):
    path = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(path, encoding="utf-8"))
    # 원래 솔버
    from myalgorithm import algorithm as orig_alg
    osol = orig_alg(data, tl)
    from utils import check_feasibility
    ores = check_feasibility(data, osol)
    print(f"\n[{nm}] 원래: obj={ores.get('objective')} z1={ores.get('obj1')}", flush=True)
    analyze(data, osol, "원래")
    # 우리 통합
    res, dist, cpsat, dt = ug.unified(data, tl, path)
    sol = res.get("_solution") if isinstance(res, dict) else None
    print(f"[{nm}] 우리: obj={res.get('objective')} z1={res.get('obj1')} dist={dist} ({dt:.0f}s)", flush=True)
    if sol:
        analyze(data, sol, "우리")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or ["prob_25"]
    for nm in names:
        diag(nm, tl)


if __name__ == "__main__":
    main()
