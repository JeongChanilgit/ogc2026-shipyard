"""_batch_front.py [inst ...]  -- frontmove A/B in the LOOP structure, same fixed
v2 start, 15-min postproc each.  For each instance: run no-front then +frontmove,
then render the A/B HTML.  Run with env python in the background.

  FRONT_AB_TL  default 900 (per run, postproc-only on the fixed start).
Default instances: 38, 33 (set2 -- where tardy/z1 lives, frontmove relevant).
"""
import os, sys, subprocess

SB = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def main():
    insts = sys.argv[1:] or ["38", "33"]
    TL = os.environ.get("FRONT_AB_TL", "900")
    base = dict(OGC_NO_V1="1", OGC_PLACE_W1_SCALE="1.0", OGC_PP_DUALWIN="1",
                OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40", OGC_PP_WRONGBAY="1",
                OGC_PP_MOVEALL="1", OGC_PP_PURET="1", OGC_PP_TOSS="1", OGC_PP_TRACE="1",
                OGC_PP_KX="16", OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80")
    for inst in insts:
        cache = f"out/_v2sol_{inst}.json"
        for tag, fm in [("nofront", "0"), ("front", "1")]:
            env = dict(os.environ); env.update(base)
            env.update(OGC_PP_FRONTMOVE=fm, BRIEF_INST=inst, BRIEF_TL=TL,
                       BRIEF_FIXED_START=cache, BRIEF_OUT=f"out/brief{inst}_{tag}.json")
            if fm == "1":
                env.update(OGC_PP_FRONT_K="16", OGC_PP_FRONT_TS="4", OGC_PP_FRONT_BUDGET="50")
            print(f"\n=== prob_{inst} {tag} (frontmove={fm}) TL={TL} ===", flush=True)
            subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        subprocess.run([PY, "_render_front_ab.py", inst], env=os.environ, cwd=SB)
    print("\nFRONT-AB DONE", flush=True)


if __name__ == "__main__":
    main()
