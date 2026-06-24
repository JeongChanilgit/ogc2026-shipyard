"""Raster geometry prefilter for crane-path checks.

This module is deliberately conservative.  It can prove that no obstruction is
possible by rasterising layer bounding boxes and applying the j >= k suffix
rule, but it never declares a placement infeasible.  Callers must fall back to
the exact Shapely-based checks when the raster mask reports a possible overlap.
"""

from __future__ import annotations

import math

import numpy as np


def _bbox_of_layer(layer) -> tuple[float, float, float, float] | None:
    if not layer:
        return None
    xs = [p[0] for p in layer]
    ys = [p[1] for p in layer]
    return min(xs), min(ys), max(xs), max(ys)


def _rect_slice(bb, width: int, height: int):
    """Return array slices covering bb, or None if the strict bbox is empty."""
    x0, y0, x1, y1 = bb
    if not (x0 < x1 and y0 < y1):
        return None
    ix0 = max(0, int(math.floor(x0)))
    iy0 = max(0, int(math.floor(y0)))
    ix1 = min(width, int(math.ceil(x1)))
    iy1 = min(height, int(math.ceil(y1)))
    if ix0 >= ix1 or iy0 >= iy1:
        return None
    return slice(iy0, iy1), slice(ix0, ix1)


def _bbox_inside_bay(bb, width: int, height: int) -> bool:
    return bb[0] >= 0 and bb[1] >= 0 and bb[2] <= width and bb[3] <= height


class CraneMask:
    """Suffix-OR mask for the crane-path rule.

    `layer_masks[j]` stores the occupied bbox cells of existing blocks at layer j.
    `suffix_masks[k]` stores the OR of all existing layers j >= k.
    """

    def __init__(self, bay, blocks=(), *, suffix: bool = True):
        self.width = int(bay.width)
        self.height = int(bay.height)
        max_layers = 0
        block_layers = []
        for block in blocks:
            layers = block.layers_at_pos()
            block_layers.append((block, layers))
            max_layers = max(max_layers, len(layers))
        self.layer_masks = [
            np.zeros((self.height, self.width), dtype=bool)
            for _ in range(max_layers)
        ]
        for _block, layers in block_layers:
            for idx, layer in enumerate(layers):
                bb = _bbox_of_layer(layer)
                if bb is None:
                    continue
                sl = _rect_slice(bb, self.width, self.height)
                if sl is not None:
                    self.layer_masks[idx][sl] = True
        self.suffix_masks = self._build_suffix() if suffix else self.layer_masks

    def _build_suffix(self):
        if not self.layer_masks:
            return []
        suffix = [None] * len(self.layer_masks)
        running = np.zeros((self.height, self.width), dtype=bool)
        for idx in range(len(self.layer_masks) - 1, -1, -1):
            running = np.logical_or(running, self.layer_masks[idx])
            suffix[idx] = running.copy()
        return suffix

    def clear_for(self, block, *, same_height: bool = False) -> bool:
        """True means the raster bbox mask proves no overlap is possible."""
        layers = block.layers_at_pos()
        for k, layer in enumerate(layers):
            bb = _bbox_of_layer(layer)
            if bb is None:
                continue
            if not _bbox_inside_bay(bb, self.width, self.height):
                return False
            masks = self.layer_masks if same_height else self.suffix_masks
            if k >= len(masks):
                continue
            sl = _rect_slice(bb, self.width, self.height)
            if sl is not None and np.any(masks[k][sl]):
                return False
        return True


def crane_path_maybe_clear(bay, target_block, existing_blocks) -> bool:
    """Conservative prefilter for check_entry/check_exit.

    Returns True only when the suffix-OR bbox mask proves that no j >= k
    obstruction can exist.  False means "run the exact check".
    """
    blockers = [b for b in existing_blocks if b.block_id != target_block.block_id]
    if not blockers:
        return True
    return CraneMask(bay, blockers, suffix=True).clear_for(target_block)


def same_height_maybe_clear(bay, target_block, existing_blocks) -> bool:
    """Conservative prefilter for same-height spatial collision checks."""
    blockers = [b for b in existing_blocks if b.block_id != target_block.block_id]
    if not blockers:
        return True
    return CraneMask(bay, blockers, suffix=False).clear_for(
        target_block, same_height=True
    )
