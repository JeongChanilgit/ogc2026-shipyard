# SESSION HANDOFF — 2026-06-18 (windowed packers / relayout polish 디벨롭 이어가기)

> **다음 세션은 이 파일 + `notes/research/assignment-z3-ledger.md` 를 먼저 읽어라.**
> 목표 = **windowed 재배치 폴리시를 파이프라인에 배선 + 더 디벨롭**. 코드는 이미 `src/relayout.py`에
> 있고 검증됐다(post-hoc −2.6M). 남은 건 (1) 배선, (2) 실제 leftover-wall 예산 검증, (3) 더 디벨롭.

---

## 0. 현재 확정 상태 (이번 세션 성과, src/에 박힘)

| 레버 | 결과 | 상태 | 코드 |
|---|---|---|---|
| **gassign-first PURE** | set2 z1 −95.7% | ✅ 채택 (default ON) | `myalgorithm.py:7869` `OGC_GASSIGN_FIRST` |
| **C3_MULT=2.0** (master z3-bias) | set2 271.93M, **경쟁자(279.82M) 7.89M 추월**; set1 −1.96%; never−1 | ✅ 채택 (default 2.0) | `gassign.py:368` `OGC_GASSIGN_C3_MULT` |

- gassign MIN_T=200 (`myalgorithm.py:7857`): gassign-first는 **T≥200에서만** 발동 (운영/set1은 legacy-first).
- **제출 zip 빌드+검증 완료**: `submissions/v-gassign-c3mult2-2026-06-18-*.zip` (0.30MB). 격리 추출 후
  import OK + gassign-first(prob_27@240 feasible 48.75M) + legacy-first(prob_1@120, prob_22@120 feasible).
  ⚠ caveat: 성과는 T≥200에서만 발동 — eval이 set2에 ≥200s 줘야 win 적용 (MIN_T 낮추는 건 미검증).

## 1. ★ 이어서 할 일 = windowed 재배치 폴리시 배선 + 디벨롭

### 1a. 무엇 / 왜
gassign 끝난 뒤 **각 tardy 베이를 더 강한 packer로 재배치**하는 최종 폴리시. 베이는 공간 독립 →
한 베이 z1↓ = instance obj↓ (z2/z3 불변). obj-gated → **never-worse**. cut 결합 없음(LBBD 밖) → **전이됨**
(per-bay-as-decoder가 전이 실패한 것과 정반대).
- **검증(post-hoc, full set2)**: 271.93M → **269.33M = −2.6M (−0.96%)**, never-worse. 경쟁자 리드 −7.89M→**−10.49M**.
  큰 승: prob_38 −1.85M, prob_31 −333K, prob_34 −243K. 대부분 +0(무해). (5문제 generous 예산땐 prob_26 −1.72M.)
- ★ **기존 perbay.improve를 이김** (C3_MULT 해는 perbay ON으로 생성됐는데 windowed가 −2.6M 더 깎음).

### 1b. 코드 (이미 있음)
- **`src/relayout.py`** (BUILT, COMPILE OK, IMPORT OK, 365줄): `polish(prob, sol, time_budget, per_bay=6.0,
  z1min=20)` + 옮겨온 packers(`solve_timing`, `pack_windowed_cpsat`, `_geo4`, `solve_subset_4d`,
  `pack_windowed_4d`) + `_parse_sol`/`_build_sol`. `polish`는 most-tardy 베이부터 best-of{windowed-fixed,
  windowed-4d}+B3, per-bay z1 개선 시만 swap.
- 원본 packers: `notes/research/perbay/packers_cpsat.py` (리서치용, src/relayout.py가 그 추출본).
- 벤치마크: `notes/research/perbay/bench.py` (per-bay z1 격리 측정 + 공식 checker 검증).

### 1c. 배선 (미완 — 다음 세션 첫 작업)
삽입 지점: `src/myalgorithm.py` perbay 직후(`:8085` `_seq_snap("3_perbay"...)` 부근) ~ **B4 serial-floor
직전**(`:8124` `if _env_on("OGC_SERIAL_FLOOR_SAFETY", True):`). 그 사이에 삽입:
```python
    # --- RELAYOUT polish (gated, final): tardy 베이를 windowed CP-SAT best-of + B3로
    # 재배치, obj-gated -> never-worse. post-hoc 검증 set2 -2.6M. (relayout.py)
    if _env_on("OGC_RELAYOUT", False):
        try:
            _elapsed = time.monotonic() - _t0
            _rl_budget = T - _elapsed - min(8.0, 0.05 * T)   # leftover wall - margin
            if _rl_budget >= 12.0:
                import relayout as _rl
                _sol_r = _rl.polish(prob_info, sol, _rl_budget)
                _ck_r = check_feasibility(prob_info, _sol_r)
                _ck_c = check_feasibility(prob_info, sol)
                if (_ck_r.get("feasible") and _ck_c.get("feasible")
                        and _ck_r["objective"] < _ck_c["objective"] - 1e-9):
                    sol = _sol_r
        except Exception:
            pass
```
- default **OFF** (`OGC_RELAYOUT`) — 검증 전까지 안전. 검증 통과하면 default ON 또는 제출시 env=1.

