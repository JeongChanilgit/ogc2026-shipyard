import json
from pathlib import Path
B = Path('notes/research/baselines')
ours = json.load(open(B / 'c8.json'))
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']

rows = []
print(f"{'inst':<8}{'our_obj':>12}{'comp_obj':>11}{'ratio':>7}{'our_z1':>7}{'cmp_z1':>7}"
      f"{'our_z3':>7}{'cmp_z3':>7}  {'verdict':<6}{'gap_to_beat':>12}")
wins = 0
for i in range(1, 21):
    k = f'prob_{i}'
    o = ours.get(k, {}); c = COMP.get(k, {})
    oo = o.get('obj'); co = c.get('obj')
    if oo is None or co is None:
        continue
    ratio = oo / co if co else float('inf')
    win = oo < co
    wins += 1 if win else 0
    gap = oo - co
    verd = 'WIN' if win else ('TIE' if abs(gap) < 1 else 'loss')
    rows.append({'inst': k, 'our_obj': oo, 'comp_obj': co, 'ratio': ratio,
                 'our_z1': o.get('z1', 0), 'comp_z1': c.get('z1', 0),
                 'our_z3': o.get('z3', 0), 'comp_z3': c.get('z3', 0),
                 'verdict': verd, 'gap': gap})
    print(f"{k:<8}{oo:>12.0f}{co:>11.0f}{ratio:>7.1f}{o.get('z1',0):>7.0f}"
          f"{c.get('z1',0):>7.0f}{o.get('z3',0):>7.0f}{c.get('z3',0):>7.0f}  "
          f"{verd:<6}{gap:>+12.0f}")
print('-' * 86)
print(f"set1 WINS = {wins}/20   (win = our obj strictly < competitor obj)")
# how many would flip to WIN if residual z1 -> 0 (obj minus w1*z1)
W = {}
import json as _j
near = []
for i in range(1, 21):
    k = f'prob_{i}'
    p = _j.load(open(f'instances/train/{k}.json', encoding='utf-8'))
    w1 = p['weights']['w1']
    o = ours[k]; c = COMP[k]
    if o['obj'] >= c['obj']:
        obj_if_z1_0 = o['obj'] - w1 * o.get('z1', 0)
        if obj_if_z1_0 < c['obj']:
            near.append((k, o.get('z1', 0), w1, int(c['obj']), int(obj_if_z1_0)))
print(f"would FLIP to WIN if its residual z1 -> 0: {[n[0] for n in near]}")
for n in near:
    print(f"   {n[0]}: z1={n[1]} w1={n[2]} comp={n[3]} -> our_obj_if_z1=0={n[4]}")
json.dump(rows, open('notes/research/_compare.json', 'w'), indent=0)
