"""
viz3d.py -- 3D spatio-temporal visualization of an OGC 2026 shipyard solution.

Renders ONE instance's solution as an interactive plotly HTML.  Each block is a
PRISM: its 2D footprint (layer-0 world polygon) extruded along the TIME axis
from its entry time (z0) to its exit time (z1).

AXES
    x = block footprint X (within a bay), with bays laid SIDE BY SIDE along X
        (bay j gets x-offset = cumsum of previous bay widths + gap)
    y = block footprint Y (within a bay)
    z = TIME (entry -> exit)  <-- the extrusion axis

COLOR (status, priority order)
    1. tardy  (exit > due_date)                 -> RED   (crimson)      -- takes priority
    2. else wrong bay (assigned != preferred)   -> BLUE  (royalblue)
    3. else ok (preferred bay AND on-time)      -> GREEN (mediumseagreen)

CLI
    python viz3d.py [prob=prob_38] [sol_file]
    default sol_file = real_<prob>.json in this directory.

Output
    viz3d_<prob>.html in this directory.
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import plotly.graph_objects as go  # noqa: E402

import adapter  # noqa: E402
import seed     # noqa: E402


# colors by status
_C_TARDY = "crimson"
_C_WRONG = "royalblue"
_C_OK = "mediumseagreen"
_BAY_GAP = 5.0          # gap (in x units) between adjacent bays
_OPACITY = 0.6


# ---------------------------------------------------------------------------
def _prism(coords, z0, z1, color, name, opacity=_OPACITY):
    """Extrude a 2D ring `coords` [(x,y),...] from z=z0 to z=z1 -> Mesh3d.

    Builds bottom face + top face + side walls as a triangle mesh.  Uses a
    fan triangulation for the caps (fine for the simple, near-convex block
    footprints here).  Returns a plotly Mesh3d, or None if degenerate.
    """
    # drop a duplicate closing vertex if the ring is closed
    ring = list(coords)
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    n = len(ring)
    if n < 3:
        return None

    xs, ys, zs = [], [], []
    # bottom ring -> verts [0 .. n-1]
    for (x, y) in ring:
        xs.append(x); ys.append(y); zs.append(z0)
    # top ring -> verts [n .. 2n-1]
    for (x, y) in ring:
        xs.append(x); ys.append(y); zs.append(z1)

    I, J, K = [], [], []

    # bottom cap (fan from vert 0), top cap (fan from vert n)
    for t in range(1, n - 1):
        I.append(0);     J.append(t);     K.append(t + 1)        # bottom
        I.append(n);     J.append(n + t); K.append(n + t + 1)    # top

    # side walls: quad (a, b, b', a') -> two triangles
    for a in range(n):
        b = (a + 1) % n
        ta, tb = a + n, b + n
        I.append(a);  J.append(b);  K.append(tb)
        I.append(a);  J.append(tb); K.append(ta)

    return go.Mesh3d(
        x=xs, y=ys, z=zs, i=I, j=J, k=K,
        color=color, opacity=opacity, flatshading=True,
        name=name, hovertext=name, hoverinfo="text",
        showlegend=False,
    )


# ---------------------------------------------------------------------------
def _ring_from_world_poly(poly):
    """layer-0 world shapely polygon -> list[(x,y)] exterior ring, or None."""
    if poly is None or poly.is_empty:
        return None
    try:
        coords = list(poly.exterior.coords)
    except Exception:
        return None
    if len(coords) < 4:   # need >=3 distinct + closing point
        return None
    return coords


def _bbox_ring(p, xoff=0.0):
    """Fallback footprint = block bbox rectangle (shifted by xoff)."""
    sh = p["sh"]
    x, y = p["x"], p["y"]
    x0 = sh.min_x + x + xoff
    y0 = sh.min_y + y
    x1 = sh.max_x + x + xoff
    y1 = sh.max_y + y
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


# ---------------------------------------------------------------------------
def build_figure(prob: str, data: dict, sol: dict, bays_placed: dict) -> go.Figure:
    blocks = data["blocks"]
    bays = data["bays"]
    m = len(bays)

    # preferred bay per block = argmax bay_preferences
    def _pref(bid):
        prefs = blocks[bid]["bay_preferences"]
        return max(range(len(prefs)), key=lambda j: prefs[j])

    def _due(bid):
        return blocks[bid].get("due_date", 0)

    # x-offset per bay: cumulative (prev widths + gap)
    x_off = {}
    cur = 0.0
    for j in range(m):
        x_off[j] = cur
        cur += bays[j]["width"] + _BAY_GAP

    # global min entry (for bay floor z) and time range
    all_entries = [p["entry"] for pl in bays_placed.values() for p in pl]
    all_exits = [p["exit"] for pl in bays_placed.values() for p in pl]
    z_floor = min(all_entries) if all_entries else 0

    fig = go.Figure()

    n_red = n_blue = n_green = 0
    n_skip = 0

    for j, placed in bays_placed.items():
        off = x_off.get(j, 0.0)
        bw, bh = bays[j]["width"], bays[j]["height"]

        # --- faint bay floor rectangle at z=z_floor ---
        fx = [off, off + bw, off + bw, off]
        fy = [0, 0, bh, bh]
        fz = [z_floor] * 4
        fig.add_trace(go.Mesh3d(
            x=fx, y=fy, z=fz,
            i=[0, 0], j=[1, 2], k=[2, 3],
            color="lightgray", opacity=0.15,
            name=f"bay {j} floor", hoverinfo="skip", showlegend=False,
        ))
        # bay label
        fig.add_trace(go.Scatter3d(
            x=[off + bw / 2.0], y=[bh / 2.0], z=[z_floor],
            mode="text", text=[f"bay {j} ({bw}x{bh})"],
            textfont=dict(size=11, color="dimgray"),
            hoverinfo="skip", showlegend=False,
        ))

        # --- block prisms ---
        for p in placed:
            bid = p["id"]
            entry, exit_t = p["entry"], p["exit"]

            # footprint ring: prefer real layer-0 world polygon
            poly0 = p["world"].get(0) if isinstance(p["world"], dict) else None
            ring = _ring_from_world_poly(poly0)
            if ring is not None:
                ring = [(x + off, y) for (x, y) in ring]
            else:
                ring = _bbox_ring(p, xoff=off)
            if ring is None:
                n_skip += 1
                continue

            # status / color (priority: tardy > wrong-bay > ok)
            tardy = exit_t > _due(bid)
            wrong_bay = (j != _pref(bid))
            if tardy:
                color, status = _C_TARDY, "tardy"
                n_red += 1
            elif wrong_bay:
                color, status = _C_WRONG, "wrong-bay"
                n_blue += 1
            else:
                color, status = _C_OK, "ok"
                n_green += 1

            z0, z1 = float(entry), float(exit_t)
            if z1 <= z0:          # degenerate-in-time: give a tiny slab
                z1 = z0 + 0.5

            name = (f"blk {bid} | bay {j} | t[{int(entry)}..{int(exit_t)}] "
                    f"due {_due(bid)} | {status}")
            mesh = _prism(ring, z0, z1, color, name)
            if mesh is None:
                n_skip += 1
                continue
            fig.add_trace(mesh)

    # --- legend via dummy Scatter3d traces ---
    for col, lbl in ((_C_TARDY, "tardy (z1)"),
                     (_C_WRONG, "wrong bay (z3)"),
                     (_C_OK, "ok")):
        fig.add_trace(go.Scatter3d(
            x=[None], y=[None], z=[None], mode="markers",
            marker=dict(size=8, color=col), name=lbl, showlegend=True,
        ))

    # --- objective for the title ---
    ev = seed.global_eval(data, bays_placed)
    obj, z1, z2, z3 = ev["obj"], ev["z1"], ev["z2"], ev["z3"]
    title = (f"{prob} - 3D (x,y, z=time)  red=tardy blue=wrong-bay green=ok  | "
             f"obj={obj} z1={z1} z2={z2} z3={z3}")

    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="position x (bays side by side)",
            yaxis_title="position y",
            zaxis_title="time (entry->exit)",
        ),
        legend=dict(title="status", itemsizing="constant"),
        margin=dict(l=0, r=0, t=40, b=0),
    )

    fig._viz_counts = (n_red, n_blue, n_green, n_skip)  # stash for caller
    return fig


# ---------------------------------------------------------------------------
def main(argv):
    prob = argv[1] if len(argv) > 1 else "prob_38"
    sol_file = argv[2] if len(argv) > 2 else os.path.join(THIS, f"real_{prob}.json")

    inst_path = os.path.normpath(
        os.path.join(THIS, "..", "instances", "train", f"{prob}.json"))

    data = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_file, encoding="utf-8"))
    bays_placed = adapter.deserialize(data, sol)

    fig = build_figure(prob, data, sol, bays_placed)
    n_red, n_blue, n_green, n_skip = fig._viz_counts
    total = n_red + n_blue + n_green

    out_path = os.path.join(THIS, f"viz3d_{prob}.html")
    fig.write_html(out_path, include_plotlyjs="cdn")

    print(f"[viz3d] prob          = {prob}", flush=True)
    print(f"[viz3d] sol_file      = {sol_file}", flush=True)
    print(f"[viz3d] blocks total  = {total}  (skipped degenerate = {n_skip})",
          flush=True)
    print(f"[viz3d]   red  (tardy)     = {n_red}", flush=True)
    print(f"[viz3d]   blue (wrong-bay) = {n_blue}", flush=True)
    print(f"[viz3d]   green (ok)       = {n_green}", flush=True)
    print(f"[viz3d] output HTML   = {os.path.abspath(out_path)}", flush=True)
    return out_path


if __name__ == "__main__":
    main(sys.argv)
