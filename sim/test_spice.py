"""Assert the ngspice buck models match theory.ipynb §7 hand calcs.

Skipped (not failed) on hosts without libngspice so CI stays green where the
runner lacks it — the assertions still gate any host that has ngspice.
"""

import pytest

from sim.constants import (
    I_5V_IDLE,
    I_5V_PEAK,
    I_CM4_BOOT_PEAK,
    L_BUCK_ISAT,
    LMR33630_ILIMIT_MAX,
    LMR33630_IOUT_MAX_MIN,
    V_5V_CM4_IDEAL_MIN,
    V_5V_CM4_MIN,
    V_BAT_MAX,
    V_BAT_MIN,
    V_RIPPLE_5V_BUDGET,
    ureg,
)
from sim.spice_load_step import simulate_load_step
from sim.spice_ripple import simulate_buck_ripple

try:
    from PySpice.Spice.NgSpice.Shared import NgSpiceShared

    NgSpiceShared.new_instance()
    HAS_NGSPICE = True
except Exception:  # any load failure means no simulator on this host
    HAS_NGSPICE = False

pytestmark = pytest.mark.skipif(not HAS_NGSPICE, reason="libngspice not available")

VIN_MAX_V = V_BAT_MAX.to(ureg.V).magnitude
VIN_MIN_V = V_BAT_MIN.to(ureg.V).magnitude
I_IDLE_A = I_5V_IDLE.to(ureg.A).magnitude
I_LIM_WORST_A = LMR33630_IOUT_MAX_MIN.to(ureg.A).magnitude
F_C_FAST_HZ = 25e3  # Reason: crossover implied by SNVSAN3F §9.2.2.5 example (2 A / 250 mV / 52 uF)
T_PEAK_S = 1e-3


class TestSwitchingRipple:
    """Open-loop switching model vs SNVSAN3F Eq 7 on the real cap bank."""

    def test_ripple_at_vin_max_matches_expected(self) -> None:
        """14.6 V in, 3 A out: 11.8 mV pk-pk (parallel bank at 400 kHz) +/-35%."""
        # arrange
        expected_mv = 11.8

        # act
        actual_mv = simulate_buck_ripple(VIN_MAX_V, 3.0)

        # assert
        assert actual_mv == pytest.approx(expected_mv, rel=0.35)

    def test_ripple_under_bulk_only_eq7_bound(self) -> None:
        """The ceramic can only help: sim <= Eq 7 with the polymer alone (14.0 mV)."""
        # act
        actual_mv = simulate_buck_ripple(VIN_MAX_V, 3.0)

        # assert
        assert actual_mv <= 14.0 * 1.15

    def test_ripple_within_rail_budget(self) -> None:
        """Worst-case ripple stays under the 50 mV (1%) rail budget."""
        # act
        actual_mv = simulate_buck_ripple(VIN_MAX_V, 3.0)

        # assert
        assert actual_mv < V_RIPPLE_5V_BUDGET.to(ureg.mV).magnitude


class TestBootPeakDroop:
    """Averaged current-mode model through the CM4 boot peak at V_BAT_MIN."""

    def test_coincident_peak_browns_out_worst_case_silicon(self) -> None:
        """3.92 A for 1 ms vs IOUT_max(min) 3.375 A: rail falls to ~3.86 V, under the floor ~0.92 ms."""
        # arrange
        expected_v_min = 3.858
        expected_t_below_ms = 0.924

        # act
        res = simulate_load_step(
            VIN_MIN_V,
            I_LIM_WORST_A,
            F_C_FAST_HZ,
            I_IDLE_A,
            I_5V_PEAK.to(ureg.A).magnitude,
            T_PEAK_S,
        )

        # assert
        assert res.v_min_v < V_5V_CM4_MIN.to(ureg.V).magnitude
        assert res.v_min_v == pytest.approx(expected_v_min, abs=0.15)
        assert res.t_below_floor_ms == pytest.approx(expected_t_below_ms, rel=0.3)

    def test_sequenced_cm4_peak_holds_rail(self) -> None:
        """3.0 A CM4-only peak (modem / Lepton sequenced away): ESR-dominated 47 mV droop."""
        # arrange
        expected_droop_v = 0.047

        # act
        res = simulate_load_step(
            VIN_MIN_V,
            I_LIM_WORST_A,
            F_C_FAST_HZ,
            I_IDLE_A,
            I_CM4_BOOT_PEAK.to(ureg.A).magnitude,
            T_PEAK_S,
        )

        # assert
        assert res.t_below_floor_ms == 0.0
        assert res.v_min_v >= V_5V_CM4_IDEAL_MIN.to(ureg.V).magnitude
        assert 5.0 - res.v_min_v == pytest.approx(expected_droop_v, rel=0.4)


class TestInductorRating:
    """SNVSAN3F §9.2.2.4: Isat must not be below ILIMIT (max 4.1 A) — ADR-014 swap."""

    def test_inductor_isat_covers_valley_current_limit(self) -> None:
        """Isat >= 4.1 A so a current-limit event cannot saturate the core."""
        # act / assert
        assert (
            L_BUCK_ISAT.to(ureg.A).magnitude >= LMR33630_ILIMIT_MAX.to(ureg.A).magnitude
        )
