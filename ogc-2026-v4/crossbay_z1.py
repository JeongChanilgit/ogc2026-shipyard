"""
crossbay_z1.py -- z1-타겟 크로스베이 이동 A/B 검증 (격리 실험)

이론: interval graph χ=ω (클리크수 = 최대 co-presence).
binding 베이 피크 클리크 멤버를 가장 한가한 베이로 이동 → 양쪽 n_b(t) 1씩 증감.
크레인 직렬화 감소 → z1 감소 가능.

대상: prob_27, prob_38, prob_40, prob_26 (set2, z1 유망 순).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from copy import deepcopy

# ---------------------------------------------------------------------------
# 경로: v4 폴더의 모듈 사용 (v3 모듈 재사용)
# ---------------------------------------------------------------------------
V4 = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.normpath(os.path.join(V4, "..", "ogc-2026-v3"))
INST_DIR = os.path.normpath(os.path.join(V4, "..", "instances", "train"))

# v4 우선, v3 보조 (adapter/crane_cpsat은 v3에서 가져옴)
for d in [V4, V3]:
    if d not in sys.path:
        sys.path.insert(0, d)

# v4 에서: utils, seed (v4 버전 있으면), adapter, crane_cpsat
# 없으면 v3 폴백
try:
    import seed as _seed_mod
except ImportError:
    sys.path.insert(0, V3)
    import seed as _seed_mod

try:
    import adapter as _adapter_mod
except ImportError:
    import adapter as _adapter_mod

try:
    import crane_cpsat as _crane_mod
except ImportError:
    import crane_cpsat as _crane_mod

import utils as _utils

make_seed = _seed_mod.make_seed
global_eval = _seed_mod.global_eval
deserialize = _adapter_mod.deserialize
crane_repack_bay = _crane_mod.crane_repack_bay


# ---------------------------------------------------------------------------
# 인스턴스 로드: real_prob_*.json (현재 솔버 실제 해) 우선, 없으면 make_seed
# ---------------------------------------------------------------------------
def _load_instance_and_solution(prob_num: int):
    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path_v4 = os.path.join(V4, f"real_prob_{prob_num}.json")
    sol_path_v3 = os.path.join(V3, f"real_prob_{prob_num}.json")

    data = json.load(open(inst_path, encoding="utf-8"))

    if os.path.exists(sol_path_v4):
        sol = json.load(open(sol_path_v4, encoding="utf-8"))
        bays_placed = deserialize(data, sol, scale=2)
        source = "real_prob(v4)"
    elif os.path.exists(sol_path_v3):
        sol = json.load(open(sol_path_v3, encoding="utf-8"))
        bays_placed = deserialize(data, sol, scale=2)
        source = "real_prob(v3)"
    else:
        # fallback: make_seed (greedy, 정확성 낮음)
        bays_placed, data = make_seed(inst_path, scale=2)
        source = "make_seed"

    return data, bays_placed, source, inst_path


# ---------------------------------------------------------------------------
# co-presence 프로파일 (copresence_diag.py 재사용 패턴)
# ---------------------------------------------------------------------------
def _copresence_profile(placed_list: list):
    """placed_list: [{entry, exit, id, ...}]
    Returns: (n_profile list indexed by t-t_min, t_min)"""
    if not placed_list:
        return [], 0
    t_min = min(p["entry"] for p in placed_list)
    t_max = max(p["exit"] for p in placed_list)
    length = t_max - t_min + 1
    profile = [0] * length
    for p in placed_list:
        a = p["entry"] - t_min
        b = p["exit"] - t_min  # n_b(t) = entry <= t < exit
        for t in range(a, b):
            if 0 <= t < length:
                profile[t] += 1
    return profile, t_min


def _peak_clique_members(placed_list, profile, t_min):
    """피크 co-presence 시각에 겹치는 블록 id 집합."""
    if not profile:
        return [], 0, 0
    pk = max(profile)
    pk_t = profile.index(pk) + t_min
    members = [p for p in placed_list
               if p["entry"] <= pk_t < p["exit"]]
    return members, pk, pk_t


def _interval_overlap_count(p, placed_list):
    """p의 [entry, exit) 구간과 겹치는 블록 수 (자기 자신 제외)."""
    return sum(1 for q in placed_list
               if q["id"] != p["id"]
               and q["entry"] < p["exit"]
               and p["entry"] < q["exit"])


def _copresence_at_interval(placed_list, p_entry, p_exit):
    """p의 [entry,exit) 구간 동안 placed_list에 있는 블록 수 (평균 co-presence)."""
    if p_exit <= p_entry:
        return 0.0
    total = 0
    span = p_exit - p_entry
    for t in range(p_entry, p_exit):
        total += sum(1 for q in placed_list
                     if q["entry"] <= t < q["exit"])
    return total / span


# ---------------------------------------------------------------------------
# 베이스라인 구축: 각 베이에 intra-bay crane_repack_bay 1패스
# ---------------------------------------------------------------------------
def _build_baseline(data, bays_placed_raw, per_bay_time=20.0):
    """실제 해를 기반으로 각 베이에 crane_repack_bay (xyo 패스) 적용.
    never-worse by construction. global_eval로 기준값 확정."""
    bp = deepcopy(bays_placed_raw)
    n_bays = len(data["bays"])

    for j in range(n_bays):
        placed_j = bp.get(j, [])
        if not placed_j:
            continue
        t0 = time.monotonic()
        new_placed, status, wall, info = crane_repack_bay(
            data, j, placed_j, per_bay_time,
            n_xcand=5, n_ycand=0, n_ocand=0,
            window_tardy_only=True, num_workers=4)
        elapsed = time.monotonic() - t0
        if new_placed is not None:
            bp[j] = new_placed
            print(f"  [baseline] bay{j}: {len(placed_j)} blks, "
                  f"status={status}, wall={elapsed:.1f}s", flush=True)
        else:
            print(f"  [baseline] bay{j}: repack None ({status}), kept original",
                  flush=True)

    ev = global_eval(data, bp)
    return bp, ev


# ---------------------------------------------------------------------------
# 메인 크로스베이 이동 연산자
# ---------------------------------------------------------------------------
def _preferred_bay(data, bid):
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def _seed_record(data, bid, pb, dest_bay):
    """bpass._seed_into_bay 패턴: bid를 dest_bay 프레임으로 시드."""
    from gridmap import build_shape
    from shapely.affinity import translate as _translate

    orient = int(pb["orient"])
    sh = build_shape(bid, data["blocks"][bid], orient, scale=pb["sh"].scale)

    W = int(data["bays"][dest_bay]["width"])
    H = int(data["bays"][dest_bay]["height"])

    # x 범위
    x_lb = int(math.ceil(sh.min_x * -1 - 1e-9)) if hasattr(sh, 'min_x') else 0
    try:
        from xreopt_ref import _x_lb, _x_ub
        x = max(_x_lb(sh), min(_x_ub(sh, W), 0))
    except Exception:
        x = max(0, min(W - 1, 0))

    y_lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
    y_ub = max(y_lb, int(math.floor(H - sh.max_y + 1e-9)))
    y = max(y_lb, min(y_ub, 0))

    R = int(data["blocks"][bid].get("release_time", 0))
    P = int(round(pb["exit"] - pb["entry"]))
    if P <= 0:
        P = int(data["blocks"][bid].get("processing_time", 0))

    entry = R
    exit_t = entry + P
    world = {l: _translate(sh.layers[l].poly, xoff=x, yoff=y)
             for l in range(sh.n_layers)}

    return {
        "id": bid,
        "sh": sh,
        "x": int(x),
        "y": int(y),
        "orient": orient,
        "entry": int(entry),
        "exit": int(exit_t),
        "world": world,
    }


def _find_placed_record(bays_placed, bid):
    for j, placed in bays_placed.items():
        for p in placed:
            if p["id"] == bid:
                return j, p
    return None, None


def crossbay_z1_pass(data, bays_placed, total_time_s=150,
                     per_move_time=15.0, n_xcand=5,
                     max_candidates=8):
    """z1-타겟 크로스베이 이동 패스.

    Returns (best_bays_placed, log).
    """
    t_start = time.monotonic()
    deadline = t_start + total_time_s

    cur = deepcopy(bays_placed)
    base_ev = global_eval(data, cur)
    cur_obj = base_ev["obj"]
    cur_z1 = base_ev["z1"]

    log = {
        "base": base_ev,
        "moves_attempted": 0,
        "moves_accepted_move": 0,
        "moves_accepted_swap": 0,
        "moves_rejected_infeasible": 0,
        "moves_rejected_noimprove": 0,
        "moves_failed_solver": 0,
        "history": [],
    }

    n_bays = len(data["bays"])
    blocks = data["blocks"]

    iteration = 0
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        iteration += 1

        # -----------------------------------------------------------------------
        # Step 1: co-presence 프로파일 계산 → binding 베이 식별
        # -----------------------------------------------------------------------
        bay_profiles = {}
        bay_t_mins = {}
        for j in range(n_bays):
            pl = cur.get(j, [])
            prof, t_min = _copresence_profile(pl)
            bay_profiles[j] = prof
            bay_t_mins[j] = t_min

        bay_peaks = {}
        for j in range(n_bays):
            prof = bay_profiles[j]
            pk = max(prof) if prof else 0
            bay_peaks[j] = pk

        # binding 베이 = 피크가 가장 높은 베이
        binding_bay = max(range(n_bays), key=lambda j: bay_peaks[j])
        binding_peak = bay_peaks[binding_bay]

        if binding_peak <= 1:
            print(f"  [iter{iteration}] binding_bay={binding_bay} peak={binding_peak} <=1, 종료",
                  flush=True)
            break

        print(f"\n  [iter{iteration}] binding_bay={binding_bay} peak={binding_peak}, "
              f"cur_obj={cur_obj:,.0f} z1={cur_z1:,.0f}", flush=True)

        # -----------------------------------------------------------------------
        # Step 2: 피크 클리크 멤버 후보 정렬
        # -----------------------------------------------------------------------
        placed_binding = cur.get(binding_bay, [])
        prof_b = bay_profiles[binding_bay]
        t_min_b = bay_t_mins[binding_bay]
        members, pk, pk_t = _peak_clique_members(placed_binding, prof_b, t_min_b)

        # z1 기여 큰 순 정렬 (tardiness가 크거나, 피크 겹침 긴 것 우선)
        def _score(p):
            due = blocks[p["id"]].get("due_date", 0)
            tard = max(0, p["exit"] - due)
            overlap_dur = min(p["exit"], pk_t + 1) - max(p["entry"], pk_t)
            return (tard * 100 + max(0, overlap_dur))

        candidates_b = sorted(members, key=_score, reverse=True)[:max_candidates]

        # -----------------------------------------------------------------------
        # Step 3: MOVE 시도
        # -----------------------------------------------------------------------
        for pb in candidates_b:
            if time.monotonic() >= deadline:
                break

            bid = pb["id"]
            j, pb_live = _find_placed_record(cur, bid)
            if pb_live is None or j != binding_bay:
                continue  # 이미 이동됨

            # 도착 베이: bid의 [entry, exit) 구간 동안 co-presence 최소인 베이
            # (binding_bay 제외, 비어있어도 OK)
            def _dest_copres(dest_j):
                pl_dest = cur.get(dest_j, [])
                # 도착 베이의 b 구간 [entry,exit) 동안 현재 co-pres 수
                entry_b = pb_live["entry"]
                exit_b = pb_live["exit"]
                return sum(1 for q in pl_dest
                           if q["entry"] < exit_b and entry_b < q["exit"])

            dest_bays = [jj for jj in range(n_bays) if jj != binding_bay]
            if not dest_bays:
                continue

            dest_j = min(dest_bays, key=_dest_copres)
            dest_copres = _dest_copres(dest_j)

            # 이동이 binding 베이 피크를 낮출 수 있는지 (최소 확인)
            # 도착 베이가 이미 binding 베이보다 피크 높으면 넘어감
            if bay_peaks[dest_j] >= binding_peak:
                # swap도 의미 없을 수 있지만 일단 시도
                pass

            remaining = deadline - time.monotonic()
            if remaining <= 2.0:
                break

            per = min(per_move_time, remaining * 0.5)
            log["moves_attempted"] += 1

            # --- MOVE ---
            b_seed = _seed_record(data, bid, pb_live, dest_j)
            placed_dest_new = list(cur.get(dest_j, [])) + [b_seed]

            print(f"    MOVE bid={bid} bay{j}->bay{dest_j} "
                  f"(dest_copres={dest_copres}, budget={per:.1f}s)", flush=True)

            new_dest, status_d, wall_d, _ = crane_repack_bay(
                data, dest_j, placed_dest_new, per,
                n_xcand=n_xcand, n_ycand=0, n_ocand=0,
                free_ids={bid}, num_workers=4)

            if new_dest is None:
                log["moves_failed_solver"] += 1
                print(f"      solver fail ({status_d})", flush=True)
                log["history"].append({
                    "kind": "move", "bid": bid, "from": j, "to": dest_j,
                    "accepted": False, "reason": f"solver-{status_d}"})
                continue

            # 출발 베이에서 bid 제거 후 재패킹 (co-presence 완화 realize 핵심)
            placed_src_new = [p for p in cur[j] if p["id"] != bid]

            remaining2 = deadline - time.monotonic()
            per2 = min(per_move_time, remaining2 * 0.5)

            if placed_src_new and per2 > 2.0:
                # 출발 베이 재패킹: 모든 블록 자유 (crane 직렬화 해소)
                new_src, status_s, wall_s, _ = crane_repack_bay(
                    data, j, placed_src_new, per2,
                    n_xcand=3, n_ycand=0, n_ocand=0,
                    num_workers=4)
                if new_src is None:
                    new_src = placed_src_new
                    print(f"      src repack fail ({status_s}), kept", flush=True)
            else:
                new_src = placed_src_new

            trial = dict(cur)
            trial[j] = new_src
            trial[dest_j] = new_dest

            ev = global_eval(data, trial)
            delta = (ev["obj"] - cur_obj) if ev["obj"] is not None else None
            rec = {
                "kind": "move", "iter": iteration,
                "bid": bid, "from": j, "to": dest_j,
                "dest_copres": dest_copres,
                "obj_before": cur_obj, "obj_trial": ev["obj"],
                "z1_before": cur_z1, "z1_trial": ev.get("z1"),
                "delta": delta, "feasible": ev["feasible"],
            }

            if ev["feasible"] and ev["obj"] is not None and ev["obj"] < cur_obj - 1e-6:
                dz1 = (ev.get("z1") or 0) - (cur_z1 or 0)
                print(f"      ACCEPTED: Δobj={delta:+.0f} Δz1={dz1:+.0f}", flush=True)
                cur = trial
                cur_obj = ev["obj"]
                cur_z1 = ev.get("z1")
                rec["accepted"] = True
                rec["reason"] = "accepted"
                log["moves_accepted_move"] += 1
                improved = True
            else:
                reason = "infeasible" if not ev["feasible"] else "obj-not-improved"
                trial_obj_str = f"{ev['obj']:.0f}" if ev["obj"] is not None else "None"
                print(f"      REJECTED ({reason}): trial_obj={trial_obj_str} "
                      f"feasible={ev['feasible']}", flush=True)
                rec["accepted"] = False
                rec["reason"] = reason
                if not ev["feasible"]:
                    log["moves_rejected_infeasible"] += 1
                else:
                    log["moves_rejected_noimprove"] += 1
            log["history"].append(rec)

            if improved:
                break  # 개선 발견 → 다음 iteration으로

        if improved:
            continue

        # -----------------------------------------------------------------------
        # Step 4: SWAP 시도 (MOVE 실패 시)
        # -----------------------------------------------------------------------
        print(f"  [iter{iteration}] MOVE 개선 없음 → SWAP 시도", flush=True)

        for pb in candidates_b:
            if time.monotonic() >= deadline:
                break

            bid = pb["id"]
            j, pb_live = _find_placed_record(cur, bid)
            if pb_live is None or j != binding_bay:
                continue

            # swap 파트너: bid의 구간과 시간 안 겹치는 블록을 다른 베이에서
            entry_b = pb_live["entry"]
            exit_b = pb_live["exit"]

            for dest_j in range(n_bays):
                if dest_j == j or time.monotonic() >= deadline:
                    continue

                placed_dest = cur.get(dest_j, [])
                if not placed_dest:
                    continue

                # b 구간과 시간 비겹치는 파트너 c 선택 (부하 보존 목적)
                non_overlap = [
                    pc for pc in placed_dest
                    if pc["exit"] <= entry_b or pc["entry"] >= exit_b
                ]
                if not non_overlap:
                    # 겹쳐도 피크가 낮은 베이면 시도
                    non_overlap = placed_dest[:1]

                if not non_overlap:
                    continue

                # footprint area 기준 가장 가까운 파트너
                b_area = float(
                    (pb_live["sh"].max_x - pb_live["sh"].min_x) *
                    (pb_live["sh"].max_y - pb_live["sh"].min_y))
                pc = min(non_overlap,
                         key=lambda q: abs(
                             (q["sh"].max_x - q["sh"].min_x) *
                             (q["sh"].max_y - q["sh"].min_y) - b_area))
                cid = pc["id"]

                remaining = deadline - time.monotonic()
                if remaining <= 4.0:
                    break

                per = min(per_move_time, remaining * 0.4)
                log["moves_attempted"] += 1

                # c -> bay j 시드, b -> bay dest_j 시드
                c_seed = _seed_record(data, cid, pc, j)
                b_seed = _seed_record(data, bid, pb_live, dest_j)

                new_j_pre = [p for p in cur[j] if p["id"] != bid] + [c_seed]
                new_dest_pre = [p for p in placed_dest if p["id"] != cid] + [b_seed]

                print(f"    SWAP bid={bid}(bay{j}) <-> cid={cid}(bay{dest_j}) "
                      f"budget={per:.1f}s", flush=True)

                new_j, st_j, _, _ = crane_repack_bay(
                    data, j, new_j_pre, per / 2,
                    n_xcand=n_xcand, n_ycand=0, n_ocand=0,
                    free_ids={cid}, num_workers=4)
                if new_j is None:
                    log["moves_failed_solver"] += 1
                    print(f"      src swap repack fail ({st_j})", flush=True)
                    continue

                remaining2 = deadline - time.monotonic()
                if remaining2 <= 2.0:
                    break

                new_dest, st_d, _, _ = crane_repack_bay(
                    data, dest_j, new_dest_pre, min(per / 2, remaining2 * 0.8),
                    n_xcand=n_xcand, n_ycand=0, n_ocand=0,
                    free_ids={bid}, num_workers=4)
                if new_dest is None:
                    log["moves_failed_solver"] += 1
                    print(f"      dest swap repack fail ({st_d})", flush=True)
                    continue

                trial = dict(cur)
                trial[j] = new_j
                trial[dest_j] = new_dest

                ev = global_eval(data, trial)
                delta = (ev["obj"] - cur_obj) if ev["obj"] is not None else None
                rec = {
                    "kind": "swap", "iter": iteration,
                    "bid": bid, "cid": cid,
                    "from_b": j, "to_b": dest_j,
                    "obj_before": cur_obj, "obj_trial": ev["obj"],
                    "z1_before": cur_z1, "z1_trial": ev.get("z1"),
                    "delta": delta, "feasible": ev["feasible"],
                }

                if ev["feasible"] and ev["obj"] is not None and ev["obj"] < cur_obj - 1e-6:
                    dz1 = (ev.get("z1") or 0) - (cur_z1 or 0)
                    print(f"      SWAP ACCEPTED: Δobj={delta:+.0f} Δz1={dz1:+.0f}",
                          flush=True)
                    cur = trial
                    cur_obj = ev["obj"]
                    cur_z1 = ev.get("z1")
                    rec["accepted"] = True
                    rec["reason"] = "accepted"
                    log["moves_accepted_swap"] += 1
                    improved = True
                else:
                    reason = "infeasible" if not ev["feasible"] else "obj-not-improved"
                    print(f"      SWAP REJECTED ({reason})", flush=True)
                    rec["accepted"] = False
                    rec["reason"] = reason
                    if not ev["feasible"]:
                        log["moves_rejected_infeasible"] += 1
                    else:
                        log["moves_rejected_noimprove"] += 1
                log["history"].append(rec)

                if improved:
                    break

            if improved:
                break

    final_ev = global_eval(data, cur)
    log["final"] = final_ev
    log["wall"] = time.monotonic() - t_start
    return cur, log


# ---------------------------------------------------------------------------
# 단일 인스턴스 실험 진입점
# ---------------------------------------------------------------------------
def run_experiment(prob_num: int, total_time_s: float = 150.0,
                   baseline_time_per_bay: float = 15.0):
    print(f"\n{'='*70}", flush=True)
    print(f"prob_{prob_num}  budget={total_time_s}s", flush=True)
    print(f"{'='*70}", flush=True)

    t0 = time.monotonic()

    # 1) 로드
    data, bays_placed_raw, source, inst_path = _load_instance_and_solution(prob_num)
    n_bays = len(data["bays"])
    n_blocks = len(data["blocks"])
    w = data["weights"]
    print(f"  source={source}  bays={n_bays}  blocks={n_blocks}  "
          f"w1={w['w1']}  w2={w['w2']}  w3={w['w3']}", flush=True)

    # 2) 베이스라인 공식 평가 (raw)
    ev_raw = global_eval(data, bays_placed_raw)
    print(f"  RAW: feasible={ev_raw['feasible']} obj={ev_raw['obj']:,.0f} "
          f"z1={ev_raw['z1']:,.0f} z3={ev_raw['z3']:,.0f}", flush=True)

    # 3) 베이스라인 구축 (intra-bay repack)
    print(f"\n  [baseline repack] per-bay crane_repack ({baseline_time_per_bay}s each)",
          flush=True)
    elapsed_so_far = time.monotonic() - t0
    remaining_for_baseline = max(baseline_time_per_bay * n_bays,
                                 total_time_s * 0.3)
    bp, ev_base = _build_baseline(data, bays_placed_raw, baseline_time_per_bay)
    elapsed_base = time.monotonic() - t0
    print(f"  BASELINE: feasible={ev_base['feasible']} obj={ev_base['obj']:,.0f} "
          f"z1={ev_base['z1']:,.0f} z3={ev_base['z3']:,.0f} "
          f"(wall={elapsed_base:.1f}s)", flush=True)

    # 4) 크로스베이 이동 패스
    remaining = total_time_s - elapsed_base
    if remaining < 10.0:
        print(f"  남은 예산 {remaining:.1f}s < 10s, crossbay 패스 스킵", flush=True)
        return {
            "prob": prob_num,
            "baseline": ev_base,
            "crossbay": ev_base,
            "log": {"moves_attempted": 0, "history": []},
            "verdict": "SKIPPED (no budget)",
        }

    print(f"\n  [crossbay pass] budget={remaining:.1f}s", flush=True)
    bp_cb, log = crossbay_z1_pass(
        data, bp,
        total_time_s=remaining,
        per_move_time=min(20.0, remaining / 4),
        n_xcand=5,
        max_candidates=6)

    ev_cb = log["final"]
    total_wall = time.monotonic() - t0

    return {
        "prob": prob_num,
        "source": source,
        "n_bays": n_bays,
        "n_blocks": n_blocks,
        "w1": w["w1"], "w3": w["w3"],
        "raw": ev_raw,
        "baseline": ev_base,
        "crossbay": ev_cb,
        "log": log,
        "wall": total_wall,
    }


# ---------------------------------------------------------------------------
# 결과 요약 출력
# ---------------------------------------------------------------------------
def print_summary(results: list):
    print(f"\n{'='*90}", flush=True)
    print("[ z1-타겟 크로스베이 이동 A/B 결과 ]", flush=True)
    print(f"{'='*90}", flush=True)
    header = (f"{'prob':>6} | {'base_obj':>12} {'base_z1':>10} {'base_z3':>10} | "
              f"{'cb_obj':>12} {'cb_z1':>10} {'cb_z3':>10} | "
              f"{'Δobj':>10} {'Δz1':>8} | "
              f"{'mv_att':>6} {'mv_acc(M)':>9} {'mv_acc(S)':>9} {'mv_rej_inf':>10} {'mv_rej_no':>9}")
    print(header, flush=True)
    print("-" * 110, flush=True)

    any_accepted = False
    for r in results:
        if "error" in r:
            print(f"  prob_{r['prob']}: ERROR {r['error']}", flush=True)
            continue
        pb = r["prob"]
        bev = r["baseline"]
        cev = r["crossbay"]
        lg = r["log"]

        bobj = bev["obj"] or 0
        bz1 = bev["z1"] or 0
        bz3 = bev["z3"] or 0
        cobj = cev["obj"] or 0
        cz1 = cev["z1"] or 0
        cz3 = cev["z3"] or 0
        dobj = cobj - bobj
        dz1 = cz1 - bz1

        att = lg.get("moves_attempted", 0)
        acc_m = lg.get("moves_accepted_move", 0)
        acc_s = lg.get("moves_accepted_swap", 0)
        rej_inf = lg.get("moves_rejected_infeasible", 0)
        rej_no = lg.get("moves_rejected_noimprove", 0)

        if acc_m + acc_s > 0:
            any_accepted = True

        row = (f"{pb:>6} | {bobj:>12,.0f} {bz1:>10,.0f} {bz3:>10,.0f} | "
               f"{cobj:>12,.0f} {cz1:>10,.0f} {cz3:>10,.0f} | "
               f"{dobj:>+10,.0f} {dz1:>+8,.0f} | "
               f"{att:>6} {acc_m:>9} {acc_s:>9} {rej_inf:>10} {rej_no:>9}")
        print(row, flush=True)

    print(f"{'='*90}", flush=True)

    print("\n[ 채택 이동 상세 ]", flush=True)
    for r in results:
        if "error" in r or "log" not in r:
            continue
        accepted = [h for h in r["log"].get("history", []) if h.get("accepted")]
        if not accepted:
            continue
        print(f"\n  prob_{r['prob']}:", flush=True)
        for h in accepted:
            if h["kind"] == "move":
                print(f"    MOVE bid={h['bid']} bay{h['from']}->bay{h['to']} "
                      f"Δobj={h.get('delta', '?'):+.0f} "
                      f"z1: {h.get('z1_before', '?'):.0f}->{h.get('z1_trial', '?'):.0f}",
                      flush=True)
            else:
                print(f"    SWAP bid={h['bid']} cid={h.get('cid','?')} "
                      f"bay{h.get('from_b','?')}<->bay{h.get('to_b','?')} "
                      f"Δobj={h.get('delta', '?'):+.0f} "
                      f"z1: {h.get('z1_before', '?'):.0f}->{h.get('z1_trial', '?'):.0f}",
                      flush=True)

    print(f"\n{'='*90}", flush=True)
    print("[ 판정 ]", flush=True)
    if any_accepted:
        print("  → 채택된 이동 존재: z1-타겟 크로스베이 = 부분 작동 레버", flush=True)
        print("    (어느 인스턴스·얼마·z1 실제 감소 여부 위 표 참조)", flush=True)
    else:
        print("  → 채택 이동 0건: z1-타겟 크로스베이 = FALSIFIED", flush=True)
        print("    근거: 구조적 co-presence (has_slack=NO) 진단과 일치.", flush=True)
        print("    binding 베이 피크 시점에 다른 베이도 이미 포화 → 이동 후 obj 개선 없음.", flush=True)
    print(f"{'='*90}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="z1-타겟 크로스베이 이동 A/B 검증")
    parser.add_argument("--probs", nargs="+", type=int,
                        default=[27, 38, 40, 26],
                        help="대상 인스턴스 번호 (기본: 27 38 40 26)")
    parser.add_argument("--budget", type=float, default=150.0,
                        help="인스턴스당 총 시간 예산 (초, 기본 150)")
    parser.add_argument("--baseline-per-bay", type=float, default=12.0,
                        help="베이스라인 bay당 repack 시간 (초, 기본 12)")
    args = parser.parse_args()

    results = []
    for prob_num in args.probs:
        try:
            r = run_experiment(prob_num,
                               total_time_s=args.budget,
                               baseline_time_per_bay=args.baseline_per_bay)
        except Exception as e:
            import traceback
            lines = traceback.format_exc().splitlines()
            short = "\n".join(lines[-5:])
            print(f"\nprop_{prob_num} EXCEPTION:\n{short}", flush=True)
            r = {"prob": prob_num, "error": str(e)}
        results.append(r)

    print_summary(results)
