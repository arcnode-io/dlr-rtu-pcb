"""The pcbnew half of the rip-up loop: find stranded pins and their blockers, or rip.

Two one-shot modes, both driven by rip_up.py in a fresh interpreter:

    PYTHONPATH=. /usr/bin/python3 -m cad.drawing.rip_targets
        prints JSON: one record per unconnected pair, holding the position of the more
        boxed-in end and the nets whose copper sits closest to it.

    PYTHONPATH=. /usr/bin/python3 -m cad.drawing.rip_targets --rip CODE X Y
        deletes that net's tracks and vias within the rip radius of (X, Y) mm, refills
        the zones and saves.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Final

import pcbnew

from cad.drawing.close_gaps import run_drc
from cad.drawing.escape_pins import resolve
from cad.drawing.maze_escape import component
from cad.drawing.pcb_util import items

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
RADIUS_MM: Final = 1.3


def distance_mm(item, centre: pcbnew.VECTOR2I) -> float:
    """Distance from a track's or via's copper edge to a point, in millimetres.

    Measured to the segment, not to its endpoints: a long trace sliding past a pin is
    exactly the thing that boxes it in, and its endpoints can be centimetres away.
    """
    half = pcbnew.ToMM(item.GetWidth()) / 2
    x, y = pcbnew.ToMM(centre.x), pcbnew.ToMM(centre.y)
    if item.GetClass() == "PCB_VIA":
        position = item.GetPosition()
        gap = math.hypot(pcbnew.ToMM(position.x) - x, pcbnew.ToMM(position.y) - y)
        return gap - half
    start, end = item.GetStart(), item.GetEnd()
    ax, ay = pcbnew.ToMM(start.x), pcbnew.ToMM(start.y)
    bx, by = pcbnew.ToMM(end.x), pcbnew.ToMM(end.y)
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = (
        0.0
        if length_sq == 0
        else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
    )
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy)) - half


def blocking_nets(board: pcbnew.BOARD, centre, net_code: int) -> list[dict]:
    """Nets with copper near `centre`, nearest first, excluding the pin's own."""
    nearest: dict[int, float] = {}
    for track in items(board.Tracks()):
        code = track.GetNetCode()
        if code in (0, net_code):
            continue
        distance = distance_mm(track, centre)
        if distance < RADIUS_MM and distance < nearest.get(code, 1e9):
            nearest[code] = distance
    return [
        {"code": code, "name": board.FindNet(code).GetNetname()}
        for code, _ in sorted(nearest.items(), key=lambda pair: pair[1])
    ]


def targets() -> list[dict]:
    """One record per unconnected pair: the boxed-in end and what surrounds it."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    records = []
    for record in run_drc(PCB_PATH):
        ends = record.get("items", [])
        if len(ends) != 2:
            continue
        pair = [resolve(board, end) for end in ends]
        pair.sort(key=lambda item: len(component(board, item)))
        centre = pair[0].GetPosition()
        records.append(
            {
                "label": ends[0]["description"],
                "x": pcbnew.ToMM(centre.x),
                "y": pcbnew.ToMM(centre.y),
                "victims": blocking_nets(board, centre, pair[0].GetNetCode()),
            }
        )
    return records


def _net_at(board: pcbnew.BOARD, centre: pcbnew.VECTOR2I) -> int:
    """Net code of the pad sitting at a point — the pin a region rip is protecting."""
    for footprint in items(board.Footprints()):
        for pad in items(footprint.Pads()):
            if pad.GetPosition() == centre:
                return pad.GetNetCode()
    return -1


def rip(net_code: int, x: float, y: float, radius: float = RADIUS_MM) -> int:
    """Delete tracks and vias within RADIUS_MM of a point, and save.

    `net_code` of 0 means every net but the one the stranded pin is on — a whole fanout
    corner cleared at once, so the router can re-stagger the escape vias instead of
    inheriting a row that only fits every other pin.
    """
    board = pcbnew.LoadBoard(str(PCB_PATH))
    centre = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    keep = _net_at(board, centre) if net_code == 0 else None
    doomed = [
        track
        for track in items(board.Tracks())
        if (track.GetNetCode() == net_code if net_code else track.GetNetCode() != keep)
        and distance_mm(track, centre) < radius
    ]
    for track in doomed:
        board.Remove(track)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB_PATH))
    return len(doomed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rip", nargs=3, metavar=("CODE", "X", "Y"))
    parser.add_argument("--radius", type=float, default=RADIUS_MM)
    options = parser.parse_args()
    if options.rip:
        code, x, y = options.rip
        print(rip(int(code), float(x), float(y), options.radius))
    else:
        print(json.dumps(targets()))
