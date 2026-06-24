"""Build a submission zip from src/.

Usage:
    python tools/build_submission.py --tag v01-baseline
    python tools/build_submission.py --tag v02-lns --note "First LNS attempt"

Output:
    submissions/<tag>-<YYYYMMDD-HHMMSS>.zip
    submissions/<tag>-<YYYYMMDD-HHMMSS>-meta.json

Rules enforced (per problem statement §3.1):
  * myalgorithm.py must be at the root of the zip
  * zip size <= 15 MB
  * banned extensions removed: .dll .vb .exe
  * utils.py NOT included (evaluator overwrites it anyway)

The meta JSON records: tag, timestamp, included files, file sizes, note, and
sha256 of the zip for traceability.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "submissions"

MAX_ZIP_BYTES = 15 * 1024 * 1024  # 15 MB
BANNED_EXT = {".dll", ".vb", ".exe"}
EXCLUDED_FILES = {"utils.py", "__init__.py"}  # utils overwritten by evaluator


def _collect_files() -> list[Path]:
    files = []
    for p in sorted(SRC.rglob("*")):
        if not p.is_file():
            continue
        if p.name in EXCLUDED_FILES:
            continue
        # Never ship utils.py OR any backup copy of it (evaluator owns utils.py),
        # and skip editor/backup artifacts that would only bloat the zip.
        if (p.name.startswith("utils.py")
                or p.name.endswith("bak")
                or p.suffix.lower() in {".bak", ".orig", ".tmp", ".swp"}):
            print(f"[skip-backup] {p.relative_to(SRC)}")
            continue
        if p.suffix.lower() in BANNED_EXT:
            print(f"[skip-banned] {p.relative_to(SRC)}")
            continue
        if "__pycache__" in p.parts or ".pytest_cache" in p.parts or p.suffix == ".pyc":
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="Build OGC 2026 submission zip.")
    ap.add_argument("--tag", required=True, help="Short version tag (e.g. v02-lns)")
    ap.add_argument("--note", default="", help="Free-form note saved in meta")
    args = ap.parse_args()

    if not (SRC / "myalgorithm.py").exists():
        print(f"[error] {SRC / 'myalgorithm.py'} not found.")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_name = f"{args.tag}-{ts}.zip"
    zip_path = OUT / zip_name

    files = _collect_files()
    if not files:
        print("[error] no files to include")
        return 2

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in files:
            arcname = f.relative_to(SRC).as_posix()
            zf.write(f, arcname=arcname)
            print(f"  + {arcname}  ({f.stat().st_size:,} B)")

    size = zip_path.stat().st_size
    if size > MAX_ZIP_BYTES:
        print(f"[error] zip too large: {size:,} B > {MAX_ZIP_BYTES:,} B (15 MB).")
        print("        Reduce contents or compress better.")
        zip_path.unlink()
        return 3

    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    meta = {
        "tag": args.tag,
        "timestamp_kst": ts,
        "zip_filename": zip_name,
        "zip_size_bytes": size,
        "zip_sha256": sha,
        "files": [
            {"path": f.relative_to(SRC).as_posix(),
             "bytes": f.stat().st_size}
            for f in files
        ],
        "note": args.note,
    }
    meta_path = zip_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"  zip   : {zip_path.relative_to(ROOT)}")
    print(f"  meta  : {meta_path.relative_to(ROOT)}")
    print(f"  size  : {size:,} B  ({size / 1024 / 1024:.2f} MB / 15 MB limit)")
    print(f"  sha256: {sha[:16]}...")
    print()
    print("  Next: email this zip to submission@optichallenge.com from your registered address.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
