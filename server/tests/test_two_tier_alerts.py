"""Alerts come in two tiers: a WARNING range, then an EMERGENCY range.

The product spec: "first a WARNING range, then an EMERGENCY range." Before
this there was one margin: a reading was fine or it paged critical. Temp,
humidity and CO2 each classify into nominal / warning / emergency.
"""

import pytest

from app.automation.engine import (
    _CO2_EMERG_MARGIN_PPM,
    _CO2_WARN_MARGIN_PPM,
    _HUMIDITY_EMERG_MARGIN,
    _HUMIDITY_WARN_MARGIN,
    _TEMP_EMERG_MARGIN_F,
    _TEMP_WARN_MARGIN_F,
    _band_severity,
)


@pytest.mark.parametrize("value,expected", [
    # band 68-76, warning past 2, emergency past 5
    (72, (None, None)),
    (79, ("warning", "high")),
    (65, ("warning", "low")),
    (82, ("emergency", "high")),
    (62, ("emergency", "low")),
    # An edge belongs to the lower tier: strictly past it, so the tiers never
    # both fire.
    (78, (None, None)),
    (81, ("warning", "high")),
    (66, (None, None)),
    (63, ("warning", "low")),
])
def test_a_reading_is_nominal_warning_or_emergency(value, expected):
    assert _band_severity(value, 68, 76, 2, 5) == expected


@pytest.mark.parametrize("value,expected", [
    (200, (None, None)),
    (1600, ("warning", "high")),
    (2100, ("emergency", "high")),
])
def test_a_ceiling_only_band_never_alerts_low(value, expected):
    """CO2 has a ceiling and no meaningful floor."""
    assert _band_severity(value, None, 1000, 500, 1000) == expected


def test_every_warning_margin_trips_before_its_emergency():
    assert _TEMP_WARN_MARGIN_F < _TEMP_EMERG_MARGIN_F
    assert _HUMIDITY_WARN_MARGIN < _HUMIDITY_EMERG_MARGIN
    assert _CO2_WARN_MARGIN_PPM < _CO2_EMERG_MARGIN_PPM
