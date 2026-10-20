"""init_db must upgrade databases created by older releases in place.

SCHEMA is applied with CREATE ... IF NOT EXISTS, so on an existing database
the old table shape survives and only the `_add_column_if_missing` migrations
add the newer columns. Any index over a migrated column therefore has to be
created AFTER its migration — otherwise the SCHEMA script itself fails with
`no such column` and the server never boots.
"""

import sqlite3

import aiosqlite
import pytest

from app.config import settings
from app.db import _add_column_if_missing, init_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session

# automation_firings as it shipped before v3.3.0 (no status / error columns).
_PRE_330_FIRINGS = """
CREATE TABLE automation_firings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    rule_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    condition_met TEXT,
    action_taken TEXT,
    session_id INTEGER
);
INSERT INTO automation_firings (rule_id, rule_name, timestamp)
VALUES (1, 'legacy rule', 1700000000.0);
"""


async def test_init_db_upgrades_pre_330_automation_firings(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_PRE_330_FIRINGS)
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(db_path))

    await init_db()  # raised OperationalError: no such column: status

    async with aiosqlite.connect(db_path) as db:
        cols = {r[1] for r in await (await db.execute(
            "PRAGMA table_info(automation_firings)")).fetchall()}
        indexes = {r[1] for r in await (await db.execute(
            "PRAGMA index_list(automation_firings)")).fetchall()}
        row = await (await db.execute(
            "SELECT rule_name, status, error FROM automation_firings")).fetchone()
    assert {"status", "error"} <= cols
    assert "idx_firings_status" in indexes
    # The pre-existing row survives and picks up the column default.
    assert row == ("legacy rule", "sent", None)


async def test_init_db_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "twice.db"))
    await init_db()
    await init_db()
    async with aiosqlite.connect(settings.database_path) as db:
        indexes = {r[1] for r in await (await db.execute(
            "PRAGMA index_list(automation_firings)")).fetchall()}
    assert "idx_firings_status" in indexes


async def _pragma(db_path, name):
    async with aiosqlite.connect(db_path) as db:
        return (await (await db.execute(f"PRAGMA {name}")).fetchone())[0]


async def test_new_database_starts_in_incremental_auto_vacuum(tmp_path, monkeypatch):
    """A fresh install never needs the writer-stalling mode-switch VACUUM:
    auto_vacuum only sticks when set before WAL mode and the first table."""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(settings, "database_path", str(db_path))
    await init_db()
    assert await _pragma(db_path, "auto_vacuum") == 2  # INCREMENTAL
    assert await _pragma(db_path, "journal_mode") == "wal"


async def test_init_db_never_rewrites_an_existing_database(tmp_path, monkeypatch):
    """Converting an existing DB takes a full VACUUM; that is the lifespan's
    explicit, logged step (retention.ensure_incremental_auto_vacuum), never a
    side effect of init_db."""
    db_path = tmp_path / "legacy.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_PRE_330_FIRINGS)
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(db_path))
    await init_db()
    assert await _pragma(db_path, "auto_vacuum") == 0


async def test_rollup_history_query_uses_the_node_sensor_time_index(tmp_path, monkeypatch):
    """get_history's rollup branch filters node_id + sensor + a timestamp
    range; without this index it scanned every node's and sensor's rollups."""
    db_path = tmp_path / "idx.db"
    monkeypatch.setattr(settings, "database_path", str(db_path))
    await init_db()
    async with aiosqlite.connect(db_path) as db:
        indexes = {r[1] for r in await (await db.execute(
            "PRAGMA index_list(telemetry_rollups)")).fetchall()}
        plan = " ".join(str(r[3]) for r in await (await db.execute(
            "EXPLAIN QUERY PLAN SELECT timestamp, avg_value FROM telemetry_rollups "
            "WHERE node_id = ? AND sensor = ? AND timestamp >= ? AND timestamp <= ?",
            ("n1", "temp_f", 0.0, 1e12))).fetchall())
    assert "idx_rollup_node_sensor_time" in indexes
    assert "idx_rollup_node_sensor_time" in plan, plan


async def _plan(db, sql, params) -> list[str]:
    return [str(r[3]) for r in await (await db.execute("EXPLAIN QUERY PLAN " + sql, params)).fetchall()]


