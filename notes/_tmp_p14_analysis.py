import json
from collections import defaultdict

INST = 'C:/claude-develop/OGC2026/instances/train/prob_14.json'
SOL  = 'C:/claude-develop/OGC2026/results/capture/stagetrace_e2/prob_14.json'

inst = json.load(open(INST))
sol  = json.load(open(SOL))
bays   = inst['bays']
blocks = inst['blocks']
ops_by_time = sol['solution']['operations']

block_ops = defaultdict(dict)
for t_str, op_list in ops_by_time.items():
    t = int(t_str)
    for op in op_list:
        bid = op['block_id']
        typ = op['type']
        if typ == 'ENTRY':
            block_ops[bid]['entry'] = t
            block_ops[bid]['bay']   = op['bay_id']
            block_ops[bid]['orient']= op['orient_idx']
        elif typ == 'EXIT':
            block_ops[bid]['exit'] = t

def bbox_orient(shape_list, orient_idx):
    for s in shape_list:
        if s['orientation'] == orient_idx:
            xs=[pt[0] for layer in s['layers'] for pt in layer]
            ys=[pt[1] for layer in s['layers'] for pt in layer]
            if xs: return (max(xs)-min(xs), max(ys)-min(ys))
    return (0,0)

def fits(shape_list, W, H):
    for s in shape_list:
        xs=[pt[0] for layer in s['layers'] for pt in layer]
        ys=[pt[1] for layer in s['layers'] for pt in layer]
        if xs:
            bw=max(xs)-min(xs); bh=max(ys)-min(ys)
            if bw<=W and bh<=H: return True
    return False

summaries=[]
for i,blk in enumerate(blocks):
    info=block_ops.get(i,{})
    entry=info.get('entry'); exit_=info.get('exit')
    bay_id=info.get('bay'); orient=info.get('orient',0)
    if exit_ is None: continue
    R=blk['release_time']; D=blk['due_date']; P=blk['processing_time']
    bw,bh=bbox_orient(blk['shape'],orient)
    summaries.append({'block_id':i,'bay':bay_id,'R':R,'P':P,'D':D,
        'entry':entry,'exit':exit_,'tardiness':max(0,exit_-D),
        'lateness':exit_-D,'orient':orient,'bw':bw,'bh':bh,
        'area':bw*bh,'shape':blk['shape']})

tardy=[s for s in summaries if s['tardiness']>0]
print(f'z1={sum(s["tardiness"] for s in tardy):.0f}, tardy_count={len(tardy)}')
print(f'block  bay   R    P    D  entry   exit  tard   bboxW   bboxH    area')
for s in sorted(tardy,key=lambda x:-x['tardiness']):
    print(f'{s["block_id"]:5d} {s["bay"]:4d} {s["R"]:4d} {s["P"]:4d} {s["D"]:4d} {s["entry"]:6d} {s["exit"]:6d} {s["tardiness"]:5.0f} {s["bw"]:7.2f} {s["bh"]:7.2f} {s["area"]:8.1f}')

print()
for j,bay in enumerate(bays):
    print(f'Bay {j}: {bay["width"]}x{bay["height"]}={bay["width"]*bay["height"]}')

all_int=defaultdict(list)
for s in summaries:
    slack=s['D']-s['exit']
    all_int[s['bay']].append((s['entry'],s['exit'],s['block_id'],s['area'],slack,s['shape']))

print()
for tb in tardy:
    ws=tb['D']-tb['P']; we=tb['D']
    bid=tb['block_id']; cbay=tb['bay']
    print(f'=== Block {bid} bay={cbay} tard={tb["tardiness"]:.0f} D={tb["D"]} P={tb["P"]} window=[{ws},{we}] entry={tb["entry"]} exit={tb["exit"]} ===')
    print(f'  bbox={tb["bw"]:.2f}x{tb["bh"]:.2f} area={tb["area"]:.1f}')
    for j,bay in enumerate(bays):
        W=bay['width']; H=bay['height']; ba=W*H
        ovl=[(e2,x2,b2,a2,s2) for (e2,x2,b2,a2,s2,sh2) in all_int[j] if b2!=bid and e2<we and x2>ws]
        occ=sum(a2 for _,_,_,a2,_ in ovl)
        pct=occ/ba*100
        rem=ba-occ-tb['area']
        fit=fits(tb['shape'],W,H)
        mark=' <- CURRENT' if j==cbay else ''
        nf=' [NOFIT]' if not fit else ''
        print(f'  Bay{j}({W}x{H}={ba}): occ={occ:.0f}({pct:.1f}%) rem={rem:.0f} n={len(ovl)}{mark}{nf}')

    cohabit=[(e2,x2,b2,a2,s2,sh2) for (e2,x2,b2,a2,s2,sh2) in all_int[cbay] if b2!=bid and e2<we and x2>ws]
    cands=sorted([(e2,x2,b2,a2,s2,sh2) for (e2,x2,b2,a2,s2,sh2) in cohabit if s2>=0],key=lambda x:(-x[4],x[3]))
    print(f'  cohabit={len(cohabit)}, slack>=0 cands={len(cands)}:')
    for (e2,x2,b2,a2,s2,sh2) in cands[:5]:
        alts=[]
        for j2,bay2 in enumerate(bays):
            if j2==cbay: continue
            if fits(sh2,bay2['width'],bay2['height']):
                occ2=sum(a3 for (e3,x3,b3,a3,s3,sh3) in all_int[j2] if b3!=b2 and e3<we and x3>ws)
                alts.append(f'bay{j2}occ={occ2:.0f}')
        print(f'    Block{b2:3d} area={a2:.0f} slack={s2:+.0f} [{e2},{x2}] alts={alts}')
    if not cands: print('    (none)')

    cohabit_all=[(e2,x2,b2,a2,s2,sh2) for (e2,x2,b2,a2,s2,sh2) in all_int[cbay] if b2!=bid and e2<tb['exit'] and x2>tb['entry']]
    later=[(b2,x2) for (e2,x2,b2,a2,s2,sh2) in cohabit_all if x2>tb['exit']]
    print(f'  CRANE: total_cohabit_full_stay={len(cohabit_all)}, later_exit={len(later)}: {later[:10]}')