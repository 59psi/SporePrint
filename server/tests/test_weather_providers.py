"""Weather providers (Open-Meteo, OpenWeatherMap, NWS) and their cascade.

* Each provider returns current conditions in the standard keys, in °F,
  % RH, mph and mb, whatever units its API uses; an outage is None / an
  empty forecast, never an exception, so the poller can fail over.
* Forecast hours are UTC on any host, a null hour is dropped (a null
  humidity or wind kept as a gap), and NWS's redirected /points lookup is
  followed.
* The chosen provider is tried first, a keyed provider without its key is
  left out, an unknown choice falls back to the default order, and the
  poller rebuilds its cascade when the choice changes.
"""

import time

import httpx
import pytest

import app.weather.providers as providers_mod
import app.weather.service as weather_svc
from app.config import settings
from app.weather.providers import (
    NWSProvider,
    OpenMeteoProvider,
    OpenWeatherMapProvider,
    _dew_point,
    _wmo_code_to_text,
    get_provider,
    provider_cascade,
)

_RealAsyncClient = httpx.AsyncClient


def _route(monkeypatch, handler):
    """Send every provider request through `handler` (a MockTransport)."""
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)
    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", factory)


def test_get_provider_builds_each_provider_and_defaults_to_open_meteo():
    assert isinstance(get_provider("openmeteo"), OpenMeteoProvider)
    assert isinstance(get_provider("nws"), NWSProvider)
    owm = get_provider("openweathermap", "fake-key")
    assert isinstance(owm, OpenWeatherMapProvider) and owm.api_key == "fake-key"
    assert isinstance(get_provider("unknown"), OpenMeteoProvider)


def test_dew_point_follows_the_magnus_formula_and_clamps_a_zero_humidity():
    assert _dew_point(75.0, 50.0) == 55.1
    assert _dew_point(75.0, 95.0) == 73.5
    # A 0 % reading (a sensor gap) is clamped to 1 % instead of log(0).
    assert _dew_point(75.0, 0.0) == _dew_point(75.0, 1.0) == -31.8


def test_wmo_codes_read_as_conditions():
    assert (_wmo_code_to_text(0), _wmo_code_to_text(63), _wmo_code_to_text(999)) == (
        "Clear", "Rain", "Unknown")


# ── Current conditions, per provider ─────────────────────────────────


def _open_meteo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"current": {
        "temperature_2m": 75.04, "relative_humidity_2m": 50, "wind_speed_10m": 3.26,
        "surface_pressure": 1013.0, "weather_code": 63,
    }})


def _open_weather_map(request: httpx.Request) -> httpx.Response:
    assert request.url.params["appid"] == "owm-key" and request.url.params["units"] == "imperial"
    return httpx.Response(200, json={
        "main": {"temp": 75.0, "humidity": 50, "pressure": 1013},
        "wind": {"speed": 3.0}, "weather": [{"main": "Clouds"}],
    })


def _nws(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/points/"):
        return httpx.Response(200, json={"properties": {
            "observationStations": "https://api.weather.gov/gridpoints/OKX/33,35/stations",
        }})
    if path.endswith("/stations"):
        return httpx.Response(200, json={"features": [{"properties": {"stationIdentifier": "KNYC"}}]})
    assert path == "/stations/KNYC/observations/latest"
    return httpx.Response(200, json={"properties": {
        "temperature": {"unitCode": "wmoUnit:degC", "value": 10.0},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 55.0},
        # Observations report km/h; converting it as m/s stored the wind 3.6x too high.
        "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 10.0},
        "barometricPressure": {"unitCode": "wmoUnit:Pa", "value": 101500},
        "textDescription": "Clear",
    }})


@pytest.mark.parametrize("provider,handler,expected", [
    (OpenMeteoProvider(), _open_meteo, {
        "outdoor_temp_f": 75.0, "outdoor_humidity": 50, "outdoor_dew_point_f": 55.1,
        "outdoor_wind_mph": 3.3, "outdoor_pressure_mb": 1013.0, "outdoor_condition": "Rain"}),
    (OpenWeatherMapProvider("owm-key"), _open_weather_map, {
        "outdoor_temp_f": 75.0, "outdoor_humidity": 50, "outdoor_dew_point_f": 55.1,
        "outdoor_wind_mph": 3.0, "outdoor_pressure_mb": 1013, "outdoor_condition": "Clouds"}),
    (NWSProvider(), _nws, {
        "outdoor_temp_f": 50.0, "outdoor_humidity": 55.0, "outdoor_dew_point_f": 34.5,
        "outdoor_wind_mph": 6.2, "outdoor_pressure_mb": 1015.0, "outdoor_condition": "Clear"}),
], ids=["openmeteo", "openweathermap", "nws"])
async def test_current_conditions_come_back_in_the_standard_keys_and_units(
    monkeypatch, provider, handler, expected,
):
    _route(monkeypatch, handler)
    assert await provider.fetch_current("40.7128", "-74.006") == expected


