# -*- coding: utf-8 -*-
"""Deterministic generator: build the Z1 literature+insights HTML from the cleaned JSON.
Insights authored by opus (main); paper tables rendered from notes/z1-papers-data.json (147 unique)."""
import json, re, sys, html
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(r"C:\claude-develop\OGC2026\notes\z1-papers-data.json")
OUT = Path(r"C:\claude-develop\OGC2026\notes\z1-literature-2026-06-06.html")
d = json.loads(DATA.read_text(encoding="utf-8"))
topics = d["topics"]
total_unique = d["total"]

CAT_NAMES = [
    "Shipyard Block Spatial Scheduling (SSP)",
    "Shipbuilding Block Stockyard & Stacking",
    "Crane Scheduling — Non-Crossing / Interference",
    "Container Pre-Marshalling & Block Relocation (j≥k analog)",
    "Single-Machine Total / Weighted Tardiness",
    "Parallel-Machine Total Weighted Tardiness",
    "RCPSP with Spatial / 2D Resources",
    "Temporal / Dynamic 2D Bin Packing with Due Dates",
    "Irregular Strip Packing / Nesting (NFP)",
    "Large Neighborhood Search (LNS / ALNS)",
    "Constraint Programming (CP-SAT / OR-Tools)",
    "Berth Allocation (space-time packing)",
    "Just-in-Time / Due-Date Scheduling & Timing DP",
    "Matheuristics & Logic-Based Benders Decomposition",
    "GA / Metaheuristics for Shipyard",
    "Time-Space Network & Dynamic Facility Layout",
    "Blocking Job-Shop / No-Wait (crane-hold analog)",
    "Combined 2D Packing + Scheduling (AM nesting)",
]

def esc(s):
    return html.escape(str(s or ""))

# distribute unique papers to first category of appearance
def norm(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:55]

displayed = set()
cats = []  # list of (name, [papers])
gidx = {}  # normtitle -> global number
counter = 0
for i, tp in enumerate(topics):
    name = CAT_NAMES[i] if i < len(CAT_NAMES) else tp.get("topic", "")[:60]
    bucket = []
    for p in tp.get("papers", []):
        k = norm(p.get("title", ""))
        if not k or k in displayed:
            continue
        displayed.add(k)
        counter += 1
        gidx[k] = counter
        bucket.append((counter, p))
    cats.append((name, bucket))

def paper_row(n, p):
    url = p.get("url", "")
    title = esc(p.get("title", ""))
    title_html = f'<a href="{esc(url)}" target="_blank" rel="noopener">{title}</a>' if url else title
    auth = esc(p.get("authors", ""))
    yr = esc(p.get("year", ""))
    ven = esc(p.get("venue", ""))
    meth = esc(p.get("method", ""))
    rel = esc(p.get("relevance", ""))
    meta = " · ".join(x for x in [auth, ven] if x)
    return f"""<tr id="p{n}">
  <td class="num">{n}</td>
  <td class="yr">{yr}</td>
  <td class="paper">
    <div class="ptitle">{title_html}</div>
    <div class="pmeta">{meta}</div>
    <div class="pm"><span class="lbl">Method</span> {meth}</div>
    <div class="pr"><span class="lbl">→ Z1 relevance</span> {rel}</div>
  </td>
</tr>"""

cat_sections = []
toc_cat = []
for ci, (name, bucket) in enumerate(cats):
    if not bucket:
        continue
    anchor = f"cat{ci}"
    toc_cat.append(f'<li><a href="#{anchor}">{esc(name)}</a> <span class="cnt">{len(bucket)}</span></li>')
    rows = "\n".join(paper_row(n, p) for n, p in bucket)
    cat_sections.append(f"""<section class="catsec" id="{anchor}">
  <h3>{ci+1}. {esc(name)} <span class="cnt">{len(bucket)} papers</span></h3>
  <table class="papers"><tbody>
{rows}
  </tbody></table>
</section>""")

