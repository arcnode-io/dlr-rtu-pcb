"""Shared pcbnew helpers for the board scripts (system python3 only).

Clearance is measured as real distance — segment to segment for tracks, segment to
rectangle for pads — not bounding-box overlap. A bounding box around a long diagonal
trace covers most of its quadrant, so a box test reports "blocked" almost everywhere
on a dense board and nothing can be placed. DRC remains the authority; these checks
only decide where it is worth trying.
"""

from __future__ import annotations

import math
from typing import Final

import pcbnew

CLEARANCE_MM: Final = 0.15
VIA_DIAMETER_MM: Final = 0.6
VIA_DRILL_MM: Final = 0.3
# Reason: the drill plus the board's min hole-to-hole rule. Net membership does not
# enter into it — two drills this close break into each other whoever owns them.
HOLE_TO_HOLE_MM: Final = VIA_DRILL_MM + 0.25


def items(container) -> list:
    """Index-based copy of a SWIG container.

    Reason: KiCad 10's SWIG iterators have no working `.next()` under Python 3.14,
    so `list(board.Tracks())` raises AttributeError.
    """
    return [container[i] for i in range(len(container))]


def _point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance from point p to segment a-b, in internal units."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segments_cross(a1, a2, b1, b2) -> bool:
    def side(p, q, r) -> float:
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

    d1, d2 = side(b1, b2, a1), side(b1, b2, a2)
    d3, d4 = side(a1, a2, b1), side(a1, a2, b2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def segment_distance(a1, a2, b1, b2) -> float:
    """Shortest distance between segments a1-a2 and b1-b2, in internal units."""
    if _segments_cross(a1, a2, b1, b2):
        return 0.0
    return min(
        _point_segment_distance(a1.x, a1.y, b1.x, b1.y, b2.x, b2.y),
        _point_segment_distance(a2.x, a2.y, b1.x, b1.y, b2.x, b2.y),
        _point_segment_distance(b1.x, b1.y, a1.x, a1.y, a2.x, a2.y),
        _point_segment_distance(b2.x, b2.y, a1.x, a1.y, a2.x, a2.y),
    )


def segment_box_distance(
    a: pcbnew.VECTOR2I, b: pcbnew.VECTOR2I, box: pcbnew.BOX2I
) -> float:
    """Shortest distance from segment a-b to an axis-aligned box, in internal units."""
    left, right = box.GetLeft(), box.GetRight()
    top, bottom = box.GetTop(), box.GetBottom()
    corners = [
        pcbnew.VECTOR2I(left, top),
        pcbnew.VECTOR2I(right, top),
        pcbnew.VECTOR2I(right, bottom),
        pcbnew.VECTOR2I(left, bottom),
    ]
    inside = left <= a.x <= right and top <= a.y <= bottom
    if inside:
        return 0.0
    return min(
        segment_distance(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4)
    )


def _pads_clear(board, a, b, net_code: int, box, reach: int) -> bool:
    """True when every foreign pad stays `reach` away from segment a-b."""
    for footprint in items(board.Footprints()):
        if not footprint.GetBoundingBox(False, False).Intersects(box):
            continue
        for pad in items(footprint.Pads()):
            if pad.GetNetCode() == net_code:
                continue
            if segment_box_distance(a, b, pad.GetBoundingBox()) < reach:
                return False
    return True


def _tracks_clear(
    board, a, b, net_code: int, box, half: int, layer: int | None
) -> bool:
    """True when every foreign track and via stays clear of segment a-b.

    Vias are checked whatever layer is being routed — a through via is on all of them.
    """
    clearance = pcbnew.FromMM(CLEARANCE_MM)
    for track in items(board.Tracks()):
        if track.GetNetCode() == net_code or not track.GetBoundingBox().Intersects(box):
            continue
        is_via = track.GetClass() == "PCB_VIA"
        if not is_via and layer is not None and track.GetLayer() != layer:
            continue
        if is_via:
            centre = track.GetPosition()
            gap = _point_segment_distance(centre.x, centre.y, a.x, a.y, b.x, b.y)
        else:
            gap = segment_distance(a, b, track.GetStart(), track.GetEnd())
        if gap < half + track.GetWidth() / 2 + clearance:
            return False
    return True


def corridor_is_clear(
    board: pcbnew.BOARD,
    a: pcbnew.VECTOR2I,
    b: pcbnew.VECTOR2I,
    net_code: int,
    width_mm: float,
    layer: int | None = None,
) -> bool:
    """True when everything of another net stays clear of the corridor from a to b."""
    # Reason: a cheap box to skip everything nowhere near the corridor; the real test
    # is the segment distance below.
    pad = pcbnew.FromMM(width_mm / 2 + CLEARANCE_MM)
    corner = pcbnew.VECTOR2I(min(a.x, b.x) - pad, min(a.y, b.y) - pad)
    span = pcbnew.VECTOR2I(abs(a.x - b.x) + 2 * pad, abs(a.y - b.y) + 2 * pad)
    box = pcbnew.BOX2I(corner, span)
    half = pcbnew.FromMM(width_mm / 2)
    reach = half + pcbnew.FromMM(CLEARANCE_MM)
    return _pads_clear(board, a, b, net_code, box, reach) and _tracks_clear(
        board, a, b, net_code, box, half, layer
    )


def via_site_is_clear(
    board: pcbnew.BOARD, centre: pcbnew.VECTOR2I, net_code: int
) -> bool:
    """True when a through via at `centre` clears every other net on every layer.

    Reason: a through via occupies all copper layers, so it must be checked against
    all of them. Testing it only on the layer being routed is how a GND via ends up
    sitting on a signal trace on the opposite side.

    The hole check deliberately ignores `net_code`. Clearance rules let a trace run
    along its own net's copper, so the copper test skips same-net items — but a second
    drill 0.1 mm from the first is a broken-out hole even when both are ground.
    """
    reach = pcbnew.FromMM(HOLE_TO_HOLE_MM)
    for track in items(board.Tracks()):
        if (
            track.GetClass() == "PCB_VIA"
            and (track.GetPosition() - centre).EuclideanNorm() < reach
        ):
            return False
    return corridor_is_clear(
        board, centre, centre, net_code, VIA_DIAMETER_MM, layer=None
    )


def make_track(
    board: pcbnew.BOARD,
    start: pcbnew.VECTOR2I,
    end: pcbnew.VECTOR2I,
    layer: int,
    net: pcbnew.NETINFO_ITEM,
    width_mm: float,
) -> pcbnew.PCB_TRACK:
    """Build (but do not add) a track segment."""
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(start)
    track.SetEnd(end)
    track.SetWidth(pcbnew.FromMM(width_mm))
    track.SetLayer(layer)
    track.SetNet(net)
    return track


def make_via(
    board: pcbnew.BOARD, centre: pcbnew.VECTOR2I, net: pcbnew.NETINFO_ITEM
) -> pcbnew.PCB_VIA:
    """Build (but do not add) a through via."""
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(centre)
    via.SetWidth(pcbnew.FromMM(VIA_DIAMETER_MM))
    via.SetDrill(pcbnew.FromMM(VIA_DRILL_MM))
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(net)
    return via
