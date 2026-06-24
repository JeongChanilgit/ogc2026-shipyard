# OGC 2026 문제 상세 분석

**The Grand Shipyard Puzzle : Pack the Block, Beat the Clock**

- **원문서** : `docs/problem-statement-v1.0.pdf` (v1.0, 2026-05-16, 14p)
- **추출 텍스트** : `docs/problem-statement-v1.0.txt`
- **베이스라인** : `baseline/ogc2026/`
- **분석 대상** : 공식 문제 정의서 + baseline_greedy.py(43KB) + utils.py(64KB) + example_B2_b10.json

---

## 0. TL;DR — 한 페이지 요약

### 문제 한 줄
> **n개의 블록을 m개의 베이(Bay)에 _어디·어떻게·언제_ 넣고 뺄지 모두 동시에 정해서, 지연·작업부하 불균형·선호도 페널티의 가중합을 최소화하라.**

### 한눈에 보기
| 구분 | 내용 |
|------|------|
| 문제 유형 | **Spatial Block Scheduling** — 2D 이형 폴리곤 패킹 + 잡샵 스케줄링 + 할당 |
| 결정 변수 | 블록별 5가지 동시 결정 : 배정 베이, 위치 (x,y), 방향 o, ENTRY 시각, EXIT 시각 |
| 제약 그룹 | (1) 할당 (2) 시간 (3) 공간 (콜리전 + 크레인 수직접근) |
| 목적함수 | `w1·Z1 + w2·Z2 + w3·Z3` (가중합 최소화) |
| 입력 | JSON (bays·blocks·weights) |
| 출력 | JSON (일자별 EXIT→ENTRY 시퀀스) |
| 제출 | submission@optichallenge.com 으로 zip 메일 (≤15MB, 쿨다운 12h) |
| 평가 서버 | AMD Threadripper PRO 9955WX / Ubuntu 24.04 / 4코어·16GB / GPU 없음 / 인터넷 차단 |
| 시간 제한 | 문제마다 다름 — **수 분 ~ 30분** (벽시계 기준), 종료 후 공개 |
| 점수 | 실현가능 → `R − nb` (R=전체팀수, nb=내 점수보다 엄밀히 더 좋은 팀 수), 실현불가/타임아웃/크래시 → **−1** |
| 솔버 허용 | Gurobi 13.0.2, FICO Xpress 9.8.1, OR-Tools 9.15 (스폰서 제공) |

### 풀이 핵심 인사이트
1. **세 문제가 한 번에 얽힘** — 패킹·스케줄링·할당이 분리 불가능. 각각 풀어 합치면 거의 항상 비실현가능.
2. **크레인 수직 접근 제약이 진짜 어렵다** — 같은 베이의 *같은 시점*에 공존하는 블록끼리 단순 콜리전만 보는 게 아니라, ENTRY/EXIT 시점에 *위쪽(상위 layer)이 비어있어야* 한다. 베이스라인이 1단계에서 무시했다가 2단계에서 보수하는 이유.
3. **티어 리더보드 + 사후 박탈** — 정확 순위를 모르므로 *티어 점프*가 유의미하고, 표절/부정행위 적발 시 시상 후에도 박탈. 코드는 전부 오픈소스로 공개됨.
4. **점수가 헤드-투-헤드** — 내 절대 목적값이 아닌 *다른 팀 대비* 위치가 점수. 한 문제에서 압도적으로 좋아도 다른 문제 실현가능성을 놓치면 손해.
5. **MIP 솔버 + 휴리스틱 하이브리드가 유망** — 상용 솔버가 무료 제공되고, 시간이 분 단위이므로 LP/MIP 부분 모델 + 메타휴리스틱(SA, LNS, GRASP 등) 조합이 정석.

---

## 1. 문제 정의 (Formal Problem Definition)

### 1.1 표기 (PDF §1.1 Terminology, 1-based)

| 기호 | 의미 |
|------|------|
| `M = {1,...,m}` | 베이(Bay) 집합 — 각 베이 `j` 는 크기 `W_j × H_j` 의 고정 직사각형 작업장 |
| `N = {1,...,n}` | 블록(Block) 집합 — 각 블록 `i` 는 `K_i` 개의 폴리곤 레이어로 구성된 3D 객체 |
| `O_i` | 블록 `i` 의 가능한 방향(orientation) 수 (인스턴스에 사전 정의) |
| `R_i` | release date — 블록 `i` 의 가용 시작 시각 |
| `D_i` | due date — 블록 `i` 의 희망 완료 시각 |
| `P_i` | processing time — 블록 `i` 의 처리 소요 시간 |
| `ENTRY_i` | 블록 `i` 가 베이에 진입한 시각 |
| `EXIT_i` | 블록 `i` 가 베이에서 나간 시각 |
| `T_i` | 지연(tardiness) — `max(0, EXIT_i − D_i)` |
| `L_i` | 블록 `i` 의 총 작업부하(workload) |
| `S_ij` | 블록 `i` 가 베이 `j` 에 배정될 때의 선호 점수 — 한 블록의 점수 합은 항상 100 |

