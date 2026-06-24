# 2026-06-01 대회 업데이트 반영 + baseline vs our 비교

> 대회 사이트(optichallenge.com)에서 baseline·문제예제·문제정의서가 갱신되어 워크스페이스에 반영하고, 신규 학습 인스턴스 20개로 공식 baseline과 우리 솔버를 비교한 기록.

## 1. 받아서 반영한 것 (출처: optichallenge.com SPA 번들의 자산 경로)

| 자산 | 신규 | 워크스페이스 반영 | 비고 |
|---|---|---|---|
| baseline | `baseline-latest-*.zip` (5/14자) | `baseline/baseline-latest.zip` + `baseline/ogc2026/` 갱신 | v1.0 zip·바뀐 파일 `.v1.0bak` 백업 |
| 문제예제 | `training-latest-*.zip` (5/31자) | `instances/train/prob_1~20.json` | **공식 학습 인스턴스 20개 (신규)** |
| 문제정의서 | `problem-statement-latest.pdf` (v1.1) | `docs/problem-statement-latest.pdf` | v1.0 보존 |

## 2. 변경점 (diff)

- **`utils.py`** (평가서버 채점기): `obj2 = math.floor(max(...))` — **Z2(작업부하 불균형) 목적값에 floor 적용**.
  - → `src/utils.py`를 신버전과 byte-identical로 동기화함 (구버전과 동일했음). 평가서버 미러이므로 동기화는 의무.
- **`baseline_greedy.py`**: 충돌검사를 *시간상 활성* 블록(`e_k > r_time`)에만 수행하도록 최적화 + `candidate_entries`도 `e > r_time` 필터.
  - 우리 `src/baseline_greedy.py`는 **구버전 fork + geom_kernel pre-check**라 이 최적화가 **없음**.
- **PDF v1.0→v1.1**: §4.2.1 "Using Other Programming Languages"(C/C++·Java17·.NET8 허용, 바이너리 zip 동봉) **정책 추가뿐**. 목적함수·제약·점수모델·결정변수 **불변**. (전체 diff: `docs/_pstmt_v1.0_vs_v1.1_diff.txt`)

## 3. 신규 인스턴스 규모

prob_1~20: **블록 100~300, 베이 2~5, 인스턴스별 weights**. (기존 gen 스위트는 n≤120 위주, example은 10블록.)
예: prob_1 w1=29091/w2=7/w3=200 → w1 압도적이라 **Z1(지연)이 점수를 지배**.

## 4. 비교 결과 (timelimit 60s, 신규 utils 채점)

- **공식 baseline(신규)**: feasible **14/20**, infeasible 6 (prob_6,9,14,17,19,20 — force-place가 경계초과/충돌/크레인 exit 위반 유발). 예산 준수(대부분 ≤60s, prob_20만 136s).
- **우리 솔버(src)**: feasible **4/20**(prob_1~4), 나머지 16 **hard-timeout(300s)**. 완료한 4개도 목적함수가 baseline 대비 **164×~~9만× 악화** (모두 ~10⁹).
  - 예: prob_1 ours 1.01e9 vs base 6.20e6 (−16,266%); prob_2 ours 9.79e8 vs base 1.08e4.
  - 실행시간: 25s 제한에 267s, 60s 제한에 140~229s → **예산 10배 폭주**.

결과물: `results/update_compare_20260601_120531/` (summary.json, report.html, report.md, viz/cmp_prob_1~4.png)

## 5. 근본 원인 ⚠️

1. `src/myalgorithm.py` (§baseline, L1426-1442)는 **"greedy가 알아서 일찍 끝난다"** 가정으로 greedy에 큰 budget(`hard_stop - now - check_cost`)을 넘김. 이 가정은 n≤120에서만 검증됨.
2. 우리 `src/baseline_greedy.py` fork는 신규 공식의 **active-block 충돌 최적화가 없어** congested 대형 인스턴스에서 Phase-1 구축이 폭주, 시간가드(블록 단위 체크)가 단일 블록의 거대한 후보탐색을 못 막음.
3. 폭주 후 force-place가 블록을 먼 미래에 배치 → tardiness 폭발 → 목적함수 ~10⁹.

**대회 영향: 현재 코드 그대로면 신규 대형 인스턴스에서 실서버 timeout = −1 (점수모델상 최악).**

## 6. 권고 (우선순위)

1. 신규 공식 `baseline_greedy.py`의 `active_in_bay`(`e_k > r_time`) 충돌 필터를 `src/baseline_greedy.py` fork + `geom_kernel` 경로에 **이식**.
2. greedy budget을 **실제로 강제**하는 Phase-1 시간가드 (후보탐색 내부 deadline 체크). L1428 가정 제거.
3. **스케일 회귀 테스트**(100~300블록 budget 준수 + feasibility)를 CI에 추가.
4. (완료) 신규 `utils.py` Z2 floor 동기화.

> 환경 메모: 로컬 실행은 conda `ogc2025`(py3.11, shapely2.1.2/numpy/numba/scipy/ortools 모두 보유)로 수행. `ogc2026` env는 미생성. geom_kernel은 numba 미사용 → 폭주는 환경이 아닌 알고리즘 문제로 확정.
