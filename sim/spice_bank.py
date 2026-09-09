"""Shared pieces of the 5 V rail ngspice models: unit stripping + the output cap bank.

The bank is exactly what cad/netlist/power.py places on 5V_RAIL: 470 uF polymer
(Nichicon PCL1A471MCL1GS, ESR 17 mΩ) || 22 uF 0805 X7R (DC-bias derated) || 100 nF.

Gotcha: ngspice parses a trailing "A" as atto (1e-18), so PySpice's `@ u_A` on an
ic= value or a PWL current list silently zeroes it. Currents are passed as plain
floats everywhere in these models; initial conditions likewise.
"""

from __future__ import annotations

from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import u_F, u_Ohm

from sim.constants import (
    C_BULK_5V,
    C_BULK_5V_ESR,
    C_OUT_CER_5V,
    C_OUT_CER_DC_BIAS_DERATE,
    C_OUT_CER_ESR,
    C_OUT_HF_5V,
    ureg,
)


def f(q, unit) -> float:
    """Strip the pint unit, then the uncertainty — SPICE wants a plain float."""
    m = q.to(unit).magnitude
    return float(getattr(m, "nominal_value", m))


def c_cer_derated_f() -> float:
    """22 uF X7R after DC-bias derating at 5 V. Returns F."""
    return f(C_OUT_CER_5V, ureg.F) * C_OUT_CER_DC_BIAS_DERATE


def c_out_total_f() -> float:
    """Total output capacitance of the bank. Returns F."""
    return f(C_BULK_5V, ureg.F) + c_cer_derated_f() + f(C_OUT_HF_5V, ureg.F)


def add_output_bank(c: Circuit, v0: float) -> None:
    """Attach the three output capacitors (with ESR) from node `out` to GND, precharged to v0."""
    c.R("esr_bulk", "out", "bulk", f(C_BULK_5V_ESR, ureg.ohm) @ u_Ohm)
    c.C("bulk", "bulk", c.gnd, f(C_BULK_5V, ureg.F) @ u_F, initial_condition=v0)
    c.R("esr_cer", "out", "cer", f(C_OUT_CER_ESR, ureg.ohm) @ u_Ohm)
    c.C("cer", "cer", c.gnd, c_cer_derated_f() @ u_F, initial_condition=v0)
    c.C("hf", "out", c.gnd, f(C_OUT_HF_5V, ureg.F) @ u_F, initial_condition=v0)