> ⚠️ **인덱싱 주의** : PDF §1 의 수식은 1-based, JSON·코드는 **0-based**. utils.py 와 알고리즘 코드 안에서는 모두 0-based.

### 1.2 베이 (Bays, §1.3)

- 베이는 서로 **물리적·운영적으로 분리**된 독립 작업장. 한 베이 = 한 크레인.
- 한 블록의 결정사항은 동시에 4가지 :
  1. 어느 베이에 배정할지
  2. 베이 내 위치(`x`, `y`)와 방향
  3. 언제 베이에 넣을지(ENTRY)
  4. 언제 베이에서 뺄지(EXIT)
- **하루 운영 규칙** : 하루에 수행 가능한 작업 수에 제한 없음. 모든 작업은 "그 날의 업무 전에" 수행 가능.
- **같은 날 작업 순서** : **모든 EXIT 가 모든 ENTRY 보다 먼저 수행**. 같은 타입 내 순서는 알고리즘이 결정.

### 1.3 블록 (Blocks, §1.4)

- 각 블록 = 다층 폴리곤(2.5D). `K_i` 개 레이어, 모두 같은 높이.
- **레이어 조건** : 빈 레이어 없음, 인접 레이어는 물리적으로 붙어있음 (floating layer 불가능).
- **폴리곤은 비-볼록 가능** (irregular). 정점 좌표는 최대 4유효숫자의 실수.
- **방향(orientation)** : 인스턴스가 제공하는 `O_i` 개 옵션 중 1개 선택 (회전 자유 X).
- **참조점(reference point)** : 방향 0번의 레이어 0번의 첫 정점 = `[0.0, 0.0]`. 다른 모든 정점은 참조점 기준 상대좌표. 블록 위치 `(x, y)` 결정 = 참조점을 베이 원점에서 `(x, y)` 만큼 평행이동.
- 결과적으로 **방향에 따라 참조점이 박스의 좌하단이 아닐 수 있음** — 단순 bbox 가정 X.

### 1.4 결정 변수 (Decisions, §1.5)

각 블록 `i ∈ N` 마다 :
1. 베이 배정 `j ∈ M`
2. 베이 내 위치 `(x_i, y_i) ∈ Z²` (정수)
3. 방향 `o_i ∈ {0, 1, ..., O_i − 1}`
4. ENTRY 시각 `ENTRY_i ∈ Z⁺`
5. EXIT 시각 `EXIT_i ∈ Z⁺` (단 `EXIT_i > ENTRY_i`)

---

## 2. 제약 (Constraints, §1.6)

세 그룹으로 묶여 있다 — 모두 동시에 만족해야 함.

### 2.1 할당 제약 (Assignment, §1.6.1)

- **할당 제약** : 모든 블록은 *정확히 한* 베이에 배정. 미할당 블록 불가.
- **운영 제약** : 모든 블록은 *정확히 한* ENTRY 와 *정확히 한* EXIT 를 가짐. 한번 놓인 블록은 이동·회전 불가.

### 2.2 시간 제약 (Temporal, §1.6.2)

- **릴리즈 제약** : `ENTRY_i ≥ R_i`
- **처리시간 제약** : `EXIT_i − ENTRY_i ≥ P_i`
- 처리 후에도 다른 블록 때문에 못 나가서 *지연 체류* 가능 → 이 경우 `EXIT_i > D_i` 면 `T_i > 0`.
- 보통 `D_i − R_i > P_i` (slack 있음) — slack 안에서 ENTRY/EXIT 시각을 잘 정해야 한다.

블록 `i` 는 베이를 `[ENTRY_i, EXIT_i)` 의 *반열린 구간* 동안 점유한다 (반열린 구간이 핵심 — 같은 시각에 한 블록이 EXIT, 다른 블록이 ENTRY 가능).

### 2.3 공간 제약 (Spatial, §1.6.3)

표기 : `P_{i,l}^{o,x,y}` = 블록 `i` 의 레이어 `l` 이 방향 `o`, 위치 `(x,y)` 에 놓였을 때의 폴리곤.

`int(·)` = 내부점 집합 (변·꼭짓점 제외).

**충돌 함수**
```
C(i1, l1, o1, x1, y1, i2, l2, o2, x2, y2) = 1  if  int(P1) ∩ int(P2) ≠ ∅
                                          = 0  otherwise
```
→ **변·꼭짓점은 공유 가능** (touch OK), 내부 겹침만 충돌로 판정.

