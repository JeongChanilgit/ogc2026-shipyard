# -*- coding: utf-8 -*-
"""
Generator for the OGC2026 research-progress visual report.
Self-contained single-file HTML (inline CSS + inline SVG charts, minimal JS).
Data sourced 2026-06-13 from:
  - results/compare_baseline_20260601_2152/  (official greedy baseline @60s)
  - results/_z3_batch4_summary.txt           (our @600 best-of-2 + competitor)
  - notes/competitor-2026-06-11.json         (competitor full-20)
  - results/z1zero_2026-06-12_per_instance.csv (gate_rc z1/z2 proxy ~90s)
  - notes/submit-profile-promotion-2026-06-13.html (gate200_v2 vs legacy)
  - z1-vs-tl sweeps (tlsweep_p6_*, z1_loop_*, memory tl=1800)
"""
import os, math

OUT = os.path.join(os.path.dirname(__file__), "research-progress-2026-06-13.html")

INF = "INFEAS"

# ---------------------------------------------------------------- data
# Official greedy baseline @60s (T0). None obj => infeasible (scored -1).
baseline = {
 1:{"z1":190,"z2":239,"z3":10,"obj":5530963},
 2:{"z1":0,"z2":656,"z3":28,"obj":10760},
 3:{"z1":11,"z2":424,"z3":584,"obj":385177},
 4:{"z1":66,"z2":1186,"z3":620,"obj":1578890},
 5:{"z1":0,"z2":1786,"z3":754,"obj":125602},
 6:None,
 7:{"z1":68,"z2":2035,"z3":780,"obj":1340149},
 8:{"z1":0,"z2":2413,"z3":8,"obj":11252},
 9:{"z1":2553,"z2":1466,"z3":660,"obj":34145479},
 10:{"z1":62,"z2":3142,"z3":963,"obj":1051863},
 11:{"z1":1331,"z2":776,"z3":520,"obj":30497259},
 12:{"z1":1672,"z2":3926,"z3":760,"obj":36775458},
 13:{"z1":1770,"z2":2129,"z3":949,"obj":33067712},
 14:None,
 15:{"z1":2069,"z2":3845,"z3":307,"obj":30712291},
 16:{"z1":987,"z2":1691,"z3":977,"obj":8911839},
 17:None,
 18:{"z1":3511,"z2":3079,"z3":487,"obj":46889250},
 19:{"z1":2992,"z2":3269,"z3":678,"obj":32018914},
 20:None,
}

# Current: CLEAN full-20 re-baseline of the actual shipped submit_v2 pipeline
# @600 (results/_rebaseline600/, 2026-06-13). All of z1/z2/z3/obj from the SAME
# run -- supersedes the earlier stale base600 best-of-2 table.
current = {
 1:{"z1":0,"z2":157,"z3":2,"obj":1499},
 2:{"z1":0,"z2":144,"z3":15,"obj":3690},
 3:{"z1":0,"z2":1558,"z3":407,"obj":76630},
 4:{"z1":0,"z2":2173,"z3":154,"obj":46011},
 5:{"z1":0,"z2":1486,"z3":360,"obj":64402},
 6:{"z1":0,"z2":1610,"z3":591,"obj":99920},
 7:{"z1":0,"z2":2271,"z3":394,"obj":74997},
 8:{"z1":0,"z2":2413,"z3":8,"obj":11252},
 9:{"z1":0,"z2":1475,"z3":382,"obj":64675},
 10:{"z1":0,"z2":945,"z3":522,"obj":76041},
 11:{"z1":0,"z2":107,"z3":338,"obj":45703},
 12:{"z1":0,"z2":1768,"z3":770,"obj":114786},
 13:{"z1":0,"z2":1287,"z3":805,"obj":113500},
 14:{"z1":1,"z2":1204,"z3":505,"obj":90963},
 15:{"z1":0,"z2":4145,"z3":226,"obj":50783},
 16:{"z1":0,"z2":3127,"z3":205,"obj":42900},
 17:{"z1":0,"z2":6105,"z3":384,"obj":75492},
 18:{"z1":0,"z2":1152,"z3":704,"obj":98240},
 19:{"z1":0,"z2":3509,"z3":368,"obj":62980},
 20:{"z1":12,"z2":1829,"z3":783,"obj":428853},
}
# exact per-instance weights (from re-baseline run JSON) -> obj = w1*z1+w2*z2+w3*z3
WEIGHTS = {
 1:(29091,7,200),2:(29091,10,150),3:(26667,10,150),4:(21918,7,200),
 5:(16000,7,150),6:(29630,7,150),7:(17778,7,150),8:(10000,4,200),
 9:(13333,5,150),10:(14545,7,133),11:(22857,7,133),12:(21918,7,133),
 13:(18605,5,133),14:(17778,5,133),15:(14815,5,133),16:(8889,5,133),
 17:(9697,4,133),18:(13333,4,133),19:(10667,4,133),20:(26667,6,125),
}

# Competitor @600 (full-20). z1=0 everywhere. z2 is UNFLOORED (raw imbalance).
competitor = {
 1:{"obj":9785,"z3":8,"z2u":1398},
 2:{"obj":6624,"z3":0,"z2u":662},
 3:{"obj":50642,"z3":94,"z2u":3654},
 4:{"obj":16917,"z3":8,"z2u":2188},
 5:{"obj":70580,"z3":183,"z2u":6162},
 6:{"obj":72400,"z3":345,"z2u":2950},
 7:{"obj":86021,"z3":402,"z2u":3675},
 8:{"obj":12908,"z3":0,"z2u":3227},
 9:{"obj":80034,"z3":473,"z2u":1817},
 10:{"obj":98957,"z3":363,"z2u":7240},
 11:{"obj":31899,"z3":167,"z2u":1385},
 12:{"obj":94110,"z3":332,"z2u":7136},
 13:{"obj":76685,"z3":435,"z2u":3766},
 14:{"obj":67302,"z3":384,"z2u":3246},
 15:{"obj":48206,"z3":192,"z2u":4534},
 16:{"obj":50047,"z3":232,"z2u":3838},
 17:{"obj":62070,"z3":222,"z2u":8136},
 18:{"obj":40206,"z3":172,"z2u":4332},
 19:{"obj":72951,"z3":401,"z2u":4941},
 20:{"obj":91096,"z3":463,"z2u":5537},
}

