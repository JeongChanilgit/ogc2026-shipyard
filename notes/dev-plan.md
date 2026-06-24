# OGC 2026 개발 명세 (v2) — `/goal` 실행용

> 작성 2026-05-29. 입력: 공식 문제정의서 v1.0(`docs/_pdf_text_extract.txt`) 재감사 + `notes/strategy.md` + 현재 `src/myalgorithm.py`(v1, 구현·검증 완료).
> 이 문서는 **`/goal` 이 읽고 코드를 완성하기 위한 단일 진실원본(SSOT)** 이다. 각 마일스톤은 독립 실행 가능하고 **명확한 수용기준**을 가진다. §4 불변식은 절대 위반 금지.

---

## 0. 한 줄 요약

v1(분해 골격 + 배정-레벨 hill-climb)은 **이미 feasible·베이스라인 우위**를 달성했다. v2의 목표는 **로컬 검증 공백을 먼저 메우고**(M0: 인스턴스 생성기+벤치), 그 위에서 **대형/고밀도/w1-지배 인스턴스에서도 타임아웃 0 + 목적값 추가 개선**을 달성하는 것이다.

---

## 1. 스펙 재감사 결론 (2026-05-29) — 전략에 반영됨

세 문서(`implementation.html`, `strategy.md`, `strategy-research.html`)를 공식 정의서와 대조한 결과:

### 1.1 정정된 오류 (1건, 실질적)
- **❌ → ✅ 상용 솔버 가정:** 기존 문서는 *"Gurobi/Xpress 팀은 firejail 라이선스 실패로 스스로 −1"* 이라 적었다. **틀렸다.** 공식 정의서 §4.1: 운영위가 **Gurobi 13.0.2·Xpress 9.8.1 을 평가서버에 정식 제공**(Gurobi·FICO 후원)하며 conda env 에 `gurobipy`·`xpress` 가 포함된다. → 상용 솔버 팀은 정상적으로 feasible·고품질 해를 낸다.
  - **전략 함의:** 우리의 솔버-회피는 *"안 돈다"* 가 아니라 **의식적 선택** — (a) **기술보고서 novelty 가점**(정의서 §3.3 이 명시적으로 "novel ideas or theoretical innovations would be appreciated, even if they do not fully translate into algorithmic performance" 라고 보상), (b) **솔버 라이선스/네트워크 변수 제거(견고성)**, (c) **비정형 패킹은 MIP 가 원래 약한 영역**.
  - **가장 중요한 결과:** "항상 feasible" 은 **필요조건일 뿐 충분조건이 아니다.** 강한 라이벌을 **목적값(랭크 `R−nb`)으로 이겨야** 한다 → 메타휴리스틱 **품질** 요구가 높아진다. (이미 세 문서에 정정 반영.)

### 1.2 검증된 사실 (문제 이해는 정확 — 그대로 신뢰 가능)
- **목적함수** `min w1·Z1 + w2·Z2 + w3·Z3` — `utils.py:1394–1421` 및 정의서와 **정확히 일치**.
  - `Z1 = Σ max(0, EXIT_i − D_i)` (총 지연). [utils.py:1402]
  - `Z2 = max_{j1≠j2} |u_j1·Σ_{i∈N(j1)} L_i − u_j2·Σ_{i∈N(j2)} L_i|`, `u_j = (Σ_k W_k·H_k / m) / (W_j·H_j)` = 평균베이면적/베이면적, `L_i` = workload. [utils.py:1395,1407–1419]
  - `Z3 = Σ_j Σ_{i∈N(j)} (S_i^max − S_ij)`, `S_i^max = max_j S_ij`. 가장 선호되는 베이에 다 넣으면 Z3=0. [utils.py:1396,1404–1405]
