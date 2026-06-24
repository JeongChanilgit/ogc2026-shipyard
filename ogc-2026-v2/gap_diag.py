"""gap_diag.py — "빈 공간 왼쪽에 붙이나?" 진단: BL(옛) vs diverse(현재) 직접 비교.

같은 베이를 두 방식으로 패킹 → 블록별 "접촉 면 수"(좌/우/상/하 중 점유·벽 닿는 면)와
contact 점수 평균을 비교. 왼쪽에만 붙으면 접촉면이 적고(주로 좌+하), 빈틈 snug-fill 이면
좌+우+하 등 여러 면이 닿는다. 두 패킹 top-view 를 한 HTML 로.
실행: <env-python> gap_diag.py [prob] [bay_id]   (기본 prob_38)
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")

import numpy as np  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def analyze(sub, placed):
    """블록별 접촉면수(0~4) + contact 점수. floor = 전 블록 union."""
    W, H, ml, scale = sub["W"], sub["H"], sub["max_layer"], sub["scale"]
    hc, wc = H * scale, W * scale
    floor = tp._occ_from_present(placed, hc, wc, ml, scale)[0]
    fpc = tp._fp_union
    sides_tot, contact_tot, leftstuck = 0, 0.0, 0
    for p in placed:
        single = tp._occ_from_present([p], hc, wc, ml, scale)[0]
        rs = np.where(single.any(axis=1))[0]
        cs = np.where(single.any(axis=0))[0]
        if rs.size == 0 or cs.size == 0:
            continue
        by0, by1, bx0, bx1 = rs.min(), rs.max() + 1, cs.min(), cs.max() + 1
        others = floor & ~single
        left = bx0 == 0 or (bx0 > 0 and others[by0:by1, bx0 - 1].any())
        right = bx1 >= wc or (bx1 < wc and others[by0:by1, bx1].any())
        bot = by0 == 0 or (by0 > 0 and others[by0 - 1, bx0:bx1].any())
        top = by1 >= hc or (by1 < hc and others[by1, bx0:bx1].any())
        sides_tot += int(left) + int(right) + int(bot) + int(top)
        # contact 점수
        cm = tp._common_masks(p["sh"], scale) if False else None
        fpm = single[by0:by1, bx0:bx1]
        contact_tot += tp._contact(fpm, floor & ~single, by0, bx0, D=2)
        # 좌만 닿고 우는 비고 + 우측에 여유(빈틈 왼쪽에 붙음 의심)
        if left and not right and bx1 < wc - 1:
            leftstuck += 1
    n = max(1, len(placed))
    return {"avg_sides": sides_tot / n, "avg_contact": contact_tot / n,
            "leftstuck": leftstuck, "leftstuck_pct": 100 * leftstuck / n, "n": len(placed)}


def topview_svg(W, H, placed, title, sub):
    PX, pad = 12, 22
    w, h = W * PX + 2 * pad, H * PX + 2 * pad

    def fx(x):
        return pad + x * PX

    def fy(y):
        return pad + (H - y) * PX
    el = [f'<svg width="{w}" height="{h}" style="background:#0d1118;border:1px solid #233">']
    el.append(f'<rect x="{fx(0)}" y="{fy(H)}" width="{W*PX}" height="{H*PX}" fill="none" stroke="#4a597a"/>')
    n = len(placed)
    for k, p in enumerate(placed):
        ring = tp._ring0(p["world"])
        if not ring:
            continue
        frac = k / max(1, n - 1)
        col = f"rgb({int(80+150*frac)},{int(120*(1-frac))},{int(220*(1-frac)+40)})"
        pts = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in ring)
        el.append(f'<polygon points="{pts}" fill="{col}" fill-opacity="0.6" stroke="{col}" stroke-width="0.8"/>')
    el.append(f'<text x="{pad}" y="15" fill="#9fc0ff" font-size="12">{title}</text></svg>')
    return "".join(el)


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    bay_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    path = os.path.join(TRAIN, nm + ".json")
    sub = tp.build_subset(path, bay_id, 2)
    W, H = sub["W"], sub["H"]
    order = tp.seed_order(sub, "edd")

    panels = []
    print(f"== [{nm}] bay {sub['bay_id']}  {W}×{H}  블록 {len(sub['subset'])}개 ==", flush=True)
    for label, dv in [("BL (옛: 각 행 leftmost)", False), ("diverse (현재)", True)]:
        tp._DIVERSE = dv
        placed, z1 = tp.simulate(sub, order, allow_stack=False, fit=True)
        a = analyze(sub, placed)
        print(f"  {label:24s} z1={z1:>6}  접촉면평균={a['avg_sides']:.2f}/4  "
              f"contact평균={a['avg_contact']:.1f}  좌측고착={a['leftstuck']}({a['leftstuck_pct']:.0f}%)",
              flush=True)
        svg = topview_svg(W, H, placed, f"{label}  z1={z1}", sub)
        panels.append((label, a, z1, svg))

    bl, dv = panels[0], panels[1]
    html = f"""<!doctype html><meta charset=utf-8>
<body style="margin:0;background:#0b0e14;color:#d7dde8;font-family:monospace;padding:18px">
<h2 style="color:#8fb7ff;margin:0 0 4px">빈 공간 왼쪽 고착? — BL vs diverse ({nm} bay{sub['bay_id']})</h2>
<div style="color:#67718a;font-size:13px;margin-bottom:12px">접촉면 평균 = 블록당 좌/우/상/하 중 점유·벽에 닿는 면 수(높을수록 snug). 색: 파랑=먼저→빨강=나중.</div>
<table style="border-collapse:collapse;font-size:13px;margin-bottom:14px">
<tr><th style="text-align:left;padding:4px 14px">방식</th><th style="padding:4px 14px">z1</th>
<th style="padding:4px 14px">접촉면 평균</th><th style="padding:4px 14px">contact 평균</th>
<th style="padding:4px 14px">좌측고착%</th></tr>
<tr><td style="padding:4px 14px;color:#6fa3ff">{bl[0]}</td><td style="text-align:center">{bl[2]}</td>
<td style="text-align:center">{bl[1]['avg_sides']:.2f}</td><td style="text-align:center">{bl[1]['avg_contact']:.1f}</td>
<td style="text-align:center;color:#ff8aa6">{bl[1]['leftstuck_pct']:.0f}%</td></tr>
<tr><td style="padding:4px 14px;color:#86e0a6">{dv[0]}</td><td style="text-align:center">{dv[2]}</td>
<td style="text-align:center;color:#86e0a6">{dv[1]['avg_sides']:.2f}</td><td style="text-align:center;color:#86e0a6">{dv[1]['avg_contact']:.1f}</td>
<td style="text-align:center">{dv[1]['leftstuck_pct']:.0f}%</td></tr></table>
<div style="display:flex;gap:18px;flex-wrap:wrap">
<div><div style="color:#6fa3ff;font-size:12px;margin-bottom:4px">{bl[0]}</div>{bl[3]}</div>
<div><div style="color:#86e0a6;font-size:12px;margin-bottom:4px">{dv[0]}</div>{dv[3]}</div>
</div></body>"""
    out = os.path.join(THIS, "out", f"gap_{nm}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  wrote {out}", flush=True)
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


if __name__ == "__main__":
    main()
