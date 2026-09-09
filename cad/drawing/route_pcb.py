"""Autoroute the carrier: DSN export -> Freerouting -> SES import -> zone fill.

Run with system python3 (pcbnew), after place_pcb.py and board_setup.py:
    python3 cad/drawing/route_pcb.py [--passes N]

Two edits to the exported DSN make Freerouting behave on a plane stack:

  * KiCad marks every copper layer "(type signal)", even one covered by a plane, so
    the router drives signals straight through the GND and 5V planes. Plane layers
    are rewritten to "(type power)" and become unroutable.
  * KiCad also emits "(plane <net> (polygon ...))" for those zones, which tells the
    router that net is already connected — it then leaves most of the net unrouted,
    and every surface pad on it ends up with no path to the inner layer. Dropping
    those declarations makes GND and 5V ordinary nets: the router connects each pad
    and drops the layer-changing vias, which land in the plane and stitch it.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pcbnew

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
WORK_DIR = Path("/tmp/dlr_route")
FREEROUTING_JAR = Path.home() / "tools" / "freerouting.jar"
DEFAULT_PASSES: Final = 20
# Reason: Freerouting's own log warns that multi-threaded optimization generates
# clearance violations; single thread is the supported configuration.
THREADS: Final = 1


def _items(container) -> list:
    return [container[i] for i in range(len(container))]


def plane_layers(board: pcbnew.BOARD) -> set[str]:
    """Names of copper layers covered by a plane zone."""
    return {board.GetLayerName(z.GetFirstLayer()) for z in _items(board.Zones())}


def mark_plane_layers(dsn_text: str, layers: set[str]) -> str:
    """Rewrite `(layer X (type signal))` to `(type power)` for each plane layer."""
    for name in layers:
        dsn_text = re.sub(
            rf"(\(layer {re.escape(name)}\s*\n\s*\(type )signal(\))",
            r"\1power\2",
            dsn_text,
        )
    return dsn_text


def drop_plane_declarations(dsn_text: str) -> tuple[str, int]:
    """Remove `(plane <net> (polygon ...))` blocks. Returns (text, blocks removed)."""
    out, removed, i = [], 0, 0
    while True:
        start = dsn_text.find("(plane ", i)
        if start < 0:
            out.append(dsn_text[i:])
            return "".join(out), removed
        out.append(dsn_text[i:start])
        depth, j = 0, start
        while j < len(dsn_text):
            if dsn_text[j] == "(":
                depth += 1
            elif dsn_text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        removed += 1
        i = j + 1
        while i < len(dsn_text) and dsn_text[i] in " \t\r\n":
            i += 1


def route(passes: int = DEFAULT_PASSES) -> None:
    """Export, route, and import; leaves the routed board saved in place."""
    if not FREEROUTING_JAR.exists():
        raise FileNotFoundError(f"{FREEROUTING_JAR} missing — see the layout-pcb skill")
    if shutil.which("java") is None:
        raise FileNotFoundError("java not on PATH — Freerouting needs a JRE")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    dsn, ses = WORK_DIR / "dlr_carrier.dsn", WORK_DIR / "dlr_carrier.ses"

    board = pcbnew.LoadBoard(str(PCB_PATH))
    planes = plane_layers(board)
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("Specctra DSN export failed")
    patched, dropped = drop_plane_declarations(
        mark_plane_layers(dsn.read_text(), planes)
    )
    dsn.write_text(patched)
    print(
        f"DSN exported; plane layers held out of routing: {sorted(planes)}; "
        f"{dropped} plane declarations dropped so their nets get routed and stitched"
    )

    result = subprocess.run(
        [
            "java",
            "-jar",
            str(FREEROUTING_JAR),
            "-de",
            str(dsn),
            "-do",
            str(ses),
            "-mp",
            str(passes),
            "-mt",
            str(THREADS),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if not ses.exists():
        sys.stderr.write(result.stdout[-4000:] + result.stderr[-4000:])
        raise RuntimeError("Freerouting produced no session file")

    routed = pcbnew.LoadBoard(str(PCB_PATH))
    if not pcbnew.ImportSpecctraSES(routed, str(ses)):
        raise RuntimeError("Specctra SES import failed")
    filler = pcbnew.ZONE_FILLER(routed)
    filler.Fill(routed.Zones())
    routed.Save(str(PCB_PATH))

    tracks = _items(routed.Tracks())
    segments = [t for t in tracks if t.GetClass() == "PCB_TRACK"]
    by_layer: dict[str, int] = {}
    for t in segments:
        name = routed.GetLayerName(t.GetLayer())
        by_layer[name] = by_layer.get(name, 0) + 1
    print(f"routed: {len(segments)} segments, {len(tracks) - len(segments)} vias")
    print(f"segments per layer: {by_layer}")
    stray = {k: v for k, v in by_layer.items() if k in planes}
    if stray:
        raise RuntimeError(f"router put signal traces on plane layers: {stray}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passes", type=int, default=DEFAULT_PASSES)
    route(parser.parse_args().passes)
