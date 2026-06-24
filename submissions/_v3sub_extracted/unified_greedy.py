"""
unified_greedy.py — H3: 배정 단계 없는 통합 전역 그리디 패킹 (사용자 본래 비전).

베이를 미리 배정하지 않는다. 각 블록(EDD순)을 *모든 베이*에 시도해, 그 베이의 현재
패킹 상태에서 가장 이른 feasible 위치(v2 폴리곤+크레인+시간재사용)에 놓았을 때의
marginal obj = w1·tardy + w2·Δz2 + w3·Δz3 를 계산 → 전역 최소 위치에 배치.
배정은 패킹 결정에서 emergent. → 배정 선결정의 z1 오추정 없음 + 다른 베이 빈 공간 활용.
그 위에 CP-SAT 타이밍 오라클로 z1 최적. 원래 솔버와 동일 인스턴스 비교.

실행: <env-python> unified_greedy.py 200 prob_38 prob_37 prob_25 prob_40
"""
from __future__ import annotations

import os

os.environ.setdefault("OGC_HYBRID_RESERVE_S", "1")

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import utils  # noqa: E402
from utils import Bay, check_feasibility  # noqa: E402
from solver_orig import _cpsat_bay_timing_verified, algorithm as orig_alg  # noqa: E402
from gridmap import build_shape  # noqa: E402
from density_pack import _common_masks  # noqa: E402
import temporal_pack as _tp  # noqa: E402  (인스턴스 간 id-캐시 초기화용)
from temporal_pack import (_bl_candidates, _crane_ok, _trap_ok,  # noqa: E402
                           _occ_from_present, _world, simulate, place_one,
                           seed_order, descent, descent_tardy)
from assign_search import build_set, _z1_job, z2 as _z2f, z3 as _z3f  # noqa: E402
from ptiming import parallel_timing  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
SCALE = 2
_CM = {}
_CUSTOM_ORDER = None     # OGC_ORDER=custom 일 때 외부가 주입하는 명시 순서 (2-pass tardy-reorder 실험용)
STAGES = []     # OGC_STAGES 면 단계별 (name, t, z1/z2/z3) 기록 (리포트용)


def _cm(sh):
    if id(sh) not in _CM:
        _CM[id(sh)] = _common_masks(sh, SCALE)
    return _CM[id(sh)]


_FITV = os.environ.get("OGC_FIT", "0")              # 0=off|1=접촉max|tardy=top-K접촉+쌓기최소|ov=접촉+오버랩
_FIT = _FITV if _FITV in ("tardy", "ov") else (_FITV != "0")
_TOSS = os.environ.get("OGC_TOSS", "0") != "0"      # 베이 간 토스 (측정오염 의심 → 기본 OFF)


def try_place_bay(W, H, ml, placed, last_entry, sh_list, R, P, allow_stack=True):
    """베이 현재 상태(placed)에서 가장 이른 feasible 위치(first-BL) → rec | None.
    그리디 배정 추정용 (최종 위치는 simulate 재패킹이 결정 → fit 은 거기서)."""
    hc, wc = H * SCALE, W * SCALE
    lo = max(R, last_entry)
    exits = [p["exit"] for p in placed]
    cand_t = sorted({lo} | {e for e in exits if e > lo})
    if exits:
        cand_t.append(max(lo, max(exits)))
    cand_t = sorted(set(cand_t))
    for t in cand_t:
        present = [p for p in placed if p["entry"] <= t < p["exit"]]
        occ = _occ_from_present(present, hc, wc, ml, SCALE)
        for sh in sh_list:
            for (x, y) in _bl_candidates(occ, sh, _cm(sh), W, H, SCALE):
                wp = _world(sh, x, y)
                if not _crane_ok(wp, present):
                    continue
                if not _trap_ok(wp, t, P, present, allow_stack):
                    continue
                return {"sh": sh, "x": x, "y": y, "entry": t, "exit": t + P, "world": wp}
    return None


