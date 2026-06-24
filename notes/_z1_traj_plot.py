"""Per-instance large-panel renderer for the Z1-trajectory harness
(notes/_z1_traj_run.py).

Renders ONE LARGE, full-width figure PER instance that has data (started or
done) to results/z1traj/panel_<inst>.png.  Each panel draws the dense
1-second-resolution z1 step curve and, crucially, the SEQUENCE (stage) labels
drawn ON the curve: at every stage boundary in `dense` a light vertical dashed
separator + the stage name is drawn, so the curve reads as
"search | cum_level | cpsat_timing | …" even DURING a live run (labels come from
`dense` alone, not stage_marks).  z1=0 arrivals get a green line + ✅ title; the
live instance gets a red "🔴 LIVE" title with its current stage and z1.  Pending
instances get NO panel file — they show as disabled tabs in the HTML.

The HTML (results/z1traj/z1_trajectory.html) is a CLICKABLE dashboard: a tab bar
(one button per prob_1..prob_20, color/badge by state) over a single pan/zoom
main view that shows the SELECTED instance's panel_<inst>.png.  Clicking a tab
swaps the image and sets location.hash so the selection survives the watcher's
~3s HTML rewrites; the shown image self-refreshes live every 3s; badges refresh
via a gentle ~12s full-page reload that is suppressed while the user is
interacting.

Two entrypoints:
  * render(data) — given an in-memory data dict (used by the live watcher), draw.
  * main()       — read every results/z1traj/<inst>_solve.json (+ _baseline if
                   present) off disk and call render() (back-compat / standalone).

Non-interactive backend (Agg) so it runs headless.

Usage (from project root):
  conda run -n ogc2025 python notes/_z1_traj_plot.py
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "results" / "z1traj"
HTML = OUT_DIR / "z1_trajectory.html"


def _panel_png(inst: str) -> Path:
    """Path to one instance's large panel PNG."""
    return OUT_DIR / f"panel_{inst}.png"


# Fixed display/sort order: numeric prob_1..prob_20.
INSTANCES = [f"prob_{n}" for n in range(1, 21)]

# Per-instance figure geometry (one large landscape figure per instance).
PANEL_W = 16.0          # figure width (inches).
PANEL_H = 6.5           # figure height (inches).
# Light tint colors for alternating stage segments (cycled).
_SEG_TINTS = ["#f2f6fc", "#fcf5ec"]

# Module-level cache of a cheap per-instance signature so the 3s watcher tick
# only re-renders panels whose data actually changed (live panels always
# re-render).  inst -> signature tuple.
_PANEL_SIG: dict = {}

# Distinct, high-contrast color per known stage so each SEQUENCE reads as its own
# color on the curve, the boundary labels, and the legend.
STAGE_COLORS = {
    "search":            "#7f7f7f",   # gray
    "incumbent":         "#7f7f7f",   # gray (same family as search)
    "baseline":          "#555555",   # dark gray (first verified floor)
    "seeds_decode":      "#bcbd22",   # olive (seed-decode incumbents)
    "cum_level":         "#1f77b4",   # blue
    "cpsat_timing":      "#ff7f0e",   # orange
    "bbox_pack":         "#2ca02c",   # green
    "crossbay_relocate": "#9467bd",   # purple
    "bbox_pack2":        "#17becf",   # cyan
    "shift_tardy":       "#8c564b",   # brown
    "tardy_redecode":    "#e377c2",   # pink
}
# Deterministic fallback palette for any stage not in STAGE_COLORS.
_FALLBACK_COLORS = [
    "#bcbd22", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896",
    "#c5b0d5", "#c49c94", "#f7b6d2", "#dbdb8d", "#9edae5",
]


def _stage_color(stage: str) -> str:
    """Distinct color for a stage name; deterministic fallback if unknown.

    Empty/None stage (legacy 2-element points) -> neutral blue so the curve
    still draws.  Unknown stages hash by name into a small fallback palette so
    the same name always gets the same color across panels and runs.
    """
    if not stage:
        return "#1f77b4"
    c = STAGE_COLORS.get(stage)
    if c is not None:
        return c
    idx = sum(ord(ch) for ch in stage) % len(_FALLBACK_COLORS)
    return _FALLBACK_COLORS[idx]


