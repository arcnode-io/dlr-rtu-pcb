"""Multi-sheet hierarchical schematic emission — child sheets.

Each functional block (power, som, sensors, connectors, cellular, anemometer)
becomes its own .kicad_sch child sheet; root_sheet.py ties them together.
Cross-block nets use hierarchical labels (matched by name on the root) and
global power symbols (+5V, +3V3, GND). Intra-block nets use local labels.

Connectivity rules that keep ERC at zero (probed against KiCad 10):
  * a wire endpoint on a pin end connects; a pin end anywhere along a wire connects
  * a wire endpoint on another wire's midpoint does NOT connect
  * a PWR_FLAG wired only to a power symbol reads as "pin not connected" — the
    flag must share a wire chain with a real pin
sch_guard.check_collisions enforces the first two across nets.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Final

import kicad_sch_api as ksa

from cad.schematic.sch_guard import Wire, check_collisions
from cad.schematic.schematic import (
    BLOCK_TITLES,
    POWER_SYMBOL_BY_NET,
    PwrCounter,
    _add_nc_at_pin,
    _outward_direction,
    _place_block,
    _real_pin_position,
)

CHILD_SHEET_SIZE: Final = "A3"  # roomy per-block sheet; A3 = 420x297 mm
POWER_STUB: Final = (
    6  # grid units from pin tip to its power symbol, along the pin direction
)
FLAG_BRANCH: Final = (
    6  # grid units perpendicular from the stub midpoint to the PWR_FLAG
)
LABEL_ROTATION: Final = {(1, 0): 0, (-1, 0): 180, (0, 1): 270, (0, -1): 90}
# Hierarchical labels and the root's sheet pins must agree on electrical type
SHEET_PIN_TYPE: Final = "bidirectional"
# Direction a power symbol's graphic points at rotation 0: rails up, GND down
RAIL_DIRECTION: Final = {"GND": (0, 1)}


def _symbol_rotation(net_name: str, d: tuple[int, int]) -> int:
    """Rotation (deg, CCW) that points the power symbol along stub direction d."""
    v = RAIL_DIRECTION.get(net_name, (0, -1))
    for k in range(4):
        if v == d:
            return 90 * k
        v = (v[1], -v[0])
    raise ValueError(f"bad direction {d}")


def cross_block_nets(by_block: dict[str, list[dict]], nets: list[dict]) -> set[str]:
    """Nets whose nodes span 2+ blocks — must be hierarchical labels."""
    block_of_ref: dict[str, str] = {}
    for block, comps in by_block.items():
        for c in comps:
            block_of_ref[c["ref"]] = block

    cross: set[str] = set()
    for net in nets:
        blocks = {block_of_ref.get(n["ref"]) for n in net["nodes"]}
        blocks.discard(None)
        if len(blocks) > 1:
            cross.add(net["name"])
    return cross


def _route_power_pin(
    sch,
    pin_grid: tuple[int, int],
    d: tuple[int, int],
    net_name: str,
    pwr: PwrCounter,
    wires: list[Wire],
    flag_nets: frozenset[str],
    flagged: set[str],
) -> None:
    """Straight stub along the pin direction to a power symbol at its tip.

    Reason: stubbing "up for rails, down for GND" regardless of pin direction ran
    wires through the symbol body and over the part's other pins (L2 pin 2's
    5V_RAIL stub crossed pin 1 / BUCK_SW). Along-the-pin never crosses a pin.
    The first pin of each flag net also gets the PWR_FLAG on a perpendicular
    branch from the stub midpoint, so pin, symbol and flag share one wire chain.
    """
    sym = POWER_SYMBOL_BY_NET[net_name]
    dx, dy = d
    tip = (pin_grid[0] + dx * POWER_STUB, pin_grid[1] + dy * POWER_STUB)
    segs = [(pin_grid, tip)]
    if net_name in flag_nets and net_name not in flagged:
        mid = (
            pin_grid[0] + dx * (POWER_STUB // 2),
            pin_grid[1] + dy * (POWER_STUB // 2),
        )
        flag_pos = (mid[0] - dy * FLAG_BRANCH, mid[1] + dx * FLAG_BRANCH)
        segs = [(pin_grid, mid), (mid, tip), (mid, flag_pos)]
        sch.components.add(
            "power:PWR_FLAG", pwr.flg_ref(), "PWR_FLAG", position=flag_pos
        )
        flagged.add(net_name)
    for a, b in segs:
        sch.add_wire(start=a, end=b)
        wires.append((a, b, net_name))
    sch.components.add(
        sym,
        pwr.pwr_ref(),
        sym.split(":")[-1],
        position=tip,
        rotation=_symbol_rotation(net_name, d),
    )


def _route_pin_multi(
    sch,
    comp,
    pin_num: str,
    net_name: str,
    cross_nets: set[str],
    pwr: PwrCounter,
    wires: list[Wire],
    flag_nets: frozenset[str],
    flagged: set[str],
) -> None:
    """Stub a pin with power symbol / NC / hierarchical label / local label."""
    pin_pos_mm = _real_pin_position(comp, pin_num)
    if not pin_pos_mm:
        return
    pin_grid = (round(pin_pos_mm.x / 1.27), round(pin_pos_mm.y / 1.27))

    # NC_ / N$ prefix from SKiDL means "auto-named net". A real multi-node net
    # may carry it if SKiDL merged through an unnamed pin; cross-block analysis
    # already decided those need a label.
    if net_name.startswith(("NC_", "N$")) and net_name not in cross_nets:
        with contextlib.suppress(Exception):
            sch.no_connects.add(position=(pin_grid[0] * 1.27, pin_grid[1] * 1.27))
        return

    dx, dy = _outward_direction(comp, pin_num)
    if net_name in POWER_SYMBOL_BY_NET:
        _route_power_pin(
            sch, pin_grid, (dx, dy), net_name, pwr, wires, flag_nets, flagged
        )
        return
    stub_len = 8 if (dx > 0 or dy > 0) else 4
    label_pos = (pin_grid[0] + dx * stub_len, pin_grid[1] + dy * stub_len)
    label_rot = LABEL_ROTATION[(dx, dy)]
    if net_name in flag_nets and net_name not in flagged:
        # A local rail with no power-output driver gets its one PWR_FLAG here. The
        # stub is split at `mid` so pin, label and flag share a single wire chain —
        # a wire that merely ends on another wire's midpoint does not connect.
        mid = (pin_grid[0] + dx * (stub_len // 2), pin_grid[1] + dy * (stub_len // 2))
        flag_pos = (mid[0] - dy * FLAG_BRANCH, mid[1] + dx * FLAG_BRANCH)
        for a, b in ((pin_grid, mid), (mid, label_pos), (mid, flag_pos)):
            sch.add_wire(start=a, end=b)
            wires.append((a, b, net_name))
        sch.components.add(
            "power:PWR_FLAG", pwr.flg_ref(), "PWR_FLAG", position=flag_pos
        )
        flagged.add(net_name)
    else:
        sch.add_wire(start=pin_grid, end=label_pos)
        wires.append((pin_grid, label_pos, net_name))
    if net_name in cross_nets:
        # Hierarchical label persists to file (add_global_label is a known
        # kicad-sch-api v0.5.6 serialization bug). It does NOT honor
        # use_grid_units — convert grid -> mm here.
        sch.add_hierarchical_label(
            net_name,
            position=(label_pos[0] * 1.27, label_pos[1] * 1.27),
            # Reason: must match the sheet pin's type on the root, which is
            # bidirectional. KiCad's hier_label_mismatch check compares electrical
            # type as well as name; the library default of "input" makes every
            # cross-sheet net an error on KiCad 9 (KiCad 10 tolerates it).
            shape=SHEET_PIN_TYPE,
            rotation=label_rot,
            size=1.0,
        )
    else:
        sch.add_label(net_name, position=label_pos, rotation=label_rot, size=0.8)


def _route_sheet_nets(
    sch,
    placed: dict,
    refs: set[str],
    nets: list[dict],
    cross_nets: set[str],
    pwr: PwrCounter,
    wires: list[Wire],
    flag_nets: frozenset[str],
    flagged: set[str],
) -> tuple[set[tuple[str, str]], set[str]]:
    """Wire / NC / label every net touching this sheet. Returns (routed pins, cross nets used)."""
    routed: set[tuple[str, str]] = set()
    sheet_cross_nets: set[str] = set()
    for net in nets:
        local_nodes = [n for n in net["nodes"] if n["ref"] in refs]
        if not local_nodes:
            continue
        if len(net["nodes"]) == 1 and net["name"] not in cross_nets:
            node = local_nodes[0]
            comp = placed.get(node["ref"])
            if comp:
                _add_nc_at_pin(sch, comp, node["pin"])
                routed.add((node["ref"], node["pin"]))
            continue
        if net["name"] in cross_nets:
            sheet_cross_nets.add(net["name"])
        for node in local_nodes:
            comp = placed.get(node["ref"])
            if comp:
                _route_pin_multi(
                    sch,
                    comp,
                    node["pin"],
                    net["name"],
                    cross_nets,
                    pwr,
                    wires,
                    flag_nets,
                    flagged,
                )
                routed.add((node["ref"], node["pin"]))
    return routed, sheet_cross_nets


def build_child_sheet(
    block_name: str,
    comps: list[dict],
    nets: list[dict],
    cross_nets: set[str],
    sheet_path: str,
    flag_nets: frozenset[str] = frozenset(),
    flagged: set[str] | None = None,
    sheet_size: str = CHILD_SHEET_SIZE,
) -> set[str]:
    """Emit one functional-block sheet. Returns the signal cross-net names it exports.

    `flag_nets` are undriven rails that still need a PWR_FLAG; `flagged` carries the
    ones already placed on earlier sheets, so each net gets exactly one flag in the
    whole hierarchy.
    """
    ksa.use_grid_units(True)
    title = BLOCK_TITLES.get(block_name, block_name.upper())
    sch = ksa.create_schematic(title)
    sch.set_paper_size(sheet_size)
    sch.set_title_block(
        title=f"DLR Carrier — {title}", company="Engineering With AI", rev="1.0"
    )

    # Grid sized to A3 minus title block (~330 x 230 grid units)
    region = {"origin": [30, 30], "width": 280, "height": 200}
    placed = _place_block(sch, comps, region)

    refs = {c["ref"] for c in comps}
    pwr = PwrCounter()
    wires: list[Wire] = []
    already_flagged = set() if flagged is None else flagged
    routed, sheet_cross_nets = _route_sheet_nets(
        sch, placed, refs, nets, cross_nets, pwr, wires, flag_nets, already_flagged
    )

    for ref, comp in placed.items():
        try:
            pins = comp.list_pins()
        except Exception:
            continue
        for pin in pins:
            if (ref, pin["number"]) not in routed:
                _add_nc_at_pin(sch, comp, pin["number"])

    check_collisions(placed, nets, wires)

    sch.save_as(sheet_path)
    _promote_to_global_labels(sheet_path)
    return sheet_cross_nets - set(POWER_SYMBOL_BY_NET)


def _promote_to_global_labels(sheet_path: str) -> None:
    """Rewrite the sheet's hierarchical labels as global labels.

    Cross-sheet nets connect by name through global labels, so no sheet pins are
    needed on the root and the hierarchical pin/label pairing disappears entirely.
    That pairing was worth removing: KiCad 9 reported every one of them as a
    hier_label_mismatch with the root's pins (and then the root's labels as
    dangling), while KiCad 10 accepted them — a whole class of version-dependent
    ERC failure for a design that is flat enough not to need hierarchy.

    Written as a post-save rewrite because kicad-sch-api 0.5.6's add_global_label
    updates its internal model but never serializes the label.
    """
    path = Path(sheet_path)
    text = path.read_text().replace("(hierarchical_label ", "(global_label ")
    text = re.sub(
        r'(\(global_label "[^"]+"\s*\n\s*\(shape )\w+(\))', r"\1bidirectional\2", text
    )
    path.write_text(text)
