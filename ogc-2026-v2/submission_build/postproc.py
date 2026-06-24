"""postproc.py -- v3 crane-repack post-process, additive & never-worse.

Wraps the v3 UNIFIED improvement loop (run_full.py) as a reusable function that
takes a finished best-of solution and polishes it within a wall-clock deadline:

  postprocess(prob_info, solution, deadline_monotonic) -> solution

Each pass is a coordinate-descent step (x/y/o crane-repack per tardy bay) or a
cross-bay move/swap, GATED never-worse on the FULL official objective
(v3pp.seed.global_eval).  A trial is accepted iff it is feasible AND total obj
strictly improves.  The loop stops when time.monotonic() >= deadline or a whole
round accepts nothing (converged).

NEVER-WORSE CONTRACT
--------------------
* The whole body is wrapped in try/except: on ANY failure (import, deserialize,
  CP-SAT crash, infeasible reconstruction, ...) we return the ORIGINAL `solution`
  unchanged.  A feasible best-of submission can never become infeasible or worse.
* The base solution is re-evaluated with the official checker first; if it is not
  feasible (shouldn't happen for a real sol) we also return the original.
* Only strictly-improving, feasible trials are ever adopted, so the returned
  serialized solution is >= the input in objective by construction.

The v3 modules live in the isolated `v3pp` package (their own temporal_pack /
gridmap / density_pack so they don't collide with the v2 solver's top-level
versions; utils is the shared official one).
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# C1 강화 노브(연구 2026-06-22): layout-bound 잔여 z1 진단 결과, free-all X축 crane_repack
# (n_xcand 큼)으로 같은-배정 zero-tardy 레이아웃을 찾으면 z1↓+obj↓(prob_6 −59K, prob_15 −15K).
# OGC_PP_KX>0: tardy 바이 X축 repack 후보수 override. OGC_PP_FREEALL=1: window_tardy_only=False
# (전 블록 자유 재배치). 둘 다 기본 0/OFF=현 동작. 정밀 set1 z1=0 레버, set2는 precompute 폭발 위험.
_PP_KX = int(os.environ.get("OGC_PP_KX", "0"))
_PP_FREEALL = os.environ.get("OGC_PP_FREEALL", "0") == "1"
# strongX free-all only for bays with <= this many blocks (big bays -> window_tardy_only
# to avoid O(n^2*cands) precompute blowup).  Size-gated, NOT set-gated -> generalizes.
_PP_FREEALL_MAX = int(os.environ.get("OGC_PP_FREEALL_MAX", "999"))
# C3 노브(연구 2026-06-22): try_move(C2)는 단일 argmax-선호 베이로만 이동. 진단(prob_18)에서
# 동점-선호 다른 베이로 옮기면 z1=0+obj↓인데 놓침. C3=잔여 tardy 블록을 모든 fit 베이로
# crane_repack(free_ids 1블록=빠름) 이동 시도, never-worse. 기본 OFF. cheap이라 set2도 후보.
_PP_MOVEALL = os.environ.get("OGC_PP_MOVEALL", "0") == "1"
# 순수 타이밍 패스(연구 2026-06-23): 위치·방향·배정 고정 -> entry(t)만 베이별 전역 최적.
# 0D 타이밍 오라클(n_xcand=n_ycand=n_ocand=0)은 큰 바이도 ~1s OPTIMAL(측정), z1 exact.
# 윈도-스패셜(near-tardy 윈도만)이 놓치는 교차-윈도 z1을 베이 전체에서 잡는다. never-worse. 기본 OFF.
_PP_PURET = os.environ.get("OGC_PP_PURET", "0") == "1"
# 스텝별 시간/obj-delta 계측(HTML 브리핑용). 기본 OFF -> 프로덕션 무영향.
_PP_TRACE = os.environ.get("OGC_PP_TRACE", "0") == "1"
_STEP_TRACE = []   # list[dict]: {step, bay, dt, d_obj, accepted}  (when _PP_TRACE)
# per-pass CP-SAT wall ceiling (s).  Lower (e.g. 30) -> each pass returns sooner ->
# MORE attempts within the budget (big bays hit FEASIBLE not OPTIMAL anyway, so a
# longer cap just burns time).  Default 40 = previous behavior (production unchanged).
_PP_TS_CAP = float(os.environ.get("OGC_PP_TS_CAP", "40"))
# 듀얼-윈도우(연구 2026-06-23, 사용자 지시): x,y축 repack을 area-인접 윈도우(x-bbox)와
# time-인접 윈도우(co-present) 두 패스로 각각 돌린다 -> 두 윈도우는 서로 다른 블록을
# active로 골라 각기 다른 크레인 충돌을 잡는다.  window_tardy_only 강제(True)라 window_mode가
# active를 지배.  기본 OFF = 기존 단일 x/y/o 패스(FREEALL 동작 유지) -> 프로덕션 무변경.
_PP_DUALWIN = os.environ.get("OGC_PP_DUALWIN", "0") == "1"
# C3-front(연구 2026-06-23, 사용자 지시): tardy 블록의 원인은 그 블록이 아니라, 그 블록이
# 진입하는 순간 크레인 창을 점유한 "시간적으로 앞선 co-present 선행 블록들"이다. 그 선행
# 블록을 다른 베이로 빼고 원 베이를 재타이밍(pure-t)하면 tardy가 freed slot으로 당겨진다.
# 앞 시간대라 다른 베이가 받아줄 여지도 큼 + 베이 구조 흔들기. never-worse. 기본 OFF.
_PP_FRONTMOVE = os.environ.get("OGC_PP_FRONTMOVE", "0") == "1"
# front pass ordering: 1 = run at the START of each round (shake BEFORE the productive
# passes, so they build on the shaken structure -- the real test of the "front enables
# others" hypothesis); 0 = at the END (leftover-only).  Default END.
_PP_FRONT_FIRST = os.environ.get("OGC_PP_FRONT_FIRST", "0") == "1"
# C3-CLUSTER(연구 2026-06-23, 사용자): 단일-블록 frontmove가 분산-레버리지로 실패하니,
# 가장 심한 tardy bt의 co-present x-overlap 선행블록들을 "묶음(cluster)"으로 한꺼번에 다른
# 베이들로 날리고 원 베이를 재타이밍 → bt의 크레인 창을 통째로 연다. atomic, never-worse.
_PP_CLUSTER = os.environ.get("OGC_PP_CLUSTER", "0") == "1"


# ---------------------------------------------------------------------------
# helpers lifted verbatim from run_full.py (kept module-local)
# ---------------------------------------------------------------------------
def _pass_cap(n_bay_blocks, remaining, n_active_bays):
    """Adaptive per-pass CP-SAT wall cap (seconds).  OGC_PP_TS_CAP overrides the
    size ceiling (default 40); lower it (e.g. 30) for more, shorter attempts."""
    size_cap = min(_PP_TS_CAP, max(12.0, 0.30 * n_bay_blocks))
    budget_cap = remaining / max(1.0, 2.0 * n_active_bays)
    return float(max(8.0, min(size_cap, max(budget_cap, 10.0), remaining)))


def _axis_kwargs(axis, K):
    if axis == "x":
        return (K, 0, 0)
    if axis == "y":
        return (0, K, 0)
    if axis == "o":
        return (0, 0, K)
    raise ValueError("unknown axis '%s'" % axis)


def _bz1(data, pl):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def _preferred(data, bid):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def _z3_contrib(data, bid, cur_bay):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(prefs) - prefs[cur_bay]


def _rec(step, bay, t0, obj_before, obj_after, accepted):
    """Record one CP-SAT step's wall + obj improvement (HTML briefing only)."""
    if _PP_TRACE:
        _STEP_TRACE.append({
            "step": step, "bay": int(bay),
            "dt": time.monotonic() - t0,
            "d_obj": float(obj_before - obj_after) if accepted else 0.0,
            "obj_after": float(obj_after),
            "accepted": bool(accepted),
        })


