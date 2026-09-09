"""DLR carrier schematic generator — block-aware placement, label-based connectivity.

Reads cad/dlr_carrier.net, classifies each component into a block (power, som,
cellular, sensors, connectors, misc), places each block's components in a
sub-grid within the block's region defined in layout_spec.yaml. Inter-block
connectivity is preserved through labels and power symbols.
"""

import contextlib
import math
from pathlib import Path
from typing import Final

import sexpdata
import yaml

LAYOUT_SPEC_PATH = Path("cad/layout_spec.yaml")
NETLIST_PATH = Path("cad/dlr_carrier.net")
SCHEMATIC_PATH = "cad/dlr_carrier.kicad_sch"

LIB_BY_PART: Final = {
    "C": "Device",
    "C_Polarized": "Device",
    "R": "Device",
    "L": "Device",
    "D_Schottky": "Device",
    "D_TVS": "Device",
    "D_TVS_Dual_AAC": "Device",
    "Polyfuse": "Device",
    "Conn_Coaxial": "Connector",
    "SIM_Card": "Connector",
    "AP2112K-3.3": "Regulator_Linear",
    "LP5907MFX-3.3": "Regulator_Linear",
    "BG95-M1": "RF_GSM",
    "TXS0108EPW": "Logic_LevelTranslator",
    "ADS1115IDGS": "Analog_ADC",
    "DHT11": "Sensor",
    "SP3485EN": "Interface_UART",
    "USB_C_Receptacle_USB2.0_14P": "Connector",
    "BQ24650": "Battery_Management",
    "LMR33630ADDA": "Regulator_Switching",
    "Q_NMOS_GSD": "Transistor_FET",
    "BAT54W": "Diode",
}

# Component value -> block (catches all uniquely-named ICs and connectors)
VALUE_TO_BLOCK: Final = {
    # power
    "PV_IN": "power",
    "SS34": "power",
    "BQ24650": "power",
    "LMR33630ADDA": "power",
    "AP2112K-3.3": "power",
    "LP5907MFX-3.8": "power",
    # som
    "CM4_J2": "som",
    # cellular
    "BG770A-NA": "cellular",
    "TXS0108E": "cellular",
    "U.FL": "cellular",
    "SIM": "cellular",
    # sensors
    "FLIR_LEPTON": "sensors",
    "FLIR_LEPTON_FFC": "sensors",
    "DHT22": "sensors",
    "SI1145": "sensors",
    "YL-83": "sensors",
    "ADS1115": "sensors",
    # connectors
    "BAT": "connectors",
    "DEBUG_UART": "connectors",
    "USBC_COMMISSIONING": "connectors",
    # anemometer
    "SP3485EN": "anemometer",
    "ANEMO_M12_5P": "anemometer",
    "SM712-like": "anemometer",
    "SMBJ24CA": "anemometer",
}

# Block-specific nets (for classifying passives that don't have unique values)
BLOCK_NETS: Final = {
    "power": {
        "PV_IN",
        "PV_RAW",
        "VBAT",
        "BAT_SRP",
        "MPPT_SW",
        "MPPT_BOOT",
        "BUCK_SW",
        "BUCK_BOOT",
        "BUCK_FB",
        "BUCK_RT",
    },
    "cellular": {
        "3V8_CELL",
        "VDD_EXT_1V8",
        "ANT_IN",
        "ANT_MATCH",
        "CELL_PWRKEY",
        "CELL_RESET",
        "CELL_STATUS",
        "CELL_NET_STATUS",
        "CELL_TX_1V8",
        "CELL_RX_1V8",
        "CELL_PWRKEY_1V8",
        "CELL_RESET_1V8",
        "CELL_STATUS_1V8",
        "CELL_NET_1V8",
    },
    "sensors": {
        "RAIN_AO",
        "GPIO4_DHT22",
        "GPIO25_VSYNC",
    },
    "connectors": {"DBG_TX", "DBG_RX"},
    "anemometer": {
        "ANEMO_RS485_A",
        "ANEMO_RS485_B",
        "ANEMO_UART_TX",
        "ANEMO_UART_RX",
        "ANEMO_DE",
        "ANEMO_V_SENSOR",
        "ANEMO_SHIELD",
    },
}

POWER_SYMBOL_BY_NET: Final = {
    "GND": "power:GND",
    "5V_RAIL": "power:+5V",
    "3V3": "power:+3V3",
}


