"""A* escape router for the connections Freerouting and close_gaps could not finish.

Freerouting leaves the fine-pitch parts (0.4 mm DF40, 0.5 mm MSOP / VQFN) with a few
pins whose only exit is straight out of the pad and then around several obstacles.
close_gaps only draws L-shapes, so it cannot express those. This searches a real grid.

Three rules make it behave where the earlier attempt did not:

  * Only copper of *other* nets is an obstacle. A pin may leave through its own pad.
  * Clearance comes from an analytic distance field (see maze_field), and every cell
    must hold clearance + half the trace + the worst interpolation error of one step,
    so a path that passes the grid test also passes DRC.
  * Every route is checked against KiCad's own connectivity before it is kept. A path
    that does not actually join the two islands is torn out again, so the board never
    collects the stubs and dangling vias of a router that only thinks it succeeded.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import pcbnew

from cad.drawing.maze_field import clearance_fields, own_copper_mask
from cad.drawing.maze_grid import GRID_MM, Window, window_around
from cad.drawing.maze_search import LAYERS, corners_of, draw, search
from cad.drawing.pcb_util import CLEARANCE_MM, VIA_DIAMETER_MM, items, make_via

WIDTHS_MM: Final = (0.25, 0.2)
MARGIN_MM: Final = 7.0
CELL_BUDGET: Final = 400_000
# Reason: the distance field is 1-Lipschitz, so between two grid points the clearance
# can dip by half the step length. A straight step is one cell, a 45 degree step is a
# cell diagonal, so the two need different margins; using the larger one everywhere
# throws away 11 um of room, which is the whole budget at a 0.4 mm-pitch pad.
AXIS_SAFETY_MM: Final = GRID_MM / 2 + 1e-4
DIAG_SAFETY_MM: Final = GRID_MM * math.sqrt(2) / 2 + 1e-4


def component(board: pcbnew.BOARD, item) -> list:
    """The item plus everything already galvanically joined to it."""
    return [item, *items(board.GetConnectivity().GetConnectedItems(item))]


def item_layers(item) -> list[int]:
    """Routable layers the item has copper on."""
    if isinstance(item, pcbnew.PAD) or item.GetClass() == "PCB_VIA":
        return [layer for layer in LAYERS if item.GetLayerSet().Contains(layer)]
    return [item.GetLayer()] if item.GetLayer() in LAYERS else []


def anchor_of(item) -> tuple[float, float]:
    """The point a trace should meet on this item."""
    position = item.GetPosition()
    return pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)


def _aligned_window(start_anchor, goal_anchor) -> Window:
    """Window over both anchors, with the grid aligned to the start point.

    Reason: a 0.4 mm-pitch pad has exactly enough room for a trace on its centreline
    and none either side, so the start must land on a grid point, not half a cell off.
    """
    rough = window_around([start_anchor, goal_anchor], MARGIN_MM, CELL_BUDGET)
    return Window(
        start_anchor[0] - round((start_anchor[0] - rough.x0) / GRID_MM) * GRID_MM,
        start_anchor[1] - round((start_anchor[1] - rough.y0) / GRID_MM) * GRID_MM,
        rough.nx,
        rough.ny,
    )


def _joined(board: pcbnew.BOARD, start_item, goal_item) -> bool:
    """True when KiCad's own connectivity now puts both items in one island."""
    board.BuildConnectivity()
    goal_id = goal_item.m_Uuid.AsString()
    return any(
        item.m_Uuid.AsString() == goal_id for item in component(board, start_item)
    )


def route_pair(board: pcbnew.BOARD, start_item, goal_item, width_mm: float) -> bool:
    """Route out of `start_item` until it joins `goal_item`'s island.

    Anything drawn is torn out again unless KiCad agrees the two are now connected.
    """
    start_layers = item_layers(start_item)
    if not start_layers:
        return False
    net = start_item.GetNet()
    start_anchor = anchor_of(start_item)
    window = _aligned_window(start_anchor, anchor_of(goal_item))
    fields, inner = clearance_fields(board, net.GetNetCode(), window, LAYERS)
    reach = CLEARANCE_MM + width_mm / 2
    passable = {layer: fields[layer] >= reach + AXIS_SAFETY_MM for layer in LAYERS}
    diagonal = {layer: fields[layer] >= reach + DIAG_SAFETY_MM for layer in LAYERS}
    via_reach = CLEARANCE_MM + VIA_DIAMETER_MM / 2 + DIAG_SAFETY_MM
    via_ok = (inner >= via_reach) & np.logical_and.reduce(
        [fields[layer] >= via_reach for layer in LAYERS]
    )
    copper = {layer: np.zeros((window.ny, window.nx), dtype=bool) for layer in LAYERS}
    on_plane = False
    for item in component(board, goal_item):
        if item.GetClass() == "ZONE":
            on_plane = True
            continue
        for layer in LAYERS:
            copper[layer] |= own_copper_mask(item, window, layer)
    goal = {
        layer: (copper[layer] | via_ok) if on_plane else copper[layer]
        for layer in LAYERS
    }
    if not any(mask.any() for mask in goal.values()):
        return False
    row, col = window.cell_of(*start_anchor)
    for layer in start_layers:
        if not passable[layer][row, col]:
            continue
        path = search(
            window, passable, diagonal, via_ok, (LAYERS.index(layer), row, col), goal
        )
        if path is not None and _commit(
            board,
            net,
            width_mm,
            window,
            path,
            start_anchor,
            copper,
            (start_item, goal_item),
        ):
            return True
    return False


def _commit(board, net, width_mm, window, path, start_anchor, copper, pair) -> bool:
    """Draw a found path, and keep it only if KiCad agrees the islands joined."""
    added = draw(board, net, width_mm, corners_of(window, path), start_anchor)
    end_layer, end_row, end_col = path[-1]
    if not copper[LAYERS[end_layer]][end_row, end_col]:
        x, y = window.point_of(end_row, end_col)
        drop = make_via(board, pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)), net)
        board.Add(drop)
        added.append(drop)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    if _joined(board, *pair):
        return True
    for item in added:
        board.Remove(item)
    board.BuildConnectivity()
    return False