- **구조적 주춧돌 (분해의 근거):** Z2·Z3 는 **배정 벡터의 순수 함수**(위치/방향/시각 무관), Z1 만 기하·시각에 결합, feasibility 는 **베이별 독립**. → v1 의 분해·캐시·(미래)병렬이 모두 정당.
- **크레인 제약 (정확):** 블록 i1 의 ENTRY/EXIT 가 feasible ⇔ 모든 `l1 ≤ l2` 에서 `C(i1,l1,…,i2,l2,…)=0` (i2 ∈ N(t,j)\{i1}). "조작 블록의 레이어는 *같은 레벨 이상*의 다른 블록 레이어와 충돌 없어야". suffix-OR 마스크 `U[L]=(레벨 ≥ L footprint OR)` 가 이 규칙 그 자체. (CLAUDE.md 의 `j≥k` 라벨은 같은 규칙의 모호한 별칭일 뿐 — v2 코드/문서는 **`l1 ≤ l2`** 표기로 통일.)
- **점수:** infeasible/timeout/crash = **−1**; feasible = **R − nb** (R=평가팀수, nb=엄밀히 더 나은 팀수, **동점=만점**). 정의서 §3.3 일치.
- **서버:** AMD Ryzen Threadripper PRO 9955WX, Ubuntu 24.04, **≤4코어(400%)·≤16GB·인터넷 차단(firejail)·부모디렉토리 접근 불가·GPU 없음·cpulimit**. 시간제한 인스턴스별 상이(수 분~30분 **벽시계**, 대회 종료 후 공개). Python 3.12, ortools 9.15.6755, shapely 2.1.2.
- **제출:** zip 루트에 `myalgorithm.py`(서브폴더 X), ≤15MB, 등록 이메일로 `submission@optichallenge.com`, **수락 후 12h 쿨다운**(제출 횟수 무제한), utils.py 포함시 서버가 덮어씀.
- **출력 스키마:** `{"operations": {date_str: [op,…]}}`, 같은 날 **EXIT 가 ENTRY 보다 먼저**, x·y 정수(서버가 반올림). 인덱스 0-based(솔루션). ENTRY op = `{type,block_id,bay_id,x,y,orient_idx}`, EXIT op = `{type,block_id,bay_id}`.
- **예시 가중치:** `example_B2_b10.json` 은 `w1=2667,w2=7,w3=20` (정의서 본문의 예시 `26667/10/300` 과 다르나 **둘 다 정상** — 인스턴스마다 다름).

> ✅ **결론: 문제 이해 자체에는 실질 오류가 없었고(목적·제약·점수·서버·출력 전부 정확), 단 1건의 경쟁-프레이밍 오류만 정정했다.** 따라서 분해 아키텍처는 유효하며, 아래 개발 계획대로 진행한다.

---

## 2. 현재 상태 (v1 = 출발 기준선)

- **파일:** `src/myalgorithm.py` 단일 파일. `from utils import …`, `from baseline_greedy import …` (bare import).
- **핵심 함수:** `_feasible_bays`, `_fits_bay`, `_force_in_bay`, `_decode_bay`, `_orderings`, `_bay_tardiness`, `_Decoder(.decode, 캐시 (bay,frozenset(ids)))`, `_objective`(utils 공식 복제), `_cpsat_assignment`(OR-Tools, 시간상자·try/except), `_decode_assignment`, `_obj_of_results`, `_local_search`(shift hill-climb, 닿은 2베이만 재디코드), `_trivial_solution`, `algorithm`(오케스트레이터).
- **측정:** `example_B2_b10.json` 에서 baseline 1,055.73 → **ours 1,022.70** (feasible stage 5, Z1=0, Z2 19.40→14.67, Z3 46). 스모크 3/3 (81s). 타임가드 0.85 준수.
- **검증 공백(핵심 리스크):** **로컬 인스턴스가 example 1개뿐.** 대형·고밀도·w1-지배 인스턴스에서의 패킹 throughput·타임아웃·품질은 **미측정**. → M0 가 최우선인 이유.

---

## 3. v2 목표 (측정 가능)

