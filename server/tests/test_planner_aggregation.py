"""Nightly weather_history aggregation reads the real chamber sensor names.

srv-auto#24: aggregate_daily_weather queried `sensor = 'temperature'`, which
nothing writes (ESP32 nodes publish temp_f; integrations write temp_c), so the
chamber columns were always NULL. Once fixed, a day with chamber data but no
weather provider inserts NULL outdoor temps, which get_calendar_data then fed
into score_species_match (None + 15.0 -> TypeError -> 500).
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import get_db
from app.planner.service import aggregate_daily_weather, get_calendar_data
from app.species.service import seed_builtins


def _yesterday_noon():
    y = datetime.now(timezone.utc) - timedelta(days=1)
    return y.strftime("%Y-%m-%d"), y.replace(hour=12, minute=0, second=0, microsecond=0).timestamp()


async def _raw(sensor, value, ts, node="climate-01"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node, sensor, value),
        )
        await db.commit()


async def _history_row(date_str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM weather_history WHERE date = ?", (date_str,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def test_chamber_temp_aggregated_from_temp_f():
    date_str, noon = _yesterday_noon()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO weather_readings (timestamp, provider, temp_f, humidity) VALUES (?, ?, ?, ?)",
            (noon, "test", 50.0, 60.0),
        )
        await db.commit()
    for i, v in enumerate((60.0, 64.0, 68.0)):
        await _raw("temp_f", v, noon + i * 60)
    await _raw("humidity", 90.0, noon)

    await aggregate_daily_weather()

    row = await _history_row(date_str)
    assert row["chamber_temp_avg_f"] == 64.0
    assert row["chamber_temp_min_f"] == 60.0
    assert row["chamber_temp_max_f"] == 68.0
    assert row["chamber_humidity_avg"] == 90.0


async def test_chamber_temp_falls_back_to_temp_c_integrations():
    date_str, noon = _yesterday_noon()
    await _raw("temp_c", 20.0, noon, node="aranet-1")
    await _raw("temp_c", 30.0, noon + 60, node="aranet-1")

    await aggregate_daily_weather()

    row = await _history_row(date_str)
    assert row is not None
    assert abs(row["chamber_temp_avg_f"] - 77.0) < 1e-9
    assert abs(row["chamber_temp_min_f"] - 68.0) < 1e-9
    assert abs(row["chamber_temp_max_f"] - 86.0) < 1e-9


async def test_calendar_skips_days_without_outdoor_data():
    """Chamber-only days (no weather provider) must not crash the calendar."""
    await seed_builtins()
    date_str, noon = _yesterday_noon()
    await _raw("temp_f", 65.0, noon)
    await aggregate_daily_weather()
    row = await _history_row(date_str)
    assert row is not None and row["outdoor_temp_avg_f"] is None

    assert await get_calendar_data() == []

    # A month that has outdoor data is still scored.
    async with get_db() as db:
        await db.execute(
            "INSERT INTO weather_history (date, outdoor_temp_avg_f, outdoor_humidity_avg) "
            "VALUES ('2025-06-15', 70.0, 60.0)"
        )
        await db.commit()
    cal = await get_calendar_data()
    assert [m["month"] for m in cal] == [6]


def test_calendar_endpoint_with_chamber_only_history(client):
    # The client fixture shares the per-test DB file; seed it synchronously.
    con = sqlite3.connect(settings.database_path)
    con.execute("INSERT INTO weather_history (date, chamber_temp_avg_f) VALUES ('2025-02-10', 66.0)")
    con.commit()
    con.close()

    r = client.get("/api/planner/calendar")
    assert r.status_code == 200
