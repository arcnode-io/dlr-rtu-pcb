"""Connectivity guard for generated sheets — fail fast on cross-net collisions.

KiCad merges nets when (a) two wire endpoints / pin ends coincide or (b) a pin
end lies anywhere along a wire. Across nets that is a silent short; it is what
collapsed most of the carrier's nets into +3V3 before this check existed.
"""

from __future__ import annotations

from cad.schematic.schematic import _real_pin_position

GridPt = tuple[int, int]
Wire = tuple[GridPt, GridPt, str]  # start, end, net name


def _on_segment(p: GridPt, a: GridPt, b: GridPt) -> bool:
    if a[0] == b[0] == p[0]:
        return min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    if a[1] == b[1] == p[1]:
        return min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
    return False


def pin_points(placed: dict, nets: list[dict]) -> dict[GridPt, tuple[str, str, str]]:
    """{grid point: (ref, pin, net)} for every pin of every placed component."""
    net_of = {(n["ref"], n["pin"]): net["name"] for net in nets for n in net["nodes"]}
    pts: dict[GridPt, tuple[str, str, str]] = {}
    for ref, comp in placed.items():
        try:
            pins = comp.list_pins()
        except Exception:
            continue
        for pin in pins:
            num = pin["number"]
            pos = _real_pin_position(comp, num)
            if pos:
                g = (round(pos.x / 1.27), round(pos.y / 1.27))
                pts[g] = (ref, num, net_of.get((ref, num), f"nc:{ref}.{num}"))
    return pts


def check_collisions(placed: dict, nets: list[dict], wires: list[Wire]) -> None:
    """Raise if any wire touches a pin or wire endpoint that belongs to another net.

    Also rejects a wire endpoint sitting on another net's wire mid-segment: KiCad
    does not connect that, but the drawing would look like it does.
    """
    pins = pin_points(placed, nets)
    ends: dict[GridPt, str] = {}
    for a, b, net in wires:
        for p in (a, b):
            other = ends.setdefault(p, net)
            if other != net:
                raise ValueError(f"wire endpoints of {net} and {other} coincide at {p}")
            hit = pins.get(p)
            if hit and hit[2] != net:
                raise ValueError(
                    f"wire of {net} ends on {hit[0]}.{hit[1]} ({hit[2]}) at {p}"
                )
        for g, (ref, num, pnet) in pins.items():
            if pnet != net and _on_segment(g, a, b):
                raise ValueError(
                    f"wire of {net} {a}->{b} passes over {ref}.{num} ({pnet})"
                )
    for a, b, net in wires:
        for p, pnet in ends.items():
            if pnet != net and p not in (a, b) and _on_segment(p, a, b):
                raise ValueError(
                    f"endpoint of {pnet} at {p} lies on wire of {net} {a}->{b}"
                )