async def test_session_feed_reads_the_newest_events_off_the_index(tmp_path, monkeypatch):
    """The dashboard feeds read a session's newest N events (get_events with a
    limit). Indexed on session_id alone, every request sorted the session's
    whole history (thousands of rule firings) to keep N."""
    db_path = tmp_path / "events.db"
    async with aiosqlite.connect(db_path) as db:  # a database from before the index
        await db.executescript(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER NOT NULL, timestamp REAL, type TEXT NOT NULL, "
            "source TEXT NOT NULL, description TEXT, data TEXT);"
            "CREATE INDEX idx_events_session ON session_events(session_id);"
        )
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(db_path))
    await init_db()
    async with aiosqlite.connect(db_path) as db:
        indexes = {r[1] for r in await (await db.execute(
            "PRAGMA index_list(session_events)")).fetchall()}
        newest = await _plan(
            db,
            "SELECT * FROM (SELECT * FROM session_events WHERE session_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?) ORDER BY timestamp, id",
            (1, 40),
        )
        full = await _plan(
            db, "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp, id", (1,))
    assert indexes == {"idx_events_session_ts"}
    assert any("idx_events_session_ts" in step for step in newest), newest
    # Only the outer re-sort of the N rows kept; the history itself is never sorted.
    assert sum("TEMP B-TREE" in step for step in newest) == 1, newest
    assert not any("TEMP B-TREE" in step for step in full), full


async def test_frame_queries_use_the_vision_indexes(tmp_path, monkeypatch):
    """Chamber photos, GET /api/vision/frames and the harvest corroboration
    read frames newest first per camera or per session: without these
    indexes each one scanned and sorted the whole table."""
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "frames.db"))
    await init_db()
    async with aiosqlite.connect(settings.database_path) as db:
        photos = await _plan(
            db,
            "SELECT * FROM vision_frames WHERE node_id IN (?, ?) "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            ("cam-1", "cam-2", 6),
        )
        by_node = await _plan(
            db, "SELECT * FROM vision_frames WHERE node_id = ? ORDER BY timestamp DESC LIMIT ?",
            ("cam-1", 50))
        by_session = await _plan(
            db, "SELECT * FROM vision_frames WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (1, 50))
    for plan in (photos, by_node, by_session):
        assert not any(step.startswith("SCAN vision_frames") for step in plan), plan
    assert any("idx_vision_node_time" in step for step in photos + by_node)
    assert any("idx_vision_session_time" in step for step in by_session)
    assert not any("TEMP B-TREE" in step for step in by_node + by_session)


# actuator_events as it shipped before the lifetime counts table.
_PRE_COUNTS_ACTUATOR_EVENTS = """
CREATE TABLE actuator_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    node_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    action TEXT NOT NULL,
    value REAL,
    trigger TEXT NOT NULL,
    session_id INTEGER,
    created_at REAL DEFAULT (unixepoch('now'))
);
INSERT INTO actuator_events (timestamp, node_id, channel, action, trigger) VALUES
    (1700000000.0, 'relay-01', 'fan', 'on', 'report'),
    (1700000060.0, 'relay-01', 'fan', 'on', 'report'),
    (1700000120.0, 'relay-01', 'fan', 'off', 'command');
"""


async def test_init_db_starts_actuator_counts_from_existing_rows_once(tmp_path, monkeypatch):
    """The Grafana counter reads the lifetime counts: on the first boot that
    has them they start from the rows already stored (a counter that dropped
    to zero would read as a reset), and later boots never count them again."""
    db_path = tmp_path / "actuators.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_PRE_COUNTS_ACTUATOR_EVENTS)
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(db_path))
    await init_db()
    await init_db()
    async with aiosqlite.connect(db_path) as db:
        rows = sorted(await (await db.execute(
            "SELECT node_id, channel, action, n FROM actuator_event_counts")).fetchall())
    assert rows == [("relay-01", "fan", "off", 1), ("relay-01", "fan", "on", 2)]


# ── the first release's sessions + hardware_nodes tables ──────────────────

