# 개선방향 2-에이전트 토론 — 공유 브리핑 (사실 자료)

> 이 문서는 토론 참가 두 에이전트가 **공통으로** 받는 사실 자료다. 너의 stance(공세파/수성파)는
> 별도 프롬프트로 받는다. 주장은 반드시 아래 사실 + 코드/결과 파일을 직접 확인해 근거를 댈 것.
> 일반론("LNS+SA+MIP 하이브리드 쓰자") 금지 — 이 문제·이 점수공식·이 결과에 특정된 주장만.

## 0. 한 줄 맥락
GPT가 `src/myalgorithm.py`를 개선했고, 우리가 신규 학습 인스턴스(prob_1~20, 100~300블록)로 평가했다.
이 토론의 목표: **다음 개선 방향**을 도출. (대회: OGC 2026, LG CNS × 대한산업공학회, 상금 2억)

## 1. 점수 모델 (가장 중요)
```
score(team, instance) = -1                if infeasible / timeout / crash
                      = R - nb             if feasible   (R=참가팀수, nb=엄밀히 더 나은 팀수)
total = Σ over all instances
```
- **−1은 치명적**: 한 인스턴스 −1 = 평균 R/2 손실. 1순위는 −1 회피.
- **동점 무해**: nb는 *엄밀히* 더 나은 팀 수 → 동점이면 nb 안 늘어남.
- 한 문제 압도보다 **모든 문제 안정적 feasible + 가능한 한 낮은 obj**가 유리.

## 2. 문제 본질
- 결정변수(블록당 동시): 베이 j, 위치(x,y) 정수, 방향 o, ENTRY 시각, EXIT 시각.
- 제약: 모든 블록 1베이 / ENTRY≥release / EXIT−ENTRY≥processing / 베이경계 / 동일층 충돌금지 /
  **크레인 수직접근(j≥k 규칙)** — feasibility의 진짜 난점(나중 배치 블록이 먼저 나갈 블록의 퇴출을 막으면 안 됨).
- 목적: `min w1·Z1 + w2·Z2 + w3·Z3`. Z1=Σtardiness, Z2=max workload imbalance(floor), Z3=Σ선호편차.

## 3. ★ 신규 인스턴스 전부 w1 압도 (결정적)
prob_1~20 모두 **w1 = 8,889 ~ 29,630** (수만), w2=4~10, w3=125~200.
→ **Z1(지연)이 목적함수를 전적으로 지배.** Z2/Z3는 사실상 tie-breaker.
→ 점수 개선 = "더 많이 feasible" + "Z1을 낮게". 규모: 블록 100~300, 베이 2~5.

## 4. ★ 평가 결과 (timelimit 60s, baseline vs ours, 동시 비교 1회)
results/eval_fresh_20260601_1500/summary.json (+ eval_report.html/md)

| inst | n×bay | baseline obj | ours obj | gap% | winner | ours wall |
|---|---|---|---|---|---|---|
| prob_1 | 100×2 | 3,465,502 | 5,200,982 | **+50.1** | BASE | 60.8s |
| prob_2 | 100×3 | 10,760 | 8,690 | −19.2 | OURS | 41.6s |
| prob_3 | 100×3 | 385,177 | 102,140 | −73.5 | OURS | 31.4s |
| prob_4 | 100×2 | 1,578,890 | 799,799 | −49.3 | OURS | 48.8s |
| prob_5 | 150×3 | 125,602 | 119,692 | −4.7 | OURS | 61.3s |
| prob_6 | 150×3 | INFEAS | 710,567,468 | — | OURS(단독feas) | 59.2s |
| prob_7 | 150×3 | 1,340,149 | 1,286,815 | −4.0 | OURS | 41.5s |
| prob_8 | 150×2 | 11,252 | 11,252 | 0.0 | TIE | 46.3s |
| prob_9 | 200×3 | 36,894,925 | 35,041,638 | −5.0 | OURS | 59.2s |
| prob_10 | 200×4 | 11,277,759 | 6,500,679 | −42.4 | OURS | 64.0s |
| prob_11 | 200×4 | 38,632,363 | 33,924,794 | −12.2 | OURS | 64.2s |
| prob_12 | 200×4 | 45,956,468 | 41,728,142 | −9.2 | OURS | 66.6s |
| prob_13 | 250×4 | INFEAS | 40,081,797 | — | OURS(단독feas) | 55.0s |
| prob_14 | 250×4 | 85,469,877 | 853,039,346 | **+898** | BASE | 64.3s |
| prob_15 | 250×4 | 38,844,956 | 655,233,956 | **+1587** | BASE | 59.5s |
| prob_16 | 250×4 | 12,341,022 | 376,606,220 | **+2952** | BASE | 61.4s |
| prob_17 | 300×4 | INFEAS | 459,444,934 | — | OURS(단독feas) | 51.5s |
| prob_18 | 300×4 | INFEAS | 51,355,805 | — | OURS(단독feas) | 63.3s |
| prob_19 | 300×4 | 33,810,970 | 685,018,517 | **+1926** | BASE | 51.4s |
| prob_20 | 300×5 | INFEAS | 1,200,200,411 | — | OURS(단독feas) | 54.0s |

