"""Nightly weather_history aggregation reads the real chamber sensor names.

aggregate_daily_weather queried `sensor = 'temperature'`, which
nothing writes (ESP32 nodes publish temp_f; integrations write temp_c), so the
chamber columns were always NULL. Once fixed, a day with chamber data but no
weather provider inserts NULL outdoor temps, which get_calendar_data then fed
into score_species_match (None + 15.0 -> TypeError -> 500).

The aggregation reads "yesterday" off the planner's clock, frozen here so a
run that crosses UTC midnight cannot aggregate a different day than the test
seeded.
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.db import get_db
from app.planner import service as planner_service
from app.planner.service import aggregate_daily_weather, get_calendar_data
from app.species.service import seed_builtins
from tests._builders import insert_reading

_TODAY = datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc)
YESTERDAY = "2026-07-14"
NOON = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc).timestamp()


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _TODAY if tz is not None else _TODAY.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _frozen_planner_clock(monkeypatch):
    monkeypatch.setattr(planner_service, "datetime", _FrozenDatetime)


async def _history_row(date_str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM weather_history WHERE date = ?", (date_str,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def test_chamber_temp_aggregated_from_temp_f_once_per_day():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO weather_readings (timestamp, provider, temp_f, humidity) VALUES (?, ?, ?, ?)",
            (NOON, "test", 50.0, 60.0),
        )
        await db.commit()
    for i, v in enumerate((60.0, 64.0, 68.0)):
        await insert_reading("climate-01", "temp_f", v, NOON + i * 60)
    await insert_reading("climate-01", "humidity", 90.0, NOON)
    await insert_reading("climate-01", "temp_f", 99.0, NOON - 86400)  # the day before: not counted

    await aggregate_daily_weather()
    await aggregate_daily_weather()  # the nightly job ran twice: still one row

    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM weather_history")).fetchall()
    [row] = [dict(r) for r in rows]
    assert row["date"] == YESTERDAY
    assert (row["outdoor_temp_avg_f"], row["outdoor_humidity_avg"]) == (50.0, 60.0)
    assert row["chamber_temp_avg_f"] == 64.0
    assert row["chamber_temp_min_f"] == 60.0
    assert row["chamber_temp_max_f"] == 68.0
    assert row["chamber_humidity_avg"] == 90.0


async def test_chamber_temp_falls_back_to_temp_c_integrations():
    await insert_reading("aranet-1", "temp_c", 20.0, NOON)
    await insert_reading("aranet-1", "temp_c", 30.0, NOON + 60)

    await aggregate_daily_weather()

    row = await _history_row(YESTERDAY)
    assert row is not None
    assert row["chamber_temp_avg_f"] == pytest.approx(77.0)
    assert row["chamber_temp_min_f"] == pytest.approx(68.0)
    assert row["chamber_temp_max_f"] == pytest.approx(86.0)


async def test_a_day_with_no_data_writes_no_row():
    await aggregate_daily_weather()
    assert await _history_row(YESTERDAY) is None


async def test_calendar_skips_days_without_outdoor_data():
    """Chamber-only days (no weather provider) must not crash the calendar."""
    await seed_builtins()
    await insert_reading("climate-01", "temp_f", 65.0, NOON)
    await aggregate_daily_weather()
    row = await _history_row(YESTERDAY)
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
    assert r.json() == []
