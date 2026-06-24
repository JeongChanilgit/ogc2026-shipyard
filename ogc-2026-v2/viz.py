"""Self-contained 3D packing visualizer for the OGC2026 shipyard solver experiment.

`write_viz(trace, out_path)` writes a SINGLE self-contained HTML file: Three.js is
loaded from a pinned CDN (ES modules + importmap), and the trace is embedded inline
as a JS const, so the page works from file:// with no external fetch.

Run `python viz.py` to emit a synthetic demo to `out/viz_demo.html`.

Trace contract (MULTI-bay; backward-compatible with the old single-bay form):
  {
    "instance": str,
    # MULTI-bay form: list of bays laid out side-by-side along +X.
    "bays": [ {"id", "width", "height", "max_layer"}, ... ],
    # OLD single-bay form (still accepted): "bay": {"id","width","height","max_layer"}.
    "blocks": { "<id>": {"bay", "orient_idx", "layers": [[[x,y],...], ...],
                         "release","due","proc"} },
    "events": [ {"t", "type": "ENTRY"|"EXIT", "block_id", ("x","y" for ENTRY)} ],
    "stats": { ... arbitrary key/values ... }
  }
Semantics:
  - bays: drawn side-by-side. Bay 0 sits at x-offset 0; bay j at offset
    sum(bays[0..j-1].width) + j*GAP (GAP world units of spacing). Each bay is its own
    wireframe box (0..width, 0..height, 0..max_layer) with a "bay <id>" label above.
  - blocks[<id>].bay: the integer bay index the block belongs to (multi-bay form). In the
    single-bay form this is omitted and all blocks render in bay 0.
  - layers: list of LOCAL-frame polygons, layer 0 = lowest. Open rings (auto-closed).
    May be concave; rendered with THREE.Shape + ExtrudeGeometry.
  - world_vertex.x = bay_x_offset + local_x + ENTRY.x ; world_vertex.y = local_y + ENTRY.y.
  - z = layer index; layer l occupies z in [l, l+1] (extrude depth 1).
  - block present at t iff ENTRY.t <= t < EXIT.t (EXIT optional -> present forever after entry).
  - TARDY: a block is tardy iff its EXIT time > its `due`. Tardy blocks render in a distinct
    red/crimson and are tallied (currently-present + total) in the readout panel.
"""

import json
import os


