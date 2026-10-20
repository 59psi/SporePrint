"""Forecast-driven closet alerts + today's forecast high/low.

Forecast alerts: `_check_forecast_alerts` compared RAW OUTDOOR forecast temps to the
closet setpoints whenever no weather→closet model had been trained yet (the
first 7+ days of every install), labelled them "Predicted closet temp",
included hours that had already elapsed ("heat danger in 0h"), and re-sent the
CRITICAL page on every 10-minute poll.

Today's high/low: `forecast_high_f` / `forecast_low_f` spanned today AND tomorrow (and
any past hours in the cache), so the "Pre-cool for Hot Forecast" rule ran the
cooler all through a mild day because tomorrow would be hot.
"""

import time
from datetime import datetime, timedelta

import pytest

import app.notifications.service as notif
import app.weather.service as weather_svc
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, create_session
from app.species.service import seed_builtins
from app.weather.prediction import _store_model

# cubensis_golden_teacher substrate_colonization: 75–80 °F.
_MAX_F = 80.0
_MIN_F = 75.0


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


# ── forecast alerts ─────────────────────────────────────────────────────────


async def test_no_model_means_no_closet_alert_from_outdoor_temps(ntfy_posts):
    """Before a model exists the outdoor forecast says nothing about the closet."""
    await _active_session()
    forecast = _hourly(_now_hour() + 3600, [_MAX_F + 30] * 48)  # scorching outdoors
    await weather_svc._check_forecast_alerts(None, forecast)
    assert ntfy_posts == []


async def test_elapsed_hours_are_ignored(ntfy_posts):
    """Open-Meteo returns hours from 00:00 today; hours already past must not
    trigger 'danger in 0h'."""
    await _active_session()
    await _identity_model()
    past = _hourly(_now_hour() - 6 * 3600, [_MAX_F + 30] * 5)  # hot, but over
    future = _hourly(_now_hour() + 3600, [(_MIN_F + _MAX_F) / 2] * 48)  # in range
    await weather_svc._check_forecast_alerts(None, past + future)
    assert ntfy_posts == []


@pytest.mark.parametrize("temps,priority,title", [
    ([_MAX_F + 15] * 24, 5, "heat danger"),
    # The advisory's old 300 s dedup was shorter than the 600 s poll interval.
    ([_MAX_F + 7] * 24, 4, "Heat advisory"),
    # A closet predicted 5-10 °F below the minimum warned for heat but never
    # for cold; only past min - 10 did anything page.
    ([_MIN_F - 7] * 24, 4, "Cold advisory"),
], ids=["heat-danger", "heat-advisory", "cold-advisory"])
async def test_a_forecast_alert_pages_once_across_polls(ntfy_posts, temps, priority, title):
    """The same forecast condition re-evaluated every poll pages once, not
    every 10 min."""
    await _active_session()
    await _identity_model()
    forecast = _hourly(_now_hour() + 3600, temps)
    for _ in range(3):
        await weather_svc._check_forecast_alerts(None, forecast)
        # Age every dedup entry by more than a poll interval AND the generic
        # 15-min critical window: only a forecast-specific window holds.
        for key in list(notif._last_sent):
            notif._last_sent[key] -= 1000
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == priority
    assert title in ntfy_posts[0]["title"]


async def test_later_critical_is_not_masked_by_an_earlier_warning(ntfy_posts):
    await _active_session()
    await _identity_model()
    temps = [_MAX_F + 7] * 5 + [_MAX_F + 20] * 5  # warning soon, danger later
    await weather_svc._check_forecast_alerts(None, _hourly(_now_hour() + 3600, temps))
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == 5


# ── today's forecast high/low ───────────────────────────────────────────────


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


# ── cold advisory and provider gaps ─────────────────────────────────────────


async def test_a_null_forecast_hour_does_not_drop_the_alerts(ntfy_posts):
    """A provider gap (temp or humidity null, the key present) raised
    TypeError in the prediction, so the poll's alerts never went out."""
    await _active_session()
    await _identity_model()
    start = _now_hour() + 3600
    forecast = [
        {"timestamp": start, "temp_f": None, "humidity": 50},
        {"timestamp": start + 3600, "temp_f": _MAX_F + 1, "humidity": None},
        {"timestamp": start + 7200, "temp_f": _MAX_F + 15, "humidity": 50},
    ]
    await weather_svc._check_forecast_alerts(None, forecast)
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == 5


