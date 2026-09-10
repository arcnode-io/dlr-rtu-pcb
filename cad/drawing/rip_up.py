"""Rip up the copper that boxes a pin in, and let the escape router redo both.

Run with system python3 (pcbnew), after escape_pins.py:
    PYTHONPATH=. /usr/bin/python3 -m cad.drawing.rip_up

What is left after the escape router is never a long-distance problem — it is a pin on
a 0.4 or 0.5 mm-pitch part whose one exit lane is taken by a neighbour's escape via or
by a fat trace on a net that should have dropped into a plane instead. No search can
fix that without moving the neighbour, so this moves the neighbour: it deletes that
net's copper in a small disc around the stranded pin, re-runs the escape router over
everything the deletion left open, and keeps the result only if the board came out
strictly better. Anything else is rolled back byte for byte.

Every step that touches pcbnew runs in a fresh subprocess. KiCad's SWIG bindings hand
back a bare SwigPyObject after a load-edit-save-reload cycle in one interpreter, so a
long-running orchestrator has to stay out of pcbnew entirely.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
RADIUS_MM: Final = 1.3
MAX_ROUNDS: Final = 8
# Reason: past the sixth nearest net the copper is no longer what boxes the pin in,
# and every try costs a full DRC plus a routing pass.
MAX_VICTIMS: Final = 6
# Reason: escalating corner sizes, judged one at a time — the smallest that works
# disturbs the least copper.
REGION_RADII_MM: Final = (1.3, 2.0)
PYTHON: Final = [sys.executable, "-m"]


def _child(module: str, *args: str) -> str:
    """Run one of this package's modules in a fresh interpreter and return its stdout."""
    result = subprocess.run(
        [*PYTHON, module, *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
    )
    return result.stdout


def drc_report() -> dict:
    """Full DRC report for the board on disk."""
    report = Path("/tmp/dlr_ripup_drc.json")
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            str(PCB_PATH),
            "--refill-zones",
            "--format",
            "json",
            "-o",
            str(report),
        ],
        capture_output=True,
        check=True,
    )
    return json.loads(report.read_text())


def score(report: dict) -> tuple[int, int]:
    """(unconnected pairs, error-severity violations) — lower is better on both."""
    errors = sum(1 for v in report["violations"] if v["severity"] == "error")
    return len(report["unconnected_items"]), errors


def rip_and_route() -> None:
    """Try each blocker around each stranded pin; keep only what improves the board."""
    best = score(drc_report())
    print(f"start: {best[0]} unconnected, {best[1]} errors", flush=True)
    for round_number in range(1, MAX_ROUNDS + 1):
        improved = False
        for anchor in json.loads(_child("cad.drawing.rip_targets")):
            victims = anchor["victims"][:MAX_VICTIMS]
            # Reason: last resort, clear the whole fanout corner and let the router
            # lay it out again from scratch. Widening matters: a corner cleared too
            # tightly still has the neighbours-of-neighbours pinning the escapes.
            victims = [
                *victims,
                *(
                    {"code": 0, "name": f"everything within {r} mm", "radius": r}
                    for r in REGION_RADII_MM
                ),
            ]
            for victim in victims:
                backup = PCB_PATH.read_bytes()
                removed = _child(
                    "cad.drawing.rip_targets",
                    "--rip",
                    str(victim["code"]),
                    str(anchor["x"]),
                    str(anchor["y"]),
                    "--radius",
                    str(victim.get("radius", RADIUS_MM)),
                ).strip()
                print(
                    _child(
                        "cad.drawing.escape_pins",
                        "--first",
                        str(anchor["x"]),
                        str(anchor["y"]),
                    ),
                    end="",
                    flush=True,
                )
                now = score(drc_report())
                if now[0] < best[0] and now[1] <= best[1]:
                    print(
                        f"  kept: ripped {removed} of {victim['name']!r} "
                        f"near {anchor['label']} -> {now}",
                        flush=True,
                    )
                    best, improved = now, True
                    break
                PCB_PATH.write_bytes(backup)
            if improved:
                break
        if not improved:
            break
        print(
            f"round {round_number}: {best[0]} unconnected, {best[1]} errors", flush=True
        )
    print(f"final: {best[0]} unconnected, {best[1]} errors")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    rip_and_route()
