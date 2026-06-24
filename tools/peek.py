#!/usr/bin/env python3
"""peek.py — 큰 파일을 Read 로 통째로 빨아들이지 않고 '싸게 요약만' 뽑는 인스펙터.

OGC2026 작업공간에서 토큰을 가장 많이 잡아먹는 파일은:
  - instances/**/*.json  (1~3 MB, prob_14 = 3.2 MB ≈ 80만 토큰)
  - results/**/*.html    (0.3~1.7 MB)
  - docs/*.pdf           (2.4 MB)
이 파일들을 Read 하지 말고 이 스크립트로 핵심 수치만 출력하라.

사용법:
  python tools/peek.py instances/train/prob_5.json     # 인스턴스 요약
  python tools/peek.py results/<dir>/sol_prob_10.json  # 솔루션 요약
  python tools/peek.py results/compare_xxx/            # 폴더의 작은 요약파일 목록
  python tools/peek.py some_big.json --keys            # 임의 JSON 의 top-level 스키마
  python tools/peek.py some.json --path bays.0         # 특정 경로만 들여다보기
"""
from __future__ import annotations
import json
import os
import sys


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def _stats(nums):
    nums = [x for x in nums if isinstance(x, (int, float))]
    if not nums:
        return "n/a"
    return f"min={min(nums)} max={max(nums)} mean={sum(nums)/len(nums):.1f}"


def summarize_instance(d: dict) -> None:
    print(f"name     : {d.get('name')}")
    bays = d.get("bays", [])
    blocks = d.get("blocks", [])
    print(f"bays     : {len(bays)}")
    for i, b in enumerate(bays):
        if isinstance(b, dict):
            dims = {k: b[k] for k in b if k in ("width", "height", "W", "H", "u", "weight")}
            print(f"  bay[{i}] keys={list(b.keys())} {dims}")
        if i >= 4:
            print(f"  ... (+{len(bays)-5} more)")
            break
    print(f"blocks   : {len(blocks)}")
    if blocks and isinstance(blocks[0], dict):
        print(f"  block keys: {list(blocks[0].keys())}")
        for key in ("release_time", "due_date", "processing_time", "workload"):
            vals = [bk.get(key) for bk in blocks if isinstance(bk, dict) and key in bk]
            if vals:
                print(f"  {key:10s}: {_stats(vals)}")
    print(f"weights  : {d.get('weights')}")


def summarize_solution(d: dict) -> None:
    ops = d.get("operations", {})
    if isinstance(ops, dict):
        total = sum(len(v) for v in ops.values() if isinstance(v, list))
        print(f"operations: {len(ops)} time-keys, {total} ops total")
        times = sorted(ops.keys(), key=lambda s: (len(s), s))
        print(f"  time range: {times[0] if times else 'n/a'} to {times[-1] if times else 'n/a'}")
    else:
        print(f"operations: {type(ops).__name__}")
    for k, v in d.items():
        if k != "operations":
            print(f"  {k}: {repr(v)[:80]}")


def schema(d, prefix="") -> None:
    if isinstance(d, dict):
        for k, v in d.items():
            kind = type(v).__name__
            extra = f" len={len(v)}" if isinstance(v, (list, dict, str)) else f" = {v!r}"
            print(f"{prefix}{k}: {kind}{extra}")
    elif isinstance(d, list):
        print(f"{prefix}list len={len(d)}; item0={type(d[0]).__name__ if d else 'n/a'}")
    else:
        print(f"{prefix}{type(d).__name__} = {d!r}")


def dig(d, path: str):
    for part in path.split("."):
        if isinstance(d, list):
            d = d[int(part)]
        elif isinstance(d, dict):
            d = d[part]
        else:
            return d
    return d


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    target = args[0]

    if os.path.isdir(target):
        print(f"DIR {target} - small summary files (< 50 KB, read these not the .html):")
        for fn in sorted(os.listdir(target)):
            fp = os.path.join(target, fn)
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                mark = "  READ-OK" if sz < 50_000 else "  ** BIG - peek/extract, do NOT Read **"
                print(f"  {_fmt_bytes(sz):>8}  {fn}{mark}")
        return 0

    if not os.path.isfile(target):
        print(f"not found: {target}")
        return 1

    sz = os.path.getsize(target)
    print(f"# {target}  ({_fmt_bytes(sz)})")
    if sz < 8000 and target.endswith(".json"):
        print("  (file is small — safe to Read directly; dumping anyway)")

    if not target.endswith(".json"):
        print(f"  non-JSON. {_fmt_bytes(sz)}. If .html/.pdf: do NOT Read; "
              f"read the sibling report.md / use Read pages= for PDF.")
        return 0

    with open(target, encoding="utf-8") as f:
        d = json.load(f)

    path_flag = next((f.split("=", 1)[1] for f in flags if f.startswith("--path=")), None)
    if "--path" in flags and not path_flag and len(args) > 1:
        path_flag = args[1]
    if path_flag:
        schema(dig(d, path_flag), prefix=f"{path_flag}.")
        return 0
    if "--keys" in flags:
        schema(d)
        return 0

    if isinstance(d, dict) and "blocks" in d and "bays" in d:
        summarize_instance(d)
    elif isinstance(d, dict) and "operations" in d:
        summarize_solution(d)
    else:
        schema(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
