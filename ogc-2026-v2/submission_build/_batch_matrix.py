"""_batch_matrix.py  -- run the OPEN-question config matrix on a fixed v2 start,
15-min postproc each: frontmove ordering (none/last/first) x window (dual/single).
Reuses brief{i}_nofront.json (no-front dual) + brief{i}_front.json (front-LAST dual);
runs the 3 NEW configs; then renders the matrix.
"""
import os, sys, subprocess

SB = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

CONFIGS = [
    ("c3_ffdual",         {"OGC_PP_DUALWIN": "1", "OGC_PP_FRONTMOVE": "1", "OGC_PP_FRONT_FIRST": "1"}),
    ("c4_nofront_single", {"OGC_PP_DUALWIN": "0", "OGC_PP_FRONTMOVE": "0"}),
    ("c5_ffsingle",       {"OGC_PP_DUALWIN": "0", "OGC_PP_FRONTMOVE": "1", "OGC_PP_FRONT_FIRST": "1"}),
]


def main():
    inst = os.environ.get("MATRIX_INST", "38")
    TL = os.environ.get("MATRIX_TL", "900")
    base = dict(OGC_NO_V1="1", OGC_PLACE_W1_SCALE="1.0", OGC_PP_TMARGIN="10",
                OGC_PP_TS_CAP="40", OGC_PP_WRONGBAY="1", OGC_PP_MOVEALL="1",
                OGC_PP_PURET="1", OGC_PP_TOSS="1", OGC_PP_TRACE="1", OGC_PP_KX="16",
                OGC_PP_FREEALL="1", OGC_PP_FREEALL_MAX="80",
                OGC_PP_FRONT_K="16", OGC_PP_FRONT_TS="4", OGC_PP_FRONT_BUDGET="50")
    cache = f"out/_v2sol_{inst}.json"
    for tag, extra in CONFIGS:
        env = dict(os.environ); env.update(base); env.update(extra)
        env.update(BRIEF_INST=inst, BRIEF_TL=TL, BRIEF_FIXED_START=cache,
                   BRIEF_OUT=f"out/brief{inst}_{tag}.json")
        print(f"\n=== {tag} {extra} TL={TL} ===", flush=True)
        subprocess.run([PY, "-u", "_brief38.py"], env=env, cwd=SB)
    subprocess.run([PY, "_render_matrix.py", inst], env=os.environ, cwd=SB)
    print("\nMATRIX DONE", flush=True)


if __name__ == "__main__":
    main()
