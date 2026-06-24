"""bias_check.py — 실제 simulate 배치가 왼쪽 쏠림인지 진단 + top-view 렌더.

production config(fit=1, diverse=1, near-접촉 D=2, NOSTACK)로 한 베이를 실제 패킹하고:
  · 최종 블록 위치 top-view (배치순 색: 파랑=먼저 → 빨강=나중) → 눈으로 쏠림 확인
  · 블록 centroid x/W 분포(좌1/3·중1/3·우1/3) + 평균 → 수치로 쏠림 판정
  · 한 step 의 후보 (x,y) 산포 → 후보가 진짜 다양한지(1픽셀 아님) 확인
실행: <env-python> bias_check.py [prob] [bay_id]   (기본 prob_38, busiest bay)
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("OGC_FIT", "1")
os.environ.setdefault("OGC_DIVERSE", "1")
os.environ.setdefault("OGC_CONTACT_D", "2")
os.environ.setdefault("OGC_WALL_W", "1")

import json  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def topview(out, W, H, placed, meanx, title):
    PX, pad = 15, 26
    w, h = W * PX + 2 * pad, H * PX + 2 * pad

    def fx(x):
        return pad + x * PX

    def fy(y):
        return pad + (H - y) * PX

    el = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
          f'style="background:#0b0e14;font-family:monospace">']
    el.append(f'<rect x="{fx(0)}" y="{fy(H)}" width="{W*PX}" height="{H*PX}" '
              f'fill="none" stroke="#4a597a" stroke-width="1.5"/>')
    n = len(placed)
    for k, p in enumerate(placed):
        ring = tp._ring0(p["world"])
        if not ring:
            continue
        frac = k / max(1, n - 1)               # 0=먼저 → 1=나중
        r = int(80 + 150 * frac); g = int(120 * (1 - frac)); b = int(220 * (1 - frac) + 40)
        col = f"rgb({r},{g},{b})"
        pts = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in ring)
        el.append(f'<polygon points="{pts}" fill="{col}" fill-opacity="0.6" '
                  f'stroke="{col}" stroke-width="1"/>')
    # 평균 centroid x 선
    el.append(f'<line x1="{fx(meanx):.1f}" y1="{fy(H)}" x2="{fx(meanx):.1f}" y2="{fy(0)}" '
              f'stroke="#ffd479" stroke-width="2" stroke-dasharray="5 4"/>')
    el.append(f'<line x1="{fx(W/2):.1f}" y1="{fy(H)}" x2="{fx(W/2):.1f}" y2="{fy(0)}" '
              f'stroke="#445" stroke-width="1.5"/>')
    el.append(f'<text x="{pad}" y="16" fill="#9fc0ff" font-size="13">{title}</text>')
    el.append(f'<text x="{fx(meanx):.0f}" y="{fy(H)+16}" fill="#ffd479" font-size="11" '
              f'text-anchor="middle">mean x={meanx:.1f}</text>')
    el.append(f'<text x="{fx(W/2):.0f}" y="{h-6}" fill="#778" font-size="10" '
              f'text-anchor="middle">center W/2={W/2:.1f}</text>')
    el.append("</svg>")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset=utf-8><body style='margin:0;background:#0b0e14'>"
                f"{''.join(el)}</body>")


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    bay_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    path = os.path.join(TRAIN, nm + ".json")
    sub = tp.build_subset(path, bay_id, 2)        # bay_id=None → 선호 최다 베이
    W, H = sub["W"], sub["H"]
    order = tp.seed_order(sub, "edd")
    # 후보 산포 캡처(한 step) — 후보 (x,y) 가 진짜 다양한가
    tp._CAP = {"min_cands": 8, "min_present": 8, "counts": []}
    placed, z1 = tp.simulate(sub, order, allow_stack=False, fit=True)
    cap = tp._CAP.get("out")
    tp._CAP = None

    cents = []
    for p in placed:
        ring = tp._ring0(p["world"])
        if not ring:
            continue
        cx = sum(v[0] for v in ring) / len(ring)
        cy = sum(v[1] for v in ring) / len(ring)
        cents.append((cx, cy))
    n = len(cents)
    meanx = sum(c[0] for c in cents) / max(1, n)
    left = sum(1 for c in cents if c[0] < W / 3)
    mid = sum(1 for c in cents if W / 3 <= c[0] < 2 * W / 3)
    right = sum(1 for c in cents if c[0] >= 2 * W / 3)
    minx = min((c[0] for c in cents), default=0)
    maxx = max((c[0] for c in cents), default=0)

    print(f"== [{nm}] bay {sub['bay_id']}  W×H={W}×{H}  블록 {n}개  z1={z1} ==", flush=True)
    print(f"  diverse 활성: {tp._DIVERSE}  (fit=True 라 div={bool(True) and tp._DIVERSE})", flush=True)
    print(f"  centroid x 평균 = {meanx:.1f} / W={W}  ({100*meanx/W:.0f}% 지점, 중앙=50%)", flush=True)
    print(f"  x 범위 = [{minx:.1f}, {maxx:.1f}]  → 가로 사용 {100*(maxx-minx)/W:.0f}%", flush=True)
    print(f"  좌1/3:중1/3:우1/3 = {left}:{mid}:{right}  "
          f"({100*left/max(1,n):.0f}% : {100*mid/max(1,n):.0f}% : {100*right/max(1,n):.0f}%)", flush=True)
    verdict = ("⚠ 왼쪽 쏠림" if meanx < W * 0.4 else
               "→ 가운데~분산 (정상)" if meanx < W * 0.6 else "오른쪽 쏠림")
    print(f"  판정: {verdict}", flush=True)
    if cap:
        cx = sorted(set(c["x"] for c in cap["cands"]))
        cy = sorted(set(c["y"] for c in cap["cands"]))
        print(f"  [후보 산포] step(블록 {cap['bid']}, present {len(cap['present'])}): "
              f"{len(cap['cands'])}후보, x값 {len(cx)}종 {cx[:8]}{'...' if len(cx)>8 else ''}, "
              f"y값 {len(cy)}종", flush=True)

    out = os.path.join(THIS, "out", f"bias_{nm}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    topview(out, W, H, placed, meanx, f"{nm} bay{sub['bay_id']} 실제 패킹 (파랑=먼저→빨강=나중)  z1={z1}")
    print(f"  wrote {out}", flush=True)
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", out], shell=False)


if __name__ == "__main__":
    main()
