"""
temporal_pack.py — 시간축 패킹-스케줄러 (크레인 LIFO + exit-순서 제약 + 진입순서 탐색).

핵심 모델 (설계 토론 2026-06-19):
- 블록 i: release R, proc P, due D. exit = entry + P (지연 없음 보장, 아래 참조).
- 진입순서(permutation)를 입력받아 event-driven 시뮬:
    각 블록을 R 이후 *가장 이른* 시각에 배치. 자리 없으면 다음 exit 이벤트까지 대기
    (시간 재사용 = 나간 블록 footprint 재활용).
- 크레인 j>=k: 위에서만 진입 → can_place_entry(suffix-OR) 로 강하 경로 검사.
    ⇒ overhang 스택은 "바닥 먼저, 위 나중" 순서로만 가능 → *진입순서가 밀도를 결정*.
- exit 제약 (사용자): "아래 블록을 자기 exit보다 늦게 나가게 만들면 안 됨."
    ⇒ B 를 A 위에 얹는 스택은 exit_B(=t+P_B) <= exit_A 일 때만 허용.
    ⇒ 어떤 블록도 갇혀 지연 안 됨 → exit = entry+P 로 고정, Z1 깨끗.
- 목적: Z1 = Σ max(0, entry_i + P_i − D_i) 최소화 = 총 대기 최소화.

진입순서 탐색: 멀티스타트(EDD/area/height/...) + 페어 스왑 국소탐색, 4코어 병렬 best-of.
검증: 단일 베이 레벨에서 ../src/utils.py 의 check_entry/check_exit/check_collisions 재실행.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _swv

try:
    from scipy.signal import fftconvolve as _fftc
except Exception:
    _fftc = None
_FFT_MASK = (os.environ.get("OGC_FFT_MASK", "1") != "0") and _fftc is not None
_FFT_MIN = int(os.environ.get("OGC_FFT_MIN", "1500000"))   # 직접/FFT 분기 임계(pos·footprint)

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)
_SRC = os.path.join(THIS, "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from gridmap import build_shape, BlockShape, LayerMask  # noqa: E402
from density_pack import _common_masks  # noqa: E402

from shapely.affinity import translate as _translate  # noqa: E402
from shapely.geometry import box as _box  # noqa: E402

import utils as _utils  # noqa: E402  (공식 src/utils.py — 크레인 진입 게이트)


def _aabb_shape(sh, scale):
    """BlockShape → AABB 버전(단층 바운딩박스 사각형). 옛 AABB 방식 재현용."""
    minx, miny, maxx, maxy = sh.min_x, sh.min_y, sh.max_x, sh.max_y
    off_cx = int(math.floor(minx * scale))
    off_cy = int(math.floor(miny * scale))
    w = max(1, int(math.ceil(maxx * scale)) - off_cx)
    h = max(1, int(math.ceil(maxy * scale)) - off_cy)
    mask = np.ones((h, w), dtype=bool)
    rect = _box(minx, miny, maxx, maxy)
    lm = LayerMask(mask=mask, off_cx=off_cx, off_cy=off_cy, poly=rect, area=rect.area)
    return BlockShape(block_id=sh.block_id, orient_idx=sh.orient_idx, scale=scale,
                      layers=[lm], min_x=minx, min_y=miny, max_x=maxx, max_y=maxy)

BIGTIME = 10 ** 7


# --------------------------------------------------------------------------
def build_subset(inst_path, bay_id, scale, geom="poly"):
    """geom='poly'(실제 다층 폴리곤) | 'aabb'(단층 바운딩박스, 옛 방식)."""
    data = json.load(open(inst_path, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    m = len(bays)
    pref = [max(range(m), key=lambda j: b["bay_preferences"][j]) for b in blocks]
    if bay_id is None:
        bay_id = max(range(m), key=lambda j: pref.count(j))
    subset = [i for i in range(len(blocks)) if pref[i] == bay_id]
    W, H = bays[bay_id]["width"], bays[bay_id]["height"]
    meta = {}
    shapes = {}
    max_layer = 1
    cm = {}
    for i in subset:
        shs = [build_shape(i, blocks[i], o, scale) for o in range(len(blocks[i]["shape"]))]
        if geom == "aabb":
            shs = [_aabb_shape(s, scale) for s in shs]
        shapes[i] = shs
        for s in shs:
            cm[id(s)] = _common_masks(s, scale)
            max_layer = max(max_layer, s.n_layers)
        meta[i] = (blocks[i].get("release_time", 0),
                   blocks[i].get("processing_time", 0),
                   blocks[i].get("due_date", 0))
    return {"bay_id": bay_id, "W": W, "H": H, "max_layer": max_layer,
            "subset": subset, "meta": meta, "shapes": shapes, "cm": cm, "scale": scale,
            "raw": {i: blocks[i] for i in subset}}


def _occ_from_present(present, hc, wc, max_layer, scale):
    occ = [np.zeros((hc, wc), dtype=bool) for _ in range(max_layer)]
    for p in present:
        sh, x, y = p["sh"], p["x"], p["y"]
        for l in range(sh.n_layers):
            lm = sh.layers[l]
            r = y * scale + lm.off_cy
            c = x * scale + lm.off_cx
            mh, mw = lm.mask.shape
            r0, c0 = max(0, r), max(0, c)               # 범위 밖 방어 클램프
            r1, c1 = min(hc, r + mh), min(wc, c + mw)
            if r1 <= r0 or c1 <= c0:
                continue
            occ[l][r0:r1, c0:c1] |= lm.mask[r0 - r:r1 - r, c0 - c:c1 - c]
    return occ


def _suffix(occ, frm):
    acc = np.zeros_like(occ[0])
    for l in range(frm, len(occ)):
        acc |= occ[l]
    return acc


def _bl_candidates(occ, sh, cm, W, H, scale, limit=6, diverse=False):
    """크레인-feasible(j>=k) 위치 후보.
    diverse=False: bottom-left 순(각 행 leftmost) 최대 limit개 (기존).
    diverse=True : feasible 영역의 *경계*(인접에 점유/벽 있는 snug 위치) = 베이 전역
                   중간 gap·코너·인터록 자리까지. 균등 샘플로 limit개."""
    boff_cx, boff_cy, Hb, Wb, cmasks = cm
    hc, wc = occ[0].shape
    if Hb > hc or Wb > wc:
        return []
    feas = np.ones((hc - Hb + 1, wc - Wb + 1), dtype=bool)
    # 큰 footprint·베이면 sliding-window AND(O(pos·Hb·Wb))이 비쌈 → FFT 상관(O(N log N)).
    # ov(겹침수)는 정수라 float FFT 오차(~1e-10) < 0.5 → (ov==0) 판정 정확. 게이트 OGC_FFT_MASK.
    use_fft = _FFT_MASK and (hc - Hb + 1) * (wc - Wb + 1) * Hb * Wb > _FFT_MIN
    for l1 in range(sh.n_layers):
        suf = _suffix(occ, l1)                      # 레이어 >= l1 (크레인 강하 차단)
        if use_fft:
            ov = _fftc(suf.astype(np.float64), cmasks[l1][::-1, ::-1].astype(np.float64), mode="valid")
            feas &= (ov < 0.5)
        else:
            win = _swv(suf, (Hb, Wb))
            ov = np.logical_and(win, cmasks[l1]).sum(axis=(2, 3))
            feas &= (ov == 0)
    xs = np.arange(int(np.ceil(-sh.min_x - 1e-9)), int(np.floor(W - sh.max_x + 1e-9)) + 1)
    ys = np.arange(int(np.ceil(-sh.min_y - 1e-9)), int(np.floor(H - sh.max_y + 1e-9)) + 1)
    if xs.size == 0 or ys.size == 0:
        return []
    cols = xs * scale + boff_cx
    rows = ys * scale + boff_cy
    cm_ok = (cols >= 0) & (cols <= wc - Wb)
    rm_ok = (rows >= 0) & (rows <= hc - Hb)
    xs, cols = xs[cm_ok], cols[cm_ok]
    ys, rows = ys[rm_ok], rows[rm_ok]
    if xs.size == 0 or ys.size == 0:
        return []
    sub = feas[np.ix_(rows, cols)]                  # (ny, nx)
    if diverse:
        ny, nx = sub.shape
        sp = np.zeros((ny + 2, nx + 2), dtype=bool)  # 격자 밖 = infeasible
        sp[1:-1, 1:-1] = sub
        interior = (sub & sp[0:ny, 1:nx + 1] & sp[2:ny + 2, 1:nx + 1]
                    & sp[1:ny + 1, 0:nx] & sp[1:ny + 1, 2:nx + 2])
        boundary = sub & ~interior                  # 인접에 점유/벽 있는 snug 자리
        ris, cis = np.where(boundary)
        out = [(int(xs[c]), int(ys[r])) for r, c in zip(ris, cis)]
        if len(out) > limit:                        # 균등 샘플
            step = len(out) / limit
            out = [out[int(i * step)] for i in range(limit)]
        return out
    out = []
    for ri in range(sub.shape[0]):                  # y 오름차순 = 아래부터
        row = sub[ri]
        for ci in range(row.shape[0]):              # x 오름차순 = 왼쪽부터
            if row[ci]:
                out.append((int(xs[ci]), int(ys[ri])))
                break                               # 이 y에서 가장 왼쪽 하나
        if len(out) >= limit:
            break
    return out


def _world(sh, x, y):
    return {l: _translate(sh.layers[l].poly, xoff=x, yoff=y) for l in range(sh.n_layers)}


def _collision_free(wp, present):
    for A in present:
        aw = A["world"]
        for l in wp.keys() & aw.keys():
            if wp[l].intersection(aw[l]).area > 1e-7:
                return False
    return True


def _crane_ok(wp, present):
    """정확 크레인 진입(j>=k): B의 레이어 lb 강하 시, 기존 A의 레이어 la>=lb 겹치면 불가.
    (la==lb 같은-층 충돌 포함). 비트맵 사전필터의 격자 누수를 shapely로 보정."""
    for A in present:
        aw = A["world"]
        for lb in wp.keys():
            for la in aw.keys():
                if la >= lb and wp[lb].intersection(aw[la]).area > 1e-7:
                    return False
    return True


def _trap_ok(wp, t_entry, P, present, allow_stack):
    """B(wp, entry=t_entry, exit=t_entry+P) 가 present A 위에 얹힐 때의 크레인 제약:
      - allow_stack=False → 어떤 overhang 스택도 불가.
      - A.entry < B.entry  (공식 stage2: 같은-시각이면 A 진입이 B에 막힘).
      - B.exit <= A.exit   (공식 stage3 + 사용자: 아래 A 를 늦게 나가게 하면 안 됨)."""
    t_exit = t_entry + P
    for A in present:
        aw = A["world"]
        for lb in wp.keys():
            for la in aw.keys():
                # 경계 접촉(area 0)도 공식 sweep 은 막으므로 intersects 로 판정
                if lb > la and wp[lb].intersects(aw[la]):
                    if not allow_stack:
                        return False
                    if A["entry"] >= t_entry:       # A 가 B보다 먼저 진입해야 (strict)
                        return False
                    if t_exit > A["exit"]:          # B 가 A보다 먼저 퇴출해야
                        return False
    return True


_CONTACT_D = int(os.environ.get("OGC_CONTACT_D", "2"))   # 접촉 인정 거리(셀). 1=면맞닿음만
_WALL_W = float(os.environ.get("OGC_WALL_W", "2.0"))     # 벽 접촉 가중치 (벽=구석 앵커 선호)


def _contact(fp, floor, row, col, D=None):
    """fp(Hb,Wb) 를 (row,col) 에 놓을 때, 블록에서 거리 D 이내의 접촉 점수.
    = WALL_W·(벽 셀) + 1·(다른블록 셀). 높을수록 snug·구석 선호·얇은 빈틈 안 남김.
    벽 가중치는 적당히 — 벽 조금 닿았다고 큰 블록접촉을 버리진 않도록."""
    if D is None:
        D = _CONTACT_D
    Hb, Wb = fp.shape
    hc, wc = floor.shape
    Hh, Ww = Hb + 2 * D, Wb + 2 * D
    r0, c0 = row - D, col - D
    sr0, sc0 = max(0, r0), max(0, c0)
    sr1, sc1 = min(hc, r0 + Hh), min(wc, c0 + Ww)
    occ = np.zeros((Hh, Ww), dtype=bool)               # 격자 안 점유 셀
    ingrid = np.zeros((Hh, Ww), dtype=bool)            # 격자 안 영역
    if sr1 > sr0 and sc1 > sc0:
        ingrid[sr0 - r0:sr1 - r0, sc0 - c0:sc1 - c0] = True
        occ[sr0 - r0:sr1 - r0, sc0 - c0:sc1 - c0] = floor[sr0:sr1, sc0:sc1]
    wall = ~ingrid                                     # 격자 밖 = 벽
    blk = np.zeros((Hh, Ww), dtype=bool)
    blk[D:D + Hb, D:D + Wb] = fp
    dil = blk.copy()                                   # D 회 4-방향 팽창
    for _ in range(D):
        d = dil.copy()
        d[1:, :] |= dil[:-1, :]
        d[:-1, :] |= dil[1:, :]
        d[:, 1:] |= dil[:, :-1]
        d[:, :-1] |= dil[:, 1:]
        dil = d
    band = dil & ~blk                                  # 블록 주변 near-zone
    return _WALL_W * int((band & wall).sum()) + int((band & occ).sum())


_CAP = None     # 후보 캡처 훅 (cand_diag 가 {"at": step} 로 설정 → ["out"] 에 기록)


def _ring0(world):
    """world dict 의 레이어0 폴리곤 exterior 좌표 (top-view 그리기용)."""
    try:
        g = world[0]
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        return [[float(x), float(y)] for x, y in g.exterior.coords]
    except Exception:
        return []


_OVERLAP_W = float(os.environ.get("OGC_OVERLAP_W", "20"))   # GOOD 인터록 보상 가중
_OVERLAP_BAD = float(os.environ.get("OGC_OVERLAP_BAD", "50"))  # BAD 인터록 페널티
_DIVERSE = os.environ.get("OGC_DIVERSE", "0") != "0"        # 후보 다양화(베이 전역 snug 자리)
_DIVERSE_LIM = int(os.environ.get("OGC_DIVERSE_LIM", "40"))
_EXIT_W = float(os.environ.get("OGC_EXIT_W", "0"))         # exit-유사 접촉 보너스 가중 (사용자 아이디어, 0=off)
_EXIT_TAU = float(os.environ.get("OGC_EXIT_TAU", "20"))    # exit 유사 판정 폭(시간단위)


def _exitmap_from_present(present, hc, wc, ml, scale):
    """셀별 free-time = 그 셀을 덮은 present 블록들의 max exit (0=free).
    → 이 셀이 언제 비는가. exit-유사 클러스터링 점수용."""
    em = np.zeros((hc, wc), dtype=np.float64)
    for p in present:
        sh, ex = p["sh"], float(p["exit"])
        for l in range(sh.n_layers):
            lm = sh.layers[l]
            r = p["y"] * scale + lm.off_cy
            c = p["x"] * scale + lm.off_cx
            mh, mw = lm.mask.shape
            r0, c0 = max(0, r), max(0, c)
            r1, c1 = min(hc, r + mh), min(wc, c + mw)
            if r1 <= r0 or c1 <= c0:
                continue
            sub = lm.mask[r0 - r:r1 - r, c0 - c:c1 - c]
            reg = em[r0:r1, c0:c1]
            reg[sub] = np.maximum(reg[sub], ex)
    return em


def _exit_affinity(fp, exitmap, row, col, exit_cand, D=None, tau=None):
    """블록 둘레 near-zone(D 팽창)의 점유셀 중, free-time 이 exit_cand 와 가까운(|Δ|<TAU)
    셀의 가중합. 높을수록 = exit 비슷한 블록 옆에 붙음 → 같이 빠져 연속공간 생성."""
    if D is None:
        D = _CONTACT_D
    if tau is None:
        tau = _EXIT_TAU
    Hb, Wb = fp.shape
    hc, wc = exitmap.shape
    Hh, Ww = Hb + 2 * D, Wb + 2 * D
    r0, c0 = row - D, col - D
    sr0, sc0 = max(0, r0), max(0, c0)
    sr1, sc1 = min(hc, r0 + Hh), min(wc, c0 + Ww)
    em = np.zeros((Hh, Ww), dtype=np.float64)
    if sr1 > sr0 and sc1 > sc0:
        em[sr0 - r0:sr1 - r0, sc0 - c0:sc1 - c0] = exitmap[sr0:sr1, sc0:sc1]
    blk = np.zeros((Hh, Ww), dtype=bool)
    blk[D:D + Hb, D:D + Wb] = fp
    dil = blk.copy()
    for _ in range(D):
        d = dil.copy()
        d[1:, :] |= dil[:-1, :]; d[:-1, :] |= dil[1:, :]
        d[:, 1:] |= dil[:, :-1]; d[:, :-1] |= dil[:, 1:]
        dil = d
    band = dil & ~blk
    occ = band & (em > 0)
    if not occ.any():
        return 0.0
    diff = np.abs(em[occ] - float(exit_cand))
    return float(np.maximum(0.0, 1.0 - diff / tau).sum())


def _overlap_value(wp, present, t, P, due):
    """후보가 기존 블록과 z축 인터록(겹침)하는 가치 (부호 있음).
    GOOD: B 가 A 시간창에 안전히 nests(A.exit≥B.exit) + B 안 tardy → 바닥 절약 보상.
    BAD : 곧 나갈 A 를 덮음(빡빡) → 페널티. score = +W·good − BAD·urgency."""
    good = 0
    bad = 0.0
    texit = t + P
    for A in present:
        aw = A["world"]
        st = False
        for lb in wp:
            for la in aw:
                if lb > la and wp[lb].intersects(aw[la]):
                    st = True
                    break
            if st:
                break
        if st:
            if A["exit"] >= texit and texit <= due:        # GOOD nest, B 안 tardy
                good += 1
            else:                                          # BAD: 임박한 A 덮음
                bad += 1.0 / max(1.0, A["exit"] - t)
    return _OVERLAP_W * good - _OVERLAP_BAD * bad


def _stack_penalty(wp, present, t):
    """후보가 기존 블록 *위에 쌓이는* 정도. 특히 일찍 나갈(긴급) 블록을 덮으면 큰 페널티
    (크레인 LIFO: 위 블록은 아래보다 먼저 나가야 함 → 시간 결합 → z1 위험)."""
    pen = 0.0
    for A in present:
        aw = A["world"]
        stacks = False
        for lb in wp:
            for la in aw:
                if lb > la and wp[lb].intersects(aw[la]):
                    stacks = True
                    break
            if stacks:
                break
        if stacks:
            pen += 1.0 + 50.0 / max(1.0, A["exit"] - t)     # A.exit 빠를수록 큰 페널티
    return pen


_FPC = {}


def _fp_union(cm):
    boff_cx, boff_cy, Hb, Wb, cmasks = cm
    k = id(cmasks)
    u = _FPC.get(k)
    if u is None:
        u = cmasks[0].copy()
        for l in range(1, len(cmasks)):
            u |= cmasks[l]
        _FPC[k] = u
    return u, boff_cx, boff_cy


def _reorder_pairs(order, pairs):
    """결합쌍의 base 를 partner 바로 앞에 오도록 재정렬 (base 먼저 배치 보장)."""
    partner_of = {v[0]: b for b, v in pairs.items()}
    out, seen = [], set()

    def emit(x):
        if x not in seen:
            out.append(x)
            seen.add(x)
    for bid in order:
        if bid in seen:
            continue
        if bid in pairs:
            emit(bid)
            emit(pairs[bid][0])
        elif bid in partner_of:
            emit(partner_of[bid])
            emit(bid)
        else:
            emit(bid)
    return out


def simulate(sub, order, allow_stack=True, fit=False, pairs=None):
    """진입순서 order 로 event-driven 배치. return (placed, Z1).
    fit=True 면 각 시각 feasible 후보 중 접촉/오버랩 점수 최대를 고른다.
    pairs={base:(partner,dx,dy,..)} 면 base 배치 직후 partner 를 오프셋에 강제 인터록."""
    W, H, ml, scale = sub["W"], sub["H"], sub["max_layer"], sub["scale"]
    hc, wc = H * scale, W * scale
    meta, shapes, cmc = sub["meta"], sub["shapes"], sub["cm"]
    raw = sub.get("raw")                       # 공식 게이트용 원본 block_data
    bay_obj = _utils.Bay(width=W, height=H) if raw else None
    if os.environ.get("OGC_STACK", "0") == "0":     # 기본=overhang 스택 금지(크레인 EXIT 위반·z1 악화 방지)
        allow_stack = False
    div = bool(fit) and _DIVERSE
    lim = _DIVERSE_LIM if div else (20 if fit else 6)
    pairs = pairs or {}
    if pairs:
        order = _reorder_pairs(order, pairs)
    placed_ids = set()

    def _place_fixed(bid, sh, px, py, t_min, placed):
        """partner 를 고정 위치(px,py)·t≥t_min 에서 가장 이른 feasible 시각에 배치 → rec|None."""
        R, P, _ = meta[bid]
        lo = max(R, t_min)
        exits = [p["exit"] for p in placed]
        ct = sorted({lo} | {e for e in exits if e > lo})
        if exits:
            ct.append(max(lo, max(exits)))
        wp = _world(sh, px, py)
        for t in sorted(set(ct)):
            present = [p for p in placed if p["entry"] <= t < p["exit"]]
            if not _crane_ok(wp, present) or not _trap_ok(wp, t, P, present, allow_stack):
                continue
            if bay_obj is not None:
                pub = [_utils.Block(p["id"], raw[p["id"]], p["x"], p["y"], p["orient"]) for p in present]
                if _utils.check_entry(bay_obj, pub, _utils.Block(bid, raw[bid], px, py, sh.orient_idx)):
                    continue
            return {"id": bid, "sh": sh, "x": px, "y": py, "orient": sh.orient_idx,
                    "entry": t, "exit": t + P, "world": wp}
        return None

    placed = []
    last_entry = 0   # 진입 시각 비감소 강제 → 순서=시간순 → present-at-t 충돌검사 정확
    for bid in order:
        if bid in placed_ids:                  # 이미 partner 로 배치됨
            continue
        R, P, D = meta[bid]
        lo = max(R, last_entry)
        exits = [p["exit"] for p in placed]
        cand_t = sorted({lo} | {e for e in exits if e > lo})
        if exits:
            cand_t.append(max(lo, max(exits)))   # 빈 베이 보장 시각 (항상 collision-free)
        cand_t = sorted(set(cand_t))
        done = False
        for t in cand_t:
            present = [p for p in placed if p["entry"] <= t < p["exit"]]
            occ = _occ_from_present(present, hc, wc, ml, scale)
            present_ub = ([_utils.Block(p["id"], raw[p["id"]], p["x"], p["y"], p["orient"])
                           for p in present] if bay_obj is not None else None)
            floor = None
            if fit:
                floor = occ[0].copy()
                for l in range(1, len(occ)):
                    floor |= occ[l]
            cands = []      # (contact, sh, x, y, wp)
            for sh in shapes[bid]:
                for (x, y) in _bl_candidates(occ, sh, cmc[id(sh)], W, H, scale, limit=lim, diverse=div):
                    wp = _world(sh, x, y)
                    if not _crane_ok(wp, present):        # 정확 크레인 진입(누수 보정)
                        continue
                    if not _trap_ok(wp, t, P, present, allow_stack):
                        continue
                    if bay_obj is not None:               # 공식 check_entry 게이트
                        nb = _utils.Block(bid, raw[bid], x, y, sh.orient_idx)
                        if _utils.check_entry(bay_obj, present_ub, nb):
                            continue
                    if not fit:
                        placed.append({"id": bid, "sh": sh, "x": x, "y": y,
                                       "orient": sh.orient_idx, "entry": t,
                                       "exit": t + P, "world": wp})
                        last_entry = t
                        done = True
                        break
                    fpm, bcx, bcy = _fp_union(cmc[id(sh)])
                    cands.append((_contact(fpm, floor, y * scale + bcy, x * scale + bcx),
                                  sh, x, y, wp))
                if done:
                    break
            if fit and cands:
                ovs = ([_overlap_value(c[4], present, t, P, D) for c in cands]
                       if fit == "ov" else None)
                if fit == "ov":         # 접촉 + 오버랩(인터록 가치): GOOD nest 보상 / BAD 페널티
                    bi = max(range(len(cands)), key=lambda i: cands[i][0] + ovs[i])
                    _, sh, x, y, wp = cands[bi]
                elif fit == "tardy":    # 접촉 top-K 중 쌓기 페널티 최소 (먼저 나갈 애 안 덮기)
                    top = sorted(cands, key=lambda c: -c[0])[:3]
                    _, sh, x, y, wp = min(top, key=lambda c: _stack_penalty(c[4], present, t))
                else:                   # 접촉 최대 (best-fit)
                    _, sh, x, y, wp = max(cands, key=lambda c: c[0])
                if _CAP is not None and "counts" in _CAP:
                    _CAP["counts"].append(len(cands))
                need_ov = _CAP.get("need_ov", False) if _CAP is not None else False
                cap_ok = (not need_ov) or (ovs is not None and any(v > 0 for v in ovs))
                if (_CAP is not None and "out" not in _CAP and cap_ok
                        and len(cands) >= _CAP.get("min_cands", 10 ** 9)
                        and len(present) >= _CAP.get("min_present", 0)):
                    _CAP["out"] = {
                        "W": W, "H": H, "bid": bid, "t": t, "picked": (x, y),
                        "present": [{"ring": _ring0(p["world"]), "exit": p["exit"]} for p in present],
                        "cands": [{"x": cx, "y": cy, "o": csh.orient_idx, "contact": ct,
                                   "ov": (round(ovs[k], 1) if ovs is not None else 0.0),
                                   "ring": _ring0(cwp)}
                                  for k, (ct, csh, cx, cy, cwp) in enumerate(cands)],
                    }
                placed.append({"id": bid, "sh": sh, "x": x, "y": y,
                               "orient": sh.orient_idx, "entry": t,
                               "exit": t + P, "world": wp})
                last_entry = t
                done = True
            if done:
                break
        if not done:
            # 최후의 보루: 빈 베이에 *모든 방향* 시도해 맞는 것 배치
            t = max(R, max(exits)) if exits else R
            empty = [np.zeros((hc, wc), dtype=bool) for _ in range(ml)]
            chosen = None
            for sh in shapes[bid]:
                cnd = _bl_candidates(empty, sh, cmc[id(sh)], W, H, scale)
                if cnd:
                    chosen = (sh, cnd[0][0], cnd[0][1])
                    break
            if chosen is None:   # 블록이 베이보다 큼(배정 오류) → 최소 orient 클램프(방어)
                sh = min(shapes[bid], key=lambda s: s.bbox_w * s.bbox_h)
                chosen = (sh, max(0, int(np.ceil(-sh.min_x))), max(0, int(np.ceil(-sh.min_y))))
            sh, x, y = chosen
            placed.append({"id": bid, "sh": sh, "x": x, "y": y,
                           "orient": sh.orient_idx, "entry": t,
                           "exit": t + P, "world": _world(sh, x, y)})
            last_entry = t
        placed_ids.add(bid)
        # 결합쌍: base 배치 직후 partner 를 오프셋에 강제 인터록 (orient0 기준이라 base orient0 일 때만)
        if pairs and bid in pairs and placed and placed[-1]["id"] == bid and placed[-1]["orient"] == 0:
            partner, dx, dy = pairs[bid][0], pairs[bid][1], pairs[bid][2]
            if partner not in placed_ids and partner in shapes:
                base = placed[-1]
                prec = _place_fixed(partner, shapes[partner][0], base["x"] + dx,
                                    base["y"] + dy, base["entry"], placed)
                if prec is not None:
                    placed.append(prec)
                    last_entry = prec["entry"]
                    placed_ids.add(partner)
    z1 = sum(max(0, p["exit"] - meta[p["id"]][2]) for p in placed)
    return placed, z1


def place_one(bid, W, H, ml, scale, placed, last_entry, shapes_i, cm_fn,
              meta_i, raw_map, bay_obj, fit=False, allow_stack=True, div=None, lim=None):
    """단일 블록 bid 를 베이 현재상태(placed)에 simulate 와 동일 품질로 *증분* 배치 → rec | None.

    전역 Pass B (unified_greedy OGC_GLOBAL) 용: 한 블록을 모든 후보 베이에 이걸 돌려보고
    marginal obj 최소 위치를 고른다. 로직 = simulate per-block body 그대로
    (가장 이른 feasible t + diverse 후보 + fit 채점 + 정확 crane/trap + 공식 check_entry).
    rec = {id,sh,x,y,orient,entry,exit,world} (= simulate placed rec 와 동형). 블록>베이면 None.
    raw_map[bid] = 공식 게이트용 원본 block_data (전역 id 인덱싱). bay_obj=utils.Bay(W,H)|None.
    div/lim 오버라이드: 데드라인 임박 시 div=False·lim 작게 주면 BL-only(후보생성 빠름)."""
    if os.environ.get("OGC_STACK", "0") == "0":
        allow_stack = False
    if div is None:
        div = bool(fit) and _DIVERSE
    if lim is None:
        lim = _DIVERSE_LIM if div else (20 if fit else 6)
    exit_w = float(os.environ.get("OGC_EXIT_W", "0"))       # 런타임 읽기(스윕 가능)
    exit_tau = float(os.environ.get("OGC_EXIT_TAU", "20"))
    R, P, Dd = meta_i
    hc, wc = H * scale, W * scale
    lo = max(R, last_entry)
    exits = [p["exit"] for p in placed]
    cand_t = sorted({lo} | {e for e in exits if e > lo})
    if exits:
        cand_t.append(max(lo, max(exits)))         # 빈 베이 보장 시각 (항상 collision-free)
    cand_t = sorted(set(cand_t))
    for t in cand_t:
        present = [p for p in placed if p["entry"] <= t < p["exit"]]
        occ = _occ_from_present(present, hc, wc, ml, scale)
        present_ub = ([_utils.Block(p["id"], raw_map[p["id"]], p["x"], p["y"], p["orient"])
                       for p in present] if bay_obj is not None else None)
        floor = None
        if fit:
            floor = occ[0].copy()
            for l in range(1, len(occ)):
                floor |= occ[l]
        exitmap = _exitmap_from_present(present, hc, wc, ml, scale) if (fit and exit_w) else None

        def _valid(sh, x, y):
            """shapely 정확검증 (crane+trap+공식 check_entry) → wp | None. 비싼 부분."""
            wp = _world(sh, x, y)
            if not _crane_ok(wp, present):
                return None
            if not _trap_ok(wp, t, P, present, allow_stack):
                return None
            if bay_obj is not None and _utils.check_entry(
                    bay_obj, present_ub, _utils.Block(bid, raw_map[bid], x, y, sh.orient_idx)):
                return None
            return wp

        eager = fit in ("ov", "tardy")     # 점수 자체가 shapely(present 교차) 필요 → 후보별 즉시검증
        cands = []      # eager: (contact, sh, x, y, wp) / contact: (contact, sh, x, y)
        for sh in shapes_i:
            cm = cm_fn(sh)
            fpm = bcx = bcy = None
            for (x, y) in _bl_candidates(occ, sh, cm, W, H, scale, limit=lim, diverse=div):
                if not fit:                 # first-feasible: 즉시 검증·첫 valid 반환
                    wp = _valid(sh, x, y)
                    if wp is not None:
                        return {"id": bid, "sh": sh, "x": x, "y": y, "orient": sh.orient_idx,
                                "entry": t, "exit": t + P, "world": wp}
                    continue
                if eager:
                    wp = _valid(sh, x, y)
                    if wp is None:
                        continue
                if fpm is None:
                    fpm, bcx, bcy = _fp_union(cm)
                ct = _contact(fpm, floor, y * scale + bcy, x * scale + bcx)
                if exitmap is not None:     # exit-유사 클러스터 보너스 (사용자 아이디어)
                    ct += exit_w * _exit_affinity(fpm, exitmap, y * scale + bcy,
                                                  x * scale + bcx, t + P, tau=exit_tau)
                cands.append((ct, sh, x, y, wp) if eager else (ct, sh, x, y))
        if eager and cands:                 # ov/tardy: 검증된 후보 중 점수 선택
            if fit == "ov":
                ovs = [_overlap_value(c[4], present, t, P, Dd) for c in cands]
                bi = max(range(len(cands)), key=lambda i: cands[i][0] + ovs[i])
                _, sh, x, y, wp = cands[bi]
            else:                           # tardy
                top = sorted(cands, key=lambda c: -c[0])[:3]
                _, sh, x, y, wp = min(top, key=lambda c: _stack_penalty(c[4], present, t))
            return {"id": bid, "sh": sh, "x": x, "y": y, "orient": sh.orient_idx,
                    "entry": t, "exit": t + P, "world": wp}
        if fit and cands:                   # contact-max: 점수순 정렬 후 첫 valid (shapely ~70×↓)
            cands.sort(key=lambda c: -c[0])
            for (_ct, sh, x, y) in cands:
                wp = _valid(sh, x, y)
                if wp is not None:
                    return {"id": bid, "sh": sh, "x": x, "y": y, "orient": sh.orient_idx,
                            "entry": t, "exit": t + P, "world": wp}
    # 최후의 보루: 빈 베이 시각에 강제 배치 (fitting bay 면 항상 feasible)
    t = max(R, max(exits)) if exits else R
    empty = [np.zeros((hc, wc), dtype=bool) for _ in range(ml)]
    for sh in shapes_i:
        cnd = _bl_candidates(empty, sh, cm_fn(sh), W, H, scale)
        if cnd:
            x, y = cnd[0]
            return {"id": bid, "sh": sh, "x": x, "y": y, "orient": sh.orient_idx,
                    "entry": t, "exit": t + P, "world": _world(sh, x, y)}
    return None


# --------------------------------------------------------------------------
def seed_order(sub, key):
    meta, shapes, subset = sub["meta"], sub["shapes"], sub["subset"]
    if key == "edd":
        return sorted(subset, key=lambda i: meta[i][2])            # due asc
    if key == "area":
        return sorted(subset, key=lambda i: -shapes[i][0].footprint_area)
    if key == "height":
        return sorted(subset, key=lambda i: -shapes[i][0].bbox_h)
    if key == "release":
        return sorted(subset, key=lambda i: meta[i][0])
    return list(subset)


def descent(sub, seed, allow_stack, budget, rng_seed):
    """seed 순서에서 페어 스왑 국소탐색으로 Z1 최소화."""
    rng = random.Random(rng_seed)
    order = list(seed)
    _, best = simulate(sub, order, allow_stack)
    n = len(order)
    tried = 0
    while tried < budget:
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j:
            continue
        order[i], order[j] = order[j], order[i]
        _, z = simulate(sub, order, allow_stack)
        tried += 1
        if z < best:
            best = z
        else:
            order[i], order[j] = order[j], order[i]   # 되돌림
    placed, z = simulate(sub, order, allow_stack)
    return {"order": order, "z1": z, "placed": placed}


def descent_tardy(sub, seed, allow_stack, deadline, fit=False):
    """타깃 스왑: tardy 블록을 순서상 *앞으로* 당겨 z1 국소최소화 (deadline 까지).
    랜덤 descent 보다 적은 simulate 로 같은 효과 (막히는 애만 건드림)."""
    meta = sub["meta"]
    order = list(seed)
    placed, best = simulate(sub, order, allow_stack, fit=fit)
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        # tardiness 큰 순으로 정렬된 tardy 블록
        tardy = sorted((p["id"] for p in placed if p["exit"] > meta[p["id"]][2]),
                       key=lambda b: -(next(q["exit"] for q in placed if q["id"] == b) - meta[b][2]))
        pos = {b: k for k, b in enumerate(order)}
        for bid in tardy:
            if time.monotonic() >= deadline:
                break
            k = pos[bid]
            for nk in (max(0, k - 1), max(0, k - 4), max(0, k - 12), 0):
                if nk >= k:
                    continue
                cand = order[:nk] + [bid] + order[nk:k] + order[k + 1:]
                _, z = simulate(sub, cand, allow_stack, fit=fit)
                if z < best - 1e-9:
                    best = z
                    order = cand
                    improved = True
                    placed, _ = simulate(sub, order, allow_stack, fit=fit)
                    pos = {b: kk for kk, b in enumerate(order)}
                    break
    placed, z = simulate(sub, order, allow_stack, fit=fit)
    return {"order": order, "z1": z, "placed": placed}


def _worker(cfg):
    sub = build_subset(cfg["inst"], cfg["bay"], cfg["scale"])
    seed = seed_order(sub, cfg["seed_key"])
    r = descent(sub, seed, cfg["allow_stack"], cfg["budget"], cfg["rng"])
    r["seed_key"] = cfg["seed_key"]
    r["bay"] = sub["bay_id"]
    return {k: r[k] for k in ("seed_key", "z1", "order", "bay")} | {
        "placed": [(p["id"], p["x"], p["y"], p["orient"], p["entry"], p["exit"])
                   for p in r["placed"]]}


def search(inst, bay, scale, seeds, allow_stack, budget, workers=4):
    from concurrent.futures import ProcessPoolExecutor
    cfgs = [{"inst": inst, "bay": bay, "scale": scale, "seed_key": s,
             "allow_stack": allow_stack, "budget": budget, "rng": 1000 + k}
            for k, s in enumerate(seeds)]
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_worker, cfgs))
    except Exception as e:
        print(f"[search] 병렬 실패({e})→순차", file=sys.stderr)
        results = [_worker(c) for c in cfgs]
    best = min(results, key=lambda r: r["z1"])
    return best, results


__all__ = ["build_subset", "simulate", "place_one", "seed_order", "descent", "search"]
