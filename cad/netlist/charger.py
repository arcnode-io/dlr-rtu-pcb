"""Solar input + MPPT battery charger: PV -> BQ24650 -> LiFePO4 4S.

TI BQ24650RVAR, datasheet SLUSA75B (Jul 2010, rev Jan 2020). Unlike the rest of
the power chain the charger is a *controller*, not a converter: it drives two
external N-channel FETs, so the support network below is not optional decoration
— without the FETs, the bootstrap, REGN/VREF/VCC bypass, the sense filter and
both feedback dividers the part does nothing.

Programming (all from the datasheet's own equations):
  Eq 1  V_BAT   = 2.1 V x (1 + R_FBT/R_FBB)      -> 14.6 V charge top (LiFePO4 4S)
  Eq 2  V_MPPSET= 1.2 V x (1 + R_MPT/R_MPB)      -> 16.8 V input regulation (~80% Voc)
  Eq 3  I_CHG   = 40 mV / R_SR                   -> 2 A (0.5C of the 4 Ah pack)
  Eq 4/5 I_PRE  = I_TERM = 4 mV / R_SR           -> 0.2 A
TS is held mid-window by a divider (ADR-009: the on-pack BMS owns low-temp cutoff),
because the pin cannot float — out-of-range TS inhibits charging.
"""

import skidl

FP_C_0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C_0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_C_1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_R_0402 = "Resistor_SMD:R_0402_1005Metric"
FP_R_1206 = "Resistor_SMD:R_1206_3216Metric"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"


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


def build_solar_input(pv_in: skidl.Net, gnd: skidl.Net) -> None:
    """2-pin PV screw terminal + reverse-polarity Schottky + input bulk."""
    j_pv = skidl.Part(
        "Connector_Generic",
        "Conn_01x02",
        ref="J1",
        footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
    )
    j_pv.value = "PV_IN"
    pv_raw = skidl.Net("PV_RAW")
    pv_raw += j_pv[1]
    gnd += j_pv[2]

    # SS34: 40V/3A Schottky for reverse-polarity protection
    d_rp = skidl.Part("Device", "D_Schottky", ref="D1", footprint="Diode_SMD:D_SMA")
    d_rp.value = "SS34"
    pv_raw += d_rp["A"]
    pv_in += d_rp["K"]
    # Reason: SLUSA75B §9.2.2.2 wants >= 20 uF rated >= 25 V at the FET drain for a
    # 21 V panel; 50 V X7R keeps DC-bias derating tolerable
    _cap("C1", "22uF", FP_C_1206, pv_in, gnd)


