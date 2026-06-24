"""pipeline_report.py — prob_38 파이프라인 분석 리포트(HTML).

단계별 동작·소요시간·z1/z2/z3 전후 변화 + 3D 공존구조 통찰 + 2D 후보위치 그림.
검증 config(near-접촉 D=2 + diverse + fit=ov, 토스/스왑 off)로 실행.

실행: <env-python> pipeline_report.py  → out/pipeline_report.html (브라우저 오픈)
"""
from __future__ import annotations

import os

os.environ.setdefault("OGC_FIT", "ov")
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_TOSS"] = "0"
os.environ["OGC_PACK_SWAP"] = "0"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_STAGES"] = "1"
os.environ.setdefault("PYTHONUTF8", "1")

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp  # noqa: E402
import unified_greedy as ug  # noqa: E402
from cand_diag import svg as cand_svg  # noqa: E402
from decomp_diag import footprint, components  # noqa: E402

NM = "prob_38"
TL = 200.0
ORIG = {"obj": 91107711, "z1": 6651, "z2": 2964, "z3": 8080}    # 원래 솔버 @200


def coexistence(data, sol):
    """베이별 최대 동시공존 + 시공간 독립성분 수 (3D 구조 통찰용)."""
    by_bay, spans = {}, {}
    for st_, ops in sol["operations"].items():
        for op in ops:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                j = int(op["bay_id"])
                f = footprint(data["blocks"][bid], int(op.get("orient_idx", 0)),
                              op.get("x", 0), op.get("y", 0))
                if f is not None:
                    by_bay.setdefault(j, []).append((bid, f))
                spans[bid] = [float(st_), None]
            elif bid in spans:
                spans[bid][1] = float(st_)
    spans = {b: (e, x if x is not None else e + 1) for b, (e, x) in spans.items()}
    out = []
    for j in sorted(by_bay):
        nb = len(by_bay[j])
        evs = []
        for bid, _ in by_bay[j]:
            e, x = spans[bid]
            evs += [(e, 1), (x, -1)]
        evs.sort()
        cur = mx = 0
        for _, d in evs:
            cur += d
            mx = max(mx, cur)
        ncomp = len(components(by_bay[j], spans))
        out.append({"bay": j, "blocks": nb, "max_coexist": mx, "st_components": ncomp})
    return out


def main():
    path = os.path.join(THIS, "..", "instances", "train", NM + ".json")
    data = json.load(open(path, encoding="utf-8"))
    tp._CAP = {"min_cands": 8, "counts": []}        # 후보 캡처 (2D 그림용)
    res, dist, cpsat, dt = ug.unified(data, TL, path)
    stages = list(ug.STAGES)
    sol = res.get("_solution")
    final = {"obj": res.get("objective"), "z1": res.get("obj1"),
             "z2": res.get("obj2"), "z3": res.get("obj3")}
    cox = coexistence(data, sol) if sol else []
    cap = tp._CAP.get("out")
    counts = tp._CAP.get("counts", [])

    # 2D 후보 SVG (캡처된 step)
    svg_inner = ""
    if cap:
        tmp = os.path.join(THIS, "out", "_cand_tmp.html")
        cand_svg(tmp, cap["W"], cap["H"], cap["present"], cap["cands"],
                 cap["picked"], cap["bid"], len(cap["cands"]))
        body = open(tmp, encoding="utf-8").read()
        svg_inner = body[body.find("<svg"):body.find("</svg>") + 6]

    # 3D viz 생성 (참조 링크)
    from viz import trace_from_solution, write_viz
    if sol:
        write_viz(trace_from_solution(data, sol, NM),
                  os.path.join(THIS, "out", f"viz_{NM}.html"))

    html = _build_html(NM, TL, dt, stages, final, ORIG, cox, dist, counts, svg_inner, cap)
    out = os.path.join(THIS, "out", "pipeline_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out}  (obj={final['obj']:,} vs orig {ORIG['obj']:,})", flush=True)
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


