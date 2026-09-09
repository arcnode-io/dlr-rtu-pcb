"""Sync PCB footprints and pad nets to the SKiDL netlist.

Replaces KiCad's GUI-only "Update PCB from Schematic" (F8). Source of truth is
cad/dlr_carrier.net (SKiDL) — not the drawn .kicad_sch, whose label/wire
collisions have previously collapsed most nets into +3V3 and leaked that into
the routed board.

Run with system python3 (pcbnew lives there, not in .venv):
    python3 cad/drawing/sync_pcb.py
"""

from pathlib import Path

import pcbnew

NETLIST_PATH = Path("cad/dlr_carrier.net")
PCB_PATH = Path("cad/dlr_carrier.kicad_pcb")
FP_LIB_ROOT = Path("/usr/share/kicad/footprints")
PILE_ORIGIN_MM = (100.0, 200.0)  # new parts pile here (below the board) until placed
PILE_PITCH_MM = 8.0
# Pads with no symbol pin at all: the microSIM holder's shell pads ("SH") -> GND
EXTRA_PAD_NETS = {("J7", "SH"): "GND"}


def _parse_sexpr(text: str) -> list:
    """Minimal s-expression reader — enough for a KiCad netlist."""
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(ch)
            i += 1
        elif ch == '"':
            j = text.index('"', i + 1)
            while text[j - 1] == "\\":
                j = text.index('"', j + 1)
            tokens.append(text[i + 1 : j])
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            tokens.append(text[i:j])
            i = j
    stack: list[list] = [[]]
    for tok in tokens:
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _section(node: list, key: str) -> list:
    return next(c for c in node if isinstance(c, list) and c and c[0] == key)


def _field(node: list, key: str) -> str:
    return _section(node, key)[1]


def read_netlist(path: Path) -> tuple[dict[str, dict], dict[tuple[str, str], str]]:
    """Return ({ref: {value, footprint}}, {(ref, pad): net_name}).

    Single-node nets are renamed to KiCad's `unconnected-(REF-PadN)` convention
    so DRC treats each stray pad as its own net instead of a short.
    """
    root = _parse_sexpr(path.read_text())
    comps: dict[str, dict] = {}
    for comp in _section(root, "components")[1:]:
        ref = _field(comp, "ref")
        comps[ref] = {
            "value": _field(comp, "value"),
            "footprint": _field(comp, "footprint"),
        }
    pad_nets: dict[tuple[str, str], str] = {}
    for net in _section(root, "nets")[1:]:
        name = _field(net, "name")
        nodes = [
            (_field(nd, "ref"), _field(nd, "pin"))
            for nd in net
            if isinstance(nd, list) and nd[0] == "node"
        ]
        for ref, pin in nodes:
            pad_nets[(ref, pin)] = (
                name if len(nodes) > 1 else f"unconnected-({ref}-Pad{pin})"
            )
    return comps, pad_nets


# Reason: KiCad 10's SWIG footprint loader degrades after ~70 loads in one process —
# the objects it returns start coming back as bare SwigPyObject with no FOOTPRINT
# methods. Loading each *distinct* footprint once (26 here, not 89) stays well inside
# that limit; repeats are served by the FOOTPRINT copy constructor.
_TEMPLATES: dict[str, pcbnew.FOOTPRINT] = {}


def _load_lib_footprint(fpid: str) -> pcbnew.FOOTPRINT:
    template = _TEMPLATES.get(fpid)
    if template is None:
        lib, name = fpid.split(":", 1)
        template = pcbnew.FootprintLoad(str(FP_LIB_ROOT / f"{lib}.pretty"), name)
        if template is None:
            raise FileNotFoundError(f"footprint {fpid} not in {FP_LIB_ROOT}")
        # the loader drops the library nickname; keep "Lib:Name" so re-syncs are idempotent
        template.SetFPIDAsString(fpid)
        _TEMPLATES[fpid] = template
    return pcbnew.FOOTPRINT(template)


