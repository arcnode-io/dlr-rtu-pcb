# DLR Carrier Board — Architecture Decision Records

Captures architectural and component decisions for the DLR PCB. New decisions append as ADR-NNN; supersedes are explicit. Date format ISO 8601.

## Index

| # | Decision | Class |
|---|---|---|
| 001 | Single-PCB CM4 carrier | Architecture |
| 002 | Battery — LiFePO4 4S | Architecture |
| 003 | Cellular bands — NA-only | Architecture |
| 004 | Solar panel — 20W | Architecture |
| 005 | I2C clock — 400 kHz | Architecture |
| 006 | Antenna form — u.FL + external blade | Architecture |
| 007 | 5V buck — TI LMR33630 | Component |
| 008 | MPPT charger — TI BQ24650 | Component |
| 009 | BMS — JBD-SP04S013 (on-pack) | Component |
| 010 | BG770A 3.8V LDO — TI LP5907 | Component |
| 011 | Level shifter — TI TXS0108E | Component |
| 012 | u.FL connector — Hirose U.FL-R-SMT-1(10) | Component |
| 013 | Lepton daughterboard for aim flexibility | Architecture |
| 014 | 5V buck inductor — Bourns SRN8040TA-100M | Component |
| 015 | MPPT charger support network — BQ24650 per SLUSA75B | Architecture |
| 016 | Layer stack — 4-layer SIG / GND / 5V / SIG | Architecture |
| 017 | 5V rail load sequencing — firmware constraint | Architecture |

---

## ADR-001: Single-PCB CM4 Carrier (vs Pi HAT)

**Status:** Accepted **Date:** 2026-05-08

### Context
30-yr maintenance-free transmission tower deployment, IP55 potted enclosure, IEC 60068-2-6 vibration (5–500 Hz, 2g), −20 to +85°C operating temp, solar+LiFePO4 budget. Initial readme proposed a Pi 5 HAT stack.

### Decision
Single-PCB ~100×80mm 4-layer carrier with Raspberry Pi CM4 mounted via DF40 connector pair. All cellular, sensor, and power-management circuitry on the same board.

### Rationale
- Pi 5 is consumer-grade (0–50°C) and won't survive spec'd environment
- 40-pin HAT stack is a vibration failure mode (connector fretting + lever arm)
- Stock Pi has unused HDMI/audio/USB hub circuitry burning solar budget for 30 yrs
- USB-A cellular dongles are the worst industrial connector
- Conformal-coating a Pi is messy (HDMI/USB ports = giant openings)

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Pi HAT stack | Faster iteration, fails environment spec |
| iMX6ULL or STM32MP1 SoM | More industrial pedigree, worse software ecosystem, longer integration |
| STM32H7 + PSRAM (no Linux) | Lowest power, ~6 mo firmware vs ~3 wk Python |

### Consequences
- 4-layer 1.6mm board with controlled impedance (50Ω microstrip + 90Ω diff)
- Operating temp pinned at −20 to +85°C (CM4 commercial spec)
- Cold-start heater needed below −20°C
- All schematic + layout effort owned by us

---

## ADR-002: Battery — LiFePO4 4S

**Status:** Accepted **Date:** 2026-05-08

### Context
Outdoor solar-powered RTU with 30-yr cycle life. Battery range must be compatible with downstream buck Vin.

### Decision
4S LiFePO4 pack: V_min = 10.0V, V_nom = 12.8V, V_max = 14.6V. 4 Ah cell → ~50 Wh nominal.

### Rationale
4S sits in the Vin range of common 12V-class bucks with transient margin. LiFePO4 has 90% DoD tolerance, 3000+ cycle life, and cold-temp safety (no thermal runaway risk in a sealed enclosure).

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| LiFePO4 3S (9.6V nom) | Cheaper, but 7.5V cutoff below most buck Vin specs |
| Li-ion 3S | Higher energy density, worse thermal safety |
| Lead-acid | Cheap, heavy, low cycle life, poor cold-temp |

### Consequences
- Buck must accept 10.0–14.6V continuously (1.46x ratio)
- BMS must handle 4-cell balancing + 0°C low-temp charge cutoff
- 50 Wh autonomy = 1.58 days at zero PV → flagged for upgrade to 100 Wh

---

## ADR-003: Cellular Bands — NA-Only

