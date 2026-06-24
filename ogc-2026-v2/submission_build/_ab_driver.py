
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import myalgorithm, utils
inst, tl = sys.argv[1], float(sys.argv[2])
prob = json.load(open(inst, encoding="utf-8"))
t0 = time.time()
sol = myalgorithm.algorithm(prob, tl)
wall = time.time() - t0
r = utils.check_feasibility(prob, sol)
ok = isinstance(r, dict)
print("RESULT " + json.dumps({
    "obj": r.get("objective") if ok else None,
    "z1": r.get("obj1") if ok else None, "z2": r.get("obj2") if ok else None,
    "z3": r.get("obj3") if ok else None, "stage": r.get("stage") if ok else None,
    "wall": round(wall, 1)}), flush=True)