def _ensure_net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    net = board.FindNet(name)
    if net is None:
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
    return net


def _items(container) -> list:
    # Reason: KiCad 10 SWIG iterators lack `.next()` on Python 3.14
    return [container[i] for i in range(len(container))]


def _pad_net_name(
    ref: str, pad_num: str, pad_nets: dict[tuple[str, str], str]
) -> str | None:
    if (ref, pad_num) in EXTRA_PAD_NETS:
        return EXTRA_PAD_NETS[(ref, pad_num)]
    return pad_nets.get((ref, pad_num))


def _sync_footprints(comps: dict[str, dict]) -> tuple[list[str], list[str], list[str]]:
    """Pass 1 — rebuild every footprint from the library so the board matches the netlist.

    Every footprint is finished (reference, value, position) before board.Add() takes
    ownership of it, and no wrapper obtained before a Remove/Add is touched afterwards:
    KiCad 10's SWIG bindings hand back bare SwigPyObjects once a wrapper goes stale.
    """
    board = pcbnew.LoadBoard(str(PCB_PATH))
    on_board = {fp.GetReference(): fp for fp in _items(board.Footprints())}
    old_place = {
        ref: (fp.GetPosition(), fp.GetOrientation()) for ref, fp in on_board.items()
    }

    removed = sorted(set(on_board) - set(comps))
    added = sorted(set(comps) - set(on_board))
    # Reason: rebuild every footprint from the library, not just the new ones. The
    # board is generated, so library geometry is the truth; keeping "matching"
    # footprints lets a stale pad set linger and DRC only whispers it as a
    # lib_footprint_mismatch warning. Distinct loads are cached, so this is 26
    # library reads and 89 copies.
    rebuilt = sorted(set(on_board) & set(comps))

    for ref in removed + rebuilt:
        board.Remove(board.FindFootprintByReference(ref))

    for i, ref in enumerate(rebuilt + added):
        comp = comps[ref]
        fp = _load_lib_footprint(comp["footprint"])
        fp.SetReference(ref)
        fp.SetValue(comp["value"])
        if ref in old_place:
            position, orientation = old_place[ref]
            fp.SetPosition(position)
            fp.SetOrientation(orientation)
        else:
            fp.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(PILE_ORIGIN_MM[0] + PILE_PITCH_MM * (i % 10)),
                    pcbnew.FromMM(PILE_ORIGIN_MM[1] + PILE_PITCH_MM * (i // 10)),
                )
            )
        board.Add(fp)

    board.Save(str(PCB_PATH))
    return added, rebuilt, removed


def _sync_pad_nets(comps: dict[str, dict], pad_nets: dict[tuple[str, str], str]) -> int:
    """Pass 2 — reassign every pad's net from the netlist, on a freshly loaded board."""
    board = pcbnew.LoadBoard(str(PCB_PATH))
    for ref in sorted(comps):
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise ValueError(f"{ref} missing after footprint sync")
        for pad in _items(fp.Pads()):
            name = _pad_net_name(ref, pad.GetNumber(), pad_nets)
            if name is None:
                pad.SetNetCode(0)  # paste-only EP sub-pads, mounting pads
            else:
                pad.SetNet(_ensure_net(board, name))
    board.Save(str(PCB_PATH))
    return board.GetNetCount()


def sync() -> None:
    """Make the board's footprints and pad nets match the netlist exactly."""
    comps, pad_nets = read_netlist(NETLIST_PATH)
    added, rebuilt, removed = _sync_footprints(comps)
    net_count = _sync_pad_nets(comps, pad_nets)
    print(
        f"{len(comps)} parts; new: {added}; rebuilt: {len(rebuilt)}; removed: {removed}"
    )
    print(f"nets on board: {net_count}  -> saved {PCB_PATH}")


if __name__ == "__main__":
    sync()
