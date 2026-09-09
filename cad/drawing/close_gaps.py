"""Close the connections the autorouter could not finish.

Run with system python3 (pcbnew), after route_pcb.py and stitch_planes.py:
    python3 cad/drawing/close_gaps.py

Freerouting reliably leaves a handful of escapes on the fine-pitch parts (0.4 mm
DF40, 0.5 mm VQFN / MSOP). Each one is a short hop between two items that are
already on the same net, so this walks KiCad's own DRC report and draws an
L-shaped trace between the reported endpoints, on whichever layer and corner order
is clear. Anything it cannot close is printed for a human to route by hand — it
never forces a trace through another net.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Final

import pcbnew

from cad.drawing.pcb_util import (
    items,
    VIA_DIAMETER_MM,
    corridor_is_clear,
    make_track,
    make_via,
    via_site_is_clear,
)

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
TRACE_WIDTH_MM: Final = 0.25
MAX_ROUNDS: Final = 6
LAYER_BY_NAME: Final = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
# Reason: B.Cu carries a fifth of F.Cu's traces, so an escape via into it usually
# has room even where the front layer is solid around a fine-pitch part.
ESCAPE_STEPS_MM: Final = (0.7, 1.0, 1.4, 1.9, 2.5)
ESCAPE_DIRECTIONS: Final = ((1, 0), (-1, 0), (0, 1), (0, -1))
# Reason: a pad on a plane net only has to reach its plane, not the partner item the
# DRC report names. Searching a spiral of via sites and bending the stub to reach one
# finds room where the stitcher's straight-out stub does not.
PLANE_STEPS_MM: Final = (0.7, 1.1, 1.6, 2.2, 3.0, 4.0)
PLANE_DIRECTIONS: Final = (
    (1, 0),
    (-1, 0),
    (0, 1),
    (0, -1),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
)


def run_drc(board_path: Path) -> list[dict]:
    """Run DRC and return the unconnected-item records."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        report = Path(handle.name)
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            str(board_path),
            "--refill-zones",
            "--severity-error",
            "--format",
            "json",
            "-o",
            str(report),
        ],
        capture_output=True,
        check=True,
    )
    data = json.loads(report.read_text())
    report.unlink()
    return data.get("unconnected_items", [])


def _endpoint(entry: dict) -> tuple[pcbnew.VECTOR2I, int | None, str | None]:
    """Position, layer and net name of one end of an unconnected report item."""
    position = pcbnew.VECTOR2I(
        pcbnew.FromMM(entry["pos"]["x"]), pcbnew.FromMM(entry["pos"]["y"])
    )
    description = entry.get("description", "")
    net_match = re.search(r"\[([^\]]+)\]", description)
    layer_match = re.search(r"on (F\.Cu|B\.Cu)", description)
    layer = LAYER_BY_NAME.get(layer_match.group(1)) if layer_match else None
    return position, layer, net_match.group(1) if net_match else None


def _try_l_path(
    board: pcbnew.BOARD,
    start: pcbnew.VECTOR2I,
    end: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    layers: list[int],
) -> bool:
    """Draw the first clear L-shaped path between two points. True when one was drawn."""
    corners = [pcbnew.VECTOR2I(start.x, end.y), pcbnew.VECTOR2I(end.x, start.y)]
    for layer in layers:
        for corner in corners:
            legs = [(start, corner), (corner, end)]
            if not all(
                corridor_is_clear(board, a, b, net.GetNetCode(), TRACE_WIDTH_MM, layer)
                for a, b in legs
                if a != b
            ):
                continue
            for a, b in legs:
                if a != b:
                    board.Add(make_track(board, a, b, layer, net, TRACE_WIDTH_MM))
            return True
    return False


def _escape_points(anchor: pcbnew.VECTOR2I) -> list[pcbnew.VECTOR2I]:
    """Candidate via positions around an anchor, nearest first."""
    return [
        pcbnew.VECTOR2I(
            anchor.x + dx * pcbnew.FromMM(step), anchor.y + dy * pcbnew.FromMM(step)
        )
        for step in ESCAPE_STEPS_MM
        for dx, dy in ESCAPE_DIRECTIONS
    ]


