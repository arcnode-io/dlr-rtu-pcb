"""Clearance distance fields for the escape router (system python3 only).

One field per routable layer, plus one for the inner planes. A field holds, for every
grid point in the window, the distance to the nearest copper of *another* net. Copper
of the net being routed is deliberately absent: a router may run along its own pad and
its own traces, and treating them as obstacles is what strands a fine-pitch pin whose
only exit is straight out of its own pad.

Distances are computed analytically from the shapes (segment, circle, rectangle), not
by rasterising and dilating, so a 0.05 mm grid does not quantise a 0.15 mm clearance.
"""

from __future__ import annotations

import math

import numpy as np
import pcbnew

from cad.drawing.maze_grid import Window
from cad.drawing.pcb_util import items


def _segment_distance(gx, gy, ax, ay, bx, by, half) -> np.ndarray:
    """Distance from every grid point to a capsule of half-width `half`."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return np.hypot(gx - ax, gy - ay) - half
    t = np.clip(((gx - ax) * dx + (gy - ay) * dy) / length_sq, 0.0, 1.0)
    return np.hypot(gx - (ax + t * dx), gy - (ay + t * dy)) - half


def _rect_distance(gx, gy, cx, cy, half_w, half_h, radians) -> np.ndarray:
    """Distance from every grid point to a rotated rectangle."""
    cos_a, sin_a = math.cos(-radians), math.sin(-radians)
    px, py = gx - cx, gy - cy
    rx = np.abs(px * cos_a - py * sin_a) - half_w
    ry = np.abs(px * sin_a + py * cos_a) - half_h
    outside = np.hypot(np.maximum(rx, 0.0), np.maximum(ry, 0.0))
    return outside + np.minimum(np.maximum(rx, ry), 0.0)


def _pad_distance(gx, gy, pad: pcbnew.PAD) -> np.ndarray:
    """Distance from every grid point to a pad's copper on the layer it sits on."""
    position, size = pad.GetPosition(), pad.GetSize()
    cx, cy = pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)
    half_w, half_h = pcbnew.ToMM(size.x) / 2, pcbnew.ToMM(size.y) / 2
    radians = math.radians(pad.GetOrientationDegrees())
    if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE:
        return np.hypot(gx - cx, gy - cy) - max(half_w, half_h)
    if pad.GetShape() == pcbnew.PAD_SHAPE_OVAL:
        # Reason: a stadium is a capsule along the pad's long axis.
        radius = min(half_w, half_h)
        reach = max(half_w, half_h) - radius
        along = (math.cos(radians), math.sin(radians))
        if half_h > half_w:
            along = (-along[1], along[0])
        return _segment_distance(
            gx,
            gy,
            cx - along[0] * reach,
            cy - along[1] * reach,
            cx + along[0] * reach,
            cy + along[1] * reach,
            radius,
        )
    return _rect_distance(gx, gy, cx, cy, half_w, half_h, radians)


def _foreign_shapes(board: pcbnew.BOARD, net_code: int) -> tuple[list, list]:
    """Copper of every other net, split into (per-layer, all-layer) shape records.

    All-layer shapes are the drilled things — vias and through-hole pads — whose barrel
    sits on every copper layer including the planes.
    """
    per_layer: list[tuple[pcbnew.LSET, object]] = []
    all_layer: list[object] = []
    for track in items(board.Tracks()):
        if track.GetNetCode() == net_code:
            continue
        if track.GetClass() == "PCB_VIA":
            centre = track.GetPosition()
            all_layer.append(
                (
                    "circle",
                    pcbnew.ToMM(centre.x),
                    pcbnew.ToMM(centre.y),
                    pcbnew.ToMM(track.GetWidth()) / 2,
                )
            )
        else:
            start, end = track.GetStart(), track.GetEnd()
            per_layer.append(
                (
                    track.GetLayerSet(),
                    (
                        "segment",
                        pcbnew.ToMM(start.x),
                        pcbnew.ToMM(start.y),
                        pcbnew.ToMM(end.x),
                        pcbnew.ToMM(end.y),
                        pcbnew.ToMM(track.GetWidth()) / 2,
                    ),
                )
            )
    for footprint in items(board.Footprints()):
        for pad in items(footprint.Pads()):
            if pad.GetNetCode() == net_code:
                continue
            if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                all_layer.append(("pad", pad))
            else:
                per_layer.append((pad.GetLayerSet(), ("pad", pad)))
    return per_layer, all_layer


def _distance_to(gx, gy, shape) -> np.ndarray:
    if shape[0] == "circle":
        return np.hypot(gx - shape[1], gy - shape[2]) - shape[3]
    if shape[0] == "segment":
        return _segment_distance(gx, gy, *shape[1:])
    return _pad_distance(gx, gy, shape[1])


def clearance_fields(
    board: pcbnew.BOARD, net_code: int, window: Window, layers: tuple[int, ...]
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Per-layer and inner-plane distance-to-foreign-copper fields for a window."""
    gx, gy = window.centres()
    per_layer, all_layer = _foreign_shapes(board, net_code)
    fields = {layer: np.full(gx.shape, 1e6) for layer in layers}
    inner = np.full(gx.shape, 1e6)
    for shape in all_layer:
        distance = _distance_to(gx, gy, shape)
        inner = np.minimum(inner, distance)
        for layer in layers:
            fields[layer] = np.minimum(fields[layer], distance)
    for layer_set, shape in per_layer:
        touched = [layer for layer in layers if layer_set.Contains(layer)]
        if not touched:
            continue
        distance = _distance_to(gx, gy, shape)
        for layer in touched:
            fields[layer] = np.minimum(fields[layer], distance)
    return fields, inner


def own_copper_mask(item, window: Window, layer: int) -> np.ndarray:
    """Cells covered by one item's copper on `layer`."""
    gx, gy = window.centres()
    if isinstance(item, pcbnew.PAD):
        if not item.GetLayerSet().Contains(layer):
            return np.zeros(gx.shape, dtype=bool)
        return _pad_distance(gx, gy, item) <= 0.0
    if item.GetClass() == "PCB_VIA":
        centre = item.GetPosition()
        radius = pcbnew.ToMM(item.GetWidth()) / 2
        return (
            np.hypot(gx - pcbnew.ToMM(centre.x), gy - pcbnew.ToMM(centre.y)) <= radius
        )
    if item.GetLayer() != layer:
        return np.zeros(gx.shape, dtype=bool)
    start, end = item.GetStart(), item.GetEnd()
    distance = _segment_distance(
        gx,
        gy,
        pcbnew.ToMM(start.x),
        pcbnew.ToMM(start.y),
        pcbnew.ToMM(end.x),
        pcbnew.ToMM(end.y),
        pcbnew.ToMM(item.GetWidth()) / 2,
    )
    return distance <= 0.0
