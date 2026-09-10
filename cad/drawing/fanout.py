"""Assign escape vias for a fine-pitch connector before anything routes it.

Run with system python3 (pcbnew), before route_pcb.py — or on an already-routed board,
followed by escape_pins to reconnect what it cleared:
    PYTHONPATH=. /usr/bin/python3 -m cad.drawing.fanout

A 0.4 mm pad pitch cannot give every pin a via in one row: two 0.6 mm vias need 0.75 mm
between centres, so only every other pin fits. The pins that miss out have to reach a
second, deeper row — and two adjacent vias in the first row leave a 0.15 mm slot, while
a 0.2 mm trace with 0.15 mm either side needs 0.5 mm. **Once the first row exists the
second row is unreachable.** A router that picks the nearest free site per pin therefore
always strands somebody, however hard it searches; the assignment has to happen up front.

So: alternate along each pad row, one pin into the inter-row gap, the next out the back
of the connector. Same-side vias end up 0.8 mm apart, which clears the 0.75 mm rule, and
every stub runs straight out of its own pad with no lane to fight over.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pcbnew

from cad.drawing.pcb_util import (
    CLEARANCE_MM,
    VIA_DIAMETER_MM,
    corridor_is_clear,
    items,
    make_track,
    make_via,
    segment_box_distance,
    via_site_is_clear,
)

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
# Reason: only J5 (0.4 mm DF40) is tight enough to need this. U4 is a 0.65 mm TSSOP —
# its pads reach far enough out that traces escape sideways without a via at all, and
# re-doing a corner that already routes would be churn for nothing.
FANOUT_REFERENCES: Final = ("J5",)
# Reason: 1.09 mm clears the 0.7 mm-long pad by 0.44 mm, and puts the two gap-side rows
# 0.90 mm apart — both comfortably over the 0.75 mm via-to-via rule.
VIA_OFFSET_MM: Final = 1.09
STUB_WIDTH_MM: Final = 0.2
# Reason: the band has to swallow anything that could clash with an escape via, and
# the tightest such thing is another via — legal at 2r + clearance = 0.75 mm away.
# Reaching only to the via's own edge leaves neighbours sitting just over the line.
BAND_MARGIN_MM: Final = VIA_OFFSET_MM + VIA_DIAMETER_MM + CLEARANCE_MM


def pad_rows(footprint: pcbnew.FOOTPRINT) -> list[list[pcbnew.PAD]]:
    """The footprint's SMD pads grouped into rows by y, each row sorted by x."""
    rows: dict[int, list[pcbnew.PAD]] = defaultdict(list)
    for pad in items(footprint.Pads()):
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            rows[pad.GetPosition().y].append(pad)
    return [sorted(rows[y], key=lambda pad: pad.GetPosition().x) for y in sorted(rows)]


def band_of(rows: list[list[pcbnew.PAD]]) -> pcbnew.BOX2I:
    """The rectangle the fanout owns: both pad rows plus both via rows and clearance."""
    xs = [pad.GetPosition().x for row in rows for pad in row]
    ys = [pad.GetPosition().y for row in rows for pad in row]
    margin = pcbnew.FromMM(BAND_MARGIN_MM)
    left, right = min(xs) - margin, max(xs) + margin
    top, bottom = min(ys) - margin, max(ys) + margin
    return pcbnew.BOX2I(
        pcbnew.VECTOR2I(left, top), pcbnew.VECTOR2I(right - left, bottom - top)
    )


def clear_band(board: pcbnew.BOARD, box: pcbnew.BOX2I) -> int:
    """Delete every track and via touching the band. Returns how many went.

    Reason: testing the endpoints is not enough. A trace on its way somewhere else can
    cross the band with both ends outside it, and it will sit right where an escape via
    has to go — which is exactly how the first run stranded four pins.
    """
    doomed = [
        track
        for track in items(board.Tracks())
        if box.Contains(track.GetPosition())
        or segment_box_distance(track.GetStart(), track.GetEnd(), box) <= 0
    ]
    for track in doomed:
        board.Remove(track)
    return len(doomed)


@dataclass(frozen=True, eq=False)
class Escape:
    """One pad's planned exit: where the stub starts, where its via lands."""

    number: str
    net_code: int
    layer: int
    pad: pcbnew.VECTOR2I
    via: pcbnew.VECTOR2I


