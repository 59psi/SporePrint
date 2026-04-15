import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
-- Telemetry time-series
CREATE TABLE IF NOT EXISTS telemetry_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    node_id TEXT NOT NULL,
    sensor TEXT NOT NULL,
    value REAL NOT NULL,
    session_id INTEGER REFERENCES sessions(id),
    created_at REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry_readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_telemetry_node ON telemetry_readings(node_id, sensor);
CREATE INDEX IF NOT EXISTS idx_telemetry_session ON telemetry_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_sensor_time ON telemetry_readings(sensor, timestamp);

-- Actuator events
CREATE TABLE IF NOT EXISTS actuator_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    node_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    action TEXT NOT NULL,
    value REAL,
    trigger TEXT NOT NULL,
    session_id INTEGER REFERENCES sessions(id),
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Grow sessions
CREATE TABLE IF NOT EXISTS sessions (
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
    tub_number TEXT,
    shelf_number INTEGER,
    shelf_side TEXT,
    growth_form TEXT,
    pinning_tek TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL DEFAULT (unixepoch('now')),
    completed_at REAL,
    total_wet_yield_g REAL DEFAULT 0,
    total_dry_yield_g REAL DEFAULT 0,
    biological_efficiency REAL,
    chamber_id INTEGER REFERENCES chambers(id)
);

-- Phase history
CREATE TABLE IF NOT EXISTS phase_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    phase TEXT NOT NULL,
    entered_at REAL NOT NULL,
    exited_at REAL,
    trigger TEXT,
    params_snapshot TEXT
);

-- Session notes
CREATE TABLE IF NOT EXISTS session_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp REAL DEFAULT (unixepoch('now')),
    text TEXT NOT NULL,
    tags TEXT,
    image_id INTEGER
);

-- Harvests
CREATE TABLE IF NOT EXISTS harvests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp REAL DEFAULT (unixepoch('now')),
    flush_number INTEGER NOT NULL,
    wet_weight_g REAL,
    dry_weight_g REAL,
    quality_rating INTEGER,
    notes TEXT,
    image_ids TEXT
);

-- Session events (append-only event log)
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp REAL DEFAULT (unixepoch('now')),
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id);

-- Species profiles (user-created/modified)
CREATE TABLE IF NOT EXISTS species_profiles (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    is_builtin INTEGER DEFAULT 0,
    created_at REAL DEFAULT (unixepoch('now')),
    updated_at REAL DEFAULT (unixepoch('now'))
);

-- Automation rules
CREATE TABLE IF NOT EXISTS automation_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    rule_data TEXT NOT NULL,
    created_at REAL DEFAULT (unixepoch('now')),
    updated_at REAL DEFAULT (unixepoch('now'))
);

-- Vision frames
CREATE TABLE IF NOT EXISTS vision_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    node_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    file_path TEXT NOT NULL,
    resolution TEXT,
    flash_used INTEGER,
    analysis_local TEXT,
    analysis_claude TEXT,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Automation rule firings log
CREATE TABLE IF NOT EXISTS automation_firings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    rule_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    condition_met TEXT,
    action_taken TEXT,
    session_id INTEGER REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_firings_time ON automation_firings(timestamp);

-- Manual overrides
CREATE TABLE IF NOT EXISTS manual_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    channel TEXT,
    locked INTEGER DEFAULT 1,
    reason TEXT,
    expires_at REAL,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Smart plug registry
CREATE TABLE IF NOT EXISTS smart_plugs (
    plug_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plug_type TEXT NOT NULL DEFAULT 'shelly',
    mqtt_topic_prefix TEXT NOT NULL,
    device_role TEXT,
    status TEXT DEFAULT 'unknown',
    last_state TEXT,
    last_power_w REAL,
    last_seen REAL,
    config TEXT,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Builder guides
CREATE TABLE IF NOT EXISTS builder_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request TEXT NOT NULL,
    constraints TEXT,
    guide TEXT NOT NULL,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Hardware nodes registry
CREATE TABLE IF NOT EXISTS hardware_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    firmware_version TEXT,
    last_seen REAL,
    ip_address TEXT,
    status TEXT DEFAULT 'unknown',
    config TEXT,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Weather readings (outdoor conditions for automation)
CREATE TABLE IF NOT EXISTS weather_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    provider TEXT,
    temp_f REAL,
    humidity REAL,
    dew_point_f REAL,
    wind_mph REAL,
    pressure_mb REAL,
    condition TEXT,
    forecast_high_f REAL,
    forecast_low_f REAL
);
CREATE INDEX IF NOT EXISTS idx_weather_time ON weather_readings(timestamp DESC);

