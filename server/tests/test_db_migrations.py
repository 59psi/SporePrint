"""init_db must upgrade databases created by older releases in place.

SCHEMA is applied with CREATE ... IF NOT EXISTS, so on an existing database
the old table shape survives and only the `_add_column_if_missing` migrations
add the newer columns. Any index over a migrated column therefore has to be
created AFTER its migration — otherwise the SCHEMA script itself fails with
`no such column` and the server never boots.
"""

import aiosqlite

from app.config import settings
from app.db import init_db

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