# ---- INSIGHTS (opus-authored) ----
INSIGHTS = r"""
<section id="diagnosis">
<h2>핵심 진단 — OGC의 Z1은 "패킹 문제"가 아니라 "Blocking Job-Shop + Block-Relocation" 문제다</h2>
<p class="lead">147편을 가로지르는 단 하나의 수렴 결론: 크레인 수직접근 규칙(<b>j ≥ k</b>, "내 위/위층이 비어야 들고 난다")은
문헌에서 두 개의 잘 정의된 제약과 <b>구조적으로 동일</b>하다 —
(1) <b>Blocking / zero-buffer 제약</b>(Mascis &amp; Pacciarelli 2002, <a href="#p132">#132</a>: alternative-graph 모델),
(2) <b>Container Block-Relocation / Pre-Marshalling의 clear-above 제약</b>(<a href="#p26">#26</a>–<a href="#p35">#35</a>).
즉 우리 코드 분석에서 나온 결론 — "재배정·cut·튜닝·packing 전부 무효, tardy 블록은 베이가 75~94% 빈 채로 대기, 레버는 crane 직렬화" — 은
문헌이 정확히 예측하는 현상이다. <b>공간은 남아돈다. 부족한 자원은 "크레인 접근 시점"이다.</b></p>

<div class="callout warn">
<b>Z1 = 0 이 가능한가? (정직한 프레이밍)</b><br>
Block-Relocation 하한(Tanaka <a href="#p29">#29</a>, <a href="#p30">#30</a>, <a href="#p35">#35</a>)과 blocking-job-shop 이론상,
혼잡 인스턴스(예: prob_14)에는 <b>구조적 tardiness 하한 L* &gt; 0</b> 이 존재할 수 있다 — 어떤 배치·순서로도 모든 블록을 마감 내 뺄 수 없는 경우.
따라서 현실적·점수최적 목표는 <b>"Z1 = 0"이 아니라</b>:
<ol>
<li><b>per-bay 하한 L*를 계산</b>하고, <b>L* = 0 인 베이는 반드시 Z1 = 0 을 달성</b>(여기서 새는 tardiness가 "버그성 손실"),</li>
<li><b>L* &gt; 0 인 베이는 L*까지 gap을 닫는다</b>(달성 가능한 최선).</li>
</ol>
점수공식이 <code>R − nb</code>(−1 회피 1순위·동점 OK)이므로, "한 인스턴스 압도"보다 "모든 베이에서 달성가능 하한까지 닫기"가 정확히 옳은 방향이다.
</div>
</section>

<section id="insights">
<h2>적용 인사이트 — 우리 알고리즘에 어떻게 꽂을 것인가 (영향·노력순)</h2>
<p class="lead">각 인사이트에 <b>근거 논문</b>, <b>우리 코드의 정확한 진입점(file:line)</b>, <b>예상 영향</b>, <b>노력/리스크</b>를 명시했다.
코드 매핑은 <code>src/myalgorithm.py</code> / <code>src/parallel_decode.py</code> 정독(code-analyzer) 결과 기준.</p>

<div class="ins big">
<div class="ins-h"><span class="rank">①</span> SEQUENCE 와 TIMING 을 분리하라 — 고정 순서에 대한 <b>최적 타이밍 DP</b> (최대 레버, 저비용)</div>
<div class="ins-b">
<p><b>문헌:</b> 고정 시퀀스의 최적 시작시각은 <b>O(n²) DP로 정확히</b> 풀린다 — Hendel &amp; Sourd "optimal timing of a sequence"(<a href="#p106">#106</a>),
single-machine earliness–tardiness 빠른 이웃탐색(<a href="#p108">#108</a>), affine idleness 타이밍 DP(<a href="#p107">#107</a>).
JIT 스케줄링의 정설: <b>"무엇을 어떤 순서로"(NP-hard)와 "그 순서에 언제"(다항시간)를 쪼갠다.</b></p>
<p><b>우리 코드의 문제:</b> <code>_decode_bay</code>(myalgorithm.py:735)는 배치+타이밍을 한 번에 그리디로 묶고, 슬롯이 없으면
<code>_force_in_bay</code>(:811)로 빈 윈도우에 직렬화하며 EXIT=entry+proc(:738,:817)를 즉석 확정한다.
사후 보정 <code>_shift_tardy_intervals_verified</code>(:2016)는 18블록 × 14틱 국소탐색에 불과 — <b>이게 바로 정확 타이밍 DP의 불완전한 대용품</b>이라 prob_14에서 no-op이었다.</p>
<p><b>적용:</b> 베이별로 (현재 layout + 현재 크레인 순서)를 고정한 뒤, ENTRY/EXIT를 <b>정확 타이밍 DP</b>로 재계산해
<code>EXIT − ENTRY ≥ P</code>·<code>ENTRY ≥ R</code>·크레인 선후행을 만족하는 한에서 Σ tardiness를 최소화. layout/배정을 전혀 안 바꾸므로 <b>objective-safe</b>(Z2/Z3 불변, Z1만 ↓).
<code>_shift_tardy_intervals_verified</code>를 이 DP로 교체.</p>
<p class="tag"><span class="t imp">영향: 높음</span><span class="t eff">노력: 중</span><span class="t risk">리스크: 낮음 (geometry 불변)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">②</span> per-bay <b>tardiness 하한 L*</b> 를 계산해 탐색을 집중하고 종료를 판단하라</div>
<div class="ins-b">
<p><b>문헌:</b> Block-Relocation의 다항시간 하한 — Tanaka &amp; Takii exact + lower bounds(<a href="#p29">#29</a>), IDBB 신규 하한(<a href="#p30">#30</a>),
LB taxonomy(<a href="#p35">#35</a>), beam-search 하한(<a href="#p31">#31</a>). 병렬머신 tardiness 하한(<a href="#p47">#47</a>), arc-time-indexed 하한(<a href="#p48">#48</a>).</p>
<p><b>우리 코드의 문제:</b> 어디에도 "이 베이에서 피할 수 없는 tardiness가 얼마인가"를 모른다. 그래서 <code>_tardy_redecode_moves_verified</code>(:2088, 10블록/3채택)와
<code>_shift_*</code>가 <b>이미 L*에 도달한(더 못 줄이는) 베이에 시간을 낭비</b>하고, 정작 gap이 큰 베이를 얕게 판다(병목 #3·#4).</p>
<p><b>적용:</b> 각 베이에 <b>release/due 기반 single-machine tardiness LB</b> + <b>relocation LB</b>를 싸게 계산 →
(a) <code>L* = 0</code> 인데 현재 Z1 &gt; 0 인 베이를 <b>최우선</b>으로 재최적화(여기 손실은 100% 회수 가능), (b) <code>현재 Z1 == L*</code> 베이는 <b>건너뛰어</b> 176/180s 예산을 절약(병목 #4 직접 해소).</p>
<p class="tag"><span class="t imp">영향: 높음 (탐색 효율·예산)</span><span class="t eff">노력: 중</span><span class="t risk">리스크: 낮음 (읽기 전용 진단)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">③</span> <b>마감-인지 레이어/통로 배치</b> — tight-due 블록을 "위가 안 막히는" 셀에 선점 배치 (anticipatory placement)</div>
<div class="ins-b">
<p><b>문헌:</b> 미래 blocking을 줄이는 선제 배치가 핵심 레버임을 직접 보인 연구들 —
yard-crane anticipatory storage(<a href="#p14">#14</a>), 핸드셰이크/중립 레이어(<a href="#p21">#21</a>),
DRL이 "재배치 56% 감소"를 학습(<a href="#p9">#9</a>, <a href="#p11">#11</a>), RCI 혼잡-우선 dispatch(<a href="#p7">#7</a>).</p>
<p><b>우리 코드의 문제:</b> <code>_candidate_positions</code>는 top-edge 패킹만 보고, <code>_candidate_crane_pressure(_bbox)</code>(:510/:542)는 사후 <i>프록시</i>로만 쓰인다(병목 #2).
즉 "마감이 급한 블록 위에 다른 블록이 쌓여 j≥k가 막히는" 구조를 <b>배치 단계에서 예방하지 못한다.</b></p>
<p><b>적용:</b> 블록을 slack(=due−release−proc)로 정렬 → <b>tight-slack 블록을 "그 위 레이어가 비게 될/안 쌓일" 셀(접근 통로)에 먼저 배치</b>,
slack 큰 블록을 깊은/하부 셀로. <code>_decode_bay</code> 선택키(:783)에 <i>"이 배치가 다른 tight 블록의 j≥k 통로를 막는가"</i> 항을 추가(프록시 → 1급 결정요소로 승격).
pre-marshalling 정신: <b>배치 = 미래 retrieval 순서를 위한 사전정렬.</b></p>
<p class="tag"><span class="t imp">영향: 높음</span><span class="t eff">노력: 중~높음</span><span class="t risk">리스크: 중 (배치 변경 → feasibility 재검 필요)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">④</span> <b>Logic-Based Benders 2단계</b>로 배정 재최적화 깊이를 키워라 (master=배정+Z1 스케줄, sub=크레인-safe 패킹 feasibility + cut)</div>
<div class="ins-b">
<p><b>문헌:</b> 우리 문제의 <b>가장 가까운 출판된 아키텍처</b>는 Additive-Manufacturing의 nesting+scheduling 분해다 —
LBBD로 packing feasibility를 분리(<a href="#p145">#145</a>), combinatorial Benders로 batch-assign↔2D-pack 분해(<a href="#p115">#115</a>, <a href="#p146">#146</a>),
p-batch packing+sched LBBD 가속(<a href="#p116">#116</a>). 이론·레시피: Hooker LBBD(<a href="#p113">#113</a>, <a href="#p114">#114</a>), branch-and-check 서베이(<a href="#p121">#121</a>),
combinatorial Benders로 single-machine+2D packing(<a href="#p115">#115</a>).</p>
<p><b>우리 코드의 문제:</b> <code>_tardy_redecode_moves_verified</code>(:2088)는 효과가 있는 <b>유일한</b> 재배정 연산자지만 max 10블록/3채택으로 탐색이 얕다(병목 #3). 무작위 move일 뿐 구조적 컷이 없다.</p>
<p><b>적용:</b> <b>master</b>(MIP/CP-SAT): 베이배정 + 크레인순서로 Z1 최소화(정확 geometry는 완화). <b>sub</b>: 그 배정이 크레인-safe 패킹으로 실현가능한지 검사
— 우리는 이미 <code>run_parallel_bay_decode</code>(parallel_decode.py:288)라는 <b>per-bay 크레인-safe 디코더</b>를 가지고 있다(이게 곧 sub-problem feasibility oracle).
실패 시 <b>no-good cut</b>("이 블록집합을 이 베이들에 동시 배정 금지")을 master에 추가. branch-and-check로 master 재해결 비용 절감.</p>
<p class="tag"><span class="t imp">영향: 매우 높음 (구조적)</span><span class="t eff">노력: 높음</span><span class="t risk">리스크: 중~높음 (예산·복잡도)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">⑤</span> 작은/중간 베이는 <b>CP-SAT 정확모델</b>로 풀어라 (no_overlap_2d + cumulative + j≥k precedence) — 4-core·no-GPU 서버의 최적 무기</div>
<div class="ins-b">
<p><b>문헌:</b> "Packing by Scheduling"이 2D 배치를 interval 쌍 + <code>no_overlap_2d</code>(diffn)로 인코딩(<a href="#p92">#92</a>),
CP-SAT-LP 하이브리드 + LNS 포트폴리오 워커(<a href="#p87">#87</a>), 산업규모 job-shop CP-SAT 벤치(<a href="#p93">#93</a>), PyJobShop 즉용 모델(<a href="#p94">#94</a>),
실제 조선소 CP(버퍼+마감)(<a href="#p95">#95</a>). 전파엔진: time-table edge-finding(<a href="#p90">#90</a>), O(kn log n) edge-finding(<a href="#p91">#91</a>).</p>
<p><b>왜 우리 서버에 최적:</b> 평가서버는 4 CPU·GPU 없음·인터넷 차단. <b>CP-SAT(OR-Tools)는 순수 CPU에서 자체 멀티워커 LNS를 돌리는</b> 바로 그 도구다.</p>
<p><b>적용:</b> 블록 ≤ ~20 인 베이마다 CP-SAT 모델: ENTRY/EXIT = interval var, 공간 = <code>add_no_overlap_2d</code>, 크레인 j≥k = 조건부 precedence(위 셀 점유 블록의 lift 선후행), 목적 = Σ tardiness.
작은 베이를 <b>정확히 0(또는 L*)까지</b> 풀어 우리 그리디 디코드 결과를 대체/warm-start. 큰 베이는 ①②③에 맡김. 최종은 기존 official-checker 게이트(:3219/:3259)가 보증.</p>
<p class="tag"><span class="t imp">영향: 매우 높음 (작은 베이 Z1→0)</span><span class="t eff">노력: 높음</span><span class="t risk">리스크: 중 (시간상한·모델링)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">⑥</span> <b>tardiness-타겟 ALNS</b> destroy 연산자 + <b>증분 Z1 평가</b>로 같은 예산에 더 깊이 탐색</div>
<div class="ins-b">
<p><b>문헌:</b> ET-ALNS의 remove-tardy + 빠른 증분 목적함수 재평가(<a href="#p86">#86</a>),
unrelated parallel-batch + 2D packing ALNS(11 removal/7 insertion)(<a href="#p147">#147</a>),
Ropke–Pisinger ALNS 표준(<a href="#p80">#80</a>), berth+crane ALNS(<a href="#p84">#84</a>, <a href="#p104">#104</a>), ruin-and-recreate(<a href="#p79">#79</a>), adaptiveness 메타분석(<a href="#p85">#85</a>).</p>
<p><b>우리 코드의 문제:</b> <code>_local_search</code>(:1320)의 ALNS는 존재하나 연산자가 Z1을 직접 겨냥하지 않고, 후보 평가가 full re-decode라 반복수가 적다(병목 #3).</p>
<p><b>적용:</b> destroy를 <b>"worst-tardy removal"</b>(Z1 기여 최대 블록 + 그 블록의 크레인-blocker들을 함께 제거) / <b>"crane-cluster removal"</b>(한 수직 스택 통째)로,
repair를 <b>regret-k(마감 tight 우선 재삽입)</b>로. 핵심은 <b>증분 Z1 캐시</b> — 건드린 베이만 재평가해 반복수를 10× 늘림.</p>
<p class="tag"><span class="t imp">영향: 중~높음</span><span class="t eff">노력: 중</span><span class="t risk">리스크: 낮음 (기존 ALNS 확장)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">⑦</span> <b>탐색 수용</b>과 <b>최종 게이트</b>를 분리하라 — 내부는 accept-worse(SA), 반환은 안전 게이트 유지 (병목 #5 해소)</div>
<div class="ins-b">
<p><b>문헌:</b> berth SA가 (position,entry,exit)에서 accept-worse로 tardiness 탈출(<a href="#p97">#97</a>),
ship-block SA accept-worse(<a href="#p122">#122</a>), threshold-accepting/SA 비교(<a href="#p40">#40</a>), record-to-record(<a href="#p79">#79</a>).</p>
<p><b>우리 코드의 문제:</b> 최종 게이트가 <code>better_obj</code> <b>또는</b> <code>same_obj_lower_z1</code>(:3259-3264)만 채택 — 이건 <b>반환 안전장치로는 옳다</b>.
문제는 <b>내부 탐색까지 똑같이 탐욕적</b>이면, Z1을 잠깐 손해 보고 Z2를 풀어야 도달하는 더 낮은-Z1 분지에 절대 못 간다.</p>
<p><b>적용:</b> 내부 ALNS/redecode 수용을 <b>SA/threshold(일시적 목적 악화 허용)</b>로 바꾸되, <b>반환 직전 official-checker 게이트는 그대로</b> 둔다 —
"중간엔 언덕을 내려가도, 최종 제출은 floor보다 나쁘면 절대 반환 안 함". 이러면 objective-safe를 깨지 않고 더 좋은 Z1 분지에 도달.</p>
<p class="tag"><span class="t imp">영향: 중 (탈출 능력)</span><span class="t eff">노력: 낮음</span><span class="t risk">리스크: 낮음 (최종 게이트 불변)</span></p>
</div></div>

<div class="ins big">
<div class="ins-h"><span class="rank">⑧</span> 순서 시드를 <b>Emmons dominance + ATC dispatch</b>로 — 거의 공짜의 즉효</div>
<div class="ins-b">
<p><b>문헌:</b> Emmons 쌍대지배규칙(<a href="#p36">#36</a>, <a href="#p112">#112</a>)이 최적해에서 많은 블록쌍의 선후를 <b>탐색 없이 고정</b>,
Lawler 정확 DP(<a href="#p37">#37</a>), ATC look-ahead dispatch(<a href="#p39">#39</a>, <a href="#p45">#45</a>), Moore–Hodgson(지각 개수 최소, O(n log n))(<a href="#p111">#111</a>).</p>
<p><b>우리 코드의 문제:</b> <code>_orderings</code>(:848)는 slack + crane-complexity 기반 EDD 타이브레이크. 평범한 EDD는 가중 tardiness에 약하다.</p>
<p><b>적용:</b> <code>_orderings</code>·<code>_tardiness_seed</code>(:1057)의 1차 정렬을 <b>ATC index</b>(=urgency×due-slack 지수가중)로 교체하고,
<b>Emmons 규칙</b>으로 확정 가능한 쌍의 선후를 고정해 후속 탐색공간을 줄인다. 베이당 O(n log n), 즉시 적용 가능.</p>
<p class="tag"><span class="t imp">영향: 중 (저렴한 baseline 상승)</span><span class="t eff">노력: 낮음</span><span class="t risk">리스크: 낮음</span></p>
</div></div>
</section>

<section id="roadmap">
<h2>권장 구현 로드맵 (objective-safe · 시간예산 우선)</h2>
<p class="lead">병목 #4(176.7/180s)가 살아있으므로 <b>"먼저 싸고 안전한 즉효 → 그 다음 구조적 변경"</b> 순서. 각 단계는 기존 official-checker 게이트로 보호되어 −1 리스크 없음.</p>
<table class="road">
<thead><tr><th>Wave</th><th>무엇</th><th>인사이트</th><th>근거</th><th>리스크</th></tr></thead>
<tbody>
<tr><td><b>0 · 진단</b></td><td>per-bay tardiness 하한 L* 계산 + "L*=0인데 Z1&gt;0" 베이 식별 (읽기 전용)</td><td>②</td><td>#29 #35 #47</td><td>없음</td></tr>
<tr><td><b>1 · 즉효</b></td><td>ATC/Emmons 순서 시드(⑧) + 정확 타이밍 DP로 <code>_shift_*</code> 교체(①) + 내부 SA 수용(⑦)</td><td>① ⑦ ⑧</td><td>#106 #36 #39</td><td>낮음 (geometry 불변, 최종 게이트 유지)</td></tr>
<tr><td><b>2 · 배치</b></td><td>마감-인지 레이어/통로 배치(③) — <code>_decode_bay</code> 선택키에 j≥k 통로보존 항 승격</td><td>③</td><td>#14 #21 #9</td><td>중 (feasibility 재검)</td></tr>
<tr><td><b>3 · 구조</b></td><td>작은 베이 CP-SAT 정확해(⑤) + tardiness-타겟 ALNS·증분평가(⑥)</td><td>⑤ ⑥</td><td>#92 #87 #86</td><td>중 (시간상한 관리)</td></tr>
<tr><td><b>4 · 통합</b></td><td>LBBD 2단계(④): master 배정·sub = <code>run_parallel_bay_decode</code> feasibility oracle + no-good cut</td><td>④</td><td>#145 #115 #113</td><td>높음 (예산·복잡도)</td></tr>
</tbody></table>
<p class="note">※ Wave 1은 layout/배정을 바꾸지 않아 Z2/Z3에 영향이 없다(순수 Z1↓) — 가장 먼저, 가장 안전하게 Z1을 끌어내릴 수 있는 구간. Wave 0은 "어디가 회수 가능한 손실인가"를 알려줘 Wave 1~4의 탐색을 집중시킨다.</p>
</section>

<section id="mapping">
<h2>Method → 우리 코드 매핑 (요약)</h2>
<table class="map">
<thead><tr><th>우리 병목 (code)</th><th>file:line</th><th>문헌 처방</th><th>대표 논문</th></tr></thead>
<tbody>
<tr><td>베이 내 크레인 직렬화 = 단일 EDD 사슬</td><td>_decode_bay :735 / force :811</td><td>Blocking Job-Shop alternative-graph; sequence↔timing 분리</td><td>#132 #133 #106</td></tr>
<tr><td>레이어/통로 배치 미최적화</td><td>_candidate_positions; pressure :510</td><td>anticipatory placement; pre-marshalling clear-above</td><td>#14 #21 #26 #9</td></tr>
<tr><td>배정 재최적화 깊이 부족</td><td>_tardy_redecode_moves :2088</td><td>LBBD master/sub + no-good cut; tardiness-ALNS</td><td>#145 #115 #86 #147</td></tr>
<tr><td>타이밍 보정이 14틱 국소탐색</td><td>_shift_tardy_intervals :2016</td><td>정확 O(n²) 타이밍 DP (고정 순서)</td><td>#106 #107 #108</td></tr>
<tr><td>시간예산 176.7/180s</td><td>work_deadline :2479</td><td>per-bay 하한으로 탐색 가지치기; CP-SAT/beam 시간상한</td><td>#29 #31 #34 #87</td></tr>
<tr><td>게이트 비대칭(탐색까지 탐욕)</td><td>gate :3259 / z1 gate :2840</td><td>탐색 SA accept-worse, 반환만 안전게이트</td><td>#97 #122 #40</td></tr>
<tr><td>순서 시드가 평EDD</td><td>_orderings :848 / seed :1057</td><td>ATC dispatch + Emmons dominance</td><td>#39 #45 #36 #112</td></tr>
<tr><td>작은 베이 미정확화</td><td>(전역 그리디)</td><td>CP-SAT no_overlap_2d + cumulative + j≥k</td><td>#92 #94 #87 #95</td></tr>
</tbody></table>
</section>
"""