# As e87fe23 (the first release) created them: sessions had no location
# columns yet, and hardware_nodes none of the later diagnostics.
_FIRST_RELEASE_TABLES = """
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    species_profile_id TEXT NOT NULL,
    substrate TEXT,
    substrate_volume TEXT,
    substrate_prep_notes TEXT,
    inoculation_date TEXT,
    inoculation_method TEXT,
    spawn_source TEXT,
    current_phase TEXT NOT NULL DEFAULT 'substrate_colonization',
    growth_form TEXT,
    pinning_tek TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL DEFAULT (unixepoch('now')),
    completed_at REAL,
    total_wet_yield_g REAL DEFAULT 0,
    total_dry_yield_g REAL DEFAULT 0,
    biological_efficiency REAL
);
CREATE TABLE hardware_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    firmware_version TEXT,
    last_seen REAL,
    ip_address TEXT,
    status TEXT DEFAULT 'unknown',
    config TEXT,
    created_at REAL DEFAULT (unixepoch('now'))
);
INSERT INTO hardware_nodes (node_id, node_type, last_seen, status) VALUES
    ('climate-01', 'climate', 1700000000.0, 'online'),
    ('relay-01', 'relay', 1690000000.0, 'offline');
"""


async def _columns(db_path, table):
    async with aiosqlite.connect(db_path) as db:
        return {r[1] for r in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()}


@pytest.fixture()
async def first_release_db(tmp_path, monkeypatch):
    db_path = tmp_path / "first.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_FIRST_RELEASE_TABLES)
        await db.commit()
    monkeypatch.setattr(settings, "database_path", str(db_path))
    return db_path


async def test_init_db_adds_the_session_location_columns(first_release_db):
    """tub_number / shelf_number / shelf_side were added to CREATE TABLE with
    no migration: on such a database every session create failed."""
    await init_db()
    assert {"tub_number", "shelf_number", "shelf_side"} <= await _columns(
        first_release_db, "sessions")
    session = await create_session(SessionCreate(
        name="tub 3", species_profile_id="blue_oyster", tub_number="3",
        shelf_number=2, shelf_side="left"))
    assert (session["tub_number"], session["shelf_number"], session["shelf_side"]) == (
        "3", 2, "left")


async def test_upgrade_counts_nodes_already_offline_as_paged(first_release_db):
    """The liveness sweeper now pages once per silence, tracked by
    offline_notified_at. Nodes already offline at the upgrade count as paged,
    so the first boot does not page every node that went quiet long ago."""
    await init_db()
    async with aiosqlite.connect(first_release_db) as db:
        rows = dict(await (await db.execute(
            "SELECT node_id, offline_notified_at FROM hardware_nodes")).fetchall())
        await db.execute("UPDATE hardware_nodes SET status = 'offline' "
                         "WHERE node_id = 'climate-01'")
        await db.commit()
    assert rows["relay-01"] is not None
    assert rows["climate-01"] is None
    await init_db()  # later boots never mark a node that went offline since
    async with aiosqlite.connect(first_release_db) as db:
        marker = (await (await db.execute(
            "SELECT offline_notified_at FROM hardware_nodes WHERE node_id = 'climate-01'"
        )).fetchone())[0]
    assert marker is None


async def test_a_failed_migration_stops_boot(first_release_db, monkeypatch):
    """A failed ALTER (here a full SD card) used to be swallowed: the server
    booted without the column and every heartbeat upsert then failed with
    'no column named ...' until a restart."""
    real_execute = aiosqlite.Connection.execute

    async def _execute(self, sql, *args, **kwargs):
        if sql.startswith("ALTER TABLE hardware_nodes"):
            raise sqlite3.OperationalError("database or disk is full")
        return await real_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", _execute)
    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        await init_db()


async def test_a_column_added_concurrently_is_not_an_error():
    class _Racing:
        """PRAGMA predates the other process's ALTER; our ALTER then collides."""

        async def execute(self, sql, *args):
            if sql.startswith("PRAGMA"):
                class _Cursor:
                    async def fetchall(self):
                        return [(0, "id")]
                return _Cursor()
            raise sqlite3.OperationalError("duplicate column name: extra")

    assert await _add_column_if_missing(
        _Racing(), "PRAGMA table_info(t)", "extra", "ALTER TABLE t ADD COLUMN extra TEXT",
    ) is False
