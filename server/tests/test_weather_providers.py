"""Tests for weather provider abstraction and factory."""

import time

import httpx
import pytest

import app.weather.providers as providers_mod
from app.weather.providers import (
    get_provider,
    OpenMeteoProvider,
    OpenWeatherMapProvider,
    NWSProvider,
    _dew_point,
    _wmo_code_to_text,
)

_RealAsyncClient = httpx.AsyncClient


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


# ── HTTP-level provider behaviour (real httpx over a MockTransport) ─────────


def _route(monkeypatch, handler):
    """Send every provider request through `handler` (a MockTransport)."""
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)
    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", factory)


@pytest.fixture()
def non_utc_host(monkeypatch):
    """Run as a native (non-Docker) install on a US-Central Pi."""
    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


async def test_openmeteo_hourly_times_are_utc_on_a_non_utc_host(monkeypatch, non_utc_host):
    """srv-rest#34: Open-Meteo returns naive GMT ISO strings; parsing them as
    host-local time shifted every forecast hour by the UTC offset."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hourly": {
            "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
            "temperature_2m": [40.0, 41.0],
            "relative_humidity_2m": [60, 61],
            "wind_speed_10m": [3.0, 4.0],
            "weather_code": [0, 1],
        }})

    _route(monkeypatch, handler)
    result = await OpenMeteoProvider().fetch_forecast("41.88", "-87.63")
    assert [r["timestamp"] for r in result] == [1767225600.0, 1767229200.0]


async def test_nws_point_lookup_handles_high_precision_coordinates(monkeypatch):
    """srv-rest#35: api.weather.gov 301-redirects /points with >4 decimals to the
    rounded point; httpx doesn't follow redirects by default, so the NWS
    failover never worked for browser-geolocated coordinates."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path == "/points/40.712776,-74.005974":
            return httpx.Response(
                301, headers={"Location": "https://api.weather.gov/points/40.7128,-74.006"}
            )
        if path == "/points/40.7128,-74.006":
            return httpx.Response(200, json={"properties": {
                "observationStations": "https://api.weather.gov/gridpoints/OKX/33,35/stations",
                "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly",
            }})
        return httpx.Response(404)

    _route(monkeypatch, handler)
    url = await NWSProvider()._get_station_url("40.712776", "-74.005974")
    assert url == "https://api.weather.gov/gridpoints/OKX/33,35/stations"
    assert seen[-1] == "/points/40.7128,-74.006"
