import json, sys
sys.path.insert(0,'C:/claude-develop/OGC2026/src')
sys.path.insert(0,'C:/claude-develop/OGC2026/tools')
import ogc_analysis as A

rows=[]
for p in range(1,21):
    prob=json.load(open(f'C:/claude-develop/OGC2026/instances/train/prob_{p}.json',encoding='utf-8'))
    sol=json.load(open(f'C:/claude-develop/OGC2026/results/z1traj/_sol_prob_{p}_solve.json',encoding='utf-8'))
    feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    # get n_blocks and n_bays cheaply
    n_blocks=None; n_bays=None
    for k in prob.keys():
        v=prob[k]
        if isinstance(v,list) and k.lower() in ('blocks','jobs','block_list','job_list'):
            n_blocks=len(v)
        if k.lower() in ('bays','bay_list'):
            if isinstance(v,list): n_bays=len(v)
        if k.lower() in ('num_bays','n_bays'):
            if isinstance(v,int): n_bays=v
    rows.append((p,bool(feas),o1,o2,o3,obj,n_blocks,n_bays))

for r in rows:
    print('P%-3d feas=%s Z1=%8.3f Z2=%8.3f Z3=%8.3f OBJ=%10.3f blocks=%s bays=%s'%r)

# Show prob_1 keys for reference
prob1=json.load(open('C:/claude-develop/OGC2026/instances/train/prob_1.json',encoding='utf-8'))
print('PROB1_KEYS:', list(prob1.keys()))
for k,v in prob1.items():
    if isinstance(v,list): print(f'  {k}: list len={len(v)}')
    else: print(f'  {k}: {type(v).__name__} = {v!r:.60}')