def _fmt_z1(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.2f}"
    except Exception:
        return str(v)


def _fmt_wall(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.0f}"
    except Exception:
        return str(v)


def _stage_segments(dense: list) -> list:
    """From a dense [[t, z1, stage], ...] curve, find stage boundaries.

    Returns [(x_start, stage, z1_at_start), ...] — one entry per contiguous run
    of equal stage (the FIRST point of each run).  The very first point counts
    as a boundary.  2-element legacy points (no stage) collapse to stage "".
    """
    segs: list = []
    prev_stage = None
    for p in dense:
        if not p:
            continue
        x = p[0]
        z = p[1]
        stage = str(p[2]) if len(p) >= 3 and p[2] is not None else ""
        if stage != prev_stage:
            segs.append((x, stage, z))
            prev_stage = stage
    return segs


def _draw_panel(ax, inst: str, d: dict) -> None:
    """Render ONE LARGE instance panel.  `d` is non-None (has data)."""
    dense = d.get("dense") or []
    final_z1 = d.get("final_z1")
    live = bool(d.get("live"))
    reached = bool(d.get("reached_zero"))
    cur_stage = d.get("cur_stage")
    wall = d.get("wall")
    if wall is None:
        wall = d.get("wall_total")

    ymax = 0.0
    cur_z = None
    # Title accent color (curve color is now PER-STAGE, set below).
    title_color = "#c5221f" if live else "#1f77b4"

    xs: list = []
    ys: list = []
    stages: list = []
    seen_stages: list = []   # stages present, in first-appearance order (legend).
    if dense:
        xs = [p[0] for p in dense]
        ys = [p[1] for p in dense]
        stages = [str(p[2]) if len(p) >= 3 and p[2] is not None else ""
                  for p in dense]
        if wall and wall > xs[-1]:
            # extend the last point to the live wall clock; keep its stage so the
            # final running stage's color reaches the right edge.
            xs = xs + [wall]
            ys = ys + [ys[-1]]
            stages = stages + [stages[-1]]
        # Draw the curve as colored per-stage segments: each maximal run of
        # consecutive points sharing a stage is one steps-post sub-line in that
        # stage's color.  To keep steps-post visually CONTINUOUS across a stage
        # boundary, the segment INCLUDES the first point of the next run as its
        # closing point (no gap; the boundary's vertical riser belongs to the
        # earlier color).
        n = len(xs)
        i = 0
        last_run_start = 0
        while i < n:
            j = i
            while j + 1 < n and stages[j + 1] == stages[i]:
                j += 1
            st = stages[i]
            if st and st not in seen_stages:
                seen_stages.append(st)
            seg_color = _stage_color(st)
            # close the segment on the next run's first point for continuity.
            end = j + 1 if j + 1 < n else j
            seg_xs = xs[i:end + 1]
            seg_ys = ys[i:end + 1]
            lw = 2.2
            # thin red highlight on the CURRENTLY-running (last) stage for live.
            if live and end >= n - 1:
                ax.plot(seg_xs, seg_ys, drawstyle="steps-post",
                        color="#d62728", lw=3.4, alpha=0.35, zorder=4)
            ax.plot(seg_xs, seg_ys, drawstyle="steps-post",
                    color=seg_color, lw=lw, zorder=5)
            last_run_start = i
            i = j + 1
        _ = last_run_start
        ymax = max(ymax, max(ys))
        cur_z = ys[-1]
    elif final_z1 is not None:
        try:
            ymax = max(ymax, float(final_z1))
        except Exception:
            pass
        cur_z = final_z1

    top = (ymax * 1.1 + 1.0) if ymax > 0 else 1.0
    x_right = (xs[-1] if xs else (wall or 1.0))
    x_left = (xs[0] if xs else 0.0)

    # ---- SEQUENCE (stage) labels drawn ON the curve, from `dense` alone ---- #
    segs = _stage_segments(dense)
    # Optional alternating segment tint (light) between boundaries.
    for i, (sx, sname, _sz) in enumerate(segs):
        nx = segs[i + 1][0] if i + 1 < len(segs) else x_right
        if nx > sx:
            ax.axvspan(sx, nx, color=_SEG_TINTS[i % len(_SEG_TINTS)],
                       alpha=0.6, zorder=0)
    # Boundary separators + readable stage-name labels + z1 annotation.
    # Each label/separator is colored to MATCH its stage's segment color.
    label_y = top * 0.95
    for i, (sx, sname, sz) in enumerate(segs):
        scol = _stage_color(sname)
        # vertical dashed separator (skip a redundant one at the very left edge).
        if i > 0:
            ax.axvline(sx, color=scol, ls="--", lw=1.0, alpha=0.7, zorder=2)
        if sname:
            ax.text(sx, label_y, f" {sname}", rotation=30, fontsize=10.5,
                    color=scol, fontweight="bold", va="top", ha="left", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec=scol, alpha=0.85))
        # z1 value at this stage-boundary point.
        ax.annotate(_fmt_z1(sz), xy=(sx, sz), xytext=(2, 4),
                    textcoords="offset points", fontsize=9, color="#555",
                    zorder=6)

    # bold final / current z1 at the right end (colored by the last stage so it
    # matches the curve's right-end segment color).
    if xs:
        ann = final_z1 if (final_z1 is not None and not live) else ys[-1]
        end_col = _stage_color(stages[-1]) if stages else title_color
        ax.annotate(_fmt_z1(ann), xy=(xs[-1], ys[-1]), xytext=(6, 2),
                    textcoords="offset points", fontsize=12, fontweight="bold",
                    color=end_col, zorder=7)

    # z1=0 arrival highlight (green dashed horizontal line).
    if reached:
        ax.axhline(0.0, color="#137333", ls="--", lw=1.5, alpha=0.85, zorder=3)

    # Per-panel stage->color legend (only stages that actually appear), compact
    # and placed top-right so it does not cover the curve.
    if seen_stages:
        from matplotlib.lines import Line2D
        handles = [Line2D([0], [0], color=_stage_color(s), lw=2.6, label=s)
                   for s in seen_stages]
        ax.legend(handles=handles, loc="upper right", fontsize=8,
                  ncol=2 if len(handles) > 4 else 1, framealpha=0.85,
                  borderpad=0.4, labelspacing=0.3, handlelength=1.4)

    # title: LIVE (red, + current stage/z1) vs reached-zero vs plain.
    if live:
        cz = _fmt_z1(cur_z)
        extra = f" · 현재: {cur_stage}" if cur_stage else ""
        ax.set_title(f"🔴 LIVE {inst} · z1={cz}{extra}", fontsize=14,
                     color=title_color, fontweight="bold")
    elif reached:
        ax.set_title(f"{inst}   ✅ z1=0 @ {_fmt_wall(wall)}s", fontsize=14,
                     color="#137333", fontweight="bold")
    else:
        ax.set_title(f"{inst}   z1={_fmt_z1(final_z1)}", fontsize=14,
                     fontweight="bold")

    ax.set_xlabel("wall seconds", fontsize=11)
    ax.set_ylabel("z1", fontsize=11)
    ax.tick_params(labelsize=10)
    ax.set_ylim(bottom=0, top=top)
    if x_right > x_left:
        ax.set_xlim(left=min(0.0, x_left), right=x_right * 1.02 + 0.5)
    ax.grid(True, alpha=0.3)


