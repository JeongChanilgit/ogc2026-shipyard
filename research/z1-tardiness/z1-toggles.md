# Z1(Tardiness)→0 레버 토글 맵 (2026-06-06)

## ★ 디코드 가속 (2026-06-06 추가, 측정 검증) — default 변경

| 플래그 | 기본 | 효과 | 비고 |
|---|---|---|---|
| `OGC_BBOX_CACHE` | **ON** | `_aabb` 메모 → **1.27× (byte-identical, 공짜)** | kill-switch=0 |
| `OGC_FAST_POSITIONS` | **ON** | O(P²)→컬럼지지 위치 → **3.55× 디코드** | kill-switch=0 |
| `OGC_FAST_POS_TOP` | **4** | 컬럼당 바닥+상위 N레벨만 (0=전부). 4=속도/Z1 sweet spot | |

**효과(측정)**: 대형/잘리는 인스턴스 大승 — prob_20 @60s **52258→1864(−96%)**, prob_14 −65%, 분산 안정화. 소형(1/5/8) 회귀 0. **권장 submission 기본값 = 그대로(둘 다 ON).** kill-switch로 OFF 시 기존 exhaustive 디코드 복원.

**폐기(측정 후 제거)**: `OGC_FAST_POS_ADAPT`(worst-of-both)·`OGC_FAST_FALLBACK`(wall초과)·`OGC_DECODE_EARLY_EXIT`(Z1 trade, OFF노브)·`OGC_FAST_CRANE`(더 느림).

**한계**: 하드 인스턴스는 ~300~420 **탐색 basin**에 plateau (시간·튜닝 무관). 5분 내 두자릿수 Z1 = **full CP-SAT/LBBD 결합모델**(insight ⑤④) 필요.

---

> 문헌 인사이트 ①–⑧(`research/z1-tardiness/`)을 **켜고 끄는** env 플래그 레퍼런스.
> 핵심 안전장치: **모든 후보는 최종 official-checker 게이트**(`_postprocess_verified_solution`의 `consider`,
> 그리고 `algorithm()` 말미의 candidate 게이트 `better_obj`/`same_obj_lower_z1`)를 통과해야 채택된다 →
> **어떤 플래그를 켜도 verified incumbent/baseline floor보다 나쁜 해는 반환되지 않는다(−1·objective 악화 불가).**
> 모든 신규 Z1 플래그 default **OFF** → 미설정 시 솔버 동작은 기존과 bit-identical.

## 한눈에

| # | 인사이트 | 플래그 | 기본 | 상태 | 효과 |
|---|---|---|---|---|---|
| ① | sequence↔timing 분리, 정확 재타이밍 | **`OGC_Z1_MULTI_RESCHED`** | OFF | **신규** | 레이아웃 고정·다중 crane-safe 순서로 ENTRY/EXIT 재계산, bay별 최소 tardiness 채택. **x/y/orient/bay 불변 → Z2/Z3 불변, Z1만↓** |
| ② | per-bay tardiness 하한 focus | **`OGC_Z1_LB`** | OFF | **신규** | `Σmax(0,r+p−due)` 하한에 이미 도달한 베이를 skip → 예산을 회수가능 베이에 집중 |
| ①②| 마스터 스위치 | **`OGC_Z1_PUSH`** | OFF | **신규** | 위 ①+② 동시 ON (가장 안전한 Z1 푸시) |
| ③ | 마감-인지 배치 (slack+crane 우선) | `OGC_CRANE_ORDER` / `OGC_ATCR_SEED` | ON / OFF | 기존 | `_orderings`가 slack·crane-complexity로 정렬(통로 보존). ATCR 켜면 ATC 순서 추가 |
| ④ | LBBD / no-good cut | `OGC_M4_CUT`(+ALNS `op_cut_destroy`) | OFF / 항상 | 기존 | force-place 인증을 읽어 over-subscribed 베이의 블록을 eject + 그 조합 cut |
| ⑤ | CP-SAT 배정 시드 | `OGC_CPSAT_FIRST` | OFF | 기존 | CP-SAT(OR-Tools)로 배정 시드 → gated candidate (ortools 필요) |
| ⑥ | tardiness-타겟 ALNS destroy | (ALNS `op_destroy_repair`, 항상) | 항상 | 기존 | destroy의 50%가 worst-tardy 우선 제거 + regret 재삽입 |
| ⑦ | 탐색 SA accept-worse | `OGC_SA_TEMP` | 0.10(regime) | 기존 | 내부 local search의 일시적 악화 허용 온도 (반환은 안전게이트 유지) |
| ⑧ | ATC dispatch 순서 | `OGC_ATCR_SEED`(+`OGC_ATCR_K`) | OFF | 기존 | EDD 대신 ATC(urgency×slack) 순서 후보 추가 |