def _try_via_jump(
    board: pcbnew.BOARD,
    start: pcbnew.VECTOR2I,
    end: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    start_layer: int,
    end_is_track: bool,
) -> bool:
    """Escape onto the opposite layer with a via, cross there, and drop back.

    A via that lands exactly on a track endpoint needs no return stub, so a target
    that is a track is tried at zero offset first.
    """
    other = pcbnew.B_Cu if start_layer == pcbnew.F_Cu else pcbnew.F_Cu
    net_code = net.GetNetCode()
    ends = ([end] if end_is_track else []) + _escape_points(end)
    for via_start in _escape_points(start):
        if not corridor_is_clear(
            board, start, via_start, net_code, VIA_DIAMETER_MM, start_layer
        ):
            continue
        for via_end in ends:
            corner = pcbnew.VECTOR2I(via_start.x, via_end.y)
            legs = [(via_start, corner), (corner, via_end)]
            if not all(
                corridor_is_clear(board, a, b, net_code, TRACE_WIDTH_MM, other)
                for a, b in legs
                if a != b
            ):
                continue
            if via_end != end and not corridor_is_clear(
                board, via_end, end, net_code, TRACE_WIDTH_MM, start_layer
            ):
                continue
            if not via_site_is_clear(
                board, via_start, net_code
            ) or not via_site_is_clear(board, via_end, net_code):
                continue
            board.Add(
                make_track(board, start, via_start, start_layer, net, TRACE_WIDTH_MM)
            )
            board.Add(make_via(board, via_start, net))
            for a, b in legs:
                if a != b:
                    board.Add(make_track(board, a, b, other, net, TRACE_WIDTH_MM))
            board.Add(make_via(board, via_end, net))
            if via_end != end:
                board.Add(
                    make_track(board, via_end, end, start_layer, net, TRACE_WIDTH_MM)
                )
            return True
    return False


def _try_plane_drop(
    board: pcbnew.BOARD,
    start: pcbnew.VECTOR2I,
    net: pcbnew.NETINFO_ITEM,
    layer: int,
) -> bool:
    """Drop a via from `start` into this net's plane, bending the stub if needed."""
    for step in PLANE_STEPS_MM:
        for dx, dy in PLANE_DIRECTIONS:
            offset = pcbnew.FromMM(step)
            target = pcbnew.VECTOR2I(start.x + dx * offset, start.y + dy * offset)
            corner = pcbnew.VECTOR2I(target.x, start.y)
            legs = [(start, corner), (corner, target)]
            if not all(
                corridor_is_clear(board, a, b, net.GetNetCode(), TRACE_WIDTH_MM, layer)
                for a, b in legs
                if a != b
            ):
                continue
            if not via_site_is_clear(board, target, net.GetNetCode()):
                continue
            for a, b in legs:
                if a != b:
                    board.Add(make_track(board, a, b, layer, net, TRACE_WIDTH_MM))
            board.Add(make_via(board, target, net))
            return True
    return False


def close_gaps() -> None:
    """Iterate DRC and close every unconnected pair that can be closed cleanly."""
    remaining: list[str] = []
    for round_number in range(1, MAX_ROUNDS + 1):
        unconnected = run_drc(PCB_PATH)
        if not unconnected:
            print(f"round {round_number}: nothing left unconnected")
            return
        board = pcbnew.LoadBoard(str(PCB_PATH))
        plane_nets = {z.GetNetname() for z in items(board.Zones())}
        closed, remaining = 0, []
        for record in unconnected:
            ends = record.get("items", [])
            if len(ends) != 2:
                continue
            (start, start_layer, net_name), (end, end_layer, _) = (
                _endpoint(e) for e in ends
            )
            net = board.FindNet(net_name) if net_name else None
            if net is None:
                remaining.append(f"{net_name} (net not on board)")
                continue
            layers = [layer for layer in (start_layer, end_layer) if layer is not None]
            layers = layers or [pcbnew.F_Cu, pcbnew.B_Cu]
            end_is_track = "Track" in ends[1].get("description", "")
            if (
                _try_l_path(board, start, end, net, layers)
                or (
                    net_name in plane_nets
                    and _try_plane_drop(board, start, net, layers[0])
                )
                or _try_via_jump(board, start, end, net, layers[0], end_is_track)
            ):
                closed += 1
            else:
                remaining.append(
                    f"{net_name} @ ({pcbnew.ToMM(start.x):.2f},{pcbnew.ToMM(start.y):.2f})"
                )
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        board.Save(str(PCB_PATH))
        print(f"round {round_number}: closed {closed}, {len(remaining)} left")
        if not closed:
            break
    if remaining:
        print("could not close cleanly — route these by hand:")
        for entry in remaining:
            print(f"  {entry}")


if __name__ == "__main__":
    close_gaps()