# The HTML template. The single `__TRACE_JSON__` token is replaced with the embedded
# trace. Everything else is literal; doubled braces are not used (no .format()), so
# JS object/template literals stay intact.
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>OGC2026 Packing Visualizer</title>
<style>
  :root { color-scheme: dark; }
  html, body { margin: 0; height: 100%; background: #0b0e14; color: #d7dde8;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  #app { position: fixed; inset: 0; display: flex; }
  #canvas-wrap { position: relative; flex: 1 1 auto; min-width: 0; }
  canvas { display: block; }
  #panel {
    flex: 0 0 320px; max-width: 40vw; overflow-y: auto; padding: 14px 16px;
    background: #11151f; border-left: 1px solid #232a3a; box-sizing: border-box;
  }
  #panel h1 { font-size: 14px; margin: 0 0 4px; color: #8fb7ff; }
  #panel h2 { font-size: 12px; margin: 16px 0 6px; color: #6fa3ff;
    text-transform: uppercase; letter-spacing: .08em; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
  button {
    background: #1c2435; color: #cfe0ff; border: 1px solid #2c3650;
    border-radius: 6px; padding: 6px 10px; font: inherit; font-size: 12px; cursor: pointer;
  }
  button:hover { background: #26314a; }
  button.active { background: #3457a6; border-color: #4f79d6; color: #fff; }
  #timeslider { width: 100%; }
  .stat { display: flex; justify-content: space-between; gap: 8px;
    padding: 2px 0; font-size: 12px; border-bottom: 1px dotted #232a3a; }
  .stat .k { color: #93a0b8; }
  .stat .v { color: #e8eefb; text-align: right; word-break: break-all; }
  #eventlabel { min-height: 18px; font-size: 12px; color: #ffd479; margin-top: 6px; }
  #legend { display: flex; flex-direction: column; gap: 3px; font-size: 11px; }
  .legitem { display: flex; align-items: center; gap: 6px; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: 0 0 auto; }
  #statsbox { font-size: 11px; }
  #overlay { position: absolute; left: 10px; top: 10px; font-size: 12px;
    color: #9fb0cc; background: rgba(11,14,20,.6); padding: 6px 9px; border-radius: 6px;
    pointer-events: none; }
  .muted { color: #67718a; }
</style>
</head>
<body>
<div id="app">
  <div id="canvas-wrap">
    <div id="overlay">drag = rotate &middot; wheel = zoom &middot; right-drag = pan</div>
  </div>
  <div id="panel">
    <h1 id="title">OGC2026 Packing</h1>
    <div class="muted" id="bayinfo"></div>

    <h2>Time</h2>
    <input id="timeslider" type="range" min="0" max="0" step="1" value="0" />
    <div class="row">
      <button id="btn-prev">&laquo; Prev</button>
      <button id="btn-play">Play</button>
      <button id="btn-next">Next &raquo;</button>
    </div>
    <div id="eventlabel"></div>

    <h2>Views</h2>
    <div class="row">
      <button id="view-top">Top (x-y)</button>
      <button id="view-front">Front (x-z)</button>
      <button id="view-side">Side (y-z)</button>
      <button id="view-iso" class="active">Iso</button>
    </div>

    <h2>Readout</h2>
    <div class="stat"><span class="k">time</span><span class="v" id="r-time">-</span></div>
    <div class="stat"><span class="k">blocks present</span><span class="v" id="r-count">-</span></div>
    <div class="stat"><span class="k">tardy blocks</span><span class="v" id="r-tardy">-</span></div>
    <div class="stat"><span class="k">floor utilization</span><span class="v" id="r-util">-</span></div>

    <h2>Legend</h2>
    <div id="legend"></div>

    <h2>Stats</h2>
    <div id="statsbox"></div>
  </div>
</div>

<script>const TRACE = __TRACE_JSON__;</script>

<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ---------------------------------------------------------------------------
// Data prep
// ---------------------------------------------------------------------------
const GAP = 8;   // world-unit spacing between adjacent bays along +X

// Normalize bays to a list (backward compat: a single "bay" -> one-element list).
let bayList = TRACE.bays;
if (!bayList || !bayList.length) {
  bayList = [TRACE.bay || { width: 10, height: 10, max_layer: 1 }];
}
bayList = bayList.map((b, j) => ({
  id: (b.id !== undefined ? b.id : j),
  width: b.width, height: b.height,
  max_layer: Math.max(1, b.max_layer || 1),
}));

// X-offset of each bay = cumulative widths of preceding bays + GAP per gap.
const bayOffset = [];
{
  let acc = 0;
  for (let j = 0; j < bayList.length; j++) {
    bayOffset.push(acc);
    acc += bayList[j].width + GAP;
  }
}
// Overall extent used for camera framing / lights / grid spans.
const totalW = bayOffset.length
  ? bayOffset[bayOffset.length - 1] + bayList[bayList.length - 1].width
  : 10;
const maxH = Math.max(1, ...bayList.map(b => b.height));
const maxL = Math.max(1, ...bayList.map(b => b.max_layer));

const blocks = TRACE.blocks || {};
const events = (TRACE.events || []).slice().sort((a, b) => a.t - b.t);

// Distinct sorted event times (the slider domain).
const times = Array.from(new Set(events.map(e => e.t))).sort((a, b) => a - b);
if (times.length === 0) times.push(0);

// Per-block ENTRY (x,y), bay index, and presence interval [entry, exit).
const placement = {};   // id -> {x, y, bay, entry, exit}
for (const ev of events) {
  const id = String(ev.block_id);
  if (!placement[id]) placement[id] = { x: 0, y: 0, bay: 0, entry: null, exit: null };
  if (ev.type === 'ENTRY') {
    placement[id].entry = ev.t;
    placement[id].x = (ev.x || 0);
    placement[id].y = (ev.y || 0);
  } else if (ev.type === 'EXIT') {
    placement[id].exit = ev.t;
  }
}
// Bay index comes from the block def (multi-bay) or defaults to 0 (single-bay).
for (const id of Object.keys(blocks)) {
  if (!placement[id]) placement[id] = { x: 0, y: 0, bay: 0, entry: null, exit: null };
  const bj = blocks[id].bay;
  placement[id].bay = (typeof bj === 'number' && bj >= 0 && bj < bayList.length) ? bj : 0;
}

// TARDY: exit time strictly greater than the block's due date.
const tardy = {};   // id -> bool
for (const id of Object.keys(blocks)) {
  const p = placement[id] || {};
  const due = blocks[id].due;
  tardy[id] = (p.exit !== null && p.exit !== undefined && due !== undefined && due !== null
               && p.exit > due);
}

function presentAt(id, t) {
  const p = placement[id];
  if (!p || p.entry === null) return false;
  if (t < p.entry) return false;
  if (p.exit !== null && t >= p.exit) return false;
  return true;
}

// Deterministic color per block id (HSL from a string hash). Slightly desaturated so
// the tardy crimson stands out against the on-time palette.
function colorFor(id) {
  const s = String(id);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  const sat = 42 + (h >> 8) % 20;        // 42-62% (desaturated)
  const lit = 50 + (h >> 16) % 12;       // 50-62%
  return new THREE.Color('hsl(' + hue + ',' + sat + '%,' + lit + '%)');
}

// Shoelace area of a (possibly concave) open polygon ring.
function polyArea(ring) {
  let a = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------
const wrap = document.getElementById('canvas-wrap');
const scene = new THREE.Scene();
scene.background = new THREE.Color('#0b0e14');

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio || 1);
wrap.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;

// The center of the whole layout, used as the orbit target / look-at for all views.
const cx = totalW / 2, cy = maxH / 2, cz = maxL / 2;
controls.target.set(cx, cy, cz);

// Lights (scaled to the whole multi-bay extent).
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const dir = new THREE.DirectionalLight(0xffffff, 0.9);
dir.position.set(totalW, maxH * 1.5, maxL * 6 + 8);
scene.add(dir);
const dir2 = new THREE.DirectionalLight(0x88aaff, 0.35);
dir2.position.set(-totalW, -maxH, maxL * 4);
scene.add(dir2);

// Text-sprite helper (used for axis labels and per-bay name labels).
function makeLabel(text, color, scale) {
  const px = Math.max(64, text.length * 36);
  const c = document.createElement('canvas');
  c.width = px; c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = color; ctx.font = 'bold 48px monospace';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, px / 2, 34);
  const tex = new THREE.CanvasTexture(c);
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  const sx = (scale || 2);
  spr.scale.set(sx * (px / 64), sx, 1);
  return spr;
}

// One wireframe box + floor grid + "bay <id>" label per bay, at its X-offset.
for (let j = 0; j < bayList.length; j++) {
  const b = bayList[j];
  const ox = bayOffset[j];
  const bw = b.width, bh = b.height, bl = b.max_layer;

  // Wireframe box (ox,0,0)..(ox+bw,bh,bl).
  const box = new THREE.BoxGeometry(bw, bh, bl);
  const edges = new THREE.EdgesGeometry(box);
  const line = new THREE.LineSegments(
    edges, new THREE.LineBasicMaterial({ color: 0x4a597a }));
  line.position.set(ox + bw / 2, bh / 2, bl / 2);
  scene.add(line);

  // Faint floor grid (z = 0) spanning this bay's footprint.
  const mat = new THREE.LineBasicMaterial({ color: 0x222d44 });
  const pts = [];
  for (let x = 0; x <= bw; x++) { pts.push(ox + x, 0, 0, ox + x, bh, 0); }
  for (let y = 0; y <= bh; y++) { pts.push(ox + 0, y, 0, ox + bw, y, 0); }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  scene.add(new THREE.LineSegments(geo, mat));

  // "bay <id>" label above the box.
  const lbl = makeLabel('bay ' + b.id, '#9fc0ff', Math.max(2.5, bw * 0.05));
  lbl.position.set(ox + bw / 2, bh + 2.5, bl + 1.5);
  scene.add(lbl);
}

// Axis labels x / y / z via sprite canvases, plus an origin axes helper.
{
  const ax = makeLabel('x', '#ff7b7b', Math.max(2, totalW * 0.02));
  ax.position.set(totalW + 1.5, 0, 0); scene.add(ax);
  const ay = makeLabel('y', '#7bff9d', Math.max(2, totalW * 0.02));
  ay.position.set(0, maxH + 1.5, 0); scene.add(ay);
  const az = makeLabel('z', '#7bb6ff', Math.max(2, totalW * 0.02));
  az.position.set(0, 0, maxL + 1.5); scene.add(az);
  const axesHelper = new THREE.AxesHelper(Math.max(totalW, maxH, maxL) * 0.3);
  scene.add(axesHelper);
}

// ---------------------------------------------------------------------------
// Block meshes (built once, toggled by visibility per time step).
// ---------------------------------------------------------------------------
const blockGroups = {};   // id -> THREE.Group

const TARDY_COLOR = new THREE.Color('#e2245a');   // crimson

function buildBlockMesh(id, def) {
  const group = new THREE.Group();
  const p = placement[id] || { x: 0, y: 0, bay: 0 };
  const ox = bayOffset[p.bay] || 0;          // bay x-offset -> world frame
  const isTardy = !!tardy[id];
  // user status palette: def.color (purple/red/yellow/blue/green); fall back to old
  const col = def && def.color ? new THREE.Color(def.color)
              : (isTardy ? TARDY_COLOR : colorFor(id));
  const highlight = def && (def.color === '#a64dff' || def.color === '#ff3b3b'
                            || def.color === '#ffd400');   // problem statuses pop
  const mat = new THREE.MeshStandardMaterial({
    color: col, transparent: true, opacity: highlight ? 0.85 : 0.6,
    roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide,
    emissive: highlight ? col.clone().multiplyScalar(0.4) : new THREE.Color('#000000'),
    emissiveIntensity: highlight ? 0.7 : 0.0,
  });
  const edgeMat = new THREE.LineBasicMaterial({
    color: isTardy ? new THREE.Color('#ff7da0') : col.clone().offsetHSL(0, 0, 0.15) });

  const layers = def.layers || [];
  for (let l = 0; l < layers.length; l++) {
    const ring = layers[l];
    if (!ring || ring.length < 3) continue;
    const shape = new THREE.Shape();
    shape.moveTo(ring[0][0], ring[0][1]);
    for (let i = 1; i < ring.length; i++) shape.lineTo(ring[i][0], ring[i][1]);
    shape.closePath();   // ExtrudeGeometry handles concave shapes via tessellation
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false });
    // Shape is in local XY; extrude grows along +Z. Layer l sits at z in [l, l+1].
    // World x = bay offset + local + ENTRY.x ; world y = local + ENTRY.y.
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(ox + p.x, p.y, l);
    group.add(mesh);
    const eg = new THREE.EdgesGeometry(geo);
    const el = new THREE.LineSegments(eg, edgeMat);
    el.position.copy(mesh.position);
    group.add(el);
  }
  // Block-id number label at the footprint centroid, floating just above the top layer.
  const ring0 = layers[0] || [];
  if (ring0.length) {
    let sx = 0, sy = 0;
    for (const v of ring0) { sx += v[0]; sy += v[1]; }
    sx /= ring0.length; sy /= ring0.length;
    const lbl = makeLabel(String(id), isTardy ? '#ffe1ea' : '#ffffff', 2.2);
    lbl.position.set(ox + p.x + sx, p.y + sy, layers.length + 0.35);
    lbl.renderOrder = 999;
    group.add(lbl);
  }
  group.userData.id = id;
  group.visible = false;
  return group;
}

for (const id of Object.keys(blocks)) {
  const grp = buildBlockMesh(id, blocks[id]);
  blockGroups[id] = grp;
  scene.add(grp);
}

// ---------------------------------------------------------------------------
// Time / animation state
// ---------------------------------------------------------------------------
let timeIdx = 0;
let playing = false;
let lastTick = 0;
const PLAY_INTERVAL_MS = 900;

function currentTime() { return times[timeIdx]; }

// Total tardy count is fixed (independent of time).
const TOTAL_TARDY = Object.keys(blocks).filter(id => tardy[id]).length;
// Sum of all bay floor areas (denominator for utilization across the layout).
const TOTAL_FLOOR = bayList.reduce((s, b) => s + b.width * b.height, 0);

function updateScene() {
  const t = currentTime();
  let count = 0;
  let tardyHere = 0;
  let usedArea = 0;
  for (const id of Object.keys(blockGroups)) {
    const here = presentAt(id, t);
    blockGroups[id].visible = here;
    if (here) {
      count++;
      if (tardy[id]) tardyHere++;
      const layers = (blocks[id].layers) || [];
      if (layers.length && layers[0] && layers[0].length >= 3) {
        usedArea += polyArea(layers[0]);
      }
    }
  }
  const util = TOTAL_FLOOR > 0 ? (100 * usedArea / TOTAL_FLOOR) : 0;

  document.getElementById('r-time').textContent = String(t);
  document.getElementById('r-count').textContent = String(count);
  document.getElementById('r-util').textContent = util.toFixed(1) + ' %';
  document.getElementById('r-tardy').textContent =
    String(tardyHere) + ' present  /  ' + String(TOTAL_TARDY) + ' total';
  document.getElementById('timeslider').value = String(timeIdx);

  // Event label: what happened exactly at this time.
  const here = events.filter(e => e.t === t);
  if (here.length) {
    document.getElementById('eventlabel').textContent =
      here.map(e => e.type + ' block ' + e.block_id +
        (e.type === 'ENTRY' ? ' @ (' + (e.x||0) + ',' + (e.y||0) + ')' : '')).join('   |   ');
  } else {
    document.getElementById('eventlabel').textContent = '';
  }
}

// ---------------------------------------------------------------------------
// View presets
// ---------------------------------------------------------------------------
function frameDistance() {
  return Math.max(totalW, maxH, maxL) * 1.2 + 8;
}
function setView(name) {
  const d = frameDistance();
  controls.target.set(cx, cy, cz);
  if (name === 'top') {            // look down -z (x-y plane)
    camera.position.set(cx, cy, cz + d);
    camera.up.set(0, 1, 0);
  } else if (name === 'front') {   // look along -y (x-z plane)
    camera.position.set(cx, cy - d, cz);
    camera.up.set(0, 0, 1);
  } else if (name === 'side') {    // look along -x (y-z plane)
    camera.position.set(cx - d, cy, cz);
    camera.up.set(0, 0, 1);
  } else {                          // iso 3/4
    camera.position.set(cx + d * 0.8, cy - d * 0.8, cz + d * 0.7);
    camera.up.set(0, 0, 1);
  }
  camera.lookAt(cx, cy, cz);
  controls.update();
  for (const b of ['top', 'front', 'side', 'iso'])
    document.getElementById('view-' + b).classList.toggle('active', b === name);
}

// ---------------------------------------------------------------------------
// UI wiring
// ---------------------------------------------------------------------------
const slider = document.getElementById('timeslider');
slider.max = String(times.length - 1);
slider.addEventListener('input', () => { timeIdx = parseInt(slider.value, 10) || 0; updateScene(); });

document.getElementById('btn-prev').addEventListener('click', () => {
  timeIdx = Math.max(0, timeIdx - 1); updateScene();
});
document.getElementById('btn-next').addEventListener('click', () => {
  timeIdx = Math.min(times.length - 1, timeIdx + 1); updateScene();
});
const playBtn = document.getElementById('btn-play');
playBtn.addEventListener('click', () => {
  playing = !playing;
  playBtn.textContent = playing ? 'Pause' : 'Play';
  playBtn.classList.toggle('active', playing);
  lastTick = performance.now();
});

document.getElementById('view-top').addEventListener('click', () => setView('top'));
document.getElementById('view-front').addEventListener('click', () => setView('front'));
document.getElementById('view-side').addEventListener('click', () => setView('side'));
document.getElementById('view-iso').addEventListener('click', () => setView('iso'));

// Title / bay info / legend / stats.
document.getElementById('title').textContent =
  'OGC2026 • ' + (TRACE.instance || 'instance');
document.getElementById('bayinfo').textContent =
  bayList.length + ' bay' + (bayList.length === 1 ? '' : 's') + '  —  ' +
  bayList.map(b => b.width + '×' + b.height + '×' + b.max_layer + 'L').join('   ');

{
  const leg = document.getElementById('legend');
  // status legend (user palette) with live counts
  const STAT = [
    ['#a64dff', '보라  tardy + wrong-bay'],
    ['#ff3b3b', '빨강  entry > due'],
    ['#ffd400', '노랑  tardy (exit > due)'],
    ['#3a7bd5', '파랑  wrong-bay (on-time)'],
    ['#36d17a', '초록  preferred & on-time'],
  ];
  const counts = {};
  for (const id of Object.keys(blocks)) {
    const c = (blocks[id].color || '#36d17a').toLowerCase();
    counts[c] = (counts[c] || 0) + 1;
  }
  for (const [hex, label] of STAT) {
    const item = document.createElement('div');
    item.className = 'legitem';
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = hex;
    const txt = document.createElement('span');
    txt.textContent = label + '   (' + (counts[hex.toLowerCase()] || 0) + ')';
    item.appendChild(sw); item.appendChild(txt);
    leg.appendChild(item);
  }
}
{
  const box = document.getElementById('statsbox');
  const stats = TRACE.stats || {};
  const keys = Object.keys(stats);
  if (!keys.length) {
    box.innerHTML = '<div class="muted">(no stats)</div>';
  } else {
    for (const k of keys) {
      const v = stats[k];
      const row = document.createElement('div');
      row.className = 'stat';
      const vs = (typeof v === 'object') ? JSON.stringify(v) : String(v);
      row.innerHTML = '<span class="k"></span><span class="v"></span>';
      row.children[0].textContent = k;
      row.children[1].textContent = vs;
      box.appendChild(row);
    }
  }
}

// ---------------------------------------------------------------------------
// Resize + render loop
// ---------------------------------------------------------------------------
function resize() {
  const w = wrap.clientWidth, h = wrap.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(1, h);
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function loop(now) {
  if (playing && now - lastTick >= PLAY_INTERVAL_MS) {
    lastTick = now;
    timeIdx = (timeIdx + 1) % times.length;
    updateScene();
  }
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
}

resize();
setView('iso');
updateScene();
requestAnimationFrame(loop);
</script>
</body>
</html>
"""


def write_viz(trace: dict, out_path: str) -> None:
    """Write a single self-contained HTML visualizer for `trace` to `out_path`.

    Pure standard library (json + string templating). The trace is embedded inline
    so the result works from file:// with no network fetch (other than the Three.js
    CDN, which is unavoidable for the renderer but loads from a pinned unpkg URL).
    """
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)

    # Embed safely: json.dumps then neutralize any "</" (e.g. inside string values)
    # so a stray "</script>" cannot break out of the <script> block.
    payload = json.dumps(trace, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")

    html = _HTML_TEMPLATE.replace("__TRACE_JSON__", payload)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def trace_from_solution(data: dict, solution: dict, instance_name: str = "") -> dict:
    """Build a MULTI-bay viz trace from an OGC2026 instance `data` and a `solution`.

    `data` keys (the official instance format):
      - "bays":   [ {"width", "height"}, ... ]
      - "blocks": [ {"shape": [ {"orientation", "layers": [ [[x,y],...], ... ]}, ... ],
                     "due_date", "release_time", "processing_time", ...}, ... ]
    `solution`:
      {"operations": { "<str_time>": [ op, ... ] }} where
        ENTRY op = {"type":"ENTRY","block_id","bay_id","x","y","orient_idx"}
        EXIT  op = {"type":"EXIT","block_id","bay_id"}
      (block_id is the index into data["blocks"]; str_time keys are wall-clock event times.)

    Layers in the trace are the RAW local polygon vertex lists `[[x,y], ...]` per layer
    (layer 0 first), taken straight from data["blocks"][bid]["shape"][orient]["layers"].
    A block's per-bay max_layer is derived from the placed blocks. Returns the multi-bay
    trace dict consumed by `write_viz`.
    """
    inst_blocks = data.get("blocks", [])
    inst_bays = data.get("bays", [])

    # Flatten operations into events; capture per-block ENTRY/EXIT info.
    ops = (solution or {}).get("operations", {}) or {}
    events = []
    entry_info = {}   # bid -> {bay, x, y, orient, t}
    exit_t = {}       # bid -> t
    for st in sorted(ops.keys(), key=lambda s: float(s)):
        t = float(st)
        if t == int(t):
            t = int(t)
        for op in ops[st]:
            bid = int(op["block_id"])
            if op.get("type") == "ENTRY":
                entry_info[bid] = {
                    "bay": int(op.get("bay_id", 0)),
                    "x": op.get("x", 0), "y": op.get("y", 0),
                    "orient": int(op.get("orient_idx", 0)), "t": t,
                }
                events.append({"t": t, "type": "ENTRY", "block_id": bid,
                               "x": op.get("x", 0), "y": op.get("y", 0)})
            elif op.get("type") == "EXIT":
                exit_t[bid] = t
                events.append({"t": t, "type": "EXIT", "block_id": bid})

    # Build block defs (only those that actually entered) with raw local layers.
    blocks = {}
    max_layer_per_bay = {}
    for bid, info in entry_info.items():
        if bid < 0 or bid >= len(inst_blocks):
            continue
        blk = inst_blocks[bid]
        orient = info["orient"]
        shapes = blk.get("shape", [])
        layers = []
        if 0 <= orient < len(shapes):
            layers = shapes[orient].get("layers", [])
        # Copy verts as plain [x, y] lists (raw local frame, NOT closed).
        layers_out = [[[v[0], v[1]] for v in ring] for ring in layers]
        # ---- status color (user rule) ----
        #  purple = tardy AND wrong-bay | red = entry_time > due | yellow = tardy
        #  (exit>due, entry on-time) | blue = wrong-bay (on-time) | green = ok
        due = blk.get("due_date")
        et = info["t"]
        xt = exit_t.get(bid)
        prefs = blk.get("bay_preferences") or []
        pref_bay = max(range(len(prefs)), key=lambda j: prefs[j]) if prefs else info["bay"]
        wrong = (info["bay"] != pref_bay)
        tardy_b = (xt is not None and due is not None and xt > due)
        entry_late = (due is not None and et is not None and et > due)
        if tardy_b and wrong:
            color = "#a64dff"          # purple
        elif entry_late:
            color = "#ff3b3b"          # red
        elif tardy_b:
            color = "#ffd400"          # yellow
        elif wrong:
            color = "#3a7bd5"          # blue
        else:
            color = "#36d17a"          # green
        blocks[str(bid)] = {
            "bay": info["bay"],
            "orient_idx": orient,
            "layers": layers_out,
            "release": blk.get("release_time"),
            "due": due,
            "proc": blk.get("processing_time"),
            "color": color,
            "pref_bay": pref_bay,
        }
        nb = info["bay"]
        max_layer_per_bay[nb] = max(max_layer_per_bay.get(nb, 0), len(layers_out))

    bays = []
    for j, b in enumerate(inst_bays):
        bays.append({
            "id": j,
            "width": b.get("width", 10),
            "height": b.get("height", 10),
            "max_layer": max(1, max_layer_per_bay.get(j, 1)),
        })

    n_tardy = sum(
        1 for bid, info in entry_info.items()
        if bid in exit_t and inst_blocks[bid].get("due_date") is not None
        and exit_t[bid] > inst_blocks[bid]["due_date"]
    )

    return {
        "instance": instance_name or data.get("name", "instance"),
        "bays": bays,
        "blocks": blocks,
        "events": events,
        "stats": {
            "n_bays": len(bays),
            "n_blocks_placed": len(blocks),
            "n_tardy": n_tardy,
            "weights": data.get("weights", {}),
        },
    }


def _demo_trace() -> dict:
    """Synthetic 2-bay trace: concave shapes across 2 bays, with one TARDY block.

    Bay 0 holds blocks 5 (L-shape) and 9 (C-shape, 2 layers). Bay 1 holds block 12
    (rectangle) and block 7 (rectangle) — block 7 EXITs (t=42) after its due (30) -> TARDY.
    """
    return {
        "instance": "demo_synthetic_2bay",
        "bays": [
            {"id": 0, "width": 20, "height": 14, "max_layer": 2},
            {"id": 1, "width": 16, "height": 12, "max_layer": 1},
        ],
        "blocks": {
            # --- bay 0 ---
            # Block 5: an L-shape (concave), single layer.
            "5": {
                "bay": 0, "orient_idx": 0,
                "layers": [
                    [[0, 0], [6, 0], [6, 2], [2, 2], [2, 5], [0, 5]],
                ],
                "release": 0, "due": 25, "proc": 8,
            },
            # Block 9: a C-shape (concave), two stacked layers (layer 1 smaller).
            "9": {
                "bay": 0, "orient_idx": 2,
                "layers": [
                    [[0, 0], [5, 0], [5, 1], [1, 1], [1, 4], [5, 4], [5, 5], [0, 5]],
                    [[0, 0], [3, 0], [3, 3], [0, 3]],
                ],
                "release": 4, "due": 30, "proc": 10,
            },
            # --- bay 1 ---
            # Block 12: a simple rectangle that arrives later (no EXIT -> stays).
            "12": {
                "bay": 1, "orient_idx": 1,
                "layers": [
                    [[-1, -1], [4, -1], [4, 3], [-1, 3]],
                ],
                "release": 10, "due": 40, "proc": 6,
            },
            # Block 7: rectangle in bay 1, EXIT (42) > due (30) -> TARDY (renders red).
            "7": {
                "bay": 1, "orient_idx": 0,
                "layers": [
                    [[0, 0], [7, 0], [7, 4], [0, 4]],
                ],
                "release": 2, "due": 30, "proc": 12,
            },
        },
        "events": [
            {"t": 0,  "type": "ENTRY", "block_id": 5,  "x": 1,  "y": 1},
            {"t": 2,  "type": "ENTRY", "block_id": 7,  "x": 6,  "y": 6},
            {"t": 5,  "type": "ENTRY", "block_id": 9,  "x": 9,  "y": 2},
            {"t": 12, "type": "ENTRY", "block_id": 12, "x": 4,  "y": 2},
            {"t": 20, "type": "EXIT",  "block_id": 5},
            {"t": 30, "type": "EXIT",  "block_id": 9},
            {"t": 42, "type": "EXIT",  "block_id": 7},   # > due 30 -> TARDY
            # block 12 has no EXIT -> present from t=12 onward
        ],
        "stats": {
            "instance": "demo_synthetic_2bay",
            "n_bays": 2,
            "n_blocks": 4,
            "n_tardy": 1,
            "note": "synthetic 2-bay trace with one tardy block for testing viz.py",
        },
    }


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "viz_demo.html")
    write_viz(_demo_trace(), out)
    print("wrote", out)