1. **feasible율 100% 유지** — 생성된 전체 인스턴스 스위트에서 한 개도 −1 없음.
2. **타임아웃 0** — 모든 인스턴스가 `timelimit×0.85` 안에 탐색 종료 + 게이트 통과.
3. **목적값 개선** — 스위트 평균에서 v1 대비 의미있는 하락(특히 Z1·Z2). 베이스라인 대비 **절대 후퇴 없음**(불변식).
4. **대형 인스턴스 견고성** — n 큰·고밀도에서도 graceful degradation 으로 feasible 유지.

---

## 4. 불변식 (절대 위반 금지 — 모든 마일스톤 공통)

1. **시그니처 고정:** `def algorithm(prob_info: dict, timelimit: float = 60) -> dict:` 변경·제거 금지.
2. **수정 금지 영역:** `src/utils.py`(서버가 덮어씀), `baseline/` 폴더. 읽기만.
3. **반환 전 게이트:** 모든 반환 해는 `utils.check_feasibility` PASS. 실패하면 직전 feasible incumbent 반환.
4. **best-feasible 절대 유실 금지:** baseline 후보를 항상 평가에 포함 → 결과 ≥ baseline 품질.
5. **외부 네트워크 0 · 상용 솔버 0:** 인터넷 호출 절대 금지. OR-Tools(CP-SAT)만 *옵션*, 없거나 실패해도 휴리스틱으로 진행. Gurobi/Xpress 사용 안 함(의식적).
6. **타임가드:** `time.monotonic()` 기준 `timelimit×0.85` 에 탐색 중단, 남은 15%로 조립+`check_feasibility`. 벽시계 초과 = 서버 타임아웃 = −1.
7. **전체 try/except:** CP-SAT·디코더·탐색·병렬 각각 격리. 어디서 터져도 확보한 incumbent 반환. 크래시 0.
8. **import 규칙:** zip 루트 평탄화(아래 §5.1) 때문에 **bare import 만**(`import packing` O, `from .packing import` X). `__init__.py` 만들지 말 것(빌드시 제외됨). 새 헬퍼는 `src/` 직속.
9. **결정성:** `random.seed`/`np.random` 고정 시드 유지(현재 20260529). 재현성 보장.

---

## 5. 모듈 / 인터페이스 명세

### 5.1 제출·실행 메커니즘 (확정 사실)
- `tools/build_submission.py` 는 `src/**.py` 전체를 **zip 루트로 평탄화**(`utils.py`·`__init__.py`·banned ext 제외, `baseline_greedy.py` 는 **포함**). → `src/` 에 둔 새 모듈은 zip 루트에 `<name>.py` 로 들어가 **bare import** 가능.
- `tools/run_local.py` 는 `sys.path.insert(0, src/)` 후 `from myalgorithm import algorithm` 호출. 로컬에서도 bare import 동작.
- ⇒ **모듈 분리는 제출 안전.** 단 §4.8 import 규칙 준수.

### 5.2 제안 파일 레이아웃 (M1 에서 분리)
```
src/
  myalgorithm.py   # 엔트리 + 오케스트레이터 (algorithm()만 public)
  decode.py        # Layer 2: per-bay 디코더 (현 _decode_bay/_Decoder 이전)
  assign.py        # Layer 1: 배정 (CP-SAT + 휴리스틱, Z2/Z3 closed-form)
  search.py        # 배정-레벨 ALNS (shift/swap/destroy-repair)
  geom_kernel.py   # [M2] suffix-OR 크레인 마스크 + raster 충돌 (NumPy)
  regime.py        # [M6] 레짐 라우팅
  baseline_greedy.py  # (기존, 수정 금지 아님이나 건드릴 이유 없음)
  utils.py            # (수정 금지, 빌드시 제외)
```
> 분리는 **리팩터(M1)** 로만 하고 동작은 불변. 분리 전(v1)에도 단일 파일로 제출 가능 — 모듈화는 가독성·테스트용이며 필수는 아님. /goal 판단으로 단일 파일 유지도 허용(단 함수 경계는 아래대로).

