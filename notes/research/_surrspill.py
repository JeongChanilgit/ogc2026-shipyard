"""H9/H12: surrogate-guided minimal spill. A CHEAP 1-machine (single-crane) total-
tardiness surrogate per bay identifies which blocks overload a bay; spill the cheapest-z3
of those to alternative bays at several aggressiveness LEVELS. Each level => a candidate
assignment; box packs it with its REAL packer (boxdecomp) — so the surrogate is only a
generator (no eval-cost in the loop), accuracy comes from box's pack. Compares each level's
packed obj to box-default and competitor.

Usage: python notes/research/_surrspill.py <inst> [pack_tl]
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["OGC_BOXDECOMP"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as B  # noqa
from utils import Bay, Block, check_feasibility  # noqa

COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]


def one_machine_tardy(ids, blocks):
    """EDD single-machine total tardiness surrogate: sort by due, process serially from
    max(release, prev_finish). Returns (total_tardy, per_block_tardy dict)."""
    order = sorted(ids, key=lambda b: (blocks[b]["due_date"], blocks[b]["release_time"]))
    t = 0.0
    tot = 0.0
    perb = {}
    for b in order:
        t = max(t, blocks[b]["release_time"]) + blocks[b]["processing_time"]
        td = max(0.0, t - blocks[b]["due_date"])
        perb[b] = td
        tot += td
    return tot, perb


def fits_of(blocks, bays, b, nb):
    fb = []
    for j in range(nb):
        for oi in range(len(blocks[b].get("shape", []))):
            try:
                if bays[j].contains_block(Block(b, blocks[b], 0, 0, oi)):
                    fb.append(j)
                    break
            except Exception:
                pass
    return fb or list(range(nb))


def build_assignment(blocks, bays, nb, prefs, fits, level):
    """preferred, then spill the `level` fraction of each bay's surrogate-tardy blocks
    (cheapest-z3 first) to their next-preferred feasible under-loaded bay."""
    members = [set() for _ in range(nb)]
    bayof = [0] * len(blocks)
    for b in range(len(blocks)):
        j = max(fits[b], key=lambda k: prefs[b][k])
        members[j].add(b)
        bayof[b] = j
    for _ in range(6):  # a few spill rounds
        moved = 0
        sload = [one_machine_tardy(members[j], blocks)[0] for j in range(nb)]
        for j in range(nb):
            tot, perb = one_machine_tardy(members[j], blocks)
            if tot <= 1e-9:
                continue
            # tardy blocks, cheapest-z3 first (smallest pref-dev loss), then most tardy
            tardy = [b for b in members[j] if perb[b] > 0]
            tardy.sort(key=lambda b: (prefs[b][j] - max((prefs[b][k] for k in fits[b] if k != j), default=prefs[b][j]),
                                      -perb[b]))
            k = max(1, int(len(tardy) * level))
            for b in tardy[:k]:
                alts = [j2 for j2 in fits[b] if j2 != j]
                if not alts:
                    continue
                # destination: feasible bay with lowest surrogate load, prefer higher pref
                j2 = min(alts, key=lambda x: (sload[x], -(prefs[b][x])))
                members[j].discard(b)
                members[j2].add(b)
                bayof[b] = j2
                sload[j2] += blocks[b]["processing_time"]
                moved += 1
        if moved == 0:
            break
    return members


def run(inst, pack_tl=12.0):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
    blocks = prob["blocks"]
    n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    B._winit(prob)
    prefs = [blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)]
    fits = [fits_of(blocks, bays, b, nb) for b in range(n)]
    c = COMP[inst]
    print(f"{inst}: comp z1={c['z1']:.0f} z3={c['z3']:.0f} obj={c['obj']:,.0f}")
    for level in [0.15, 0.3, 0.5, 0.8]:
        mem = build_assignment(blocks, bays, nb, prefs, fits, level)
        try:
            r = B._pack_members(mem, bays, blocks, n, prob,
                                time.monotonic() + pack_tl, "boxdecomp")
        except Exception as e:
            print(f"  level={level}: ERR {e}")
            continue
        if r is None:
            print(f"  level={level}: pack None")
            continue
        obj, sol = r
        ck = check_feasibility(prob, sol)
        beat = (ck.get("obj1", 9e9) <= c["z1"] and ck.get("obj3", 9e9) < c["z3"])
        print(f"  level={level:<4} z1={ck.get('obj1'):>7.0f} z3={ck.get('obj3'):>6.0f} "
              f"obj={ck.get('objective'):>13,.0f} "
              f"{'*** BEAT z1&z3 ***' if beat else ('obj<comp' if ck.get('objective', 9e18) < c['obj'] else '')}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "prob_29",
        float(sys.argv[2]) if len(sys.argv) > 2 else 12.0)
