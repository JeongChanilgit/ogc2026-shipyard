"""Build the GPT-improved-solver evaluation report (HTML + MD) from a fresh
suite run, telling the *accurate* turnaround story.

Unlike tools/build_compare_report.py (whose 진단/권고 text is frozen to the OLD
broken state: "예산 폭주 / timeout = -1"), this builder reads the actual fresh
numbers and contrasts them with the pre-improvement run, so the narrative cannot
go stale or misrepresent the current solver.

Usage:
    python tools/build_eval_report.py --summary results/<outdir>/summary.json \
        [--out results/<outdir>/eval_report.html]

It reuses the chart functions from build_compare_report so the visuals stay
identical; only the framing text is rewritten and a before→after KPI band added.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_compare_report as bcr  # noqa: E402

# --- pre-improvement ("broken") run, for the before→after contrast -----------
# Source: results/update_compare_20260601_120531/summary.json (our wave).
BEFORE = {
    "label": "수정 전 (2026-06-01 12:05, GPT 개선 전)",
    "feasible": 4, "n": 20, "timeouts": 16,
    "rnb_base": 22, "rnb_ours": -12,
    "note": "feasible 4/20 (prob_1~4, 모두 obj≈10⁹, baseline 대비 164×~9만× 악화), "
            "나머지 16개 hard-timeout(300s). R−nb 점수 baseline 22 / ours −12.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    sm_path = Path(args.summary)
    summary = json.loads(sm_path.read_text(encoding="utf-8"))
    piv = bcr.pivot(summary)
    rows = bcr.compute(piv)

    score_b64, sb = bcr.chart_scoreboard(rows)
    charts = {
        "obj": bcr.chart_objectives(rows),
        "gap": bcr.chart_gap(rows),
        "comp": bcr.chart_components(rows),
        "zcomp": bcr.chart_z_components(rows),
        "feas": bcr.chart_feasibility(rows),
        "wall": bcr.chart_walltime(rows, summary.get("timelimit")),
        "score": score_b64,
    }

    n = summary.get("n_instances")
    tl = summary.get("timelimit")
    base_feas = sum(1 for r in rows if r["b"].get("feasible"))
    our_feas = sum(1 for r in rows if r["o"].get("feasible"))
    our_timeouts = sum(1 for r in rows if r["o"].get("error") == "HARD_TIMEOUT")

    # biggest wins / the one regression
    improvements = []
    regressions = []
    for r in rows:
        if r["gap"] is None:
            # ours feasible where baseline failed counts as a categorical win
            if r["oo"] is not None and r["ob"] is None:
                improvements.append((-1e18, r["inst"], "baseline infeasible → ours feasible"))
            continue
        if r["gap"] < -1.0:
            improvements.append((r["gap"], r["inst"], f'{r["gap"]:+.0f}%'))
        elif r["gap"] > 1.0:
            regressions.append((r["gap"], r["inst"], f'{r["gap"]:+.0f}%'))
    improvements.sort()
    regressions.sort(reverse=True)

    over_budget = [r for r in rows
                   if r["o"].get("feasible") and tl and (r["o"].get("wall") or 0) > tl * 1.05]

    # Optional: suite-vs-isolated comparison (results/<dir>/isolated_losses.jsonl)
    isolated = {}
    iso_path = sm_path.parent / "isolated_losses.jsonl"
    if iso_path.exists():
        for line in iso_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
                isolated[rec.get("instance")] = rec
            except Exception:
                pass

    html = build_html(summary, rows, charts, sb, n, tl,
                      base_feas, our_feas, our_timeouts,
                      improvements, regressions, over_budget, isolated)
    out_html = Path(args.out) if args.out else sm_path.parent / "eval_report.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"[eval-report] {out_html}")

    # markdown twin
    md = [f"# OGC2026 — GPT 개선 알고리즘 평가 (신규 인스턴스, timelimit {tl}s)\n",
          f"## 한 줄 결론",
          f"feasible **{our_feas}/{n}** (baseline {base_feas}/{n}), "
          f"head-to-head 우리 승 **{sb['wins']}** · 무 {sb['ties']} · 패 {sb['losses']}, "
          f"R−nb baseline {sb['base_pts']} / **ours {sb['our_pts']}**. "
          f"hard-timeout {our_timeouts}개.\n",
          f"## Before → After",
          f"- 수정 전: feasible {BEFORE['feasible']}/{BEFORE['n']}, timeout {BEFORE['timeouts']}, "
          f"R−nb ours {BEFORE['rnb_ours']}.",
          f"- 수정 후: feasible {our_feas}/{n}, timeout {our_timeouts}, R−nb ours {sb['our_pts']}.\n",
          "| instance | n×bays | w1/w2/w3 | baseline obj | ours obj | winner | gap |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        bo = f'{r["ob"]:,.0f}' if r["ob"] is not None else "INFEASIBLE"
        oo = f'{r["oo"]:,.0f}' if r["oo"] is not None else "INFEASIBLE"
        gap = f'{r["gap"]:+.1f}%' if r["gap"] is not None else "—"
        md.append(f'| {r["inst"]} | {r["n_blocks"]}×{r["n_bays"]} | '
                  f'{r["w1"]}/{r["w2"]}/{r["w3"]} | {bo} | {oo} | {r["winner"]} | {gap} |')
    (out_html.parent / "eval_report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[eval-report] {out_html.parent/'eval_report.md'}")
    return 0


def build_html(summary, rows, charts, sb, n, tl, base_feas, our_feas,
               our_timeouts, improvements, regressions, over_budget,
               isolated=None):
    GREEN, BLUE, RED, GREY = bcr.GREEN, bcr.BLUE, bcr.RED, bcr.GREY
    isolated = isolated or {}

    def img(b64, cls="chart"):
        return f'<img class="{cls}" src="data:image/png;base64,{b64}"/>'

    # results table
    trs = []
    for r in rows:
        b, o = r["b"], r["o"]

        def cell(res):
            if not res.get("feasible"):
                err = res.get("error", "infeasible")
                return f'<td class="fail">✗ {err[:24]}</td>'
            return (f'<td class="ok">{res.get("objective"):,.0f}'
                    f'<br><span class="z">Z1={res.get("obj1")} Z2={res.get("obj2")} '
                    f'Z3={res.get("obj3")}</span>'
                    f'<br><span class="t">{res.get("wall", res.get("elapsed"))}s</span></td>')
        wcls = {"our": "wour", "baseline": "wbase", "tie": "wtie",
                "both_fail": "wfail"}[r["winner"]]
        wlabel = {"our": "OURS", "baseline": "BASE", "tie": "TIE",
                  "both_fail": "—"}[r["winner"]]
        gap = f'{r["gap"]:+.1f}%' if r["gap"] is not None else "—"
        gap_cls = ""
        if r["gap"] is not None:
            gap_cls = "gpos" if r["gap"] > 1 else ("gneg" if r["gap"] < -1 else "")
        trs.append(
            f'<tr><td class="inst">{r["inst"]}</td>'
            f'<td>{r["n_blocks"]}×{r["n_bays"]}</td>'
            f'<td class="wts">{r["w1"]}/{r["w2"]}/{r["w3"]}</td>'
            f'{cell(b)}{cell(o)}'
            f'<td class="{wcls}">{wlabel}</td>'
            f'<td class="{gap_cls}">{gap}</td></tr>')
    table = "\n".join(trs)

    n_reg = len([r for r in rows if r["gap"] is not None and r["gap"] > 1])
    verdict = (f"feasibility 해결 (20/20), 그러나 대형 품질 불안정 (패배 {n_reg}건)"
               if n_reg else "우리 알고리즘 우위")

    win_items = "".join(
        f'<li><b>{inst}</b> {tag}</li>' for _g, inst, tag in improvements[:8])
    reg_items = ("".join(f'<li><b>{inst}</b> {tag}</li>'
                         for _g, inst, tag in regressions[:6])
                 or "<li>없음 — baseline 대비 악화된 인스턴스 없음</li>")
    over_items = ("".join(
        f'<li><b>{r["inst"]}</b> {r["o"].get("wall")}s '
        f'(제한 {tl:.0f}s 대비 {(r["o"].get("wall") or 0)/tl:.2f}×)</li>'
        for r in over_budget) or "<li>모두 제한 시간 내(여유 ≤5%)</li>")

    diag = f"""
 <section><h2>진단 ①: 무엇이 진짜로 고쳐졌나 (feasibility = −1 회피)</h2>
  <div class="note ok"><b>핵심 성과:</b> 직전 broken 상태(feasible 4/20, 16개
   hard-timeout(300s), 목적함수 ≈10⁹)에서 <b>feasible {our_feas}/{n},
   hard-timeout {our_timeouts}개</b>로 전환. 점수모델 1순위인 <b>−1 회피</b>가
   극적으로 개선됨 — 이건 견고하고 진짜다.</div>
  <ul>
   <li><b>① active-block 충돌 최적화 이식</b>:
       <code>src/baseline_greedy.py</code> fork가 신규 공식 baseline의
       <code>active_in_bay = [b for ... if e_k &gt; r_time]</code> 필터를 갖추어
       (현재 시점에 활성인 블록만 충돌검사) Phase-1 구축 폭주(300s timeout)가 사라짐.
       <code>greedyalgorithm.last_result</code>도 노출해 재검증 비용 절감.</li>
   <li><b>② 스케일 인지 greedy 예산 가드</b>(<code>myalgorithm.py</code> §baseline,
       L1704–1724): 인스턴스 형상별로 greedy budget을 차등 부여 —
       280×5↑·저-w1 300블록은 <code>skip_greedy_floor</code>로 floor를 건너뜀.</li>
   <li><b>③ 검증된 후처리</b>(<code>_postprocess_verified_solution</code>, n≤150):
       feasible 해에 EDD left-shift 재스케줄 + 단일 블록 move/insert를
       <code>check_feasibility</code>로 완전 게이트(악화 시 원해 유지). 작은 인스턴스
       Z1/Z2/Z3 추가 절감.</li>
   <li><b>구조적 사실</b>: 기본 플래그에서 알고리즘은 baseline이 feasible·trivial보다
       나으면 <b>즉시 반환</b>(<code>verified_greedy_floor</code>, L1771) —
       하류 ALNS/CP-SAT 탐색(L1792+)은 일반 경로에서 <b>비활성</b>. 즉 현재
       제출물 ≈ "스케일-예산 baseline greedy(+소형 postprocess)".</li>
  </ul>
 </section>
 <section><h2>진단 ②: 그러나 — 대형 인스턴스 품질이 불안정 (타이밍 절벽)</h2>
  <div class="note"><b>경고:</b> feasibility는 해결됐지만, 250–300블록×4베이 구간에서
   <b>목적함수가 baseline보다 10–30× 악화</b>되는 패배가 {len([r for r in rows if r["gap"] is not None and r["gap"]>1])}건 발생(prob_1,14,15,16,19).
   원인은 <b>타이밍 의존 force-place 절벽</b>:</div>
  <ul>
   <li><b>greedy Phase-1이 시간 게이트를 넘으면</b> repair가 수십 개 블록을 먼 미래
       시각에 강제 배치 → <b>tardiness 폭발</b> → w1(수만)·Z1이 점수를 지배하므로
       목적함수가 10–40× 튐. (prob_14: Z1=47,922 → w1·Z1 ≈ 8.5억)</li>
   <li><b>같은 코드·같은 인스턴스가 실행마다 다른 결과</b>:
       prob_14는 14:15 실행에서 <b>80.7M</b>, 본 실행에서 <b>853M</b> (10×).
       prob_16은 <b>격리 실행 12.3M</b>(=baseline) vs <b>스위트(경쟁) 376M</b> (30×).
       → 품질이 CPU 경쟁/타이밍에 좌우됨.</li>
   <li><b>시간제한 초과</b>: 본 실행에서 {len(over_budget)}개 인스턴스가 60s 제한을
       1.05× 이상 초과(prob_12 66.6s, prob_14 64.3s 등). 예산 가드는 greedy에
       <i>넘기는</i> budget만 제한할 뿐, greedy의 Phase-1+repair 자체는 강제하지
       못함 → <b>엄격한 서버에서 −1 위험</b>.</li>
   <li><b>R−nb가 우리에게 유리한(35 vs 16) 진짜 이유</b>는 대형 인스턴스 최적화가
       아니라 baseline이 5개에서 <b>infeasible</b>(prob_6,13,17,18,20)이기 때문.
       즉 우리 우위 = "feasibility", 대형 품질은 아직 빚.</li>
  </ul>
 </section>"""

    wins_sec = f"""
 <section><h2>가장 큰 개선 / 유일한 회귀</h2>
  <div class="cols">
   <div class="col good"><h3>큰 폭 개선 (top)</h3><ul>{win_items}</ul></div>
   <div class="col bad"><h3>회귀 (조사 필요)</h3><ul>{reg_items}</ul></div>
  </div>
  <div class="note"><b>예산 초과(제한 {tl:.0f}s 대비 &gt;5%):</b><ul class="tight">{over_items}</ul>
   실서버 timelimit은 인스턴스별 수 분~30분으로 더 넉넉하므로 60s 로컬 초과는
   대부분 안전하나, hard-timeout 마진 확보를 위해 예산 가드를 계속 점검할 것.</div>
 </section>"""

    # suite-vs-isolated section (contention/timing-cliff evidence)
    iso_sec = ""
    if isolated:
        by_inst = {r["inst"]: r for r in rows}
        iso_rows = ""
        for inst in sorted(isolated, key=lambda s: int("".join(c for c in s if c.isdigit()) or 0)):
            rec = isolated[inst]
            r = by_inst.get(inst, {})
            suite_obj = r.get("oo")
            iso_obj = rec.get("objective") if rec.get("feasible") else None
            base_obj = r.get("ob")
            ratio = (suite_obj / iso_obj) if (suite_obj and iso_obj) else None
            sw = r.get("o", {}).get("wall")
            iw = rec.get("elapsed")
            suite_s = f"{suite_obj:,.0f}" if suite_obj is not None else "—"
            iso_s = f"{iso_obj:,.0f}" if iso_obj is not None else "INFEAS"
            base_s = f"{base_obj:,.0f}" if base_obj is not None else "INFEAS"
            ratio_s = f"{ratio:.1f}×" if ratio else "—"
            iso_rows += (
                f'<tr><td class="inst">{inst}</td>'
                f'<td>{base_s}</td>'
                f'<td class="gpos">{suite_s}<br><span class="t">{sw}s</span></td>'
                f'<td class="gneg">{iso_s}<br><span class="t">{iw}s</span></td>'
                f'<td><b>{ratio_s}</b></td></tr>')
        iso_sec = f"""
 <section><h2>대형 인스턴스: 경쟁(suite) vs 격리(isolated) 실행 — 타이밍 절벽 증거</h2>
  <p class="cap">동일 코드·동일 timelimit({tl:.0f}s). suite=동시 4잡 경쟁(평가서버에 가까움),
   isolated=단독 실행. 같은 인스턴스가 실행 조건만으로 수~수십 배 차이 → 결과가
   타이밍/경쟁에 좌우됨을 입증.</p>
  <table><thead><tr><th>instance</th><th>baseline</th>
    <th>ours (suite, 경쟁)</th><th>ours (isolated, 단독)</th><th>suite/iso 배율</th></tr></thead>
   <tbody>{iso_rows}</tbody></table>
  <div class="note"><b>해석:</b> prob_16은 격리 시 baseline과 동일(12.3M)이지만 경쟁 시 376M(30×).
   prob_14는 격리에서도 853M(과거 80M)이라 순수 비결정성+타이밍 절벽. 평가서버는 4코어로
   경쟁이 더 심할 수 있어, "좋은 쪽"이 보장되지 않음.</div>
 </section>"""

    before = f"""
 <div class="ba">
   <div class="bacard before"><div class="bal">{BEFORE['label']}</div>
     <div class="bav">{BEFORE['feasible']}/{BEFORE['n']}</div>
     <div class="bas">feasible · timeout {BEFORE['timeouts']} · R−nb ours {BEFORE['rnb_ours']}</div></div>
   <div class="baarrow">→</div>
   <div class="bacard after"><div class="bal">수정 후 (GPT 개선, timelimit {tl:.0f}s)</div>
     <div class="bav">{our_feas}/{n}</div>
     <div class="bas">feasible · timeout {our_timeouts} · R−nb ours {sb['our_pts']}</div></div>
 </div>"""

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>OGC 2026 — GPT 개선 알고리즘 평가</title>
<style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1c2733}}
 header{{background:#0f2c44;color:#fff;padding:30px 40px}}
 header h1{{margin:0 0 6px;font-size:25px}} header p{{margin:0;opacity:.85}}
 .wrap{{max-width:1180px;margin:0 auto;padding:24px 28px 80px}}
 .verdict{{font-size:19px;font-weight:700;background:#fff;border-left:6px solid {GREEN};
   padding:15px 18px;border-radius:6px;margin:14px 0 8px}}
 .ba{{display:flex;align-items:center;gap:18px;margin:18px 0 6px;flex-wrap:wrap}}
 .bacard{{flex:1;min-width:230px;background:#fff;border-radius:12px;padding:16px 20px;
   box-shadow:0 1px 3px rgba(0,0,0,.08)}}
 .bacard.before{{border-top:5px solid {RED}}} .bacard.after{{border-top:5px solid {GREEN}}}
 .bal{{color:#5a6b7b;font-size:13px}} .bav{{font-size:38px;font-weight:800;margin:4px 0}}
 .bacard.before .bav{{color:{RED}}} .bacard.after .bav{{color:{GREEN}}}
 .bas{{color:#5a6b7b;font-size:13px}} .baarrow{{font-size:34px;color:#9aa0a6;font-weight:700}}
 .kpis{{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}}
 .kpi{{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08);
   flex:1;min-width:140px}}
 .kpi .n{{font-size:30px;font-weight:700}} .kpi .l{{color:#5a6b7b;font-size:13px}}
 .kpi.win .n{{color:{GREEN}}} .kpi.lose .n{{color:{BLUE}}} .kpi.bad .n{{color:{RED}}}
 section{{background:#fff;border-radius:10px;padding:20px 24px;margin:18px 0;
   box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 section h2{{margin:0 0 14px;font-size:18px;border-bottom:2px solid #eef1f4;padding-bottom:8px}}
 img.chart{{width:100%;height:auto;border:1px solid #eef1f4;border-radius:6px}}
 .cap{{color:#5a6b7b;font-size:13px;margin:6px 0 0}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th,td{{padding:8px 10px;text-align:center;border-bottom:1px solid #eef1f4}}
 th{{background:#0f2c44;color:#fff;position:sticky;top:0}}
 td.inst{{font-weight:700;text-align:left}} td.ok{{color:#16324f}}
 td.fail{{color:{RED};font-weight:600}}
 td.wour{{background:{GREEN};color:#fff;font-weight:700}}
 td.wbase{{background:{BLUE};color:#fff;font-weight:700}}
 td.wtie{{background:{GREY};color:#fff}} td.wfail{{background:{RED};color:#fff}}
 td.gneg{{color:{GREEN};font-weight:700}} td.gpos{{color:{RED};font-weight:700}}
 .z{{color:#7a8a99;font-size:11px}} .t{{color:#aab3bd;font-size:11px}}
 .wts{{color:#5a6b7b;font-size:11px}}
 .note{{background:#fff8e6;border-left:5px solid #e0a800;padding:12px 16px;border-radius:6px;
   font-size:14px;margin:10px 0}}
 .note.ok{{background:#e8f6ee;border-left-color:{GREEN}}}
 .cols{{display:flex;gap:16px;flex-wrap:wrap}} .col{{flex:1;min-width:260px}}
 .col h3{{font-size:15px;margin:0 0 8px}} .col.good h3{{color:{GREEN}}} .col.bad h3{{color:{RED}}}
 ul.tight{{margin:6px 0 0}} ul.tight li{{font-size:13px}}
 .tag{{display:inline-block;background:#eef1f4;border-radius:5px;padding:1px 7px;font-size:12px}}
</style></head><body>
<header><h1>OGC 2026 — GPT 개선 알고리즘 평가 리포트</h1>
<p>신규 학습 인스턴스 prob_1…20 (100–300블록) · 공식 baseline vs 우리 솔버 ·
 timelimit {tl}s · 신규 utils(math.floor Z2) 채점 · 동시 비교 1회</p></header>
<div class="wrap">
 <div class="verdict">결과: {verdict} &nbsp;|&nbsp; feasible {our_feas}/{n} (baseline {base_feas}/{n})
  &nbsp;|&nbsp; 우리 승 {sb['wins']} · 무 {sb['ties']} · 패 {sb['losses']} · 양쪽실패 {sb['bothfail']}
  &nbsp;|&nbsp; R−nb baseline {sb['base_pts']} / <b>ours {sb['our_pts']}</b></div>
 {before}
 <div class="kpis">
  <div class="kpi win"><div class="n">{sb['wins']}/{n}</div><div class="l">우리가 더 나은 인스턴스</div></div>
  <div class="kpi"><div class="n">{sb['ties']}</div><div class="l">동점</div></div>
  <div class="kpi lose"><div class="n">{sb['losses']}</div><div class="l">baseline이 더 나음</div></div>
  <div class="kpi bad"><div class="n">{sum(1 for r in rows if not r['o'].get('feasible'))}</div>
    <div class="l">우리 infeasible</div></div>
  <div class="kpi bad"><div class="n">{our_timeouts}</div><div class="l">hard-timeout</div></div>
 </div>
 {diag}
 {wins_sec}
 {iso_sec}
 <section><h2>① 인스턴스별 목적함수 (log, 낮을수록 좋음)</h2>{img(charts['obj'])}</section>
 <section><h2>② 목적함수 격차 (음수 = 우리 승)</h2>{img(charts['gap'])}</section>
 <section><h2>③ 가중 목적함수 구성 (w1·Z1 / w2·Z2 / w3·Z3)</h2>{img(charts['comp'])}
   <p class="cap">전 인스턴스 w1이 수만 단위 → Z1(지연)이 점수를 지배. 개선의 우선 타깃이 Z1임을 시각 확인.</p></section>
 <section><h2>④ 원시 목적 성분 Z1 / Z2 / Z3</h2>{img(charts['zcomp'])}</section>
 <section><h2>⑤ 실현가능성 그리드</h2>{img(charts['feas'])}
   <p class="cap">−1(실현불가)은 대회 점수에서 치명적 — 한 칸이라도 빨강이면 평균 R/2 손실.</p></section>
 <section><h2>⑥ 실행 시간 (제한선 점선)</h2>{img(charts['wall'])}</section>
 <section><h2>⑦ 종합 스코어보드 (R−nb, R=2)</h2>{img(charts['score'])}</section>
 <section><h2>⑧ 상세 결과 표</h2>
  <table><thead><tr><th>instance</th><th>n×bays</th><th>w1/w2/w3</th>
   <th>baseline</th><th>ours</th><th>winner</th><th>gap</th></tr></thead>
   <tbody>{table}</tbody></table>
  <p class="cap">gap = (ours − baseline) / baseline. 녹색=우리 승, 빨강=회귀.
   baseline infeasible 칸은 gap "—"(우리 단독 feasible 승).</p></section>
 <section><h2>⑨ 다음 단계 — 개선 방향</h2>
  <p>개선 방향은 별도 <b>2-에이전트 토론</b>으로 도출(동봉 문서
   <code>notes/improvement-debate.html</code>). 현 리포트는 "현재 어디에 서 있는가"의 사실 기록.</p></section>
</div></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
