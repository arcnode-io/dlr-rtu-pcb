"""Cellular interface: BG770A LTE Cat-M1 + TXS0108E level shifter + u.FL antenna.

BG770A symbol stands in via the BG95-M1 part (Quectel sister module, same family pinout).
TXS0108E shifts CM4 3.3V <-> BG770A 1.8V on UART + control lines (ADR-011).
USB 2.0 D+/D- routes direct to CM4 — no shifting needed.
u.FL connector + 3-pad Pi-network footprint (ADR-012).
"""

import skidl

# Footprint shorthand
FP_C_0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_R_0402 = "Resistor_SMD:R_0402_1005Metric"


def _cap(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    c = skidl.Part("Device", "C", ref=ref, value=value, footprint=fp)
    n1 += c[1]
    n2 += c[2]


def _connect_all_named(part: skidl.Part, name: str, net: skidl.Net) -> None:
    """Connect every pin matching `name` on a multi-unit part to `net`.

    SKiDL's part[name] returns only the first match; multi-unit symbols (e.g.,
    BG95-M1 has many GND, VBAT_BB, etc.) need explicit iteration to fully wire.
    """
    for pin in part.pins:
        if pin.name == name:
            net += pin


def build_cellular(
    v3v8: skidl.Net,
    v3v3: skidl.Net,
    gnd: skidl.Net,
    usb_dp: skidl.Net,
    usb_dm: skidl.Net,
    uart_tx_cm4: skidl.Net,
    uart_rx_cm4: skidl.Net,
    pwrkey: skidl.Net,
    reset_n: skidl.Net,
    status: skidl.Net,
    net_status: skidl.Net,
    shifter_oe: skidl.Net,
) -> None:
    """Wire BG770A + level shifter + u.FL.

    All control + UART signals shift through TXS0108E; USB2 routes direct.
    """
    # Reason: BG770A symbol not in kicad libs; BG95-M1 is sister module with shared family pinout
    u_modem = skidl.Part(
        "RF_GSM",
        "BG95-M1",
        ref="U3",
        footprint="RF_GSM:Quectel_BG95",
    )
    u_modem.value = "BG770A-NA"

    v1v8 = skidl.Net("VDD_EXT_1V8")  # BG770A's 1.8V output, drives TXS0108E VccA

    # BG95-M1/BG770A has many same-named power pins across schematic units;
    # connect ALL matching pins, not just the first.
    _connect_all_named(u_modem, "VBAT_BB", v3v8)
    _connect_all_named(u_modem, "VBAT_RF", v3v8)
    _connect_all_named(u_modem, "GND", gnd)
    _connect_all_named(u_modem, "VDD_EXT", v1v8)

    # USB2 direct (no shifting — USB 2.0 spec on both sides)
    usb_dp += u_modem["USB_DP"]
    usb_dm += u_modem["USB_DM"]

    # 1.8V-side nets going into TXS0108E A pins
    cell_tx_1v8 = skidl.Net("CELL_TX_1V8")
    cell_rx_1v8 = skidl.Net("CELL_RX_1V8")
    cell_pwrkey_1v8 = skidl.Net("CELL_PWRKEY_1V8")
    cell_reset_1v8 = skidl.Net("CELL_RESET_1V8")
    cell_status_1v8 = skidl.Net("CELL_STATUS_1V8")
    cell_net_1v8 = skidl.Net("CELL_NET_1V8")

    cell_tx_1v8 += u_modem["MAIN_TXD"]
    cell_rx_1v8 += u_modem["MAIN_RXD"]
    cell_pwrkey_1v8 += u_modem["PWRKEY"]
    cell_reset_1v8 += u_modem["~{RESET}"]
    cell_status_1v8 += u_modem["STATUS"]
    cell_net_1v8 += u_modem["NET_STATUS"]

    # 4.7uF + 100nF VBAT decoupling (BG770A datasheet)
    _cap("C18", "4.7uF", FP_C_0402, v3v8, gnd)
    _cap("C19", "100nF", FP_C_0402, v3v8, gnd)
    _cap("C20", "100nF", FP_C_0402, v1v8, gnd)

    # Antenna chain: BG770A ANT_MAIN -> Pi-network -> u.FL
    ant_in = skidl.Net("ANT_IN")
    ant_match = skidl.Net("ANT_MATCH")
    ant_in += u_modem["ANT_MAIN"]

    # Pi-network footprints — series + 2 shunts; default 0R series, NC shunts (ADR-012)
    r_series = skidl.Part(
        "Device", "R", ref="R5", value="0R", footprint="Resistor_SMD:R_0402_1005Metric"
    )
    ant_in += r_series[1]
    ant_match += r_series[2]
    # Shunt input (NC by default, footprint reserved)
    c_shunt_in = skidl.Part("Device", "C", ref="C21", value="DNP", footprint=FP_C_0402)
    ant_in += c_shunt_in[1]
    gnd += c_shunt_in[2]
    # Shunt output (NC by default)
    c_shunt_out = skidl.Part("Device", "C", ref="C22", value="DNP", footprint=FP_C_0402)
    ant_match += c_shunt_out[1]
    gnd += c_shunt_out[2]

    # u.FL connector (Hirose U.FL-R-SMT-1) — ADR-012
    j_ufl = skidl.Part(
        "Connector",
        "Conn_Coaxial",
        ref="J6",
        footprint="Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
    )
    j_ufl.value = "U.FL"
    ant_match += j_ufl[1]
    gnd += j_ufl[2]

    # SIM card holder
    j_sim = skidl.Part(
        "Connector",
        "SIM_Card",
        ref="J7",
        footprint="Connector_Card:microSIM_JAE_SF53S006VCBR2000",
    )
    j_sim.value = "SIM"
    # Wire SIM — kicad SIM_Card pin names: VCC, RST, CLK, GND, VPP, I/O
    # BG95-M1 uses USIM_* prefix (per kicad lib)
    j_sim["VCC"] += u_modem["USIM_VDD"]
    j_sim["RST"] += u_modem["USIM_RST"]
    j_sim["CLK"] += u_modem["USIM_CLK"]
    j_sim["I/O"] += u_modem["USIM_DATA"]
    gnd += j_sim["GND"]
    skidl.Net("SIM_VPP") & j_sim["VPP"]  # VPP NC

    # TXS0108EPW level shifter — A=1.8V, B=3.3V
    u_lvl = skidl.Part(
        "Logic_LevelTranslator",
        "TXS0108EPW",
        ref="U4",
        footprint="Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    )
    u_lvl.value = "TXS0108E"
    _connect_all_named(u_lvl, "VCCA", v1v8)
    _connect_all_named(u_lvl, "VCCB", v3v3)
    _connect_all_named(u_lvl, "GND", gnd)
    shifter_oe += u_lvl["OE"]

    # Channel mapping: A side <-> B side
    # A1<->B1: BG770A TXD -> CM4 RXD
    cell_tx_1v8 += u_lvl["A1"]
    uart_rx_cm4 += u_lvl["B1"]
    # A2<->B2: CM4 TXD -> BG770A RXD
    cell_rx_1v8 += u_lvl["A2"]
    uart_tx_cm4 += u_lvl["B2"]
    # A3<->B3: PWRKEY (CM4 -> BG770A)
    cell_pwrkey_1v8 += u_lvl["A3"]
    pwrkey += u_lvl["B3"]
    # A4<->B4: RESET_N (CM4 -> BG770A)
    cell_reset_1v8 += u_lvl["A4"]
    reset_n += u_lvl["B4"]
    # A5<->B5: STATUS (BG770A -> CM4)
    cell_status_1v8 += u_lvl["A5"]
    status += u_lvl["B5"]
    # A6<->B6: NET_STATUS (BG770A -> CM4)
    cell_net_1v8 += u_lvl["A6"]
    net_status += u_lvl["B6"]
    # A7, A8 / B7, B8 — spare, NC
    for ch in (7, 8):
        skidl.Net(f"NC_LVL_A{ch}") & u_lvl[f"A{ch}"]
        skidl.Net(f"NC_LVL_B{ch}") & u_lvl[f"B{ch}"]

    _cap("C23", "100nF", FP_C_0402, v1v8, gnd)
    _cap("C24", "100nF", FP_C_0402, v3v3, gnd)

    # OE pull-down for boot-time isolation (ADR-011)
    r_oe = skidl.Part("Device", "R", ref="R6", value="100k", footprint=FP_R_0402)
    shifter_oe += r_oe[1]
    gnd += r_oe[2]
