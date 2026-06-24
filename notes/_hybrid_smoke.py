import sys, os, json, time


def main():
    sys.path.insert(0, 'src')
    import myalgorithm
    from utils import check_feasibility
    inst = sys.argv[1] if len(sys.argv) > 1 else 'prob_26'
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 220.0
    with open(f'instances/train/{inst}.json') as f:
        prob = json.load(f)
    t0 = time.monotonic()
    sol = myalgorithm.algorithm(prob, tl)
    wall = time.monotonic() - t0
    with open(f'instances/train/{inst}.json') as f:
        probc = json.load(f)
    if sol is None:
        print(f'RESULT {inst}: SOL=None wall={wall:.1f}')
    else:
        fc = check_feasibility(probc, sol)
        print(f'RESULT {inst}: feasible={fc.get("feasible")} '
              f'obj={fc.get("objective"):,.0f} z1={fc.get("obj1")} '
              f'z2={fc.get("obj2")} z3={fc.get("obj3")} '
              f'wall={wall:.1f}s TL={tl}')


if __name__ == "__main__":
    main()
