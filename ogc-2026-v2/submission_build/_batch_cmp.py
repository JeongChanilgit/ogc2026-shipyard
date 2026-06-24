"""_batch_cmp.py [inst ...]  -- for each instance, run BOTH starting solutions
(z3-only greedy W1=0, z1z3 greedy W1=1.0) through the dual-window v3 postproc
SEQUENTIALLY (no oversubscription), then render its comparison HTML.

Run with env python directly, in the background, AFTER any other solver run finishes.
  BATCH_TL=360  default per-start time limit.
Default instances span types: prob_13 (set1 z3-dominated), prob_14 (set1 congested),
prob_33 (set2 big).
"""
import os, sys, subprocess

SB = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def main():
    insts = sys.argv[1:] or ["13", "14", "33"]
    TL = os.environ.get("BATCH_TL", "360")
    for inst in insts:
        for scale, tag in [("0", "z3only"), ("1.0", "z1z3")]:
            env = dict(os.environ)
            env.update(OGC_PLACE_W1_SCALE=scale, OGC_PP_DUALWIN="1", OGC_PP_TMARGIN="10",
                       OGC_PP_TS_CAP="40", OGC_NO_V1="1", BRIEF_TL=TL, BRIEF_INST=inst,
                       BRIEF_OUT=f"out/brief{inst}_{tag}.json")
            print(f"\n=== prob_{inst}  start={tag} (W1={scale})  TL={TL} ===", flush=True)
            subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
        print(f"--- render prob_{inst} ---", flush=True)
        subprocess.run([PY, "_render_greedy_cmp.py", inst], env=os.environ, cwd=SB)
    print("\nBATCH DONE", flush=True)


if __name__ == "__main__":
    main()
