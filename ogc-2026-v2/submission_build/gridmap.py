"""
gridmap.py — 정수격자 비트맵 패킹 커널 (ROMA 침투맵 방식).

핵심 아이디어 (설계 README §0):
- 폴리곤을 정수격자에 래스터화 → 오버랩 검사 = numpy 부분배열 AND = 사실상 O(cells).
- AABB no-overlap 대신 *진짜 폴리곤 오목부*까지 활용 → 밀도 ↑ ("빠른 밀도").
- 레이어별 점유 격자 + suffix-OR 마스크로 크레인 j>=k 규칙을 같은 구조로 처리.

좌표/규약 (recon 확정):
- 베이 = 직사각형 [0,W]x[0,H]. 블록 배치는 정수 (x,y) 앵커 (평가서버 int(round)).
- shape[o]["layers"][l] = local 폴리곤 정점 리스트 [[x,y],...], NOT closed, float, 음수 가능.
- layers[0][0] == (0,0) = 앵커. world_vertex = local_vertex + (x, y). 전 레이어 동일 오프셋.
- layer 0 = 베이 바닥. 블록은 z 승강 없음 → 자기 layer l 이 곧 베이 높이 레벨 l.

검증의 진실은 항상 ../src/utils.py 의 check_feasibility. 이 모듈은 *빠른 후보 필터*다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import numpy as np

try:
    from shapely.geometry import Polygon, box as _box
    from shapely import area as _sh_area  # noqa: F401
    _HAVE_SHAPELY = True
except Exception:  # pragma: no cover - shapely expected in env
    _HAVE_SHAPELY = False


# --------------------------------------------------------------------------
# 폴리곤 유틸
# --------------------------------------------------------------------------
def shoelace_area(verts: list) -> float:
    """단순 폴리곤 면적 (절대값)."""
    n = len(verts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def _poly(verts):
    """shapely 폴리곤 (buffer(0) 자기교차/방향 보정)."""
    p = Polygon(verts)
    if not p.is_valid:
        p = p.buffer(0)
    return p


# --------------------------------------------------------------------------
# 블록 모양 → 레이어별 래스터 마스크 (local 프레임, 앵커 기준)
# --------------------------------------------------------------------------
@dataclass
class LayerMask:
    """한 레이어의 local 래스터: mask[row=cy, col=cx], 셀 오프셋(정수, *SCALE 단위)."""
    mask: np.ndarray            # bool (h_cells, w_cells)
    off_cx: int                 # local bbox 좌하단 셀 인덱스 (음수 가능)
    off_cy: int
    poly: object                # shapely Polygon (local) — 정확검사용
    area: float                 # 폴리곤 실제 면적 (격자 아님)


@dataclass
class BlockShape:
    """블록 한 방향(orient_idx)의 모든 레이어 모양 + 래스터."""
    block_id: int
    orient_idx: int
    scale: int
    layers: list = field(default_factory=list)   # list[LayerMask], layer0 first
    # local bbox (실수, 앵커=원점 기준; 음수 가능)
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0

    @property
    def n_layers(self) -> int:
        return len(self.layers)

    @property
    def footprint_area(self) -> float:
        """layer 0 면적 (= 바닥 점유)."""
        return self.layers[0].area if self.layers else 0.0

    @property
    def volume(self) -> float:
        """3D 부피 = 전 레이어 폴리곤 면적 합 (z 두께 1/레이어 가정)."""
        return sum(lm.area for lm in self.layers)

    @property
    def bbox_w(self) -> float:
        return self.max_x - self.min_x

    @property
    def bbox_h(self) -> float:
        return self.max_y - self.min_y


def _rasterize_layer(verts, scale: int) -> LayerMask:
    """local 폴리곤 → bool 마스크 (셀 중심이 폴리곤 내부면 점유 = tight, 변공유 허용).

    벡터화: shapely.vectorized.contains 우선, 없으면 prepared 폴리곤 루프 폴백.
    """
    poly = _poly(verts)
    minx, miny, maxx, maxy = poly.bounds
    off_cx = int(math.floor(minx * scale))
    off_cy = int(math.floor(miny * scale))
    end_cx = int(math.ceil(maxx * scale))
    end_cy = int(math.ceil(maxy * scale))
    w_cells = max(1, end_cx - off_cx)
    h_cells = max(1, end_cy - off_cy)
    inv = 1.0 / scale
    cxs = (np.arange(w_cells) + off_cx + 0.5) * inv      # 셀 중심 x
    cys = (np.arange(h_cells) + off_cy + 0.5) * inv      # 셀 중심 y
    XX, YY = np.meshgrid(cxs, cys)                        # (h, w)
    mask = None
    try:
        from shapely import vectorized as _vec  # type: ignore
        mask = _vec.contains(poly, XX.ravel(), YY.ravel()).reshape(h_cells, w_cells)
    except Exception:
        try:
            from shapely.prepared import prep
            from shapely.geometry import Point
            pp = prep(poly)
            mask = np.zeros((h_cells, w_cells), dtype=bool)
            for j in range(h_cells):
                for i in range(w_cells):
                    if pp.contains(Point(XX[j, i], YY[j, i])):
                        mask[j, i] = True
        except Exception:
            mask = np.ones((h_cells, w_cells), dtype=bool)   # 최후 폴백: bbox
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        # 아주 얇은 폴리곤 → 중심 셀이라도 점유로 (충돌검사 누락 방지)
        mask[h_cells // 2, w_cells // 2] = True
    return LayerMask(mask=mask, off_cx=off_cx, off_cy=off_cy,
                     poly=poly, area=poly.area)


def build_shape(block_id: int, block_data: dict, orient_idx: int, scale: int = 2) -> BlockShape:
    """blocks[i] 원본 dict + orient_idx → BlockShape (래스터 포함)."""
    layers_raw = block_data["shape"][orient_idx]["layers"]
    sh = BlockShape(block_id=block_id, orient_idx=orient_idx, scale=scale)
    gminx = gminy = math.inf
    gmaxx = gmaxy = -math.inf
    for verts in layers_raw:
        lm = _rasterize_layer(verts, scale)
        sh.layers.append(lm)
        b = lm.poly.bounds
        gminx, gminy = min(gminx, b[0]), min(gminy, b[1])
        gmaxx, gmaxy = max(gmaxx, b[2]), max(gmaxy, b[3])
    sh.min_x, sh.min_y, sh.max_x, sh.max_y = gminx, gminy, gmaxx, gmaxy
    return sh


# --------------------------------------------------------------------------
# 베이 점유 격자 + 크레인 suffix 마스크
# --------------------------------------------------------------------------
class BayGrid:
    """
    레이어별 점유 비트맵. 같은-층 충돌(stage4) + 크레인 j>=k(stage2/3) 를
    suffix-OR 마스크로 한 번에 검사.

    can_place_entry(): 새 블록을 (x,y)에 *지금 진입* 시킬 수 있나 (크레인 강하 포함).
    place()/remove():  점유 갱신.
    """

    def __init__(self, width: int, height: int, max_layer: int, scale: int = 2,
                 exact: bool = False):
        self.W = width
        self.H = height
        self.L = max_layer
        self.scale = scale
        self.wc = width * scale
        self.hc = height * scale
        # occ[l] : (hc, wc) bool — 레이어 l 점유
        self.occ = [np.zeros((self.hc, self.wc), dtype=bool) for _ in range(max_layer)]
        self._placed: dict = {}   # block_id -> (shape, x, y)
        # exact=True: 비트맵(빠른 사전필터) 통과 후 shapely 정확검사로 커밋 → 격자
        # 경계 누수(셀중심 래스터의 미세 겹침) 제거. 약간 느리지만 feasibility-clean.
        self.exact = exact
        self._wpolys: list = []   # [(block_id, {layer: world shapely poly})]

    # --- 내부: 블록 레이어 l 의 셀 슬라이스 범위 (베이격자 인덱스) ---
    def _slice(self, shape: BlockShape, layer: int, x: int, y: int):
        lm = shape.layers[layer]
        c0 = x * self.scale + lm.off_cx
        r0 = y * self.scale + lm.off_cy
        c1 = c0 + lm.mask.shape[1]
        r1 = r0 + lm.mask.shape[0]
        return r0, r1, c0, c1, lm.mask

    def in_bounds(self, shape: BlockShape, x: int, y: int) -> bool:
        """베이 경계 안에 폴리곤 bbox 전체가 들어오나 (recon: bbox min>=0, max<=W/H)."""
        if shape.min_x + x < -1e-6 or shape.min_y + y < -1e-6:
            return False
        if shape.max_x + x > self.W + 1e-6 or shape.max_y + y > self.H + 1e-6:
            return False
        return True

    def _world_polys(self, shape: BlockShape, x: int, y: int) -> dict:
        from shapely.affinity import translate
        return {l: translate(shape.layers[l].poly, xoff=x, yoff=y)
                for l in range(shape.n_layers)}

    def _exact_clear(self, shape: BlockShape, x: int, y: int) -> bool:
        """shapely 정확 같은-층 무겹침 (변/꼭짓점 공유는 허용, area>eps 만 충돌)."""
        wp = self._world_polys(shape, x, y)
        for (_bid, ep) in self._wpolys:
            for l in set(wp) & set(ep):
                if wp[l].intersection(ep[l]).area > 1e-7:
                    return False
        return True

    def _suffix_occ(self, from_layer: int) -> np.ndarray:
        """레이어 >= from_layer 의 점유 OR (크레인 강하 차단 영역)."""
        acc = np.zeros((self.hc, self.wc), dtype=bool)
        for l in range(from_layer, self.L):
            acc |= self.occ[l]
        return acc

    def can_place_entry(self, shape: BlockShape, x: int, y: int,
                        check_bounds: bool = True) -> bool:
        """
        크레인 진입 가능? 각 레이어 l1 에 대해, 기존 점유(레이어 >= l1)와 겹치면 불가.
        (j>=k 규칙. l2==l1 포함 → 같은-층 충돌도 자동 포함.)
        """
        if check_bounds and not self.in_bounds(shape, x, y):
            return False
        for l1 in range(shape.n_layers):
            r0, r1, c0, c1, m = self._slice(shape, l1, x, y)
            if r0 < 0 or c0 < 0 or r1 > self.hc or c1 > self.wc:
                return False
            blocked = self._suffix_occ(l1)[r0:r1, c0:c1]
            if np.any(blocked & m):
                return False
        return True

    def can_coexist(self, shape: BlockShape, x: int, y: int,
                    check_bounds: bool = True) -> bool:
        """
        같은-층 충돌만 검사 (크레인 순서 무시, '동시에 놓을 수 있나' = 정적 max-fit용).
        """
        if check_bounds and not self.in_bounds(shape, x, y):
            return False
        for l1 in range(shape.n_layers):
            r0, r1, c0, c1, m = self._slice(shape, l1, x, y)
            if r0 < 0 or c0 < 0 or r1 > self.hc or c1 > self.wc:
                return False
            if np.any(self.occ[l1][r0:r1, c0:c1] & m):
                return False
        if self.exact and not self._exact_clear(shape, x, y):
            return False
        return True

    def place(self, shape: BlockShape, x: int, y: int):
        for l1 in range(shape.n_layers):
            r0, r1, c0, c1, m = self._slice(shape, l1, x, y)
            self.occ[l1][r0:r1, c0:c1] |= m
        self._placed[shape.block_id] = (shape, x, y)
        if self.exact:
            self._wpolys.append((shape.block_id, self._world_polys(shape, x, y)))

    def remove(self, block_id: int):
        shape, x, y = self._placed.pop(block_id)
        for l1 in range(shape.n_layers):
            r0, r1, c0, c1, m = self._slice(shape, l1, x, y)
            # 다른 블록과 셀 공유가 없다는 전제(tight raster) → 해당 셀 끔.
            self.occ[l1][r0:r1, c0:c1] &= ~m
        if self.exact:
            self._wpolys = [e for e in self._wpolys if e[0] != block_id]

    # --- 측정 ---
    def floor_utilization(self) -> float:
        """layer 0 점유 셀 비율 (면적활용 근사)."""
        return float(self.occ[0].sum()) / float(self.hc * self.wc)

    def occupied_floor_area(self) -> float:
        """배치된 블록 layer0 실제 폴리곤 면적 합 / 베이 바닥 면적."""
        tot = sum(sh.footprint_area for (sh, _, _) in self._placed.values())
        return tot / float(self.W * self.H)

    @property
    def n_placed(self) -> int:
        return len(self._placed)


# --------------------------------------------------------------------------
# AABB 비교용 (옛 방식): 바운딩박스 no-overlap
# --------------------------------------------------------------------------
class AABBGrid:
    """옛 솔버 방식 — 블록을 bbox 로 보고 겹침 금지. 폴리곤 오목부 활용 0."""

    def __init__(self, width: int, height: int, max_layer: int):
        self.W = width
        self.H = height
        self.L = max_layer
        self._rects: list = []     # (block_id, lo_x, lo_y, hi_x, hi_y, n_layers)
        self._placed: dict = {}

    def in_bounds(self, shape: BlockShape, x: int, y: int) -> bool:
        return not (shape.min_x + x < -1e-6 or shape.min_y + y < -1e-6 or
                    shape.max_x + x > self.W + 1e-6 or shape.max_y + y > self.H + 1e-6)

    def can_coexist(self, shape: BlockShape, x: int, y: int,
                    check_bounds: bool = True) -> bool:
        if check_bounds and not self.in_bounds(shape, x, y):
            return False
        lo_x, lo_y = shape.min_x + x, shape.min_y + y
        hi_x, hi_y = shape.max_x + x, shape.max_y + y
        for (_bid, ax0, ay0, ax1, ay1, _nl) in self._rects:
            # AABB 겹침 (변 접촉은 허용)
            if lo_x < ax1 - 1e-6 and ax0 < hi_x - 1e-6 and \
               lo_y < ay1 - 1e-6 and ay0 < hi_y - 1e-6:
                return False
        return True

    # 정적 max-fit 비교에선 크레인 순서 무시 → can_place_entry == can_coexist
    can_place_entry = can_coexist

    def place(self, shape: BlockShape, x: int, y: int):
        self._rects.append((shape.block_id, shape.min_x + x, shape.min_y + y,
                            shape.max_x + x, shape.max_y + y, shape.n_layers))
        self._placed[shape.block_id] = (shape, x, y)

    def remove(self, block_id: int):
        self._placed.pop(block_id)
        self._rects = [r for r in self._rects if r[0] != block_id]

    def occupied_floor_area(self) -> float:
        tot = sum(sh.footprint_area for (sh, _, _) in self._placed.values())
        return tot / float(self.W * self.H)

    @property
    def n_placed(self) -> int:
        return len(self._placed)


__all__ = [
    "BlockShape", "LayerMask", "BayGrid", "AABBGrid",
    "build_shape", "shoelace_area",
]