**동시점유 블록 집합**
```
N(t, j) := { i ∈ N : ENTRY_i ≤ t < EXIT_i  and  i ∈ bay j }
```

#### (a) Bay Containment — 베이 경계
각 블록은 배정된 베이에 완전히 포함되어야 함.
PDF Figure 7(b) 가 위반 예시.

#### (b) Layer Collision-Free — 동일층 충돌 금지
임의의 `t`, 베이 `j`, 두 블록 `i1, i2 ∈ N(t, j)` 에 대해
```
C(i1, l, o1, x1, y1, i2, l, o2, x2, y2) = 0   ∀ l = 1, ..., min(K_i1, K_i2)
```
즉 **같은 높이(같은 layer index)** 의 폴리곤끼리만 비교한다. 다른 층은 같은 (x,y) 영역에 있어도 OK (서로 다른 z 평면이라 가정).
PDF Figure 7(a) 가 ok 예시, Figure 7(c) 가 위반 예시.

#### (c) Crane Operation — 크레인 수직 접근
ENTRY/EXIT 시점에 크레인이 *수직으로* 블록을 내리거나 들어올려야 한다. 이 동안 블록의 모든 레이어가 *그 위쪽 어떤 다른 블록의 레이어와도* 부딪히면 안 됨.

수식 :
```
C(i1, l1, o1, x1, y1, i2, l2, o2, x2, y2) = 0
   ∀ l2 ≥ l1,  i2 ∈ N(t, j) \ {i1},  l1 = 1..K_i1,  l2 = 1..K_i2
```

쉽게 말해 : **레이어 `l1` 보다 같거나 위쪽(`l2 ≥ l1`)의 다른 블록 레이어와 겹치지 않아야** ENTRY/EXIT 가능. PDF Figure 7(d) 에서 Block 2 가 Block 1 위로 가려져서 못 들어가는 경우.

> 💡 **이게 진짜 어려운 제약** :
> - 단순 동시점유 충돌(b)은 *같은 layer 만* 보면 되지만,
> - 크레인 접근(c)은 *상위 layer 전부* 를 본다.
> - 결과적으로 *현재 시점에 비실현가능하지 않은 블록도 ENTRY/EXIT 가 막힐 수 있음*. baseline_greedy 가 phase 1 에서 크레인 제약을 *대부분* 본 후 phase 2 에서 잔여 위반을 보수하는 이유.

`utils.py` 의 도키스트링 : *"j == k 면 최종 위치에서 충돌, j > k 면 하강 경로 충돌. j < k 인 경우는 새 블록 layer k 보다 기존 layer j 가 *아래*라 절대 부딪히지 않는다."*

### 2.4 작업 순서 (within a day)
- 같은 시각의 작업은 **EXIT 전부 → ENTRY 전부** 순서로 처리.
- 같은 타입 내 순서는 알고리즘이 결정 — 단, 각 작업이 그 시점 베이 상태에 대해 실현가능해야 함.

---

## 3. 목적함수 (Objective, §1.7)

### 3.1 세 가지 평가 기준 최소화

```
minimize   w1·Z1 + w2·Z2 + w3·Z3
```
`w1, w2, w3 ≥ 0` 은 인스턴스에 명시.

#### Z1 — Total Tardiness (총 지연)
```
Z1 := Σ_{i=1..n} T_i    where  T_i = max(0, EXIT_i − D_i)
```

#### Z2 — Workload Imbalance (작업부하 불균형)
```
Z2 := max_{j1, j2 ∈ M, j1≠j2}  | u_{j1}·Σ_{i ∈ N(j1)} L_i  −  u_{j2}·Σ_{i ∈ N(j2)} L_i |
```
여기서 `N(j)` = 베이 `j` 에 배정된 블록 집합, `u_j` 는 베이 가중치 :
```
u_j = (Σ_{k ∈ M} W_k · H_k) / m   ÷   (W_j · H_j)
    = (모든 베이의 평균 면적) / (베이 j 의 면적)
```
- **큰 베이일수록 `u_j` 작음** → 같은 작업부하라도 큰 베이에 넣으면 "혼잡도 가중치"가 낮게 잡힘.
- 패널티는 *모든 베이 쌍 중 최악의 불균형* (max).

#### Z3 — Preference Deviation (선호도 페널티)
```
Z3 := Σ_{j ∈ M} Σ_{i ∈ N(j)} (S_i^max − S_ij)    where  S_i^max := max_{j ∈ M} S_ij
```
- 모든 블록이 *각자의 최선호 베이* 에 들어가면 `Z3 = 0`.
- 한 블록의 선호 점수 합이 100 이므로 `S_i^max − S_ij ∈ [0, 100]`.