**Status:** Accepted **Date:** 2026-05-08

### Context
Cat-M1 RTU deployment scoped to North American utility customers initially. Module SKU + antenna selection depend on band targets.

### Decision
NA-only Cat-M1 bands: B12/B13/B71/B85 (600–960 MHz LB).

### Rationale
NA-only narrows BG770A SKU choice (BG770A-NA), reduces antenna BOM (single LB element vs multiband), avoids global certification cost (FCC/IC only).

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Global multiband | Larger antenna, dual-band cert, higher cost, premature for utility scope |
| EU + NA | Splits cert effort, no current customer pull |

### Consequences
- BG770A-NA SKU only
- Antenna spec: 600–960 MHz, ~3 dBi, single-band blade
- Future global expansion = new SKU + new antenna (acceptable)

---

## ADR-004: Solar Panel — 20W

**Status:** Accepted **Date:** 2026-05-08

### Context
Daily energy budget at 1/min sampling + 1/15-min cellular TX = 29.1 Wh/day (theory.ipynb). Need PV sizing for ≥1.5x winter margin.

### Decision
20W mono panel, ~17V Vmp, ~21V Voc.

### Rationale
20W × 2.5 sun-hours × 0.90 MPPT η = 45 Wh/day winter worst case = 1.55x margin over 29 Wh/day budget. Annual avg = 2.5x. Panel envelope (~30×40 cm, ~2 kg) is mechanically reasonable for a tower cross-arm.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| 10W panel | Insufficient — winter margin <1x |
| 30–40W panel | Larger envelope, unnecessary for IEEE 738 sample rate |

### Consequences
- MPPT charger Vin range must cover 17V Vmp comfortably (5–28V is fine)
- Panel mounting hardware sized for ~2 kg + wind/ice loading
- If sample rate ever bumps to 1Hz, panel must scale to ~125W (separate ADR)

---

## ADR-005: I2C Clock — 400 kHz

**Status:** Accepted **Date:** 2026-05-08

### Context
On-board I2C bus carries ADS1115 (0x48) + SI1145 (0x60) + 2 spare slots. Pull-up sizing depends on clock rate.

### Decision
400 kHz fast mode (UM10204 Rev 7.0).

### Rationale
ADS1115 supports up to 3.4 MHz, SI1145 up to 400 kHz. Fast mode is the highest rate the slowest device supports. With 75 pF estimated C_bus and 2.2 kΩ pull-ups, rise time = 140 ns vs 300 ns spec (53% margin).

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| 100 kHz standard mode | Larger pull-ups OK, but slower readings limit sensor poll rate headroom |
| 1 MHz fast-mode-plus | SI1145 exceeded; would force discrete buffer per device |

### Consequences
- 2.2 kΩ pull-ups on SDA/SCL (E24, in 967Ω–4.72kΩ range)
- C_bus budget: 75 pF (verify after layout)

---

## ADR-006: Antenna Form — u.FL + External Blade

**Status:** Accepted **Date:** 2026-05-08

### Context
Tower-top deployment needs reliable RF link to a Cat-M1 base station. Antenna choice trades cost vs gain vs durability.

### Decision
On-board u.FL connector → external pigtail (RG316) → N-female bulkhead → external blade antenna.

### Rationale
u.FL is the canonical cellular module connector; pigtail to N-female bulkhead gives mechanical robustness at the enclosure wall. External blade provides ~3 dBi at 600–960 MHz vs negative gain for an internal PCB trace antenna.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| On-board PCB trace antenna (Taoglas FXUB63) | No external connector, but gain too low for tower-top |
| MMCX/SMA on-board (no pigtail) | More robust mechanically, 10× footprint, overkill inside potted enclosure |
| Whip with magnetic base | Won't work on transmission tower (lattice, not steel) |

### Consequences
- 50Ω microstrip from BG770A ANT to u.FL (≤30 mm preferred per theory section 5)
- External antenna + pigtail are accessories, specified at integration time
- Pi-network footprint provisioned on-board for VSWR tuning during EVT

---

## ADR-007: 5V Buck — TI LMR33630ADDAR

**Status:** Accepted **Date:** 2026-05-08

### Context
Battery 10–14.6V → 5V/3A continuous + 3.92A boot inrush. Sits upstream of CM4 + BG770A LDO + sensors.

