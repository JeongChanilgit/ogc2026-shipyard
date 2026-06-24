# Scratch diagnostic: brute-force the true optimal bay-assignment objective for a
# small instance, to validate whether cpsat's "optimal" is the real optimum or an
# over-restricted one. Lower bound uses w2*obj2 + w3*obj3 (w1*Z1 >= 0).
import json, sys, itertools

path = sys.argv[1] if len(sys.argv) > 1 else "instances/example/example_B2_b10.json"
with open(path, encoding="utf-8") as f:
    prob = json.load(f)

w = prob["weights"]
w1, w2, w3 = w["w1"], w["w2"], w["w3"]
blocks = prob["blocks"]
bays = prob["bays"]
n = len(blocks)
m = len(bays)

# bay_u[j] = avg_bay_area / (W_j * H_j)
areas = [b["width"] * b["height"] for b in bays]
avg = sum(areas) / len(areas)
bay_u = [avg / a for a in areas]

print(f"instance={path}")
print(f"n_blocks={n} n_bays={m} weights w1={w1} w2={w2} w3={w3}")
print(f"bay areas={areas} avg={avg:.1f} bay_u={[round(u,4) for u in bay_u]}")

workloads = [b["workload"] for b in blocks]
prefs = [b["bay_preferences"] for b in blocks]
smax = [max(p) for p in prefs]

best = None
# enumerate all m^n assignments (only feasible for small n)
for assign in itertools.product(range(m), repeat=n):
    loads = [0.0] * m
    obj3 = 0.0
    for b, j in enumerate(assign):
        loads[j] += workloads[b]
        obj3 += smax[b] - prefs[b][j]
    wl = [bay_u[j] * loads[j] for j in range(m)]
    obj2 = max(wl) - min(wl)
    val = w2 * obj2 + w3 * obj3
    if best is None or val < best[0]:
        best = (val, obj2, obj3, assign)

val, obj2, obj3, assign = best
print("\n=== TRUE assignment-level optimum (assuming Z1=0 achievable) ===")
print(f"min  w2*obj2 + w3*obj3 = {val:.2f}")
print(f"     obj2(imbalance)   = {obj2:.4f}  (x w2={w2} -> {w2*obj2:.2f})")
print(f"     obj3(preference)  = {obj3:.1f}   (x w3={w3} -> {w3*obj3:.1f})")
print(f"     assignment        = {list(assign)}")
loads = [0.0]*m
for b,j in enumerate(assign): loads[j]+=workloads[b]
print(f"     bay loads         = {[round(l,1) for l in loads]}")

# also report a few alternative trade-off points
print("\n=== reference points ===")
# all-most-preferred (Z3=0)
pref_assign = [max(range(m), key=lambda j: prefs[b][j]) for b in range(n)]
def evalA(a):
    loads=[0.0]*m; o3=0.0
    for b,j in enumerate(a): loads[j]+=workloads[b]; o3+=smax[b]-prefs[b][j]
    wl=[bay_u[j]*loads[j] for j in range(m)]; o2=max(wl)-min(wl)
    return w2*o2+w3*o3, o2, o3
v,o2,o3 = evalA(pref_assign)
print(f"all-most-preferred: val={v:.2f} obj2={o2:.2f} obj3={o3:.1f}")
