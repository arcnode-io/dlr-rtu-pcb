"""Open-loop switching model of the LMR33630 5 V buck — output ripple (SNVSAN3F Eq 7).

Ideal switch node (0 / Vin pulse at f_sw), the placed 10 uH + DCR, the output cap
bank and a resistive load. Duty is fixed at what the regulator's loop would settle
to, so the sim starts at steady state and only switching ripple remains.

Assumptions (stated per theory.ipynb §7): Rds(on) = 0 (shifts duty, not ripple
amplitude); no dead time; ESL of the caps neglected; ideal load resistor.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_H, u_Ohm, u_s, u_V

from sim.constants import L_BUCK, L_BUCK_DCR, LMR33630_FSW, V_RAIL_5V, ureg
from sim.spice_bank import add_output_bank, f

SW_EDGE_S: Final = 10e-9
STEP_S: Final = (
    10e-9  # Reason: 250 points per 2.5 us period, 100x finer than the ESR-C corner
)
SETTLE_PERIODS: Final = (
    1200  # Reason: 3 ms ≈ 2x the 2·R_load·C_out damping tau of the LC filter
)
MEASURE_PERIODS: Final = 20


def build_ripple_circuit(vin_v: float, iout_a: float) -> Circuit:
    """Buck power stage with the switch node driven as an ideal pulse source."""
    vout = f(V_RAIL_5V, ureg.V)
    period = 1.0 / f(LMR33630_FSW, ureg.Hz)
    dcr = f(L_BUCK_DCR, ureg.ohm)
    duty = (vout + iout_a * dcr) / vin_v
    inductance = f(L_BUCK, ureg.H)
    # Reason: the pulse starts on its rising edge, where the inductor current is at
    # its valley, not its average — starting at the average rings the LC filter
    d_il = (vin_v - vout) * duty / (inductance * f(LMR33630_FSW, ureg.Hz))
    c = Circuit("LMR33630 open-loop ripple")
    c.PulseVoltageSource(
        "sw",
        "sw",
        c.gnd,
        initial_value=0 @ u_V,
        pulsed_value=vin_v @ u_V,
        pulse_width=(duty * period) @ u_s,
        period=period @ u_s,
        rise_time=SW_EDGE_S @ u_s,
        fall_time=SW_EDGE_S @ u_s,
    )
    c.R("dcr", "sw", "lx", dcr @ u_Ohm)
    # Plain float, never `@ u_A`: ngspice reads a trailing "A" as atto (1e-18)
    c.L("buck", "lx", "out", inductance @ u_H, initial_condition=iout_a - d_il / 2)
    add_output_bank(c, vout)
    c.R("load", "out", c.gnd, (vout / iout_a) @ u_Ohm)
    return c


def ripple_waveform(vin_v: float, iout_a: float) -> tuple[np.ndarray, np.ndarray]:
    """Transient run; returns (t in s, V_out in V) over the settle + measure window."""
    period = 1.0 / f(LMR33630_FSW, ureg.Hz)
    sim = build_ripple_circuit(vin_v, iout_a).simulator(
        temperature=25, nominal_temperature=25
    )
    sim.initial_condition(out=f(V_RAIL_5V, ureg.V))
    analysis = sim.transient(
        step_time=STEP_S @ u_s,
        end_time=(SETTLE_PERIODS * period) @ u_s,
        max_time=STEP_S @ u_s,
        use_initial_condition=True,
    )
    return np.asarray(analysis.time, dtype=float), np.asarray(
        analysis["out"], dtype=float
    )


def simulate_buck_ripple(vin_v: float, iout_a: float) -> float:
    """Peak-to-peak 5 V rail ripple over the last MEASURE_PERIODS cycles. Returns mV."""
    period = 1.0 / f(LMR33630_FSW, ureg.Hz)
    t, v = ripple_waveform(vin_v, iout_a)
    window = v[t >= t[-1] - MEASURE_PERIODS * period]
    return float((window.max() - window.min()) * 1e3)