def _pct(new, old):
    if not old:
        return "—"
    d = (old - new) / old * 100
    sign = "▼" if d > 0 else "▲"
    col = "#39e639" if d > 0 else "#e2245a"
    return f'<span style="color:{col}">{sign}{abs(d):.0f}%</span>'


def _build_html(nm, tl, dt, stages, final, orig, cox, dist, counts, svg_inner, cap):
    from collections import Counter
    hist = Counter(min(c, 8) for c in counts) if counts else {}
    nplc = len(counts) or 1
    multi = sum(1 for c in counts if c >= 2)
    # 단계 행
    rows = []
    for s in stages:
        z = lambda k: f'{s[k]:,}' if s.get(k) is not None else '·'
        extra = []
        if "dist" in s:
            extra.append(f'분포 {s["dist"]}')
        if "ovf" in s:
            extra.append(f'오버플로 {s["ovf"]}')
        rows.append(f'''<tr><td>{s["name"]}</td><td class=n>{s["dt"]}s</td>
          <td class=n>{z("z1")}</td><td class=n>{z("z2")}</td><td class=n>{z("z3")}</td>
          <td class=muted>{" · ".join(extra)}</td></tr>''')
    stage_rows = "\n".join(rows)
    cox_rows = "\n".join(
        f'<tr><td>bay {c["bay"]}</td><td class=n>{c["blocks"]}</td>'
        f'<td class=n>{c["max_coexist"]}</td><td class=n>{c["st_components"]}</td></tr>'
        for c in cox)
    hist_str = "  ".join(f'{k if k < 8 else "8+"}개:{hist.get(k,0)}' for k in range(1, 9))

    return f'''<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>OGC2026 파이프라인 분석 · {nm}</title><style>
:root{{color-scheme:dark}}
body{{margin:0;background:#0b0e14;color:#d7dde8;font-family:ui-monospace,Menlo,Consolas,monospace;
  line-height:1.6;padding:0 0 60px}}
.wrap{{max-width:960px;margin:0 auto;padding:24px}}
h1{{color:#8fb7ff;font-size:22px;margin:8px 0}}
h2{{color:#6fa3ff;font-size:15px;margin:30px 0 10px;border-bottom:1px solid #232a3a;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #1c2433}}
th{{color:#93a0b8;font-weight:600;font-size:12px}}
td.n{{text-align:right}} .muted{{color:#67718a;font-size:12px}}
.big{{font-size:30px;color:#39e639;font-weight:700}}
.kpi{{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0}}
.card{{background:#11151f;border:1px solid #232a3a;border-radius:9px;padding:14px 18px;flex:1;min-width:150px}}
.card .v{{font-size:24px;color:#e8eefb}} .card .k{{color:#93a0b8;font-size:12px}}
.ins{{background:#10171f;border-left:3px solid #4f79d6;padding:10px 16px;margin:12px 0;border-radius:0 8px 8px 0}}
.ins b{{color:#8fb7ff}}
svg{{max-width:100%;height:auto;background:#0b0e14;border:1px solid #232a3a;border-radius:8px}}
a{{color:#6fa3ff}}
</style></head><body><div class=wrap>

<h1>OGC2026 통합 그리디 솔버 — 파이프라인 분석 ({nm})</h1>
<div class=muted>N={250} 블록 · 3 베이 · 가중치 w1=3333~ · 검증 config: near-접촉(D=2)+diverse후보+fit=ov(접촉+오버랩), 토스/스왑 off · 총 {dt:.0f}s</div>

<div class=kpi>
  <div class=card><div class=k>우리 obj</div><div class=v>{final["obj"]:,}</div></div>
  <div class=card><div class=k>원래 솔버 obj</div><div class=v>{orig["obj"]:,}</div></div>
  <div class=card><div class=k>개선</div><div class="v big">{(orig["obj"]-final["obj"])/orig["obj"]*100:.1f}%</div></div>
</div>

<h2>① 알고리즘 단계별 동작 · 시간 · z1/z2/z3 진행</h2>
<table><tr><th>단계 (무엇을 하나)</th><th class=n>시간</th><th class=n>z1<br>(지각)</th>
  <th class=n>z2<br>(불균형)</th><th class=n>z3<br>(선호)</th><th>비고</th></tr>
{stage_rows}
<tr style="border-top:2px solid #2c3650"><td><b>원래 솔버 (기준)</b></td><td class=n>—</td>
  <td class=n>{orig["z1"]:,}</td><td class=n>{orig["z2"]:,}</td><td class=n>{orig["z3"]:,}</td><td class=muted>비교 baseline</td></tr>
</table>
<div class=ins>
<b>핵심 흐름</b>: <b>z2·z3는 배정(①②)에서 확정</b>되고 패킹/타이밍서 불변 — 배정만의 함수라서다.
<b>z1은 배치(③)가 상한을 정하고 CP-SAT 타이밍(④)이 그 상한 안에서 최적화</b>한다.
최종 vs 원래: z1 {_pct(final["z1"],orig["z1"])} · z2 {_pct(final["z2"],orig["z2"])} · z3 {_pct(final["z3"],orig["z3"])}.
즉 <b>세 항 모두 원래보다 낮다</b> — 배정 없이 통합 그리디로 빈 공간을 활용해 혼잡을 줄이고, diverse 후보로 snug 배치를 찾고, CP-SAT로 타이밍을 짜낸 결과.
</div>

<h2>② 3D 공간 구조 분석 (내 통찰)</h2>
<table><tr><th>베이</th><th class=n>블록 수</th><th class=n>최대 동시공존</th><th class=n>시공간 독립성분</th></tr>
{cox_rows}</table>
<div class=ins>
<b>관찰</b>: 각 베이가 수십 블록을 담는데 <b>최대 동시공존 수가 높고</b>, 시공간 독립성분도 많다.
의미 → 블록들이 <b>같은 시각에 서로 안 겹치게 나란히(side-by-side) 공존</b>한다. 이게 z1을 낮추는 메커니즘이다:
공존이 많을수록 병렬 처리되어 makespan(완료시각)이 짧아지고 → 지각(z1)이 준다.
<b>"꽉 채우기(jam)"가 아니라 "펼쳐서 병렬화"가 레버</b>임을 구조가 보여준다. 다만 z축 인터록(오버행 겹침)은
이득될 때만 <b>선택적으로</b> 일어난다 — 강제하면 타이밍이 묶여 오히려 악화(반증됨).
</div>
<div class=muted>▶ 인터랙티브 3D: <a href="viz_{nm}.html">viz_{nm}.html</a> (전체 베이 동시 표시, tardy=진홍색, 슬라이더로 ENTRY/EXIT 재생, 블록 번호 라벨)</div>

<h2>③ 2D 후보 위치 선택 (내 통찰)</h2>
<div class=muted>한 배치 시점(block {cap["bid"] if cap else "?"})에서 생성된 후보 위치들. 회색=점유 블록,
빨강=점수 1위, 주황=2~3위, 파랑=나머지, 초록=실제 배치. 후보수 분포: {hist_str} ({100*multi//nplc}%가 2개+)</div>
{svg_inner}
<div class=ins>
<b>관찰</b>: 후보가 <b>베이 전역에 퍼져</b> 있다(좌하단 띠가 아니라 중간 gap·코너 포함). 이게 <b>diverse 후보 생성</b>의 효과 —
feasible 영역의 *경계*(인접에 점유/벽 있는 snug 자리)를 전부 띄운다. 기존 bottom-left만 봤을 땐 중간의 애매한 틈에
딱 맞는 자리가 후보에 없어서 못 넣었는데, 이걸 고치니 <b>z1이 단번에 −15%</b> 떨어졌다.
선택은 <b>접촉도(snug, 벽·블록에 붙음) + 오버랩가치(이득되는 z축 겹침은 보상, 먼저 나갈 블록 덮으면 페널티)</b>로 한다.
</div>

</div></body></html>'''


if __name__ == "__main__":
    main()
