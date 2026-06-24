"""_batch_winner.py [inst ...] -- loop-test the WINNING front methodology
(M4 = overlap select + slack dest + swap, FRONT_FIRST) vs no-front, 15-min postproc
on a fixed v2 start, per set2 problem.  Reuses existing brief{i}_nofront.json if present.
Renders nofront-vs-front A/B per problem.
"""
import os, sys, subprocess

SB = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
V2 = os.path.dirname(SB)


def main():
    insts = sys.argv[1:] or ["38", "33", "30"]
    TL = os.environ.get("WIN_TL", "900")
    base = dict(OGC_NO_V1="1", OGC_PLACE_W1_SCALE="1.0", OGC_PP_DUALWIN="1",
                OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40", OGC_PP_WRONGBAY="1",
                OGC_PP_MOVEALL="1", OGC_PP_PURET="1", OGC_PP_TOSS="1", OGC_PP_TRACE="1",
                OGC_PP_KX="16", OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80")
    winner = dict(OGC_PP_FRONTMOVE="1", OGC_PP_FRONT_FIRST="1", OGC_PP_FRONT_SEL="overlap",
                  OGC_PP_FRONT_DEST="slack", OGC_PP_FRONT_SWAP="1", OGC_PP_FRONT_K="20",
                  OGC_PP_FRONT_TS="5", OGC_PP_FRONT_BUDGET="60")
    for inst in insts:
        cache = f"out/_v2sol_{inst}.json"
        nofront_json = os.path.join(V2, "out", f"brief{inst}_nofront.json")
        # no-front baseline (reuse if present)
        if not os.path.exists(nofront_json):
            env = dict(os.environ); env.update(base)
            env.update(OGC_PP_FRONTMOVE="0", BRIEF_INST=inst, BRIEF_TL=TL,
                       BRIEF_FIXED_START=cache, BRIEF_OUT=f"out/brief{inst}_nofront.json")
            print(f"\n=== prob_{inst} nofront TL={TL} ===", flush=True)
            subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        else:
            print(f"\n=== prob_{inst} nofront (reuse existing) ===", flush=True)
        # winner front
        env = dict(os.environ); env.update(base); env.update(winner)
        env.update(BRIEF_INST=inst, BRIEF_TL=TL, BRIEF_FIXED_START=cache,
                   BRIEF_OUT=f"out/brief{inst}_front.json")
        print(f"\n=== prob_{inst} WINNER-front (M4+first) TL={TL} ===", flush=True)
        subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        subprocess.run([PY, "_render_front_ab.py", inst], env=os.environ, cwd=SB)
    print("\nWINNER-BATCH DONE", flush=True)


if __name__ == "__main__":
    main()
