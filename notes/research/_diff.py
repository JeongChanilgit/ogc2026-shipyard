import json
from pathlib import Path
B = Path('notes/research/baselines')
new = json.load(open(B / 'c8.json'))
old = json.load(open(B / 'h6.json'))
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']

def tot(d):
    return sum(d[k]['obj'] for k in d if d[k].get('feas') and d[k].get('obj') is not None)

improved = regressed = 0
regs = []
wins_new = wins_old = []
wn = wo = 0
flips = []
print(f"{'inst':<9}{'h6_obj':>14}{'c8_obj':>14}{'delta':>14}{'c8_z1':>7}{'comp':>14}{'win':>6}")
for i in range(1, 41):
    k = f'prob_{i}'
    o = old.get(k, {}); n = new.get(k, {})
    oo = o.get('obj'); no = n.get('obj')
    comp = COMP.get(k, {}).get('obj')
    if oo is None or no is None:
        continue
    d = no - oo
    if d < -1e-6: improved += 1
    elif d > 1e-6:
        regressed += 1; regs.append((k, oo, no, d))
    win_n = comp is not None and no < comp
    win_o = comp is not None and oo < comp
    if comp is not None:
        wn += 1 if win_n else 0
        wo += 1 if win_o else 0
        if win_n and not win_o: flips.append(k)
    mark = ('WIN' if win_n else 'loss') if comp is not None else ''
    star = ' *' if (d < -1e-6 and abs(d) > 1e4) else ''
    print(f"{k:<9}{oo:>14.0f}{no:>14.0f}{d:>+14.0f}{n.get('z1',0):>7.0f}"
          f"{(comp if comp else 0):>14.0f}{mark:>6}{star}")
print('-' * 80)
print(f"total h6={tot(old):.0f}  c8={tot(new):.0f}  delta={tot(new)-tot(old):+.0f} "
      f"({100*(tot(new)-tot(old))/tot(old):+.2f}%)")
print(f"improved={improved} regressed={regressed}  regs={[(r[0],int(r[3])) for r in regs] or 'NONE'}")
print(f"set1 wins: h6={wo} -> c8={wn}   new flips to WIN: {flips or 'none'}")
