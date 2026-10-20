"""Weather provider adapters: Open-Meteo (default, no key), OpenWeatherMap, NWS."""

import logging
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

import httpx

from ..http_tls import tls_context

log = logging.getLogger(__name__)


def as_finite(value) -> float | None:
    """`value` as a float, or None when it is missing or not a finite number.

    Providers send gaps as null (Open-Meteo serialises a missing hour's NaN as
    null; NWS leaves `value` null), and a None that reaches the arithmetic or
    max()/sum() downstream raises TypeError.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _at(values: Sequence | None, i: int):
    """values[i], or None past the end of a short (or missing) series."""
    return values[i] if values is not None and i < len(values) else None


def _dew_point(temp_f: float, rh: float) -> float:
    """Approximate dew point in °F using Magnus formula."""
    temp_c = (temp_f - 32) * 5 / 9
    a, b = 17.27, 237.7
    try:
        gamma = (a * temp_c) / (b + temp_c) + math.log(max(rh, 1) / 100)
        dp_c = (b * gamma) / (a - gamma)
        return round(dp_c * 9 / 5 + 32, 1)
    except (ValueError, ZeroDivisionError):
        return round(temp_f - 10, 1)


def _utc_timestamp(value) -> float:
    """Epoch seconds for a provider time value.

    Open-Meteo (with no `timezone` param) returns naive GMT ISO strings such as
    "2026-01-01T00:00"; `datetime.fromisoformat(...).timestamp()` would read
    those as HOST-local time, shifting every hour by the UTC offset on a native
    (non-Docker) install. Naive values are therefore pinned to UTC; aware ISO
    strings (NWS) and numeric unix times pass through unchanged.
    """
    if isinstance(value, (int, float)):
        return float(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _nws_point(lat: str, lon: str) -> str:
    """Format a /points path segment the way api.weather.gov wants it.

    NWS answers /points requests with more than 4 decimal places (e.g. a
    browser-geolocated 40.712776,-74.005974) with a 301 to the rounded point.
    """
    def _fmt(v) -> str:
        return f"{float(v):.4f}".rstrip("0").rstrip(".")
    return f"{_fmt(lat)},{_fmt(lon)}"


class WeatherProvider(ABC):
    name: str

    @abstractmethod
    async def fetch_current(self, lat: str, lon: str) -> dict | None:
        """Return current conditions as a flat dict with standard keys."""

    @abstractmethod
    async def fetch_forecast(self, lat: str, lon: str) -> list[dict]:
        """Return 7-day hourly forecast as a list of dicts."""


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo: completely free, no API key needed."""
    name = "openmeteo"

    async def fetch_current(self, lat: str, lon: str) -> dict | None:
        params = {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure,weather_code",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        try:
            async with httpx.AsyncClient(timeout=10, verify=tls_context()) as client:
                r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                r.raise_for_status()
                data = r.json()
            c = data["current"]
            temp = c["temperature_2m"]
            rh = c["relative_humidity_2m"]
            return {
                "outdoor_temp_f": round(temp, 1),
                "outdoor_humidity": rh,
                "outdoor_dew_point_f": _dew_point(temp, rh),
                "outdoor_wind_mph": round(c.get("wind_speed_10m", 0), 1),
                "outdoor_pressure_mb": round(c.get("surface_pressure", 0), 1),
                "outdoor_condition": _wmo_code_to_text(c.get("weather_code", 0)),
            }
        except Exception as e:
            log.error("Open-Meteo current fetch failed: %s", e)
            return None

    async def fetch_forecast(self, lat: str, lon: str) -> list[dict]:
        params = {
            "latitude": lat, "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "forecast_days": 7,
            "timezone": "GMT",  # explicit: hourly times are parsed as UTC below
        }
        try:
            async with httpx.AsyncClient(timeout=10, verify=tls_context()) as client:
                r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                r.raise_for_status()
                data = r.json()
            hourly = data["hourly"]
            temps = hourly.get("temperature_2m")
            humidities = hourly.get("relative_humidity_2m")
            winds = hourly.get("wind_speed_10m")
            codes = hourly.get("weather_code")
            results = []
            for i, time_str in enumerate(hourly["time"]):
                temp_f = as_finite(_at(temps, i))
                if temp_f is None:
                    continue  # a missing hour: Open-Meteo sends its NaN as null
                results.append({
                    "timestamp": _utc_timestamp(time_str),
                    "temp_f": temp_f,
                    "humidity": as_finite(_at(humidities, i)),
                    "wind_mph": as_finite(_at(winds, i)) or 0,
                    "condition": _wmo_code_to_text(_at(codes, i) or 0),
                })
            return results
        except Exception as e:
            log.error("Open-Meteo forecast fetch failed: %s", e)
            return []


class OpenWeatherMapProvider(WeatherProvider):
    """OpenWeatherMap: requires API key, 5-day forecast."""
    name = "openweathermap"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_current(self, lat: str, lon: str) -> dict | None:
        params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "imperial"}
        try:
            async with httpx.AsyncClient(timeout=10, verify=tls_context()) as client:
                r = await client.get("https://api.openweathermap.org/data/2.5/weather", params=params)
                r.raise_for_status()
                data = r.json()
            main = data["main"]
            wind = data.get("wind", {})
            temp = main["temp"]
            rh = main.get("humidity", 0)
            return {
                "outdoor_temp_f": round(temp, 1),
                "outdoor_humidity": rh,
                "outdoor_dew_point_f": _dew_point(temp, rh),
                "outdoor_wind_mph": round(wind.get("speed", 0), 1),
                "outdoor_pressure_mb": main.get("pressure", 0),
                "outdoor_condition": data.get("weather", [{}])[0].get("main", "Unknown"),
            }
        except Exception as e:
            log.error("OpenWeatherMap current fetch failed: %s", e)
            return None

    async def fetch_forecast(self, lat: str, lon: str) -> list[dict]:
        params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "imperial"}
        try:
            async with httpx.AsyncClient(timeout=10, verify=tls_context()) as client:
                r = await client.get("https://api.openweathermap.org/data/2.5/forecast", params=params)
                r.raise_for_status()
                data = r.json()
            results = []
            for entry in data.get("list", []):
                main = entry.get("main") or {}
                temp_f = as_finite(main.get("temp"))
                if temp_f is None:
                    continue
                results.append({
                    "timestamp": entry["dt"],
                    "temp_f": temp_f,
                    "humidity": as_finite(main.get("humidity")),
                    "wind_mph": as_finite((entry.get("wind") or {}).get("speed")) or 0,
                    "condition": entry["weather"][0]["main"] if entry.get("weather") else "Unknown",
                })
            return results
        except Exception as e:
            log.error("OpenWeatherMap forecast fetch failed: %s", e)
            return []