### 3.2 가중치 해석
PDF Listing 1 의 예시 :
```json
"weights": { "w1": 26667, "w2": 10, "w3": 300 }
```
→ **지연 1단위가 압도적 비중**. 작업부하 불균형은 큰 수치이므로 `w2` 가 작음. 선호도는 중간.
→ 이 비율은 인스턴스마다 다르며, 인스턴스가 어떤 측면을 더 중시하는지 결정.

### 3.3 평가 코드 (utils.py)
```python
obj1 = Σ max(0, exit_time_i − due_date_i)         # 지연
obj2 = max_{j1≠j2} |u_j1·load_j1 − u_j2·load_j2|  # 불균형
obj3 = Σ_i (S_i_max − S_i_bay_i)                   # 선호도
objective = w1·obj1 + w2·obj2 + w3·obj3
```

---

## 4. 입출력 포맷 (§2 / §4)

### 4.1 입력 JSON (problem instance)

```json
{
  "name": "training_problem_01",
  "bays": [
    { "width": 125, "height": 15 },
    { "width": 71,  "height": 18 },
    { "width": 140, "height": 25 }
  ],
  "blocks": [
    {
      "release_time":   37,
      "due_date":       44,
      "processing_time": 7,
      "workload":       20,
      "bay_preferences": [19, 26, 55],  // sum = 100
      "shape": [
        {
          "orientation": 0,
          "layers": [
            [ [0.0, 0.0], [0.8093, 5.4723], [1.2955, 11.0993], ... ],  // layer 0
            [ [-3.0413, 0.3435], [0.5671, -0.064], ... ]                // layer 1
          ]
        },
        { "orientation": 1, "layers": [...] },
        ...
      ]
    },
    ...
  ],
  "weights": { "w1": 26667, "w2": 10, "w3": 300 }
}
```

**필드 명세**
| 필드 | 타입 | 비고 |
|------|------|------|
| `bays[].width / height` | int | 베이 크기 (정수) |
| `blocks[].release_time` | int | 릴리즈 시각 (정수) |
| `blocks[].due_date` | int | 마감 시각 (정수) |
| `blocks[].processing_time` | int | 처리 시간 (정수) |
| `blocks[].workload` | int | 작업부하 (정수) |
| `blocks[].bay_preferences[j]` | int | 각 베이별 선호 (합=100) |
| `blocks[].shape[o].orientation` | int | 방향 ID |
| `blocks[].shape[o].layers[l]` | list of [x,y] | 레이어 폴리곤 (최대 4유효숫자 실수) |

- **인덱싱은 0-based** (PDF §1 의 1-based 수식과 다름 — 코드 작성 시 주의)
- 레이어는 *아래에서 위로* 정렬 (layer 0 이 최하단)
- 모든 시간·선호도 값은 정수

### 4.2 출력 JSON (solution)

```json
{
  "operations": {
    "0":  [ {"type":"ENTRY","block_id":48,"bay_id":1,"x":0,"y":0,"orient_idx":0}, ... ],
    "1":  [ {"type":"ENTRY","block_id":19,"bay_id":2,"x":37,"y":0,"orient_idx":2}, ... ],
    "28": [
      {"type":"EXIT", "block_id":25,"bay_id":2},
      {"type":"EXIT", "block_id":31,"bay_id":1},
      {"type":"ENTRY","block_id":15,"bay_id":0,"x":106,"y":0,"orient_idx":0},
      ...
    ]
  }
}
```

**규칙**
- 최상위 키는 `"operations"` 하나뿐.
- 값은 *날짜→작업리스트* dict. 날짜 키는 정수의 문자열 (`"0"`, `"28"` 등).
- 작업이 있는 날만 포함.
- 한 날짜 내 EXIT 가 ENTRY 보다 앞에 와야 함.
- ENTRY 필드 : `type, block_id, bay_id, x, y, orient_idx`
- EXIT 필드 : `type, block_id, bay_id`
- **모든 숫자는 정수** — `x`, `y` 가 소수면 평가시스템이 *반올림 후* 검사. 그래서 직접 정수로 내는 게 안전.

### 4.3 5단계 실현가능성 검사 (utils.check_feasibility)

| Stage | 검사 항목 | 실패 시 |
|------|----------|--------|
| **1** | 할당 유효성 (모든 블록이 정확히 1 ENTRY + 1 EXIT, bay_id/orient_idx 범위, 릴리즈/처리시간) | `stage=1` 반환 |
| **2** | ENTRY 시점 크레인 진입 실현가능성 (j ≥ k 규칙) | `stage=2` |
| **3** | EXIT 시점 크레인 퇴출 실현가능성 (j ≥ k 규칙) | `stage=3` |
| **4** | 공간 충돌 + 베이 경계 (동시점유 블록 쌍의 같은-층 폴리곤 겹침) | `stage=4` |
| **5** | 시점별 순차 실현가능성 (EXIT 먼저 → ENTRY, 베이 상태 시뮬레이션) | `stage=5` |