### 5.3 데이터 계약 (정확)
- **입력 `prob_info`:** `{"name": str, "bays": [{"width":int,"height":int}], "blocks": [{"release_time":int,"due_date":int,"processing_time":int,"workload":int,"bay_preferences":[int](베이당 1개, 합=100),"shape":[{"orientation":int,"layers":[[[x,y],…],…]}](길이 8)}], "weights": {"w1":int,"w2":int,"w3":int}}`. layer 0 첫 정점은 reference point `[0.0,0.0]`, 레이어는 low→high 순.
- **출력 `solution`:** §1.2 출력 스키마.
- **내부 표현:** 배정 = `assign: list[int]` (길이 n, `assign[i]` = 블록 i 의 bay_id). per-bay 디코드 결과 = `{block_id: (x,y,orient_idx,entry,exit)}`. 목적 평가는 `_objective(assign, decode_results, prob_info)` → `(objective, Z1, Z2, Z3)`.

### 5.4 핵심 함수 시그니처 (분리시 유지/명문화)
```python
# decode.py
def decode_bay(bay_idx, block_ids, prob_info, *, order="edd") -> dict | None
    # 한 베이의 블록집합 → 크레인-feasible 배치 {bid:(x,y,o,entry,exit)} / 실패시 None(상위가 force fallback)
def force_in_bay(bay_idx, block_ids, prob_info) -> dict   # 빈-시간창 force-place, 항상 성공(defer-not-fail)

# assign.py
def feasible_bays(prob_info) -> list[set[int]]            # 블록별 들어갈 수 있는 베이 집합(필요조건 필터)
def cpsat_assignment(prob_info, time_budget) -> list[int] | None   # Z2/Z3 균형 배정 1개, 시간상자, 실패 None
def heuristic_seeds(prob_info) -> list[list[int]]         # baseline·최선호·균형 등 시드 배정들

# search.py
def local_search(assign, decoder, prob_info, deadline) -> tuple[list[int], dict]
    # 배정-레벨 탐색. deadline=time.monotonic() 절대시각. best-feasible 반환.

# geom_kernel.py  [M2]
class CraneMask:   # 베이별 suffix-OR 비트마스크, ENTRY/EXIT 증분 갱신, l1<=l2 검사 O(layers)
    def can_place(self, block, x, y, orient) -> bool
    def add(self, block, x, y, orient): ...
    def remove(self, block): ...
```

---

## 6. 마일스톤 (의존순 — 각 수용기준 충족해야 다음 진행)

### M0 — 인스턴스 생성기 + 벤치 하니스 ★최우선 (검증 공백 해소, 다른 모든 M의 전제)
- **`tools/gen_instance.py`** — 파라미터로 스키마-유효 인스턴스 생성.
  - 인자: `--n`(블록수) `--m`(베이수) `--density`(패킹 밀도, 베이면적 대비 블록면적 합 비율) `--regime`(`w1|w2|w3` 중 지배항) `--tightness`(due−release 여유; 작을수록 빡빡) `--max-layers` `--seed` `--out`.
  - 출력: `prob_info` 스키마 그대로. bay_preferences 는 합=100 정수, 모든 time 값 정수, shape 는 비정형 폴리곤(직사각+노치 정도면 충분, layer0[0]=[0,0]).
  - **수용기준:** 생성한 인스턴스 전부에서 `baseline_greedy.greedyalgorithm` 이 **feasible** 해를 낸다(=구조적으로 풀 수 있는 인스턴스). example 과 동일 키 구조. `check_feasibility` 가 baseline 해를 PASS.