# ── every active grow, on the setpoints in force ───────────────────────────


async def _grow(name, species, phase, chamber_id=None, created_at=None) -> dict:
    s = await create_session(SessionCreate(
        name=name, species_profile_id=species, current_phase=phase, chamber_id=chamber_id,
    ))
    if created_at is not None:
        async with get_db() as db:
            await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?",
                             (created_at, s["id"]))
            await db.commit()
    return s


async def _chamber(name: str) -> int:
    async with get_db() as db:
        cursor = await db.execute("INSERT INTO chambers (name) VALUES (?)", (name,))
        await db.commit()
        return cursor.lastrowid


async def test_every_active_grow_gets_its_forecast_alert(ntfy_posts):
    """Only the newest active session anywhere was checked: with two chambers
    the older grow's heat danger never paged."""
    await seed_builtins()
    now = time.time()
    a, b = await _chamber("A"), await _chamber("B")
    await _grow("older", "blue_oyster", "fruiting", a, now - 100)   # 55-65 °F
    await _grow("newer", "pink_oyster", "fruiting", b, now)         # 70-85 °F
    await _identity_model()
    await weather_svc._check_forecast_alerts(None, _hourly(_now_hour() + 3600, [78.0] * 6))
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == 5
    assert "Blue Oyster (older) heat danger" in ntfy_posts[0]["title"]


async def test_rest_phase_is_checked_against_the_fruiting_envelope(ntfy_posts):
    """Most profiles define no rest phase: the engine runs it on the fruiting
    envelope, but the forecast alerts found no setpoints and went silent for
    every rest between flushes."""
    await seed_builtins()
    s = await _grow("flush", "blue_oyster", "fruiting")
    await advance_phase(s["id"], PhaseAdvance(phase="rest"))
    await _identity_model()
    await weather_svc._check_forecast_alerts(None, _hourly(_now_hour() + 3600, [85.0] * 6))
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == 5
    assert "heat danger" in ntfy_posts[0]["title"]


async def test_cold_storage_gets_no_closet_forecast_alert(ntfy_posts):
    """A jar in the fridge runs on no species setpoints: the closet forecast
    says nothing about it."""
    await seed_builtins()
    s = await _grow("jar", "blue_oyster", "substrate_colonization")
    await advance_phase(s["id"], PhaseAdvance(phase="cold_storage"))
    await _identity_model()
    await weather_svc._check_forecast_alerts(None, _hourly(_now_hour() + 3600, [85.0] * 6))
    assert ntfy_posts == []


# ── GET /api/weather/impact ────────────────────────────────────────────────


def _cache_forecast(monkeypatch, entries: list[dict]) -> None:
    monkeypatch.setattr(weather_svc, "_forecast_cache", entries)
    monkeypatch.setattr(weather_svc, "_forecast_cache_ts", time.time())


async def test_impact_tiers_follow_the_alert_bands(monkeypatch):
    """The endpoint called max + 5 a danger the alerts only advise on; now a
    danger is what pages CRITICAL, and anything outside the band a warning."""
    await seed_builtins()
    await _grow("tiers", "blue_oyster", "fruiting")  # 55-65 °F
    await _identity_model()

    async def impact_types(temp: float) -> list[str]:
        _cache_forecast(monkeypatch, _hourly(_now_hour() + 3600, [temp] * 4))
        return [i["type"] for i in (await weather_svc.get_forecast_impact())["impacts"]]

    assert await impact_types(60.0) == ["good"]
    assert await impact_types(68.0) == ["warning"]   # outside, no page
    assert await impact_types(72.0) == ["warning"]   # an advisory
    assert await impact_types(80.0) == ["danger"]    # a CRITICAL page


async def test_impact_reports_predicted_cold_and_skips_elapsed_hours(monkeypatch):
    """The trained-model branch checked heat only, and counted the hours since
    00:00 GMT ('reaches 110°F in -6h')."""
    await seed_builtins()
    await _grow("cold", "pink_oyster", "fruiting")  # 70-85 °F
    await _identity_model()
    elapsed_heat = _hourly(_now_hour() - 6 * 3600, [110.0] * 3)
    cold = _hourly(_now_hour() + 3600, [55.0] * 24)
    _cache_forecast(monkeypatch, elapsed_heat + cold)
    result = await weather_svc.get_forecast_impact()
    [impact] = result["impacts"]
    assert impact["type"] == "danger"
    assert "drops to 55°F" in impact["message"]
    assert " in -" not in impact["message"]
    assert all(p["forecast_time"] > time.time() - 3600 for p in result["predictions"])