### Decision
TI LMR33630ADDAR, HSOIC-8, programmable Fsw=400 kHz, paired with 470 µF aluminum polymer bulk cap on 5V to absorb CM4 boot inrush.

### Rationale
3.8–36V Vin = huge headroom over 14.6V max. 3A integrated synchronous FETs, ~92% peak η, industrial −40 to +125°C, hand-solderable, ~$1.50.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| TI TPS62133 | Smaller QFN, but Vin tops at 15V — only 0.4V margin over V_BAT_MAX |
| TI TPS54331 | Asynchronous → ~80% light-load η, hurts PSM idle budget |
| LM2596 (legacy) | Cheap + ubiquitous, ~75% η wastes 25% of solar budget |
| MPS MP2459 | Undersized at <1A |

### Consequences
- Bulk cap on 5V rail is mandatory (boot inrush mitigation)
- Programmable Fsw lets us trade efficiency vs component size at layout time
- 92% efficiency vs 90% theory assumption gives small headroom in derivation

---

## ADR-008: MPPT Charger — TI BQ24650RVAR

**Status:** Accepted **Date:** 2026-05-08

### Context
20W panel input → 4S LiFePO4 charge. Needs true MPPT (not just input-voltage regulation) and adjustable charge profile.

### Decision
TI BQ24650RVAR, VQFN-16. R_SR = 20 mΩ for 2A charge (0.5C of 4 Ah cell). VINREG set to 16.8V (~80% of Voc). VFB divider gives 14.6V V_charge.

### Rationale
True MPPT buck charger via VINREG pin (not just CV input regulation). 5–28V Vin covers 17V Vmp + transients. Programmable charge V/I via resistor dividers. Industrial −40 to +85.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| LTC4015 | LiFePO4-aware + I²C telemetry, but 2× cost + 38-pin QFN, overkill |
| MP2731 | Cheap, designed for 1S phone use case — won't drive 4S/14.6V |
| CN3791 | Asian-market chip, sparse docs, max 8.4V output (2S only) |
| Discrete LT3652 + LTC4054 | Most flexible, but 2 ICs + more passives, harder to debug |

### Consequences
- Cell balancing + low-temp cutoff are NOT in BQ24650 → handled by separate BMS (ADR-009)
- TS pin can monitor pack NTC; partially overlaps with BMS — leave NC unless needed
- R_SR = 20 mΩ ±1% sense resistor required

---

## ADR-009: BMS — JBD-SP04S013 (On-Pack)

**Status:** Accepted **Date:** 2026-05-08

### Context
LiFePO4 4S pack needs cell balancing + per-cell over/undervoltage cutoff + low-temp charge inhibit (charging below 0°C destroys LiFePO4 cells permanently).

### Decision
JBD-SP04S013 (or equivalent commoditized 4S LiFePO4 BMS PCB), mounted **physically on the battery pack**, NOT on the carrier PCB. 15A continuous discharge, balancing, 0°C low-temp cutoff, ~150 µA quiescent, ~$8.

### Rationale
Designing a discrete BMS on the carrier multiplies layout complexity, MOSFET sourcing risk, and validation effort for a problem that's already commoditized. On-pack mounting means the carrier sees only `BAT+`/`BAT-` — drastically simpler PCB.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Discrete on-carrier (TI BQ77216 + dual N-FETs) | ~6 ICs + 8 FETs + 30 passives added; ~3 wks of layout + validation |
| Discrete on-carrier (Analog Devices LTC6804) | Best-in-class, $15 IC, designed for EV/grid storage — massive overkill |
| No BMS | NEVER acceptable — cell imbalance kills LiFePO4 in <100 cycles |
| Bioenno BLF-1204AS (battery + BMS combined) | Zero design effort but 3× cost, locks vendor |

### Consequences
- Carrier PCB has 2-pin battery input only (no cell sense lines, no protection FETs)
- Battery is a swappable assembly serviced separately — better 30-yr maintenance story
- BMS quiescent (150 µA × 12.8V × 24h = 0.046 Wh/day) is negligible vs 29 Wh/day budget

---

## ADR-010: BG770A 3.8V LDO — TI LP5907MFX-3.8

**Status:** Accepted **Date:** 2026-05-08

### Context
BG770A VBAT spec is 3.4–4.3V (Li-ion class). Cannot power directly from 4S battery (10–14.6V) or 5V buck. Cellular RF is sensitive to LDO ripple.

