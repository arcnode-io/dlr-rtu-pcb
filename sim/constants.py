"""Physical parameters for DLR carrier board design.

Mirrors theory.ipynb constants — notebook is the derivation document,
constants.py is the parameter source for sim/test_run.py.
"""

import math
from typing import Final

import pint
from uncertainties import ufloat

ureg = pint.UnitRegistry()
Q_ = ureg.Quantity

# === Battery: LiFePO4 4S ===
# Reason: 3.2V/cell nominal x 4 = 12.8V; 2.5V cutoff x 4 = 10.0V; 3.65V charge x 4 = 14.6V
V_BAT_NOM: Final = 12.8 * ureg.V
V_BAT_MIN: Final = 10.0 * ureg.V
V_BAT_MAX: Final = 14.6 * ureg.V
BAT_CAPACITY: Final = 4.0 * ureg.A * ureg.hour
BAT_USABLE_FRACTION: Final = 0.90

# === BMS — JBD-SP04S013, on-pack (off-carrier) ===
# Reason: commoditized 4S LiFePO4 protection PCB, mounts to battery pack
BMS_I_DISCHARGE_MAX: Final = 15.0 * ureg.A  # protection trip current
BMS_LOW_TEMP_CUTOFF: Final = 0.0  # degC; charging below this destroys LiFePO4 cells
BMS_QUIESCENT: Final = 150 * ureg.uA  # 0.046 Wh/day continuous battery drain

# === Buck (5V) — TI LMR33630ADDAR, HSOIC-8 ===
# Reason: LMR33630 datasheet SNVSAN3F (Aug 2017, rev Nov 2020) §7.5; 3.8-36V Vin, 3A FETs
V_RAIL_5V: Final = 5.0 * ureg.V
LMR33630_VIN_MIN: Final = 3.8 * ureg.V
LMR33630_VIN_MAX: Final = 36.0 * ureg.V
LMR33630_IOUT_RATED: Final = 3.0 * ureg.A
LMR33630_FSW: Final = 400 * ureg.kHz  # "A" version, §7.5 OSCILLATOR: 340/400/460 kHz
BUCK_EFFICIENCY: Final = ufloat(0.90, 0.03)  # LMR33630 typical curve at 12V->5V/1.5A
# §7.5 CURRENT LIMITS (open-loop production test): high-side peak ISC, low-side valley ILIMIT
LMR33630_ISC_MIN: Final = 3.85 * ureg.A
LMR33630_ISC_MAX: Final = 5.05 * ureg.A
LMR33630_ILIMIT_MIN: Final = 2.9 * ureg.A
LMR33630_ILIMIT_MAX: Final = 4.1 * ureg.A
# Reason: §8.3.? Eq 1 — Vout drops out of regulation above IOUT_max ≈ (ILIMIT + ISC) / 2
LMR33630_IOUT_MAX_MIN: Final = (LMR33630_ILIMIT_MIN + LMR33630_ISC_MIN) / 2  # 3.375 A
LMR33630_RIPPLE_K: Final = 0.3  # §9.2.2.4 recommended inductor ripple ratio
LMR33630_T_SS: Final = 4 * ureg.ms  # §7.5 SOFT START typ (2.9-6 ms)
# --- Buck passives exactly as placed in cad/netlist/power.py ---
# Reason: Bourns SRN8040TA-100M (bourns.com/docs/product-datasheets/srn8040ta.pdf) 10 uH
# ±20%, DCR 33 mΩ, Irms 4.6 A, Isat 5.0 A (L -30%). §9.2.2.4 requires Isat ≥ ILIMIT,
# ideally ≥ ISC — the earlier SRN8040-100M (Isat 3.4 A) failed that rule (ADR-014).
L_BUCK: Final = ufloat(10.0, 2.0) * ureg.uH
L_BUCK_DCR: Final = 33 * ureg.mohm
L_BUCK_ISAT: Final = 5.0 * ureg.A
L_BUCK_IRMS: Final = 4.6 * ureg.A
# Reason: 5V bulk cap absorbs CM4 boot inrush (3.92A peak) while buck stays <3A
# Nichicon PCL1A471MCL1GS: 470 uF ±20%, 10 V polymer, φ8x10 (= CP_Elec_8x10), ESR 17 mΩ @100 kHz
C_BULK_5V: Final = ufloat(470, 94) * ureg.uF
C_BULK_5V_ESR: Final = 17 * ureg.mohm
C_OUT_CER_5V: Final = 22 * ureg.uF  # 0805 X7R ceramic on the 5V rail
# Reason: assumption — 0805 22 uF X7R loses ~50% at 5 V DC bias (generic MLCC bias curve)
C_OUT_CER_DC_BIAS_DERATE: Final = 0.5
C_OUT_CER_ESR: Final = 5 * ureg.mohm  # assumption: typical 0805 MLCC at 400 kHz
C_OUT_HF_5V: Final = 100 * ureg.nF
V_RIPPLE_5V_BUDGET: Final = 50 * ureg.mV  # assumption: 1% pk-pk on the CM4 rail

# === CM4 SoM 5V input — CM4 Datasheet, Raspberry Pi Ltd, Release 4 (2026-06-30) ===
# Reason: §3.3 pin table "+5V (Input) 4.75V-5.25V"; §5.1 "+5V ... stay above 4.75V for the
# entire operation"; §6.1 hardware checklist "ideally > +4.9V including any noise"
V_5V_CM4_MIN: Final = 4.75 * ureg.V
V_5V_CM4_IDEAL_MIN: Final = 4.9 * ureg.V
I_5V_IDLE: Final = 240 * ureg.mA  # readme power budget, idle (PSM) column total
I_CM4_BOOT_PEAK: Final = (
    3000 * ureg.mA
)  # readme power budget; RPi publishes no inrush figure
# Reason: assumption — duration of the coincident boot peak (RPi unspecified); swept in theory.ipynb
T_CM4_BOOT_PEAK: Final = 1 * ureg.ms