# stats
cat_counts = [(CAT_NAMES[i] if i < len(CAT_NAMES) else topics[i].get("topic","")[:40], len(b)) for i,(_,b) in enumerate(cats)]
rendered = sum(len(b) for _, b in cats)

CSS = r"""
:root{--bg:#0f1419;--panel:#171d26;--panel2:#1d2530;--ink:#e6edf3;--mut:#8b98a8;--line:#2a3441;--acc:#4ea1ff;--acc2:#ffb454;--good:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Malgun Gothic",sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px}
header.top{padding:48px 0 26px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#131a24,transparent)}
header.top h1{margin:0 0 8px;font-size:30px;letter-spacing:-.3px}
header.top .sub{color:var(--mut);font-size:16px}
header.top .meta{margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}
.pill{background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:5px 13px;font-size:13px;color:var(--mut)}
.pill b{color:var(--ink)}
nav.toc{position:sticky;top:0;z-index:20;background:rgba(15,20,25,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:8px}
nav.toc .wrap{display:flex;gap:8px;flex-wrap:wrap}
nav.toc a{font-size:13px;color:var(--mut);padding:4px 10px;border-radius:7px}
nav.toc a:hover{background:var(--panel2);color:var(--ink);text-decoration:none}
h2{font-size:23px;margin:42px 0 14px;padding-top:10px;letter-spacing:-.2px}
h3{font-size:18px;margin:26px 0 12px}
.lead{color:#c4cfdb;font-size:15.5px}
.callout{border-radius:12px;padding:16px 18px;margin:18px 0;border:1px solid var(--line);background:var(--panel)}
.callout.warn{border-color:#7a5a12;background:#211b0d}
.callout ol{margin:8px 0 0;padding-left:20px}
.ins{background:var(--panel);border:1px solid var(--line);border-radius:13px;margin:16px 0;overflow:hidden}
.ins-h{padding:15px 18px;font-size:16.5px;font-weight:700;background:var(--panel2);border-bottom:1px solid var(--line);display:flex;align-items:flex-start;gap:10px}
.rank{display:inline-flex;min-width:30px;height:30px;align-items:center;justify-content:center;background:var(--acc);color:#06101d;border-radius:8px;font-weight:800;flex:none}
.ins-b{padding:6px 18px 14px}
.ins-b p{margin:11px 0}
.ins-b b{color:#fff}
.tag{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px!important}
.t{font-size:12.5px;padding:3px 10px;border-radius:7px;border:1px solid var(--line)}
.t.imp{background:#0f2a18;border-color:#1c5132;color:#5fd07e}
.t.eff{background:#26210d;border-color:#5a4a12;color:#e8c45a}
.t.risk{background:#241620;border-color:#5a2440;color:#e58fb0}
code{background:#0b0f15;border:1px solid var(--line);border-radius:5px;padding:1px 6px;font:13px/1.4 "SF Mono",Consolas,monospace;color:#ffcf8a}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}
.road th,.road td,.map th,.map td{border:1px solid var(--line);padding:9px 11px;text-align:left;vertical-align:top}
.road th,.map th{background:var(--panel2);color:#cdd8e4;font-weight:600}
.road tr:nth-child(even),.map tr:nth-child(even){background:#141a23}
table.papers{font-size:14px}
.catsec{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:6px 18px 14px;margin:16px 0}
.catsec h3{display:flex;align-items:baseline;gap:10px}
.cnt{font-size:12.5px;color:var(--mut);font-weight:500;background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:2px 9px}
table.papers td{border-bottom:1px solid var(--line);padding:11px 8px;vertical-align:top}
table.papers tr:last-child td{border-bottom:none}
td.num{color:var(--acc2);font-weight:700;width:34px;font-variant-numeric:tabular-nums}
td.yr{color:var(--mut);width:48px;font-variant-numeric:tabular-nums}
.ptitle{font-weight:600;font-size:14.5px;color:#eef3f8}
.pmeta{color:var(--mut);font-size:12.5px;margin:2px 0 6px}
.pm,.pr{font-size:13.5px;margin:3px 0;color:#c2cdda}
.lbl{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);min-width:96px}
.pr .lbl{color:var(--good)}
.note{color:var(--mut);font-size:13.5px}
footer{border-top:1px solid var(--line);margin-top:50px;padding:24px 0 60px;color:var(--mut);font-size:13px}
.toc-cats{columns:2;gap:24px;margin:10px 0}
.toc-cats li{margin:3px 0}
@media(max-width:760px){.toc-cats{columns:1}nav.toc{position:static}}
"""