> ⑥⑦은 search가 돌 때 항상 활성(개별 플래그 아님). ⑦ 온도는 `OGC_SA_TEMP`로 조절.
> ⑧·`OGC_CRANE_TIEBREAK`은 과거 **소형 인스턴스 회귀**로 default OFF (메모리 `ogc2026-z1-lever-is-packing`). 켤 땐 소형 회귀 확인 필수.

## 관련 보조 노브

| 플래그 | 기본 | 역할 |
|---|---|---|
| `OGC_GATE_POSTPROCESS` | ON | postprocess 게이트(exit_pull·reschedule·shift·redecode·**multi_reschedule**) 활성 |
| `OGC_Z1_BAY_DECODE` | ON | 같은 배정을 베이별로 깨끗이 재디코드하는 gated candidate (`run_parallel_bay_decode`) |
| `OGC_PARALLEL_MS` | auto(T≥20 & n≥30) | 4코어 병렬 multistart (1=강제ON, 0=강제OFF) |
| `OGC_CRANE_MOVE_CAP` | 80 | `_tardy_redecode_moves`의 후보 cap |
| `OGC_CAND_CAP` / `OGC_CAND_CAP_MIN` | 0 | 디코드 후보 가지치기(대형 가속, 소형 보호) |
| `OGC_CRANE_TIEBREAK` | OFF | 동점 move를 crane 방향으로 tie-break (소형 회귀 주의) |

## 사용 예시 (PowerShell)

```powershell
# 가장 안전한 Z1 푸시 (신규 ①+②) — 단일 인스턴스
$env:OGC_Z1_PUSH = "1"
conda run -n ogc2025 python tools/run_solver_once.py instances/train/prob_14.json --solver our --timelimit 180
Remove-Item Env:OGC_Z1_PUSH   # 끄기

# 개별 레버만
$env:OGC_Z1_MULTI_RESCHED = "1"          # ① 만
$env:OGC_Z1_LB = "1"                      # ② focus
$env:OGC_CPSAT_FIRST = "1"               # ⑤ CP-SAT 시드
$env:OGC_ATCR_SEED = "1"; $env:OGC_ATCR_K = "2.0"   # ⑧ ATC (소형 회귀 주의)
$env:OGC_SA_TEMP = "0.15"                # ⑦ SA 온도 ↑
```

```bash
# bash
OGC_Z1_PUSH=1 conda run -n ogc2025 python tools/run_solver_once.py instances/train/prob_14.json --solver our --timelimit 180
```

## 검증

- A/B 하니스: `notes/_z1_ab.py` → `results/z1_push_ab.json` (base vs push, feasible·objective-safe·Z1·wall).
- 단위: `conda run -n ogc2025 python -m pytest tests/test_safe_foundation_contract.py tests/test_parallel_pickle.py tests/test_smoke.py -q`
- objective-safety 불변식: 어떤 조합도 `push.objective ≤ base.objective` 이고 `feasible=True` (게이트 보증).

## 미구현(향후, 본격 작업 필요)

- ⑤ **per-bay 정확 CP-SAT 재패킹**(no_overlap_2d + j≥k precedence를 utils 기하와 정합): 현재는 CP-SAT **배정** 시드만 존재. 완전 재패킹 모델은 utils crane 기하 복제가 필요해 별도 큰 작업·시간상한 위험 → 게이트 보호 하에 추후.
- ④ **완전 LBBD**(CP-SAT master + cut): 현재는 휴리스틱 no-good destroy(M4)로 근사. master를 CP-SAT로 올리는 건 별도 작업.
