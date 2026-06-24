"""_rebuild_zip.py [TAG] -- rebuild the submission zip from v7/, preserving the
EXACT entry structure of the last submitted zip (34 root .py + v3pp/9) so only the
v7 code edits (adopted lever gate + myalgorithm setdefault) change.  Excludes all
experiment harness files / __pycache__ / .html by construction (we copy ONLY the
43 entries that were in the reference zip).

Validates the rebuilt zip standalone (extract to a temp dir, import myalgorithm,
run prob_21 + prob_38 to feasibility) before declaring success.
"""
import os, sys, zipfile, json, time, shutil, subprocess

THIS = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(THIS, "v7")
REF = "C:/claude-develop/OGC2026/submissions/v-fullset-moveall-aabb-2026-06-24-204401.zip"
TAG = sys.argv[1] if len(sys.argv) > 1 else "cap-adopted"
OUT = f"C:/claude-develop/OGC2026/submissions/v-{TAG}-2026-06-25.zip"


def main():
    ref_names = zipfile.ZipFile(REF).namelist()
    files = [n for n in ref_names if not n.endswith("/")]
    missing = [n for n in files if not os.path.exists(os.path.join(V7, n))]
    if missing:
        print(f"MISSING in v7: {missing}"); sys.exit(1)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for n in files:
            z.write(os.path.join(V7, n), n)
    size = os.path.getsize(OUT)
    print(f"built {OUT}  ({size/1e6:.2f} MB, {len(files)} entries)")
    assert size < 15e6, "zip > 15MB!"
    # myalgorithm sanity: confirm the adopted gate is present
    ma = zipfile.ZipFile(OUT).read("myalgorithm.py").decode()
    for knob in ("OGC_PP_MOVEALL", "OGC_PRECOMP_AABB"):
        assert knob in ma, f"{knob} missing from zipped myalgorithm!"
    print("  zipped myalgorithm setdefaults:",
          [l.split('"')[1] for l in ma.splitlines() if "setdefault" in l and "OGC" in l])
    # standalone validation: extract to clean dir, run 2 instances
    tmp = os.path.join(THIS, "_rebuild_check")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    zipfile.ZipFile(OUT).extractall(tmp)
    runner = os.path.join(tmp, "_chk.py")
    with open(runner, "w") as f:
        f.write(
            "import sys,os,json,time\n"
            "sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))\n"
            "import myalgorithm,utils\n"
            "B='C:/claude-develop/OGC2026/instances/train'\n"
            "if __name__=='__main__':\n"
            "  for i in (21,38):\n"
            "    d=json.load(open(f'{B}/prob_{i}.json'));t=time.time()\n"
            "    s=myalgorithm.algorithm(d,60);r=utils.check_feasibility(d,s)\n"
            "    print(f'prob_{i}: obj={r.get(\"objective\")} feas={r.get(\"objective\") is not None} wall={time.time()-t:.0f}s')\n")
    print("  standalone check (prob_21, prob_38 @60s):", flush=True)
    r = subprocess.run([sys.executable, runner], cwd=tmp, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr[-1500:]); sys.exit(1)
    print(f"DONE -> {OUT}")


if __name__ == "__main__":
    main()