toc_links = """
<a href="#diagnosis">진단</a>
<a href="#insights">적용 인사이트 ①–⑧</a>
<a href="#roadmap">로드맵</a>
<a href="#mapping">Method→코드</a>
<a href="#papers">논문 147편</a>
"""

cat_index_html = "<ul class='toc-cats'>" + "".join(toc_cat) + "</ul>"

doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OGC2026 — Z1(Tardiness)→0 문헌·인사이트</title>
<style>{CSS}</style></head>
<body>
<header class="top"><div class="wrap">
<h1>OGC 2026 — Z1(Tardiness) → 0 을 위한 문헌 리뷰 &amp; 적용 인사이트</h1>
<div class="sub">조선소 블록 배치·스케줄링의 크레인(j≥k) 직렬화 tardiness를 줄이는 방법 — 147편 정밀 서치 + 우리 코드 매핑</div>
<div class="meta">
<span class="pill"><b>{total_unique}</b> 고유 논문</span>
<span class="pill"><b>{len([1 for _,b in cats if b])}</b> 주제군</span>
<span class="pill">서치: <b>haiku</b> ×18 병렬</span>
<span class="pill">합성: <b>opus</b></span>
<span class="pill">2026-06-06</span>
</div>
</div></header>

<nav class="toc"><div class="wrap">{toc_links}</div></nav>

