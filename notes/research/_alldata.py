import json
from pathlib import Path
B = Path('notes/research/baselines')
ours = json.load(open(B / 'c12.json'))
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
rows = []
for i in range(1, 41):
    k = f'prob_{i}'
    o = ours.get(k, {})
    prob = json.load(open(f'instances/train/{k}.json', encoding='utf-8'))
    w = prob['weights']; w1, w2, w3 = w['w1'], w['w2'], w['w3']
    nb = len(prob['bays']); nblk = len(prob['blocks'])
    z1 = o.get('z1'); z2 = o.get('z2'); z3 = o.get('z3'); obj = o.get('obj')
    row = {'inst': k, 'set': 1 if i <= 20 else 2, 'nblk': nblk, 'nbay': nb,
           'w1': w1, 'w2': w2, 'w3': w3, 'feas': o.get('feas'),
           'z1': z1, 'z2': z2, 'z3': z3, 'obj': obj,
           'c1': (w1 * z1 if z1 is not None else None),
           'c2': (w2 * z2 if z2 is not None else None),
           'c3': (w3 * z3 if z3 is not None else None)}
    c = COMP.get(k)
    if c:
        row['comp_obj'] = c.get('obj'); row['comp_z1'] = c.get('z1')
        row['comp_z2'] = c.get('z2_unfloored'); row['comp_z3'] = c.get('z3')
        row['win'] = (obj is not None and c.get('obj') is not None and obj < c['obj'])
        row['gap_pct'] = (100 * (obj - c['obj']) / c['obj']) if (obj and c.get('obj')) else None
    rows.append(row)
out = {'rows': rows,
       'total_obj': sum(r['obj'] for r in rows if r.get('obj') is not None),
       'set1_total': sum(r['obj'] for r in rows if r['set'] == 1 and r.get('obj') is not None),
       'set2_total': sum(r['obj'] for r in rows if r['set'] == 2 and r.get('obj') is not None),
       'comp_set1_total': sum(r['comp_obj'] for r in rows if r.get('comp_obj') is not None),
       'wins': sum(1 for r in rows if r.get('win')),
       'feasible': sum(1 for r in rows if r.get('feas'))}
json.dump(out, open('notes/research/_alldata.json', 'w'), indent=1)
print('wrote _alldata.json')
print('total_obj=%.0f set1=%.0f set2=%.0f comp_set1=%.0f wins=%d feasible=%d/40'
      % (out['total_obj'], out['set1_total'], out['set2_total'],
         out['comp_set1_total'], out['wins'], out['feasible']))