- 모든 단계 통과 시 `feasible=True`, `objective` 계산.
- 첫 위반에서 즉시 중단 (이후 단계는 평가 안 함).
- 부동소수점 비교는 `1e-6` 허용오차.
- **검사기 코드는 수정 불가** — `utils.py` 는 제출 zip 에 포함해도 평가 서버가 덮어쓴다.

---

## 5. 제출 & 평가 (§3)

### 5.1 제출 규칙
- **이메일** : `submission@optichallenge.com` (수신)
- **발신** : 등록 시 사용한 이메일과 동일해야 함
- **첨부** : zip 1개
  - 루트에 `myalgorithm.py` (서브폴더 X)
  - `utils.py` 포함 시 평가 서버가 덮어씀 (수정 의미 X)
  - 추가 모듈/패키지 자유 (zip 안에 묶기)
  - 압축 후 **≤ 15MB**
- **쿨다운** : 직전 *수락된* 제출 이후 **12시간** 경과 필요
- **금지 확장자** : Gmail 등이 `.dll`, `.vb`, `.exe` 차단 가능 — 회피 책임은 팀에 있음
- 제출 후 자동 회신으로 acceptance/rejection 알림

### 5.2 알고리즘 인터페이스
```python
def algorithm(prob_info: dict, timelimit: float) -> dict:
    ...
    return solution
```
- `prob_info` : 인스턴스 JSON 을 dict 로 로드한 것
- `timelimit` : 벽시계(wall-clock) 초 단위 제한
- 반환 : §4.2 의 solution dict

### 5.3 평가 서버 사양
| 항목 | 값 |
|------|----|
| CPU | AMD Ryzen Threadripper PRO 9955WX |
| OS | Ubuntu 24.04 LTS |
| **CPU 코어 한도** | **4 코어 (400% CPU)** — `cpulimit` 강제 |
| **메모리 한도** | **16 GB** |
| **GPU** | 없음 (ML 패키지는 CPU 전용으로만) |
| **인터넷** | 차단 — `firejail` 격리 |
| **상위 디렉토리 접근** | 차단 |
| 시간 제한 | 인스턴스별 다름 (수 분 ~ 30분, 종료 후 공개) |

### 5.4 conda 환경 (제공)
- Python 3.12
- 라이브러리 : pandas 2.2.3, networkx 3.4.2, scipy 1.15.2, scikit-learn 1.6.1, numba 0.61, cython 3.0.10, openjdk 17, dotnet-runtime 8
- ML : torch 2.11, torchvision 0.26, tensorflow 2.21, keras 3.14, gymnasium 1.2.3
- **MIP 솔버** (스폰서 무료) :
  - **Gurobi 13.0.2** (gurobipy)
  - **FICO Xpress 9.8.1**
  - **OR-Tools 9.15.6755** (Google)
- 기하 : shapely ≥ 2.1.0
- 추가 패키지 요청은 Discord 로

### 5.5 채점 (§3.3 Leaderboard)
- 각 hidden 인스턴스에 대해 :
  - **실현가능** → `R − nb` 점 (R = 총 평가팀 수, nb = 내 목적값보다 *엄밀히 더 좋은* 팀 수)
  - **실현불가 / 타임아웃 / 크래시** → **−1 점**
- 리더보드 = 모든 인스턴스 점수 합
- **시간별 집계** (hourly aggregation)
- 본선은 점수 + **기술보고서 + 발표** 까지 종합 — 운영위가 가중치 조정

### 5.6 제출 시스템 정책
- 제출 수 무제한 (단 쿨다운 12h 적용)
- 시스템 남용 시 제재/실격 가능
- 결선팀 코드·보고서는 **전부 오픈소스 공개** — 참가가 곧 공개 동의
- 사후 부정행위 적발 시 시상 후에도 박탈

---

## 6. Baseline 알고리즘 분석

### 6.1 구조 (`baseline/baseline_greedy.py` 1146 LOC)

**2단계 휴리스틱 : EDD + Best-Fit Greedy + Post-Hoc Repair**

#### Phase 1 — Aggressive Greedy Placement
1. 블록을 **EDD (Earliest Due Date)** 순으로 정렬, 동률은 **SPT (Shortest Processing Time)**.
2. 각 블록에 대해 *모든* `(bay, orientation, position, time-slot)` 조합 스코어링 → 가장 싼 것 채택.
3. 위치 후보는 **Bottom-Left Fill** — 베이 경계 + 기존 블록의 AABB 우상단 꼭짓점.
4. 시각 후보는 `{r_time} ∪ {기존 블록들의 exit_time}`.
5. 크레인 ENTRY/EXIT 실현가능성 (`check_entry`, `check_exit`)을 *대부분* 검증.

