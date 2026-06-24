"""Pre-process stage_trace JSONs into ONE report_data.json for the HTML report.

Output: results/stage_trace/report_data.json
{
  "tl": 100, "stage_order": [...],
  "instances": {
    "prob_1": {"n_blocks":N,"n_bays":B,"weights":{"w1":..,"w2":..,"w3":..},
      "default": {"final":{z1,z2,z3,obj,wall,feas},
                  "traj":[{"stage","z1","z2","z3","obj","t"}...],   # floor + adopted stages
                  "timing":{stage:sec,...}, "total_s":..},
      "raster": {...}}, ...}
}
The sequence axis = traj order; the time axis (t) = cumulative wall-time best-effort.
"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")
ST = os.path.join(ROOT, "results", "stage_trace")

# canonical pipeline order (obj-stage names) + timing-name mapping
ORDER = ["floor", "search", "cpsat_seed", "seeds_decode", "cum_level",
         "cpsat_timing", "bbox_pack", "bbox_pack_slab", "crossbay_relocate",
         "bbox_pack2", "cheaper_steps", "reschedule", "fb_relocate", "fb_swap"]
# obj-stage -> timing-stage (for cumulative wall-time)
TMAP = {"floor": "baseline", "cum_level": "cum_level", "cpsat_timing": "cpsat_timing",
        "bbox_pack": "bbox_pack", "bbox_pack_slab": "bbox_pack",
        "crossbay_relocate": "crossbay_relocate", "bbox_pack2": "bbox_pack2",
        "cheaper_steps": "cheaper_steps", "reschedule": "cheaper_steps",
        "search": "search", "cpsat_seed": "cpsat_seed", "seeds_decode": "seeds_decode"}


def cfg_record(rec):
    so = (rec.get("stage_obj") or {}).get("stages", {}) or {}
    st = (rec.get("stage_timing") or {}).get("stages", {}) or {}
    total_s = (rec.get("stage_timing") or {}).get("total_s", 0.0)
    fin = rec.get("final") or {}
    # floor point from _postproc_base
    base = so.get("_postproc_base", {})
    traj = []
    if base:
        traj.append({"stage": "floor", "z1": base.get("obj1"), "z2": base.get("obj2"),
                     "z3": base.get("obj3"), "obj": base.get("obj")})
    for name in ORDER:
        if name == "floor":
            continue
        e = so.get(name)
        if not e:
            continue
        traj.append({"stage": name, "z1": e.get("z1"), "z2": e.get("z2"),
                     "z3": e.get("z3"), "obj": e.get("after")})
    # cumulative wall-time per traj point (best-effort)
    cum = 0.0
    seen_t = set()
    for p in traj:
        tname = TMAP.get(p["stage"])
        if tname and tname not in seen_t:
            cum += float(st.get(tname, 0.0) or 0.0)
            seen_t.add(tname)
        # fb_* / reschedule after timed stages -> push toward end
        if p["stage"] in ("fb_relocate", "fb_swap"):
            cum = max(cum, total_s)
        p["t"] = round(cum, 2)
    return {"final": fin, "traj": traj,
            "timing": {k: round(float(v), 3) for k, v in st.items() if v},
            "total_s": round(total_s, 2)}


def main():
    out = {"tl": 100, "stage_order": ORDER, "instances": {}}
    for i in range(1, 21):
        name = f"prob_{i}"
        prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
        w = prob.get("weights", {})
        rec = {"n_blocks": len(prob.get("blocks", [])),
               "n_bays": len(prob.get("bays", [])),
               "weights": {"w1": w.get("w1"), "w2": w.get("w2"), "w3": w.get("w3")}}
        for tag in ("default", "raster"):
            p = os.path.join(ST, tag, name + ".json")
            if os.path.exists(p):
                rec[tag] = cfg_record(json.load(open(p)))
        out["instances"][name] = rec
    dst = os.path.join(ST, "report_data.json")
    json.dump(out, open(dst, "w"))
    print("wrote", dst)
    # quick sanity print
    for name in ("prob_1", "prob_20"):
        r = out["instances"][name]
        for tag in ("default", "raster"):
            t = r[tag]
            print(f"  {name} {tag}: stages={[p['stage'] for p in t['traj']]} "
                  f"final_z1={t['final'].get('z1')}")


if __name__ == "__main__":
    main()
