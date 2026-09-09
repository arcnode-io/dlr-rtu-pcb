"""Anemometer RS-485 block — sensor-agnostic for SKU split.

One PCB carries an RS-485/Modbus port to an off-board ultrasonic anemometer.
The sensor itself is a field-replaceable SKU on the cable harness:

  high-wind variant (demo build) — Calypso ULP STD ($300, 3.3-18V, Modbus RTU)
  low-wind variant               — Vaisala WMT702 / Gill WindObserver 65
                                   ($1.5-3k, 9-30V, Modbus RTU)

VBAT (10-14.6V) feeds the sensor through a polyfuse — covers the entire
voltage range of both variants. CM4 talks via UART (TX/RX) + DE/RE GPIO for
half-duplex direction control.

Block contents:
  - SP3485EN 3.3V half-duplex RS-485 transceiver (SOIC-8)
  - 120 Ohm termination across A-B at the receiver end
  - 680 Ohm bias network (A pulled to 3V3, B to GND) — idle state
  - D_TVS_Dual_AAC across A/B to GND for surge
  - Polyfuse on V+ to sensor (250 mA hold)
  - 100 nF bypass on transceiver VCC
  - 5-pin sealed connector (V+, GND, A, B, shield)
"""

import skidl

FP_C_0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_R_0402 = "Resistor_SMD:R_0402_1005Metric"
FP_POLYFUSE = "Resistor_SMD:R_1206_3216Metric"  # miniSMDC-class polyfuse
FP_TVS = "Package_TO_SOT_SMD:SOT-23"  # SM712 dual TVS
FP_TVS_SMB = "Diode_SMD:D_SMB"  # SMBJ series = DO-214AA (SMB), 2-terminal
FP_CONN_5 = "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical"  # placeholder; M12-5P at fab
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"


def _cap(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    c = skidl.Part("Device", "C", ref=ref, value=value, footprint=fp)
    n1 += c[1]
    n2 += c[2]


def _res(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    r = skidl.Part("Device", "R", ref=ref, value=value, footprint=fp)
    n1 += r[1]
    n2 += r[2]


def build_anemometer(
    vbat: skidl.Net,
    v3v3: skidl.Net,
    gnd: skidl.Net,
    uart_tx: skidl.Net,
    uart_rx: skidl.Net,
    de_n: skidl.Net,
) -> None:
    """RS-485 anemometer interface, sensor-agnostic.

    Args:
        vbat: 10-14.6 V LiFePO4 rail (feeds sensor via polyfuse).
        v3v3: 3.3 V rail (powers SP3485EN logic).
        gnd: ground.
        uart_tx: CM4 UART TX -> SP3485 DI.
        uart_rx: SP3485 RO -> CM4 UART RX.
        de_n: CM4 GPIO -> SP3485 DE (and ~RE tied together for half-duplex).
    """
    u = skidl.Part("Interface_UART", "SP3485EN", ref="U7", footprint=FP_SOIC8)
    u.value = "SP3485EN"

    rs485_a = skidl.Net("ANEMO_RS485_A")
    rs485_b = skidl.Net("ANEMO_RS485_B")
    v_sensor = skidl.Net("ANEMO_V_SENSOR")

    # Transceiver pinout (LTC2850xS8 base):
    # 1=RO  2=~RE  3=DE  4=DI  5=GND  6=A  7=B  8=VCC
    uart_rx += u[1]
    de_n += u[2]  # tied to DE for half-duplex
    de_n += u[3]
    uart_tx += u[4]
    gnd += u[5]
    rs485_a += u[6]
    rs485_b += u[7]
    v3v3 += u[8]
    _cap("C30", "100nF", FP_C_0402, v3v3, gnd)

    # 120 Ohm termination across the differential pair (receiver end)
    _res("R14", "120", FP_R_0402, rs485_a, rs485_b)

    # Bias network — keeps idle state defined when no driver enabled
    _res("R15", "680", FP_R_0402, v3v3, rs485_a)
    _res("R16", "680", FP_R_0402, rs485_b, gnd)

    # Differential TVS on A/B to GND for surge protection
    tvs = skidl.Part("Device", "D_TVS_Dual_AAC", ref="D2", footprint=FP_TVS)
    tvs.value = "SM712-like"
    rs485_a += tvs[1]
    gnd += tvs[2]
    rs485_b += tvs[3]

    # Polyfuse on sensor V+ — 250 mA hold covers Calypso (~5 mA) and
    # Vaisala WMT702 (~30 mA) with margin.
    f = skidl.Part("Device", "Polyfuse", ref="F1", value="250mA", footprint=FP_POLYFUSE)
    vbat += f[1]
    v_sensor += f[2]

    # Lightning / surge clamp on V+ to GND — IEC 61000-4-5 2 kV combination
    # wave (42 Ω source) per utility-tower deployment. SMBJ24CA bidirectional,
    # 24 V stand-off, 38.9 V clamp @ 1 A — well below WMT702 max input 36 V.
    tvs_v = skidl.Part(
        "Device", "D_TVS", ref="D3", value="SMBJ24CA", footprint=FP_TVS_SMB
    )
    v_sensor += tvs_v[1]
    gnd += tvs_v[2]

    # 5-pin sealed connector — V+, GND, A, B, shield
    # Calypso wiring: brown=V+, white=GND, green=A, yellow=B; shield tied to GND
    # at the connector (single-point system grounding).
    j = skidl.Part(
        "Connector_Generic",
        "Conn_01x05",
        ref="J13",
        footprint=FP_CONN_5,
    )
    j.value = "ANEMO_M12_5P"
    v_sensor += j[1]
    gnd += j[2]
    rs485_a += j[3]
    rs485_b += j[4]
    gnd += j[5]
