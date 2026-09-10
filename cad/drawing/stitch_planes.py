"""Stitch surface pads to their inner plane with vias.

Run with system python3 (pcbnew), after route_pcb.py:
    python3 cad/drawing/stitch_planes.py

Freerouting treats a net that owns a plane as already connected and stops routing
it, but a surface pad has no path to an inner layer without a via. This adds, for
every SMD pad on a plane net, a via just outside the pad plus a short trace to it.
Through-hole pads need nothing — their barrel already crosses the plane.

Placement rule: the via goes outward along the pad's long axis (away from the
footprint centre), the first candidate distance that clears every other item wins;
a pad that cannot be stitched is reported rather than silently skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pcbnew

from cad.drawing.pcb_util import (
    HOLE_TO_HOLE_MM,
    VIA_DIAMETER_MM,
    corridor_is_clear,
    items as _items,
    make_track,
    make_via,
)

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
TRACE_WIDTH_MM: Final = 0.3
# Reason: try close first (short stub = low inductance), then step outward
GAP_STEPS_MM: Final = (0.25, 0.45, 0.7, 1.0, 1.4)


def _outward(footprint: pcbnew.FOOTPRINT, pad: pcbnew.PAD) -> pcbnew.VECTOR2I:
    """Unit-ish step vector pointing away from the footprint centre, along the pad's long axis."""
    size = pad.GetSize()
    delta = pad.GetPosition() - footprint.GetPosition()
    if size.x >= size.y:
        sign = 1 if delta.x >= 0 else -1
        return pcbnew.VECTOR2I(sign, 0)
    sign = 1 if delta.y >= 0 else -1
    return pcbnew.VECTOR2I(0, sign)


def _half_extent(pad: pcbnew.PAD, direction: pcbnew.VECTOR2I) -> int:
    size = pad.GetSize()
    return size.x // 2 if direction.x else size.y // 2


def _corridor_is_clear(
    board: pcbnew.BOARD, pad: pcbnew.PAD, centre: pcbnew.VECTOR2I
) -> bool:
    """True when nothing of another net sits under the via or its stub trace."""
    width = max(VIA_DIAMETER_MM, TRACE_WIDTH_MM)
    return corridor_is_clear(board, pad.GetPosition(), centre, pad.GetNetCode(), width)


def dedupe_vias(board: pcbnew.BOARD) -> int:
    """Drop same-net vias that land on top of each other. Returns how many went.

    Reason: the stitch list is built from the board as it was, so two pads whose
    outward step lands on the same point each add a via there. One hole drilled
    several times is a fab defect the board file happily carries — and a near miss
    is worse than an exact hit, because the drills break into each other.
    """
    kept: list[pcbnew.PCB_VIA] = []
    doomed = []
    for track in _items(board.Tracks()):
        if track.GetClass() != "PCB_VIA":
            continue
        position = track.GetPosition()
        clash = any(
            other.GetNetCode() == track.GetNetCode()
            and (other.GetPosition() - position).EuclideanNorm()
            < pcbnew.FromMM(HOLE_TO_HOLE_MM)
            for other in kept
        )
        (doomed if clash else kept).append(track)
    for track in doomed:
        board.Remove(track)
    return len(doomed)


def _via_site_free(board: pcbnew.BOARD, centre: pcbnew.VECTOR2I) -> bool:
    """True when no existing via is close enough to clash with one at `centre`."""
    reach = pcbnew.FromMM(VIA_DIAMETER_MM + 0.15)
    for track in _items(board.Tracks()):
        if track.GetClass() != "PCB_VIA":
            continue
        if (track.GetPosition() - centre).EuclideanNorm() < reach:
            return False
    return True


def _has_via_nearby(board: pcbnew.BOARD, pad: pcbnew.PAD) -> bool:
    """True when this net already has a via close enough to serve as the pad's plane drop."""
    reach = pcbnew.FromMM(2.0)
    position = pad.GetPosition()
    for track in _items(board.Tracks()):
        if track.GetClass() != "PCB_VIA" or track.GetNetCode() != pad.GetNetCode():
            continue
        delta = track.GetPosition() - position
        if abs(delta.x) <= reach and abs(delta.y) <= reach:
            return True
    return False


def stitch() -> None:
    """Add a stitching via for every SMD pad sitting on a plane net."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    removed = dedupe_vias(board)
    plane_nets = {z.GetNetname() for z in _items(board.Zones())}
    plane_codes = {board.FindNet(n).GetNetCode(): board.FindNet(n) for n in plane_nets}

    todo: list[tuple[pcbnew.FOOTPRINT, pcbnew.PAD]] = [
        (footprint, pad)
        for footprint in _items(board.Footprints())
        for pad in _items(footprint.Pads())
        if pad.GetNetCode() in plane_codes
        and pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
        and not _has_via_nearby(board, pad)
    ]

    stitched, failed = 0, []
    for footprint, pad in todo:
        net = plane_codes[pad.GetNetCode()]
        direction = _outward(footprint, pad)
        base = _half_extent(pad, direction) + pcbnew.FromMM(VIA_DIAMETER_MM / 2)
        for gap in GAP_STEPS_MM:
            step = base + pcbnew.FromMM(gap)
            centre = pcbnew.VECTOR2I(
                pad.GetPosition().x + direction.x * step,
                pad.GetPosition().y + direction.y * step,
            )
            if not _corridor_is_clear(board, pad, centre) or not _via_site_free(
                board, centre
            ):
                continue
            board.Add(make_via(board, centre, net))
            board.Add(
                make_track(
                    board,
                    pad.GetPosition(),
                    centre,
                    pad.GetLayer(),
                    net,
                    TRACE_WIDTH_MM,
                )
            )
            stitched += 1
            break
        else:
            failed.append(f"{footprint.GetReference()}.{pad.GetNumber()}")

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(str(PCB_PATH))
    print(
        f"plane nets {sorted(plane_nets)}: {stitched} of {len(todo)} SMD pads stitched"
        f"; {removed} duplicate vias removed"
    )
    if failed:
        print(f"no room for a via at: {failed}")


if __name__ == "__main__":
    stitch()
