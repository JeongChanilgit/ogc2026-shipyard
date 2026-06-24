"""_levertest.py -- correctness + model-size smoke test for the new repack levers.

On prob_38's biggest bay (107 blocks, saturated), greedy start shared:
  (1) P1③ memo OUTPUT-INVARIANCE: _precompute_combos memo ON must return a
      pair_bools dict IDENTICAL to memo OFF (and identical on a 2nd cache-hit
      call).  This is the safety guarantee -- unlike the bitmask, memo must NOT
      drop/alter any constraint.
  (2) gated-OFF == production: with all new knobs off, n_stored == AABB baseline.
  (3) model-shrink levers (cap / blocker / K) reduce n_stored and are never-worse
      per bay (new_z1 <= input_z1).

env: C:/Users/peter/anaconda3/envs/ogc2025/python.exe
"""
import os, sys, json, time

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, V7)
for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1").items():
    os.environ.setdefault(k, v)
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG                                  # noqa: E402
from v3pp import adapter, crane_cpsat as C                   # noqa: E402
from v3pp.crane_cpsat import _build_candidates, _precompute_combos, _meta_RPD  # noqa
from utils import Bay                                        # noqa: E402
assert "v7" in C.__file__.replace("\\", "/"), C.__file__

BASE = "C:/claude-develop/OGC2026"
INST = int(os.environ.get("LV_INST", "38"))


def bz1(data, pl):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def clear_lever_env():
    for k in ("OGC_PP_MEMO", "OGC_PP_ACTIVE_CAP", "OGC_PP_ACTIVE_MODE", "OGC_XSMART"):
        os.environ.pop(k, None)


def main():
    print(f"# lever smoke test  prob_{INST}  {time.strftime('%H:%M')}", flush=True)
    path = f"{BASE}/instances/train/prob_{INST}.json"
    data = json.load(open(path, encoding="utf-8"))
    UG._REGREEDY_PEN = {}
    res = UG.unified(data, 70.0, path)[0]
    cur = adapter.deserialize(data, res["_solution"])
    nb, j = sorted(((len(pl), jj) for jj, pl in cur.items()), reverse=True)[0]
    placed = cur[j]
    print(f"# biggest bay {j}: {nb} blocks, input z1={bz1(data, placed):,}", flush=True)

    W = int(data["bays"][j]["width"]); H = int(data["bays"][j]["height"])
    bay = Bay.from_dict(data["bays"][j], j)
    meta = _meta_RPD(data, placed)

    # ---- (1) memo output-invariance at the precompute level ----
    clear_lever_env()
    cands, cand_shapes, tardy, active = _build_candidates(
        data, placed, meta, W, H, 5, 0, 0, False, 8.0, None, 0, 0, bay=bay, bay_id=j)
    os.environ["OGC_PP_MEMO"] = "0"
    pb0, _, _ = _precompute_combos(data, bay, placed, cands, cand_shapes, None, bay_id=j)
    os.environ["OGC_PP_MEMO"] = "1"; C._memo_reset_if_new(data)
    pb1, _, _ = _precompute_combos(data, bay, placed, cands, cand_shapes, None, bay_id=j)
    pb2, _, _ = _precompute_combos(data, bay, placed, cands, cand_shapes, None, bay_id=j)
    inv = (pb0 == pb1 == pb2)
    print(f"\n[1] MEMO OUTPUT-INVARIANCE: {'PASS' if inv else '*** FAIL ***'}  "
          f"stored off={len(pb0):,} on={len(pb1):,} hit={len(pb2):,}  "
          f"cache={len(C._BOOL_CACHE):,}", flush=True)
    clear_lever_env()

    # ---- (2)+(3) config table via full crane_repack_bay (window_tardy_only=True
    #             = production active selection) ----
    in_z1 = bz1(data, placed)
    print(f"\n[2,3] crane_repack_bay (window_tardy_only=True, n_xcand=5, ts=6s)", flush=True)
    print(f"{'config':<16} {'cands':>6} {'stored':>8} {'pre':>6} {'cpsat':>6} "
          f"{'new_z1':>10} {'dz1':>10} {'feas?':>5}", flush=True)
    configs = [
        ("prod(off)", {}),
        ("memo", {"OGC_PP_MEMO": "1"}),
        ("cap20", {"OGC_PP_ACTIVE_CAP": "20"}),
        ("cap40", {"OGC_PP_ACTIVE_CAP": "40"}),
        ("blocker", {"OGC_PP_ACTIVE_MODE": "blocker"}),
        ("blocker+cap20", {"OGC_PP_ACTIVE_MODE": "blocker", "OGC_PP_ACTIVE_CAP": "20"}),
        ("xsmart", {"OGC_XSMART": "1"}),
    ]
    ref_stored = None
    for name, env in configs:
        clear_lever_env()
        for k, v in env.items():
            os.environ[k] = v
        new_pl, st, wall, info = C.crane_repack_bay(
            data, j, placed, 6.0, n_xcand=5, window_tardy_only=True)
        if new_pl is None:
            print(f"{name:<16} (returned None, status={st})", flush=True)
            continue
        nz = bz1(data, new_pl)
        note = ""
        if name == "prod(off)":
            ref_stored = info["n_stored"]
        if name == "memo" and ref_stored is not None:
            note = "  <<< stored != prod!" if info["n_stored"] != ref_stored else "  (==prod stored)"
        worse = "" if nz <= in_z1 + 1e-9 else "  <<< WORSE!"
        print(f"{name:<16} {info['n_cands_total']:>6,} {info['n_stored']:>8,} "
              f"{info['precompute_wall']:>6.2f} {info['cpsat_wall']:>6.2f} "
              f"{nz:>10,} {nz-in_z1:>+10,} {str(st)[:5]:>5}{note}{worse}", flush=True)
    clear_lever_env()
    print("\n# DONE", flush=True)


if __name__ == "__main__":
    main()