### Decision
TI LP5907MFX-3.8, SOT-23-5. Fixed 3.8V output (no resistor divider), 250 mA, 6.5 µVrms ultra-low-noise, 16 µA quiescent.

### Rationale
LP5907 is the LDO Quectel's BG770A hardware design guide explicitly recommends. Fixed 3.8V SKU exactly matches Quectel's typical, no divider drift. Ultra-low noise prevents desensing the cellular receiver.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| MPS MP2161 (3.8V buck from 5V) | Higher η, but switching noise into RF chain — needs filtering, not worth it for ~0.18 Wh/day savings |
| TPS73801 (adjustable LDO) | 1A capacity, but higher quiescent + divider drift |
| AP2112-3.3 (re-use 3V3 LDO) | Below BG770A's 3.4V minimum — TX brownouts |
| Adjustable LDO from battery direct | 12V × 250mA peak = 3.6W heat, thermally infeasible |

### Consequences
- Daily energy budget already accounts for BG770A draw at 5V-equivalent (LDO η ~80%)
- LP5907 EN pin wired to a CM4 GPIO → power-cycle option for stuck cellular state
- 250 mA capacity covers TX peaks with margin

---

## ADR-011: Level Shifter — TI TXS0108E

**Status:** Accepted **Date:** 2026-05-08

