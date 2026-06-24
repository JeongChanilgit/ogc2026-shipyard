# 다음 세션 시작 프롬프트 — OGC2026 set1 경쟁자 추월

> 아래 블록을 그대로 복사해서 다음 세션 첫 메시지로 붙여넣으면 된다.

---

OGC2026 set1 돌파 작업 이어서 해. **무슨 일이 있어도 경쟁자(set1 총 obj 1,139,442)를 이긴다.** 외부 라이브러리 설치·번들 OK (사용자 승인됨).

**먼저 읽어 (순서대로):**
1. `notes/research/INSIGHTS.md` §0 — 단일 진실 소스 (PIVOT/NEW-EXPLORATION 배너)
2. `notes/HYPOTHESES-VERIFY-2026-06-15.html` — H0(좌하단 진단) + H1~H13 가설·예측·검증절차·게이트
3. `notes/NEXT-EXPLORATION-HANDOFF-2026-06-15.html` — 13개 레버 상세 + 출처

**현황:** 활성 솔버 = 하이브리드(`src/myalgorithm.py` = best-of(legacy 옛솔버, `boxsolver.py` box-decomp)), **set1 = 1,312,961** (`baselines/hybrid_set1.json`). 경쟁자 1,139,442 → −173,519 추월 필요.

**근본 병목 (H0 확정):** 두 패커(`fastfloor._ft_search_pos`, box-decomp `_bl_fit_cells`)가 **좌하단(Bottom-Left) 그리디** — 후보를 (Y,X) 최저로 정렬해 첫 feasible 채택, 백트래킹·전역밀도목적 없음 → 틈 남김 → spill 과다 → **z3 패배**. 경쟁자는 2~4× 조밀하게 크레인-안전 패킹. 모든 패배는 z1=0, z3 지배. 최대 타깃 = prob_20(+90K)·prob_14(+48K)·prob_13(+37K)·prob_18(+34K).

**순차 검증·적용 (EV 순; 통과분만 gated 채택):**
- **Phase 1:** H1 spyrrow(SOTA 네스팅=최대 밀도 레버, 설치·번들 검증부터) · H2 Diagonal-Fill(우상단 추가) · H3 NFP-BLF(pyclipper) · H4 CP-SAT no_overlap_2d+energetic · H7 순서최적화(GRASP/beam)
- **Phase 2:** H5 raster-FFT · H6 jostle · H11 ALNS-밀도
- **Phase 3:** H8 LBBD(EJOR2024 구조동일) · H9 GLS-STA(크레인 대응, 조선 +12.7%) · H10 Gurobi(서버) · H12 15°근사 · H13 cumulative

**검증 규칙 (공통):** 각 가설 = 단일-베이 밀도 self-test → mini-gate(prob_13/14/20) → full set1 gate vs `baselines/hybrid_set1.json`. 게이트: set1 총 obj↓ · feasible · **never −1**(wall≤TL) · best-of 무회귀 · `OGC_*` flag gated · INSIGHTS에 결과 기록(반증도 보존).

**실행 주의:**
- 측정은 **env python 직접** 실행: `C:/Users/peter/anaconda3/envs/ogc2025/python.exe`. **`conda run` 금지** (4워커 CP-SAT 크래시). 하니스: `notes/research/_fstest.py`, `eval.py --set SET1`.
- 외부 wheel은 **eval env(Linux x86_64, py3.12)** 호환 확인 후 zip에 **번들**(서버 무인터넷), **15MB 제한** 주의.

**⚠ 병행 필수 — set2 −1 (실측):** legacy가 set2 시간초과 = prob_25 183.7s, prob_26 161.6s @TL120 → 서버면 −1(점수 파국). legacy TL-discipline(하드 데드라인+빠른 fallback) 보강이 실 ALL40 점수엔 set1 0.3M보다 더 중요. 신규 패커도 set2 never −1 보장.

**수정 금지:** `src/utils.py`(평가서버 덮어씀)·`baseline/`. `algorithm(prob_info, timelimit)` 시그니처 불변.
**백업:** fresh-start = `notes/research/myalgorithm-freshstart-2026-06-15.py` / `freshstart.py`; 옛 솔버 원본 = `archive/old-solver-src-2026-06-14/`.

먼저 H0(좌하단)을 self-test로 재확인하고, H1(spyrrow) 설치·베이패킹 검증부터 시작해.

---

## 부가 컨텍스트 (이 세션 요약)

- **회복 궤적:** 9,033,067(fresh-start 퇴보) → 1,385,779(옛 솔버 복원) → 1,312,961(하이브리드). 근본원인 = 옛 솔버의 **분리(decouple: 레이아웃 고정 + 1-D 타이밍 오라클)** 기법을 리셋에서 잃었던 것.
- **검증 완료(반증) 레버:** box-decomp/feasspill(congested z1 높음), cumulative+4워커(z1 152→123 천장), targeted-spill+oracle(옛 솔버로 수렴), CAP_TIGHT(무효), longer-TL(@300=@600 천장), UC_CPPACK(무효), 하이브리드(채택 1.31M). → 검증 가능한 기존 레버 소진, **신규 13 방법론으로 전환**.
- **상태 HTML:** `notes/research/STATUS-2026-06-15.html` (인스턴스별 표·레버·결정).