def unified(data, tl, inst):
    _CM.clear()          # id(sh) 키 캐시 — 인스턴스마다 초기화 (id 재사용 → stale mask 크래시 방지)
    _tp._FPC.clear()     # id(cmasks) 키 캐시도 초기화 (멀티-인스턴스/평가서버 안전)
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    m, N = len(bays), len(blocks)
    dims = [(b["width"], b["height"]) for b in bays]
    area = [W * H for (W, H) in dims]
    u = [(sum(area) / m) / a for a in area]
    t0 = time.time()
    _rec = os.environ.get("OGC_STAGES")
    if _rec:
        STAGES.clear()
    _tprev = [t0]

    def st(name, **kw):
        if _rec:
            now = time.time()
            STAGES.append({"name": name, "t": round(now - t0, 1),
                           "dt": round(now - _tprev[0], 1), **kw})
            _tprev[0] = now

    def _obb(blk, o):
        xs = [p[0] for ly in blk["shape"][o]["layers"] for p in ly]
        ys = [p[1] for ly in blk["shape"][o]["layers"] for p in ly]
        return max(xs) - min(xs), max(ys) - min(ys)

    shapes, fit = {}, []
    ml = 1
    for i in range(N):
        shs = [build_shape(i, blocks[i], o, SCALE) for o in range(len(blocks[i]["shape"]))]
        shapes[i] = shs
        ml = max(ml, max(s.n_layers for s in shs))
        bbs = [_obb(blocks[i], o) for o in range(len(blocks[i]["shape"]))]
        fit.append([j for j in range(m)
                    if any(bw <= dims[j][0] + 1e-6 and bh <= dims[j][1] + 1e-6 for bw, bh in bbs)]
                   or list(range(m)))

    state = {j: {"placed": [], "last_entry": 0} for j in range(m)}
    load = [0.0] * m

    def z2_of(loads):
        wl = [u[j] * loads[j] for j in range(m)]
        return max(wl) - min(wl)

    def place(j, i, R, P):
        return try_place_bay(dims[j][0], dims[j][1], ml, state[j]["placed"],
                             state[j]["last_entry"], shapes[i], R, P)

    def commit(i, j, pl, wk):
        rec = {"id": i, "sh": pl["sh"], "x": pl["x"], "y": pl["y"],
               "orient": pl["sh"].orient_idx, "entry": pl["entry"],
               "exit": pl["exit"], "world": pl["world"]}
        state[j]["placed"].append(rec)
        state[j]["last_entry"] = pl["entry"]
        load[j] += wk

    _ord = os.environ.get("OGC_ORDER", "blend")   # 채택: R+0.5P 블렌드 — set2 181.43M (+9.2% vs EDD)
    if _ord == "custom" and _CUSTOM_ORDER is not None:   # 외부 주입 순서 (2-pass 실험)
        order = [i for i in _CUSTOM_ORDER if 0 <= i < N]
    elif _ord == "slack":      # 최소여유(critical) 우선: due - release - proc
        order = sorted(range(N), key=lambda i: (blocks[i]["due_date"]
                       - blocks[i].get("release_time", 0) - blocks[i]["processing_time"]))
    elif _ord == "area":       # 큰 블록 먼저(공간 선점) → due tiebreak
        order = sorted(range(N), key=lambda i: (-shapes[i][0].footprint_area, blocks[i]["due_date"]))
    elif _ord == "release":    # release 순
        order = sorted(range(N), key=lambda i: (blocks[i].get("release_time", 0), blocks[i]["due_date"]))
    elif _ord == "areaXdue":   # 큰·급한 우선: area / slack
        order = sorted(range(N), key=lambda i: -(shapes[i][0].footprint_area)
                       / max(1, blocks[i]["due_date"] - blocks[i].get("release_time", 0)))
    elif _ord == "exitearly":  # 가장 빨리 나갈 수 있는 순 (R+P 오름차순) = EXIT 임박
        order = sorted(range(N), key=lambda i: (blocks[i].get("release_time", 0)
                       + blocks[i]["processing_time"], blocks[i]["due_date"]))
    elif _ord == "blend":      # R + α·P 블렌드 (release=α0, exitearly=α1). 채택 α=0.5
        _a = float(os.environ.get("OGC_ORDER_ALPHA", "0.5"))
        order = sorted(range(N), key=lambda i: (blocks[i].get("release_time", 0)
                       + _a * blocks[i]["processing_time"], blocks[i]["due_date"]))
    elif _ord == "blendsize":  # 사용자: 혼잡할 때만 큰 블록 나중 (congestion-gated γ)
        _a = float(os.environ.get("OGC_ORDER_ALPHA", "0.5"))
        _g = float(os.environ.get("OGC_ORDER_GAMMA", "0.1"))
        _thr = float(os.environ.get("OGC_CONG_THRESH", "1.0"))
        _mk = max((blocks[i]["due_date"] for i in range(N)), default=1) or 1
        _dem = sum(shapes[i][0].footprint_area * blocks[i].get("processing_time", 0) for i in range(N))
        _cong = _dem / max(1.0, sum(area) * _mk)
        _ge = _g if _cong > _thr else 0.0      # 혼잡(cong>thr)일 때만 큰-블록-나중 발동
        print(f"[DBG] blendsize cong={_cong:.2f} ge={_ge:.3f}", file=sys.stderr, flush=True)
        order = sorted(range(N), key=lambda i: (blocks[i].get("release_time", 0)
                       + _a * blocks[i]["processing_time"] + _ge * shapes[i][0].footprint_area))
    elif _ord == "areasmall":  # 작은 블록 먼저 (사용자 아이디어 순수형, large-last)
        order = sorted(range(N), key=lambda i: (shapes[i][0].footprint_area, blocks[i]["due_date"]))
    elif _ord == "exitdue":    # = EDD(due) 와 동일, 명시용
        order = sorted(range(N), key=lambda i: blocks[i]["due_date"])
    else:                      # edd (기본) = due(EXIT 데드라인) 순
        order = sorted(range(N), key=lambda i: blocks[i]["due_date"])

    # ---- CP-SAT 가이드라인 (z2·z3 전역최소) + z1-오버플로 + 재계획 ----
    USE_GUIDE = os.environ.get("OGC_GUIDE", "1") != "0"
    REPLAN_EVERY = int(os.environ.get("OGC_GUIDE_REPLAN", "5"))
    MAX_REPLAN = int(os.environ.get("OGC_GUIDE_MAXREPLAN", "8"))   # 재계획 폭주 캡(prob_40형)
    replan_ct = 0
    GLOBAL = os.environ.get("OGC_GLOBAL", "0") != "0"   # Pass B 전역 품질배치 (배정 emergent)
    bay_objs = {j: utils.Bay(width=dims[j][0], height=dims[j][1]) for j in range(m)} if GLOBAL else None
    # 배치 데드라인: 초과 시 남은 블록 BL-only 강등 → CP-SAT 타이밍 예산 확보 + TL 보장
    place_deadline = t0 + tl * float(os.environ.get("OGC_PLACE_FRAC", "0.72"))
    # E1: anticipatory 공존 페널티 — 이 베이에 시간창 겹치는 기존 블록 많으면 페널티(z1 proxy)
    CP_W = float(os.environ.get("OGC_COPRESENCE", "0"))
    # exit-group 배정(사용자 아이디어 bay-level): 같은-exit(±TAU) 블록 많은 베이 선호 → 그룹 함께 빠져 베이 회전
    EG_W = float(os.environ.get("OGC_EXITGROUP", "0"))
    EG_TAU = float(os.environ.get("OGC_EXITGROUP_TAU", "20"))
    guide, fixed, ovf_ct = None, {}, 0
    if USE_GUIDE:
        from cpsat_guideline import cpsat_guideline
        guide = cpsat_guideline(data, time_s=min(10.0, max(3.0, tl * 0.08)), fit=fit)
        print(f"[DBG] USE_GUIDE=1 guide dist={[guide.count(j) for j in range(m)]}", file=sys.stderr, flush=True)
        st("CP-SAT 가이드라인(z2·z3 배정)", z2=round(_z2f(guide, blocks, u, m)),
           z3=_z3f(guide, blocks), dist=[guide.count(j) for j in range(m)])

    for i in order:
        R = blocks[i].get("release_time", 0)
        D = blocks[i]["due_date"]
        P = blocks[i]["processing_time"]
        pr = blocks[i]["bay_preferences"]
        smax = max(pr)
        wk = blocks[i].get("workload", 0)

        # ---- 전역 Pass B: 모든 베이에 *품질* 배치해보고 marginal 최소 선택 (배정 emergent) ----
        if GLOBAL:
            g = guide[i] if (guide is not None and guide[i] in fit[i]) else fit[i][0]
            fast = time.time() > place_deadline      # 예산 초과 → BL-only(후보생성 빠름)로 강등
            best = None      # (score, j, rec)  rec = 그 베이에 놓은 실제 품질 위치
            for j in fit[i]:
                rec = place_one(i, dims[j][0], dims[j][1], ml, SCALE,
                                state[j]["placed"], state[j]["last_entry"],
                                shapes[i], _cm, (R, P, D), blocks, bay_objs[j], _FIT, True,
                                div=(False if fast else None), lim=(6 if fast else None))
                if rec is None:
                    continue
                tardy = max(0, rec["exit"] - D)
                nl = load[:]
                nl[j] += wk
                sc = w1 * tardy + w2 * (z2_of(nl) - z2_of(load)) + w3 * (smax - pr[j])
                if CP_W:        # 시간창 [entry,exit) 겹치는 기존 블록 수 × w1 proxy
                    e0, e1 = rec["entry"], rec["exit"]
                    cp = sum(1 for p in state[j]["placed"] if p["entry"] < e1 and e0 < p["exit"])
                    sc += CP_W * w1 * cp
                if EG_W:        # 같은-exit(±TAU) 블록 많은 베이 보상 → 그룹 함께 빠져 연속공간
                    ex = rec["exit"]
                    eg = sum(1 for p in state[j]["placed"] if abs(p["exit"] - ex) < EG_TAU)
                    sc -= EG_W * w1 * eg
                if best is None or sc < best[0]:
                    best = (sc, j, rec)
            if best is None:
                continue
            _, j, rec = best
            state[j]["placed"].append(rec)       # 품질 위치 그대로 commit (재패킹 없음)
            state[j]["last_entry"] = rec["entry"]
            load[j] += wk
            fixed[i] = j
            if guide is not None and j != g:     # 가이드 이탈 → 재계획 (횟수·데드라인 캡)
                ovf_ct += 1
                if (REPLAN_EVERY > 0 and ovf_ct % REPLAN_EVERY == 0
                        and replan_ct < MAX_REPLAN and time.time() < place_deadline):
                    guide = cpsat_guideline(data, fixed=fixed,
                                            time_s=min(5.0, max(2.0, tl * 0.03)), fit=fit)
                    replan_ct += 1
            continue

        if USE_GUIDE:
            g = guide[i] if guide[i] in fit[i] else fit[i][0]
            pl_g = place(g, i, R, P)
            # 가이드 베이서 z1 안 터지면(지각0) 그대로 따른다 → z2/z3 전역최적 보존
            if pl_g is not None and max(0, pl_g["exit"] - D) == 0:
                commit(i, g, pl_g, wk)
                fixed[i] = g
                continue
            # z1 터짐(또는 배치불가) → 전역 marginal 탐색해 오버플로
            best = None
            for j in fit[i]:
                pl = pl_g if j == g else place(j, i, R, P)
                if pl is None:
                    continue
                tardy = max(0, pl["exit"] - D)
                nl = load[:]
                nl[j] += wk
                sc = w1 * tardy + w2 * (z2_of(nl) - z2_of(load)) + w3 * (smax - pr[j])
                if best is None or sc < best[0]:
                    best = (sc, j, pl)
            if best is None:
                continue
            _, j, pl = best
            commit(i, j, pl, wk)
            fixed[i] = j
            if j != g:
                ovf_ct += 1
                # 오버플로 누적 → 이미 놓인 블록 고정한 채 남은 가이드라인 재계획
                if REPLAN_EVERY > 0 and ovf_ct % REPLAN_EVERY == 0:
                    guide = cpsat_guideline(data, fixed=fixed,
                                            time_s=min(5.0, max(2.0, tl * 0.03)), fit=fit)
            continue

        # ---- 가이드 OFF: 순수 전역 marginal 그리디 (구버전) ----
        best = None
        for j in fit[i]:
            pl = place(j, i, R, P)
            if pl is None:
                continue
            tardy = max(0, pl["exit"] - D)
            nl = load[:]
            nl[j] += wk
            sc = w1 * tardy + w2 * (z2_of(nl) - z2_of(load)) + w3 * (smax - pr[j])
            if best is None or sc < best[0]:
                best = (sc, j, pl)
        if best is None:
            continue
        _, j, pl = best
        commit(i, j, pl, wk)

    print(f"[DBG] after placement state dist={[len(state[j]['placed']) for j in range(m)]} ovf={ovf_ct}", file=sys.stderr, flush=True)
    # ---- 배정 추출 (greedy 결과) ----
    assign = [fit[i][0] for i in range(N)]
    for j in range(m):
        for p in state[j]["placed"]:
            assign[p["id"]] = j
    st("그리디 배치(가이드 추종+오버플로)", z2=round(_z2f(assign, blocks, u, m)),
       z3=_z3f(assign, blocks), dist=[len(state[j]["placed"]) for j in range(m)], ovf=ovf_ct)

    # ---- 베이 간 토스 정제: relocate로 obj↓ (z2 몰빵·z1 혼잡 해소) ----
    z1c, tc = {}, {}

    def gz1(W, H, ids):
        k = (W, H, ids)
        if k not in z1c:
            _, z, t = _z1_job((inst, W, H, ids))
            z1c[k], tc[k] = z, t
        return z1c[k]

    def bids(a):
        return {j: tuple(sorted(i for i in range(N) if a[i] == j)) for j in range(m)}

    ex = ProcessPoolExecutor(max_workers=4)
    moves, toss_dl = 0, t0 + tl * 0.55
    try:
        while _TOSS and moves < 60 and time.time() < toss_dl:
            bi = bids(assign)
            z1by = {j: gz1(dims[j][0], dims[j][1], bi[j]) for j in range(m)}
            bott = max(range(m), key=lambda j: z1by[j])
            if z1by[bott] == 0:
                break
            tlst = tc[(dims[bott][0], dims[bott][1], bi[bott])]
            tardy = sorted([(e, x - d) for (e, x, d) in tlst if x - d > 0], key=lambda z: -z[1])[:14]
            if not tardy:
                break
            cand = [e for e, _ in tardy]
            jobs = {}
            for i in cand:
                jobs[(dims[bott][0], dims[bott][1], tuple(sorted(set(bi[bott]) - {i})))] = 1
                for tj in (j for j in range(m) if j != bott and j in fit[i]):
                    jobs[(dims[tj][0], dims[tj][1], tuple(sorted(set(bi[tj]) | {i})))] = 1
            todo = [k for k in jobs if k not in z1c]
            for key, z, t in ex.map(_z1_job, [(inst, k0, k1, k2) for (k0, k1, k2) in todo]):
                z1c[key], tc[key] = z, t
            b2, b3 = _z2f(assign, blocks, u, m), _z3f(assign, blocks)
            best = None
            for i in cand:
                za = z1c[(dims[bott][0], dims[bott][1], tuple(sorted(set(bi[bott]) - {i})))]
                for tj in (j for j in range(m) if j != bott and j in fit[i]):
                    zb = z1c[(dims[tj][0], dims[tj][1], tuple(sorted(set(bi[tj]) | {i})))]
                    a2 = list(assign)
                    a2[i] = tj
                    dd = (w1 * ((za + zb) - (z1by[bott] + z1by[tj]))
                          + w2 * (_z2f(a2, blocks, u, m) - b2) + w3 * (_z3f(a2, blocks) - b3))
                    if best is None or dd < best[0]:
                        best = (dd, i, tj)
            if best is None or best[0] >= -1e-9:
                break
            _, i, tj = best
            assign[i] = tj
            moves += 1
    finally:
        ex.shutdown()

    # ---- 최종 배정 per-bay 패킹 → results ----
    if GLOBAL:
        # 전역 배치(state)의 품질 위치를 그대로 results 로 — 재패킹 없음 (위치 이미 품질배치).
        results, dist, pack_z1 = {}, [0] * m, 0
        for j in range(m):
            if not state[j]["placed"]:
                continue
            results[j] = {}
            for p in state[j]["placed"]:
                dist[j] += 1
                results[j][p["id"]] = {"block_id": p["id"], "bay_id": j, "x": p["x"], "y": p["y"],
                                       "orient_idx": p["orient"], "entry_time": p["entry"],
                                       "exit_time": p["exit"]}
                pack_z1 += max(0, p["exit"] - blocks[p["id"]]["due_date"])
    else:
        seed_key = os.environ.get("OGC_PACK_SEED", "edd")   # edd|area|height|release
        desc_budget = int(os.environ.get("OGC_PACK_DESCENT", "0"))  # >0: 랜덤 페어스왑 예산
        swap_frac = float(os.environ.get("OGC_PACK_SWAP", "0"))      # >0: 타깃 스왑에 줄 TL 비율
        use_merge = os.environ.get("OGC_MERGE", "0") != "0"          # 결합블록 강제 인터록
        nz = sum(1 for j in range(m) if any(assign[i] == j for i in range(N)))
        swap_per_bay = tl * swap_frac / max(1, nz) if swap_frac > 0 else 0
        results, dist, pack_z1 = {}, [0] * m, 0
        for j in range(m):
            ids = [i for i in range(N) if assign[i] == j]
            if not ids:
                continue
            sub = build_set(blocks, dims[j][0], dims[j][1], ids, SCALE)
            order0 = seed_order(sub, seed_key)
            pairs = None
            if use_merge:
                from merge import find_pairs
                pairs, _ = find_pairs(blocks, ids, SCALE)
            if swap_frac > 0:
                r = descent_tardy(sub, order0, True, time.monotonic() + swap_per_bay, fit=_FIT)
                placed, _gz = r["placed"], r["z1"]
            elif desc_budget > 0:
                r = descent(sub, order0, True, desc_budget, 7000 + j)
                placed, _gz = r["placed"], r["z1"]
            else:
                placed, _gz = simulate(sub, order0, allow_stack=True, fit=_FIT, pairs=pairs)
            pack_z1 += _gz
            results[j] = {}
            for p in placed:
                dist[j] += 1
                results[j][p["id"]] = {"block_id": p["id"], "bay_id": j, "x": p["x"], "y": p["y"],
                                       "orient_idx": p["orient"], "entry_time": p["entry"], "exit_time": p["exit"]}
    st("per-bay 패킹(diverse+fit=ov)", z1=int(pack_z1), z2=round(_z2f(assign, blocks, u, m)),
       z3=_z3f(assign, blocks), dist=list(dist))
    # ---- 병렬 per-bay CP-SAT 타이밍 (베이크기 비례 캡: 무캡은 노이즈로 낭비) ----
    elapsed = time.time() - t0
    max_bay = max((sum(1 for i in range(N) if assign[i] == j) for j in range(m)), default=1)
    cap = float(os.environ.get("OGC_TIMING_CAP", "0")) or (15.0 + 0.5 * max_bay)
    per_bay = float(os.environ.get("OGC_TIMING_S", "0")) or min(max(8.0, tl - elapsed - 5.0), cap)
    print(f"[DBG] timing per_bay_s={per_bay:.0f} (elapsed={elapsed:.0f})", file=sys.stderr, flush=True)
    res = parallel_timing(inst, data, results, per_bay_s=per_bay, workers=4)
    st("CP-SAT 타이밍(z1 최적화)", z1=res.get("obj1"), z2=res.get("obj2"),
       z3=res.get("obj3"), obj=res.get("objective"))

    # ---- E2: windowed Fix-and-Optimize — tardy 블록 사후 재배치(나머지 고정), additive ----
    if GLOBAL and os.environ.get("OGC_FIXOPT", "0") != "0" and res.get("objective") is not None:
        from ptiming import _bay_job
        fo_dl = t0 + tl - max(5.0, tl * 0.05)
        fo_pb = min(12.0, max(6.0, per_bay))

        def _bz1(j):
            """베이 j 현 블록-위치 고정, CP-SAT 최적 타이밍 z1 (pure, mutate 안 함)."""
            pl = state[j]["placed"]
            if not pl:
                return 0.0
            recs = {p["id"]: {"block_id": p["id"], "bay_id": j, "x": p["x"], "y": p["y"],
                              "orient_idx": p["orient"], "entry_time": p["entry"],
                              "exit_time": p["exit"]} for p in pl}
            try:
                _, rt = _bay_job((inst, j, recs, fo_pb))
            except Exception:
                rt = None
            if not rt:
                return float(sum(max(0, p["exit"] - blocks[p["id"]]["due_date"]) for p in pl))
            return float(sum(max(0, x - blocks[b]["due_date"])
                             for b, (e, x) in rt.items() if x is not None))

        z1b = {j: _bz1(j) for j in range(m) if state[j]["placed"]}
        moves = 0
        improved = True
        while improved and time.time() < fo_dl:
            improved = False
            tardy = sorted(((p["exit"] - blocks[p["id"]]["due_date"], p["id"], j)
                            for j in range(m) for p in state[j]["placed"]
                            if p["exit"] > blocks[p["id"]]["due_date"]), reverse=True)
            for _td, bid, j in tardy[:10]:
                if time.time() >= fo_dl:
                    break
                rj = next((p for p in state[j]["placed"] if p["id"] == bid), None)
                if rj is None:
                    continue
                state[j]["placed"].remove(rj)
                z1j_new = _bz1(j)
                R = blocks[bid].get("release_time", 0)
                P = blocks[bid]["processing_time"]
                D = blocks[bid]["due_date"]
                pr = blocks[bid]["bay_preferences"]
                wk = blocks[bid].get("workload", 0)
                best = None      # (dobj, j2, rec2, z1j2_new)
                for j2 in fit[bid]:
                    if j2 == j or time.time() >= fo_dl:
                        continue
                    rec2 = place_one(bid, dims[j2][0], dims[j2][1], ml, SCALE,
                                     state[j2]["placed"], state[j2]["last_entry"],
                                     shapes[bid], _cm, (R, P, D), blocks, bay_objs[j2], _FIT, True)
                    if rec2 is None:
                        continue
                    state[j2]["placed"].append(rec2)
                    z1j2_new = _bz1(j2)
                    state[j2]["placed"].pop()
                    nl = load[:]
                    nl[j] -= wk
                    nl[j2] += wk
                    dz1 = (z1j_new + z1j2_new) - (z1b[j] + z1b.get(j2, 0.0))
                    dz2 = z2_of(nl) - z2_of(load)
                    dz3 = pr[j] - pr[j2]      # z3 = Σ(smax-pr): 이동시 변화 = pr[j]-pr[j2]
                    dobj = w1 * dz1 + w2 * dz2 + w3 * dz3
                    if best is None or dobj < best[0]:
                        best = (dobj, j2, rec2, z1j2_new)
                if best is not None and best[0] < -1e-6:
                    _, j2, rec2, z1j2_new = best
                    state[j2]["placed"].append(rec2)
                    load[j] -= wk
                    load[j2] += wk
                    z1b[j] = z1j_new
                    z1b[j2] = z1j2_new
                    moves += 1
                    improved = True
                else:
                    state[j]["placed"].append(rj)    # 복원
        if moves:
            assign = [fit[i][0] for i in range(N)]
            results2, dist2 = {}, [0] * m
            for j in range(m):
                if not state[j]["placed"]:
                    continue
                results2[j] = {}
                for p in state[j]["placed"]:
                    assign[p["id"]] = j
                    dist2[j] += 1
                    results2[j][p["id"]] = {"block_id": p["id"], "bay_id": j, "x": p["x"], "y": p["y"],
                                            "orient_idx": p["orient"], "entry_time": p["entry"],
                                            "exit_time": p["exit"]}
            elapsed2 = time.time() - t0
            pb2 = min(per_bay, max(6.0, tl - elapsed2 - 3.0))
            res2 = parallel_timing(inst, data, results2, per_bay_s=pb2, workers=4)
            print(f"[DBG] FIXOPT moves={moves} obj {res.get('objective'):,}→{res2.get('objective')}",
                  file=sys.stderr, flush=True)
            if res2.get("objective") is not None and res2["objective"] < res["objective"]:
                results, dist, res = results2, dist2, res2     # additive: 개선시만 채택
        st("FIXOPT(tardy 재배치)", z1=res.get("obj1"), z2=res.get("obj2"),
           z3=res.get("obj3"), obj=res.get("objective"), moves=moves)
    # ---- 유휴시간 LNS (파괴-재구성으로 base 위 개선) ----
    if os.environ.get("OGC_LNS", "0") != "0" and res.get("objective") is not None:
        elapsed = time.time() - t0
        if tl - elapsed > 12.0:                          # 12초+ 남으면
            from lns import lns_improve
            results, res2 = lns_improve(inst, data, results, assign,
                                        t0 + tl - 3.0, per_bay,
                                        fit=_FITV if _FITV in ("tardy", "ov") else "1")
            if res2.get("objective") is not None and res2["objective"] < res["objective"]:
                res = res2
            st("LNS(유휴시간 개선)", z1=res.get("obj1"), z2=res.get("obj2"),
               z3=res.get("obj3"), obj=res.get("objective"))
    return res, dist, True, time.time() - t0