-- Weather forecasts (stored hourly forecast entries for prediction training)
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at REAL NOT NULL,
    forecast_time REAL NOT NULL,
    temp_f REAL,
    humidity REAL,
    wind_mph REAL,
    condition TEXT,
    provider TEXT
);
CREATE INDEX IF NOT EXISTS idx_forecast_time ON weather_forecasts(forecast_time);
CREATE INDEX IF NOT EXISTS idx_forecast_fetched ON weather_forecasts(fetched_at);

-- Telemetry rollups (compressed historical data)
CREATE TABLE IF NOT EXISTS telemetry_rollups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    node_id TEXT NOT NULL,
    sensor TEXT NOT NULL,
    resolution TEXT NOT NULL,
    avg_value REAL,
    min_value REAL,
    max_value REAL,
    count INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rollup_unique ON telemetry_rollups(timestamp, node_id, sensor, resolution);

-- Weather rollups (compressed historical weather)
CREATE TABLE IF NOT EXISTS weather_rollups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    resolution TEXT NOT NULL,
    avg_temp_f REAL,
    min_temp_f REAL,
    max_temp_f REAL,
    avg_humidity REAL,
    count INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weather_rollup_unique ON weather_rollups(timestamp, resolution);

-- Prediction models (learned weather→closet correlation coefficients)
CREATE TABLE IF NOT EXISTS prediction_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL DEFAULT (unixepoch('now')),
    model_type TEXT NOT NULL,
    coefficients TEXT NOT NULL,
    r_squared REAL,
    training_days INTEGER,
    training_samples INTEGER
);

-- Weather history (daily aggregates for planner)
CREATE TABLE IF NOT EXISTS weather_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    outdoor_temp_avg_f REAL,
    outdoor_temp_min_f REAL,
    outdoor_temp_max_f REAL,
    outdoor_humidity_avg REAL,
    chamber_temp_avg_f REAL,
    chamber_temp_min_f REAL,
    chamber_temp_max_f REAL,
    chamber_humidity_avg REAL
);
CREATE INDEX IF NOT EXISTS idx_weather_history_date ON weather_history(date);

-- Cultures (spawn/genetics tracking)
CREATE TABLE IF NOT EXISTS cultures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    parent_id INTEGER REFERENCES cultures(id),
    species_profile_id TEXT NOT NULL,
    source TEXT NOT NULL,
    vendor_name TEXT,
    lot_number TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    spore_print_quality TEXT,
    tissue_source_location TEXT,
    clone_success_rate REAL,
    storage_location TEXT,
    created_at REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX IF NOT EXISTS idx_cultures_species ON cultures(species_profile_id);
CREATE INDEX IF NOT EXISTS idx_cultures_parent ON cultures(parent_id);

-- Chambers (multi-chamber management)
CREATE TABLE IF NOT EXISTS chambers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    node_ids TEXT NOT NULL DEFAULT '[]',
    active_session_id INTEGER REFERENCES sessions(id),
    automation_rule_ids TEXT NOT NULL DEFAULT '[]',
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Experiments (A/B testing for grows)
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    control_session_id INTEGER NOT NULL REFERENCES sessions(id),
    variant_session_id INTEGER NOT NULL REFERENCES sessions(id),
    independent_variable TEXT NOT NULL,
    control_value TEXT NOT NULL,
    variant_value TEXT NOT NULL,
    dependent_variables TEXT NOT NULL DEFAULT '["total_wet_yield_g","colonization_days","contamination_count"]',
    status TEXT NOT NULL DEFAULT 'active',
    conclusion TEXT,
    created_at REAL DEFAULT (unixepoch('now')),
    completed_at REAL
);

-- Drying log entries (extends harvests)
CREATE TABLE IF NOT EXISTS drying_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    harvest_id INTEGER NOT NULL REFERENCES harvests(id),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp REAL DEFAULT (unixepoch('now')),
    weight_g REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drying_harvest ON drying_log(harvest_id);
"""


async def _add_column_if_missing(db, pragma_sql: str, column: str, alter_sql: str):
    """Add a column to an existing table if it doesn't exist yet."""
    try:
        cursor = await db.execute(pragma_sql)
        columns = {row[1] for row in await cursor.fetchall()}
        if column not in columns:
            await db.execute(alter_sql)
    except Exception:
        pass  # Table doesn't exist yet (will be created by SCHEMA)


async def init_db():
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(SCHEMA)
        # Migrations for databases created before v3.0
        await _add_column_if_missing(
            db, "PRAGMA table_info(weather_readings)", "provider",
            "ALTER TABLE weather_readings ADD COLUMN provider TEXT",
        )
        await _add_column_if_missing(
            db, "PRAGMA table_info(sessions)", "chamber_id",
            "ALTER TABLE sessions ADD COLUMN chamber_id INTEGER REFERENCES chambers(id)",
        )
        await db.commit()


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
