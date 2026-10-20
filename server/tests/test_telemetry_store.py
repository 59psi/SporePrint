"""How telemetry is stored and read back: per-connection durability, the
(node, sensor, time) index, the newest-reading queries, node clocks far in
the future, and the manual ingest's input checks.
"""

import inspect
import time

import aiosqlite
import pytest

from app.config import settings
from app.db import get_db, init_db
from app.mqtt import _handle_message, get_reliability_counters
from app.node_clock import MAX_FUTURE_SKEW_SECONDS
from app.retention import service as retention_service
from app.retention.service import _restamp_future_readings
from app.telemetry import service as telemetry
from app.telemetry.service import get_latest, latest_node_timestamp, reading_rows


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))


@pytest.fixture()
def no_rules(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _noop)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _noop)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)


async def _put(node_id, sensor, value, ts):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value) VALUES (?, ?, ?, ?)",
            (ts, node_id, sensor, value))
        await db.commit()


# ── storage ───────────────────────────────────────────────────────────────


async def test_every_connection_runs_wal_with_synchronous_normal():
    async with get_db() as db:
        sync = (await (await db.execute("PRAGMA synchronous")).fetchone())[0]
        mode = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
    assert sync == 1  # NORMAL; it is per connection, and the default is FULL
    assert mode == "wal"


async def test_an_older_database_trades_the_node_index_for_node_sensor_time(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            "CREATE TABLE telemetry_readings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, node_id TEXT NOT NULL, sensor TEXT NOT NULL, "
            "value REAL NOT NULL, session_id INTEGER, created_at REAL);"
            "CREATE INDEX idx_telemetry_node ON telemetry_readings(node_id, sensor);")
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(path))
    await init_db()
    async with aiosqlite.connect(path) as db:
        names = {r[0] for r in await (await db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND tbl_name = 'telemetry_readings'")).fetchall()}
    assert "idx_telemetry_node" not in names
    assert "idx_telemetry_node_sensor_time" in names


def test_history_re_buckets_at_the_rollup_tiers_own_widths():
    # One map: retention builds its tiers at these widths, history reads them.
    assert telemetry.RESOLUTION_BUCKETS is retention_service.RESOLUTION_BUCKETS
    assert retention_service.RESOLUTION_BUCKETS == {"5min": 300, "hourly": 3600, "daily": 86400}
    source = inspect.getsource(retention_service)
    for width in (300, 3600, 86400):
        assert f"/ {width} AS INT" not in source, "a tier width written out again"


def test_values_that_are_not_finite_numbers_are_skipped():
    rows = reading_rows("n1", {
        "temp_f": 70, "humidity": None, "co2_ppm": float("nan"), "lux": float("inf"),
        "dew_point_f": "12", "weight_g": 10 ** 400, "door_open": True,
        "pressure_hpa": 1013.2, "unrelated": 5,
    }, 1_760_000_000.0, 7)
    assert [(r[2], r[3]) for r in rows] == [
        ("temp_f", 70.0), ("door_open", 1.0), ("pressure_hpa", 1013.2)]
    assert all(r[0] == 1_760_000_000.0 and r[4] == 7 for r in rows)


async def test_a_failed_insert_still_records_the_node_as_alive(no_rules, monkeypatch):
    """The readings and the last_seen touch share one transaction; a failed
    insert (here a session gone from under it: a foreign key) rolls back on
    its own, and the node's liveness still commits."""
    async def _gone_session(node_id, ts):
        return 424242

    monkeypatch.setattr("app.mqtt.active_session_for_node", _gone_session)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, last_seen) VALUES ('n1', 'climate', ?)",
            (time.time() - 3600,))
        await db.commit()
    before = time.time()
    await _handle_message(_Sio(), "sporeprint/n1/telemetry",
                          {"ts": time.time() - 60, "temp_f": 70.0, "replay": True})
    async with get_db() as db:
        count = (await (await db.execute("SELECT COUNT(*) FROM telemetry_readings")).fetchone())[0]
        seen = (await (await db.execute(
            "SELECT last_seen FROM hardware_nodes WHERE node_id = 'n1'")).fetchone())[0]
    assert count == 0
    assert seen >= before


# ── newest readings ───────────────────────────────────────────────────────


async def test_latest_is_the_newest_reading_of_each_node_and_sensor():
    now = time.time()
    for node in ("n1", "n2"):
        for sensor, base in (("temp_f", 70.0), ("humidity", 80.0)):
            for i in range(5):
                await _put(node, sensor, base + i, now - 100 + i)
    await _put("n3", "co2_ppm", 900.0, now - 3600)
    latest = {(r["node_id"], r["sensor"]): (r["value"], r["timestamp"])
              for r in await get_latest()}
    assert latest == {
        ("n1", "humidity"): (84.0, now - 96), ("n1", "temp_f"): (74.0, now - 96),
        ("n2", "humidity"): (84.0, now - 96), ("n2", "temp_f"): (74.0, now - 96),
        ("n3", "co2_ppm"): (900.0, now - 3600),
    }
    assert {(r["sensor"], r["value"]) for r in await get_latest("n1")} == {
        ("temp_f", 74.0), ("humidity", 84.0)}
    assert await get_latest("nobody") == []
    assert await latest_node_timestamp("n2") == pytest.approx(now - 96)
    assert await latest_node_timestamp("nobody") is None


