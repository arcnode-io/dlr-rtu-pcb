"""Board stack-up, design rules, net classes and inner power planes for the DLR carrier.

Run with system python3 (pcbnew) AFTER place_pcb.py (which clears zones) and
BEFORE the Freerouting export:   python3 cad/drawing/board_setup.py

Stack (ADR-016): F.Cu signal / In1.Cu GND plane / In2.Cu 5V_RAIL plane / B.Cu signal,
1.6 mm FR4, 0.2 mm prepreg F.Cu->In1 for the USB 90 Ω pair (theory.ipynb §5).

Reason for the rule values: KiCad's library MSOP-10 / DF40 footprints have 0.15 mm
pad gaps, so 0.2 mm default clearance fails DRC inside the footprint. JLCPCB 4-layer
capability is 0.09 mm trace/space, so 0.15 mm carries margin.
"""

from pathlib import Path
from typing import Final

import pcbnew

PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")

COPPER_LAYERS: Final = 4
CLEARANCE_MM: Final = 0.15
TRACK_SIGNAL_MM: Final = 0.2
TRACK_POWER_MM: Final = (
    0.6  # Reason: ~1.5 A continuous per IPC-2221 outer layer; planes carry the rest
)
# Reason: 0.6/0.3 mm keeps a 0.15 mm annular ring, which is both KiCad's default
# minimum and every fab's cheapest tier. A 0.5/0.25 mm via was tried to ease fanout
# from the 0.4 mm-pitch DF40 — it left a 0.125 mm ring, so DRC failed 115 vias and
# it did not close the escapes anyway.
VIA_DIAMETER_MM: Final = 0.6
VIA_DRILL_MM: Final = 0.3
VIA_POWER_DIAMETER_MM: Final = 0.6
VIA_POWER_DRILL_MM: Final = 0.3
PLANE_INSET_MM: Final = 0.5
PLANES: Final = {"GND": pcbnew.In1_Cu, "5V_RAIL": pcbnew.In2_Cu}
POWER_NETS: Final = (
    "VBAT",
    "5V_RAIL",
    "3V3",
    "3V8_CELL",
    "GND",
    "PV_IN",
    "PV_RAW",
    "BAT_SRP",
    "MPPT_SW",
    "BUCK_SW",
    "ANEMO_V_SENSOR",
)


def _netclass(
    name: str, track_mm: float, via_mm: float, drill_mm: float
) -> pcbnew.NETCLASS:
    nc = pcbnew.NETCLASS(name)
    nc.SetClearance(pcbnew.FromMM(CLEARANCE_MM))
    nc.SetTrackWidth(pcbnew.FromMM(track_mm))
    nc.SetViaDiameter(pcbnew.FromMM(via_mm))
    nc.SetViaDrill(pcbnew.FromMM(drill_mm))
    return nc


def _add_plane(board: pcbnew.BOARD, net_name: str, layer: int) -> None:
    net = board.FindNet(net_name)
    if net is None:
        raise ValueError(f"net {net_name} not on board — run sync_pcb.py first")
    bb = board.GetBoardEdgesBoundingBox()
    inset = pcbnew.FromMM(PLANE_INSET_MM)
    zone = pcbnew.ZONE(board)
    zone.SetNet(net)
    zone.SetLayer(layer)
    zone.SetZoneName(f"{net_name}_plane")
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in (
        (bb.GetLeft() + inset, bb.GetTop() + inset),
        (bb.GetRight() - inset, bb.GetTop() + inset),
        (bb.GetRight() - inset, bb.GetBottom() - inset),
        (bb.GetLeft() + inset, bb.GetBottom() - inset),
    ):
        outline.Append(x, y)
    board.Add(zone)


def setup() -> None:
    """Apply stack-up, constraints, net classes and inner planes; save."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    board.SetCopperLayerCount(COPPER_LAYERS)
    ds = board.GetDesignSettings()
    ds.m_MinClearance = pcbnew.FromMM(CLEARANCE_MM)
    ds.m_TrackMinWidth = pcbnew.FromMM(TRACK_SIGNAL_MM)
    ds.m_ViasMinSize = pcbnew.FromMM(VIA_DIAMETER_MM)
    ds.m_MinThroughDrill = pcbnew.FromMM(VIA_DRILL_MM)
    # Reason: 0402 pads cannot always get two thermal spokes from a plane
    ds.m_MinResolvedSpokes = 1

    ns = ds.m_NetSettings
    ns.SetDefaultNetclass(
        _netclass("Default", TRACK_SIGNAL_MM, VIA_DIAMETER_MM, VIA_DRILL_MM)
    )
    ns.SetNetclass(
        "power",
        _netclass("power", TRACK_POWER_MM, VIA_POWER_DIAMETER_MM, VIA_POWER_DRILL_MM),
    )
    ns.ClearNetclassPatternAssignments()
    for net in POWER_NETS:
        ns.SetNetclassPatternAssignment(net, "power")
    ns.RecomputeEffectiveNetclasses()

    for net_name, layer in PLANES.items():
        _add_plane(board, net_name, layer)

    board.Save(str(PCB_PATH))
    print(
        f"{COPPER_LAYERS} copper layers; planes {list(PLANES)}; clearance {CLEARANCE_MM} mm; "
        f"signal {TRACK_SIGNAL_MM} mm / power {TRACK_POWER_MM} mm on {len(POWER_NETS)} nets"
    )


if __name__ == "__main__":
    setup()
