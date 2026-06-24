"""Regression checks for the conservative raster geometry prefilter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def test_crane_kernel_has_no_false_clear_on_generated_suite():
    from geom_kernel import crane_path_maybe_clear, same_height_maybe_clear
    from utils import Bay, Block, check_collisions, check_entry

    inst_paths = sorted((ROOT / "instances" / "gen").glob("*.json"))
    assert inst_paths, "generated instance suite is missing"

    checked = 0
    for inst_path in inst_paths:
        prob = json.loads(inst_path.read_text(encoding="utf-8"))
        bay = Bay.from_dict(prob["bays"][0], 0)
        n = min(8, len(prob["blocks"]))

        for a in range(n):
            for b in range(n):
                if a == b:
                    continue
                target = Block(a, prob["blocks"][a], x=0, y=0, orient_idx=0)
                exist = Block(b, prob["blocks"][b], x=0, y=0, orient_idx=0)
                if not bay.contains_block(target) or not bay.contains_block(exist):
                    continue

                if crane_path_maybe_clear(bay, target, [exist]):
                    assert not check_entry(bay, [exist], target, fast=True), (
                        f"false clear in crane mask for {inst_path.name}: {a} vs {b}"
                    )

                if same_height_maybe_clear(bay, target, [exist]):
                    assert not check_collisions(bay, [target, exist]), (
                        f"false clear in collision mask for {inst_path.name}: {a} vs {b}"
                    )
                checked += 1

    assert checked > 0