class NWSProvider(WeatherProvider):
    """National Weather Service: US-only, free, no API key."""
    name = "nws"

    async def _get_station_url(self, lat: str, lon: str) -> str | None:
        """Resolve lat/lon to the nearest NWS observation station."""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                         verify=tls_context()) as client:
                r = await client.get(
                    f"https://api.weather.gov/points/{_nws_point(lat, lon)}",
                    headers={"User-Agent": "SporePrint/1.0"},
                )
                r.raise_for_status()
                data = r.json()
            return data["properties"]["observationStations"]
        except Exception as e:
            log.error("NWS point lookup failed: %s", e)
            return None

    async def fetch_current(self, lat: str, lon: str) -> dict | None:
        stations_url = await self._get_station_url(lat, lon)
        if not stations_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                         verify=tls_context()) as client:
                r = await client.get(stations_url, headers={"User-Agent": "SporePrint/1.0"})
                r.raise_for_status()
                station_id = r.json()["features"][0]["properties"]["stationIdentifier"]

                r = await client.get(
                    f"https://api.weather.gov/stations/{station_id}/observations/latest",
                    headers={"User-Agent": "SporePrint/1.0"},
                )
                r.raise_for_status()
                props = r.json()["properties"]

            temp_c = as_finite((props.get("temperature") or {}).get("value"))
            rh = as_finite((props.get("relativeHumidity") or {}).get("value"))
            pressure = as_finite((props.get("barometricPressure") or {}).get("value"))

            if temp_c is None:
                return None

            temp_f = round(temp_c * 9 / 5 + 32, 1)
            rh = round(rh, 0) if rh else 50
            return {
                "outdoor_temp_f": temp_f,
                "outdoor_humidity": rh,
                "outdoor_dew_point_f": _dew_point(temp_f, rh),
                "outdoor_wind_mph": round(_nws_observed_wind_mph(props.get("windSpeed")), 1),
                "outdoor_pressure_mb": round((pressure or 101325) / 100, 1),
                "outdoor_condition": props.get("textDescription", "Unknown"),
            }
        except Exception as e:
            log.error("NWS current fetch failed: %s", e)
            return None

    async def fetch_forecast(self, lat: str, lon: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                         verify=tls_context()) as client:
                r = await client.get(
                    f"https://api.weather.gov/points/{_nws_point(lat, lon)}",
                    headers={"User-Agent": "SporePrint/1.0"},
                )
                r.raise_for_status()
                forecast_url = r.json()["properties"]["forecastHourly"]

                r = await client.get(forecast_url, headers={"User-Agent": "SporePrint/1.0"})
                r.raise_for_status()
                periods = r.json()["properties"]["periods"]

            results = []
            for p in periods[:168]:  # max 7 days
                temp_f = as_finite(p.get("temperature"))
                if temp_f is None:
                    continue
                results.append({
                    "timestamp": _utc_timestamp(p["startTime"]),
                    "temp_f": temp_f,
                    "humidity": as_finite((p.get("relativeHumidity") or {}).get("value")),
                    "wind_mph": _nws_forecast_wind_mph(p.get("windSpeed")),
                    "condition": p.get("shortForecast") or "Unknown",
                })
            return results
        except Exception as e:
            log.error("NWS forecast fetch failed: %s", e)
            return []


