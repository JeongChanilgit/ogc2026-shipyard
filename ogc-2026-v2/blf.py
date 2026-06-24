"""
blf.py — semi-discrete Bottom-Left Fill 배치기.

각 블록을 정수 컬럼 x 마다 가능한 가장 낮은 y 로 떨어뜨리고(semi-discrete),
전 후보 중 bottom-left(최소 y, 동률이면 최소 x) 를 고른다. 방향(orient)도 함께 탐색.

grid 는 gridmap.BayGrid(폴리곤) 또는 gridmap.AABBGrid(바운딩박스) — 같은 인터페이스
(can_coexist / can_place_entry / in_bounds / place). 동일 order 로 두 그리드를 돌리면
"폴리곤 오목부+overhang 을 살릴 때 vs AABB 일 때 몇 개가 더 들어가나" 가 바로 나온다.

entry_mode=True 면 크레인 강하(can_place_entry)까지 본 시간순 진입; False(기본)면
같은-층 충돌만 보는 정적 max-fit.
"""
from __future__ import annotations

import math


def bottom_left_fill(grid, shapes_by_block: dict, order: list,
                     *, entry_mode: bool = False, y_step: int = 1, x_step: int = 1):
    """
    grid            : BayGrid | AABBGrid
    shapes_by_block : block_id -> list[BlockShape]  (탐색할 방향들)
    order           : 배치 시도 순서 (block_id 리스트)
    return          : (placements, unplaced)
                      placements = [(block_id, x, y, orient_idx), ...]
    """
    test = grid.can_place_entry if entry_mode else grid.can_coexist
    placements = []
    unplaced = []

    for bid in order:
        best = None   # (y, x, shape)
        for sh in shapes_by_block[bid]:
            # bbox 가 [0,W]x[0,H] 안에 들어오는 정수 앵커 범위 (local 정점 음수 가능)
            x_lo = int(math.ceil(-sh.min_x - 1e-9))
            x_hi = int(math.floor(grid.W - sh.max_x + 1e-9))
            y_lo = int(math.ceil(-sh.min_y - 1e-9))
            y_hi = int(math.floor(grid.H - sh.max_y + 1e-9))
            if x_lo > x_hi or y_lo > y_hi:
                continue
            for x in range(x_lo, x_hi + 1, x_step):
                # 이 컬럼에서 가능한 가장 낮은 y (drop)
                for y in range(y_lo, y_hi + 1, y_step):
                    if test(sh, x, y, check_bounds=False):
                        if best is None or (y < best[0] or (y == best[0] and x < best[1])):
                            best = (y, x, sh)
                        break   # 이 x 의 최저 y 확보 → 다음 x
        if best is not None:
            y, x, sh = best
            grid.place(sh, x, y)
            placements.append((bid, x, y, sh.orient_idx))
        else:
            unplaced.append(bid)

    return placements, unplaced


__all__ = ["bottom_left_fill"]
