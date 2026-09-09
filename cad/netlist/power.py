"""Rails downstream of the battery: LMR33630 5V buck -> AP2112K 3V3 + LP5907 3V8.

The solar input and MPPT charger live in charger.py. Battery is a 2-pin connector —
the BMS is on-pack (ADR-009), so the carrier sees only BAT+ / BAT-.

LMR33630 programming (SNVSAN3F):
  Eq 3  V_OUT = 1 V x (1 + R_FBT/R_FBB)   -> 100k / 24.9k = 5.02 V (datasheet's own
        5 V example values; the previous 39.2k/10k divider gave 4.92 V, i.e. -1.6%
        before tolerances, eating most of the CM4's -5% window)
  f_sw is fixed by the part suffix — "A" = 400 kHz. The HSOIC-8 has no RT pin.
"""

import skidl

# Footprint shorthand
FP_C_0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C_0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_C_1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_R_0402 = "Resistor_SMD:R_0402_1005Metric"


def _cap(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    """Place a 2-pin capacitor between n1 and n2."""
    c = skidl.Part("Device", "C", ref=ref, value=value, footprint=fp)
    n1 += c[1]
    n2 += c[2]


def _res(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    """Place a 2-pin resistor between n1 and n2."""
    r = skidl.Part("Device", "R", ref=ref, value=value, footprint=fp)
    n1 += r[1]
    n2 += r[2]


def build_buck_5v(vbat: skidl.Net, v5_rail: skidl.Net, gnd: skidl.Net) -> None:
    """LMR33630 sync buck: 10-14.6V Vbat -> 5V/3A. 470uF polymer bulk on the output."""
    u = skidl.Part(
        "Regulator_Switching",
        "LMR33630ADDA",
        ref="U9",
        footprint="Package_SO:Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm_ThermalVias",
    )
    u.value = "LMR33630ADDA"

    vbat += u["VIN"]
    vbat += u["EN"]  # EN tied to VIN — always-on
    for pin in u.pins:
        if pin.name == "GND":  # PGND pin 1 and the AGND/thermal pad pin 9
            gnd += pin
    skidl.Net("NC_BUCK_PG") & u["PG"]

    sw = skidl.Net("BUCK_SW")
    boot = skidl.Net("BUCK_BOOT")
    fb = skidl.Net("BUCK_FB")
    vcc = skidl.Net("BUCK_VCC")
    sw += u["SW"]
    boot += u["BOOT"]
    fb += u["FB"]
    vcc += u["VCC"]

    # Input bypass per §9.2.2.6: >= 10 uF ceramic + a small-case 220 nF at the pin
    _cap("C4", "10uF", FP_C_1206, vbat, gnd)
    _cap("C5", "220nF", FP_C_0402, vbat, gnd)
    _cap("C6", "100nF", FP_C_0402, boot, sw)
    # VCC internal-LDO output — §9.2.2.8 requires a 1 uF ceramic to GND
    _cap("C36", "1uF", FP_C_0402, vcc, gnd)

    # Bourns SRN8040TA-100M: 10 uH, Isat 5.0 A, Irms 4.6 A, DCR 33 mΩ (ADR-014).
    # Reason: SNVSAN3F §9.2.2.4 needs Isat ≥ ILIMIT (4.1 A max), ideally ≥ ISC (5.05 A)
    ind = skidl.Part(
        "Device",
        "L",
        ref="L2",
        value="10uH",
        footprint="Inductor_SMD:L_Bourns_SRN8040TA",
    )
    sw += ind[1]
    v5_rail += ind[2]

    # FB divider (Eq 3): 1 V x (1 + 100k/24.9k) = 5.02 V — the datasheet's 5 V pair
    _res("R2", "100k", FP_R_0402, v5_rail, fb)
    _res("R3", "24.9k", FP_R_0402, fb, gnd)

    # Reason: no RT pin exists on the HSOIC-8 (SNVSAN3F Table 6-1) — f_sw is set by
    # the version suffix, "A" = 400 kHz. The placeholder schematic had invented one
    # and hung a 47k resistor off it.

    # Output: 470uF polymer bulk (Nichicon PCL1A471MCL1GS, ESR 17 mOhm) + ceramics.
    # Sizing and the resulting transient behaviour are derived in theory.ipynb §7.
    c_bulk = skidl.Part(
        "Device",
        "C_Polarized",
        ref="C7",
        value="470uF",
        footprint="Capacitor_SMD:CP_Elec_8x10",
    )
    v5_rail += c_bulk[1]
    gnd += c_bulk[2]
    _cap("C8", "22uF", FP_C_0805, v5_rail, gnd)
    _cap("C9", "100nF", FP_C_0402, v5_rail, gnd)


def _build_fixed_ldo(
    sym: str,
    label: str,
    refs: tuple[str, str, str],
    vin: skidl.Net,
    vout: skidl.Net,
    en: skidl.Net,
    gnd: skidl.Net,
) -> None:
    """Generic fixed-voltage LDO in SOT-23-5. Pins by number — AP2112K and LP5907 share layout.

    1=VIN, 2=GND, 3=EN, 4=NC, 5=VOUT. refs = (regulator, C_in, C_out).
    """
    u_ref, cin_ref, cout_ref = refs
    u = skidl.Part(
        "Regulator_Linear", sym, ref=u_ref, footprint="Package_TO_SOT_SMD:SOT-23-5"
    )
    u.value = label
    vin += u[1]
    gnd += u[2]
    en += u[3]
    skidl.Net(f"NC_{label}") & u[4]
    vout += u[5]
    _cap(cin_ref, "1uF", FP_C_0402, vin, gnd)
    _cap(cout_ref, "1uF", FP_C_0402, vout, gnd)


def build_ldo_3v3(v5: skidl.Net, v3v3: skidl.Net, gnd: skidl.Net) -> None:
    """AP2112K-3.3 LDO — 5V -> 3.3V/600mA for sensor analog front-end. Always-on."""
    _build_fixed_ldo(
        "AP2112K-3.3", "AP2112K-3.3", ("U1", "C10", "C11"), v5, v3v3, v5, gnd
    )


def build_ldo_3v8(
    v5: skidl.Net, v3v8: skidl.Net, en: skidl.Net, gnd: skidl.Net
) -> None:
    """LP5907-3.8 LDO — 5V -> 3.8V/250mA for BG770A VBAT (ADR-010). EN from CM4 GPIO."""
    # Reason: LP5907MFX-3.8 symbol not in default kicad libs; -3.3 symbol with -3.8 value
    _build_fixed_ldo(
        "LP5907MFX-3.3", "LP5907MFX-3.8", ("U2", "C12", "C13"), v5, v3v8, en, gnd
    )