스코어 함수 :
```
score = w1·tardiness
      + w2·new_imbalance     (이 베이에 넣었을 때의 Z2 근사)
      + w3·pref_penalty       (S_max − S_ij)
      + w4·top_y              (좌상단 높이 — 타이브레이커, 더 빡빡한 패킹)
```
`w4 = 1e-4` 로 매우 작은 타이브레이커.

#### Phase 2 — Iterative Repair
1. Phase 1 결과에 `check_feasibility` 호출.
2. 위반 블록을 EDD 순으로 *재배치*.
3. 두 모드 :
   - **`greedy`** (기본) : 위반 블록 제거 → Phase 1 의 전체 탐색 재실행.
     - 사이클 감지 : 두 번 이상 다시 위반되면 `forced_ids` 에 추가, `_force_place` 로 *빈 베이 윈도우 (0,0)* 강제 배치.
     - 시간 가드 : `timelimit · 0.9` 초과 후엔 모두 `_force_place`.
   - **`simple`** : 위반 블록을 다음 *완전 빈 베이 윈도우* 로 그냥 미룸.

### 6.2 인터페이스 (`baseline/myalgorithm.py` — 참가자 수정 파일)
```python
def algorithm(prob_info, timelimit=60):
    import baseline_greedy
    return baseline_greedy.greedyalgorithm(prob_info, timelimit)
```
- **시그니처 변경 금지**.
- 다른 모듈 import 자유.
- `baseline_greedy.py` 를 *시작점* 또는 *부분 호출* 로 사용 가능 (그대로 두거나 통째로 갈아끼우거나).

### 6.3 핵심 utils.py 구성요소
| 함수/클래스 | 역할 |
|------------|------|
| `Bay`, `Block` | 베이·블록 기하 객체. `Block` 생성 시 world-coord layer polygon 캐싱. |
| `check_collisions(bay, blocks)` | 동시점유 블록쌍의 *같은-층* 폴리곤 충돌. AABB 조기탈출 + Shapely intersection. |
| `check_entry(bay, blocks, new)` | ENTRY 시 j≥k 규칙 + 베이 경계. |
| `check_exit(bay, blocks, target)` | EXIT 시 j≥k 규칙. |
| `check_feasibility(prob_info, solution)` | **5단계 검증 + 목적값 계산** (공식 평가 서버와 동일). |
| `_resolve_layers`, `_anchor_layers`, `_bounding_box` | 폴리곤 기하 헬퍼. |

폴리곤 캐시 : `@lru_cache(maxsize=8192)` 로 `_poly_from_verts_cached`. `buffer(0)` 으로 self-intersect 자동 보수.

### 6.4 알고리즘 약점 (개선 여지)
1. **그리디만 사용** → 국소 최적에 쉽게 빠짐. LNS/SA/Tabu/Memetic 같은 메타휴리스틱 미사용.
2. **MIP 솔버 미활용** — Gurobi/Xpress 가 무료인데 활용 여지 큼. 작은 부분 인스턴스 또는 *서브문제* (예: 단일 베이 패킹) 에 MIP 적용 가능.
3. **시간 슬라이스 후보가 단순** — 기존 EXIT 시각만 후보. 더 정교한 *이벤트 기반* 시간 후보 가능.
4. **방향 탐색 무작위 안 함** — 모든 방향 시도하지만 베이별 선호 방향 학습 없음.
5. **Phase 2 가 사후 보수** — 크레인 제약을 Phase 1 에 *완전히* 통합한 알고리즘은 더 좋은 해를 낼 수 있음.
6. **선호도 가중치 무시 가능** — 인스턴스에 따라 `w3` 가 크면 EDD 보다 *preferred bay 우선* 정렬이 유리할 수 있음.

---

## 7. 문제 난이도와 풀이 전략 시사점

### 7.1 복잡도 직관
- **2D irregular packing** 단독으로 NP-hard (Strip Packing).
- **단일 머신 스케줄링 + tardiness 최소화** 도 NP-hard.
- 두 문제가 *동시 의사결정*으로 결합되면 더 어려워짐.
- 크레인 수직접근 제약이 **z-ordering** 을 도입 — 시간축에 *블록 진입 순서* 가 영향을 미침.
- 게다가 **할당(bay assignment)** + **선호도** + **부하 균형** 까지 결합.
- 한마디로 : "교과서적 어려운 문제 3개를 곱한 것."

### 7.2 풀이 접근 방향 (제안)

#### 휴리스틱
- **EDD + Best-Fit** (베이스라인) → 빠르지만 약함
- **LNS (Large Neighborhood Search)** : 한 베이 또는 시간 윈도우 일부를 통째로 destroy → repair. 베이스라인의 Phase 2 사이클을 LNS 로 대체하면 즉시 강해질 가능성.
- **Simulated Annealing** : 블록 swap, orientation change, time shift 의 3가지 이동.
- **Tabu Search** : 최근 변경된 (블록, 베이) 쌍 금지.
- **GRASP** : 무작위화 그리디 + 로컬서치.

