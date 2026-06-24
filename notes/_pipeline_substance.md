# OGC 2026 솔버 파이프라인 — 단계별 설명 본문 (HTML 자료용 substance)

> 이 문서는 HTML 보고서의 "파이프라인 시퀀스 설명" 섹션 본문이다. 정확성 검증됨(코드 근거 file:line 포함).
> 작업 파일: `src/myalgorithm.py`(엔트리·후처리), `src/baseline_greedy.py`(greedy floor).

## 0. 문제와 목적함수 (한 줄 컨텍스트)
조선소 블록을 *베이·위치·방향·진입/퇴출 시각* 동시 결정. 3개 NP-hard 결합(2D 이형 폴리곤 패킹 + tardiness 스케줄링 + 베이배정).
목적함수 최소화:
```
obj = w1·Z1 + w2·Z2 + w3·Z3
  Z1 = Σ tardiness        (지연 — 가장 큰 가중, w1~17000~27000)
  Z2 = max workload imbalance  (베이 부하 불균형, w2~5~6)
  Z3 = Σ (S_max - S_chosen)    (선호도 이탈, w3~125~133)
```
**핵심 사실**: w1 ≫ w3 ≫ w2. 그래서 Z1(지연)이 obj를 지배 → 파이프라인은 Z1을 먼저·강하게 줄이고, 그다음 Z2/Z3(베이배정 함수)를 다듬는다. **모든 개선 단계는 `consider()` = full-objective 게이트를 통과해야 채택**되므로 어떤 단계도 obj를 악화시키지 않는다(objective-safe by construction).

## 0a. 시간 예산 (모든 단계가 공유)
- `T` = 인스턴스별 제한시간(평가서버 수분~30분, 로컬 스트레스테스트 100s).
- `done_by = t_start + 0.88·T`, `hard_stop = t_start + min(0.988·T, T-8)` (myalgorithm.py:4728,4745).
- 후처리는 단일 공유 deadline(`pp_deadline = hard_stop - 2·check_cost`)을 본다. cum_level만 잔여의 70% 캡(`OGC_CUMLEVEL_BUDGET_PCT`)을 먹고, **이후 단계들은 매번 잔여 시간 전체를 재흡수** → 앞 단계가 일찍 끝나면 절약분이 뒤 단계로 자동 흐른다.

---

## 1. FLOOR (baseline / greedy)  — 최초 실현가능해
**무엇**: 모든 블록을 베이에 배치해 *최초의 feasible 해*를 만든다. 이후 모든 단계의 출발점.
**어떻게**: `baseline_greedy.greedyalgorithm` — (Phase 1) EDD(Earliest Due Date) 순서로 블록을 돌며, 각 블록에 대해 선호도 내림차순 베이(`bay_order`)에서 `_placement_score = w1·tardiness + w2·imbalance + w3·preference`가 최소인 (베이,위치,방향)을 best-fit으로 선택, 크레인 수직접근(j≥k) 안전한 진입/퇴출 시각 부여. (Phase 2) repair로 잔여 충돌 해소.
**적응형 floor (핵심 레버)**: 큰 인스턴스·짧은 tl에선 full floor가 시간 초과 → fast-floor로 전환. 트리거 `_greedy_est = 1.2e-3·n² > 0.4·T` (myalgorithm.py:4904). fast-floor는 후보위치 폭 `pos_k`를 축소(기본 2). full floor(pos_k=0)는 ALNS 탐색 경로(아래 8)를 동반하며 긴 tl에서만 적합.
**RASTER 옵션(전처리 가속, OGC_FLOOR_RASTER)**: 크레인 충돌 체크를 Shapely 대신 **폴리곤을 정수셀로 보수적 래스터화**한 셀집합 교집합으로(baseline_greedy.py:416,496). 폴리곤 정밀 유지 + 빠름 → 같은 tl에 더 넓은 floor(pos_k=3) 가능 → 더 낮은 z1. 단 dense 구조라 선호도(z3) 희생 경향.
**무엇을 움직이나**: z1/z2/z3 **모두**의 출발값을 정한다. tardy 인스턴스의 floor z1이 높으면 뒤 단계들이 끌어내린다.

## 2. cum_level  — Z1 (재디코드)
**무엇**: 베이를 *재디코드*해 tardiness(Z1)를 낮춘다. 후처리에서 보통 시간을 가장 많이 쓰는 단계.
**어떻게**: 여러 (블록순서 × alpha 가중) 시드를 best-of로 시도(`OGC_CUMLEVEL_ORDERS`/`ALPHAS`). 각 시드마다 CP-SAT 누적(cumulative) 타이밍 + 크레인-안전 재배치(`_decode_bay`→`_find_slot_crane_safe`)로 베이를 다시 푼다. 시간이 많을수록 더 많은 시드 → 더 낮은 z1 (메모리: "z1 = time + breadth").
**무엇을 움직이나**: **Z1만**(베이 배정 유지). 시간 대비 z1 수율은 중간(저효율인 인스턴스도 있음).
**예산**: 잔여의 70% 캡(`_cl_dl`, myalgorithm.py:4180).