# Research timeline: (date, label, total_obj or None, z1zero_count, lever)
timeline = [
 ("06-01","Greedy baseline",256000000,3,"EDD + Best-Fit greedy; 4 infeasible (−1 each)"),
 ("06-08","DUAL + slab pack",None,16,"polygon slab packing + wide cum_level"),
 ("06-10","Front B reassign",2225579,15,"bay reassignment gate-fix unlocked"),
 ("06-12","gate_rc cap+repair",1621719,17,"assign-cap 0.85 + z1-repair loop"),
 ("06-13","gate200_v2  (SHIPPED)",1550000,19,"FastFloor primary + BAN-RACE"),
]
COMP_TOTAL=1139440  # competitor @600 reference

# z1 vs solver time-limit, hard instances. (tl_seconds, z1)
z1_curves = {
 6: [(120,889),(300,76),(600,4)],
 11:[(60,268),(120,1),(600,0)],
 13:[(60,983),(120,10),(600,7),(1800,1)],
 14:[(60,1804),(120,61),(300,3),(600,0)],
 18:[(60,1782),(120,0)],
 20:[(60,1020),(120,507),(300,10),(600,9),(1800,2)],
}

PROBS=list(range(1,21))
WINS={1,2,5,7,8,9,10,16,19}  # true @600 re-baseline (9/20), was stale 6/20

# ---------------------------------------------------------------- helpers
def fmt(n):
    if n is None: return "—"
    if isinstance(n,float) and n!=int(n): return f"{n:,.0f}"
    return f"{int(round(n)):,}"

def pct(base,cur):
    if base in (None,0): return None
    return (cur-base)/base*100.0

C = {  # palette
 "bg":"#070b16","panel":"#0f1626","panel2":"#131c30","line":"#1e2c44",
 "txt":"#e6edf7","mut":"#8aa0c0","mut2":"#5f7characters",  # placeholder fixed below
}
C["mut2"]="#5f7395"
ACC={"z1":"#38bdf8","z2":"#fbbf24","z3":"#c084fc","obj":"#34d399",
     "base":"#fb7185","cur":"#34d399","comp":"#a78bfa","inf":"#64748b"}