def _real_pin_position(comp, pin_num: str):
    """Pin position in sheet coords, fixing kicad-sch-api's y-inversion bug.

    kicad-sch-api computes pin_y = sym_y + pin_offset_y, but KiCad's actual
    rendering uses pin_y = sym_y - pin_offset_y (symbol coords are +y up,
    sheet coords are +y down). Reflect ksa's reported y around sym_y to get
    the position KiCad will actually draw the pin at.

    Only valid for unrotated symbols (rotation=0). All components produced
    by _place_one are placed unrotated, so this assumption holds.
    """
    pos = comp.get_pin_position(pin_num)
    if not pos:
        return None
    sym_y = comp.position.y
    return type(pos)(pos.x, 2 * sym_y - pos.y)


def _resolve_lib(part_name: str) -> str:
    if part_name in LIB_BY_PART:
        return LIB_BY_PART[part_name]
    if part_name.startswith("Conn_01x") or part_name.startswith("Conn_02x"):
        return "Connector_Generic"
    raise ValueError(f"Unknown lib for part {part_name!r}")


def _parse_netlist(path: Path) -> tuple[list[dict], list[dict]]:  # noqa: C901
    """Extract components and nets from a SKiDL-generated kicad netlist."""
    data = sexpdata.loads(path.read_text())
    components, nets = [], []

    def s(node) -> str:
        return str(node[0]) if isinstance(node, list) and node else ""

    def find_section(root, key) -> list:
        if isinstance(root, list):
            if s(root) == key:
                return root
            for child in root:
                r = find_section(child, key)
                if r:
                    return r
        return []

    for comp in find_section(data, "components")[1:]:
        info: dict = {}
        for field in comp[1:]:
            tag = s(field)
            if tag == "ref":
                info["ref"] = field[1]
            elif tag == "value":
                info["value"] = field[1]
            elif tag == "footprint":
                info["footprint"] = field[1]
            elif tag == "libsource":
                for sub in field[1:]:
                    if s(sub) == "part":
                        info["part"] = sub[1]
            elif tag == "fields":
                # Look for SKiDL's "SKiDL Line" field — source file pinpoints block
                for sub in field[1:]:
                    if s(sub) == "field":
                        # field structure: (field (name "SKiDL Line") "power.py:17")
                        for inner in sub[1:]:
                            if (
                                isinstance(inner, list)
                                and s(inner) == "name"
                                and len(inner) > 1
                                and inner[1] == "SKiDL Line"
                                and len(sub) > 2
                                and isinstance(sub[2], str)
                            ):
                                # field structure: (field (name "SKiDL Line") "power.py:17")
                                info["source"] = sub[2]
        if info.get("ref"):
            components.append(info)

    for net in find_section(data, "nets")[1:]:
        info = {"name": "", "nodes": []}
        for field in net[1:]:
            tag = s(field)
            if tag == "name":
                info["name"] = field[1]
            elif tag == "node":
                node = {}
                for sub in field[1:]:
                    if s(sub) == "ref":
                        node["ref"] = sub[1]
                    elif s(sub) == "pin":
                        node["pin"] = sub[1]
                    elif s(sub) == "pintype":
                        node["pintype"] = sub[1]
                if node:
                    info["nodes"].append(node)
        if info["name"]:
            nets.append(info)
    return components, nets


def _comp_nets_index(nets: list[dict]) -> dict[str, set[str]]:
    """Build {ref: {net_name, ...}} for all components."""
    idx: dict[str, set[str]] = {}
    for net in nets:
        for node in net["nodes"]:
            idx.setdefault(node["ref"], set()).add(net["name"])
    return idx


SOURCE_FILE_TO_BLOCK: Final = {
    "charger.py": "charger",
    "power.py": "power",
    "som.py": "som",
    "cellular.py": "cellular",
    "sensors.py": "sensors",
    "connectors.py": "connectors",
    "anemometer.py": "anemometer",
    "model.py": "connectors",  # model.py's _build_battery_connector previously
}