# === LDO (3V3) — Diodes Inc AP2112K-3.3 ===
V_RAIL_3V3: Final = 3.3 * ureg.V
LDO_DROPOUT_AT_600MA: Final = 250 * ureg.mV  # AP2112K datasheet

# === LDO (3V8 cellular) — TI LP5907MFX-3.8, SOT-23-5 ===
# Reason: Quectel BG770A hardware design guide recommends LP5907; ultra-low-noise (6.5 µVrms)
V_RAIL_3V8: Final = 3.8 * ureg.V
LP5907_DROPOUT_AT_250MA: Final = 250 * ureg.mV  # LP5907 datasheet
LP5907_QUIESCENT: Final = 16 * ureg.uA

# === Level shifter (CM4 3.3V <-> BG770A 1.8V) — TI TXS0108E, TSSOP-20 ===
# Reason: 8-ch auto-direction, OD-compatible, Quectel BG770A reference design
V_RAIL_1V8: Final = 1.8 * ureg.V  # sourced from BG770A VDD_EXT output

# === Solar / power budget ===
PANEL_RATING: Final = 20 * ureg.W
PANEL_VMP: Final = 17.0 * ureg.V  # typical 12V-class 20W mono panel
PANEL_VOC: Final = 21.0 * ureg.V
SUN_HOURS_WORST: Final = 2.5 * ureg.hour  # December NE US
SUN_HOURS_AVG: Final = 4.0 * ureg.hour  # Annual avg NE US
MPPT_EFFICIENCY: Final = 0.90
I_5V_PEAK: Final = 3920 * ureg.mA
I_5V_TYPICAL: Final = 1660 * ureg.mA

# === MPPT charger — TI BQ24650RVAR, VQFN-16 ===
# Reason: BQ24650 datasheet SLUSAS9C; programmable charge V/I, true MPPT via VINREG
BQ24650_VIN_MIN: Final = 5.0 * ureg.V
BQ24650_VIN_MAX: Final = 28.0 * ureg.V
BQ24650_VFB_REF: Final = 2.1 * ureg.V  # charge voltage feedback ref
BQ24650_VINREG_REF: Final = 5.0 * ureg.V  # MPPT input regulation ref
BQ24650_ISENSE_FULL: Final = 0.04 * ureg.V  # V across R_SR at full charge current
# Reason: 0.5C charge for LiFePO4 long cycle life on 4 Ah cell = 2 A
BQ24650_I_CHARGE_TARGET: Final = 2.0 * ureg.A
# Reason: 80% of Voc keeps panel near MPP under typical irradiance
BQ24650_VINREG_TARGET: Final = (0.80 * PANEL_VOC.magnitude) * ureg.V

# === Duty cycle (1/min sample, 1/15-min TX) ===
SAMPLE_INTERVAL: Final = 1 * ureg.minute
SAMPLE_DURATION: Final = 5 * ureg.s
TX_INTERVAL: Final = 15 * ureg.minute
TX_DURATION: Final = 5 * ureg.s
I_CM4_IDLE: Final = 120 * ureg.mA
I_CM4_ACTIVE: Final = 1400 * ureg.mA
I_LEPTON_ON: Final = 150 * ureg.mA
I_BG770_PSM: Final = 1 * ureg.mA
I_BG770_TX: Final = 250 * ureg.mA
I_SENSORS_ACTIVE: Final = 9 * ureg.mA

# === I2C (UM10204 Rev 7.0 Table 10, fast mode 400 kHz) ===
V_OL_MAX: Final = 0.4 * ureg.V
I_OL_FAST: Final = 3.0 * ureg.mA
T_RISE_FAST_MAX: Final = 300 * ureg.ns
C_BUS_ESTIMATED: Final = 75 * ureg.pF
R_PULLUP: Final = 2.2 * ureg.kohm  # E24, in 967-4720 ohm range

# === FLIR Lepton SPI ===
F_SPI_MAX: Final = 20 * ureg.MHz
BW_HARMONIC_FACTOR: Final = 5  # 5x f_clk for clean edges

# === FR4 substrate + USB 2.0 ===
EPSILON_R_FR4: Final = 4.3
V_PROP_FR4: Final = 3e8 / math.sqrt(EPSILON_R_FR4) * ureg.m / ureg.s
Z_DIFF_USB_TARGET: Final = 90 * ureg.ohm
USB_SKEW_MAX: Final = 100 * ureg.ps
H_TO_GND: Final = 0.20 * ureg.mm  # F.Cu to In1.GND, 4L 1.6mm fab order
W_TRACE_USB: Final = 0.20 * ureg.mm  # 8 mil
G_GAP_USB: Final = 0.15 * ureg.mm  # 6 mil

# === RF — u.FL connector + Pi-match footprint (Hirose U.FL-R-SMT-1(10)) ===
# Reason: canonical cellular module connector; Pi-network provisioned but not populated by default
Z_RF: Final = 50.0 * ureg.ohm  # antenna feed impedance, 50 ohm microstrip from BG770A
RF_MATCH_SERIES_DEFAULT: Final = 0.0 * ureg.ohm  # default: 0R jumper, no matching
# RF_MATCH_SHUNT_INPUT, RF_MATCH_SHUNT_OUTPUT footprints provisioned, NC by default