### Context
CM4 GPIO is 3.3V CMOS, BG770A I/O is 1.8V CMOS. 8 lines need shifting: TXD, RXD, PWRKEY, RESET, DTR, STATUS, NETLIGHT, RING. (USB doesn't need shifting — USB 2.0 spec on both sides.)

### Decision
TI TXS0108E, TSSOP-20. 8-channel auto-direction-sensing, OD-compatible, 1.65–5.5V on either side, ~1.2 Mbps OD / 50 Mbps push-pull.

### Rationale
Mixed signal types on BG770A side (some OD outputs) — TXS0108E handles both. Single-IC vs 16 discrete transistors. Auto-direction means no DIR pin to manage. Quectel reference designs use this part.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| TI TXB0108 | Stronger push-pull drive, but fails on OD signals — risky if STATUS/NETLIGHT are OD |
| Discrete BSS138 + 10kΩ pulls | Cheapest, but 16 transistors + 16 resistors = 50× layout area |
| 4× SN74LVC1T45 single-channel | Per-channel direction control, but 4 ICs + 4 GPIOs consumed |
| Series resistor only | Will damage BG770A inputs over time via protection diodes |

### Consequences
- VccA = 1.8V (sourced from BG770A VDD_EXT, ~50 mA available)
- VccB = 3.3V (from existing AP2112K)
- OE pin → CM4 GPIO with pull-down for boot-time isolation
- 100 nF decoupling on each Vcc

---

## ADR-012: u.FL Connector — Hirose U.FL-R-SMT-1(10) + Pi-Match

**Status:** Accepted **Date:** 2026-05-08

### Context
On-board RF chain from BG770A ANT pin to external pigtail. Form-factor decision (ADR-006) selected u.FL; this ADR pins the specific connector and matching topology.

### Decision
Hirose U.FL-R-SMT-1(10) connector + 3-pad Pi-network footprint between BG770A ANT and u.FL. Default: 0Ω series jumper, NC/NC shunts. Components populated only if EVT VSWR testing requires.

### Rationale
Hirose is the canonical industry u.FL — every cellular module reference design uses it. Pi-network footprint is free in layout space and preserves tuning option without a respin.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Molex 73412-0110 | Functionally equivalent, sometimes better-stocked, but pigtails specced for Hirose may not seat as well |
| Skip Pi-network, direct trace | One less footprint, but no recourse if VSWR is bad at EVT |
| MMCX/SMA on-board | More robust mechanically, but 10× area + 4–5× cost, overkill inside potted enclosure |

### Consequences
- 50Ω microstrip from BG770A ANT → Pi-network → u.FL center pin
- u.FL placed near board edge for pigtail clearance + 10×10mm keepout for cable bend radius
- Off-board accessories (pigtail + N-female bulkhead + blade antenna) specified at integration, not PCB design

---

## ADR-013: Lepton Daughterboard for Aim Flexibility

**Status:** Accepted **Date:** 2026-05-10

### Context
ADR-001 mandated a single-PCB carrier with all sensor, cellular, and power-management circuitry on one board, motivated by stacked-Pi-HAT vibration failures over 30-yr deployments. Cross-arm DLR deployment requires the FLIR Lepton 3.5 lens to aim at a conductor ~1.5 m below the cross-arm; with a sky-facing solar panel constraint and the lens perpendicular to the main PCB, no monolithic-board orientation satisfies both.

### Decision
Split the Lepton onto a small (~25 × 40 mm) daughterboard linked to the main PCB by a 14-pin 0.5 mm-pitch FFC. Daughterboard mounts to a sheet-metal bracket with M3 pivot + M3 arc-slot lock, allowing ±15° aim adjustment at integration time. Sealed industrial USB-C commissioning port on the main carrier provides live thermal preview to a laptop while the integrator sets aim.

### Rationale
ADR-001's spirit was to avoid stacked compute (Pi 5 HAT). A passive sensor daughterboard with no active electronics beyond the Lepton socket and decoupling is not the failure class ADR-001 was guarding against. The daughterboard inherits the 30-yr robustness of the main carrier (same conformal coat, same enclosure, same potting) and adds no compute.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Lens out the side via vertical PCB | CM4 + cellular re-layout, vibration cantilever, antenna re-route. Overkill for an optical aim problem. |
| 45° gold folding mirror inside enclosure | Field-degradation: dust, condensation, ice, biofilm. Mirror-axis drift over 30 yrs. |
| Right-angle Lepton breakout (commercial) | Locks us to a specific vendor SKU with EOL risk; still needs a daughterboard or adapter. |
| GroupGets Lepton breakout as the daughterboard | Pre-designed, but vendor EOL risk over 30 yrs and no native FFC connection — adapter board still needed. |

### Consequences
- Two PCBs in the project: `cad/dlr_carrier.*` (main) and `cad/lepton_daughter/*` (new). Two KiCad projects, two BOM/CPL files, two Gerber sets to fab; ~+$15 marginal fab cost per unit at low volume.
- J8 footprint on main PCB changes from a 14-pin 2.54 mm THT header to a Hirose FH12-14S-0.5SH FFC connector. Pin map preserves the GroupGets 14-pin Lepton breakout signal order so the schematic on the daughterboard is reusable.
- Aim is set once at integration with lockwasher + Loctite 243; no field-accessible knob (an external knob would be an IP55 / O-ring / corrosion-over-30-yrs liability).
- Sealed industrial USB-C commissioning port (J12) is mandatory — without it the integrator can't see the live thermal frame to set aim.
- ADR-001 retains force for compute and the bulk of sensor / power circuitry; ADR-013 is a scoped exception covering only the Lepton optical chain.

---

## ADR-014: 5V Buck Inductor — Bourns SRN8040TA-100M

**Status:** Accepted **Date:** 2026-09-08 **Amends:** ADR-007 (passive selection only)

### Context
The LMR33630 datasheet (SNVSAN3F §9.2.2.4) requires the inductor saturation current to be no less than the low-side current limit I_LIMIT (4.1 A max over temperature) and ideally at least the high-side limit I_SC (5.05 A max). theory.ipynb §7 checked the placed Bourns SRN8040-100M against those numbers: Isat 3.4 A, and the peak inductor current at the rated 3 A load is already 3.41 A at V_BAT_MAX. The core saturates before the regulator can limit current.

### Decision
Bourns SRN8040TA-100M: 10 µH ±20 %, Isat 5.0 A, Irms 4.6 A, DCR 33 mΩ, AEC-Q200, same 8 × 8 × 4 mm family; KiCad footprint `Inductor_SMD:L_Bourns_SRN8040TA`.

### Rationale
Same inductance, so the ripple / transient analysis in theory.ipynb §7 is unchanged; lower DCR; Isat clears the hard rule with margin and sits within 1 % of the "ideal" I_SC bound. One footprint swap, no layout topology change.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Keep SRN8040-100M | Violates the datasheet rule; saturates at rated load |
| Coilcraft XAL7030-103 / Würth WE-LHMI 10 µH | Higher Isat, but new footprint and vendor; not needed |
| 6.8 µH in the same family | Higher Isat at lower L, but K = 0.44 ripple ratio and a re-run of §7 |

### Consequences
- `sim/constants.py` L_BUCK_* and `sim/test_spice.py::TestInductorRating` encode the rule; the test fails the build if a future BOM change regresses it.
- The 3.92 A coincident boot peak still exceeds the worst-case-silicon I_OUT,max (3.375 A) — that is a load-sequencing requirement on firmware (ADR-017), not an inductor problem.

---

## ADR-015: MPPT Charger Support Network — BQ24650 per SLUSA75B

**Status:** Accepted **Date:** 2026-09-08 **Completes:** ADR-008

### Context
ADR-008 selected the BQ24650, but the netlist stood it up as a generic 16-pin connector symbol on an HVQFN footprint with a bootstrap cap, an inductor and a sense resistor — and nothing else. The BQ24650 is a *controller*, not a converter: it has no internal power FETs. As captured, the part had no switching devices, no feedback divider on VFB, no MPPSET divider, no VCC/VREF/REGN bypass, no bootstrap diode, no TS bias and a floating TERM_EN. It could not have charged a battery, and the pin numbering in the placeholder did not match the real device either.

### Decision
Real `Battery_Management:BQ24650` symbol on the TI VQFN-16 thermal-pad footprint, plus the support network the datasheet requires (`cad/netlist/charger.py`, split out of `power.py`):

| Function | Parts | Datasheet basis |
|---|---|---|
| Power stage | Q1/Q2 DMN4035L-7 (40 V, 4.6 A, SOT-23) | §9.2.2.4 — ≥40 V for a 20–28 V input |
| Bootstrap | C2 100 nF PH→BTST, D4 BAT54W REGN→BTST | pin table, REGN / BTST |
| Charge voltage | R20 297k / R21 49.9k (0.1%) → 14.60 V | Eq 1, V_FB = 2.1 V |
| MPPT set point | R18 130k / R19 10k → 16.8 V (~80% Voc) | Eq 2, V_MPPSET = 1.2 V |
| Charge current | R1 20 mΩ → 2 A; I_PRE = I_TERM = 0.2 A | Eq 3/4/5, 40 mV full-scale |
| Bias / bypass | R17 10 Ω + C31 on VCC, C32 VREF, C33 REGN | pin table |
| TS window | R22 10k / R23 15k from VREF → 0.60·VREF | §7.5 thresholds (V_HTF 47.5%, V_LTF 73.5%) |
| Termination | TERM_EN tied to VREF | pin table — must not float |
| Telemetry | STAT1/STAT2 → 10k pull-ups → CM4 GPIO18 / GPIO7 | §8.3.20 open-drain outputs |
| Output filter | L1 6.8 µH SRN8040TA (Isat 5.6 A) + C3 22 µF | Eq 12/13; §9.2.2.3 wants the LC pole in 12–17 kHz — 6.8 µH / 22 µF = 13.1 kHz |

### Rationale
Every one of these is load-bearing per the datasheet; none is decoration. The 0.1% divider on VFB is the one deliberate upgrade over the datasheet example: a 1% pair puts the LiFePO4 top-of-charge at ±150 mV, and over-voltage on LiFePO4 is a cell-life problem, not a rounding error.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Keep the placeholder | Non-functional; hides the missing FETs behind a plausible-looking netlist |
| Integrated-FET charger (e.g. BQ25703) | No external FETs, but I²C-configured and 2× the pin count for no gain here |
| AO3400A (30 V) for Q1/Q2 | Cheaper and in the KiCad library, but under-rated for a 21 V Voc panel |

### Consequences
- Charger moves to its own SKiDL module and its own schematic sheet (`SOLAR MPPT CHARGER`).
- KiCad has no symbol for the DMN4035L-7; the generic `Q_NMOS_GSD` symbol carries the MPN as its value, the same convention already used for the BG770A.
- TS is biased mid-window rather than reading a pack thermistor — ADR-009 leaves low-temperature cutoff to the on-pack BMS. If a pack NTC is ever wired to the carrier, R22/R23 become the 103AT divider from the datasheet.

---

## ADR-016: Layer Stack — 4-Layer SIG / GND / 5V / SIG

**Status:** Accepted **Date:** 2026-09-08 **Formalizes:** the 4-layer intent in ADR-001

### Context
ADR-001 and the readme describe a 4-layer 1.6 mm board with an unbroken GND plane under the Lepton SPI and a 90 Ω USB pair referenced to In1 at 0.20 mm (theory.ipynb §5). The board file that was actually routed was 2-layer with F/B ground pours, so those claims were not true of the artifact, and the 0.4 mm-pitch DF40 CM4 connector left 13 nets unrouted.

### Decision
F.Cu signal / In1.Cu full GND plane / In2.Cu full 5V_RAIL plane / B.Cu signal. 1.6 mm FR4, controlled-impedance order with 0.20 mm F.Cu→In1 prepreg. VBAT, 3V3 and the other supply nets are 0.6 mm traces on the outer layers (`power` net class). `cad/drawing/board_setup.py` applies the stack, rules and planes programmatically so every regeneration produces the same board.

### Rationale
A solid GND plane is what the SPI / USB / RF analyses assume; a 5 V plane makes the highest-current, most-distributed rail (CM4, both LDOs, Lepton) a via-drop instead of a routed trace, and lets Freerouting escape the DF40 with vias to planes rather than traces between 0.4 mm pads.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| 2-layer with pours | Cheapest fab, but the readme's impedance and plane claims are false and the DF40 does not fully route |
| 4-layer GND / GND | Better for signal integrity, but 5 V distribution reverts to traces at 3–4 A |
| 6-layer | Unnecessary for ~70 parts at this density |

### Consequences
- Fab: 4-layer order with stack-up specified; ~2× bare-board cost at prototype volume.
- DRC is run with `--refill-zones` so plane fills are part of the check.
- Ground pours on F/B are kept for stitching; islands are pruned by KiCad's island removal.

---

## ADR-017: 5V Rail Load Sequencing — Firmware Constraint

**Status:** Accepted **Date:** 2026-09-08

### Context
theory.ipynb §7 and `sim/test_spice.py` (ngspice, averaged current-mode model of the LMR33630 with SNVSAN3F §7.5 current limits and the placed 470 µF polymer bank) show that the readme's coincident 3.92 A peak — CM4 boot + Lepton shutter + modem TX — exceeds the regulator's worst-case I_OUT,max of 3.375 A. The rail falls to ≈ 3.86 V and sits under the CM4's 4.75 V floor (CM4 datasheet §5.1) for ≈ 0.9 ms of every 1 ms of coincidence. The CM4 boot peak alone (3.0 A) holds ≈ 4.95 V.

### Decision
The hardware guarantees 3.0 A transients on the 5 V rail, not 3.92 A. Firmware in `dlr-rtu-firmware` must (1) keep the BG770A disabled (LP5907 EN, GPIO17) and never trigger a Lepton shutter until CM4 boot is complete, and (2) never schedule a Lepton shutter concurrently with a modem TX burst. Handed off to the embedded engineer (`/tmp/handoff_embedded-engineer_load-sequencing.md`).

### Rationale
More output capacitance cannot fix a sustained deficit — the cap only buys time (≈ 0.2 ms per 250 mV at 0.55 A). A larger regulator (4 A-class) or a second stage would add cost and board area for a peak that is entirely avoidable in software.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| 4 A-class buck (e.g. LMR36540 / TPS5450) | Solves it in hardware; larger inductor, respin of the power block, more idle loss |
| Second bulk stage (≥ 2 mF) | Only stretches the brown-out to ~2 ms; still fails a 5 ms coincidence |
| Reduce Lepton shutter current | Not controllable — FLIR module behaviour |

### Consequences
- The readme power-budget table's "Peak" column is a worst-case sum, not a supported operating point; annotated accordingly.
- The LMR33630 internal loop crossover with ~9× the recommended C_out is unpublished; bench Bode / load-step test before production is a hard requirement (SNVSAN3F §9.2.2.5).

---

## ADR-018: Finish the Routing in Code, Not in pcbnew

**Status:** Accepted **Date:** 2026-09-09

### Context
Freerouting routes ~99% of this board and `close_gaps` closes most of the remainder, but a handful of connections always survive both. Every one of them is the same shape: a pin on a 0.4 mm-pitch DF40 or a 0.5 mm-pitch VQFN/MSOP whose only exit is straight out of its own pad, past a neighbour's 0.6 mm escape via or a 0.6 mm power trace. `close_gaps` can only draw L-shapes, so it cannot express the path even when one exists; and where no path exists, the fix is to move the neighbour, which no amount of searching will do.

Hand-routing those in pcbnew works — the interactive router shoves neighbours out of the way — but it is a GUI step, and the pipeline's whole claim is that the board is regenerated from the netlist with no GUI step. A board finished by hand cannot be rebuilt after a schematic change.

### Decision
Finish the routing in code, in three layers:

* `maze_field` / `maze_search` / `maze_escape` — a windowed A* over a 0.05 mm grid on F.Cu and B.Cu with via layer changes. Clearance comes from analytic distance fields built from the copper shapes; **only copper of other nets is an obstacle**, so a pin may leave through its own pad. Each route is checked against KiCad's own connectivity and torn out again unless the two islands really joined.
* `escape_pins` — drives that off the DRC report, widest trace first (0.25 mm, then 0.2 mm).
* `rip_up` / `rip_targets` — when a pin is boxed in, delete the blocking net's copper (or the whole fanout corner) within 1.3 mm, re-run the escape router over everything that opened up, and keep the result only if DRC comes out strictly better. Every attempt is rolled back byte for byte otherwise.

### Rationale
The stranded pins are a *placement* problem disguised as a routing problem: a 0.4 mm pad pitch only fits an escape via on every other pin, so the middle pin's via has to sit in a second, deeper row. A grid search finds that automatically once the corner is cleared, because the near via sites are already taken. Encoding that as a rip-and-retry loop with DRC as the accept test means the board is never left worse than it was found, and the whole result is reproducible from `poe layout-asm`.

### Alternatives Considered
| Option | Tradeoff |
|---|---|
| Hand-route in pcbnew (shove mode) | Works, and fast for a human; unreproducible, and the next netlist change loses it |
| Re-run Freerouting with narrower net classes | Would relieve congestion globally, but rips up and re-lays 1000+ good segments to fix 3 connections |
| 0.5 / 0.25 mm signal vias to ease the DF40 fanout | Leaves a 0.125 mm annular ring, under the 0.13 mm rule; tried and reverted (see `board_setup.py`) |
| 6-layer stack | Solves the fanout outright; roughly doubles bare-board cost for a 40-pin connector |

### Consequences
- Escapes past a fine-pitch pad neck down to 0.25 / 0.2 mm, below the `power` net class's 0.6 mm. These are millimetre-scale stubs into a pin, so the current rating of the trunk is unaffected; JLCPCB's standard 4-layer process holds 0.1 mm trace and space, so 0.2 mm is well inside it.
- `rip_up` is slow — it re-runs DRC and the escape router for every candidate — but it only runs when the board is otherwise finished.
- `stitch_planes` gained a duplicate-via guard: it used to build its work list up front, so two pads whose outward step landed on the same point each added a via there, and the drill file carried the hole several times. The guard rejects a near miss as well as an exact hit — two 0.3 mm drills 0.03 mm apart break into each other, which is worse than one hole drilled twice.
- `cad/drawing/fanout.py` assigns the escape vias up front, alternating each pad row between the inter-row gap and the back of the connector so same-side vias land 0.8 mm apart. It places all 39 of J5's escapes cleanly. It has to own its band to do that, though, and on an already-routed board the 223 tracks it clears cost more than `escape_pins` can rebuild — so it belongs before Freerouting, which is where `poe layout-asm` calls it, and that path is not yet run end to end.
- Two router defects surfaced while proving it, both now fixed: `clear_band` tested only endpoints, so a trace *crossing* the band survived and blocked four via sites; and via placement used the net-aware clearance fields, which skip same-net copper on purpose — correct for traces, wrong for drills, and it stacked 14 same-net vias. Holes are now checked without regard to net, in `via_site_is_clear` and in the router's own `hole_field`.
- The tooling took the board from 5 open connections to 2, both of them redundant ground pins on the DF40, with no clearance, short, annular-ring or hole error left. The last two are a **fanout-capacity limit, not a search failure**: a row of 0.6 mm escape vias needs 0.75 mm centre to centre, so a 0.4 mm pad pitch only fits a via on every other pin, and the 0.15 mm slot left between two adjacent vias cannot pass the 0.2 mm trace (plus 0.15 mm clearance either side) that a second, deeper row would need. Via rows have to be assigned before routing, alternating gap-side and outward; a greedy per-pin router always finishes one slot short. Closing it needs a fanout pass, 0.45 / 0.25 mm vias, or six layers — see the board-status section of readme.md.
