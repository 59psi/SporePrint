"""Tests for weather provider abstraction and factory."""

import time

import httpx
import pytest

import app.weather.providers as providers_mod
import app.weather.service as weather_svc
from app.config import settings
from app.weather.providers import (
    get_provider,
    provider_cascade,
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
    """Open-Meteo returns naive GMT ISO strings; parsing them as
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
    """api.weather.gov 301-redirects /points with >4 decimals to the
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


# ── provider gaps and units ─────────────────────────────────────────────────


async def test_openmeteo_drops_a_null_hour_and_keeps_a_null_humidity(monkeypatch):
    """Open-Meteo serialises a missing value as null: a None temperature reached
    the prediction arithmetic and the daily max()/sum() and raised TypeError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hourly": {
            "time": ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"],
            "temperature_2m": [40.0, None, 42.0],
            "relative_humidity_2m": [60, 61, None],
            "wind_speed_10m": [3.0, None, None],
            "weather_code": [0, 1, None],
        }})

    _route(monkeypatch, handler)
    result = await OpenMeteoProvider().fetch_forecast("41.88", "-87.63")
    assert [(r["temp_f"], r["humidity"], r["wind_mph"]) for r in result] == [
        (40.0, 60.0, 3.0), (42.0, None, 0)]


async def test_nws_forecast_tolerates_null_humidity_temperature_and_wind(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/points/"):
            return httpx.Response(200, json={"properties": {
                "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly",
            }})
        return httpx.Response(200, json={"properties": {"periods": [
            {"startTime": "2026-01-01T00:00:00-05:00", "temperature": 40,
             "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": None},
             "windSpeed": None, "shortForecast": "Clear"},
            {"startTime": "2026-01-01T01:00:00-05:00", "temperature": None,
             "relativeHumidity": None, "windSpeed": "5 to 10 mph", "shortForecast": "Clear"},
            {"startTime": "2026-01-01T02:00:00-05:00", "temperature": 41,
             "relativeHumidity": {"value": 70}, "windSpeed": "10 mph", "shortForecast": "Clear"},
        ]}})

    _route(monkeypatch, handler)
    result = await NWSProvider().fetch_forecast("40.7128", "-74.006")
    assert [(r["temp_f"], r["humidity"], r["wind_mph"]) for r in result] == [
        (40.0, None, 0.0), (41.0, 70.0, 10.0)]


async def test_nws_observed_wind_is_converted_from_kmh(monkeypatch):
    """NWS observations report windSpeed in km/h (wmoUnit:km_h-1); converting
    it as m/s stored and published the wind 3.6x too high."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/points/"):
            return httpx.Response(200, json={"properties": {
                "observationStations": "https://api.weather.gov/gridpoints/OKX/33,35/stations",
            }})
        if path.endswith("/stations"):
            return httpx.Response(200, json={"features": [
                {"properties": {"stationIdentifier": "KNYC"}}]})
        return httpx.Response(200, json={"properties": {
            "temperature": {"unitCode": "wmoUnit:degC", "value": 10.0},
            "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 55.0},
            "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 10.0},
            "barometricPressure": {"unitCode": "wmoUnit:Pa", "value": 101500},
            "textDescription": "Clear",
        }})

    _route(monkeypatch, handler)
    current = await NWSProvider().fetch_current("40.7128", "-74.006")
    assert current["outdoor_wind_mph"] == 6.2


def test_nws_observed_wind_follows_its_unit_code():
    wind = providers_mod._nws_observed_wind_mph
    assert wind({"unitCode": "wmoUnit:m_s-1", "value": 10}) == pytest.approx(22.3694)
    assert wind({"unitCode": "wmoUnit:km_h-1", "value": 10}) == pytest.approx(6.21371)
    assert wind({"value": 10}) == pytest.approx(6.21371)  # NWS's km/h when unstated
    assert wind({"unitCode": "wmoUnit:km_h-1", "value": None}) == 0.0
    assert wind(None) == 0.0


# ── the chosen provider ─────────────────────────────────────────────────────


def _names(providers) -> list[str]:
    return [p.name for p in providers]


def test_cascade_tries_the_chosen_provider_first():
    """SPOREPRINT_WEATHER_PROVIDER / the Settings value was stored and never
    read: Open-Meteo was always tried first."""
    assert _names(provider_cascade("openmeteo")) == ["openmeteo", "nws"]
    assert _names(provider_cascade("nws")) == ["nws", "openmeteo"]
    assert _names(provider_cascade("openweathermap", "key")) == ["openweathermap", "openmeteo", "nws"]
    assert _names(provider_cascade("openmeteo", "key")) == ["openmeteo", "nws", "openweathermap"]


def test_a_keyed_provider_without_its_key_is_left_out():
    """Chosen with no key, OpenWeatherMap would fail every poll."""
    assert _names(provider_cascade("openweathermap")) == ["openmeteo", "nws"]


def test_an_unknown_provider_falls_back_to_the_default_order():
    assert _names(provider_cascade("bogus")) == ["openmeteo", "nws"]


def test_the_poller_rebuilds_its_cascade_when_the_choice_changes(monkeypatch):
    monkeypatch.setattr(weather_svc, "_providers", None)
    monkeypatch.setattr(weather_svc, "_providers_key", None)
    monkeypatch.setattr(settings, "weather_api_key", "")
    monkeypatch.setattr(settings, "weather_provider", "openmeteo")
    assert _names(weather_svc._get_providers()) == ["openmeteo", "nws"]
    monkeypatch.setattr(settings, "weather_provider", "nws")
    assert _names(weather_svc._get_providers()) == ["nws", "openmeteo"]
