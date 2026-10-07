"""Forecast-driven closet alerts + today's forecast high/low.

srv-rest#5: `_check_forecast_alerts` compared RAW OUTDOOR forecast temps to the
closet setpoints whenever no weather→closet model had been trained yet (the
first 7+ days of every install), labelled them "Predicted closet temp",
included hours that had already elapsed ("heat danger in 0h"), and re-sent the
CRITICAL page on every 10-minute poll.

srv-rest#6: `forecast_high_f` / `forecast_low_f` spanned today AND tomorrow (and
any past hours in the cache), so the "Pre-cool for Hot Forecast" rule ran the
cooler all through a mild day because tomorrow would be hot.
"""

import json
import time
from datetime import datetime, timedelta

import httpx
import pytest

import app.notifications.service as notif
import app.weather.service as weather_svc
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins
from app.weather.prediction import _store_model

_RealAsyncClient = httpx.AsyncClient

# cubensis_golden_teacher substrate_colonization: 75–80 °F.
_MAX_F = 80.0
_MIN_F = 75.0


@pytest.fixture()
def ntfy(monkeypatch):
    """Real notifier over a MockTransport; returns the published JSON bodies."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"id": "x"})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealAsyncClient(*args, **kwargs)

    monkeypatch.setattr("app.config.settings.ntfy_url", "http://ntfy:80")
    monkeypatch.setattr(notif.httpx, "AsyncClient", factory)
    return bodies


async def _active_session():
    await seed_builtins()
    await create_session(SessionCreate(
        name="forecast-alerts",
        species_profile_id="cubensis_golden_teacher",
        substrate="CVG",
        current_phase="substrate_colonization",
    ))


async def _identity_model():
    """A trained temp model whose prediction == the outdoor forecast temp."""
    await _store_model("temp", {"coefficients": [1.0, 0.0, 0.0, 0.0], "r_squared": 0.9}, 10, 240)


def _hourly(start_ts: float, temps: list[float]) -> list[dict]:
    return [
        {"timestamp": start_ts + i * 3600, "temp_f": t, "humidity": 50}
        for i, t in enumerate(temps)
    ]


def _now_hour() -> float:
    now = time.time()
    return now - (now % 3600)


# ── srv-rest#5 ──────────────────────────────────────────────────────────────


async def test_no_model_means_no_closet_alert_from_outdoor_temps(ntfy):
    """Before a model exists the outdoor forecast says nothing about the closet."""
    await _active_session()
    forecast = _hourly(_now_hour() + 3600, [_MAX_F + 30] * 48)  # scorching outdoors
    await weather_svc._check_forecast_alerts(None, forecast)
    assert ntfy == []


async def test_elapsed_hours_are_ignored(ntfy):
    """Open-Meteo returns hours from 00:00 today; hours already past must not
    trigger 'danger in 0h'."""
    await _active_session()
    await _identity_model()
    past = _hourly(_now_hour() - 6 * 3600, [_MAX_F + 30] * 5)  # hot, but over
    future = _hourly(_now_hour() + 3600, [(_MIN_F + _MAX_F) / 2] * 48)  # in range
    await weather_svc._check_forecast_alerts(None, past + future)
    assert ntfy == []


async def test_forecast_critical_is_deduped_across_polls(ntfy):
    """The same forecast danger re-evaluated every poll pages once, not every 10 min."""
    await _active_session()
    await _identity_model()
    forecast = _hourly(_now_hour() + 3600, [_MAX_F + 15] * 24)
    for _ in range(3):
        await weather_svc._check_forecast_alerts(None, forecast)
        # Age every dedup entry by more than a poll interval AND the generic
        # 15-min critical window: only a forecast-specific window holds.
        for key in list(notif._last_sent):
            notif._last_sent[key] -= 1000
    assert len(ntfy) == 1
    assert ntfy[0]["priority"] == 5
    assert "heat danger" in ntfy[0]["title"]


async def test_heat_warning_is_deduped_across_polls(ntfy):
    """The warning's old 300 s dedup was shorter than the 600 s poll interval."""
    await _active_session()
    await _identity_model()
    forecast = _hourly(_now_hour() + 3600, [_MAX_F + 7] * 24)
    await weather_svc._check_forecast_alerts(None, forecast)
    for key in list(notif._last_sent):  # age the entry past one poll interval
        notif._last_sent[key] -= 1000
    await weather_svc._check_forecast_alerts(None, forecast)
    assert len(ntfy) == 1
    assert ntfy[0]["priority"] == 4


async def test_later_critical_is_not_masked_by_an_earlier_warning(ntfy):
    await _active_session()
    await _identity_model()
    temps = [_MAX_F + 7] * 5 + [_MAX_F + 20] * 5  # warning soon, danger later
    await weather_svc._check_forecast_alerts(None, _hourly(_now_hour() + 3600, temps))
    assert len(ntfy) == 1
    assert ntfy[0]["priority"] == 5


# ── srv-rest#6 ──────────────────────────────────────────────────────────────


async def test_forecast_high_low_cover_only_today(monkeypatch):
    day_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    today_noon = (day_start + timedelta(hours=12)).timestamp()
    today_morning = (day_start + timedelta(hours=6)).timestamp()
    yesterday_noon = (day_start - timedelta(hours=12)).timestamp()
    tomorrow_noon = (day_start + timedelta(days=1, hours=12)).timestamp()
    # monkeypatch restores the module global, so this synthetic forecast can't
    # leak into later tests regardless of fixture order.
    monkeypatch.setattr(weather_svc, "_forecast_cache", [
        {"timestamp": yesterday_noon, "temp_f": 101.0},
        {"timestamp": today_morning, "temp_f": 61.0},
        {"timestamp": today_noon, "temp_f": 72.0},
        {"timestamp": tomorrow_noon, "temp_f": 95.0},
    ])
    weather = {"outdoor_temp_f": 70.0, "outdoor_humidity": 50}
    await weather_svc._update_current_cache(weather, "openmeteo")
    assert weather["forecast_high_f"] == 72.0
    assert weather["forecast_low_f"] == 61.0