async def test_impact_without_a_model_reads_the_outdoor_days(monkeypatch):
    await seed_builtins()
    await _grow("outdoor", "blue_oyster", "fruiting")
    _cache_forecast(monkeypatch, _hourly(_now_hour() + 3600, [90.0] * 4))
    result = await weather_svc.get_forecast_impact()
    assert result["predictions"] == []
    assert result["model_status"]["status"] == "learning"
    assert {i["type"] for i in result["impacts"]} == {"danger"}
    assert "Outdoor high 90.0°F" in result["impacts"][0]["message"]


async def test_impact_covers_every_active_grow_with_its_label(monkeypatch):
    await seed_builtins()
    now = time.time()
    a, b = await _chamber("A"), await _chamber("B")
    older = await _grow("older", "blue_oyster", "fruiting", a, now - 100)
    newer = await _grow("newer", "pink_oyster", "fruiting", b, now)
    await _identity_model()
    _cache_forecast(monkeypatch, _hourly(_now_hour() + 3600, [78.0] * 4))
    impacts = {i["session_id"]: i for i in (await weather_svc.get_forecast_impact())["impacts"]}
    assert impacts[older["id"]]["type"] == "danger"
    assert impacts[older["id"]]["chamber_id"] == a
    assert impacts[newer["id"]]["type"] == "good"
    assert impacts[newer["id"]]["session_name"] == "newer"


async def test_impact_for_a_rest_phase_uses_the_fruiting_envelope(monkeypatch):
    """A rest phase the profile does not define returned no impact at all."""
    await seed_builtins()
    s = await _grow("resting", "blue_oyster", "fruiting")
    await advance_phase(s["id"], PhaseAdvance(phase="rest"))
    await _identity_model()
    _cache_forecast(monkeypatch, _hourly(_now_hour() + 3600, [85.0] * 4))
    [impact] = (await weather_svc.get_forecast_impact())["impacts"]
    assert impact["type"] == "danger"
    assert impact["session_id"] == s["id"]


async def test_impact_with_no_active_grow_says_so(monkeypatch):
    _cache_forecast(monkeypatch, _hourly(_now_hour() + 3600, [70.0] * 4))
    [impact] = (await weather_svc.get_forecast_impact())["impacts"]
    assert impact["type"] == "info"


def test_impact_endpoint_survives_a_null_forecast_hour(client, monkeypatch):
    """max()/sum() over a None temperature or humidity made it a 500."""
    _cache_forecast(monkeypatch, [
        {"timestamp": _now_hour() + 3600, "temp_f": None, "humidity": None},
        {"timestamp": _now_hour() + 7200, "temp_f": 70.0, "humidity": None},
    ])
    r = client.get("/api/weather/impact")
    assert r.status_code == 200, r.text
    days = r.json()["forecast"]
    assert days and all(d["high_f"] == 70.0 and d["avg_humidity"] == 50.0 for d in days)


@pytest.fixture()
def pacific_host(monkeypatch):
    """Run as a Pi whose compose TZ is US Pacific."""
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_daily_summary_uses_the_local_day(pacific_host):
    """Days were bucketed and named in UTC: a local evening hour landed on the
    next day, and yesterday evening's hours (the cache starts at 00:00 GMT)
    set today's low."""
    now = datetime(2026, 10, 17, 12, 0).timestamp()        # Sat noon, local
    forecast = [
        {"timestamp": datetime(2026, 10, 16, 20, 0).timestamp(), "temp_f": 40.0},  # Fri evening
        {"timestamp": datetime(2026, 10, 17, 6, 0).timestamp(), "temp_f": 50.0},
        {"timestamp": datetime(2026, 10, 17, 20, 0).timestamp(), "temp_f": 55.0},  # Sun in UTC
        {"timestamp": datetime(2026, 10, 18, 12, 0).timestamp(), "temp_f": 65.0},
    ]
    days = weather_svc.summarize_daily(forecast, now)
    assert [(d["date"], d["day_name"], d["low_f"], d["high_f"]) for d in days] == [
        ("2026-10-17", "Sat", 50.0, 55.0),
        ("2026-10-18", "Sun", 65.0, 65.0),
    ]
