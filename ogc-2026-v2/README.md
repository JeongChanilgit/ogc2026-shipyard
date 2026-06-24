# OGC 2026 — v2 실험 (공간-시간 부피 패킹 재설계)

> 처음부터 다시 짜는 솔버 실험 공간. `../src/` 는 건드리지 않는다. 검증은 항상 공식 `../src/utils.py` 체커로.

## 0. 핵심 재설계 사상 (설계 토론 결론, 2026-06-19)

### 정사영(projection): 목적함수는 5변수 중 2변수에만 산다
블록당 결정 5개 `(j, x, y, o, ENTRY, EXIT)` 중:
- **Z2(부하불균형) = 배정 `j` 만의 함수.** `L_i`·`u_j` 상수. 기하·시간 무관.
- **Z3(선호) = 배정 `j` 만의 함수.**
- **Z1(지연) = EXIT 시각만의 함수.**
- **`(x, y, o)` = 목적함수에 기울기 0 → 순수 실현가능성 변수.**

⇒ 목적공간 `(배정, EXIT시각)` / 실현가능성공간 `(x, y, o, layer, ENTRY)` 로 직교 분해.
변수 축소 = 실현가능성공간을 쥐어짜고, 목적공간은 작으니 정확히 푼다.

### 진짜 천장 = 패킹 밀도 (면적이 아니라 **공간×시간×높이 부피**)
- 경쟁자 패킹 효율 ~95% vs 우리 ~80%. 이 15%p가 버려진 부피.
- 옛 AABB no-overlap은 이중 낭비: (1) 이형 폴리곤 **오목부**, (2) **수직 레이어**.
- tardiness 폭발 메커니즘 2종:
  - **A. 공간부족** — release 시각 R에 자리 없음 (prob_29: 116블록 중 89 delayed).
  - **B. 크레인 직렬화** — 면적 75~94% 비어도 `j≥k` 스택이 진입/퇴출을 순서 강제.

### 밀도 레버 3종 (비용이 다르다)
| 메커니즘 | 무엇 | 크레인 비용 |
|---|---|---|
| 수평 interlock | 같은 layer, 폴리곤 오목부 맞물림 (AABB→정확폴리곤) | 없음 |
| 수직 stacking | 같은 xy, 다른 layer, 같은 시간 | 있음 (laminar nesting) |
| 시간 재사용 | 같은 xy, 다른 시간 | 없음 |

### 크레인 = LIFO 컬럼 → laminar 시간 nesting
`j≥k`: 위에서만 넣고 위에서만 뺀다 ⇒ footprint 컬럼은 LIFO. B를 A 위에 쌓으면
`[B.entry, B.exit] ⊆ [A.entry, A.exit]` (위 블록 먼저 나감, 아래 블록 갇힘).
⇒ **스케줄-aware 스택 규칙: 바닥 = 마감 늦은 블록, 위 = 마감 빠른 블록.**
(부피 최대화 ≠ obj 최소화. 스택은 공간 벌지만 바닥 블록 Z1 비용 발생.)

### ⚠ 반증된 레버 — 방향 맞지만 *느리게* 하면 죽는다
`LCA·contact-area·finer-raster·exact box packer` = 전부 falsified.
이유: 밀도가 안 통해서가 **아니라 너무 느려서**(net-negative). 정답 = **빠른 밀도**.

## 1. 이번 실험 목표 — "빠른 밀도" 두 엔진 구현 + 배치

1. **정수격자 비트맵 (ROMA 침투맵)** — 폴리곤을 정수격자에 래스터화, 오버랩 = 비트마스크 AND = O(1). 격자 해상도까지 정확하면서 빠름. AABB→폴리곤을 공짜 속도로.
2. **Semi-discrete BLF** — NFP 없이 ~100배 빠른 bottom-left fill. "3D z선분 = crane 동형" → 같은 구조로 수직 stacking + 크레인 동시 처리.

## 2. 검증 게이트 (사용자 지시)
- feasibility 판정은 **공식 `../src/utils.py` 의 `check_feasibility`** 로만.
- 성능 판정은 **개별 z가 아니라 총 obj**, 검증은 **full set**(set1 또는 ALL40).
- `algorithm(prob_info, timelimit)` 시그니처 불변.

## 3. TODO / 진행
- [x] (recon) 인스턴스 스키마 + utils 기하/feasibility 인터페이스 확정
- [x] `gridmap.py` — 폴리곤 정수격자 래스터화 + 비트마스크 오버랩 + 크레인 suffix + `exact` 정확검증 모드
- [x] `blf.py` — semi-discrete bottom-left fill (방향 탐색 포함)
- [x] `viz.py` — 자기완결 Three.js 3D 뷰어 (시간 슬라이더 + Top/Front/Side/Iso)
- [x] `pack_experiment.py` — prob_29 형상진단 + AABB vs 폴리곤 max-fit + shapely 교차검증
- [ ] **temporal Z1 실험** — EDD + 시간재사용 패킹, AABB vs POLY 실제 tardiness 측정 (+ viz에 ENTER/EXIT)
- [ ] 패커 80→95% — compaction/search 를 폴리곤 기하 위에 얹기

