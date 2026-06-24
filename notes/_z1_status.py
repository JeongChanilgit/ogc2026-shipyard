"""Report z1 (and full objective) for the latest solution of each train instance.
Read-only: uses ogc_analysis. Picks the best available saved solution per prob."""
import os, sys, glob
sys.path.insert(0, "tools")
import ogc_analysis as A

INST_DIR = "instances/train"
# candidate solution files per instance, newest-intent first
PATTERNS = ["results/_z0_prob_{n}.json", "results/_routed_prob_{n}.json",
            "results/_base_prob_{n}.json"]

print(f"{'inst':9} {'z1':>10} {'z2':>8} {'z3':>8} {'obj':>14}  src")
for n in range(1, 21):
    inst = f"{INST_DIR}/prob_{n}.json"
    if not os.path.exists(inst):
        continue
    sol_path = None
    for pat in PATTERNS:
        p = pat.format(n=n)
        if os.path.exists(p):
            sol_path = p
            break
    if sol_path is None:
        print(f"prob_{n:<4} {'(no sol)':>10}")
        continue
    try:
        prob = A.load_instance(inst)
        sol = A.load_solution(sol_path)
        feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
        tag = "" if feas else " INFEAS"
        print(f"prob_{n:<4} {o1:>10.1f} {o2:>8.1f} {o3:>8.1f} {obj:>14.1f}  "
              f"{os.path.basename(sol_path)}{tag}")
    except Exception as ex:
        print(f"prob_{n:<4}  ERR {ex}")