## 3. cpsat_timing  — Z1 (타이밍만)
**무엇**: 베이/위치/방향을 **고정**한 채 진입·퇴출 *시각만* CP-SAT로 최적화해 tardiness를 더 깎는다.
**어떻게**: pairwise 크레인 충돌 boolean을 precompute한 disjunctive 타이밍 모델을 CP-SAT로 푼다(`_cpsat_bay_timing_verified`).
**무엇을 움직이나**: **Z1만**. 배치가 고정이라 **Z2/Z3 불변**(myalgorithm.py:2454, "bay/x/y/orient fixed → Z2,Z3 unchanged"). 보통 작은 추가 개선.

## 4. bbox_pack (+ bbox_pack2)  — Z1 (재패킹)
**무엇**: 베이별로 블록 *위치*를 CP-SAT로 다시 패킹해 tardiness를 낮춘다.
**어떻게**: 각 베이에 잔여시간 비례 예산(`sub_budget`)을 주고 tardiness 최소화 CP-SAT(`_bbox_pack_bay`). 예산이 클수록 더 낮은 tardiness까지 푼다(myalgorithm.py:3443). bbox_pack2는 2차 패스.
**무엇을 움직이나**: 주로 **Z1**. 시간 대비 z1 수율이 매우 높은 단계(관측: prob_20 tl=100서 z1 171→65를 4초에).

## 5. crossbay_relocate  — Z1 (베이 간 이동)
**무엇**: **tardy 블록**을 다른 베이로 옮겨 tardiness를 낮춘다(배정 변경).
**어떻게**: tardy 블록을 순회하며 다른 베이로 relocate + 해당 베이 재패킹(bbox CP-SAT), `consider`(full-obj) 게이트로 채택. `max_moves`(기본 40)·deadline까지.
**무엇을 움직이나**: 주로 **Z1**(배정이 바뀌므로 Z2/Z3도 부수적으로 변하나, 선호도를 능동적으로 노리진 않음 — z3는 약간 악화되기도).

## 6. cheaper_steps / reschedule  — Z1 (결정적 마무리)
**무엇**: 고정 레이아웃에서 EDD left-shift로 진입시각을 당겨 잔여 tardiness를 제거(`_fixed_layout_reschedule`) + 값싼 소규모 이동.
**어떻게**: 결정적 단일 패스(시간 비례 아님 — deadline은 중단용, myalgorithm.py:2354). 한 번에 마무리 효과.
**무엇을 움직이나**: **Z1**의 잔여분(force-place로 멀리 밀린 블록 회수).

## 7. Front B  — Z2/Z3 (베이 재배정)
**무엇**: 블록을 **선호 베이로 재배정**해 선호도 이탈(Z3)과 부하 불균형(Z2)을 낮춘다. Z2/Z3의 *유일한 능동 레버*.
**어떻게**: 잔여 예산 동안(`while time < deadline`, myalgorithm.py:4483) 반복: ① relocate — 각 블록을 다른 베이로 옮길 때의 Z2/Z3를 closed-form `_assignment_proxy`로 평가, 개선 후보를 크레인-안전 `_insert_block_fixed_others`로 실현, `consider`(full-obj) 게이트. ② swap — relocate가 막히면 두 블록의 베이를 교환(꽉 찬 선호 베이에서 블록을 빼냄).
**무엇을 움직이나**: **Z2/Z3**. **full-obj 게이트라 Z1 악화 이동은 자동 거부**(w1 지배) → objective-safe. 단 "leftover budget" 단계라 앞의 Z1 단계들이 시간을 다 쓰면 거의 못 돈다(짧은 tl의 한계). dense floor에선 단일 이동이 Z1을 깨서 채택 실패하기도(Z3가 floor에 baked-in).

## 8. (긴 tl 전용) search / cpsat_seed / seeds_decode  — ALNS 탐색
**무엇**: full-floor 경로(긴 tl·작은 인스턴스)에서 도는 LNS/ALNS 기반 메타휴리스틱 탐색 + CP-SAT 시드 + 시드 디코드. 더 나은 전역 구조를 탐색.
**어떻게**: 파괴-재구성(destroy-repair) 반복, gated incumbent 갱신. fast-floor 경로(큰 인스턴스·짧은 tl)에선 시간이 없어 거의 0초(skip).
**무엇을 움직이나**: 전역적으로 obj(주로 Z1 구조). 짧은 tl 대형 인스턴스에선 비활성.

---

## 그래프로 봐야 할 핵심 (per-problem 트레이드오프)
- **Z1 궤적**: floor에서 시작해 cum_level→cpsat_timing→bbox_pack→crossbay→reschedule을 거치며 계단식 하강. 큰 인스턴스(prob_14/20)는 짧은 tl에서 floor z1이 높아 끝까지 못 내려가기도.
- **Z3 궤적**: 거의 floor에서 결정됨(베이 배정). Front B가 줄이려 하나 leftover 예산·dense 구조에 막히면 평평.
- **시간축**: cum_level이 시간을 가장 많이 먹음. 단계별 시간(STAGE_TIMING)과 z1 감소(STAGE_OBJ)를 겹쳐 보면 "어느 단계가 시간 대비 z1을 많이 줄이는지" 한눈에.
- **config 비교(default vs raster+posk3 @ tl=100)**: raster+posk3은 floor z1을 크게 낮춰(특히 prob_14/20) tl=100서 전 인스턴스 z1≤4 달성. 대가로 z1=0 인스턴스의 z3는 default보다 높음(선호도 희생).