def build_mppt_charger(
    pv_in: skidl.Net,
    vbat: skidl.Net,
    gnd: skidl.Net,
    v3v3: skidl.Net,
    stat1: skidl.Net,
    stat2: skidl.Net,
) -> None:
    """BQ24650 synchronous MPPT charger: 21 V panel -> 14.6 V / 2 A into 4S LiFePO4."""
    u = skidl.Part(
        "Battery_Management",
        "BQ24650",
        ref="U8",
        footprint=(
            "Package_DFN_QFN:Texas_RVA_VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.14x2.14mm_ThermalVias"
        ),
    )
    u.value = "BQ24650RVAR"

    vcc = skidl.Net("CHG_VCC")
    vref = skidl.Net("CHG_VREF")
    regn = skidl.Net("CHG_REGN")
    btst = skidl.Net("CHG_BTST")
    ph = skidl.Net("MPPT_SW")
    hidrv = skidl.Net("CHG_HIDRV")
    lodrv = skidl.Net("CHG_LODRV")
    mppset = skidl.Net("CHG_MPPSET")
    vfb = skidl.Net("CHG_VFB")
    ts = skidl.Net("CHG_TS")
    srp = skidl.Net("BAT_SRP")

    # Pin 11 power ground and pin 17 thermal pad are both GND; part["GND"] returns
    # only the first match, so connect every same-named pin explicitly.
    for pin in u.pins:
        if pin.name == "GND":
            gnd += pin

    # VCC: 10R from the panel rail + 1uF close to the pin (pin-function table)
    _res("R17", "10", FP_R_0402, pv_in, vcc)
    vcc += u["VCC"]
    _cap("C31", "1uF", FP_C_0402, vcc, gnd)

    # MPPSET (Eq 2): 1.2 V x (1 + 130k/10k) = 16.8 V input regulation, ~80% of 21 V Voc
    _res("R18", "130k", FP_R_0402, pv_in, mppset)
    _res("R19", "10k", FP_R_0402, mppset, gnd)
    mppset += u["MPPSET"]

    # VFB (Eq 1): 2.1 V x (1 + 297k/49.9k) = 14.60 V charge top. 0.1% parts —
    # Reason: a 1% divider puts the LiFePO4 top-of-charge +-150 mV, which is cell-damaging
    _res("R20", "297k", FP_R_0402, vbat, vfb)
    _res("R21", "49.9k", FP_R_0402, vfb, gnd)
    vfb += u["VFB"]

    # VREF / REGN bypass (pin-function table: 1uF each, close to the pin)
    vref += u["VREF"]
    _cap("C32", "1uF", FP_C_0402, vref, gnd)
    regn += u["REGN"]
    _cap("C33", "1uF", FP_C_0402, regn, gnd)

    # TERM_EN tied to VREF -> charge termination enabled (pin cannot float)
    vref += u["TERM_EN"]

    # TS held mid-window: 10k/15k from VREF gives 0.60 x VREF, inside the valid
    # band (VHTF 47.5% .. VLTF 73.5%). ADR-009: the on-pack BMS owns low-temp cutoff.
    _res("R22", "10k", FP_R_0402, vref, ts)
    _res("R23", "15k", FP_R_0402, ts, gnd)
    ts += u["TS"]

    # Charge-status open-drain outputs -> 3V3 pull-ups -> CM4 GPIO (telemetry)
    stat1 += u["STAT1"]
    stat2 += u["STAT2"]
    _res("R24", "10k", FP_R_0402, v3v3, stat1)
    _res("R25", "10k", FP_R_0402, v3v3, stat2)

    # Gate drive + bootstrap. BAT54W from REGN to BTST recharges the bootstrap cap
    # while the low-side FET conducts (pin-function table, REGN).
    hidrv += u["HIDRV"]
    lodrv += u["LODRV"]
    btst += u["BTST"]
    ph += u["PH"]
    _cap("C2", "100nF", FP_C_0402, btst, ph)
    d_boot = skidl.Part(
        "Diode", "BAT54W", ref="D4", footprint="Package_TO_SOT_SMD:SOT-323_SC-70"
    )
    d_boot.value = "BAT54W"
    regn += d_boot["A"]
    btst += d_boot["K"]

    # Synchronous power stage. DMN4035L-7: 40 V / 4.6 A N-channel in SOT-23 —
    # Reason: SLUSA75B §9.2.2.4 wants >= 40 V for a 20-28 V input; the panel's
    # 21 V Voc sits in that band, so a 30 V part (e.g. AO3400A) is under-rated.
    # KiCad has no symbol for this MPN; the generic G/S/D symbol carries the real
    # part in its value, same convention as the BG770A stand-in in cellular.py.
    q_hi = skidl.Part("Transistor_FET", "Q_NMOS_GSD", ref="Q1", footprint=FP_SOT23)
    q_hi.value = "DMN4035L-7"
    q_lo = skidl.Part("Transistor_FET", "Q_NMOS_GSD", ref="Q2", footprint=FP_SOT23)
    q_lo.value = "DMN4035L-7"
    hidrv += q_hi["G"]
    pv_in += q_hi["D"]
    ph += q_hi["S"]
    lodrv += q_lo["G"]
    ph += q_lo["D"]
    gnd += q_lo["S"]

    # Output inductor. SRN8040TA-6R8M: 6.8 uH, Isat 5.6 A, Irms 5.1 A.
    # Reason: Eq 13 ripple at V_IN=21 V / V_BAT=14.6 V, 600 kHz -> 0.71 A pk-pk
    # (35% of the 2 A charge current, inside the datasheet's 20-40% band);
    # Eq 12 needs Isat >= I_CHG + ripple/2 = 2.36 A.
    ind = skidl.Part(
        "Device",
        "L",
        ref="L1",
        value="6.8uH",
        footprint="Inductor_SMD:L_Bourns_SRN8040TA",
    )
    ph += ind[1]
    srp += ind[2]

    # Charge-current sense (Eq 3): 40 mV / 20 mOhm = 2 A. 1% 1206 for the power rating.
    r_sense = skidl.Part("Device", "R", ref="R1", value="20m", footprint=FP_R_1206)
    srp += r_sense[1]
    vbat += r_sense[2]
    srp += u["SRP"]
    vbat += u["SRN"]

    # Sense filtering per the SRP/SRN pin-function entries
    _cap("C34", "100nF", FP_C_0402, srp, vbat)  # differential
    _cap("C35", "100nF", FP_C_0402, vbat, gnd)  # common mode

    # Charger output bulk (§9.2.2.3): keep the LC resonance in the 12-17 kHz band
    # the internal compensator expects — 6.8 uH with 22 uF gives 13.1 kHz.
    _cap("C3", "22uF", FP_C_1206, vbat, gnd)