# ---------------------------------------------------------------------------
def _front_pass(data, cur, cur_obj, deadline, K):
    """C3-front (cheap, HARD time-bounded): move a tardy block's temporal predecessors
    (co-present blocks that started no later) to another bay, then re-time the source
    bay (pure-t) so the tardy block slides into the freed crane window.

    Bounded so the WHOLE pass finishes well under a minute and never starves the other
    passes:  OGC_PP_FRONT_BUDGET (wall cap, default 45s, checked between calls) +
    OGC_PP_FRONT_K (top-K biggest crane-blockers, default 6) + OGC_PP_FRONT_TS (small
    per-call CP-SAT cap, default 5s).  never-worse gated.  Returns (cur, cur_obj, n_acc).
    """
    from v3pp import seed as S
    from v3pp import crane_cpsat as C
    from v3pp.bpass import _seed_into_bay
    fk = int(os.environ.get("OGC_PP_FRONT_K", "6"))
    fbud = float(os.environ.get("OGC_PP_FRONT_BUDGET", "45"))
    fts = float(os.environ.get("OGC_PP_FRONT_TS", "5"))
    sel = os.environ.get("OGC_PP_FRONT_SEL", "xext")    # xext | overlap
    dest_mode = os.environ.get("OGC_PP_FRONT_DEST", "any")  # any | slack
    front_swap = os.environ.get("OGC_PP_FRONT_SWAP", "0") == "1"  # exchange when dest full
    front_deadline = min(deadline, time.monotonic() + fbud)
    nbay = len(data["bays"])
    cands, seen_f = [], set()
    for j, pl in cur.items():
        tardies = [p for p in pl if p["exit"] > data["blocks"][p["id"]].get("due_date", 0)]
        if not tardies:
            continue
        for bt in tardies:
            te = bt["entry"]
            bx0, bx1 = bt["x"] + bt["sh"].min_x, bt["x"] + bt["sh"].max_x
            for p in pl:
                if p["id"] == bt["id"]:
                    continue
                # co-present predecessor: started no later than bt, present at its entry
                if not (p["entry"] <= te and p["exit"] > te):
                    continue
                px0, px1 = p["x"] + p["sh"].min_x, p["x"] + p["sh"].max_x
                xov = min(px1, bx1) - max(px0, bx0)    # x-overlap with bt (>0 = crane blocker)
                if sel == "overlap" and xov <= 0:
                    continue                           # not in bt's crane column -> skip
                key = (j, p["id"])
                if key in seen_f:
                    continue
                seen_f.add(key)
                # rank: overlap -> most x-overlap (most blocking); xext -> widest block
                score = xov if sel == "overlap" else (p["sh"].max_x - p["sh"].min_x)
                cands.append((score, j, p["id"]))
    cands.sort(reverse=True)
    cands = cands[:fk]
    n_acc = 0
    for _xe, j, fid in cands:
        now = time.monotonic()
        if now >= front_deadline:
            break
        ob = cur_obj
        p = next((q for q in cur.get(j, []) if q["id"] == fid), None)
        if p is None:
            continue
        ts = min(fts, _pass_cap(8, deadline - now, 1))
        reduced_j = [q for q in cur[j] if q["id"] != fid]
        try:
            retimed_j, _s, _w, _i = C.crane_repack_bay(
                data, j, reduced_j, ts, n_xcand=0, n_ycand=0, n_ocand=0,
                window_tardy_only=False)
        except Exception:
            retimed_j = None
        if retimed_j is None:
            retimed_j = reduced_j
        acc = False
        fe, fx = p["entry"], p["exit"]
        fa = (p["sh"].max_x - p["sh"].min_x) * (p["sh"].max_y - p["sh"].min_y)
        if dest_mode == "slack":   # least-occupied bay during f's [entry,exit] first
            def _occ(tb, _fe=fe, _fx=fx):
                return sum((q["sh"].max_x - q["sh"].min_x) * (q["sh"].max_y - q["sh"].min_y)
                           for q in cur.get(tb, []) if q["entry"] < _fx and q["exit"] > _fe)
            dests = sorted((tb for tb in range(nbay) if tb != j), key=_occ)
        else:
            dests = [tb for tb in range(nbay) if tb != j]
        for tb in dests:
            if time.monotonic() >= front_deadline:
                break
            # (a) plain move: f -> tb (tb frozen)
            b_seed = _seed_into_bay(data, tb, p)
            try:
                new_tb, _s, _w, _i = C.crane_repack_bay(
                    data, tb, list(cur.get(tb, [])) + [b_seed], ts, n_xcand=K, free_ids={fid})
            except Exception:
                new_tb = None
            if new_tb is not None:
                trial = dict(cur); trial[j] = retimed_j; trial[tb] = new_tb
                ev = S.global_eval(data, trial)
                if (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6):
                    cur, cur_obj = trial, ev["obj"]
                    n_acc += 1; acc = True
                    break
            # (b) SWAP fallback: dest full -> exchange f with a co-present similar-size
            # block c in tb (f -> tb minus c; c -> bay j's freed space).  z2-neutral.
            if front_swap:
                co = [q for q in cur.get(tb, []) if q["entry"] < fx and q["exit"] > fe]
                co.sort(key=lambda q: abs((q["sh"].max_x - q["sh"].min_x)
                                          * (q["sh"].max_y - q["sh"].min_y) - fa))
                for c in co[:3]:
                    if time.monotonic() >= front_deadline:
                        break
                    cid = c["id"]
                    tb_pre = [q for q in cur.get(tb, []) if q["id"] != cid] + [_seed_into_bay(data, tb, p)]
                    j_pre = list(retimed_j) + [_seed_into_bay(data, j, c)]
                    try:
                        new_tb2, _, _, _ = C.crane_repack_bay(data, tb, tb_pre, ts, n_xcand=K, free_ids={fid})
                        new_j2, _, _, _ = C.crane_repack_bay(data, j, j_pre, ts, n_xcand=K, free_ids={cid})
                    except Exception:
                        new_tb2 = new_j2 = None
                    if new_tb2 is None or new_j2 is None:
                        continue
                    trial = dict(cur); trial[tb] = new_tb2; trial[j] = new_j2
                    ev = S.global_eval(data, trial)
                    if (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6):
                        cur, cur_obj = trial, ev["obj"]
                        n_acc += 1; acc = True
                        break
                if acc:
                    break
        _rec("frontmoveall", j, now, ob, cur_obj, acc)
    return cur, cur_obj, n_acc