## 3A. 측정 결과 (2026-06-19, prob_29)
- 형상: **오목 125/150(83%)**, 중앙값 footprint=bbox의 75%, overhang 블록 54개. → 그림판 interlock 실재.
- 혼잡 베이 0(50×23): 116/150 블록이 선호.
- **지표 정정**: 패킹 밀도 = **3D 부피활용**(z=블록 최대높이=2), 바닥면적 아님.
- max-fit 부피: AABB **58.4%** → 폴리곤(bl/area) **67.7%** (+9.2%p), shapely 무겹침 ✓. 속도 1.4s/구성, 4코어 포트폴리오 3.2s.
- **음성 결과**: "겹침 최대화" 스코어(overlap/vol)는 bottom-left와 동률(67.4 vs 67.7). 그리디 단일패스는 ~68% 부피서 평평. 레버=스코어 아니라 폴리곤 기하 사용 여부.
- **빈 32% = 대부분 빈 layer-1(z)**. 바닥 80%찬데 부피 68%. z 채우기 = overhang 스택 = **아래 블록 가둠(LIFO) → exit_top ≤ exit_bottom 일때만 합법** → 기하 아닌 **exit-순서(시간) 문제**.
- 결론: 정적 부피 68%=시간무시 상한. 남은 밀도+실제 Z1 = temporal 모델로.

## 3B. temporal 모델 결과 (2026-06-19, prob_29 bay 0)
- `temporal_pack.py`: 진입순서 입력 → event-driven 시뮬(시간재사용+크레인 LIFO+overhang스택+exit가드). 진입시각 **비감소 강제**(순서=시간순)로 충돌검사 정확. 커밋 전 **정확 크레인 검증**(_crane_ok)으로 래스터 누수 보정.
- **exit 제약(사용자)**: B를 A 위에 스택 = exit_B ≤ exit_A 일 때만 → 아래 블록 지각 안 됨, exit=entry+P 고정.
- 결과: 116블록 전부 배치, **FEASIBLE**(충돌 0, 크레인 위반 0), **Z1=7019** = 구조적 바닥(bay 0 과적, 웨이브당 14~21만 소화).
- 3-way viz: `show_three.py` → out/three_{1_aabb,2_poly,3_temporal}.html.
- 순서 탐색: `temporal_pack.search`(4코어 멀티스타트+페어스왑) 빌드됨. budget↑시 Z1↓ 여지.
- 다음: (1) 배정/toss 층(다른 베이로 분산→Z1 실제 완화, Z3 트레이드) (2) 공식 utils 전체 검증 (3) 순서탐색 강화.

## 3C. AABB vs POLY 목적함수 (2026-06-19, prob_29 전 베이, `z1_compare.py`/`static_all_bays.py`)
- 정적 밀도 모든 베이: bay0(50×23) 116선호 AABB14→POLY21, bay1(65×18) 24선호 22→**24/24**, bay2(32×22) 10선호 7→**10/10**. 폴리곤이 비과적 베이(1·2) 가짜혼잡 완전 제거. bay2는 폴리곤도 45%만 참(절반 비어=toss 여유 실재). 불균형: bay0 과적·bay2 텅.
- temporal Z1 (EDD 순서, 동일 스케줄러, 기하만): bay0 AABB **2611**→POLY **1565**(−40%), bay1·2 차이 0(비과적). 합 2636→1590.
- 목적함수(w1=13333,w2=3,w3=300, everyone-to-preferred Z3=0 Z2=11828): AABB **35.18M** → POLY **21.23M = −39.6%**, 전부 Z1.
- 교훈: density Z1이득은 **과적 베이에만**. **순서(EDD)가 더 큰 레버**(같은 폴리곤 area순서 7019 vs edd 1565). Z2는 w2=3이라 무의미=순수 Z1게임. 다음 레버=bay0→bay2 toss(Z3 트레이드).

## 3D. 배정/toss 층 (2026-06-19, `assign_search.py`)
- per-bay temporal 오라클 위에 배정 결정 그리디(병목 베이 지각블록 → 여유 베이 relocate, Δobj<0 채택, 후보평가 4코어 병렬).
- prob_29 파이프라인: AABB+preferred **35.18M** → POLY+preferred **21.23M**(밀도−40%) → **POLY+toss 2.73M**(재배정−87%). 합 **−92.2%**. Z1 2636→1590→**156**, 배정 bay0 116→86/bay1 24→40/bay2 10→24. Z2도 11828→4122(균형개선), Z3 0→2140(w3=300이라 비용 작음).
- toss가 최대 레버(과적은 density 아닌 재배정이 푼다). ⚠ 미수렴(MAX_MOVES=30, 여전히 개선중)·그리디·**내부검증만(공식 utils 미검증)**.
- 다음: (1) **공식 utils.check_feasibility 전체 검증**(이제 완전한 배정+스케줄 있어 가능) (2) 수렴까지(MAX_MOVES↑) (3) set1 확인 (4) swap/2-opt 강화.

## 4. 파일맵
- `gridmap.py` · `blf.py` · `experiment.py` · `out/` (실험 산출물)
- 읽기 허용: `../src/utils.py`(검증), `../src/geom_kernel.py`(기하 재사용 후보), `../instances/train/prob_29.json`, `../instances/example/example_B2_b10.json`
- **수정 금지**: `../src/*`, `../baseline/*`
