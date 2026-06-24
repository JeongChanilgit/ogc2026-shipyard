import json, sys
sys.path.insert(0,'C:/claude-develop/OGC2026/src')
sys.path.insert(0,'C:/claude-develop/OGC2026/tools')

# Raw Z values already known from previous run; compute weighted contribution
data = {
    3:  (0,   424, 584,  100, 3),
    4:  (1,  1299, 654,  100, 2),
    6:  (0,  3290,1652,  150, 3),
    9:  (2,  1986,1531,  200, 3),
   12:  (20, 4582,1206,  200, 4),
   13:  (1,  2097,1106,  250, 4),
   14:  (35, 2162,1324,  250, 4),
   15:  (2,  3859, 214,  250, 4),
   16:  (1,  1733,1120,  250, 4),
   17:  (0,  7028,1968,  300, 4),
   20:  (18,  573,10422, 300, 5),
}

for p in sorted(data.keys()):
    prob=json.load(open(f'C:/claude-develop/OGC2026/instances/train/prob_{p}.json',encoding='utf-8'))
    w=prob['weights']
    z1,z2,z3,nb,nbays=data[p]
    c1=w['w1']*z1; c2=w['w2']*z2; c3=w['w3']*z3
    total=c1+c2+c3
    dom='Z1' if c1==max(c1,c2,c3) else ('Z2' if c2==max(c1,c2,c3) else 'Z3')
    print(f'P{p:02d} blocks={nb} bays={nbays} w1={w["w1"]:6d} w2={w["w2"]:4d} w3={w["w3"]:5d} | c1={c1:10.0f} c2={c2:10.0f} c3={c3:10.0f} | DOM={dom}')
