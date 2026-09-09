"""CM4 SoM connector — represented as 40-pin Pi GPIO header equivalent.

Real CM4 has 2x DF40-100 board-to-board connectors (not in default kicad libs).
For netlist-stage we use Conn_02x20_Odd_Even (40 pins) with Pi-standard pinout —
sufficient for connectivity verification. Final layout uses a custom DF40-100 footprint.
"""

import skidl


def build_cm4(
    v5_in: skidl.Net,
    v3v3: skidl.Net,
    gnd: skidl.Net,
    sda: skidl.Net,
    scl: skidl.Net,
    spi_mosi: skidl.Net,
    spi_miso: skidl.Net,
    spi_sck: skidl.Net,
    spi_ce0: skidl.Net,
    uart_tx: skidl.Net,
    uart_rx: skidl.Net,
    gpio4: skidl.Net,
    gpio25: skidl.Net,
    cell_en: skidl.Net,
    usb_dp: skidl.Net,
    usb_dm: skidl.Net,
    cmsn_dp: skidl.Net,
    cmsn_dm: skidl.Net,
    pwrkey: skidl.Net,
    reset_n: skidl.Net,
    status: skidl.Net,
    net_status: skidl.Net,
    shifter_oe: skidl.Net,
    dbg_tx: skidl.Net,
    dbg_rx: skidl.Net,
    anemo_uart_tx: skidl.Net,
    anemo_uart_rx: skidl.Net,
    anemo_de_n: skidl.Net,
    chg_stat1: skidl.Net,
    chg_stat2: skidl.Net,
) -> None:
    """Wire CM4 J2 (GPIO/UART/I2C/SPI/USB2) to the carrier.

    Pin numbers follow Pi 40-pin GPIO header convention. CM4 J2 DF40 has
    different physical pin numbers but the same signal set; final layout
    requires the custom DF40-100 footprint.
    """
    j_cm4 = skidl.Part(
        "Connector_Generic",
        "Conn_02x20_Odd_Even",
        ref="J5",
        footprint="Connector_Hirose_DF40:Hirose_DF40HC(3.0)-40DS-0.4V_2x20_P0.4mm",
    )
    j_cm4.value = "CM4_J2"

    # Power rails (Pi GPIO header standard)
    v3v3 += j_cm4[1]
    v5_in += j_cm4[2]
    v5_in += j_cm4[4]
    v3v3 += j_cm4[17]
    for pin in (6, 9, 14, 20, 25, 30, 34, 39):
        gnd += j_cm4[pin]

    # I2C1 (sensors bus)
    sda += j_cm4[3]  # GPIO2
    scl += j_cm4[5]  # GPIO3

    # 1-wire DHT22 + Lepton VSYNC
    gpio4 += j_cm4[7]  # GPIO4
    gpio25 += j_cm4[22]  # GPIO25

    # UART0 to BG770A (via TXS0108E)
    uart_tx += j_cm4[8]  # GPIO14 / TXD0
    uart_rx += j_cm4[10]  # GPIO15 / RXD0

    # Cellular interface controls
    cell_en += j_cm4[11]  # GPIO17 — LP5907 EN
    net_status += j_cm4[13]  # GPIO27 — BG770A NET_STATUS (input)
    pwrkey += j_cm4[15]  # GPIO22 — BG770A PWRKEY
    reset_n += j_cm4[16]  # GPIO23 — BG770A ~{RESET}
    status += j_cm4[18]  # GPIO24 — BG770A STATUS (input)
    shifter_oe += j_cm4[29]  # GPIO5 — TXS0108E OE

    # Debug UART (UART4 on GPIO12/13 — CM4 secondary UART)
    dbg_tx += j_cm4[32]  # GPIO12 / TXD4
    dbg_rx += j_cm4[33]  # GPIO13 / RXD4

    # SPI0 — FLIR Lepton
    spi_mosi += j_cm4[19]  # GPIO10 / MOSI
    spi_miso += j_cm4[21]  # GPIO9 / MISO
    spi_sck += j_cm4[23]  # GPIO11 / SCLK
    spi_ce0 += j_cm4[24]  # GPIO8 / CE0

    # UART2 to anemometer RS-485 transceiver (dtoverlay=uart2 maps to GPIO0/1)
    anemo_uart_tx += j_cm4[27]  # GPIO0 / TXD2
    anemo_uart_rx += j_cm4[28]  # GPIO1 / RXD2
    anemo_de_n += j_cm4[31]  # GPIO6 — SP3485EN DE/~RE direction control

    # BQ24650 charge status (open drain, pulled up to 3V3 in charger.py) — telemetry
    chg_stat1 += j_cm4[12]  # GPIO18 — STAT1 low = charging
    chg_stat2 += j_cm4[26]  # GPIO7 — STAT2 low = charge complete

    # USB2 to BG770A — placeholder pins (real CM4 USB lives on J1, not GPIO header)
    usb_dp += j_cm4[38]
    usb_dm += j_cm4[40]

    # USB2 OTG → commissioning USB-C port (ADR-013)
    # Placeholder pins; real CM4 J1 has a separate OTG pair, exposed via the
    # custom DF40-100 footprint at PCB layout time.
    cmsn_dp += j_cm4[36]
    cmsn_dm += j_cm4[37]

    # 4x 100nF decoupling near connector
    for ref in ("C14", "C15", "C16", "C17"):
        c = skidl.Part(
            "Device",
            "C",
            ref=ref,
            value="100nF",
            footprint="Capacitor_SMD:C_0402_1005Metric",
        )
        v5_in += c[1]
        gnd += c[2]

    # Truly unused pins. Reason: listing a pin here that is wired above merges the
    # NC_ net into the real one and SKiDL may keep the NC_ name (ANEMO_DE became NC_CM4_31)
    skidl.Net("NC_CM4_35") & j_cm4[35]
