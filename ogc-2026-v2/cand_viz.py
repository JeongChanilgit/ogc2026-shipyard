"""cand_viz.py — 후보위치 선정 로직을 *실제 함수*로 계산해 레이어드 HTML 로 시각화.

temporal_pack 의 진짜 `_bl_candidates`(크레인-feasible 후보생성: BL frontier / diverse 경계)
+ `_contact`(near-접촉 D-팽창 채점) 을 읽기 좋은 합성 씬(16×11 베이, 점유 3개, 들어올 4×3)
에 돌려, 단계별 레이어를 토글하는 자기완결 HTML 을 만든다. 풀 솔버 안 돌림(빠름).

실행: <env-python> cand_viz.py
출력: out/cand_logic.html (브라우저 자동 오픈)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp          # noqa: E402  (실제 후보/접촉 함수)
from temporal_pack import _bl_candidates, _contact, _fp_union, _suffix  # noqa: E402
from density_pack import _common_masks  # noqa: E402
from gridmap import build_shape     # noqa: E402

SCALE = 2
W, H = 18, 12                       # 베이 (블록단위)
hc, wc = H * SCALE, W * SCALE       # 셀

# 들어올 블록 = 4×3 사각형 (단층)
INCOMING = {"shape": [{"orientation": 0, "layers": [[[0, 0], [4, 0], [4, 3], [0, 3]]]}]}
# 발견 데모: 왼쪽은 넓게 열린 "쉬운" 영역(BL 이 잡는 좌하단), 오른쪽엔 P·Q 사이 폭4 = *중간 snug gap*.
# BL-프론티어는 각 행 leftmost 만 보므로 왼쪽 열린 자리만 잡고 *중간 gap 을 놓친다*. diverse 가 잡아 인터록.
OCC_BLOCKS = [
    (0, 0, 3, 4),     # S: 좌하단 작은 블록
    (8, 0, 12, 6),    # P: 중앙 블록 (gap 왼벽)
    (16, 0, 18, 6),   # Q: 우 블록   → P 와 사이 x12..16(폭4) = 중간 snug gap
    (3, 8, 9, 12),    # R: 상단 코너
]


def feasible_anchors(occ, sh, cm):
    """temporal_pack._bl_candidates :127-145 의 feasibility 계산을 그대로 재현 →
    각 앵커 (x,y) 가 크레인-feasible 한지 + 해당 footprint-origin 셀 (col0,row0)."""
    boff_cx, boff_cy, Hb, Wb, cmasks = cm
    from numpy.lib.stride_tricks import sliding_window_view as _swv
    feas = np.ones((hc - Hb + 1, wc - Wb + 1), dtype=bool)
    for l1 in range(sh.n_layers):
        suf = _suffix(occ, l1)
        win = _swv(suf, (Hb, Wb))
        ov = np.logical_and(win, cmasks[l1]).sum(axis=(2, 3))
        feas &= (ov == 0)
    xs = np.arange(int(np.ceil(-sh.min_x - 1e-9)), int(np.floor(W - sh.max_x + 1e-9)) + 1)
    ys = np.arange(int(np.ceil(-sh.min_y - 1e-9)), int(np.floor(H - sh.max_y + 1e-9)) + 1)
    cols = xs * SCALE + boff_cx
    rows = ys * SCALE + boff_cy
    out = []
    for iy, (y, r) in enumerate(zip(ys, rows)):
        if r < 0 or r > hc - Hb:
            continue
        for ix, (x, c) in enumerate(zip(xs, cols)):
            if c < 0 or c > wc - Wb:
                continue
            if feas[r, c]:
                out.append((int(x), int(y), int(c), int(r)))
    return out, (Hb, Wb)


def contact_band(fpm, floor, row, col, D=2):
    """_contact :239-250 의 band 계산 재현 → band 셀을 (c,r,kind) 로 분류."""
    Hb, Wb = fpm.shape
    blk = np.zeros((Hb + 2 * D, Wb + 2 * D), dtype=bool)
    blk[D:D + Hb, D:D + Wb] = fpm
    dil = blk.copy()
    for _ in range(D):
        d = dil.copy()
        d[1:, :] |= dil[:-1, :]; d[:-1, :] |= dil[1:, :]
        d[:, 1:] |= dil[:, :-1]; d[:, :-1] |= dil[:, 1:]
        dil = d
    band = dil & ~blk
    r0, c0 = row - D, col - D
    cells = []
    for i in range(Hb + 2 * D):
        for j in range(Wb + 2 * D):
            if not band[i, j]:
                continue
            gr, gc = r0 + i, c0 + j
            if gr < 0 or gr >= hc or gc < 0 or gc >= wc:
                kind = "wall"
            elif floor[gr, gc]:
                kind = "block"
            else:
                continue                      # 빈 near-zone 은 점수 0 → 생략
            cells.append([int(gc), int(gr), kind])
    return cells


def main():
    # 점유 격자 (단층)
    occ = [np.zeros((hc, wc), dtype=bool)]
    occ_rects = []
    for (x0, y0, x1, y1) in OCC_BLOCKS:
        c0, r0, c1, r1 = x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE
        occ[0][r0:r1, c0:c1] = True
        occ_rects.append([c0, r0, c1, r1])

    sh = build_shape(0, INCOMING, 0, SCALE)
    cm = _common_masks(sh, SCALE)
    fpm, bcx, bcy = _fp_union(cm)
    Hb, Wb = cm[2], cm[3]

    # 1) feasible 앵커 전체
    feas, (Hb, Wb) = feasible_anchors(occ, sh, cm)
    feas_origins = [[c, r] for (_x, _y, c, r) in feas]

    # 2) BL frontier 후보 (각 행 leftmost, 최대 8)
    bl = _bl_candidates(occ, sh, cm, W, H, SCALE, limit=8, diverse=False)
    bl_fp = [{"x": x, "y": y, "c": x * SCALE + bcx, "r": y * SCALE + bcy} for (x, y) in bl]

    # 3) diverse 후보 (feasible 경계, snug) + contact 점수. blmiss = BL 후보엔 없는 자리(=놓친 틈)
    dv = _bl_candidates(occ, sh, cm, W, H, SCALE, limit=40, diverse=True)
    bl_set = {(d["x"], d["y"]) for d in bl_fp}
    div = []
    for (x, y) in dv:
        col0, row0 = x * SCALE + bcx, y * SCALE + bcy
        ct = _contact(fpm, occ[0], row0, col0, D=2)
        div.append({"x": x, "y": y, "c": col0, "r": row0, "contact": round(float(ct), 1),
                    "blmiss": (x, y) not in bl_set})

    # 4) 선택 = contact 최대
    win = max(div, key=lambda d: d["contact"]) if div else None
    band = contact_band(fpm, occ[0], win["r"], win["c"], D=2) if win else []

    n_blmiss = sum(1 for d in div if d["blmiss"])
    win_blmiss = bool(win and win["blmiss"])
    scene = {
        "W": W, "H": H, "scale": SCALE, "wc": wc, "hc": hc, "Wb": int(Wb), "Hb": int(Hb),
        "occRects": occ_rects, "feasOrigins": feas_origins,
        "bl": bl_fp, "div": div, "win": win, "band": band,
        "nFeas": len(feas), "nBL": len(bl), "nDiv": len(div), "nBLmiss": n_blmiss,
        "winBLmiss": win_blmiss,
    }
    out = os.path.join(THIS, "out", "cand_logic.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__SCENE__", json.dumps(scene)))
    print(f"feasible 앵커={len(feas)}  BL 후보={len(bl)}  diverse 후보={len(div)}  "
          f"(그중 BL 누락 자리={n_blmiss})", flush=True)
    if win:
        print(f"선택(contact max): @({win['x']},{win['y']}) contact={win['contact']} "
              f"band={len(band)}셀  {'★ BL이 놓친 중간 gap!' if win_blmiss else '(BL도 잡는 자리)'}",
              flush=True)
    print(f"wrote {out}", flush=True)
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>후보위치 선정 로직</title>
<style>
  :root{color-scheme:dark}*{box-sizing:border-box}
  html,body{margin:0;background:#0b0e14;color:#d7dde8;font-family:ui-monospace,Consolas,monospace}
  .wrap{max-width:1180px;margin:0 auto;padding:22px 20px 60px}
  h1{font-size:20px;color:#8fb7ff;margin:0 0 3px}.sub{color:#67718a;font-size:13px;margin-bottom:14px}
  .main{display:flex;gap:22px;align-items:flex-start}
  .left{flex:0 0 auto}.right{flex:1 1 0;min-width:0}
  .ctrl{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 10px}
  button{background:#1c2435;color:#cfe0ff;border:1px solid #2c3650;border-radius:6px;
    padding:5px 11px;font:inherit;font-size:12px;cursor:pointer}
  button.on{background:#27406e;border-color:#4f79d6;color:#fff}
  svg{background:#0d1118;border:1px solid #222d44;border-radius:6px}
  .step{border:1px solid #232a3a;border-radius:9px;padding:11px 13px;margin-bottom:11px;background:#11151f}
  .step h3{margin:0 0 5px;font-size:13px;color:#9fc0ff}
  .step p{margin:0;font-size:12.5px;line-height:1.65;color:#aeb9cc}
  .step code{color:#ffd479;background:#1a1f2b;padding:1px 5px;border-radius:4px;font-size:11.5px}
  .sw{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:middle;margin:0 3px}
  .legend{font-size:12px;color:#aeb9cc;line-height:1.9;margin-top:8px}
  b.g{color:#86e0a6}b.o{color:#ffb15a}b.b{color:#6fa3ff}b.r{color:#ff6b8a}
</style></head><body><div class="wrap">
<h1>후보위치 선정 로직 — BL 프론티어의 맹점 (발견)</h1>
<div class="sub">왼쪽은 넓게 열린 자리(BL 이 잡음), 오른쪽 <b style="color:#e85ad0">P·Q 사이 폭4 = 중간 snug gap</b>. BL-프론티어는 각 행 leftmost 만 봐서 이 중간 gap 을 <b>놓치고</b>, diverse 가 잡아 인터록한다. temporal_pack 의 진짜 <code>_bl_candidates</code>·<code>_contact</code> 출력.</div>
<div class="main">
  <div class="left">
    <div class="ctrl" id="ctrl"></div>
    <svg id="svg"></svg>
    <div class="legend" id="legend"></div>
  </div>
  <div class="right" id="steps"></div>
</div>
<script>
const S = __SCENE__;
const PX = 21, PAD = 14;
const wpx = S.wc*PX + 2*PAD, hpx = S.hc*PX + 2*PAD;
const NS="http://www.w3.org/2000/svg";
function E(t,a){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
// cell(col,row) → svg (row 0 = 바닥 → 위로 flip)
function X(c){return PAD + c*PX;}
function Y(r,h){return PAD + (S.hc-(r+(h||1)))*PX;}
const svg=document.getElementById("svg");
svg.setAttribute("width",wpx); svg.setAttribute("height",hpx);

function cellRect(c,r,w,h,attr){const e=E("rect",Object.assign(
  {x:X(c),y:Y(r,h),width:w*PX,height:h*PX},attr));return e;}

const layers={};
function L(name){const g=E("g",{});svg.appendChild(g);layers[name]=g;return g;}

// 베이 격자
{const g=L("grid");
 for(let c=0;c<=S.wc;c++) g.appendChild(E("line",{x1:X(c),y1:Y(S.hc),x2:X(c),y2:Y(0),
   stroke:"#1a2233","stroke-width":c%2?0.5:0.8}));
 for(let r=0;r<=S.hc;r++) g.appendChild(E("line",{x1:X(0),y1:Y(r,0),x2:X(S.wc),y2:Y(r,0),
   stroke:"#1a2233","stroke-width":r%2?0.5:0.8}));
 g.appendChild(E("rect",{x:X(0),y:Y(S.hc),width:S.wc*PX,height:S.hc*PX,fill:"none",
   stroke:"#4a597a","stroke-width":1.5}));}

// 점유 블록 (회색)
{const g=L("occ");
 S.occRects.forEach(([c0,r0,c1,r1])=>{
   g.appendChild(cellRect(c0,r0,c1-c0,r1-r0,{fill:"#3a4257",stroke:"#5a6478","stroke-width":1.2,rx:2}));});}

// feasible 앵커 origin 셀 (연녹)
{const g=L("feas");g.style.display="none";
 S.feasOrigins.forEach(([c,r])=>{
   g.appendChild(cellRect(c,r,1,1,{fill:"#1f7a4d","fill-opacity":0.55,stroke:"#2f9a63","stroke-width":0.4}));});}

// BL frontier 후보 (블루 윤곽 footprint)
{const g=L("bl");g.style.display="none";
 S.bl.forEach(d=>{ g.appendChild(cellRect(d.c,d.r,S.Wb,S.Hb,
   {fill:"#1d3a66","fill-opacity":0.20,stroke:"#6fa3ff","stroke-width":1.6,rx:1}));
   g.appendChild(E("circle",{cx:X(d.c)+3,cy:Y(d.r,0)-3,r:2.5,fill:"#6fa3ff"}));});}

// diverse 후보 (오렌지 윤곽 + contact 점수). BL 누락 자리 = 마젠타 점선 덧고리
{const g=L("div");
 S.div.forEach(d=>{ const win = S.win && d.x===S.win.x && d.y===S.win.y;
   g.appendChild(cellRect(d.c,d.r,S.Wb,S.Hb,{fill:"#3a2a14","fill-opacity":win?0:0.16,
     stroke:win?"#39e639":"#ffb15a","stroke-width":win?2.4:1.4,rx:1}));
   if(d.blmiss) g.appendChild(cellRect(d.c,d.r,S.Wb,S.Hb,{fill:"none",stroke:"#e85ad0",
     "stroke-width":1.3,"stroke-dasharray":"3 3",rx:1}));
   const tx=E("text",{x:X(d.c)+S.Wb*PX/2,y:Y(d.r,S.Hb)+S.Hb*PX/2+4,fill:win?"#bfffce":"#ffcf94",
     "font-size":10.5,"text-anchor":"middle","font-weight":win?"bold":"normal"});
   tx.textContent=d.contact; g.appendChild(tx);
   if(d.blmiss){const m=E("text",{x:X(d.c)+S.Wb*PX/2,y:Y(d.r,S.Hb)-3,fill:"#e85ad0",
     "font-size":9,"text-anchor":"middle"});m.textContent="BL✗";g.appendChild(m);}});}

// 선택의 contact band (벽=하늘 / 블록=빨강)
{const g=L("band");g.style.display="none";
 (S.band||[]).forEach(([c,r,kind])=>{
   const col = kind==="wall" ? "#3aa0ff" : "#ff5577";
   g.appendChild(cellRect(c,r,1,1,{fill:col,"fill-opacity":0.5,stroke:col,"stroke-width":0.5}));});
 if(S.win) g.appendChild(cellRect(S.win.c,S.win.r,S.Wb,S.Hb,
   {fill:"#39e639","fill-opacity":0.30,stroke:"#39e639","stroke-width":2.4,rx:1}));}

// 토글 버튼
const defs=[["occ","점유 블록",true],["feas","feasible 앵커",false],
  ["bl","BL frontier 후보",false],["div","diverse 후보 + contact",true],
  ["band","선택 + 접촉 band",false]];
const ctrl=document.getElementById("ctrl");
defs.forEach(([k,label,on])=>{ layers[k].style.display=on?"":"none";
  const b=document.createElement("button"); b.textContent=label; if(on)b.className="on";
  b.onclick=()=>{const vis=layers[k].style.display==="none"; layers[k].style.display=vis?"":"none";
    b.classList.toggle("on",vis);}; ctrl.appendChild(b);});

document.getElementById("legend").innerHTML =
  `<span class="sw" style="background:#3a4257"></span>점유  `+
  `<span class="sw" style="background:#1f7a4d"></span>feasible 앵커(${S.nFeas})  `+
  `<span class="sw" style="background:#6fa3ff"></span>BL(${S.nBL})  `+
  `<span class="sw" style="background:#ffb15a"></span>diverse(${S.nDiv})  `+
  `<span class="sw" style="border:1.5px dashed #e85ad0;background:none"></span>BL✗ 누락자리(${S.nBLmiss})  `+
  `<span class="sw" style="background:#39e639"></span>선택  `+
  `<span class="sw" style="background:#3aa0ff"></span>벽접촉 <span class="sw" style="background:#ff5577"></span>블록접촉`;

const steps=[
 ["① 크레인-feasible 마스크 <code>_bl_candidates :127-145</code>",
  `각 앵커 (x,y) 에 블록을 놓을 수 있나? 레이어별 suffix-OR(위층까지 OR)과 footprint 마스크를 `+
  `슬라이딩-윈도우 AND → 겹침 0 인 앵커만 <b class="g">feasible</b>. "feasible 앵커" 토글이 그 영역(연녹)이다. `+
  `크레인 j≥k(위에서 강하)도 이 suffix-OR 로 같이 처리.`],
 ["② 후보 생성 — BL frontier의 맹점 vs diverse <code>:146-168</code>",
  `<b class="b">BL</b>(기본·빠름): 각 행에서 <b>가장 왼쪽 feasible</b> 한 칸 하나씩 → 좌하단 띠(${S.nBL}개). `+
  `<b>문제</b>: 왼쪽이 열려 있으면 leftmost 가 거기로 가버려서 <b style="color:#e85ad0">오른쪽 중간 snug gap(P·Q 사이)</b>이 `+
  `후보에서 빠진다. 이 씬에서 <b style="color:#e85ad0">BL✗ 누락 자리 ${S.nBLmiss}개</b>. `+
  `<b class="o">diverse</b>(품질·기본 ON): feasible 영역의 <b>경계</b>(인접에 점유/벽 있는 snug 칸)를 전역에서 `+
  `균등 샘플 → 코너·중간 gap·인터록 자리까지(${S.nDiv}개). <b>그래서 선택(④)이 BL이 못 본 중간 gap을 잡는다.</b>`],
 ["③ near-contact 채점 <code>_contact :221-250</code>",
  `각 diverse 후보를 점수화: 블록 둘레를 <code>D=2</code> 칸 팽창한 near-zone 에서 `+
  `<b class="r">벽 셀</b>×WALL_W + <b class="r">다른블록 셀</b>×1 을 센다. 높을수록 <b>snug</b>(구석·통로에 꽉 끼고 `+
  `얇은 빈틈 안 남김). "면 맞닿음만"이 아니라 <b>가까이 붙음</b>까지 인정(D=2)이 핵심 픽스. `+
  `"선택 + 접촉 band" 토글로 이긴 후보의 접촉 셀이 보인다.`],
 ["④ 선택",
  `<b class="g">contact 최대</b> 후보를 배치(fit=1 기본). fit=ov 면 +오버랩(인터록 가치), `+
  `fit=tardy 면 접촉 top-3 중 쌓기 페널티 최소. 전역 Pass B(OGC_GLOBAL)에선 베이마다 이 후보를 `+
  `뽑아 marginal obj(w1·tardy+w2·Δz2+w3·pref) 로 베이까지 동시 선택.`],
];
document.getElementById("steps").innerHTML = steps.map(([h,p])=>
  `<div class="step"><h3>${h}</h3><p>${p}</p></div>`).join("");
</script></body></html>"""


if __name__ == "__main__":
    main()
