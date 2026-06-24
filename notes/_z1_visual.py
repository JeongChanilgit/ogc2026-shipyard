# -*- coding: utf-8 -*-
"""Generate a visual (SVG-diagram) explainer of the Z1->0 application insights (diagnosis + 1..8 + roadmap)."""
import sys, html, shutil
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(r"C:\claude-develop\OGC2026")
OUT = ROOT / "notes" / "z1-insights-visual-2026-06-06.html"
RES = ROOT / "research" / "z1-tardiness"

# palette
BG="#0f1419"; PANEL="#171d26"; PANEL2="#1d2530"; INK="#e6edf3"; MUT="#8b98a8"; LINE="#2a3441"
ACC="#4ea1ff"; AMBER="#ffb454"; GREEN="#3fb950"; RED="#f85149"; SLATE="#5b7characters"  # placeholder
SLATE="#54688a"; SLATE2="#3a4a60"; PURP="#b07cff"

def esc(s): return html.escape(str(s))
def T(x,y,s,size=13,fill=INK,anchor="start",weight="400",style=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" style="{style}" font-family="Segoe UI,Malgun Gothic,sans-serif">{esc(s)}</text>'
def R(x,y,w,h,fill,rx=5,stroke="none",sw=1,dash=None,op=1.0):
    d=f' stroke-dasharray="{dash}"' if dash else ''
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d} opacity="{op}"/>'
def LN(x1,y1,x2,y2,stroke,sw=2,dash=None,marker=False):
    d=f' stroke-dasharray="{dash}"' if dash else ''
    m=' marker-end="url(#ah)"' if marker else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}{m}/>'
def block(x,y,w,h,fill,label="",sub="",tcol="#06101d"):
    s=R(x,y,w,h,fill,rx=4)
    if label: s+=T(x+w/2,y+h/2+1,label,12,tcol,"middle","700")
    if sub: s+=T(x+w/2,y+h/2+15,sub,10,tcol,"middle","500")
    return s
def crane(cx,top,blocked=False):
    col=RED if blocked else AMBER
    s=LN(cx-44,top,cx+44,top,AMBER,3)              # rail
    s+=R(cx-7,top,14,9,AMBER,rx=2)                 # trolley
    s+=LN(cx,top+9,cx,top+24,col,2)                # hook line
    s+=f'<polygon points="{cx-4},{top+24} {cx+4},{top+24} {cx},{top+30}" fill="{col}"/>'
    if blocked:
        s+=T(cx,top-6,"✕ 접근 차단",11,RED,"middle","700")
    else:
        s+=T(cx,top-6,"크레인",10,AMBER,"middle","600")
    return s
