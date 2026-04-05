"""Weather provider adapters: Open-Meteo (default, no key), OpenWeatherMap, NWS."""

import logging
import math
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger(__name__)


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
            async with httpx.AsyncClient(timeout=10) as client:
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
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
                r.raise_for_status()
                data = r.json()
            hourly = data["hourly"]
            results = []
            for i, time_str in enumerate(hourly["time"]):
                from datetime import datetime
                ts = datetime.fromisoformat(time_str).timestamp()
                results.append({
                    "timestamp": ts,
                    "temp_f": hourly["temperature_2m"][i],
                    "humidity": hourly["relative_humidity_2m"][i],
                    "wind_mph": hourly["wind_speed_10m"][i] if hourly.get("wind_speed_10m") else 0,
                    "condition": _wmo_code_to_text(hourly["weather_code"][i] if hourly.get("weather_code") else 0),
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
            async with httpx.AsyncClient(timeout=10) as client:
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
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get("https://api.openweathermap.org/data/2.5/forecast", params=params)
                r.raise_for_status()
                data = r.json()
            return [
                {
                    "timestamp": entry["dt"],
                    "temp_f": entry["main"]["temp"],
                    "humidity": entry["main"]["humidity"],
                    "wind_mph": entry.get("wind", {}).get("speed", 0),
                    "condition": entry["weather"][0]["main"] if entry.get("weather") else "Unknown",
                }
                for entry in data.get("list", [])
            ]
        except Exception as e:
            log.error("OpenWeatherMap forecast fetch failed: %s", e)
            return []


class NWSProvider(WeatherProvider):
    """National Weather Service: US-only, free, no API key."""
    name = "nws"

    async def _get_station_url(self, lat: str, lon: str) -> str | None:
        """Resolve lat/lon to the nearest NWS observation station."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.weather.gov/points/{lat},{lon}",
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
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(stations_url, headers={"User-Agent": "SporePrint/1.0"})
                r.raise_for_status()
                station_id = r.json()["features"][0]["properties"]["stationIdentifier"]

                r = await client.get(
                    f"https://api.weather.gov/stations/{station_id}/observations/latest",
                    headers={"User-Agent": "SporePrint/1.0"},
                )
                r.raise_for_status()
                props = r.json()["properties"]

            temp_c = props.get("temperature", {}).get("value")
            rh = props.get("relativeHumidity", {}).get("value")
            wind_ms = props.get("windSpeed", {}).get("value")
            pressure = props.get("barometricPressure", {}).get("value")

            if temp_c is None:
                return None

            temp_f = round(temp_c * 9 / 5 + 32, 1)
            rh = round(rh, 0) if rh else 50
            return {
                "outdoor_temp_f": temp_f,
                "outdoor_humidity": rh,
                "outdoor_dew_point_f": _dew_point(temp_f, rh),
                "outdoor_wind_mph": round((wind_ms or 0) * 2.237, 1),
                "outdoor_pressure_mb": round((pressure or 101325) / 100, 1),
                "outdoor_condition": props.get("textDescription", "Unknown"),
            }
        except Exception as e:
            log.error("NWS current fetch failed: %s", e)
            return None

    async def fetch_forecast(self, lat: str, lon: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.weather.gov/points/{lat},{lon}",
                    headers={"User-Agent": "SporePrint/1.0"},
                )
                r.raise_for_status()
                forecast_url = r.json()["properties"]["forecastHourly"]

                r = await client.get(forecast_url, headers={"User-Agent": "SporePrint/1.0"})
                r.raise_for_status()
                periods = r.json()["properties"]["periods"]

            from datetime import datetime
            results = []
            for p in periods[:168]:  # max 7 days
                ts = datetime.fromisoformat(p["startTime"]).timestamp()
                temp_f = p["temperature"]
                results.append({
                    "timestamp": ts,
                    "temp_f": temp_f,
                    "humidity": p.get("relativeHumidity", {}).get("value", 50),
                    "wind_mph": float(str(p.get("windSpeed", "0")).split()[0]),
                    "condition": p.get("shortForecast", "Unknown"),
                })
            return results
        except Exception as e:
            log.error("NWS forecast fetch failed: %s", e)
            return []


def get_provider(name: str, api_key: str = "") -> WeatherProvider:
    """Factory: return the configured weather provider."""
    if name == "openweathermap":
        return OpenWeatherMapProvider(api_key)
    elif name == "nws":
        return NWSProvider()
    else:
        return OpenMeteoProvider()


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
