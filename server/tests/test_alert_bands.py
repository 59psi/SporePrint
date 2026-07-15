"""Gap 2: two-tier (WARNING / EMERGENCY) alert bands from species phase params.

Pre-fix, _check_safety_thresholds had ONE global margin (temp 5F, CO2 1000 ppm)
and fired ONLY notify_critical (via temperature_alert/co2_alert) once that single
margin was crossed. There was no warning tier at all, and the band width was the
same constant for every species. These tests pin:

- a reading just outside nominal → WARNING (never fired pre-fix), and
- a reading further out → EMERGENCY, with
- band widths coming from the phase's per-species margin fields, plus
- an unconditional human-safety CO2 ceiling, and
- species-band CO2 alerts gated by whether the sensor is coupled to the substrate.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.automation.engine import _check_safety_thresholds
from app.species.models import PhaseParams


def _phase(**over):
    d = dict(
        temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
        co2_max_ppm=800, co2_tolerance="low", light_hours_on=12, light_hours_off=12,
        light_spectrum="daylight_6500k", fae_mode="scheduled", expected_duration_days=(7, 14),
    )
    d.update(over)
    return PhaseParams(**d)


def _mocks():
    return patch.multiple(
        "app.automation.engine",
        notify_warning=AsyncMock(),
        notify_critical=AsyncMock(),
    )


async def _run(readings, phase=None, co2_meaningful=True):
    phase = phase or _phase()
    with patch("app.cloud.service.forward_event", new=AsyncMock()), _mocks():
        import app.automation.engine as eng
        await _check_safety_thresholds("cam-01", phase, readings, {"id": 1}, co2_meaningful)
        return eng.notify_warning, eng.notify_critical


async def test_temp_nominal_is_silent():
    warn, crit = await _run({"temp_f": 74})
    warn.assert_not_called()
    crit.assert_not_called()


async def test_temp_warning_band():
    # max 76 + warn 2 = 78 → warning, not emergency.
    warn, crit = await _run({"temp_f": 78.5})
    warn.assert_awaited()
    crit.assert_not_called()


async def test_temp_emergency_band():
    # max 76 + emergency 5 = 81 → emergency.
    warn, crit = await _run({"temp_f": 82})
    crit.assert_awaited()


async def test_temp_low_side_warning():
    # min 72 - warn 2 = 70 → warning on the cold side.
    warn, crit = await _run({"temp_f": 69})
    warn.assert_awaited()
    crit.assert_not_called()


async def test_co2_warning_then_emergency():
    warn, crit = await _run({"co2_ppm": 1350})   # 800 + 500 warn
    warn.assert_awaited()
    crit.assert_not_called()

    warn, crit = await _run({"co2_ppm": 1900})   # 800 + 1000 emergency
    crit.assert_awaited()


async def test_band_widths_follow_species_margins():
    """A CO2-tolerant phase with wide margins does NOT alert where a tight one would."""
    tolerant = _phase(co2_max_ppm=800, co2_warn_margin_ppm=2000, co2_emergency_margin_ppm=5000)
    warn, crit = await _run({"co2_ppm": 1900}, phase=tolerant)
    warn.assert_not_called()   # 1900 < 800+2000 warn edge
    crit.assert_not_called()


async def test_co2_species_band_gated_by_container_but_ceiling_is_not():
    # Sealed container: a chamber CO2 of 1900 is room air, not the substrate's —
    # no species-band alert.
    warn, crit = await _run({"co2_ppm": 1900}, co2_meaningful=False)
    warn.assert_not_called()
    crit.assert_not_called()

    # ...but a genuinely hazardous room CO2 alerts regardless of container.
    warn, crit = await _run({"co2_ppm": 45000}, co2_meaningful=False)
    crit.assert_awaited()


async def test_co2_floor_breach_warns():
    """A species that wants CO2 held HIGH warns when it drops below its floor."""
    reishi_like = _phase(co2_max_ppm=10000, co2_min_ppm=1500)
    warn, crit = await _run({"co2_ppm": 900}, phase=reishi_like)
    warn.assert_awaited()
    crit.assert_not_called()