### 1d. 배선 후 반드시 검증 (이게 핵심 미해결)
**⚠ 검증(−2.6M)은 post-hoc, 베이당 넉넉한 예산(6s/bay)이었다. 파이프라인에선 gassign(0.8T)+box+perbay가
시간을 거의 다 써서 leftover가 빠듯하다.** 그래서:
1. 실제 파이프라인 예산에서 −2.6M이 유지되는가? (leftover가 작으면 1~2 베이만 폴리시 → 이득 축소)
2. CP-SAT 폴리시가 leftover를 넘겨 **−1(타임아웃)** 내지 않는가? (relayout 내부 deadline + 위 obj-gate로 막지만 full set2+set1 ALL40로 never-1 확인 필수)
- 검증 명령: `notes/_capture20_aff.py --instances SET2 --timelimit 240 --tag relayout_on --env OGC_RELAYOUT=1`
  → `summ_*` 로 z3_c3m2_set2(=OFF, 이미 있음) 대비 총 obj + feasible. **never-1 + 총 obj↓ 면 채택.**

### 1e. 더 디벨롭 아이디어 (windowed packers)
- **best-of 셀렉터**: windowed-fixed는 congested 큰 베이(prob_27 −8.4%), windowed-4d는 orient-중요 베이
  (prob_39 −24%)에서 이김. 베이 특성(블록수·orient 다양성)으로 어느 걸 쓸지 싸게 고르면 2배 시간 절약.
- **4D 모델 크기**: ncand=2가 캡. 큰 베이는 4d가 iter 굶음(prob_27 +1.2%) → 베이 크기로 ncand/K 적응.
- **속도**: 폴리시가 느림(CP-SAT 5~12s/bay). 베이당 budget·후보 줄이거나, fast 휴리스틱 1차 필터 후 CP-SAT.
- **window 슬라이싱 튜닝**: K(배치 크기). prob_27은 K=30이 최적(2484), K=45는 예산부족 악화.

## 2. 검증해서 기각된 것 (재시도 금지)
- **per-bay packer를 LBBD *decoder*로** (COVERT-race, ALNS in-loop): per-bay 개선이나 **instance 전이 실패**
  (cut 결합 + CP-SAT 노이즈). full set2 COVERT-race +0.41%(노이즈). → 폴리시는 *최종*(밖)에서만.
- **rho/depgroup 노브**: rho90 +0.5%(z3↓ z1↑ 나쁜 거래), dep05 −0.0%. z3는 master C3_MULT이 정답.
- **refiner A+B (사후 cross-bay 블록 이동)**: `src/refiner.py`. C3_MULT 위 0 이득(packing-locked). 보존만.
- **schedule-first** (면적-스케줄 먼저→위치): +9~50% (면적 proxy ≠ 기하).
- **랜덤 다중시작 decode**: +41%/infeasible.
- **iterative B2↔B3** (사용자 아이디어): **진동/미수렴** (B2가 entry=R 리셋 → 핑퐁). prob_39만 −4.4%.
  windowed 폴리시가 이 직관의 *작동판*.

## 3. 핵심 진단 (왜 C3_MULT이 답이었나)
set2 적자 전체가 **z3 과-스필**: 경쟁자 대비 z1 −11.1M(우리 승)/z3 +14.0M(우리 패)/net +2.82M(패).
master가 area-time 완화라 spill의 z1-이득을 과대평가 → 과-스필. **c3×2로 spill 억제 → z1 무손실 z3 −16% → 추월.**
사후 정제는 *배정*(z3)은 못 고침(packing-locked) → z3는 master에서, **z1만 사후 폴리시(relayout)로** 추가 회복.

## 4. 파일 맵 (이 작업 관련)
- 활성 솔버: `src/myalgorithm.py`(entry·legacy·B3), `src/gassign.py`(B1 master+C3_MULT), `src/fastfloor.py`
  (B2, F4=COVERT/F5=ATC 정렬 추가됨-미사용), `src/boxsolver.py`(box best-of), `src/perbay.py`(현 폴리시).
- **신규/실험**: `src/relayout.py`(폴리시, 배선 대기), `src/refiner.py`(기각된 cross-bay, 보존),
  `notes/research/perbay/packers_cpsat.py`(packer 연구 원본), `bench.py`(per-bay 벤치).
- 원장: `notes/research/assignment-z3-ledger.md`(C3_MULT·relayout 트랙, 가장 최신), `notes/research/perbay/
  LEDGER.md`(per-bay 탐색 C1~C16).
- 시각자료(생성물): `notes/algorithm-architecture-2026-06-18.html`, `notes/current-config-2026-06-18.html`,
  `notes/research/perbay/research-2026-06-18.html`.
- 실행: env python 직접 `C:/Users/peter/anaconda3/envs/ogc2025/python.exe` (conda run 크래시). 4-worker CP-SAT.
- 검증 하니스: `notes/_capture20_aff.py --instances SET2|ALL20|ALL40 --timelimit N --tag T --env K=V` (5슬롯×4코어).
- 경쟁자: `notes/competitor-2026-06-15.json` (utf-8, set2 포함; set2 official total 279,824,051).

## 5. 다음 세션 추천 순서
1. **배선** (1c 스니펫) → compile.
2. **never-1 검증**: ALL40 @T=240 `OGC_RELAYOUT=1`, feasible 40/40 + 총 obj 확인 (leftover 예산에서 −2.6M 유지되나).
3. 유지되면 → default ON + 제출 zip 재빌드. 축소되면 → 1e(속도/best-of셀렉터)로 폴리시 효율화 후 재검증.
4. 여유 있으면 1e의 windowed packer 디벨롭 (K/ncand 적응, fast 필터).
