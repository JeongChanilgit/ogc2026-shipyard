"""cand_diag.py — 한 배치 step 에서 *후보 위치들*을 top-view 로 디스플레이.

후보가 정말 다양한지(=top-K 선택이 의미 있는지), 아니면 bottom-left 수직 띠로
거의 같은 위치인지 눈으로 확인. 점유 블록(회색) + 후보 폴리곤(점수 라벨) + 선택(초록).

실행: <env-python> cand_diag.py <prob> <step>   (예: cand_diag.py prob_25 30)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp  # noqa: E402
import unified_greedy as ug  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def svg(out, W, H, present, cands, picked, bid, step):
    PX = 18                      # world unit → px
    pad = 30
    w, h = W * PX + 2 * pad, H * PX + 2 * pad

    def fx(x):
        return pad + x * PX

    def fy(y):
        return pad + (H - y) * PX        # y 위로

    def poly(ring, **kw):
        pts = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in ring)
        at = " ".join(f'{k}="{v}"' for k, v in kw.items())
        return f'<polygon points="{pts}" {at}/>'

    el = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
          f'style="background:#0b0e14;font-family:monospace">']
    el.append(f'<rect x="{pad}" y="{pad}" width="{W*PX}" height="{H*PX}" '
              f'fill="none" stroke="#4a597a"/>')
    # 점유 블록 (회색)
    for p in present:
        if p["ring"]:
            el.append(poly(p["ring"], fill="#3a4257", stroke="#5a6478",
                           **{"fill-opacity": "0.7"}))
    # 후보 (랭크색 + 점수)
    cands = sorted(cands, key=lambda c: -(c["contact"] + c["ov"]))
    for i, c in enumerate(cands):
        col = "#e2245a" if i == 0 else ("#f0a020" if i < 3 else "#3d8bff")
        if c["ring"]:
            el.append(poly(c["ring"], fill="none", stroke=col, **{"stroke-width": "2"}))
        cxp = fx(c["x"] + 0.3)
        cyp = fy(c["y"] + 0.3)
        el.append(f'<text x="{cxp:.0f}" y="{cyp:.0f}" fill="{col}" font-size="10">'
                  f'#{i+1} c{c["contact"]:.0f} o{c["ov"]:.0f} @({c["x"]},{c["y"]})</text>')
    # 선택 표시
    px, py = picked
    el.append(f'<circle cx="{fx(px+0.5):.1f}" cy="{fy(py+0.5):.1f}" r="6" '
              f'fill="none" stroke="#39e639" stroke-width="3"/>')
    el.append(f'<text x="{pad}" y="18" fill="#9fc0ff" font-size="13">'
              f'block {bid} placement @step {step} — {len(cands)} candidates '
              f'(red=#1 picked-by-score, green=actually placed)</text>')
    el.append("</svg>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset=utf-8><body style='margin:0'>{''.join(el)}</body>")


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_25"
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    fit = os.environ.get("OGC_FIT", "ov")
    os.environ["OGC_PACK_SWAP"] = "0"
    ug._FIT = fit          # 모듈 전역 직접 오버라이드 (import 시점 값 무시)
    ug._TOSS = False
    path = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(path, encoding="utf-8"))

    # step = 디스플레이할 최소 후보수 (그 이상인 첫 배치를 잡음)
    minp = int(os.environ.get("OGC_CAP_MINPRESENT", "12"))
    tp._CAP = {"min_cands": step, "min_present": minp, "counts": []}
    ug.unified(data, 120.0, path)
    counts = tp._CAP["counts"]
    # 후보 개수 분포 (top-K 가 의미 있나)
    from collections import Counter
    hist = Counter(min(c, 6) for c in counts)
    n = len(counts)
    print(f"[{nm}] 후보수 분포 ({n} placements): "
          + "  ".join(f"{k if k < 6 else '6+'}개={hist.get(k,0)}({100*hist.get(k,0)/max(1,n):.0f}%)"
                      for k in range(1, 7)), flush=True)
    multi = sum(1 for c in counts if c >= 2)
    print(f"  → 후보 2개+ (선택 의미 있음): {multi}/{n} ({100*multi/max(1,n):.0f}%)", flush=True)
    out_data = tp._CAP.get("out")
    if not out_data:
        print(f"  (후보 {step}개+ 인 step 없음 → 디스플레이 생략)", flush=True)
        return
    o = out_data
    xs = sorted(set((c["x"], c["y"]) for c in o["cands"]))
    print(f"  디스플레이: block {o['bid']}, {len(o['cands'])} candidates, "
          f"present={len(o['present'])}, picked={o['picked']}", flush=True)
    ovs = [c["ov"] for c in o["cands"]]
    nz = [v for v in ovs if abs(v) > 1e-9]
    pick = next((c for c in o["cands"] if (c["x"], c["y"]) == tuple(o["picked"])), None)
    cons = [c["contact"] + c["ov"] for c in o["cands"]]
    best = max(o["cands"], key=lambda c: c["contact"] + c["ov"])
    print(f"  ov(오버랩값): 0아닌 후보 {len(nz)}/{len(ovs)}, "
          f"max={max(ovs):.0f} min={min(ovs):.0f}, picked ov={pick['ov'] if pick else '?'}", flush=True)
    print(f"  점수1위 후보: contact={best['contact']:.0f} ov={best['ov']:.0f} "
          f"(접촉+오버랩={best['contact']+best['ov']:.0f}) @({best['x']},{best['y']})", flush=True)
    out = os.path.join(THIS, "out", f"cand_{nm}.html")
    svg(out, o["W"], o["H"], o["present"], o["cands"], o["picked"], o["bid"], len(o["cands"]))
    print(f"  wrote {out}", flush=True)
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


if __name__ == "__main__":
    main()
