"""Close the last connections with the maze escape router.

Run with system python3 (pcbnew), after close_gaps.py:
    PYTHONPATH=. /usr/bin/python3 -m cad.drawing.escape_pins

close_gaps draws L-shapes and gets most of the leftovers; what survives it is always a
fine-pitch pin that has to leave its pad in one particular direction and then work its
way around several obstacles. This walks KiCad's DRC report and hands each of those to
the A* router, starting from whichever end is the more boxed in.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pcbnew

from cad.drawing.close_gaps import run_drc
from cad.drawing.maze_escape import WIDTHS_MM, component, route_pair
from cad.drawing.pcb_util import items

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")


def resolve(board: pcbnew.BOARD, entry: dict):
    """Find the board item a DRC report entry refers to."""
    description = entry.get("description", "")
    pad_match = re.match(r"(?:N?PTH )?[Pp]ad (\S+) \[[^\]]*\] of (\S+)", description)
    if pad_match:
        number, reference = pad_match.group(1), pad_match.group(2)
        for footprint in items(board.Footprints()):
            if footprint.GetReference() != reference:
                continue
            for pad in items(footprint.Pads()):
                if pad.GetNumber() == number:
                    return pad
        raise LookupError(f"no pad {reference}.{number}")
    net_match = re.search(r"\[([^\]]+)\]", description)
    net_name = net_match.group(1) if net_match else ""
    target = pcbnew.VECTOR2I(
        pcbnew.FromMM(entry["pos"]["x"]), pcbnew.FromMM(entry["pos"]["y"])
    )
    candidates = [t for t in items(board.Tracks()) if t.GetNetname() == net_name]
    if not candidates:
        raise LookupError(f"no track on net {net_name!r}")
    return min(
        candidates,
        key=lambda track: min(
            (track.GetStart() - target).EuclideanNorm(),
            (track.GetEnd() - target).EuclideanNorm(),
        ),
    )


def _nearest_first(x: float, y: float):
    """Sort key putting the pair closest to (x, y) at the front.

    Reason: the router is greedy, so the first pin routed claims the lane. After a
    region is ripped up, the pin the rip was meant to free has to choose first.
    """

    def key(record: dict) -> float:
        ends = record.get("items", [])
        if not ends:
            return 1e9
        return min(
            (end["pos"]["x"] - x) ** 2 + (end["pos"]["y"] - y) ** 2 for end in ends
        )

    return key


def escape_all(first: tuple[float, float] | None = None) -> None:
    """Route every unconnected pair DRC still reports, widest trace first."""
    unconnected = run_drc(PCB_PATH)
    if not unconnected:
        print("nothing left unconnected")
        return
    board = pcbnew.LoadBoard(str(PCB_PATH))
    drawn = 0
    order = _nearest_first(*first) if first else None
    for record in sorted(unconnected, key=order) if order else unconnected:
        ends = record.get("items", [])
        if len(ends) != 2:
            continue
        pair = [resolve(board, end) for end in ends]
        # Reason: the island with less copper is the stranded pin; routing out of it is
        # what the search is good at, and it keeps the window small.
        pair.sort(key=lambda item: len(component(board, item)))
        start_item, goal_item = pair
        if any(route_pair(board, start_item, goal_item, w) for w in WIDTHS_MM):
            drawn += 1
            print(f"  routed {ends[0]['description']} -> {ends[1]['description']}")
        else:
            print(f"  no path: {ends[0]['description']} -> {ends[1]['description']}")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB_PATH))
    print(f"routed {drawn} of {len(unconnected)} remaining connections")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", nargs=2, type=float, metavar=("X", "Y"))
    options = parser.parse_args()
    escape_all(tuple(options.first) if options.first else None)