def _panel_signature(d: dict) -> tuple:
    """Cheap change-detection signature for one instance's data.

    Captures the things that change the rendered panel: dense length, the last
    dense point, the final z1, the live flag, and the reached-zero flag.  Two
    equal signatures => the panel image would look the same => skip re-render
    (unless live, which the caller always re-renders).
    """
    dense = d.get("dense") or []
    last = tuple(dense[-1]) if dense else None
    return (
        len(dense),
        last,
        d.get("final_z1"),
        bool(d.get("live")),
        bool(d.get("reached_zero")),
    )


def _render_panel(inst: str, d: dict) -> None:
    """Render ONE instance's large landscape figure to panel_<inst>.png."""
    fig, ax = plt.subplots(figsize=(PANEL_W, PANEL_H))
    try:
        _draw_panel(ax, inst, d)
        fig.tight_layout()
        fig.savefig(_panel_png(inst), dpi=120)
    finally:
        plt.close(fig)


def render(data: dict) -> None:
    """Render a LARGE per-instance panel PNG for each instance with data, then
    write the clickable HTML dashboard.

    Only instances that HAVE DATA (started or done) get a panel file; pending
    instances are shown as disabled tabs in the HTML.  To keep the ~3s watcher
    tick fast we only re-render a panel whose cheap signature changed since the
    last render; LIVE instances are always re-rendered.

    data: {inst -> {dense, stage_marks, final_z1, feasible, wall, live,
                    cur_stage, reached_zero}}.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    active = [i for i in INSTANCES if data.get(i)]
    pending = [i for i in INSTANCES if not data.get(i)]

    for inst in active:
        d = data[inst]
        sig = _panel_signature(d)
        live = bool(d.get("live"))
        # Always re-render live panels (cur stage/z1 advance); otherwise skip
        # when the data is unchanged since the last render.
        if not live and _PANEL_SIG.get(inst) == sig and _panel_png(inst).exists():
            continue
        try:
            _render_panel(inst, d)
            _PANEL_SIG[inst] = sig
        except Exception:
            # never let one bad instance break the whole tick.
            _PANEL_SIG.pop(inst, None)

    done = sum(1 for i in INSTANCES
               if data.get(i) and not data[i].get("live"))
    zeros = sum(1 for i in INSTANCES
                if data.get(i) and data[i].get("reached_zero"))
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_html(data, done, zeros, ts, pending)


def _tab_meta(inst: str, d: dict) -> dict:
    """Per-instance tab metadata: state class, badge label, whether it has a
    panel (clickable) and whether it is live."""
    if not d:
        return {"cls": "pending", "badge": "대기", "has": False, "live": False}
    live = bool(d.get("live"))
    reached = bool(d.get("reached_zero"))
    fz = d.get("final_z1")
    if live and fz is None:
        dense = d.get("dense") or []
        fz = dense[-1][1] if dense else None
    if live:
        return {"cls": "live", "badge": "🔴", "has": True, "live": True}
    if reached:
        return {"cls": "done-zero", "badge": "✅", "has": True, "live": False}
    return {"cls": "done", "badge": _fmt_z1(fz), "has": True, "live": False}


def _write_html(data: dict, done: int, zeros: int, ts: str,
                pending: list | None = None) -> None:
    pending = pending or [i for i in INSTANCES if not data.get(i)]
    pend_line = ("대기: " + ", ".join(pending)) if pending else "대기: (없음)"

    # ---- tab bar: one button per prob_1..prob_20, colored/badged by state ----
    btns = []
    first_live = None
    first_data = None
    for inst in INSTANCES:
        d = data.get(inst) or {}
        m = _tab_meta(inst, d)
        if m["live"] and first_live is None:
            first_live = inst
        if m["has"] and first_data is None:
            first_data = inst
        disabled = "" if m["has"] else " disabled"
        dis_attr = "" if m["has"] else ' aria-disabled="true"'
        btns.append(
            f'<button class="tab {m["cls"]}" id="tab_{inst}"'
            f' data-inst="{inst}" data-has="{1 if m["has"] else 0}"'
            f'{disabled}{dis_attr}>'
            f'<span class="tn">{inst}</span>'
            f'<span class="tb">{m["badge"]}</span></button>'
        )
    tabbar = "\n".join(btns)

    # default selection: first live, else first with data, else prob_1.
    default_inst = first_live or first_data or "prob_1"
    cb = datetime.datetime.now().strftime("%H%M%S")

    # CSS + JS kept as PLAIN strings (single braces) and injected via {STYLE}/{JS}
    # so the f-string never has to double-escape their braces.
    STYLE = """<style>
 body { font-family: -apple-system, Segoe UI, sans-serif; margin: 16px; }
 h1 { font-size: 19px; margin: 4px 0; }
 .prog { color: #1a73e8; font-size: 14px; font-weight: 600; margin: 6px 0; }
 .pending { color: #888; font-size: 13px; margin: 6px 0; }
 .note { color: #666; font-size: 12px; margin: 6px 0; }
 .ctl { margin: 8px 0; }
 .ctl button { font-size: 13px; padding: 4px 12px; margin-right: 8px; cursor: pointer; }
 #tabbar { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
 .tab { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
        padding: 5px 9px; border: 1px solid #bbb; border-radius: 6px;
        cursor: pointer; background: #eee; color: #333; line-height: 1.1; }
 .tab .tb { font-weight: 700; font-size: 11px; }
 .tab.pending { background: #f0f0f0; color: #999; cursor: not-allowed; }
 .tab.live { background: #fde8e8; border-color: #e57373; color: #b71c1c; }
 .tab.done-zero { background: #e6f4ea; border-color: #66bb6a; color: #137333; }
 .tab.done { background: #e8f0fe; border-color: #7baaf7; color: #1a4fb0; }
 .tab.sel { outline: 3px solid #1a73e8; outline-offset: 1px; font-weight: 700; }
 #imgwrap { height: 82vh; overflow: hidden; border: 1px solid #ccc;
            background: #fafafa; cursor: grab; position: relative; }
 #g { width: 100%; transform-origin: 0 0; will-change: transform;
      user-select: none; -webkit-user-drag: none; }
</style>"""

    JS = """<script>
(function(){
  var img=document.getElementById('g'), wrap=document.getElementById('imgwrap');
  var scale=1, tx=0, ty=0, drag=false, sx=0, sy=0;
  var cur=null, lastInteraction=Date.now();
  function touch(){ lastInteraction=Date.now(); }
  function apply(){ img.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')'; }
  function reset(){ scale=1; tx=0; ty=0; apply(); }
  // valid clickable instances (have a panel image).
  var TABS={}; var btns=document.querySelectorAll('.tab');
  btns.forEach(function(b){ TABS[b.getAttribute('data-inst')]=(b.getAttribute('data-has')==='1'); });
  function setSel(inst){
    var prev=document.querySelector('.tab.sel'); if(prev) prev.classList.remove('sel');
    var b=document.getElementById('tab_'+inst); if(b) b.classList.add('sel');
  }
  function show(inst, keepView){
    cur=inst;
    if(!keepView) reset();
    img.src='panel_'+inst+'.png?v='+Date.now();
    setSel(inst);
  }
  function pickDefault(){
    var h=(location.hash||'').replace('#','');
    if(h && TABS[h]) return h;
    return window.__DEFAULT_INST__;
  }
  // tab clicks: swap image + set hash so the selection survives HTML rewrites.
  btns.forEach(function(b){
    b.addEventListener('click', function(){
      var inst=b.getAttribute('data-inst');
      if(b.getAttribute('data-has')!=='1') return;
      touch();
      location.hash=inst;
      show(inst, false);
    });
  });
  // pan/zoom (counts as interaction so the badge reload won't yank the view).
  wrap.addEventListener('wheel', function(e){
    e.preventDefault(); touch();
    var r=wrap.getBoundingClientRect(), cx=e.clientX-r.left, cy=e.clientY-r.top;
    var f=e.deltaY<0?1.15:1/1.15, ns=Math.min(40,Math.max(1,scale*f));
    tx=cx-(cx-tx)*(ns/scale); ty=cy-(cy-ty)*(ns/scale); scale=ns; apply();
  }, {passive:false});
  wrap.addEventListener('mousedown', function(e){ drag=true; touch(); sx=e.clientX-tx; sy=e.clientY-ty; wrap.style.cursor='grabbing'; e.preventDefault(); });
  window.addEventListener('mouseup', function(){ drag=false; wrap.style.cursor='grab'; });
  window.addEventListener('mousemove', function(e){ if(!drag)return; touch(); tx=e.clientX-sx; ty=e.clientY-sy; apply(); });
  img.addEventListener('dblclick', function(){ touch(); reset(); });
  document.getElementById('reset').addEventListener('click', function(){ touch(); reset(); });
  window.addEventListener('hashchange', function(){
    var h=(location.hash||'').replace('#','');
    if(h && TABS[h] && h!==cur) show(h, false);
  });
  // initial selection from hash, else first live / first-with-data / prob_1.
  show(pickDefault(), false);
  // LIVE: refresh ONLY the currently-selected panel image (cache-busted) so the
  // user's zoom/pan persists; do NOT full-reload the page on this timer.
  setInterval(function(){
    if(!cur || !TABS[cur]) return;
    var i=new Image(); i.onload=function(){ img.src=i.src; };
    i.src='panel_'+cur+'.png?v='+Date.now();
  }, 3000);
  // BADGES: gentle full-page reload to pick up the watcher's rewritten tab
  // badges -- but skip it if the user interacted within the last ~10s; the
  // location.hash keeps the selected tab across the reload.
  setInterval(function(){
    if(Date.now()-lastInteraction < 10000) return;   // user is active: skip.
    location.reload();
  }, 12000);
})();
</script>"""

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>Z1 trajectory (solve-all)</title>
{STYLE}</head>
<body>
<h1>Z1 궤적 — 인스턴스 클릭 → 그 인스턴스의 큰 그래프 · 1초 해상도</h1>
<p class="prog">진행 {done}/20 · z1=0 도달 {zeros}/20 · 갱신 {ts}</p>
<p class="pending">{pend_line}</p>
<p class="note">아래 탭에서 인스턴스를 <b>클릭</b>하면 그 인스턴스의 큰 그래프가 표시됩니다.
x = wall초, y = z1 (steps-post). 세로 점선 = stage 경계(search | cum_level | cpsat_timing …).
🔴=진행 중, ✅=z1=0 도달, 숫자=최종 z1, 회색=대기. 선택 그래프는 3초마다 실시간 갱신(줌/팬 유지).</p>
<div id="tabbar">
{tabbar}
</div>
<div class="ctl">
 <button id="reset">리셋(1:1)</button>
 <span class="note">휠=확대/축소(커서 기준) · 드래그=이동 · 더블클릭=리셋</span>
</div>
<div id="imgwrap"><img id="g" src="panel_{default_inst}.png?v={cb}" alt="z1 trajectory"></div>
<script>window.__DEFAULT_INST__={default_inst!r};</script>
{JS}
</body></html>
"""
    HTML.write_text(html, encoding="utf-8")


def _load_disk() -> dict:
    """Read every results/z1traj/<inst>_solve.json (+ _baseline fallback) into a
    render-ready data dict.  Robust to missing/partial/corrupt files."""
    data: dict = {}
    for inst in INSTANCES:
        rec = None
        for cfg in ("solve", "baseline"):  # solve wins if both exist.
            f = OUT_DIR / f"{inst}_{cfg}.json"
            if not f.exists():
                continue
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            rec = r
            break
        if rec is None:
            continue
        data[inst] = {
            "dense": rec.get("dense") or [],
            "stage_marks": rec.get("stage_marks") or [],
            "final_z1": rec.get("final_z1"),
            "feasible": rec.get("feasible"),
            "wall": rec.get("wall_total"),
            "live": False,
            "reached_zero": bool(rec.get("reached_zero")),
            "early_exit": bool(rec.get("early_exit")),
        }
    return data


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = _load_disk()
    render(data)
    n_panels = sum(1 for i in INSTANCES if _panel_png(i).exists())
    print(f"[z1_plot] {len(data)} run(s) -> {n_panels} panel PNG(s) in {OUT_DIR}")
    print(f"[z1_plot] {HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