# ---------------------------------------------------------------- SVG: grouped bars
def grouped_bar(metric, key, scale="log", show_comp=False, comp_key="z3", unit=""):
    """One metric across 20 problems: baseline vs current (+ optional competitor tick)."""
    W,H = 1180,330
    ml,mr,mt,mb = 46,14,30,46
    pw = W-ml-mr; ph = H-mt-mb
    gw = pw/20.0
    # collect values
    vals=[]
    for p in PROBS:
        b = None if baseline[p] is None else baseline[p][key]
        c = current[p][key]
        cm = competitor[p].get(comp_key) if show_comp else None
        vals += [v for v in (b,c,cm) if v is not None]
    vmax=max(vals) if vals else 1
    def Y(v):
        if v is None: return None
        if scale=="log":
            return ph*(math.log10(v+1)/math.log10(vmax+1))
        return ph*(v/vmax)
    s=[f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    # gridlines
    if scale=="log":
        ticks=[t for t in [1,10,100,1000,10000,100000,1000000,10000000] if t<=vmax]
    else:
        ticks=[vmax*f for f in (0,.25,.5,.75,1)]
    for t in ticks:
        y=mt+ph-Y(t)
        s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" stroke="{C["line"]}" stroke-width="1"/>')
        s.append(f'<text x="{ml-6}" y="{y+3:.1f}" text-anchor="end" class="ax">{fmt(t)}</text>')
    for i,p in enumerate(PROBS):
        gx=ml+i*gw
        b = None if baseline[p] is None else baseline[p][key]
        c = current[p][key]
        bw=gw*0.30
        x_b=gx+gw*0.16; x_c=gx+gw*0.52
        # baseline bar (or infeasible hatch)
        if baseline[p] is None:
            s.append(f'<rect x="{x_b:.1f}" y="{mt}" width="{bw:.1f}" height="{ph}" fill="url(#hatch)" stroke="{ACC["inf"]}" stroke-width="1"><title>prob_{p} baseline: INFEASIBLE (−1)</title></rect>')
        else:
            hb=Y(b);
            s.append(f'<rect x="{x_b:.1f}" y="{mt+ph-hb:.1f}" width="{bw:.1f}" height="{max(hb,0.6):.1f}" rx="1.5" fill="{ACC["base"]}" opacity="0.85"><title>prob_{p} baseline {metric}: {fmt(b)}</title></rect>')
        # current bar
        hc=Y(c)
        s.append(f'<rect x="{x_c:.1f}" y="{mt+ph-hc:.1f}" width="{bw:.1f}" height="{max(hc,0.6):.1f}" rx="1.5" fill="{ACC["cur"]}"><title>prob_{p} current {metric}: {fmt(c)}</title></rect>')
        # competitor tick
        if show_comp:
            cm=competitor[p].get(comp_key)
            if cm is not None:
                ycm=mt+ph-Y(cm)
                s.append(f'<line x1="{x_b-1:.1f}" y1="{ycm:.1f}" x2="{x_c+bw+1:.1f}" y2="{ycm:.1f}" stroke="{ACC["comp"]}" stroke-width="2.2" stroke-dasharray="3,2"><title>prob_{p} competitor {comp_key}: {fmt(cm)}</title></line>')
        # residual label for current z1>0
        if key=="z1" and c>0:
            s.append(f'<text x="{x_c+bw/2:.1f}" y="{mt+ph-hc-4:.1f}" text-anchor="middle" class="res">{c}</text>')
        # x label
        s.append(f'<text x="{gx+gw/2:.1f}" y="{H-mb+16}" text-anchor="middle" class="xl {"win" if p in WINS else ""}">{p}</text>')
    s.append('</svg>')
    return "".join(s)

# ---------------------------------------------------------------- SVG: timeline
def timeline_svg():
    W,H=1180,300; ml,mr,mt,mb=58,58,28,52
    pw=W-ml-mr; ph=H-mt-mb
    n=len(timeline)
    xs=[ml+pw*i/(n-1) for i in range(n)]
    objs=[t[2] for t in timeline]
    omax=max(o for o in objs if o); omin=COMP_TOTAL*0.8
    def Yo(v):
        return mt+ph-ph*(math.log10(v)-math.log10(omin))/(math.log10(omax)-math.log10(omin))
    zmax=20
    def Yz(v): return mt+ph-ph*(v/zmax)
    s=[f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    # obj gridlines
    for t in [1000000,3000000,10000000,30000000,100000000,256000000]:
        if omin<=t<=omax:
            y=Yo(t); s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" stroke="{C["line"]}"/>')
            s.append(f'<text x="{ml-6}" y="{y+3:.1f}" text-anchor="end" class="ax">{fmt(t)}</text>')
    # competitor reference
    yc=Yo(COMP_TOTAL)
    s.append(f'<line x1="{ml}" y1="{yc:.1f}" x2="{W-mr}" y2="{yc:.1f}" stroke="{ACC["comp"]}" stroke-width="1.5" stroke-dasharray="5,4"/>')
    s.append(f'<text x="{W-mr}" y="{yc-6:.1f}" text-anchor="end" class="cmpl">competitor total {fmt(COMP_TOTAL)}</text>')
    # obj line (skip None)
    pts=[(xs[i],Yo(objs[i])) for i in range(n) if objs[i]]
    s.append('<polyline points="'+" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)+f'" fill="none" stroke="{ACC["obj"]}" stroke-width="3"/>')
    # z1zero line (right axis)
    zpts=[(xs[i],Yz(timeline[i][3])) for i in range(n)]
    s.append('<polyline points="'+" ".join(f"{x:.1f},{y:.1f}" for x,y in zpts)+f'" fill="none" stroke="{ACC["z1"]}" stroke-width="2.4" stroke-dasharray="2,3"/>')
    for i in range(n):
        # z1 axis right
        pass
    # right axis labels z1zero
    for zc in (0,5,10,15,20):
        y=Yz(zc); s.append(f'<text x="{W-mr+8}" y="{y+3:.1f}" text-anchor="start" class="ax z1c">{zc}</text>')
    # markers + date labels
    for i,(d,lab,o,z,lev) in enumerate(timeline):
        if o:
            s.append(f'<circle cx="{xs[i]:.1f}" cy="{Yo(o):.1f}" r="5" fill="{ACC["obj"]}" stroke="{C["bg"]}" stroke-width="1.5"><title>{d} {lab}: total obj {fmt(o)}</title></circle>')
            s.append(f'<text x="{xs[i]:.1f}" y="{Yo(o)-11:.1f}" text-anchor="middle" class="onl">{fmt(o)}</text>')
        s.append(f'<circle cx="{xs[i]:.1f}" cy="{Yz(z):.1f}" r="4" fill="{ACC["z1"]}"><title>{d}: z1=0 on {z}/20</title></circle>')
        s.append(f'<text x="{xs[i]:.1f}" y="{Yz(z)+(16 if i==0 else -10):.1f}" text-anchor="middle" class="z1l">{z}/20</text>')
        s.append(f'<text x="{xs[i]:.1f}" y="{H-mb+18}" text-anchor="middle" class="dl">{d}</text>')
        s.append(f'<text x="{xs[i]:.1f}" y="{H-mb+33}" text-anchor="middle" class="dl2">{lab}</text>')
    s.append('</svg>')
    return "".join(s)

# ---------------------------------------------------------------- SVG: z1 vs tl
def z1_tl_svg():
    W,H=1180,360; ml,mr,mt,mb=52,120,24,46
    pw=W-ml-mr; ph=H-mt-mb
    allt=sorted({t for c in z1_curves.values() for t,_ in c})
    tmin,tmax=60,1800
    def X(t): return ml+pw*(math.log10(t)-math.log10(tmin))/(math.log10(tmax)-math.log10(tmin))
    zmax=2000
    def Y(z): return mt+ph-ph*(math.log10(z+1)/math.log10(zmax+1))
    cols=["#38bdf8","#34d399","#fbbf24","#fb7185","#c084fc","#f472b6"]
    s=[f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">']
    for z in [0,1,10,100,1000,2000]:
        y=Y(z); s.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" stroke="{C["line"]}"/>')
        s.append(f'<text x="{ml-6}" y="{y+3:.1f}" text-anchor="end" class="ax">{z}</text>')
    for t in [60,120,300,600,1800]:
        x=X(t); s.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{mt+ph}" stroke="{C["line"]}" stroke-dasharray="2,4"/>')
        s.append(f'<text x="{x:.1f}" y="{H-mb+18}" text-anchor="middle" class="ax">{t}s</text>')
    for i,(p,curve) in enumerate(sorted(z1_curves.items())):
        col=cols[i%len(cols)]
        pts=[(X(t),Y(z)) for t,z in curve]
        s.append('<polyline points="'+" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)+f'" fill="none" stroke="{col}" stroke-width="2.4"/>')
        for (t,z),(x,y) in zip(curve,pts):
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{col}"><title>prob_{p} @{t}s: z1={z}</title></circle>')
        lx,ly=pts[-1]
        s.append(f'<text x="{lx+8:.1f}" y="{ly+3:.1f}" class="leg" fill="{col}">prob_{p}</text>')
    s.append('</svg>')
    return "".join(s)

# ---------------------------------------------------------------- per-problem table
def table_rows():
    rows=[]
    for p in PROBS:
        b=baseline[p]; c=current[p]; cm=competitor[p]
        verdict = "WIN" if p in WINS else "LOSE"
        ratio = c["obj"]/cm["obj"]
        binfo = "INFEAS" if b is None else fmt(b["obj"])
        bz1 = "—" if b is None else fmt(b["z1"])
        gap = c["obj"]-cm["obj"]
        rows.append(f'''<tr class="{ 'win' if p in WINS else 'lose'}">
          <td class="pid">prob_{p}</td>
          <td class="num bcol">{binfo}</td>
          <td class="num">{fmt(c['obj'])}</td>
          <td class="num comp">{fmt(cm['obj'])}</td>
          <td class="num {'gpos' if gap>0 else 'gneg'}">{('+' if gap>0 else '')}{fmt(gap)}</td>
          <td class="num">{ratio:.2f}×</td>
          <td class="num">{bz1}→{fmt(c['z1'])}</td>
          <td class="num">{fmt(c['z2'])}</td>
          <td class="num z3c">{fmt(c['z3'])} <span class="vs">/ {fmt(cm['z3'])}</span></td>
          <td><span class="badge {verdict.lower()}">{verdict}</span></td>
        </tr>''')
    return "\n".join(rows)

# ---------------------------------------------------------------- pipeline stages
# (n, title, file:line, target, flag, default, budget)
stages=[
 ("0","SUBMIT_V2 inject 16 knobs","myalgorithm.py:5280","struct","OGC_SUBMIT_V2","ON","T≥60 setdefault"),
 ("1","Trivial serialized floor","myalgorithm.py:5518","feas","always","ON","instant · −1 guard"),
 ("2","FastFloor (crane-aware init)","fastfloor.py","z1","OGC_FASTFLOOR","ON*","~30s / 0.20·T"),
 ("2b","FF-PRIMARY swap","myalgorithm.py:5846","z1","OGC_FF_PRIMARY","ON*","replaces greedy floor"),
 ("3","Greedy / raster floor","myalgorithm.py:5857","z1","adaptive","ON","≤ base budget"),
 ("3b","Verify + base-swap","myalgorithm.py:5881","feas","always","ON","check_feasibility"),
]
pp_stages=[
 ("4.1","cum_level redecode","myalgorithm.py:4340","z1","OGC_CUMLEVEL","ON · 30%"),
 ("4.2","CP-SAT timing (entry/exit)","myalgorithm.py:4348","z1","OGC_CPSAT_TIMING","ON"),
 ("4.3","bbox-pack (+slab dual)","myalgorithm.py:4408","z1","OGC_BBOX_PACK","ON"),
 ("4.4","crossbay relocate","myalgorithm.py:4449","z1z2","OGC_CROSSBAY_RELOCATE","ON · 30s"),
 ("4.6","tardy-reloc + moves","myalgorithm.py:4562","z1z3","OGC_TARDY_RELOC","ON"),
 ("4.7","Front B (assign reopt)","myalgorithm.py:5051","z3","OGC_FRONTB","ON ← live z3 lever"),
 ("4.8","z1-repair + assign-cap","myalgorithm.py:4622","z1","OGC_FF_ASSIGN_CAP","cap 0.85"),
]
race_stages=[
 ("5b","T1 raster race","myalgorithm.py:6228","z1","OGC_LONGTL_RACE","ON · T≥300 · ≤105s"),
 ("5","BAN-RACE (dual-path)","myalgorithm.py:6375","z1","OGC_BAN_RACE","ON* · ROUNDS=2 · 90s"),
 ("6","z3-RACE (temporal reassign)","z3race.py:97","z3","OGC_Z3_RACE","OFF ← KEY LEVER"),
 ("7","ALNS search","myalgorithm.py:6808","z1z2z3","OGC_ALNS_OVER_BASELINE","ON"),
 ("8","Final gate (rank+verify)","myalgorithm.py:7166","feas","OGC_GATE_POSTPROCESS","ON"),
 ("9","Floor return / −1 guard","myalgorithm.py:7262","feas","always","ON · never −1"),
]
TGT={"z1":("Z1 tardiness",ACC["z1"]),"z2":("Z2 imbalance",ACC["z2"]),
     "z3":("Z3 preference",ACC["z3"]),"z1z2":("Z1+Z2",ACC["z1"]),
     "z1z3":("Z1+Z3",ACC["z1"]),"z1z2z3":("all",ACC["obj"]),
     "feas":("feasibility",C["mut2"]),"struct":("structure",C["mut2"])}

def stage_box(st,big=False):
    n,title,loc,tgt,flag,dflt=st[0],st[1],st[2],st[3],st[4],st[5]
    bud=st[6] if len(st)>6 else ""
    lab,col=TGT[tgt]
    off = "off" if "OFF" in dflt else ""
    key = "key" if ("KEY" in dflt or "live z3" in dflt) else ""
    return f'''<div class="stage {off} {key}" style="--tc:{col}">
      <div class="st-top"><span class="st-n">{n}</span><span class="st-title">{title}</span></div>
      <div class="st-meta"><span class="st-tgt" style="color:{col}">●&nbsp;{lab}</span><span class="st-loc">{loc}</span></div>
      <div class="st-flag"><code>{flag}</code><span class="st-d">{dflt}</span></div>
      {f'<div class="st-bud">{bud}</div>' if bud else ''}
    </div>'''

# ---------------------------------------------------------------- assemble
def kpi(v,l,sub,col): return f'<div class="kpi"><div class="kv" style="color:{col}">{v}</div><div class="kl">{l}</div><div class="ks">{sub}</div></div>'

base_total=sum(b["obj"] for b in baseline.values() if b)
cur_total=sum(c["obj"] for c in current.values())

html=f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OGC2026 · 연구 진행 시각화 · 2026-06-13</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:{C['bg']};--pan:{C['panel']};--pan2:{C['panel2']};--line:{C['line']};--txt:{C['txt']};--mut:{C['mut']};--mut2:{C['mut2']}}}
body{{background:var(--bg);color:var(--txt);font-family:'Segoe UI',-apple-system,system-ui,sans-serif;line-height:1.5;
 background-image:radial-gradient(1200px 600px at 80% -10%,rgba(56,189,248,.07),transparent),radial-gradient(900px 500px at -10% 20%,rgba(192,132,252,.06),transparent)}}
.wrap{{max-width:1240px;margin:0 auto;padding:34px 26px 90px}}
code{{font-family:'JetBrains Mono','Consolas',monospace}}
.num,.kv,.ax,.mono{{font-variant-numeric:tabular-nums;font-family:'JetBrains Mono','Consolas',monospace}}
h1{{font-size:27px;font-weight:800;letter-spacing:-.5px}}
.sub{{color:var(--mut);font-size:14px;margin-top:6px}}
.tag{{display:inline-block;font-size:11px;color:#7dd3fc;border:1px solid #1e3a52;background:#0c1c2c;padding:2px 9px;border-radius:20px;margin-right:6px;font-weight:600}}
nav{{position:sticky;top:0;z-index:20;background:rgba(7,11,22,.82);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);
 display:flex;gap:4px;flex-wrap:wrap;padding:10px 26px;margin:0 -26px 26px}}
nav a{{color:var(--mut);text-decoration:none;font-size:12.5px;font-weight:600;padding:5px 11px;border-radius:7px}}
nav a:hover{{color:var(--txt);background:var(--pan2)}}
section{{margin:40px 0}}
h2{{font-size:19px;font-weight:700;margin-bottom:4px;display:flex;align-items:center;gap:9px}}
h2 .dot{{width:9px;height:9px;border-radius:50%}}
.h2sub{{color:var(--mut);font-size:13px;margin-bottom:18px}}
.card{{background:linear-gradient(180deg,var(--pan),var(--bg));border:1px solid var(--line);border-radius:14px;padding:20px 22px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}}
.kpi{{background:var(--pan);border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
.kv{{font-size:26px;font-weight:800;letter-spacing:-.5px}}
.kl{{font-size:13px;margin-top:3px;font-weight:600}}
.ks{{font-size:11.5px;color:var(--mut2);margin-top:3px}}
.chart{{width:100%;height:auto;display:block;margin-top:6px}}
.ax{{fill:var(--mut2);font-size:10.5px}} .z1c{{fill:{ACC['z1']}}}
.xl{{fill:var(--mut);font-size:11px}} .xl.win{{fill:{ACC['cur']};font-weight:700}}
.res{{fill:{ACC['z1']};font-size:9.5px;font-weight:700}}
.dl{{fill:var(--txt);font-size:11.5px;font-weight:700}} .dl2{{fill:var(--mut);font-size:10px}}
.onl{{fill:{ACC['obj']};font-size:10.5px;font-weight:700;font-family:monospace}}
.z1l{{fill:{ACC['z1']};font-size:10px;font-weight:700;font-family:monospace}}
.cmpl{{fill:{ACC['comp']};font-size:11px;font-weight:600}} .leg{{font-size:11px;font-weight:700}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:8px;align-items:center}}
.sw{{display:inline-block;width:14px;height:10px;border-radius:2px;vertical-align:middle;margin-right:5px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:4px}}
th{{text-align:right;color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px;padding:8px 9px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
td{{padding:7px 9px;border-bottom:1px solid rgba(30,44,68,.5)}}
td.num{{text-align:right}} .pid{{font-weight:700;font-family:monospace}}
.bcol{{color:var(--mut2)}} .comp{{color:{ACC['comp']}}} .z3c{{color:{ACC['z3']};font-weight:600}}
.vs{{color:var(--mut2);font-weight:400}}
.gpos{{color:{ACC['base']}}} .gneg{{color:{ACC['cur']}}}
tr.win{{background:rgba(52,211,153,.05)}}
.badge{{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:5px}}
.badge.win{{background:rgba(52,211,153,.16);color:{ACC['cur']}}} .badge.lose{{background:rgba(251,113,133,.13);color:{ACC['base']}}}
.flow{{display:flex;flex-direction:column;gap:8px}}
.flrow{{display:flex;gap:8px;flex-wrap:wrap;align-items:stretch}}
.stage{{flex:1;min-width:150px;background:var(--pan2);border:1px solid var(--line);border-left:3px solid var(--tc);border-radius:9px;padding:9px 11px;position:relative}}
.stage.off{{opacity:.55;border-left-style:dashed}}
.stage.key{{box-shadow:0 0 0 1px var(--tc),0 0 18px -4px var(--tc)}}
.st-top{{display:flex;gap:7px;align-items:baseline}}
.st-n{{font-family:monospace;font-size:11px;color:var(--mut2);font-weight:700}}
.st-title{{font-size:13px;font-weight:700}}
.st-meta{{display:flex;justify-content:space-between;gap:6px;margin-top:3px;font-size:10.5px}}
.st-tgt{{font-weight:600}} .st-loc{{color:var(--mut2);font-family:monospace}}
.st-flag{{margin-top:5px;font-size:10.5px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.st-flag code{{color:#9ec5ff;font-size:10px}} .st-d{{color:var(--mut)}}
.st-bud{{font-size:10px;color:var(--mut2);margin-top:3px}}
.phase-h{{font-size:11.5px;font-weight:700;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;margin:14px 0 4px;display:flex;align-items:center;gap:8px}}
.phase-h::before{{content:"";flex:0 0 18px;height:1px;background:var(--line)}}
.arrow{{text-align:center;color:var(--mut2);font-size:15px;line-height:1}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:880px){{.grid2{{grid-template-columns:1fr}}}}
.lever{{background:var(--pan);border:1px solid var(--line);border-radius:12px;padding:16px 18px;border-top:3px solid var(--lc)}}
.lever h3{{font-size:15px;display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.lever .rank{{font-family:monospace;background:var(--lc);color:#06121f;font-weight:800;font-size:12px;padding:1px 8px;border-radius:6px}}
.lever p{{font-size:13px;color:var(--mut);margin-bottom:7px}}
.lever .ev{{font-size:11.5px;color:var(--mut2);border-top:1px solid var(--line);padding-top:8px;margin-top:4px}}
.lever b{{color:var(--txt)}}
.note{{font-size:11.5px;color:var(--mut2);background:var(--pan);border:1px solid var(--line);border-radius:9px;padding:11px 14px;margin-top:14px}}
.note b{{color:var(--mut)}}
ul.tl{{list-style:none;margin-top:8px}} ul.tl li{{padding:6px 0;border-bottom:1px solid rgba(30,44,68,.5);font-size:12.5px;display:flex;gap:10px}}
ul.tl .d{{color:{ACC['z1']};font-family:monospace;font-weight:700;flex:0 0 52px}}
ul.tl .l{{color:var(--mut)}}
.hl{{color:{ACC['obj']};font-weight:700}}
.hr{{color:{ACC['base']};font-weight:700}}
</style></head><body><div class="wrap">

<header>
  <div><span class="tag">OGC 2026</span><span class="tag">조선소 블록 패킹</span><span class="tag">2026-06-13</span></div>
  <h1 style="margin-top:12px">연구 진행 시각화 — Z1·Z2·Z3·Total Objective</h1>
  <p class="sub">베이스라인(06-01) → 현재(gate200_v2, 06-13)까지 20개 인스턴스의 목적함수 성분이 시간·연구에 따라 어떻게 줄었는가 · 솔버 시퀀스 · 향후 돌파 방향</p>
</header>

<nav>
  <a href="#kpi">현황</a><a href="#time">연구 타임라인</a><a href="#metrics">성분별 20문제</a>
  <a href="#z1tl">Z1 vs 시간</a><a href="#table">전체 표</a><a href="#seq">솔버 시퀀스</a><a href="#break">돌파 방향</a>
</nav>

<section id="kpi">
  <h2><span class="dot" style="background:{ACC['obj']}"></span>현재 상태 한눈에</h2>
  <p class="h2sub">gate200_v2 = 실제 제출 기본값 (2026-06-13 승격). 괄호는 베이스라인 대비.</p>
  <div class="kpis">
    {kpi("19/20","Z1 = 0 달성","베이스라인 3/20 → 현재 19/20",ACC['z1'])}
    {kpi("20/20","Feasible","베이스라인 16/20 (4개 −1) → 전부 실현가능",ACC['cur'])}
    {kpi("−42%","총 obj 감소","legacy 2.68M → 1.55M (제출경로 @200s)",ACC['obj'])}
    {kpi("~165×","베이스라인 대비","256M → 1.55M (실현가능분 기준)",ACC['z2'])}
    {kpi("9/20","경쟁자 상대 승","full-20 @600 재측정 확정 (구 리포트 6/20=stale)",ACC['comp'])}
    {kpi("prob_20","단일 최대 갭","+337,757 = 전체 갭의 64% (z1=12 페널티)",ACC['base'])}
  </div>
</section>

<section id="time">
  <h2><span class="dot" style="background:{ACC['obj']}"></span>연구 타임라인 — 총 목적함수 · Z1=0 달성 수</h2>
  <p class="h2sub">왼쪽축=총 obj(로그, <span style="color:{ACC['obj']}">●선</span>) · 오른쪽축=z1=0 인스턴스 수(<span style="color:{ACC['z1']}">┄선</span>) · <span style="color:{ACC['comp']}">┄</span>=경쟁자 총 obj. 12일 만에 ~165× 축소.</p>
  <div class="card">{timeline_svg()}</div>
  <ul class="tl">
    {''.join(f'<li><span class="d">{d}</span><span><b>{lab}</b> <span class="l">— {lev}</span></span></li>' for d,lab,o,z,lev in timeline)}
  </ul>
</section>

<section id="metrics">
  <h2><span class="dot" style="background:{ACC['z1']}"></span>성분별 · 모든 문제 (baseline → current)</h2>
  <p class="h2sub"><span class="sw" style="background:{ACC['base']}"></span>베이스라인 @60s &nbsp; <span class="sw" style="background:{ACC['cur']}"></span>현재 @600 &nbsp; <span style="border-top:2.5px dashed {ACC['comp']};display:inline-block;width:16px;vertical-align:middle"></span> 경쟁자 &nbsp;·&nbsp; x축 숫자 초록=경쟁자 상대 승. 빗금=실현불가(−1).</p>

  <div class="card" style="margin-bottom:16px">
    <h2 style="font-size:15px"><span class="dot" style="background:{ACC['z1']}"></span>Z1 — 총 지연 (tardiness) · 로그축</h2>
    <p class="h2sub">베이스라인은 수백~수천. 현재는 18/20이 0 (@600 잔여: prob_14=1, prob_20=12). 가장 큰 가중치(w1=10K~30K) 성분 → <span class="hl">사실상 해결, 단 prob_20이 핵심 예외</span>.</p>
    {grouped_bar("Z1","z1","log")}
  </div>

  <div class="card" style="margin-bottom:16px">
    <h2 style="font-size:15px"><span class="dot" style="background:{ACC['z3']}"></span>Z3 — 선호도 편차 (preference) · 선형축 · <span class="hr">남은 병목</span></h2>
    <p class="h2sub">w3=125~200으로 z1=0일 때 obj를 지배. 경쟁자(┄) 대비 우리(초록)가 대부분 1.5~4× 높음 = 11개 손실 중 9개의 원인. 최대 갭 prob_18(704 vs 172)·prob_12(770 vs 332)·prob_13(805 vs 435).</p>
    {grouped_bar("Z3","z3","linear",show_comp=True,comp_key="z3")}
  </div>

  <div class="grid2">
    <div class="card">
      <h2 style="font-size:15px"><span class="dot" style="background:{ACC['obj']}"></span>Total Obj · 로그축</h2>
      <p class="h2sub">현재(초록) vs 경쟁자(┄). 우리 <b>9/20 승</b>(@600 재측정). prob_20이 로그축 최상단=단일 최대 갭.</p>
      {grouped_bar("obj","obj","log",show_comp=True,comp_key="obj")}
    </div>
    <div class="card">
      <h2 style="font-size:15px"><span class="dot" style="background:{ACC['z2']}"></span>Z2 — 작업부하 불균형 · 선형축</h2>
      <p class="h2sub">w2≈5로 가중치 작음 → z1=0·z3 확보 위해 <b>의도적으로 양보</b>하는 성분. 단조 감소 아님(파레토 거래).</p>
      {grouped_bar("Z2","z2","linear")}
    </div>
  </div>
  <div class="note"><b>가중치 구조가 전략을 결정한다.</b> obj = w1·Z1 + w2·Z2 + w3·Z3 에서 w1(지연)은 수천 단위로 압도적 → Z1=0이 1순위(달성). z1=0이면 남는 건 w3≈133·Z3 vs w2≈5·Z2 인데, Z3 항이 Z2 항의 수~수십 배 → <b>Z3가 obj의 숨은 지배자</b>. 예: prob_13 obj 113,500 중 z3 기여 ≈94%(805×133), prob_4 obj 46,011 중 z3 ≈67%(154×200). z1=0 손실은 전부 Z3 게임. <b>유일 예외=prob_20</b>(z1=12 페널티가 obj의 75%).</div>
</section>

<section id="z1tl">
  <h2><span class="dot" style="background:{ACC['z1']}"></span>Z1 vs 솔버 시간제한 — 막혔던 문제들</h2>
  <p class="h2sub">양축 로그. 시간(+연구)이 늘면 z1이 붕괴. prob_13: 983→1, prob_20: 1020→2 (60s→1800s). 평가서버는 인스턴스당 최대 30분 → z1=0 여력 충분. <span class="note" style="display:inline;padding:2px 6px">tl=1800 값은 메모리 기록(2026-06-08), 그 외는 측정 파일.</span></p>
  <div class="card">{z1_tl_svg()}</div>
</section>

<section id="table">
  <h2><span class="dot" style="background:{ACC['comp']}"></span>전체 인스턴스 표 — baseline · current · competitor</h2>
  <p class="h2sub">헤더 클릭 = 정렬. Δobj 양수(빨강)=경쟁자에 뒤짐. z3 열 = 우리 / 경쟁자.</p>
  <div class="card" style="overflow-x:auto">
  <table id="tbl">
    <thead><tr>
      <th data-k="0" data-t="s">인스턴스</th><th data-k="1">baseline obj</th><th data-k="2">current obj</th>
      <th data-k="3">competitor</th><th data-k="4">Δ obj</th><th data-k="5">비율</th>
      <th data-k="6" data-t="s">Z1 (b→c)</th><th data-k="7">Z2</th><th data-k="8">Z3 우/경</th><th data-k="9" data-t="s">판정</th>
    </tr></thead>
    <tbody>{table_rows()}</tbody>
  </table>
  </div>
  <div class="note"><b>측정 컨텍스트 (2026-06-13 재측정).</b> baseline=공식 greedy @60s · current=실제 제출 파이프라인(submit_v2 default) <b>full-20 @600 단일런</b>의 z1/z2/z3/obj 전부(`results/_rebaseline600/`) — 더 이상 혼합 근사 아님 · competitor=2026-06-11 스크린샷 @600. <b>총합 ours 1,643,317 vs comp 1,139,440, 9승 11패.</b> 직전 리포트의 base600 수치는 submit_v2 이전 약한 config라 prob_16/7 등을 패배로 오기했음(stale). prob_20 z1·obj는 변동 큼(@200 z1≈6, @600 z1≈12) — 돌파 섹션 참조.</div>
</section>

<section id="seq">
  <h2><span class="dot" style="background:{ACC['cur']}"></span>솔버 시퀀스 — Floor-and-Improve 파이프라인</h2>
  <p class="h2sub">핵심 원리: 항상 <b>검증된 feasible "floor"</b>를 들고, 그것을 <b>엄밀히 이기는</b> 해만 반환 → 크래시·타임아웃도 −1 불가. 색=주 타깃 성분(<span style="color:{ACC['z1']}">●z1</span> <span style="color:{ACC['z2']}">●z2</span> <span style="color:{ACC['z3']}">●z3</span> <span style="color:{C['mut2']}">●feas</span>). 점선·흐림=기본 OFF.</p>
  <div class="card">
    <div class="flow">
      <div class="phase-h">구성 — Floor 만들기</div>
      <div class="flrow">{''.join(stage_box(s) for s in stages[:3])}</div>
      <div class="arrow">▼</div>
      <div class="flrow">{''.join(stage_box(s) for s in stages[3:])}</div>

      <div class="phase-h">개선 — 검증된 floor 위 후처리 <code style="font-size:10px;color:var(--mut2)">_postprocess_verified_solution()</code> (z1→z2→z3 순)</div>
      <div class="flrow">{''.join(stage_box(s) for s in pp_stages[:4])}</div>
      <div class="arrow">▼</div>
      <div class="flrow">{''.join(stage_box(s) for s in pp_stages[4:])}</div>

      <div class="phase-h">레이스 — 대안 floor 경쟁 + 최종 게이트</div>
      <div class="flrow">{''.join(stage_box(s) for s in race_stages[:3])}</div>
      <div class="arrow">▼</div>
      <div class="flrow">{''.join(stage_box(s) for s in race_stages[3:])}</div>
    </div>
  </div>
  <div class="note"><b>제출 경로(gate200_v2, T≥60).</b> <code>OGC_SUBMIT_V2</code>(ON)가 16개 노브를 <code>setdefault</code> 주입: FastFloor를 1차 floor로 승격(greedy 대체) · cum_level 예산 30% · assign-cap 0.85 · BAN-RACE(ROUNDS=2,TAIL,90s). <b>z3-RACE(stage 6)는 구현·배선 완료이나 기본 OFF</b> — 현재 살아있는 z3 레버는 Front B(4.7)뿐. ★표=v2에서 ON되는 플래그.</div>
</section>

<section id="break">
  <h2><span class="dot" style="background:{ACC['z3']}"></span>돌파 방향 — 실험 기반 재정렬 (2026-06-13/14)</h2>
  <p class="h2sub">제안했던 #1 레버(z3-race)를 실제로 켜서 검증 → <b>KILL</b>. 진짜 @600 갭(ours 1.64M vs comp 1.14M)을 측정해 우선순위 재배치. <span class="hr">prob_20 하나가 갭의 64%.</span></p>
  <div class="grid2">
    <div class="lever off" style="--lc:{ACC['inf']}">
      <h3><span class="rank" style="background:{ACC['inf']}">KILL</span> z3-RACE — 발동하나 채택 0</h3>
      <p>@600에서 prob_16/17/7 ON vs OFF 검증: z3-race가 <b>3/3 발동</b>(게이트·배선 정상)했으나 <b>채택 0/3</b>, obj 변화 정확히 0. 완화 CP-SAT 모델의 z3 이득이 entry-targeted 디코드(크레인·패킹)에서 <b>증발</b>(realize 시 z1 폭발 또는 z3 상승).</p>
      <div class="ev"><b>원인:</b> submit_v2의 Front B가 이미 floor z3를 낮게(16=205·17=405·7=394) 깎아놔 들어갈 틈 없음. 06-11 @300 진단과 동일 → <b>현재 파이프라인 상대 z3-race 폐기 확정.</b></div>
    </div>
    <div class="lever key" style="--lc:{ACC['base']}">
      <h3><span class="rank">#1</span> prob_20 z1 닫기 — 갭의 64%</h3>
      <p>우리 428,853 vs 91,096 (<b>4.7×</b>). 그중 <b>z1=12 × w1=26,667 = 320K가 z1 페널티</b>. z1만 0이면 obj≈108,849로 거의 동률. 다른 10개 손실(z3) 합보다 큼.</p>
      <div class="ev"><b>검증 중:</b> z1-repair 루프 실가동(<code>OGC_Z1_REPAIR_LOOP=1</code>+RESERVE — 배선됐으나 예산기아로 한번도 안 돎) @600 + 시간 스케일링 @1200/@1800(대형 인스턴스는 eval에서 ~30분 → 과거 z1 9→2 기록). <b>결과 대기 중.</b></div>
    </div>
    <div class="lever" style="--lc:{ACC['z3']}">
      <h3><span class="rank">#2</span> Z3 손실 클러스터 — 10개 중 9개</h3>
      <p>prob_18(+58K)·13(+37K)·4(+29K)·6(+28K)·3(+26K)·12(+21K)·11(+14K)·17(+13K)·15(+3K). 전부 z1=0, z3가 경쟁자의 1.5~4×. 경쟁자가 5~47초에 낮은 z3 달성 = <b>구조적으로 가능함의 증거</b>.</p>
      <div class="ev"><b>레버(z3-race 아님):</b> ① config 포트폴리오 레이스(raster/posk3가 과거 prob_17/19/4를 이긴 기록 — submit_v2 흡수 여부 검증) ② z3-aware <b>초기 배정</b>(post-hoc relocate가 아닌 — Front B는 로컬옵티멈). realize-barrier가 근본 난제.</div>
    </div>
    <div class="lever" style="--lc:{ACC['z1']}">
      <h3><span class="rank">#3</span> 잔여 — prob_14 z1=1 · prob_15 회귀</h3>
      <p>prob_14: z1=1만 닫으면 −17,778(#1과 같은 repair 레버). prob_15: raster 시절 37,814 → submit_v2 50,783 <b>회귀(+34%)</b> — 알려진 손실, config 레이스로 raster 경로 복원 시 되돌릴 수 있음.</p>
      <div class="ev"><b>접근:</b> #1의 repair 루프가 prob_14도 커버. prob_15는 #2의 config 포트폴리오와 동일 레버.</div>
    </div>
  </div>
  <div class="note"><b>전략 요약 (수정).</b> "갭은 전부 z3 → z3-race가 레버"라는 가설은 <b>실험으로 반증됨</b>: (1) z3-race는 현 파이프라인을 못 이긴다, (2) 갭의 64%는 z3가 아니라 <b>prob_20의 z1</b>이다. 새 우선순위 = prob_20 z1 닫기(검증 중) → 그다음 z3 손실에 <b>config 포트폴리오 레이스</b>(z3-race 아님). 검증 규칙: 채택 판정은 full-20 paired(사용자 지시). 경쟁자가 모든 인스턴스 z1=0·낮은 z3를 5~47초에 달성 = 우리가 닿을 수 있는 상한의 존재 증명.</div>
</section>

<footer style="margin-top:50px;padding-top:18px;border-top:1px solid var(--line);color:var(--mut2);font-size:11.5px">
  생성 2026-06-13 (갱신 06-14, 실험기반) · 데이터: results/compare_baseline_20260601_2152 · <b>results/_rebaseline600/</b>(full-20 @600 재측정) · results/_z3probe/(z3-race ON/OFF) · competitor-2026-06-11.json · 파이프라인: src/myalgorithm.py + src/z3race.py + src/fastfloor.py
</footer>

<script>
(function(){{
 const tbl=document.getElementById('tbl');if(!tbl)return;
 tbl.querySelectorAll('th').forEach(th=>{{th.addEventListener('click',()=>{{
   const k=+th.dataset.k,typ=th.dataset.t||'n',tb=tbl.tBodies[0];
   const rows=[...tb.rows];const dir=th._d=!th._d?1:-1;
   const val=r=>{{let s=r.cells[k].innerText.replace(/[,×→].*$/,'').replace(/[^0-9.\-]/g,'');return typ==='s'?r.cells[k].innerText:parseFloat(s)||0;}};
   rows.sort((a,b)=>{{const x=val(a),y=val(b);return typ==='s'?(''+x).localeCompare(y)*dir:(x-y)*dir;}});
   rows.forEach(r=>tb.appendChild(r));
 }});}});
}})();
</script>
</div></body></html>'''

with open(OUT,"w",encoding="utf-8") as f:
    f.write(html)
print("WROTE",OUT,len(html),"bytes")
print("base_total(feasible16)=",base_total,"cur_total=",cur_total)