<main class="wrap">
{INSIGHTS}

<section id="papers">
<h2>문헌 {total_unique}편 — 주제군별</h2>
<p class="lead">18개 검색 주제로 haiku web-researcher 18개를 병렬 팬아웃해 수집(177건) 후 중복 제거({total_unique}편). 각 논문은 첫 등장 주제군에 1회 배치. 번호는 위 인사이트의 <a href="#p1">#n</a> 인용과 일치.</p>
{cat_index_html}
{''.join(cat_sections)}
</section>
</main>

<footer><div class="wrap">
생성: 2026-06-06 · 데이터 <code>notes/z1-papers-data.json</code> · 코드 매핑 <code>src/myalgorithm.py</code>·<code>src/parallel_decode.py</code> (code-analyzer 정독).
링크는 수집 당시 haiku가 제시한 출처(arXiv/DOI/publisher/Scholar) — 인용 전 확인 권장. 일부 URL은 Scholar 검색 링크일 수 있음.
</div></footer>
</body></html>"""

OUT.write_text(doc, encoding="utf-8")
print("WROTE", OUT, f"({OUT.stat().st_size} bytes)")
print("rendered papers:", rendered, "/ unique", total_unique)
print("categories with papers:", len([1 for _,b in cats if b]))
for nm,c in cat_counts:
    print(f"  {c:2d}  {nm}")