# mph per unit of an api.weather.gov observation's windSpeed, by its WMO
# unitCode. Observations report km/h (wmoUnit:km_h-1).
_NWS_WIND_MPH_PER_UNIT = {
    "wmoUnit:km_h-1": 0.621371,
    "wmoUnit:m_s-1": 2.23694,
    "wmoUnit:kt": 1.150779,
    "wmoUnit:mi_h-1": 1.0,
}
_NWS_DEFAULT_WIND_UNIT = "wmoUnit:km_h-1"


def _nws_observed_wind_mph(wind) -> float:
    """An NWS observation's windSpeed ({unitCode, value}) in mph, 0 when unknown.

    The factor follows the unitCode (km/h when it is missing or unknown):
    reading the km/h value as m/s overstated the wind 3.6x.
    """
    if not isinstance(wind, dict):
        return 0.0
    value = as_finite(wind.get("value"))
    if value is None:
        return 0.0
    unit = wind.get("unitCode")
    factor = _NWS_WIND_MPH_PER_UNIT.get(unit, _NWS_WIND_MPH_PER_UNIT[_NWS_DEFAULT_WIND_UNIT])
    return value * factor


_LEADING_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _nws_forecast_wind_mph(text) -> float:
    """An NWS hourly period's windSpeed text ("10 mph", "5 to 10 mph") in mph:
    its first number, 0 when it has none."""
    match = _LEADING_NUMBER.search(str(text or ""))
    return float(match.group()) if match else 0.0


# Registered providers, in failover order. The poller tries the operator's
# chosen provider (SPOREPRINT_WEATHER_PROVIDER / Settings) first, then the
# others in this order, so a provider registered here is both selectable and
# a failover.
_PROVIDERS: dict[str, Callable[[str], WeatherProvider]] = {
    "openmeteo": lambda api_key: OpenMeteoProvider(),
    "nws": lambda api_key: NWSProvider(),
    "openweathermap": OpenWeatherMapProvider,
}
DEFAULT_PROVIDER = "openmeteo"
PROVIDER_NAMES = tuple(_PROVIDERS)
# Providers that answer only with an API key (SPOREPRINT_WEATHER_API_KEY):
# without one every request fails, so the cascade leaves them out.
_KEYED_PROVIDERS = frozenset({"openweathermap"})


def get_provider(name: str, api_key: str = "") -> WeatherProvider:
    """Factory: the provider registered as `name` (Open-Meteo for an unknown name)."""
    return _PROVIDERS.get(name, _PROVIDERS[DEFAULT_PROVIDER])(api_key)


def provider_cascade(preferred: str, api_key: str = "") -> list[WeatherProvider]:
    """The providers the poller tries in turn: `preferred` first, then every
    other registered one in failover order, each once. A provider that needs
    a key joins only when one is set (chosen without a key, it is skipped).
    """
    if preferred not in _PROVIDERS:
        preferred = DEFAULT_PROVIDER
    names = [preferred, *(n for n in _PROVIDERS if n != preferred)]
    return [get_provider(n, api_key) for n in names if api_key or n not in _KEYED_PROVIDERS]


def _wmo_code_to_text(code: int) -> str:
    """Convert WMO weather interpretation code to human-readable text."""
    codes = {
        0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime Fog",
        51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
        61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
        71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
        80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
        95: "Thunderstorm", 96: "Thunderstorm + Hail", 99: "Heavy Thunderstorm",
    }
    return codes.get(code, "Unknown")
