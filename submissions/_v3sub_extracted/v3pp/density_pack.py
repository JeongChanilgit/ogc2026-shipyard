"""
density_pack.py — "겹침 최대화" 배치 + numpy 벡터화 + 4코어 포트폴리오.

blf.py 의 bottom-left 는 겹침을 *허용*만 했지 *최대화*하진 않았다 (그래서 prob_29
bay0 에서 21/116 에 그침). 여기선 배치 목적함수를 바꾼다:

  scorer='overlap' : 후보 위치를 *기존 블록 bbox 와의 겹침 면적 최대*로 고른다
                     → 이웃 오목부/overhang 에 제일 깊게 파고듦 (= 사용자 "최대한 겹치게").
  scorer='bl'      : bottom-left (비교 기준).

속도:
  - 후보 feasibility 를 (block,orient) 마다 numpy sliding_window_view 상관연산으로 일괄
    계산 (Python y-루프 제거). 점수도 bbox-density 윈도우 합으로 벡터화.
  - 비트맵은 *빠른 사전필터*; 최종 커밋 직전 shapely 정확검증 (격자 누수 제거).
  - 포트폴리오: scorer×순서 여러 구성을 ProcessPoolExecutor(4코어) 로 병렬 → best-of.

검증의 진실은 ../src/utils.py. 이 모듈은 밀도 천장 추격용 패커.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _swv

THIS = os.path.dirname(os.path.abspath(__file__))
# v3pp package: cross-imports are package-relative; do NOT pollute sys.path.
from .gridmap import build_shape  # noqa: E402

try:
    from shapely.affinity import translate as _translate
except Exception:
    _translate = None

TOPK = 24            # orient 당 점수 상위 후보 보관 (exact-verify fallback 용)


# --------------------------------------------------------------------------
def _common_masks(shape, scale):
    """블록 전 레이어를 공통 bbox 프레임으로 정렬한 마스크 + 격자 오프셋."""
    boff_cx = int(np.floor(shape.min_x * scale))
    boff_cy = int(np.floor(shape.min_y * scale))
    end_cx = int(np.ceil(shape.max_x * scale))
    end_cy = int(np.ceil(shape.max_y * scale))
    Wb = max(1, end_cx - boff_cx)
    Hb = max(1, end_cy - boff_cy)
    cmasks = []
    for lm in shape.layers:
        m = np.zeros((Hb, Wb), dtype=bool)
        r0 = lm.off_cy - boff_cy
        c0 = lm.off_cx - boff_cx
        m[r0:r0 + lm.mask.shape[0], c0:c0 + lm.mask.shape[1]] = lm.mask
        cmasks.append(m)
    return boff_cx, boff_cy, Hb, Wb, cmasks


def _exact_ok(wp, placed_polys):
    """shapely 같은-층 무겹침 (변/꼭짓점 공유 허용)."""
    for ep in placed_polys:
        for l in wp.keys() & ep.keys():
            if wp[l].intersection(ep[l]).area > 1e-7:
                return False
    return True


def _greedy(W, H, max_layer, shapes_by_block, order, scorer, scale):
    """겹침-최대화(또는 BL) 그리디. return (placements, count, util)."""
    hc, wc = H * scale, W * scale
    occ = [np.zeros((hc, wc), dtype=bool) for _ in range(max_layer)]
    # per-layer bbox 누적 밀도: 'overlap'=layer0만(수평 오목부), 'vol'=전 레이어(z 채움)
    bden = [np.zeros((hc, wc), dtype=np.int32) for _ in range(max_layer)]
    placed_polys = []
    placements = []
    cm_cache = {}

    for bid in order:
        cands = []   # (score, x, y, sh)
        for sh in shapes_by_block[bid]:
            key = id(sh)
            if key not in cm_cache:
                cm_cache[key] = _common_masks(sh, scale)
            boff_cx, boff_cy, Hb, Wb, cmasks = cm_cache[key]
            if Hb > hc or Wb > wc:
                continue
            # --- 벡터화 feasibility: 레이어별 상관연산 AND ---
            feas = np.ones((hc - Hb + 1, wc - Wb + 1), dtype=bool)
            for l in range(sh.n_layers):
                win = _swv(occ[l], (Hb, Wb))           # (ny,nx,Hb,Wb) view
                ov = np.logical_and(win, cmasks[l]).sum(axis=(2, 3))
                feas &= (ov == 0)
            # --- 정수 앵커(strided) 위치 ---
            xs = np.arange(int(np.ceil(-sh.min_x - 1e-9)),
                           int(np.floor(W - sh.max_x + 1e-9)) + 1)
            ys = np.arange(int(np.ceil(-sh.min_y - 1e-9)),
                           int(np.floor(H - sh.max_y + 1e-9)) + 1)
            if xs.size == 0 or ys.size == 0:
                continue
            cols = xs * scale + boff_cx
            rows = ys * scale + boff_cy
            cmask = (cols >= 0) & (cols <= wc - Wb)
            rmask = (rows >= 0) & (rows <= hc - Hb)
            xs, cols = xs[cmask], cols[cmask]
            ys, rows = ys[rmask], rows[rmask]
            if xs.size == 0 or ys.size == 0:
                continue
            sub = feas[np.ix_(rows, cols)]             # (ny,nx) feasible
            if not sub.any():
                continue
            # --- 점수 ---
            if scorer in ("overlap", "vol"):
                # overlap=layer0 bbox 겹침(수평), vol=블록 점유 전 레이어 bbox 겹침(z 포함)
                layers_sum = [0] if scorer == "overlap" else list(range(sh.n_layers))
                sc_full = np.zeros((hc - Hb + 1, wc - Wb + 1), dtype=np.int64)
                for l in layers_sum:
                    sc_full += _swv(bden[l], (Hb, Wb)).sum(axis=(2, 3)).astype(np.int64)
                sc = sc_full[np.ix_(rows, cols)]
            else:  # 'bl' : y 작고 x 작을수록 좋음
                sc = -(ys[:, None].astype(np.int64) * 1000000 + xs[None, :])
            sc = np.where(sub, sc, np.iinfo(np.int64).min)
            # 상위 TOPK 추출
            flat = sc.ravel()
            ny, nx = sc.shape
            k = min(TOPK, flat.size)
            top = np.argpartition(flat, -k)[-k:]
            for idx in top:
                v = flat[idx]
                if v == np.iinfo(np.int64).min:
                    continue
                ri, ci = divmod(int(idx), nx)
                cands.append((int(v), int(xs[ci]), int(ys[ri]), sh))
        if not cands:
            continue
        # 점수 desc → shapely 정확검증 첫 통과를 커밋
        cands.sort(key=lambda c: -c[0])
        committed = None
        for (_s, x, y, sh) in cands:
            wp = {l: _translate(sh.layers[l].poly, xoff=x, yoff=y)
                  for l in range(sh.n_layers)}
            if _exact_ok(wp, placed_polys):
                committed = (x, y, sh, wp)
                break
        if committed is None:
            continue
        x, y, sh, wp = committed
        for l in range(sh.n_layers):
            lm = sh.layers[l]
            r = y * scale + lm.off_cy
            c = x * scale + lm.off_cx
            occ[l][r:r + lm.mask.shape[0], c:c + lm.mask.shape[1]] |= lm.mask
        boff_cx, boff_cy, Hb, Wb, _ = cm_cache[id(sh)]
        rr = y * scale + boff_cy
        cc = x * scale + boff_cx
        for l in range(sh.n_layers):
            bden[l][rr:rr + Hb, cc:cc + Wb] += 1
        placed_polys.append(wp)
        placements.append((bid, x, y, sh.orient_idx))

    # 면적활용(layer0) + 부피활용(전 레이어 / W*H*max_layer)
    tot_floor = tot_vol = 0.0
    for bid, x, y, oi in placements:
        sh = next(s for s in shapes_by_block[bid] if s.orient_idx == oi)
        tot_floor += sh.footprint_area
        tot_vol += sh.volume
    floor_util = tot_floor / float(W * H)
    vol_util = tot_vol / float(W * H * max_layer)
    return placements, len(placements), floor_util, vol_util


# --------------------------------------------------------------------------
def _argmax(xs):
    return max(range(len(xs)), key=lambda i: xs[i])


def _load_subset(inst_path, bay_id):
    data = json.load(open(inst_path, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    n, m = len(blocks), len(bays)
    pref = [_argmax(b["bay_preferences"]) for b in blocks]
    if bay_id is None:
        counts = [pref.count(j) for j in range(m)]
        bay_id = _argmax(counts)
    subset = [i for i in range(n) if pref[i] == bay_id]
    return data, bays, blocks, bay_id, subset


def _order(blocks, subset, shapes_by_block, key):
    if key == "area":
        return sorted(subset, key=lambda i: -shapes_by_block[i][0].footprint_area)
    if key == "due":
        return sorted(subset, key=lambda i: blocks[i].get("due_date", 0))
    if key == "height":
        return sorted(subset, key=lambda i: -shapes_by_block[i][0].bbox_h)
    if key == "width":
        return sorted(subset, key=lambda i: -shapes_by_block[i][0].bbox_w)
    return list(subset)


def pack_run(inst_path, bay_id, scale, scorer, order_key):
    """단일 구성 실행 (worker 진입점). return dict."""
    t0 = time.time()
    data, bays, blocks, bay_id, subset = _load_subset(inst_path, bay_id)
    W, H = bays[bay_id]["width"], bays[bay_id]["height"]
    shapes_by_block = {}
    max_layer = 1
    for i in subset:
        shs = [build_shape(i, blocks[i], o, scale=scale)
               for o in range(len(blocks[i]["shape"]))]
        shapes_by_block[i] = shs
        max_layer = max(max_layer, max(s.n_layers for s in shs))
    order = _order(blocks, subset, shapes_by_block, order_key)
    placements, count, floor_util, vol_util = _greedy(
        W, H, max_layer, shapes_by_block, order, scorer, scale)
    return {
        "scorer": scorer, "order": order_key, "bay": bay_id,
        "W": W, "H": H, "max_layer": max_layer,
        "count": count, "subset": len(subset),
        "util": floor_util, "vol_util": vol_util,
        "time": time.time() - t0, "placements": placements,
    }


def _worker(cfg):
    return pack_run(**cfg)


def pack_portfolio(inst_path, bay_id, scale, configs, workers=4):
    """configs = [{scorer,order_key}, ...] → 4코어 병렬, best-of (count, util)."""
    from concurrent.futures import ProcessPoolExecutor
    full = [{"inst_path": inst_path, "bay_id": bay_id, "scale": scale, **c}
            for c in configs]
    results = []
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_worker, full))
    except Exception as e:
        # 병렬 실패 시 순차 폴백
        print(f"[portfolio] 병렬 실패 ({e}) → 순차", file=sys.stderr)
        results = [_worker(c) for c in full]
    best = max(results, key=lambda r: (r["vol_util"], r["count"]))
    return best, results


__all__ = ["pack_run", "pack_portfolio", "_greedy"]