- **`tools/bench.py`** — 인스턴스 디렉토리 × {baseline, ours} 실행 → 표.
  - 출력: 인스턴스별 `feasible, objective, Z1, Z2, Z3, elapsed, timelimit` 을 baseline vs ours 로 나란히 CSV + markdown 요약(평균 개선율, feasible율, 타임아웃 건수).
  - **수용기준:** `example_B2_b10.json` 에서 v1 수치(1022.70 vs 1055.73, feasible) 재현.
- **인스턴스 스위트 생성:** `instances/gen/` 에 고정 시드로 최소 **15개** — {small n≈10, mid n≈40, large n≈120} × {loose, tight 패킹} × {w1-dom, w2-dom, w3-dom} 조합 대표. 커밋(작으면) 또는 생성 스크립트 보존.
- **산출:** `python tools/bench.py instances/gen --timelimit 60` 한 줄로 전체 회귀 가능.

### M1 — 모듈 분리 (리팩터, 동작 불변)
- v1 함수들을 §5.2 레이아웃으로 이동(또는 단일 파일 유지하되 경계 명문화). public 은 `algorithm` 만.
- **수용기준:** M0 벤치 결과가 분리 전후 **비트 동일**(목적값·feasible·ops 동일). 스모크 3/3. import 규칙(§4.8) 준수 — `python tools/build_submission.py --tag v1-refactor-check` 가 myalgorithm.py 루트 + 헬퍼 동봉 zip 생성하고 ≤15MB.

### M2 — 기하 커널 `geom_kernel.py` (suffix-OR + raster, NumPy)
- 크레인 feasibility 를 `l1 ≤ l2` suffix-OR 비트마스크로, 동일층 충돌을 정수 raster AND 로. ENTRY/EXIT 증분 갱신.
- 디코더(decode.py)가 베이스라인 Shapely 검사 대신(또는 사전필터로) 이 커널을 쓰도록 교체. **단 베이스라인 프리미티브는 폴백으로 유지**(검증된 안전망).
- **수용기준:** (a) example 결과 **불변**(feasible·목적값 동일), (b) large 인스턴스에서 디코드 throughput 측정상 향상(bench elapsed ↓ 또는 동일 시간 내 탐색 반복수 ↑), (c) 커널 결과와 `check_feasibility` 가 모든 스위트 인스턴스에서 **일치**(불일치 0 — 회귀 테스트로 박제).

### M3 — ALNS 강화 (swap + 다중블록 destroy/repair + SA 수용)
- 현 단일 shift 이동에 **swap(두 블록 베이 교환)**, **다중블록 destroy→repair(worst-tardiness/related-by-bay removal → ATCS 재삽입)**, **SA 식 악화 수용** 추가. 여전히 **배정 레벨**에서만(픽셀 탐색 금지), 닿은 베이만 재디코드.
- **수용기준:** 스위트 평균 목적값 v1 대비 개선(특히 w1·w2-dom 레짐), **feasible율 100% 유지**, 타임아웃 0. 작은 인스턴스 수렴 안정성(여러 timelimit 에서 동일/단조 개선).

### M4 — no-good cut 루프 (봉합선 완성)
- Layer 2 가 "베이 j 는 블록셋 B 동시수용 불가" / "i 가 due≫ 늦게 EXIT" **인증서** 발행 → Layer 1(assign) 에 no-good cut 주입·**증분 재해결**(Z2/Z3 closed-form 이라 기하 재계산 없음). destroy 가 overflow 블록을 eject, repair 가 cut 반영 재배정.
- **수용기준:** 고밀도 인스턴스에서 **defer(force-place) 건수 감소 → Z1 개선**. feasible율 100%. cut 루프가 large 인스턴스에서도 타임가드 내 종료.

### M5 — 4코어 병렬
- 베이별 독립 디코드를 `multiprocessing` 으로, 또는 독립 시드 GRASP 재시작 후 best 채택. **피클 안전 확인 필수**(prob_info·결과 직렬화). 실패시 단일프로세스 자동 폴백.
- **수용기준:** 동일 벽시계에서 탐색 반복수 증가(bench), 결과 ≥ 단일프로세스, 타임가드·게이트 준수, 4코어 초과 점유 없음(서버 제약).