async def test_latest_on_an_empty_table():
    assert await get_latest() == []


async def test_latest_reads_by_index_seeks_not_a_scan_of_the_history():
    plans = []
    async with get_db() as db:
        for sql, params in (
            (f"WITH RECURSIVE {telemetry._LATEST_PAIRS_ALL} {telemetry._LATEST_ROWS}", {}),
            (f"WITH RECURSIVE {telemetry._LATEST_PAIRS_NODE} {telemetry._LATEST_ROWS}",
             {"node": "n1"}),
        ):
            cursor = await db.execute("EXPLAIN QUERY PLAN " + sql, params)
            plans.append([r[3] for r in await cursor.fetchall()])
    for plan in plans:
        # The table appears as telemetry_readings, t or r; the CTEs (nodes,
        # pairs, p) may be scanned, the table never is.
        table_scans = [line for line in plan if line.split(" ")[:2] in (
            ["SCAN", "telemetry_readings"], ["SCAN", "t"], ["SCAN", "r"])]
        assert table_scans == [], plan
        assert any(line.startswith("SEARCH") for line in plan), plan


# ── a node clock far in the future ────────────────────────────────────────


async def test_a_far_future_frame_is_stored_at_its_arrival_time(no_rules):
    before = get_reliability_counters()["future_ts_clamps"]
    sio = _Sio()
    arrival = time.time()
    await _handle_message(sio, "sporeprint/n1/telemetry",
                          {"ts": arrival + 365 * 86400, "temp_f": 95.0})
    await _handle_message(sio, "sporeprint/n1/telemetry",
                          {"ts": time.time(), "temp_f": 72.0})
    (latest,) = await get_latest("n1")
    assert latest["value"] == 72.0
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT timestamp FROM telemetry_readings WHERE node_id = 'n1'")).fetchall()
    assert all(r[0] < time.time() + 1 for r in rows)
    assert get_reliability_counters()["future_ts_clamps"] == before + 1
    # Still live (the Pi's clock decides nothing), and the skew is reported.
    assert [d["temp_f"] for e, d in sio.events if e == "telemetry"] == [95.0, 72.0]
    assert get_reliability_counters()["node_clock_skew"]["n1"]["observed_at"] >= arrival


async def test_a_small_lead_is_kept_as_the_nodes_own_time(no_rules):
    ts = time.time() + MAX_FUTURE_SKEW_SECONDS / 2
    await _handle_message(_Sio(), "sporeprint/n1/telemetry", {"ts": ts, "temp_f": 70.0})
    assert await latest_node_timestamp("n1") == pytest.approx(ts)


async def test_a_replayed_far_future_frame_does_not_shadow_the_latest_reading(no_rules):
    now = time.time()
    await _handle_message(_Sio(), "sporeprint/n1/telemetry", {"ts": now, "temp_f": 72.0})
    await _handle_message(_Sio(), "sporeprint/n1/telemetry",
                          {"ts": now + 30 * 86400, "temp_f": 99.0, "replay": True})
    assert [r["value"] for r in await get_latest("n1")] == [72.0]


async def test_retention_restamps_readings_already_stored_in_the_future():
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, created_at) "
            "VALUES (?, 'n1', 'temp_f', 95.0, ?)", (now + 365 * 86400, now - 60))
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, created_at) "
            "VALUES (?, 'n1', 'temp_f', 72.0, ?)", (now - 30, now - 30))
        await db.commit()
    await _restamp_future_readings()
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT value, timestamp FROM telemetry_readings ORDER BY value")).fetchall()
    assert [(r[0], round(r[1])) for r in rows] == [(72.0, round(now - 30)), (95.0, round(now - 60))]
    assert (await get_latest("n1"))[0]["value"] == 72.0


# ── manual ingest ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    {"node_id": "m1", "ts": "yesterday", "temp_f": 70},
    {"node_id": "m1", "ts": True, "temp_f": 70},
    {"node_id": "m1", "ts": 10 ** 400, "temp_f": 70},
    {"node_id": 42, "temp_f": 70},
    {"node_id": "", "temp_f": 70},
])
def test_manual_ingest_refuses_a_bad_ts_or_node_id(client, body):
    assert client.post("/api/telemetry/ingest", json=body).status_code == 422


def test_manual_ingest_stores_a_numeric_ts(client):
    r = client.post("/api/telemetry/ingest",
                    json={"node_id": "m1", "ts": 1_760_000_000, "temp_f": 70, "co2_ppm": None})
    assert r.status_code == 200
    latest = client.get("/api/telemetry/latest", params={"node_id": "m1"}).json()
    assert [(r["sensor"], r["timestamp"]) for r in latest] == [("temp_f", 1_760_000_000.0)]
