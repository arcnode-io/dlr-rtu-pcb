"""Averaged current-mode model of the LMR33630 5 V buck — CM4 boot-peak droop.

Control nodes carry amps as volts (1 V == 1 A): a PI voltage loop produces a
current command, clamped at the datasheet output-current limit; the "inductor"
current tracks it with a short time constant and the di/dt that L allows at this
Vin / Vout; that current feeds the real output cap bank while a PWL load pulses
through the boot peak.

Assumptions (stated per theory.ipynb §7): the LMR33630's internal compensation is
not published — loop crossover f_c is a parameter; switching ripple ignored
(see spice_ripple); ESL neglected; load is an ideal current sink.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
from pydantic import BaseModel
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_F, u_Ohm, u_s

from sim.constants import L_BUCK, V_5V_CM4_MIN, V_RAIL_5V, ureg
from sim.spice_bank import add_output_bank, c_out_total_f, f

LOOP_ZERO_RATIO: Final = 10  # PI zero one decade below crossover
CURRENT_LOOP_TAU_S: Final = (
    5e-6  # Reason: current-mode inner loop settles in ~2 switching cycles
)
MAX_STEP_S: Final = 0.5e-6  # Reason: 10x finer than the current-loop tau
LOAD_EDGE_S: Final = 10e-6
T0_S: Final = 1e-3
TAIL_S: Final = 2e-3


class LoadStepResult(BaseModel):
    """Worst point of the 5 V rail during a load step."""

    v_min_v: float
    t_below_floor_ms: float


def build_load_step_circuit(
    vin_v: float,
    i_lim_a: float,
    f_c_hz: float,
    i_idle_a: float,
    i_peak_a: float,
    t_peak_s: float,
) -> Circuit:
    """Averaged converter + cap bank + PWL load pulse from i_idle to i_peak for t_peak."""
    vout = f(V_RAIL_5V, ureg.V)
    inductance = f(L_BUCK, ureg.H)
    kp = 2 * math.pi * f_c_hz * c_out_total_f()
    ki = kp * 2 * math.pi * f_c_hz / LOOP_ZERO_RATIO
    slew_up = (vin_v - vout) / inductance
    slew_dn = vout / inductance
    c = Circuit("LMR33630 current-mode averaged load step")
    c.BehavioralSource("err", "err", c.gnd, voltage_expression=f"{vout} - V(out)")
    c.BehavioralSource(
        "cmdraw", "cmdraw", c.gnd, voltage_expression=f"{kp}*V(err) + V(nint)"
    )
    c.BehavioralSource(
        "cmd", "cmd", c.gnd, voltage_expression=f"max(0, min({i_lim_a}, V(cmdraw)))"
    )
    # PI integrator with back-calculation anti-windup: when the command is clamped, the
    # (cmd - cmdraw) term bleeds the integrator back toward the clamp. Continuous
    # (no step functions) so ngspice's step control does not collapse at the clamp edges.
    kaw = ki / kp
    c.BehavioralSource(
        "int",
        c.gnd,
        "nint",
        current_expression=f"{ki}*V(err) + {kaw}*(V(cmd) - V(cmdraw))",
    )
    c.C("int", "nint", c.gnd, 1 @ u_F, initial_condition=i_idle_a)
    c.R("int_leak", "nint", c.gnd, 1e12 @ u_Ohm)
    track = f"(V(cmd) - V(il))/{CURRENT_LOOP_TAU_S}"
    c.BehavioralSource(
        "slew",
        c.gnd,
        "il",
        current_expression=f"max(-{slew_dn}, min({slew_up}, {track}))",
    )
    c.C("il", "il", c.gnd, 1 @ u_F, initial_condition=i_idle_a)
    c.R("il_leak", "il", c.gnd, 1e12 @ u_Ohm)
    c.BehavioralSource("conv", c.gnd, "out", current_expression="V(il)")
    add_output_bank(c, vout)
    t1 = T0_S + t_peak_s
    # Load pulse as a B-source pwl(): PySpice's PWL current source appends "A" to
    # every value, which ngspice reads as atto — the pulse would vanish.
    knots = [
        (0.0, i_idle_a),
        (T0_S, i_idle_a),
        (T0_S + LOAD_EDGE_S, i_peak_a),
        (t1, i_peak_a),
        (t1 + LOAD_EDGE_S, i_idle_a),
        (t1 + TAIL_S, i_idle_a),
    ]
    pwl = ", ".join(f"{t}, {i}" for t, i in knots)
    c.BehavioralSource("load", "out", c.gnd, current_expression=f"pwl(TIME, {pwl})")
    return c


def load_step_waveform(
    vin_v: float,
    i_lim_a: float,
    f_c_hz: float,
    i_idle_a: float,
    i_peak_a: float,
    t_peak_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Transient run; returns (t in s, V_out in V)."""
    circuit = build_load_step_circuit(
        vin_v, i_lim_a, f_c_hz, i_idle_a, i_peak_a, t_peak_s
    )
    sim = circuit.simulator(temperature=25, nominal_temperature=25)
    sim.initial_condition(out=f(V_RAIL_5V, ureg.V))
    analysis = sim.transient(
        step_time=1e-6 @ u_s,
        end_time=(T0_S + t_peak_s + TAIL_S) @ u_s,
        max_time=MAX_STEP_S @ u_s,
        use_initial_condition=True,
    )
    return np.asarray(analysis.time, dtype=float), np.asarray(
        analysis["out"], dtype=float
    )


def simulate_load_step(
    vin_v: float,
    i_lim_a: float,
    f_c_hz: float,
    i_idle_a: float,
    i_peak_a: float,
    t_peak_s: float,
) -> LoadStepResult:
    """Rail minimum and time spent under the CM4 4.75 V floor."""
    t, v = load_step_waveform(vin_v, i_lim_a, f_c_hz, i_idle_a, i_peak_a, t_peak_s)
    below = v < f(V_5V_CM4_MIN, ureg.V)
    t_below = float(np.sum(np.diff(t)[below[1:]])) if below.any() else 0.0
    return LoadStepResult(v_min_v=float(v.min()), t_below_floor_ms=t_below * 1e3)