def _classify(comp: dict, comp_nets: set[str]) -> str:
    """Assign component to a block by SKiDL source file, then value, then nets."""
    # Best signal: SKiDL records the source file in a field
    src = comp.get("source", "")
    for fname, block in SOURCE_FILE_TO_BLOCK.items():
        if fname in src:
            return block
    val = comp.get("value", "")
    if val in VALUE_TO_BLOCK:
        return VALUE_TO_BLOCK[val]
    scores = {
        b: sum(1 for n in comp_nets if n in nets) for b, nets in BLOCK_NETS.items()
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    if {"5V_RAIL", "3V3"} & comp_nets:
        return "power"
    return "misc"


# Reason: a cell must hold the symbol (half-extent ≤ 10 wide / ≤ 14 tall for a
# 1x14 header) plus its 8-grid stubs on both sides, so no stub can reach a
# neighbour's pin end — that is the only way two nets ever merge on a sheet.
MIN_CELL_W: Final = 40
MIN_CELL_H: Final = 50


def _grid_for_block(n: int, w: int, h: int) -> tuple[int, int, int]:
    """Choose (cols, cell_w, cell_h) so n components fit in w x h with cells ≥ MIN_CELL."""
    if n == 0:
        return 1, w, h
    cols = max(1, min(n, w // MIN_CELL_W))
    rows = math.ceil(n / cols)
    if rows * MIN_CELL_H > h:
        raise ValueError(
            f"{n} components need {rows} rows of {MIN_CELL_H}; block is {h} tall"
        )
    return cols, w // cols, h // rows


BLOCK_TITLES: Final = {
    "charger": "SOLAR MPPT CHARGER",
    # Reason: no "/" in a sheet name — kicad-cli builds the export filename from it
    "power": "POWER RAILS",
    "som": "CM4 SoM",
    "cellular": "CELLULAR",
    "sensors": "IEEE 738 SENSORS",
    "connectors": "CONNECTORS",
    "anemometer": "ANEMOMETER RS-485",
    "misc": "MISC",
}


# Components whose symbol body is much taller than typical (multi-unit / many-pin).
# They get a dedicated column on the left of their block so their pin labels
# and body don't overflow into the grid of ordinary parts.
TALL_COMPONENT_VALUES: Final = {"BG770A-NA", "CM4_J2"}
TALL_COL_WIDTH: Final = 110  # grid units — BG770A body + stubs + label text


def _place_one(sch, comp: dict, gx: int, gy: int):
    """Instantiate a single component at (gx, gy)."""
    lib_id = f"{_resolve_lib(comp['part'])}:{comp['part']}"
    c = sch.components.add(
        lib_id, comp["ref"], comp.get("value", ""), position=(gx, gy)
    )
    if comp.get("footprint"):
        c.footprint = comp["footprint"]
    return c


def _place_block(sch, block_components: list[dict], region: dict) -> dict:
    """Place tall ICs in a left column, the rest in a deterministic sub-grid.

    No jitter: placement is a pure function of the netlist, so two runs give the
    same schematic and ERC result. Cross-net safety comes from MIN_CELL_* plus
    sch_guard.check_collisions, not from randomness.
    """
    placed: dict = {}
    ox, oy = region["origin"]
    w, h = region["width"], region["height"]

    tall = [c for c in block_components if c.get("value") in TALL_COMPONENT_VALUES]
    rest = [c for c in block_components if c.get("value") not in TALL_COMPONENT_VALUES]

    rest_ox, rest_w = ox, w
    if tall:
        row_h = h // len(tall)
        for i, comp in enumerate(tall):
            gx = ox + TALL_COL_WIDTH // 2
            gy = oy + i * row_h + row_h // 2
            placed[comp["ref"]] = _place_one(sch, comp, gx, gy)
        rest_ox = ox + TALL_COL_WIDTH
        rest_w = max(MIN_CELL_W, w - TALL_COL_WIDTH)

    n = len(rest)
    if n:
        cols, cw, ch = _grid_for_block(n, rest_w, h)
        for i, comp in enumerate(rest):
            row, col = divmod(i, cols)
            gx = rest_ox + col * cw + cw // 2
            gy = oy + row * ch + ch // 2
            placed[comp["ref"]] = _place_one(sch, comp, gx, gy)
    return placed


class PwrCounter:
    """Generates unique #PWR / #FLG references for power symbols."""

    def __init__(self):
        """Init counters."""
        self.n = 1
        self.flg = 1

    def pwr_ref(self) -> str:
        """Next unique #PWR ref."""
        ref = f"#PWR{self.n:03d}"
        self.n += 1
        return ref

    def flg_ref(self) -> str:
        """Next unique #FLG ref."""
        ref = f"#FLG{self.flg:03d}"
        self.flg += 1
        return ref


def _outward_direction(comp, pin_num: str) -> tuple[int, int]:
    """Direction the pin points outward from the symbol body (dx, dy in grid units).

    Uses the pin's own rotation attribute. Convention: kicad pin rotation 0
    means the pin LINE extends rightward INTO the symbol body, so the
    connection end (outer tip) is on the LEFT. Outward direction is the
    opposite of the pin line direction.
    """
    try:
        p = comp.get_pin(pin_num)
        if not p:
            return (-1, 0)
        rot = int(p.rotation) % 360
    except Exception:
        return (-1, 0)
    if rot == 0:
        return (-1, 0)  # pin points right into body -> outward left
    if rot == 180:
        return (1, 0)  # pin points left into body  -> outward right
    if rot == 90:
        return (0, 1)  # pin points up into body    -> outward down (+y in kicad = down)
    if rot == 270:
        return (0, -1)  # pin points down into body  -> outward up
    return (-1, 0)


def _add_nc_at_pin(sch, comp, pin_num: str) -> None:
    """Place a no-connect marker at a component pin (mm coords)."""
    try:
        pos_mm = _real_pin_position(comp, pin_num)
    except Exception:
        return
    if not pos_mm:
        return
    with contextlib.suppress(Exception):
        sch.no_connects.add(position=(pos_mm.x, pos_mm.y))


def _power_driven_nets(nets: list[dict]) -> set[str]:
    """Power nets that already have a Power-output driver (regulator output).

    A PWR_FLAG on such a net would conflict with the driver — ERC sees two
    Power-output pins on one net and reports pin_to_pin. Skip them.
    """
    driven: set[str] = set()
    for net in nets:
        for node in net["nodes"]:
            ptype = node.get("pintype", "").upper().replace("_", "-")
            if "POWER-OUT" in ptype:
                driven.add(net["name"])
                break
    return driven


def _power_input_nets(nets: list[dict]) -> set[str]:
    """Nets that feed at least one power-input pin."""
    inputs: set[str] = set()
    for net in nets:
        for node in net["nodes"]:
            ptype = node.get("pintype", "").upper().replace("_", "-")
            if ptype.startswith("POWER-IN"):
                inputs.add(net["name"])
                break
    return inputs


def flag_required_nets(nets: list[dict]) -> frozenset[str]:
    """Nets ERC will call undriven: they reach a power-input pin with no power-output pin.

    Reason: a rail fed through a passive — VBAT out of the battery connector, the
    charger's VCC through its 10 ohm filter — has no Power-output pin anywhere, so
    KiCad reports power_pin_not_driven until a PWR_FLAG declares it a source.
    """
    return frozenset(_power_input_nets(nets) - _power_driven_nets(nets))


def build_schematic() -> None:
    """Top-level — emit hierarchical multi-sheet schematic.

    Root .kicad_sch holds one sheet symbol per functional block; each block
    becomes its own dlr_carrier-<block>.kicad_sch child file.
    """
    from cad.schematic.multi_sheet import build_child_sheet, cross_block_nets
    from cad.schematic.root_sheet import build_root_sheet

    spec = yaml.safe_load(LAYOUT_SPEC_PATH.read_text())
    components, nets = _parse_netlist(NETLIST_PATH)
    comp_nets = _comp_nets_index(nets)

    by_block: dict[str, list[dict]] = {}
    for comp in components:
        block = _classify(comp, comp_nets.get(comp["ref"], set()))
        by_block.setdefault(block, []).append(comp)

    cross_nets = cross_block_nets(by_block, nets)
    # Every undriven rail needs exactly one PWR_FLAG in the hierarchy. The three
    # global power nets are flagged on the POWER sheet; a local rail (VBAT, CHG_VCC)
    # is flagged on whichever sheet owns it — first sheet to route it wins.
    flag_nets = flag_required_nets(nets)
    global_flags = frozenset(set(POWER_SYMBOL_BY_NET) & flag_nets)
    local_flags = flag_nets - set(POWER_SYMBOL_BY_NET)
    flagged: set[str] = set()
    root_path = Path(SCHEMATIC_PATH)
    block_sheets: list[tuple[str, str, set[str]]] = []

    block_order = [
        "charger",
        "power",
        "som",
        "sensors",
        "cellular",
        "connectors",
        "anemometer",
        "misc",
    ]
    for block_name in block_order:
        comps = by_block.get(block_name, [])
        if not comps:
            continue
        child_filename = f"{root_path.stem}-{block_name}.kicad_sch"
        child_path = str(root_path.parent / child_filename)
        child_cross = build_child_sheet(
            block_name,
            comps,
            nets,
            cross_nets,
            child_path,
            flag_nets=(global_flags if block_name == "power" else frozenset())
            | local_flags,
            flagged=flagged,
        )
        block_sheets.append((block_name, child_filename, child_cross))

    build_root_sheet(block_sheets, str(root_path), spec["title"])


if __name__ == "__main__":
    build_schematic()
    print(f"Schematic: {SCHEMATIC_PATH}")