### M6 — 레짐 라우팅 명시화
- `regime.py` 가 `w1:w2:w3` 비율 + 패킹밀도 + n 을 읽고 탐색 예산/모드(분해-우세 vs co-evolve escape) 분기.
- **수용기준:** 각 레짐에서 라우팅 적용이 단일-모드 대비 **≥ 동급**(회귀 없음), 최소 한 레짐에서 개선.

---

## 7. 테스트 / 검증 계획

- **회귀(필수, 매 마일스톤):**
  - `python -m pytest tests/test_smoke.py -v` → 3/3 유지.
  - `tests/test_feasibility.py`(신규, M0): 생성 스위트 전체를 `algorithm` 으로 풀고 **전부 `check_feasibility` PASS** 단언.
  - `python tools/bench.py instances/gen --timelimit 60` → feasible율 100%, 타임아웃 0, 평균 목적값 비교.
- **타임 안전:** 대표 인스턴스를 `--timelimit 30/120/600` 으로 실행 → 모두 `0.85·timelimit` 내 반환 확인(run_local elapsed 로그).
- **제출 무결성:** `build_submission.py` 산출 zip 을 풀어 루트에 `myalgorithm.py` 존재·≤15MB·bare import 동작 확인.
- **로컬 환경:** `C:/Users/peter/anaconda3/envs/ogc2025/python.exe` (Python 3.11, numpy·ortools·shapely 설치됨). conda env 이름은 `ogc2025`(CLAUDE.md 의 `ogc2026` 은 로컬엔 없음 — 서버만 ogc2026).

---

## 8. 리스크 / −1 가드 회귀 (마일스톤마다 재확인)

| 리스크 | 가드 |
|---|---|
| `multiprocessing` 직렬화 실패(M5) | 피클 사전검증 + 실패시 단일프로세스 폴백. 서버 4코어/16GB 초과 금지. |
| CP-SAT 시간초과/예외 | 항상 `time_budget` 상자 + try/except + None 폴백 → 휴리스틱 배정. |
| 큰 인스턴스 타임아웃 | graceful degradation(탐색 예산·이웃 축소), feasible incumbent 우선 emit. |
| 기하 커널(M2) 버그로 false-feasible | 반환 전 **항상 공식 `check_feasibility`** 게이트(커널은 탐색 가속용일 뿐, 진실은 utils). |
| 로컬↔서버 환경 차 | utils.py·baseline 미수정, 외부 deps 최소(ortools·shapely 만, 둘 다 서버 env 포함). |

---

## 9. 비목표 (이번 범위 아님 — 명시적 제외)

- 상용 솔버(Gurobi/Xpress) 통합 — 제공되지만 §1.1 근거로 의식적 제외.
- GPU/ML 학습 — 서버 GPU 없음. (CPU 추론도 ROI 낮아 보류.)
- `utils.py` 재구현 — 서버가 덮어쓰므로 무의미.
- 새 패킹 엔진을 처음부터 — 베이스라인 검증 프리미티브 재사용 원칙 유지(M2 는 가속이지 대체 아님, 폴백 보존).

---

## 10. `/goal` 실행 노트

1. **반드시 M0 부터.** 인스턴스 생성기·벤치 없이는 M2+ 의 "개선됐다"를 증명할 수 없다(현재 인스턴스 1개).
2. 마일스톤은 **순서대로**, 각 종료시 §7 회귀(스모크 + bench + feasibility 테스트) 통과 확인 후 다음.
3. 매 코드 변경 후 `python tools/run_local.py instances/example/example_B2_b10.json --timelimit 30` 로 example feasible 즉시 확인.
4. §4 불변식 위반이 의심되면 즉시 중단하고 incumbent 보존 경로 점검.
5. 커밋/제출 zip 빌드는 사용자 승인 후. (이메일 제출은 사용자가 직접.)
