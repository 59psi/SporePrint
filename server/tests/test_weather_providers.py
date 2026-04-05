"""Tests for weather provider abstraction and factory."""

from app.weather.providers import (
    get_provider,
    OpenMeteoProvider,
    OpenWeatherMapProvider,
    NWSProvider,
    _dew_point,
    _wmo_code_to_text,
)


def test_get_provider_openmeteo():
    p = get_provider("openmeteo")
    assert isinstance(p, OpenMeteoProvider)
    assert p.name == "openmeteo"


def test_get_provider_openweathermap():
    p = get_provider("openweathermap", "fake-key")
    assert isinstance(p, OpenWeatherMapProvider)
    assert p.api_key == "fake-key"


def test_get_provider_nws():
    p = get_provider("nws")
    assert isinstance(p, NWSProvider)


def test_get_provider_default():
    p = get_provider("unknown")
    assert isinstance(p, OpenMeteoProvider)


def test_dew_point_normal():
    dp = _dew_point(75.0, 50.0)
    assert 54 < dp < 58


def test_dew_point_high_rh():
    dp = _dew_point(75.0, 95.0)
    assert 72 < dp < 75


def test_dew_point_zero_rh():
    dp = _dew_point(75.0, 0.0)
    assert isinstance(dp, float)


def test_wmo_code_clear():
    assert _wmo_code_to_text(0) == "Clear"


def test_wmo_code_rain():
    assert _wmo_code_to_text(63) == "Rain"


def test_wmo_code_unknown():
    assert _wmo_code_to_text(999) == "Unknown"