# 원래 솔버 기준선 (H1' @200s 측정값) — 재실행 스킵용
BASELINE = {
    "prob_38": {"objective": 91107711, "obj1": 6651, "obj2": 2964, "obj3": 8080},
    "prob_37": {"objective": 8579049, "obj1": 2045, "obj2": 2616, "obj3": 2921},
    "prob_25": {"objective": 550459, "obj1": 716, "obj2": 47, "obj3": 3642},
    "prob_40": {"objective": 4194610, "obj1": 6045, "obj2": 3241, "obj3": 12258},
}


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 200.0
    names = sys.argv[2:] or ["prob_38"]
    skip = os.environ.get("OGC_SKIP_ORIG") and all(n in BASELINE for n in names)
    print(f"== H3: 배정없는 통합 그리디 + CP-SAT vs 원래 (@{tl}s){' [orig cached]' if skip else ''} ==", flush=True)
    wins = 0
    for nm in names:
        path = os.path.join(TRAIN, nm + ".json")
        data = json.load(open(path, encoding="utf-8"))
        og = BASELINE[nm] if skip else check_feasibility(data, orig_alg(data, tl))
        res, dist, cpsat, dt = unified(data, tl, path)
        o = res.get("objective")
        print(f"\n[{nm}] N={len(data['blocks'])}, {len(data['bays'])}bays, w={data['weights']}", flush=True)
        print(f"  원래       obj={og.get('objective'):>14,.0f}  z1={og.get('obj1')} z2={og.get('obj2')} z3={og.get('obj3')}", flush=True)
        if o is None:
            print(f"  H3(통합)   INFEASIBLE stage={res.get('stage')} {(res.get('violations') or [])[:2]}", flush=True)
            continue
        d = og["objective"] - o
        if d > 0:
            wins += 1
        print(f"  H3(통합)   obj={o:>14,.0f}  z1={res.get('obj1')} z2={res.get('obj2')} z3={res.get('obj3')}"
              f"  => {'승' if d > 0 else '패'} {d/og['objective']*100:+.1f}%  (cpsat={cpsat}, dist={dist}, {dt:.0f}s)", flush=True)
    print(f"\n승 {wins}/{len(names)}", flush=True)


if __name__ == "__main__":
    main()
