import sys, json
inst, tl, cfg = sys.argv[1], sys.argv[2], sys.argv[3]
line = sys.stdin.read().strip().splitlines()
line = line[-1] if line else ""
try:
    d = json.loads(line)
    print(f"{inst}\t{tl}\t{cfg}\t{d.get('feasible')}\t{d.get('obj1')}\t{d.get('obj2')}\t{d.get('obj3')}\t{d.get('elapsed')}")
except Exception as e:
    print(f"{inst}\t{tl}\t{cfg}\tPARSE_ERR\t{repr(e)}\t-\t-\t-")