@pytest.mark.parametrize("provider", [OpenMeteoProvider(), OpenWeatherMapProvider("k"), NWSProvider()],
                         ids=["openmeteo", "openweathermap", "nws"])
async def test_a_provider_outage_is_no_reading_so_the_poller_can_fail_over(monkeypatch, provider):
    _route(monkeypatch, lambda request: httpx.Response(503, text="maintenance"))
    assert await provider.fetch_current("40.7128", "-74.006") is None
    assert await provider.fetch_forecast("40.7128", "-74.006") == []


def test_nws_observed_wind_follows_its_unit_code():
    wind = providers_mod._nws_observed_wind_mph
    assert wind({"unitCode": "wmoUnit:m_s-1", "value": 10}) == pytest.approx(22.3694)
    assert wind({"unitCode": "wmoUnit:km_h-1", "value": 10}) == pytest.approx(6.21371)
    assert wind({"value": 10}) == pytest.approx(6.21371)  # NWS's km/h when unstated
    assert wind({"unitCode": "wmoUnit:km_h-1", "value": None}) == 0.0
    assert wind(None) == 0.0


# ── Forecasts ────────────────────────────────────────────────────────


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


async def test_openweathermap_forecast_drops_a_null_hour_and_keeps_a_null_humidity(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/2.5/forecast"
        return httpx.Response(200, json={"list": [
            {"dt": 1767225600, "main": {"temp": 40.0, "humidity": 60},
             "wind": {"speed": 3.0}, "weather": [{"main": "Clear"}]},
            {"dt": 1767236400, "main": {"temp": None, "humidity": 61}},
            {"dt": 1767247200, "main": {"temp": 42.0, "humidity": None}},
        ]})

    _route(monkeypatch, handler)
    result = await OpenWeatherMapProvider("k").fetch_forecast("41.88", "-87.63")
    assert [(r["timestamp"], r["temp_f"], r["humidity"], r["wind_mph"], r["condition"])
            for r in result] == [
        (1767225600, 40.0, 60.0, 3.0, "Clear"), (1767247200, 42.0, None, 0, "Unknown")]


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


# ── The chosen provider ─────────────────────────────────────────────────────


def _names(providers) -> list[str]:
    return [p.name for p in providers]


@pytest.mark.parametrize("choice,key,order", [
    # SPOREPRINT_WEATHER_PROVIDER / the Settings value was stored and never
    # read: Open-Meteo was always tried first.
    ("openmeteo", "", ["openmeteo", "nws"]),
    ("nws", "", ["nws", "openmeteo"]),
    ("openweathermap", "key", ["openweathermap", "openmeteo", "nws"]),
    ("openmeteo", "key", ["openmeteo", "nws", "openweathermap"]),
    # Chosen with no key, OpenWeatherMap would fail every poll.
    ("openweathermap", "", ["openmeteo", "nws"]),
    ("bogus", "", ["openmeteo", "nws"]),
], ids=["openmeteo", "nws", "openweathermap", "keyed-fallback-last", "keyed-without-key",
        "unknown-choice"])
def test_cascade_tries_the_chosen_provider_first(choice, key, order):
    assert _names(provider_cascade(choice, key)) == order


def test_the_poller_rebuilds_its_cascade_when_the_choice_changes(monkeypatch):
    monkeypatch.setattr(weather_svc, "_providers", None)
    monkeypatch.setattr(weather_svc, "_providers_key", None)
    monkeypatch.setattr(settings, "weather_api_key", "")
    monkeypatch.setattr(settings, "weather_provider", "openmeteo")
    assert _names(weather_svc._get_providers()) == ["openmeteo", "nws"]
    monkeypatch.setattr(settings, "weather_provider", "nws")
    assert _names(weather_svc._get_providers()) == ["nws", "openmeteo"]