#### MIP / CP
- 전체 문제는 *대규모 변수* (시간 × 베이 × 위치 × 방향) → 직접 MIP 어려움.
- **부분 MIP** : 베이 배정과 시각 결정만 MIP, 위치/방향은 휴리스틱 후처리.
- **CP-SAT** (OR-Tools) : 스케줄링 부분에 강함 — `IntervalVar` + `NoOverlap2D` 활용.
- **Column generation** : 베이별 *유효 배치 패턴* 을 컬럼으로 생성.

#### Learning-based
- GPU 없음 → 추론용 가벼운 모델만 가능.
- **Pointer Network / Transformer** 로 블록 순서 학습 → 그리디 시드용.
- **Reinforcement Learning** : 환경 시뮬레이션이 비싸므로 학습 단계가 제한적.
- 학습된 *순서 정책* + 휴리스틱 배치가 현실적.

#### 하이브리드 (가장 유망)
1. ML/그리디로 *순서/배정* 초안 → MIP로 *시각* 정밀화 → LNS로 *국소 개선*.
2. 시간이 분 단위이므로 **여러 시드의 병렬 그리디 + 풀에서 최선택** 도 효과적.
3. **앙상블** : 여러 알고리즘 실행 후 최적해 선택. 평가 서버는 4코어이므로 4스레드 병렬 가능.

### 7.3 주의해야 할 함정
1. **−1 점 회피가 최우선** — 한 인스턴스라도 실현불가/타임아웃이면 그 인스턴스에서 -1, 다른 팀 평균이 R-1 이라 손해 큼.
2. **시간 모니터링 필수** — 인스턴스별 시간이 다르고 *공개도 종료 후*. 알고리즘 내부에서 `time.time()` 기반 자가 모니터링 필수.
3. **메모리 16GB 한도** — 폴리곤 캐시·후보 위치 풀 등이 폭발하지 않게 주의. Shapely 객체는 무겁다.
4. **정수 좌표** — `x, y` 가 정수여야 하고 평가시스템이 반올림 → 직접 정수로 생성하는 게 안전.
5. **부동소수점 비교** — 폴리곤 변·꼭짓점 공유는 OK 이지만 `1e-6` 허용오차. 자체 알고리즘 안에서 마진 둘 것.
6. **EXIT < ENTRY 순서 위반** — 같은 시점에 EXIT 와 ENTRY 가 있을 때 EXIT 가 먼저 와야 함. JSON 출력 시 리스트 순서 보장.
7. **Layer 개수 불일치** — `min(K_i1, K_i2)` 까지만 동층 충돌 검사하지만 크레인 검사는 *모든 상위 layer* 검사. 베이스라인의 j≥k 규칙 도키스트링 참고.
8. **방향별 참조점 위치 변화** — 좌하단 정렬을 가정하면 종종 베이 경계 위반. utils.py 의 `_bounding_box` 가 정답.

### 7.4 단계별 작전
| 시점 | 목표 |
|------|------|
| **W1 (등록·환경 셋업)** | conda env 생성 → 베이스라인 실행 → example_B2_b10.json 으로 점수 확인 |
| **W2 (예선 시작)** | 베이스라인 약점 1~2개 개선 (LNS 도입 또는 시간슬롯 정밀화) |
| **W3~W4** | 메타휴리스틱 본격 적용 + MIP 솔버 부분 활용 |
| **W5 (예선 마감 직전)** | 다양한 인스턴스 특성에 robust 한 버전 — *최악 케이스 −1 회피* 우선 |
| **본선 (Top 30~40)** | 기술보고서·발표 준비 — 알고리즘 신규성·수학적 통찰 어필 |

### 7.5 점수 모델 통찰
점수 `R − nb` 의 특성 :
- 1위 (`nb = 0`) → `R` 점, 2위 (`nb = 1`) → `R − 1` 점, ...
- 모든 팀과 같은 점수면 `nb = 0` (엄밀히 더 좋아야 카운트). 동점자 모두 만점.
- 한 문제만 압도해도 다른 문제 실현불가면 -1 손실이 큼 → **모든 인스턴스에서 feasibility 확보가 우선**.
- 이후 *조금씩 더 잘하는 방향* 으로.

---

## 8. 운영위원회 (§6)

OGC 2026 은 아래 위원회에서 운영 :

