"""Alerts come in two tiers: a WARNING range, then an EMERGENCY range.

The product spec: "We want alerts for parameters that go out of range: first a
WARNING range, then an EMERGENCY range." Before this, there was a single margin
— a reading either was fine or it paged you critical, with nothing in between.
Now temp, humidity, and CO2 each classify into nominal / warning / emergency.
"""

from app.automation.engine import (
    _band_severity,
    _TEMP_WARN_MARGIN_F,
    _TEMP_EMERG_MARGIN_F,
    _CO2_WARN_MARGIN_PPM,
    _CO2_EMERG_MARGIN_PPM,
)


# ── the band classifier ────────────────────────────────────────────────────


def test_inside_the_band_is_nominal():
    assert _band_severity(72, 68, 76, 2, 5) == (None, None)


def test_just_outside_is_a_warning_not_an_emergency():
    # band 68-76; warn at +2, emergency at +5
    assert _band_severity(79, 68, 76, 2, 5) == ("warning", "high")   # 78 < 79 <= 81
    assert _band_severity(65, 68, 76, 2, 5) == ("warning", "low")    # 63 <= 65 < 66


def test_far_outside_is_an_emergency():
    assert _band_severity(82, 68, 76, 2, 5) == ("emergency", "high")  # > 81
    assert _band_severity(62, 68, 76, 2, 5) == ("emergency", "low")   # < 63


def test_the_boundary_belongs_to_the_lower_tier():
    """Exactly at the warning edge is still nominal; exactly at the emergency
    edge is still warning. Strictly-greater keeps the tiers from double-firing."""
    assert _band_severity(78, 68, 76, 2, 5) == (None, None)          # == max+warn
    assert _band_severity(81, 68, 76, 2, 5) == ("warning", "high")   # == max+emerg


def test_ceiling_only_band_ignores_the_low_side():
    """CO2 has a max but no meaningful min — a low reading is never an alert."""
    assert _band_severity(200, None, 1000, 500, 1000) == (None, None)
    assert _band_severity(1600, None, 1000, 500, 1000) == ("warning", "high")
    assert _band_severity(2100, None, 1000, 500, 1000) == ("emergency", "high")


def test_margins_are_ordered_warning_then_emergency():
    """A warning must always trip before an emergency, or the tiers are useless."""
    assert _TEMP_WARN_MARGIN_F < _TEMP_EMERG_MARGIN_F
    assert _CO2_WARN_MARGIN_PPM < _CO2_EMERG_MARGIN_PPM