def svg(w,h,body):
    defs=(f'<defs>'
          f'<marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="{ACC}"/></marker>'
          f'<marker id="ahr" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="{RED}"/></marker>'
          f'</defs>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" role="img">{defs}{body}</svg>'

FIGS=[]
def add(idx,badge,title,svg_body,svg_wh,caption,take):
    FIGS.append((idx,badge,title,svg(svg_wh[0],svg_wh[1],svg_body),caption,take))

# ---------- DIAGNOSIS ----------
b=""
# panel A : intuition (wrong) - top view, mostly empty
b+=T(153,26,"직관 (틀림): 공간이 부족해서?",13,MUT,"middle","700")
b+=R(48,52,210,150,PANEL2,rx=8,stroke=LINE)
b+=T(153,88,"공간은 남는다 ❌",12,RED,"middle","700")
b+=T(153,120,"바닥 75~94% 텅 빔",11.5,MUT,"middle")
b+=block(130,148,46,26,RED,"지각")
b+=T(153,192,"이 블록은 계속 대기중",10,RED,"middle","600")
# divider
b+=LN(310,44,310,228,LINE,1,"4 4")
# panel B : reality (side view stack, crane blocked)
b+=T(470,26,"실제: 크레인 j≥k 수직접근이 직렬화",13,INK,"middle","700")
b+=R(370,104,150,98,PANEL2,rx=6,stroke=LINE)
b+=crane(445,86,blocked=True)
b+=block(382,168,126,26,RED,"B — 나가야 함")
b+=block(382,140,126,26,SLATE,"A")
b+=block(382,112,126,26,SLATE2,"")
b+=T(528,150,"B를 들려면",10.5,INK)
b+=T(528,166,"위 블록 먼저",10.5,INK)
b+=T(528,182,"치워야 → 대기",10.5,RED,"start","700")
add("진단","DIAGNOSIS","Z1은 패킹이 아니라 \"크레인 직렬화\" 문제다",
    b,(640,250),
    "왼쪽 직관은 틀렸다. tardy 블록은 바닥이 75~94% 빈 채로 평균 8~166시간 대기한다. 부족한 자원은 면적이 아니라 \"크레인이 그 블록에 닿을 수 있는 시점\"이다. 위층(j≥k)이 비어야 들고 나는 규칙 = 컨테이너 적재(stacking)와 동일.",
    "공간은 남는다. 크레인 접근 순서가 병목이다.")

# ---------- (1) sequence vs timing ----------
b=""
def gantt(y0,title,bars,due_x,tcol):
    s=T(40,y0-10,title,12.5,tcol,"start","700")
    s+=LN(40,y0+58,560,y0+58,LINE,1)                       # time axis
    s+=LN(due_x,y0-2,due_x,y0+58,AMBER,1.5,"4 3")
    s+=T(due_x,y0-6,"마감",10,AMBER,"middle","600")
    for (x,w,lab,fill) in bars:
        s+=block(x,y0+ (0 if lab!='C' else 0),w,16,fill,lab) if False else ""
    return s
# manual bars top (greedy)
y0=58
b+=T(40,y0-12,"현재 (그리디 + force-place): 같은 순서인데 늦게 시작",12.5,MUT,"start","700")
b+=LN(40,y0+70,580,y0+70,LINE,1)
duex=470
b+=LN(duex,y0-4,duex,y0+78,AMBER,1.5,"4 3"); b+=T(duex,y0-6,"마감",10,AMBER,"middle","600")
b+=block(60,y0+4,90,16,SLATE,"A")
b+=block(170,y0+26,90,16,SLATE,"B")
b+=block(300,y0+48,110,16,SLATE,"C")
b+=block(430,y0+48,90,16,RED,"D")            # D ends past due -> tardy
b+=T(548,y0+60,"지각!",11,RED,"start","700")
b+=T(60,y0+18,"틈(idle)",9,"#06101d","start") if False else ""
# bottom (timing DP)
y1=170
b+=T(40,y1-12,"타이밍 DP: 순서·배치 그대로, ENTRY/EXIT만 앞으로 당김",12.5,GREEN,"start","700")
b+=LN(40,y1+70,580,y1+70,LINE,1)
b+=LN(duex,y1-4,duex,y1+78,AMBER,1.5,"4 3")
b+=block(60,y1+4,90,16,GREEN,"A")
b+=block(150,y1+26,90,16,GREEN,"B")
b+=block(240,y1+48,110,16,GREEN,"C")
b+=block(350,y1+48,90,16,GREEN,"D")          # now before due
b+=T(452,y1+60,"정시 ✓",11,GREEN,"start","700")
b+=LN(300,y0+74,240,y1+44,ACC,1.6,None,True)
add("①","TIMING DP","순서(NP-hard)와 타이밍(다항시간)을 분리하라",
    b,(600,250),
    "\"무엇을 어떤 순서로\"(어려움)와 \"그 순서에 언제\"(쉬움)를 쪼갠다. 고정된 순서·배치에 대해 최적 ENTRY/EXIT는 O(n²) DP로 정확히 계산된다. 우리 _shift_tardy_intervals(:2016)의 14틱 국소탐색을 이 DP로 교체하면 배치를 안 바꾸므로 Z2/Z3 불변, Z1만 내려간다.",
    "배치를 안 건드리는 가장 안전한 Z1↓. objective-safe.")

# ---------- (2) lower bound ----------
b=""
b+=T(300,20,"각 베이의 '피할 수 없는' tardiness 하한 L*를 먼저 안다",13,INK,"middle","700")
bays=[("Bay 1",120,0,"회수가능 → 최우선",GREEN),
      ("Bay 2",80,80,"이미 하한 → SKIP",MUT),
      ("Bay 3",200,60,"gap 140 닫기",AMBER),
      ("Bay 4",30,30,"하한 → SKIP",MUT)]
x0=70; bw=90; gap=40; base=210; scale=0.7
for i,(nm,z1,ls,note,col) in enumerate(bays):
    x=x0+i*(bw+gap)
    h=z1*scale
    b+=R(x,base-h,bw,h,RED if z1>ls else SLATE,rx=4,op=0.92)   # current Z1
    if ls>0:
        ly=base-ls*scale
        b+=LN(x-6,ly,x+bw+6,ly,GREEN,2.5)
        b+=T(x+bw+8,ly+4,f"L*={ls}",10,GREEN,"start","700")
        # gap shading
        if z1>ls:
            b+=R(x,base-h,bw,h-ls*scale,RED,rx=3,op=0.25)
    else:
        b+=LN(x-6,base,x+bw+6,base,GREEN,2.5)
        b+=T(x+bw+8,base+4,"L*=0",10,GREEN,"start","700")
    b+=T(x+bw/2,base-h-8,f"Z1={z1}",11,INK,"middle","700")
    b+=T(x+bw/2,base+18,nm,11,MUT,"middle","600")
    b+=T(x+bw/2,base+33,note,9.5,col,"middle","600")
b+=LN(40,base,560,base,LINE,1)
add("②","LOWER BOUND","per-bay 하한 L*로 탐색을 집중하고 종료를 판단",
    b,(600,260),
    "Block-Relocation·single-machine 하한을 싸게 계산한다. L*=0 인데 Z1>0 인 베이는 손실 100% 회수 가능 → 최우선. 이미 Z1==L* 인 베이는 더 못 줄이니 건너뛴다 → 176/180s 예산을 gap 있는 곳에만 쓴다(병목 #4 직접 해소).",
    "어디가 '회수 가능한 손실'인지 알면 예산이 안 샌다.")

# ---------- (3) anticipatory placement ----------
b=""
def stack3(bx,title,layers,blocked,tcol):
    s=T(bx+75,24,title,11.5,tcol,"middle","700")
    s+=R(bx,110,150,96,PANEL2,rx=6,stroke=LINE)
    s+=crane(bx+75,92,blocked=blocked)
    yy=176
    for (lab,fill,tc) in layers:
        s+=block(bx+18,yy,114,26,fill,lab,"",tc)
        yy-=28
    return s
b+=stack3(80,"나쁨: 급한 블록을 깊이 묻음",[("R — 급함",RED,"#06101d"),("여유블록",SLATE,"#06101d"),("여유블록",SLATE2,"#e6edf3")],True,"#f0a0a0")
b+=T(155,224,"→ 위 2개 치워야 → 지각",10.5,RED,"middle","700")
b+=T(310,150,"vs",16,MUT,"middle","700")
b+=stack3(380,"좋음: 급한 블록을 통로·상단에",[("여유블록",SLATE2,"#e6edf3"),("여유블록",SLATE,"#06101d"),("R — 급함",GREEN,"#06101d")],False,"#a0e0b0")
b+=T(455,224,"→ 크레인 바로 접근 → 정시",10.5,GREEN,"middle","700")
add("③","PLACEMENT","마감-인지 배치 — 급한 블록을 '안 막히는' 셀에 선점",
    b,(620,250),
    "배치 단계에서 미래의 retrieval 순서를 미리 고려한다(pre-marshalling 정신). slack=due−release−proc 가 작은(급한) 블록은 위층이 안 쌓일 통로·상단에, 여유 블록은 깊은 곳에. 우리 _candidate_positions는 top-edge 패킹만 보므로 crane 압력을 프록시→1급 결정요소로 승격.",
    "배치 = 미래 크레인 접근 순서를 위한 사전정렬.")

# ---------- (4) LBBD ----------
b=""
b+=R(60,34,300,54,PANEL2,rx=8,stroke=ACC)
b+=T(210,56,"MASTER  (MIP / CP-SAT)",13,ACC,"middle","700")
b+=T(210,74,"베이 배정 + 크레인 순서로 Z1 최소화",10.5,INK,"middle")
b+=LN(120,88,120,150,ACC,2,None,True)
b+=T(130,122,"배정 후보 ↓",10.5,ACC,"start","600")
b+=R(60,150,300,56,PANEL2,rx=8,stroke=GREEN)
b+=T(210,172,"SUB  (run_parallel_bay_decode)",12.5,GREEN,"middle","700")
b+=T(210,190,"이 배정이 크레인-safe 패킹으로 실현가능?",10.5,INK,"middle")
# feedback cut (up, on the right, clear of boxes)
b+=f'<path d="M 360 178 C 500 150, 500 72, 362 60" fill="none" stroke="{RED}" stroke-width="2" stroke-dasharray="5 3" marker-end="url(#ahr)"/>'
b+=T(478,116,"실패 시",10.5,RED,"middle","700")
b+=T(478,133,"no-good cut",10.5,RED,"middle","700")
b+=T(478,150,"(이 조합 금지)",9.5,RED,"middle")
add("④","LBBD","Logic-Based Benders 2단계로 배정 재최적화 깊이를 키움",
    b,(640,228),
    "AM nesting+scheduling 문헌의 가장 가까운 아키텍처. master가 배정·순서로 Z1을 풀고, sub가 크레인-safe 패킹 실현가능성을 검사한다. 우리는 이미 sub용 oracle(run_parallel_bay_decode)을 갖고 있다. 실패하면 'no-good cut'을 master에 더해 같은 실수를 반복하지 않는다 → 얕은 _tardy_redecode_moves(10블록)보다 훨씬 넓게 탐색.",
    "feasibility를 cut으로 학습 → 깊은 재배정.")

# ---------- (5) CP-SAT ----------
b=""
b+=T(110,24,"작은 베이 (≤~20 블록)",12,MUT,"middle","600")
b+=R(40,36,150,120,PANEL2,rx=8,stroke=LINE)
for (x,y,w,h,c) in [(52,120,40,26,SLATE),(96,120,36,26,SLATE2),(52,90,30,26,SLATE),(86,86,46,30,SLATE2),(60,52,60,28,SLATE)]:
    b+=R(x,y,w,h,c,rx=3)
b+=LN(200,96,260,96,ACC,2,None,True)
b+=R(265,40,150,112,PANEL2,rx=8,stroke=PURP)
b+=T(340,62,"CP-SAT 모델",12.5,PURP,"middle","700")
b+=T(340,82,"interval (ENTRY/EXIT)",10.5,INK,"middle")
b+=T(340,98,"+ no_overlap_2d",10.5,INK,"middle")
b+=T(340,114,"+ j≥k precedence",10.5,INK,"middle")
b+=T(340,134,"min Σ tardiness",11,GREEN,"middle","700")
b+=LN(420,96,478,96,ACC,2,None,True)
b+=R(482,68,96,56,PANEL2,rx=8,stroke=GREEN)
b+=T(530,92,"정확해",12,GREEN,"middle","700")
b+=T(530,110,"Z1 = 0 (또는 L*)",10.5,GREEN,"middle","600")
add("⑤","CP-SAT","작은 베이는 CP-SAT 정확해 — 4코어·no-GPU 서버의 최적 무기",
    b,(600,180),
    "2D 배치를 interval 쌍 + no_overlap_2d(diffn)로, 크레인 j≥k를 조건부 precedence로 인코딩하고 Σtardiness를 최소화한다. CP-SAT(OR-Tools)는 순수 CPU에서 자체 멀티워커 LNS를 돌리는 도구라 평가서버(4코어·GPU없음·인터넷차단)에 완벽히 맞다. 작은 베이를 정확히 0/L*까지 풀어 그리디 결과를 대체·warm-start.",
    "GPU 없는 4코어에서 작은 베이를 진짜 0으로.")

# ---------- (6) ALNS ----------
b=""
def minisol(x,title,blocks,tcol):
    s=T(x+70,26,title,11,tcol,"middle","700")
    s+=R(x,38,140,116,PANEL2,rx=8,stroke=LINE)
    yy=124
    for (lab,fill) in blocks:
        s+=block(x+14,yy,112,22,fill,lab)
        yy-=26
    return s
b+=minisol(30,"① 현재 해",[("D — 지각",RED),("C",SLATE),("B",SLATE),("A",SLATE)],INK)
b+=LN(176,96,214,96,ACC,2,None,True); b+=T(195,88,"파괴",10,RED,"middle","700")
b+=minisol(220,"② worst-tardy 제거",[("",PANEL2),("C",SLATE),("",PANEL2),("A",SLATE)],RED)
b+=LN(366,96,404,96,ACC,2,None,True); b+=T(385,88,"복구",10,GREEN,"middle","700")
b+=minisol(410,"③ regret-k 재삽입",[("D — 정시",GREEN),("C",SLATE),("B",GREEN),("A",SLATE)],GREEN)
add("⑥","ALNS","tardiness-타겟 destroy/repair + 증분 Z1 평가",
    b,(600,175),
    "destroy를 'worst-tardy removal'(Z1 기여 1등 블록 + 그 크레인-blocker들) / 'crane-cluster removal'(수직 스택 통째)로, repair를 regret-k(마감 급한 것 먼저 재삽입)로 특화. 핵심은 증분 Z1 캐시 — 건드린 베이만 재평가해 같은 예산에 반복수를 10× 늘린다.",
    "막힌 블록을 통째로 빼고 마감순으로 다시 끼운다.")

# ---------- (7) SA accept-worse ----------
b=""
# landscape curve
pts="40,120 110,150 170,90 210,160 280,70 330,150 400,110 470,175 540,60"
b+=f'<polyline points="60,150 120,180 175,120 215,190 285,95 340,180 405,140 470,205 545,80" fill="none" stroke="{LINE}" stroke-width="2"/>'
b+=T(300,24,"목적함수 지형 (낮을수록 Z1↓)",12,MUT,"middle","600")
# greedy stuck
b+=f'<circle cx="175" cy="120" r="7" fill="{RED}"/>'
b+=T(175,108,"그리디: 국소최소에 갇힘",10.5,RED,"middle","700")
# SA path up then down
b+=f'<path d="M 175 120 Q 215 200 285 95" fill="none" stroke="{ACC}" stroke-width="2.5" stroke-dasharray="5 3" marker-end="url(#ah)"/>'
b+=T(248,150,"탐색: 일시적 악화 허용 (SA)",10.5,ACC,"middle","700")
b+=f'<circle cx="285" cy="95" r="7" fill="{GREEN}"/>'
b+=T(300,200,"더 낮은-Z1 분지",10.5,GREEN,"middle","700")
# final gate
b+=R(470,40,110,40,PANEL2,rx=8,stroke=AMBER)
b+=T(525,58,"반환 게이트",11,AMBER,"middle","700")
b+=T(525,72,"floor보다 나쁘면 거부",9,INK,"middle")
b+=LN(335,150,468,62,AMBER,1.5,"4 3")
add("⑦","ESCAPE","탐색은 accept-worse(SA), 반환만 안전 게이트",
    b,(600,225),
    "최종 게이트(:3259)가 '같은 objective에 더 낮은 Z1만' 채택하는 건 반환 안전장치로는 옳다. 문제는 내부 탐색까지 똑같이 탐욕적이면 Z1을 잠깐 손해 봐야 도달하는 더 좋은 분지에 못 간다. 내부 수용을 SA/threshold로 풀되, 반환 직전 official-checker 게이트는 그대로 둔다.",
    "중간엔 언덕을 내려가도, 제출은 절대 손해 안 봄.")

# ---------- (8) ATC vs EDD ----------
b=""
b+=T(160,24,"EDD (마감만): 급하고 짧은 일이 뒤에 막힘",11.5,MUT,"middle","600")
order_edd=[("A",SLATE,"느림"),("B",SLATE,""),("C",RED,"급+짧→지각"),("D",SLATE,"")]
x=40
for lab,fill,note in order_edd:
    b+=block(x,42,70,30,fill,lab)
    if note: b+=T(x+35,86,note,9,RED if fill==RED else MUT,"middle","600")
    x+=84
b+=T(160,118,"ATC (urgency×slack): 급한 걸 앞으로",11.5,GREEN,"middle","600")
order_atc=[("C",GREEN,"정시 ✓"),("A",SLATE,""),("B",SLATE,""),("D",SLATE,"")]
x=40
for lab,fill,note in order_atc:
    b+=block(x,134,70,30,fill,lab)
    if note: b+=T(x+35,178,note,9,GREEN,"middle","600")
    x+=84
b+=LN(75,76,75,130,ACC,1.6,None,True)
b+=T(420,100,"+ Emmons dominance:",11,INK,"start","700")
b+=T(420,118,"많은 블록쌍의 선후를",10.5,MUT,"start")
b+=T(420,134,"탐색 없이 미리 고정",10.5,MUT,"start")
b+=T(420,150,"→ 탐색공간 축소",10.5,AMBER,"start","600")
add("⑧","DISPATCH","ATC 우선순위 + Emmons 지배규칙 — 거의 공짜의 즉효",
    b,(600,200),
    "평범한 EDD는 가중 tardiness에 약하다. ATC(Apparent Tardiness Cost)는 urgency(w/p)와 due-slack을 지수가중해 급하고 짧은 일을 앞세운다(O(n log n)). Emmons 규칙은 최적해에서 확정되는 블록쌍 선후를 탐색 전에 고정. _orderings(:848)·_tardiness_seed(:1057)의 1차 정렬 교체로 즉시 적용.",
    "베이당 O(n log n), 코드 한 곳 교체로 baseline 상승.")

# ---------- ROADMAP ----------
def road():
    waves=[("Wave 0","진단","per-bay 하한 L*","②","#56708f"),
           ("Wave 1","즉효","타이밍DP·ATC·SA","①⑦⑧",GREEN),
           ("Wave 2","배치","마감-인지 배치","③",AMBER),
           ("Wave 3","구조","CP-SAT·ALNS","⑤⑥","#d98b4a"),
           ("Wave 4","통합","LBBD 2단계","④",RED)]
    s=""
    x=20; w=132; gap=14
    for i,(wv,kind,what,ins,col) in enumerate(waves):
        s+=R(x,40,w,96,PANEL2,rx=10,stroke=col,sw=1.6)
        s+=T(x+w/2,64,wv,13,col,"middle","800")
        s+=T(x+w/2,82,kind,10.5,MUT,"middle","600")
        s+=T(x+w/2,103,what,10.5,INK,"middle","600")
        s+=R(x+w/2-22,112,44,18,col,rx=9,op=0.18)
        s+=T(x+w/2,124,ins,11,col,"middle","800")
        if i<len(waves)-1:
            s+=LN(x+w,88,x+w+gap,88,ACC,2,None,True)
        x+=w+gap
    s+=T(370,24,"가장 안전(geometry 불변) → 가장 강력(구조 변경) 순",12,MUT,"middle","600")
    return s
ROADMAP=svg(760,150,road())

# ---------- assemble HTML ----------
cards=[]
for idx,badge,title,sv,cap,take in FIGS:
    cards.append(f"""<section class="card">
  <div class="ch"><span class="badge">{esc(idx)}</span><div><div class="ctitle">{esc(title)}</div><div class="cbadge">{esc(badge)}</div></div></div>
  <div class="fig">{sv}</div>
  <p class="cap">{esc(cap)}</p>
  <div class="take">💡 {esc(take)}</div>
</section>""")

CSS=f"""
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
body{{margin:0;background:{BG};color:{INK};font:15px/1.6 -apple-system,'Segoe UI',Roboto,'Malgun Gothic',sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 20px}}
header.top{{padding:44px 0 22px;border-bottom:1px solid {LINE};background:linear-gradient(180deg,#131a24,transparent)}}
header.top h1{{margin:0 0 8px;font-size:27px;letter-spacing:-.3px}}
header.top .sub{{color:{MUT};font-size:15.5px}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;margin-top:16px;font-size:13px;color:{MUT}}}
.legend span{{display:inline-flex;align-items:center;gap:6px}}
.sw{{width:13px;height:13px;border-radius:3px;display:inline-block}}
h2.sec{{font-size:21px;margin:38px 0 6px}}
.diag{{margin:14px 0 26px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:8px}}
.card{{background:{PANEL};border:1px solid {LINE};border-radius:14px;padding:16px 18px;display:flex;flex-direction:column}}
.card.full{{grid-column:1/-1}}
.ch{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.badge{{display:inline-flex;min-width:38px;height:38px;align-items:center;justify-content:center;background:{ACC};color:#06101d;border-radius:10px;font-weight:800;font-size:19px;flex:none}}
.ctitle{{font-size:16px;font-weight:700;line-height:1.3}}
.cbadge{{font-size:11px;letter-spacing:.08em;color:{MUT};text-transform:uppercase;margin-top:2px}}
.fig{{background:#0b0f15;border:1px solid {LINE};border-radius:10px;padding:8px;margin:6px 0 10px}}
.cap{{font-size:13.5px;color:#c4cfdb;margin:4px 0 10px}}
.take{{margin-top:auto;background:{PANEL2};border-left:3px solid {AMBER};border-radius:0 8px 8px 0;padding:8px 12px;font-size:13.5px;font-weight:600;color:#fff}}
footer{{border-top:1px solid {LINE};margin-top:46px;padding:22px 0 60px;color:{MUT};font-size:13px}}
@media(max-width:820px){{.grid{{grid-template-columns:1fr}}}}
"""

# diagnosis card (full width) is FIGS[0]; rest in grid
diag_idx,diag_badge,diag_title,diag_sv,diag_cap,diag_take=FIGS[0]
diag_card=f"""<section class="card full">
  <div class="ch"><span class="badge" style="background:{RED}">★</span><div><div class="ctitle">{esc(diag_title)}</div><div class="cbadge">{esc(diag_badge)}</div></div></div>
  <div class="fig">{diag_sv}</div>
  <p class="cap">{esc(diag_cap)}</p>
  <div class="take">💡 {esc(diag_take)}</div>
</section>"""
grid_cards="\n".join(cards[1:])

doc=f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OGC2026 — Z1→0 인사이트 그림 설명</title><style>{CSS}</style></head><body>
<header class="top"><div class="wrap">
<h1>그림으로 보는 Z1(Tardiness) → 0 인사이트</h1>
<div class="sub">크레인 직렬화를 푸는 8가지 처방을 다이어그램으로 — <a href="z1-literature-2026-06-06.html" style="color:{ACC}">문헌 리포트(147편)</a>의 시각 요약</div>
<div class="legend">
<span><i class="sw" style="background:{GREEN}"></i>정시 블록</span>
<span><i class="sw" style="background:{RED}"></i>지각 블록</span>
<span><i class="sw" style="background:{SLATE}"></i>여유(slack) 블록</span>
<span><i class="sw" style="background:{AMBER}"></i>크레인 / 마감</span>
<span><i class="sw" style="background:{ACC}"></i>탐색 흐름</span>
</div>
</div></header>
<main class="wrap">
<div class="diag">{diag_card}</div>
<h2 class="sec">적용 인사이트 ①–⑧</h2>
<div class="grid">{grid_cards}</div>
<h2 class="sec">권장 구현 순서</h2>
<section class="card full"><div class="fig">{ROADMAP}</div>
<p class="cap">Wave 1(①⑦⑧)은 배치·배정을 안 바꿔 Z2/Z3에 영향이 없는 'objective-safe 즉효'다. Wave 0(②)이 어디에 예산을 쓸지 먼저 알려준다. 오른쪽으로 갈수록 강력하지만 리스크·노력이 커진다.</p>
<div class="take">💡 안전한 즉효부터 구조적 변경 순으로. 모든 Wave는 기존 official-checker 게이트로 보호되어 −1 리스크 없음.</div></section>
</main>
<footer><div class="wrap">생성 2026-06-06 · 그림은 개념 모델(스케일 무관) · 근거 논문·file:line은 <a href="z1-literature-2026-06-06.html" style="color:{ACC}">메인 리포트</a> 참조 · crane j≥k = Blocking Job-Shop + Block-Relocation.</div></footer>
</body></html>"""

OUT.write_text(doc,encoding="utf-8")
RES.mkdir(parents=True,exist_ok=True)
shutil.copy2(OUT, RES/OUT.name)
print("WROTE", OUT, f"({OUT.stat().st_size} bytes)")
print("COPIED", RES/OUT.name)
print("figures:", len(FIGS), "+ roadmap")
