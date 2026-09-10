"""Grid A* for the escape router: the search itself and the geometry it emits."""

from __future__ import annotations

import math
from heapq import heappop, heappush
from itertools import pairwise
from typing import Final

import numpy as np
import pcbnew
from scipy.ndimage import distance_transform_edt, label

from cad.drawing.maze_grid import Window
from cad.drawing.pcb_util import make_track, make_via

LAYERS: Final = (pcbnew.F_Cu, pcbnew.B_Cu)
# Reason: a layer change costs a via and its two annular rings; price it like 2 mm of
# trace so the search only takes one when going around really is longer.
VIA_COST_CELLS: Final = 40.0
STEPS: Final = tuple(
    (dr, dc, math.hypot(dr, dc))
    for dr in (-1, 0, 1)
    for dc in (-1, 0, 1)
    if (dr, dc) != (0, 0)
)


def _reachable(passable, via_ok, start, goal) -> bool:
    """Cheap necessary condition: is any goal cell in the start's free-space region?

    Labels each layer's passable mask, then joins the two layers wherever a via could
    be dropped. When the start's group holds no goal cell there is no path at all, and
    the A* would otherwise pay for exhausting the whole window to find that out.
    """
    blobs = {
        layer: label(passable[layer], structure=np.ones((3, 3), dtype=int))[0]
        for layer in LAYERS
    }
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find(node):
        while parent.setdefault(node, node) != node:
            parent[node] = node = parent[parent[node]]
        return node

    front, back = blobs[LAYERS[0]], blobs[LAYERS[1]]
    crossing = via_ok & (front > 0) & (back > 0)
    pairs = zip(front[crossing].tolist(), back[crossing].tolist(), strict=True)
    for a, b in set(pairs):
        root_a, root_b = find((0, a)), find((1, b))
        if root_a != root_b:
            parent[root_a] = root_b
    tag = int(blobs[LAYERS[start[0]]][start[1], start[2]])
    if tag == 0:
        return False
    home = find((start[0], tag))
    for index, layer in enumerate(LAYERS):
        touched = goal[layer] & (blobs[layer] > 0)
        if any(find((index, int(t))) == home for t in np.unique(blobs[layer][touched])):
            return True
    return False


def search(window, passable, diagonal, via_ok, start, goal):
    """A* over (layer index, row, col). Returns the cell path, or None.

    `passable` is the mask for a straight step, `diagonal` the stricter one for a 45
    degree step, which sweeps further from both grid points it joins.
    """
    if not _reachable(passable, via_ok, start, goal):
        return None
    heuristic = distance_transform_edt(~np.logical_or.reduce(list(goal.values())))
    cost = np.full((len(LAYERS), window.ny, window.nx), np.inf)
    parent = np.full((len(LAYERS), window.ny, window.nx, 3), -1, dtype=np.int32)
    cost[start] = 0.0
    queue = [(heuristic[start[1], start[2]], start)]
    while queue:
        _, node = heappop(queue)
        layer, row, col = node
        if goal[LAYERS[layer]][row, col] and node != start:
            path, cursor = [node], node
            while parent[cursor][0] >= 0:
                cursor = tuple(int(v) for v in parent[cursor])
                path.append(cursor)
            return path[::-1]
        here = cost[node]
        for neighbour, step in _neighbours(window, passable, diagonal, via_ok, node):
            if here + step < cost[neighbour]:
                cost[neighbour] = here + step
                parent[neighbour] = node
                heappush(
                    queue,
                    (
                        cost[neighbour] + heuristic[neighbour[1], neighbour[2]],
                        neighbour,
                    ),
                )
    return None


def _neighbours(window, passable, diagonal, via_ok, node):
    """Every cell reachable in one move from `node`, with what the move costs."""
    layer, row, col = node
    if via_ok[row, col]:
        for other in range(len(LAYERS)):
            if other != layer:
                yield (other, row, col), VIA_COST_CELLS
    for d_row, d_col, step in STEPS:
        next_row, next_col = row + d_row, col + d_col
        if not (0 <= next_row < window.ny and 0 <= next_col < window.nx):
            continue
        mask = diagonal if d_row and d_col else passable
        if mask[LAYERS[layer]][next_row, next_col] and mask[LAYERS[layer]][row, col]:
            yield (layer, next_row, next_col), step


def corners_of(window: Window, path: list[tuple[int, int, int]]) -> list[tuple]:
    """Collapse the cell path into (layer, x, y) corners at every turn or via."""
    keep = [path[0]]
    for index in range(1, len(path) - 1):
        previous, node, following = path[index - 1], path[index], path[index + 1]
        turned = (node[1] - previous[1], node[2] - previous[2]) != (
            following[1] - node[1],
            following[2] - node[2],
        )
        if turned or node[0] != previous[0] or node[0] != following[0]:
            keep.append(node)
    keep.append(path[-1])
    return [(LAYERS[layer], *window.point_of(row, col)) for layer, row, col in keep]


def draw(board, net, width_mm, corners, start_anchor) -> list:
    """Turn corners into tracks and vias, meeting the source pad exactly."""
    corners[0] = (corners[0][0], *start_anchor)
    added = []
    for (layer, x, y), (next_layer, next_x, next_y) in pairwise(corners):
        point = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
        next_point = pcbnew.VECTOR2I(pcbnew.FromMM(next_x), pcbnew.FromMM(next_y))
        if layer != next_layer:
            added.append(make_via(board, point, net))
        elif point != next_point:
            added.append(make_track(board, point, next_point, layer, net, width_mm))
    for item in added:
        board.Add(item)
    return added