| 이름 | 소속 | 역할 |
|------|------|------|
| **Kyungsik Lee** (이경식) | Seoul National University | **Chair (위원장)** |
| Chungmok Lee (이충목) | Hankuk University of Foreign Studies | 위원 |
| Jonghoon Woo (우종훈) | Seoul National University | 위원 |
| Chankmug Kang (강찬묵) | Soongsil University | 위원 |
| Seulgi Joung (정슬기) | Ajou University | 위원 |
| Yunwoo Jung (정윤우) | LG CNS | 위원 |
| Gibeak Ahn (안기백) | LG CNS | 위원 |
| Jerimi Lee (이제리미) | LG CNS | 위원 |

LG CNS 와 KIIE 의 공동 운영. 평가 기준·시간 제한·운영 변경은 운영위 재량.

---

## 9. 핵심 체크리스트 (실전용)

### 환경 준비
- [ ] `conda env create -f baseline/ogc2026/ogc2026_env.yml` 으로 ogc2026 환경 생성
- [ ] `conda activate ogc2026` 후 `python -c "from utils import check_feasibility; print('ok')"` 확인
- [ ] `cd baseline/ogc2026/alg_tester && python alg_tester_app.py` 로 GUI 테스터 실행
- [ ] example_B2_b10.json 인스턴스로 베이스라인 점수·feasibility 확인
- [ ] Gurobi / Xpress 라이선스 동작 확인 (`import gurobipy; m = gurobipy.Model()`)

### 알고리즘 개발
- [ ] `algorithm(prob_info, timelimit)` 시그니처 유지
- [ ] 내부 시간 모니터링 (`time.time()` 또는 `time.monotonic()`) — 90% 한도에서 안전 종료
- [ ] feasibility 검사 단위 테스트 — 직접 만든 작은 인스턴스로 `check_feasibility` 의 5단계 통과 확인
- [ ] 좌표 정수화 (반올림은 평가가 해주지만 직접 처리가 더 명확)
- [ ] EXIT 가 같은 시점 ENTRY 보다 *리스트에서 먼저* 오도록 출력
- [ ] 16GB 메모리 모니터링 — Shapely 객체 캐시 무한 증식 주의
- [ ] 4코어 활용 (multiprocessing 등) — 단, 평가 서버에서 spawn 비용 고려

### 제출 직전
- [ ] zip 루트에 `myalgorithm.py` (서브폴더 X)
- [ ] zip 크기 ≤ 15MB
- [ ] `utils.py` 는 zip 에 넣지 말거나 (평가가 덮어쓰므로 무의미) 또는 동일 사본 사용
- [ ] 등록된 이메일에서 발송
- [ ] 직전 *수락된* 제출로부터 12시간 경과 확인
- [ ] `.exe`, `.dll`, `.vb` 확장자 포함 안 함

### 본선 진출 시
- [ ] 기술보고서 (운영위 양식) — 알고리즘 설명, 실험 결과, 한계 분석
- [ ] 발표 자료 — 알고리즘 핵심 아이디어, 신규성, 수학적 통찰
- [ ] 코드 오픈소스 정리 (어차피 공개됨)

---

## 10. 부록 — 자주 참조할 수식 모음

### 시간 점유 구간 (반열린)
```
block i occupies bay j during [ENTRY_i, EXIT_i)
```

### 동시점유 집합
```
N(t, j) = { i ∈ N : ENTRY_i ≤ t < EXIT_i  and  block i assigned to j }
```

### 베이 가중치
```
u_j = (Σ_k W_k·H_k) / m  ÷  (W_j · H_j)
```
- 모든 베이 같은 크기 → `u_j = 1` ∀j
- 큰 베이 → `u_j < 1` → 부하가 같아도 페널티 작음
- 작은 베이 → `u_j > 1` → 부하가 같아도 페널티 큼

### 충돌 검사
```
# 동시점유 같은-층 충돌 (Z2 제약)
for all l = 1..min(K_i1, K_i2):
    int(P_{i1,l}^{o1,x1,y1}) ∩ int(P_{i2,l}^{o2,x2,y2}) = ∅

# 크레인 수직 진입/퇴출 (l1 = new block layer, l2 = existing block layer)
for all l2 ≥ l1:
    int(P_{i1,l1}^{o1,x1,y1}) ∩ int(P_{i2,l2}^{o2,x2,y2}) = ∅
```

### 목적 함수
```
minimize  w1·Σ T_i  +  w2·max|u·load 차이|  +  w3·Σ (S_max − S_chosen)
```

### 점수 함수 (리더보드)
```
score(team, instance) = { -1            if infeasible/timeout/crash
                        { R - nb        if feasible
                          where R = #evaluated teams
                                nb = #teams with strictly better objective on this instance

total_score(team) = Σ_{instance} score(team, instance)
```

---

*본 분석 문서는 `problem-statement-v1.0.pdf` (2026-05-16 v1.0) 와 첨부 `baseline-v1.0.zip` 의 코드를 직접 정독·교차검증해 작성했다. 문서 갱신 시 (v1.1, v2.0 등) 본 분석도 재검토할 것.*
