"""_batch_cluster.py [inst ...] -- loop-test C3-CLUSTER vs no-front, 15-min postproc
on a fixed v2 start, per set2 problem.  Cluster runs at round start (shake first).
Reuses brief{i}_nofront.json if present.  Renders nofront-vs-front(cluster) A/B.
"""
import os, sys, subprocess

SB = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
V2 = os.path.dirname(SB)


def main():
    insts = sys.argv[1:] or ["38", "33", "30"]
    TL = os.environ.get("CL_TL", "900")
    base = dict(OGC_NO_V1="1", OGC_PLACE_W1_SCALE="1.0", OGC_PP_DUALWIN="1",
                OGC_PP_TMARGIN="10", OGC_PP_TS_CAP="40", OGC_PP_WRONGBAY="1",
                OGC_PP_MOVEALL="1", OGC_PP_PURET="1", OGC_PP_TOSS="1", OGC_PP_TRACE="1",
                OGC_PP_KX="16", OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80")
    clu = dict(OGC_PP_CLUSTER="1", OGC_PP_CLUSTER_MAX="6", OGC_PP_CLUSTER_TS="4",
               OGC_PP_CLUSTER_BUDGET="60")
    for inst in insts:
        cache = f"out/_v2sol_{inst}.json"
        nofront_json = os.path.join(V2, "out", f"brief{inst}_nofront.json")
        if not os.path.exists(nofront_json):
            env = dict(os.environ); env.update(base)
            env.update(OGC_PP_FRONTMOVE="0", OGC_PP_CLUSTER="0", BRIEF_INST=inst, BRIEF_TL=TL,
                       BRIEF_FIXED_START=cache, BRIEF_OUT=f"out/brief{inst}_nofront.json")
            print(f"\n=== prob_{inst} nofront TL={TL} ===", flush=True)
            subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        else:
            print(f"\n=== prob_{inst} nofront (reuse) ===", flush=True)
        env = dict(os.environ); env.update(base); env.update(clu)
        env.update(BRIEF_INST=inst, BRIEF_TL=TL, BRIEF_FIXED_START=cache,
                   BRIEF_OUT=f"out/brief{inst}_front.json")
        print(f"\n=== prob_{inst} +CLUSTER TL={TL} ===", flush=True)
        subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        subprocess.run([PY, "_render_front_ab.py", inst], env=os.environ, cwd=SB)
    print("\nCLUSTER-BATCH DONE", flush=True)


if __name__ == "__main__":
    main()
