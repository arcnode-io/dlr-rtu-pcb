"""Off-board connectors: battery, debug UART, USB-C commissioning."""

import skidl


def build_battery_connector(vbat: skidl.Net, gnd: skidl.Net) -> None:
    """2-pin battery input — BMS lives on-pack (ADR-009), carrier sees protected pack."""
    j = skidl.Part(
        "Connector_Generic",
        "Conn_01x02",
        ref="J3",
        footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
    )
    j.value = "BAT"
    vbat += j[1]
    gnd += j[2]


def build_debug_header(
    v3v3: skidl.Net, gnd: skidl.Net, dbg_tx: skidl.Net, dbg_rx: skidl.Net
) -> None:
    """4-pin debug UART header (3V3, TX, RX, GND) for serial console."""
    j = skidl.Part(
        "Connector_Generic",
        "Conn_01x04",
        ref="J11",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    )
    j.value = "DEBUG_UART"
    v3v3 += j[1]
    dbg_tx += j[2]
    dbg_rx += j[3]
    gnd += j[4]


def build_commissioning_usbc(
    gnd: skidl.Net, usb_dp: skidl.Net, usb_dm: skidl.Net
) -> None:
    """Sealed industrial USB-C commissioning port — wired to CM4 USB2 OTG.

    Per ADR-013: integrator opens the enclosure, connects a laptop via this
    port, runs a live Lepton thermal preview, tilts the daughterboard until
    the conductor is centered with >=3 px coverage, then locks and seals.

    Production part is a sealed industrial USB-C (e.g., Bulgin PX0843 with
    screw cap, IP67) or a panel-mount M12-X bulkhead with a USB-C pigtail.
    Netlist uses the standard GCT USB4085 footprint as a placeholder.

    UFP (device) configuration: 5.1k Rd pull-downs on CC1/CC2 advertise device
    mode to the host laptop. VBUS left NC — the carrier is self-powered.
    """
    j = skidl.Part(
        "Connector",
        "USB_C_Receptacle_USB2.0_14P",
        ref="J12",
        footprint="Connector_USB:USB_C_Receptacle_GCT_USB4085",
    )
    j.value = "USBC_COMMISSIONING"

    # GND pins + shield. Reason: the shield's pin *number* changed between KiCad
    # symbol-library releases (S1 -> SH); its name is stable, so connect by name.
    for pin_num in ("A1", "A12", "B1", "B12"):
        gnd += j[pin_num]
    gnd += j["SHIELD"]

    # VBUS pins NC — carrier is self-powered, doesn't accept laptop power
    for pin_num in ("A4", "A9", "B4", "B9"):
        skidl.Net(f"NC_USBC_VBUS_{pin_num}") & j[pin_num]

    # USB 2.0 D+/D- cross-wired so the cable plugs in either orientation
    usb_dp += j["A6"]
    usb_dp += j["B6"]
    usb_dm += j["A7"]
    usb_dm += j["B7"]

    # CC1/CC2 — 5.1k Rd pull-downs for UFP (device) advertisement
    for ref, cc_pin in (("R12", "A5"), ("R13", "B5")):
        r = skidl.Part(
            "Device",
            "R",
            ref=ref,
            value="5.1k",
            footprint="Resistor_SMD:R_0402_1005Metric",
        )
        j[cc_pin] += r[1]
        gnd += r[2]