**집계**: baseline feasible 15/20, ours feasible **20/20**, ours hard-timeout 0.
head-to-head: ours 승 14 · 무 1 · 패 5. **R−nb: baseline 16 / ours 35.**
직전 broken 상태(2026-06-01 12:05)는 ours feasible 4/20, 16개 timeout, R−nb ours −12 였음.

## 5. ★ 타이밍 절벽 / 불안정 (격리 vs 경쟁)
같은 코드·같은 60s 인데 실행 조건으로 결과가 수~수십 배 변함:
- **prob_16**: 격리 단독 실행 **12,341,022**(=baseline와 동일!) vs 스위트(동시4잡) **376,606,220** → 30×.
- **prob_14**: 14:15 실행 **80,687,595** vs 본 실행/격리 **853,039,346** → 10×. (격리에서도 나쁨 = 순수 비결정)
- **prob_1**: 격리 6,451,895 vs 스위트 5,200,982 — 둘 다 baseline 3.47M보다 나쁨(진짜 품질 격차).
- 원인: greedy Phase-1이 시간 게이트를 넘으면 repair가 수십 블록을 먼 미래 시각에 force-place
  → Z1 폭발(prob_14 Z1=47,922 → w1·Z1≈8.5억). CPU 속도/경쟁에 좌우 = 절벽.
- (정밀 비교표는 eval_report.html "suite vs isolated" 섹션 / isolated_losses.jsonl)

## 6. ★ 시간제한 초과 (−1 위험)
본 실행에서 60s 제한을 넘긴 인스턴스: prob_1 60.8, prob_5 61.3, prob_10 64.0, prob_11 64.2,
prob_12 66.6, prob_14 64.3, prob_18 63.3 (s). 격리 prob_14는 **67.5s**, prob_1 60.5s.
예산 가드는 greedy에 *넘기는* budget만 제한, greedy Phase-1+repair 자체는 강제 못 함.
**엄격한 hard-timelimit 서버라면 이 초과분이 그대로 −1.** (단, 실서버 timelimit은 인스턴스별 수분~30분으로
60s보다 넉넉 — 그래도 절대 강제 종료 마진은 필요.)

## 7. ★ 코드 구조 사실 (직접 확인 권장: src/myalgorithm.py)
- 기본 플래그(OGC_SEARCH_AFTER_BASELINE=off)에서, baseline greedy가 feasible이고 trivial floor보다
  나으면 알고리즘은 **즉시 반환**: `verified_greedy_floor`(L1771) 또는 n≤150이면 `_postprocess_verified_solution`
  후 `postprocess`(L1769). → **하류 ALNS/CP-SAT/assignment hill-climb(L1792~2097)은 일반 경로에서 비활성(dead).**
- 즉 현재 제출물 ≈ **"스케일-예산 baseline greedy fork (+ n≤150 단일이동 postprocess)"**. 정교한 메타휴리스틱은 잠들어 있음.
- GPT가 고친 것: ① `baseline_greedy.py` fork에 active-block 충돌필터(`e_k>r_time`) 이식 + `last_result` 노출,
  ② 형상별 greedy budget 가드(L1704~1724, `skip_greedy_floor` 등), ③ `_postprocess_verified_solution`(L1419, n≤150).
- 안전장치: 모든 경로 floor+gate(check_feasibility) → 개선 실패해도 검증된 floor로 폴백, 설계상 −1 안 남
  (단, 위 6의 wall-clock 초과는 별개 위험).

## 8. 제약 (개선안은 이걸 지켜야 함)
- 평가서버: 4 CPU, 16GB, **인터넷 차단**, GPU 없음. zip ≤15MB, 루트에 myalgorithm.py.
- `src/utils.py`, `baseline/` 수정 금지. `algorithm(prob_info, timelimit)->dict` 시그니처 불변.
- 가용 라이브러리: numpy/scipy/numba/shapely/ortools(CP-SAT) 모두 있음(ogc2025 env 기준).

## 9. 토론 산출 요구
너의 stance에서 **구체적·검증가능한 개선 방향 3~5개**(각각: 무엇을·왜 이 결과가 그걸 가리키는지·
예상 효과·리스크·구현난이도). 상대 주장을 읽으면 **공격**하고, 마지막에 **수정된 입장 + 양보점 + 끝까지 고수점**.
