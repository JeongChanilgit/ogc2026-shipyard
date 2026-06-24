# SESSION HANDOFF — 2026-06-14 Rebuild

> **Supersedes**: `SESSION-HANDOFF-2026-06-12-fastfloor.md` (delete or archive).
> Single source of truth for the next session.

---

> ## ⚠ UPDATE 2026-06-14 PM — §4 polygon-nester lever FALSIFIED (do NOT rebuild it)
>
> The "remaining lever = polygon-level dense nester" (§0/§4 below) was **built and
> empirically falsified**. Three distinct density levers all FAIL to beat BL under
> the online crane decode:
> 1. **LCA / Extreme-Point + contact-area placement** (`fastfloor._ft_search_pos_lca`,
>    gated `OGC_UC_NEST`, default OFF) — per-bay tardiness WORSE than BL across the
>    whole band sweep; full-solve obj prob_11 +7805. Max-contact fragments residual
>    free space for the EDD-ordered sequence. (`notes/devlog/probe_nest_density.py`,
>    `probe_nest_fullsolve.py`)
> 2. **Temporal pre-staggering** — the timing ORACLE already re-times entries
>    crane-safe-optimally on the fixed layout; naive pre-stagger is worse
>    (prob_17 catastrophic). (= handoff's own "timing-in-loop rejected".)
> 3. **Finer-raster geometry** — the unit raster over-estimates polygon footprint
>    by 31–40%, but finer cells (1/S, still sound) DON'T reduce tardiness
>    (mixed/negative): crane serialization is layer-stacking among co-present
>    blocks, not footprint-boundary rounding. (`notes/devlog/probe_fine_geom.py`)
>
> **Sharp new diagnosis (`notes/devlog/probe_assign_realize.py`):** the loss is a
> **REALIZE gap, not an assignment gap.** prob_17 our area-optimal assignment
> z3=**159 < competitor 222**, but it does NOT realize at z1=0 (z1=72); we over-spill
> to z3=384 to reach z1=0 while the competitor realizes z3=222 at z1=0 (~3.5× more
> z3-efficient spill). demand_peak: preferred bay foot=115% (>100%) at the release
> peak → some spill/stagger is unavoidable. The remaining theoretical lever (min-z3
> reassignment with a real-decode realize gate) = LBBD, already marginal. **The
> ceiling is fundamental to BL-greedy + per-bay-oracle; breaking it needs a global
> joint position+time+assignment optimizer (large, uncertain — baypack_cp's exact
> box version got only halfway).**
>
> **PRELIM REFRAME:** prelim opens 2026-06-15 14:00 KST → the competitor table is
> TRAIN-only; against the unknown field, rank=R−nb is maximised by minimising our
> obj robustly (= user directive "minimize objective, don't fixate on z1/z2/z3").
> Highest-value next work = **prelim-readiness (never −1 on unknown shapes/sizes,
> TL discipline) + validate on the new prelim instances** (user to drop them in
> `instances/` — they're behind the login portal), NOT more train-ceiling grinding.
> Submit path UNTOUCHED (10/20, `OGC_UC_NEST` default OFF, bit-identical). Full
> write-up: `notes/devlog/REFLECTIONS.md` (2026-06-14 PM entries) + the report
> `notes/structural-ceiling-2026-06-14.html`.

---

## 0. 30초 요약

| 항목 | 내용 |
|---|---|
| 제출 현황 | **10/20** (legacy 9/20 격파, 채택·검증·제출 가능) |
| 핵심 변화 | 신규 모듈 `uconstruct.py` = CP-SAT-guided 통합 constructive. `OGC_REBUILD_AUGMENT=1`이 SUBMIT_V2 default에 승격 |
| 천장 | **10/20 확인** (≥13가지 접근 전부 시도, win-set 고정) |
| 유일한 남은 레버 | **폴리곤 단위 조밀 nester** (Extreme-Point + LCA + 크레인 검증) — 다음 세션 메인 과제 |

승리 인스턴스: `{1,2,5,7,8,9,10,15,16,19}`. prob_15가 이번 세션의 신규 flip.

---

## 1. 지금 채택되어 돌아가는 것 (제출 경로)

**진입점**: `myalgorithm.py` ≈ line 5290, SUBMIT_V2 default-injection 블록 (`T≥60`).

```
OGC_REBUILD_AUGMENT=1  # SUBMIT_V2 블록 안에 하드코딩 (default ON)
```

**동작 흐름**:
1. `uconstruct.solve_unified` 를 `budget = min(45s, 0.35·T)` 로 선실행 → verified 해 stash
2. 나머지 시간: legacy 파이프라인 정상 실행
3. gate 직전 `("unified", sol)` 후보 추가 → best-of 선택
4. unified < legacy 이면 절대 채택 안 함 → **회귀 0 보장**

**가역**: `OGC_REBUILD_AUGMENT=0` 환경변수 → 정확히 legacy 동작.

**검증 결과**: full-20 paired ×2 (augment200 r1 + r2) = **10/20 양쪽 동일**, win-set 안정.

**제출 zip**: `submissions/v-unified-augment-10of20-20260614-120502.zip` (0.19 MB).

**smoke 체크**:
- prob_15: 46751 (WIN, 이전 legacy 50783, comp 48206)
- prob_1: 1499 (보존)

---

## 2. 신규 모듈 지도 + 플래그

| 모듈 | 역할 | default | 주요 플래그 |
|---|---|---|---|
| `src/uconstruct.py` | **augment 핵심** — criticality-order greedy, CP-SAT bay-target, crane-safe BY CONSTRUCTION | via AUGMENT | `OGC_REBUILD_UNIFIED`, `OGC_UC_CPSAT`(on), `OGC_UC_Z3DESCENT`(**off**, score-neutral), `OGC_UC_CPPACK`(**off**, 느림), `_BUDGET`, `_MAXBLK` |
| `src/rebuild.py` | W1~W4 LBBD 재설계 shell + AUGMENT 훅 | off | `OGC_REBUILD`(off), `OGC_W1..W4`, `OGC_REBUILD_AUGMENT`(**on via SUBMIT_V2**), `OGC_REBUILD_PACKER`(off), `OGC_REBUILD_EXACT`(off), `OGC_REBUILD_PCAP`(off) |
| `src/baypack_cp.py` | exact 베이별 CP-SAT 2D box-packing + 스케줄링 (`pack_bay_cp`, `improve_bay`) | off | `OGC_UC_CPPACK`로 uconstruct가 호출 |
| `src/packer.py` | repositioning LNS 패커 (LNS window-rebuild + swap + nudge, crane-safe) | off | `OGC_REBUILD_PACKER`(off) |

모두 `build_submission.py`가 `src/*.py` 자동 번들. uconstruct/baypack_cp/packer/rebuild 포함 확인됨.

---

## 3. 핵심 발견 — 왜 10/20이 천장인가

### 3.1 손실 구조

전 패배 인스턴스가 z3 지배 (z1=0 on 19/20, z3 ≈ 2–4× 경쟁자):

| inst | 우리 z3 | 경쟁자 z3 | obj 갭 |
|---|---|---|---|
| prob_11 | 355 (cppack) / 704 (base) | 167 | +43% |
| prob_17 | 297 (cppack) / 405 (base) | 222 | +26% |
| prob_3 | 200 (cppack) / 514 (base) | 94 | +25% |
| prob_6 | 601 (cppack) / 844 (base) | 345 | +29% |
| prob_18 | ~704 | 172 | 4× |
| prob_20 | ~783 + z1=7~12 구조 | 463 | 3~10× |

### 3.2 경쟁자의 전략

경쟁자는 **z2를 올리고 z3를 내린다** (w2≈5 ≪ w3≈133이라 이게 유리).
예: prob_3 경쟁자 z2=3654/z3=94 vs 우리 z2=700/z3=562.
선호 베이에 블록을 조밀하게 크레인-안전으로 패킹 → 퇴거(spill) 최소 → z3 낮음.

### 3.3 시도하고 기각한 접근 (13+가지)

W1~W4 (LBBD/cap-cut/ban-cut/exact decode) · timing-in-loop · raster rebuild · exact `_decode_bay`@300 · packer LNS · PCAP(packer-calibrated capacity) · unified constructive · CP-SAT guidance · z3-descent(z2↑z3↓) · exact CP-SAT box packer (`baypack_cp`, z3 절반이지만 flip 0).

**공통 결론**: box vs polygon 밀도 갭. CP-SAT packer가 bbox로 패킹 → 폴리곤 오목부 여유 낭비 → 경쟁자 수준 z3 불가. **남은 레버 = 폴리곤 단위 nester**.

---

## 4. 다음 세션 메인 과제 — 폴리곤 단위 조밀 nester

### 4.1 목표

선호 베이에 폴리곤 단위로 더 조밀하게 패킹 → spill 감소 → z3를 경쟁자 수준으로 → 근접 패배 flip → 13/20.

1순위 flip 타깃: prob_11 (z3 355→167 필요), prob_17 (297→222), prob_3 (200→94).

### 4.2 핵심 단순화 (설계 출발점)

동시 존재(co-present) 블록의 **footprint 비중첩 + 크레인 j≥k 안전** ⟹ 실현 가능. 따라서 "시간창 겹치는 블록만 폴리곤 비중첩"인 2D nester면 충분 — 별도 시간 스케줄러 불필요.

**주의**: 블록이 대부분 2-layer (`prob_3=86/100, prob_5=123/150, prob_12=171/200`). 표준 footprint-raster(fftconvolve) BLF는 크레인 j≥k를 무시 → 크레인-안전 불가. 반드시 기존 layer-aware primitives(`_ft_search_pos` / `fastfloor._verify`) 위에 구현해야 함.

### 4.3 권장 구현 설계 (Packer v2)

**Extreme-Point + LCA (Largest-Contact-Area) + diagonal-slide, 크레인 검증**:

```
후보 집합 = {베이 모서리} ∪ {이미 놓인 각 블록의 TL,TR,BR,BL 꼭짓점}
각 블록 × 후보점 × 방향:
  - BL-slide (y↑, x↑) 검증
  - TR-slide (y↓, x↓) 검증  — diagonal-fill (Kwon & Lee 2015)
  크레인 검증: fastfloor._verify / _ft_pair_ok
유효 위치 중 contact perimeter 최대인 것 선택  — LCA (Shang&Gu 2017, Koh 2008)
```

추가 옵션 (느린 refiner):
- **jostle re-pack** (Martinez-Sykora 2018): 전체 re-insert 반복으로 갭 채우기
- **MergeDJD** (Gardeyn 2026): 블록 쌍 사전병합 → 더 직각적 단위
- **Sparrow / jagua-rs**: Rust 구현, 포팅 필요

### 4.4 통합 위치

`uconstruct._pack_bay` / `_construct_cppack` 자리에 폴리곤 nester를 끼움.
augment 45s 캡 안에 들어오려면 per-bay budget ≤ 2~3s 목표. 초과 시 `OGC_UC_CPPACK` 처럼 gated OFF + unified budget 확대.

### 4.5 검증 순서

1. 단일 베이 self-test: prob_3 bay2 (ft_tard 19→?), prob_5 bay0 (ft_tard 69→?) — 면적초과(164%)라 일부는 퇴거 불가피, 비중첩 비율 측정
2. mini-gate prob_11 + prob_17 (fail-fast)
3. full-20 paired ×2 (채택 게이트)

---

## 5. 측정·검증 규칙

**하니스**: `notes/_capture20_aff.py` (conda env **ogc2025**, 4코어 affinity)

```powershell
# 실행 예시
conda run -n ogc2025 python notes/_capture20_aff.py `
  --instances ALL --timelimit 200 --tag <tag> `
  --env "OGC_REBUILD=1,OGC_REBUILD_UNIFIED=1,OGC_UC_CPPACK=1"
```

**채점**: `notes/devlog/score.py --dir <capdir> [--paired <dir2>]` (vs `notes/competitor-2026-06-11.json`)

**시퀀스 로그**: `notes/devlog/seqlog.py <tag>`

**단일 실행**: `notes/devlog/run_one.py <inst> --timelimit <s> --env "..."`

**채택 규칙**: **full-20 paired ×2** (미니게이트 prob_14+prob_20는 fail-fast 선별 전용)

**실험 기록**: `notes/devlog/experiments.jsonl` + `DEVLOG.md` (매 실험 자동 기록), `REFLECTIONS.md` (인사이트).

---

## 6. 절대 규칙 / 안전

- `src/utils.py` · `baseline/` **수정 금지**
- `algorithm(prob_info, timelimit)` 시그니처 **불변**
- 신규 코드: 전부 `src/` 안 + env-gated default OFF
- augment 패턴: 신규 해법 = best-of gate 통과해야 채택 → 회귀 0 구조 유지
- 아카이브: `archive/src-snapshot-2026-06-14-pre-rebuild.zip`
- build_submission.py가 `src/*.py` 전체 자동 번들 (uconstruct/baypack_cp/packer/rebuild 포함 확인됨)

---

## 7. 관련 메모리 / 문서

| 항목 | 경로 |
|---|---|
| 메모리 (전 과정 ★) | `ogc2026-rebuild-kickoff-2026-06-14` |
| 메모리 (제출 base) | `ogc2026-submit-profile-promoted` |
| 메모리 (검증 규칙) | `ogc2026-validate-full20` |
| 브리핑 HTML | `notes/rebuild-results-2026-06-14.html` |
| 패킹 리서치 | `notes/devlog/packing-research-2026-06-14.md` |
| 인사이트 로그 | `notes/devlog/REFLECTIONS.md` |
| 프리미티브 맵 | `notes/devlog/integration-map.md` |
| 전략 리서치 | `notes/strategy-research-2026-06-11.html` |