def _cluster_pass(data, cur, cur_obj, deadline, K):
    """C3-CLUSTER (developed 2026-06-23): bulk-evict the worst tardy block's blocking
    predecessor cluster to other bays + re-time, so bt slides into the freed window.
    Attacks single-block frontmove's diffuse-leverage failure (one predecessor owns a
    fraction of bt's contention; the cluster owns it all).  v2 improvements:
      (1) WINDOW-aware selection: predecessors x-overlapping bt that occupy bt's DESIRED
          window [release, current_entry] -- the slot bt wants -- not just bt's entry.
      (2) ADAPTIVE size: try the full cluster atomically, then fall back to smaller
          sub-clusters (half/quarter/1) so SATURATED bays still land a partial win.
    Atomic per accepted sub-cluster, never-worse.  (cur, cur_obj, n_acc).

    OGC_PP_CLUSTER_BUDGET (60s) / _TS (4s) / _MAX (6) / _ADAPT (1=size fallback).
    """
    from v3pp import seed as S
    from v3pp import crane_cpsat as C
    from v3pp.bpass import _seed_into_bay
    cbud = float(os.environ.get("OGC_PP_CLUSTER_BUDGET", "60"))
    cts = float(os.environ.get("OGC_PP_CLUSTER_TS", "4"))
    cmax = int(os.environ.get("OGC_PP_CLUSTER_MAX", "6"))
    adapt = os.environ.get("OGC_PP_CLUSTER_ADAPT", "1") == "1"
    cdl = min(deadline, time.monotonic() + cbud)
    nbay = len(data["bays"])
    n_acc = 0

    def _evict(j, retimed_j, sub, ts):
        """Evict sub (already removed from retimed_j) to other bays, freeze the rest.
        Returns (trial, obj) if ALL placed and feasible, else (None, None)."""
        trial = dict(cur)
        trial[j] = retimed_j
        for c in sub:
            if time.monotonic() >= cdl:
                return None, None
            fe, fx = c["entry"], c["exit"]

            def _occ(tb, _fe=fe, _fx=fx):
                return sum((q["sh"].max_x - q["sh"].min_x) * (q["sh"].max_y - q["sh"].min_y)
                           for q in trial.get(tb, []) if q["entry"] < _fx and q["exit"] > _fe)
            placed = False
            for tb in sorted((b for b in range(nbay) if b != j), key=_occ):
                seed = _seed_into_bay(data, tb, c)
                try:
                    new_tb, _s, _w, _i = C.crane_repack_bay(
                        data, tb, list(trial.get(tb, [])) + [seed], ts,
                        n_xcand=K, free_ids={c["id"]})
                except Exception:
                    new_tb = None
                if new_tb is not None:
                    trial[tb] = new_tb
                    placed = True
                    break
            if not placed:
                return None, None
        ev = S.global_eval(data, trial)
        if ev["feasible"] and ev["obj"] is not None:
            return trial, ev["obj"]
        return None, None

    tardy_list = []
    for j, pl in cur.items():
        for p in pl:
            d = data["blocks"][p["id"]].get("due_date", 0)
            if p["exit"] > d:
                tardy_list.append((p["exit"] - d, j, p["id"]))
    tardy_list.sort(reverse=True)        # worst tardy first (highest leverage)
    for _lat, j, btid in tardy_list:
        now = time.monotonic()
        if now >= cdl:
            break
        ob = cur_obj
        bt = next((q for q in cur.get(j, []) if q["id"] == btid), None)
        if bt is None:
            continue
        te = bt["entry"]
        R = data["blocks"][btid].get("release_time", 0)
        bx0, bx1 = bt["x"] + bt["sh"].min_x, bt["x"] + bt["sh"].max_x
        cl = []
        for p in cur[j]:
            if p["id"] == btid:
                continue
            # occupies bt's DESIRED window [release, current_entry] AND its crane column
            if not (p["entry"] <= te and p["exit"] > R):
                continue
            px0, px1 = p["x"] + p["sh"].min_x, p["x"] + p["sh"].max_x
            ov = min(px1, bx1) - max(px0, bx0)
            if ov > 0:
                cl.append((ov, p))
        if not cl:
            continue
        cl.sort(reverse=True, key=lambda t: t[0])
        full = [p for _o, p in cl[:cmax]]
        if adapt:
            sizes = sorted({len(full), max(1, len(full) // 2),
                            max(1, len(full) // 4), 1}, reverse=True)
        else:
            sizes = [len(full)]
        ts = min(cts, _pass_cap(8, cdl - now, 1))
        acc = False
        for csize in sizes:                       # largest cluster first, fall back smaller
            if time.monotonic() >= cdl:
                break
            sub = full[:csize]
            cids = {p["id"] for p in sub}
            reduced_j = [q for q in cur[j] if q["id"] not in cids]
            try:
                retimed_j, _s, _w, _i = C.crane_repack_bay(
                    data, j, reduced_j, ts, n_xcand=0, n_ycand=0, n_ocand=0,
                    window_tardy_only=False)
            except Exception:
                retimed_j = None
            if retimed_j is None:
                retimed_j = reduced_j
            trial, tobj = _evict(j, retimed_j, sub, ts)
            if trial is not None and tobj < cur_obj - 1e-6:
                cur, cur_obj = trial, tobj
                n_acc += 1
                acc = True
                break
        _rec("cluster", j, now, ob, cur_obj, acc)
    return cur, cur_obj, n_acc


def _moveall_pass(data, cur, cur_obj, deadline, K):
    """Enhanced moveall test-bed (NOT wired into the loop yet) -- tardy block -> another
    bay.  Gated enhancements over the inline production moveall:
      OGC_PP_MOVEALL_PREF=1        try bt's PREFERRED bay first (z1+z3 double win), then
                                   remaining bays slack-ordered at bt's window.
      OGC_PP_MOVEALL_DESTRETIME=1  free bt AND the dest blocks co-present with bt's
                                   window -> destination RE-TIMES to absorb bt (vs the
                                   frozen-dest baseline that fails on saturated bays).
    Baseline (both 0) == inline moveall (free_ids={bt}, dest frozen, any-fit).
    never-worse.  Returns (cur, cur_obj, n_acc)."""
    from v3pp import seed as S
    from v3pp import crane_cpsat as C
    from v3pp.bpass import _seed_into_bay
    pref_first = os.environ.get("OGC_PP_MOVEALL_PREF", "0") == "1"
    destretime = os.environ.get("OGC_PP_MOVEALL_DESTRETIME", "0") == "1"
    nbay = len(data["bays"])
    n_acc = 0
    tardy_blocks = [(p["exit"] - data["blocks"][p["id"]].get("due_date", 0), j, p["id"])
                    for j, pl in cur.items() for p in pl
                    if p["exit"] > data["blocks"][p["id"]].get("due_date", 0)]
    # OGC_PP_MOVEALL_ORDER: tardy(default, worst-first) | area(biggest bbox first) |
    # copres(most co-present neighbors in its bay first).  Only changes which moves the
    # 60s budget tries first; 'tardy' == current production behavior.
    _order = os.environ.get("OGC_PP_MOVEALL_ORDER", "tardy")
    if _order in ("area", "copres"):
        def _okey(tb):
            _l, jj, bb = tb
            q = next((x for x in cur.get(jj, []) if x["id"] == bb), None)
            if q is None:
                return 0
            if _order == "area":
                return (q["sh"].max_x - q["sh"].min_x) * (q["sh"].max_y - q["sh"].min_y)
            e, x = q["entry"], q["exit"]
            return sum(1 for r in cur.get(jj, []) if r["entry"] < x and r["exit"] > e)
        tardy_blocks.sort(key=_okey, reverse=True)
    else:
        tardy_blocks.sort(reverse=True)    # worst tardy first (highest leverage)
    for _lat, j, bid in tardy_blocks:
        now = time.monotonic()
        if now >= deadline - 1.0:
            break
        ob = cur_obj
        p = next((q for q in cur.get(j, []) if q["id"] == bid), None)
        if p is None:
            continue
        ts = _pass_cap(8, deadline - now, 1)
        others = [tb for tb in range(nbay) if tb != j]
        if pref_first:
            be = int(data["blocks"][bid].get("release_time", 0))
            bx = be + int(round(p["exit"] - p["entry"]))

            def _occ(tb, _e=be, _x=bx):
                return sum((q["sh"].max_x - q["sh"].min_x) * (q["sh"].max_y - q["sh"].min_y)
                           for q in cur.get(tb, []) if q["entry"] < _x and q["exit"] > _e)
            others.sort(key=_occ)
            pref = _preferred(data, bid)
            if pref != j and pref in others:
                others = [pref] + [tb for tb in others if tb != pref]
        acc = False
        for tb in others:
            if time.monotonic() >= deadline - 1.0:
                break
            b_seed = _seed_into_bay(data, tb, p)
            placed_new = list(cur.get(tb, [])) + [b_seed]
            free = {bid}
            if destretime:
                fe, fx = b_seed["entry"], b_seed["exit"]
                free |= {q["id"] for q in cur.get(tb, [])
                         if q["entry"] < fx and q["exit"] > fe}
            try:
                new_k, _st, _w, _ci = C.crane_repack_bay(
                    data, tb, placed_new, ts, n_xcand=K, free_ids=free)
            except Exception:
                new_k = None
            if new_k is None:
                continue
            trial = dict(cur)
            trial[j] = [q for q in cur[j] if q["id"] != bid]
            trial[tb] = new_k
            ev = S.global_eval(data, trial)
            if (ev["feasible"] and ev["obj"] is not None
                    and ev["obj"] < cur_obj - 1e-6):
                cur, cur_obj = trial, ev["obj"]
                n_acc += 1
                acc = True
                break
        _rec("moveall", j, now, ob, cur_obj, acc)
    return cur, cur_obj, n_acc


# ---------------------------------------------------------------------------
def _run_loop(data, cur, cur_obj, deadline, K=5):
    """run_full.main()'s round loop, deadline-driven, quiet, gated never-worse.

    Returns (best_bays_placed, best_obj).  Only strictly-improving feasible
    trials are adopted, so (cur, cur_obj) only ever improves.
    """
    from v3pp import seed as S
    from v3pp import crane_cpsat as C
    from v3pp import bpass as B

    while time.monotonic() < deadline - 1.0:
        round_accepts = 0

        # ---- C3-FRONT (FIRST, optional): shake structure BEFORE the productive passes
        if _PP_FRONTMOVE and _PP_FRONT_FIRST:
            cur, cur_obj, _na = _front_pass(data, cur, cur_obj, deadline, K)
            round_accepts += _na

        # ---- C3-CLUSTER (optional): bulk-evict the worst tardy block's predecessor
        # cluster to other bays + re-time.  Runs early (structural shake before others).
        if _PP_CLUSTER:
            cur, cur_obj, _na = _cluster_pass(data, cur, cur_obj, deadline, K)
            round_accepts += _na

        # ---- PURE-T (CHEAPEST, FIRST): per-bay timing oracle on the FIXED layout ----
        # positions/orient/assignment frozen (n_*cand=0) -> only entry(t) free, over the
        # WHOLE bay timeline (window_tardy_only=False is moot with 0 candidates, but every
        # block still gets an entry IntVar).  0D model = ~1s OPTIMAL even on big bays;
        # catches cross-window z1 the windowed spatial passes miss.  never-worse gated.
        if _PP_PURET:
            puret_bays = [(j, _bz1(data, pl)) for j, pl in cur.items()]
            puret_bays = [(j, z) for j, z in puret_bays if z > 0]
            puret_bays.sort(key=lambda x: -x[1])
            for j, _z in puret_bays:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                ob = cur_obj
                ts = _pass_cap(len(cur[j]), deadline - now, max(1, len(puret_bays)))
                try:
                    new_pl, _st, _w, _ci = C.crane_repack_bay(
                        data, j, cur[j], ts, n_xcand=0, n_ycand=0, n_ocand=0,
                        window_tardy_only=False)
                except Exception:
                    new_pl = None
                accepted = False
                if new_pl is not None:
                    trial = dict(cur)
                    trial[j] = new_pl
                    ev = S.global_eval(data, trial)
                    if (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6):
                        cur = trial
                        cur_obj = ev["obj"]
                        round_accepts += 1
                        accepted = True
                _rec("puret", j, now, ob, cur_obj, accepted)

        # ---- C3 (CHEAP, FIRST): z1 cross-bay repair -- tardy block -> ANY fit bay ----
        # Runs BEFORE the expensive strongX C1 so cheap z1-fixes never get starved.
        # C2/try_move only target the single argmax-preferred bay; a tie/low-cost OTHER
        # bay can be zero-tardy (diag prob_18: move to tie-pref bay => z1 0, obj -6329).
        if _PP_MOVEALL:
            from v3pp.bpass import _seed_into_bay
            nbay = len(data["bays"])
            tardy_blocks = [(j, p["id"]) for j, pl in cur.items() for p in pl
                            if p["exit"] > data["blocks"][p["id"]].get("due_date", 0)]
            for j, bid in tardy_blocks:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                ob = cur_obj
                p = next((q for q in cur.get(j, []) if q["id"] == bid), None)
                if p is None:
                    continue
                ts = _pass_cap(8, deadline - now, 1)
                acc = False
                for tb in range(nbay):
                    if tb == j:
                        continue
                    b_seed = _seed_into_bay(data, tb, p)
                    placed_new = list(cur.get(tb, [])) + [b_seed]
                    try:
                        new_k, _st, _w, _ci = C.crane_repack_bay(
                            data, tb, placed_new, ts, n_xcand=K, free_ids={bid})
                    except Exception:
                        new_k = None
                    if new_k is None:
                        continue
                    trial = dict(cur)
                    trial[j] = [q for q in cur[j] if q["id"] != bid]
                    trial[tb] = new_k
                    ev = S.global_eval(data, trial)
                    if (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6):
                        cur = trial
                        cur_obj = ev["obj"]
                        round_accepts += 1
                        acc = True
                        break
                _rec("moveall", j, now, ob, cur_obj, acc)

        # ---- SPATIAL: coordinate descent on tardy bays ----
        bays_t = [(j, _bz1(data, pl)) for j, pl in cur.items()]
        bays_t = [(j, z) for j, z in bays_t if z > 0]
        bays_t.sort(key=lambda x: -x[1])
        n_active_bays = len(bays_t)
        if _PP_DUALWIN:
            # x,y each run TWICE: area-adjacent (x-bbox) AND time-adjacent (co-present).
            # The two windows select DIFFERENT block sets -> each catches its own crane
            # conflicts.  o runs once (area).  window_mode forces window_tardy_only=True.
            passes = [("x", "x", "x-area"), ("x", "t", "x-time"),
                      ("y", "x", "y-area"), ("y", "t", "y-time"),
                      ("o", "x", "o-area")]
        else:
            passes = [("x", None, "spatial:x"), ("y", None, "spatial:y"),
                      ("o", None, "spatial:o")]
        for j, _z1 in bays_t:
            for axis, wmode, sname in passes:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                ob = cur_obj
                remaining = deadline - now
                ts = _pass_cap(len(cur[j]), remaining, n_active_bays)
                nxc, nyc, noc = _axis_kwargs(axis, K)
                if axis == "x" and _PP_KX:        # 강화된 X축 repack 후보수
                    nxc = _PP_KX
                kw = {"n_xcand": nxc, "n_ycand": nyc, "n_ocand": noc}
                if _PP_DUALWIN:
                    kw["window_mode"] = wmode      # window_tardy_only stays True (default)
                elif _PP_FREEALL and len(cur[j]) <= _PP_FREEALL_MAX:
                    kw["window_tardy_only"] = False
                try:
                    new_pl, st, wall, _info = C.crane_repack_bay(data, j, cur[j], ts, **kw)
                except TypeError:
                    kw.pop("n_ocand", None)
                    kw.pop("window_tardy_only", None)
                    kw.pop("window_mode", None)
                    new_pl, st, wall, _info = C.crane_repack_bay(data, j, cur[j], ts, **kw)
                accepted = False
                if new_pl is not None:
                    trial = dict(cur)
                    trial[j] = new_pl
                    ev = S.global_eval(data, trial)
                    if (ev["feasible"] and ev["obj"] is not None
                            and ev["obj"] < cur_obj - 1e-6):
                        cur = trial
                        cur_obj = ev["obj"]
                        round_accepts += 1
                        accepted = True
                _rec(sname, j, now, ob, cur_obj, accepted)
            if time.monotonic() >= deadline - 1.0:
                break

        # ---- CROSS-BAY: move/swap on tardy + wrong-bay blocks ----
        # H1 (OGC_PP_WRONGBAY=1): drop the tardy filter so preference-displaced
        # blocks (wrong-bay, z1=0) also become move/swap targets -> recovers z3 on
        # set1 where everything is on-time. never-worse gate still protects.
        _wrongbay = os.environ.get("OGC_PP_WRONGBAY") == "1"
        targets = []
        for j, placed in cur.items():
            for p in placed:
                bid = p["id"]
                due = data["blocks"][bid].get("due_date", 0)
                if (not _wrongbay) and p["exit"] <= due:
                    continue
                k = _preferred(data, bid)
                if k == j:
                    continue
                if _z3_contrib(data, bid, j) <= 0:
                    continue
                targets.append((bid, _z3_contrib(data, bid, j), p["exit"] - due))
        targets.sort(key=lambda t: (t[1], t[2]), reverse=True)

        for bid, z3c, _late in targets:
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            ob = cur_obj
            remaining = deadline - now
            pref_bay = _preferred(data, bid)
            dest_n = len(cur.get(pref_bay, []))
            ts = _pass_cap(dest_n, remaining, max(1, n_active_bays))

            # --- try_move ---
            trial, _info = B.try_move(data, cur, bid, ts, n_xcand=K)
            accepted_here = False
            if trial is not None:
                ev = S.global_eval(data, trial)
                if (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6):
                    cur = trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
                    accepted_here = True
            _rec("move", pref_bay, now, ob, cur_obj, accepted_here)
            if accepted_here:
                continue

            # --- try_swap (only if move didn't improve) ---
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            ob = cur_obj
            ts = _pass_cap(dest_n, deadline - now, max(1, n_active_bays))
            s_trial, s_info = B.try_swap(data, cur, bid, ts, n_xcand=K)
            accepted_s = False
            if s_trial is not None:
                ev = S.global_eval(data, s_trial)
                if (ev["feasible"] and ev["obj"] is not None
                        and ev["obj"] < cur_obj - 1e-6):
                    cur = s_trial
                    cur_obj = ev["obj"]
                    round_accepts += 1
                    accepted_s = True
            _rec("swap", pref_bay, now, ob, cur_obj, accepted_s)

        # ---- C3-FRONT (LAST): structural shake on leftover time (unless FRONT_FIRST).
        if _PP_FRONTMOVE and not _PP_FRONT_FIRST:
            cur, cur_obj, _na = _front_pass(data, cur, cur_obj, deadline, K)
            round_accepts += _na

        if round_accepts == 0:
            break

    return cur, cur_obj


# ---------------------------------------------------------------------------
def postprocess(prob_info, solution, deadline_monotonic, K=5):
    """Polish a finished best-of `solution` until `deadline_monotonic`.

    ADDITIVE + NEVER-WORSE: returns either an improved-and-feasible solution or
    the ORIGINAL `solution` unchanged.  Any exception => original solution.
    """
    if _PP_TRACE:
        _STEP_TRACE.clear()
    try:
        from v3pp import adapter
        from v3pp import seed as S

        bays_placed = adapter.deserialize(prob_info, solution)
        base = S.global_eval(prob_info, bays_placed)
        # If the reconstruction isn't feasible (shouldn't happen for a real sol),
        # don't risk returning a re-serialized version -- keep the original.
        if not base["feasible"] or base["obj"] is None:
            return solution

        best_bays, best_obj = _run_loop(
            prob_info, bays_placed, base["obj"], deadline_monotonic, K=K)

        # Only return a re-serialized solution if we STRICTLY improved AND it is
        # still feasible; otherwise hand back the untouched original.
        if best_obj < base["obj"] - 1e-6:
            final = S.global_eval(prob_info, best_bays)
            if final["feasible"] and final["obj"] is not None \
                    and final["obj"] < base["obj"] - 1e-6:
                return S.serialize(best_bays)
        return solution
    except Exception:
        return solution


__all__ = ["postprocess"]