def plan_escapes(rows: list[list[pcbnew.PAD]]) -> list[Escape]:
    """Work out every pad's stub and via site, alternating sides along each row.

    Reason: read in full *before* any copper is deleted. pcbnew hands back a bare
    SwigPyObject for anything fetched from a footprint once board.Remove() has run, so
    the plan has to be plain numbers by the time the band is cleared.
    """
    planned = []
    for row_index, row in enumerate(rows):
        # Reason: the first row is the upper one, so its gap side is +y; the lower row's
        # gap side is -y. Everything else about the two rows is identical.
        gap_sign = 1 if row_index == 0 else -1
        for index, pad in enumerate(row):
            if pad.GetNetCode() == 0 or pad.GetNetname().startswith("unconnected-"):
                continue
            side = gap_sign if index % 2 == 0 else -gap_sign
            position = pad.GetPosition()
            planned.append(
                Escape(
                    pad.GetNumber(),
                    pad.GetNetCode(),
                    pad.GetLayer(),
                    pcbnew.VECTOR2I(int(position.x), int(position.y)),
                    pcbnew.VECTOR2I(
                        int(position.x),
                        int(position.y) + side * pcbnew.FromMM(VIA_OFFSET_MM),
                    ),
                )
            )
    return planned


def escape_is_clear(board: pcbnew.BOARD, escape: Escape) -> bool:
    """True when this pad's stub and via site clear every other net's copper."""
    return corridor_is_clear(
        board, escape.pad, escape.via, escape.net_code, STUB_WIDTH_MM, escape.layer
    ) and via_site_is_clear(board, escape.via, escape.net_code)


def draw_escape(board: pcbnew.BOARD, escape: Escape) -> None:
    """Draw one pad's stub and via."""
    net = board.FindNet(escape.net_code)
    board.Add(
        make_track(board, escape.pad, escape.via, escape.layer, net, STUB_WIDTH_MM)
    )
    board.Add(make_via(board, escape.via, net))


def clear_all() -> None:
    """Pass one: delete every connector's fanout band, then save and get out.

    Reason: board.Remove() poisons this interpreter's SWIG bindings — footprints and
    pads fetched afterwards come back as bare SwigPyObject. So clearing and placing are
    two processes with a save between them, not two halves of one function.
    """
    board = pcbnew.LoadBoard(str(PCB_PATH))
    for footprint in _wanted(board):
        rows = pad_rows(footprint)
        if len(rows) != 2:
            raise ValueError(f"{footprint.GetReference()} is not a two-row footprint")
        print(f"{footprint.GetReference()}: cleared {clear_band(board, band_of(rows))}")
    board.Save(str(PCB_PATH))


def place_all() -> None:
    """Pass two: check every escape against the cleared board, then draw them all.

    Every check runs before the first Add for the same reason clearing is its own pass.
    Sibling escapes are not in the check: the alternation puts same-side vias 0.8 mm
    apart against a 0.75 mm rule, which holds by construction.
    """
    board = pcbnew.LoadBoard(str(PCB_PATH))
    planned = [
        (footprint.GetReference(), escape)
        for footprint in _wanted(board)
        for escape in plan_escapes(pad_rows(footprint))
    ]
    stuck = [
        f"{reference}.{escape.number}"
        for reference, escape in planned
        if not escape_is_clear(board, escape)
    ]
    if stuck:
        raise RuntimeError(
            f"no room for an escape at {stuck} — the offsets in this module no longer "
            "fit the board"
        )
    for _, escape in planned:
        draw_escape(board, escape)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(PCB_PATH))
    print(f"placed {len(planned)} escapes")


def _wanted(board: pcbnew.BOARD) -> list[pcbnew.FOOTPRINT]:
    """The footprints named in FANOUT_REFERENCES, in that order."""
    found = {
        footprint.GetReference(): footprint
        for footprint in items(board.Footprints())
        if footprint.GetReference() in FANOUT_REFERENCES
    }
    missing = set(FANOUT_REFERENCES) - set(found)
    if missing:
        raise LookupError(f"no such footprint: {sorted(missing)}")
    return [found[reference] for reference in FANOUT_REFERENCES]


def fanout() -> None:
    """Clear then place, each in its own interpreter."""
    for stage in ("--clear", "--place"):
        result = subprocess.run(
            [sys.executable, "-m", "cad.drawing.fanout", stage],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "."},
            check=False,
        )
        print(result.stdout, end="")
        if result.returncode:
            raise RuntimeError(f"{stage} failed:\n{result.stderr[-2000:]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--place", action="store_true")
    options = parser.parse_args()
    if options.clear:
        clear_all()
    elif options.place:
        place_all()
    else:
        fanout()
