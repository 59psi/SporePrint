"""Rows and domain objects the server tests build: hardware nodes, smart plugs,
chambers, grows, telemetry, safety watchdogs and rule firings, species
profiles and automation rules.

Not collected (no ``test_`` prefix). Every builder writes through get_db(),
so it lands in the test's own database (conftest's ``_db``).
"""

import json
import time

from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleCondition,
    ThresholdCondition,
)
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile

DAY = 86_400

RELAY_CHANNELS = ["fae", "exhaust", "circulation", "aux"]
LIGHT_CHANNELS = ["white", "blue", "red", "far_red"]


async def rows(sql: str, *params) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]


# ── hardware nodes ─────────────────────────────────────────────────────────

# Defaults that differ from NULL: a node's heartbeats report its roles (its
# type among them) and stamp last_seen.
_ROLES_OF_ITS_TYPE = object()
_SEEN_NOW = object()


async def register_node(node_id: str, node_type: str = "relay",
                        channels: list[str] | None = None, *,
                        roles: list[str] | None = _ROLES_OF_ITS_TYPE,
                        last_seen: float | None = _SEEN_NOW, **columns) -> None:
    """A hardware_nodes row as a node's heartbeats leave it: roles
    ``[node_type]``, seen just now.

    ``channels`` None is a node that has not reported its channels yet;
    ``roles=None`` or ``last_seen=None`` leave that column NULL (firmware that
    reports no roles, a node never heard from). Any other column (status,
    config, ...) by keyword.
    """
    if roles is _ROLES_OF_ITS_TYPE:
        roles = [node_type]
    if last_seen is _SEEN_NOW:
        last_seen = time.time()
    row = {
        "node_id": node_id, "node_type": node_type,
        "roles": json.dumps(roles) if roles is not None else None,
        "channels": json.dumps(channels) if channels is not None else None,
        "last_seen": last_seen, **columns,
    }
    async with get_db() as db:
        await db.execute(
            f"INSERT INTO hardware_nodes ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
            tuple(row.values()),
        )
        await db.commit()


async def node_row(node_id: str) -> dict | None:
    found = await rows("SELECT * FROM hardware_nodes WHERE node_id = ?", node_id)
    return found[0] if found else None


async def node_ids() -> list[str]:
    return [r["node_id"] for r in await rows("SELECT node_id FROM hardware_nodes ORDER BY node_id")]


# ── smart plugs and chambers ───────────────────────────────────────────────


async def insert_plug(plug_id: str, plug_type: str, prefix: str, *, role: str | None = None,
                      config: dict | str | None = None, status: str = "unknown",
                      last_state: str | None = None, last_seen: float | None = None) -> None:
    """A smart_plugs row written straight to the table (register_plug checks
    the prefix; this does not, so a test can store one it refuses)."""
    if isinstance(config, dict):
        config = json.dumps(config)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role, "
            "config, status, last_state, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plug_id, plug_id, plug_type, prefix, role, config, status, last_state, last_seen),
        )
        await db.commit()


async def plug_row(plug_id: str) -> dict | None:
    found = await rows("SELECT * FROM smart_plugs WHERE plug_id = ?", plug_id)
    return found[0] if found else None


async def chamber(name: str, node_ids: list[str]) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES (?, ?)", (name, json.dumps(node_ids)),
        )
        await db.commit()
        return cursor.lastrowid


# ── safety watchdogs and rule firings ──────────────────────────────────────


async def insert_watchdog(target: str, channel: str | None, rule_name: str,
                          expires_at: float, *, armed_at: float | None = None) -> None:
    """A persisted safety ceiling, as a running Pi leaves one behind: armed
    by default a minute before it expired, or a minute ago if it has not
    (a row armed in the future says the clock is behind: rehydrate fires it
    at once)."""
    if armed_at is None:
        armed_at = min(expires_at, time.time()) - 60
    async with get_db() as db:
        await db.execute(
            "INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (target, channel, rule_name, armed_at, expires_at),
        )
        await db.commit()


async def watchdog_rows() -> list[dict]:
    return await rows("SELECT target, channel, rule_name, expires_at FROM safety_watchdogs "
                      "ORDER BY expires_at, target")


async def firings(rule_name: str | None = None) -> list[dict]:
    """automation_firings rows (rule_name, status, error), oldest first."""
    if rule_name is None:
        return await rows("SELECT rule_name, status, error FROM automation_firings ORDER BY id")
    return await rows("SELECT rule_name, status, error FROM automation_firings "
                      "WHERE rule_name = ? ORDER BY id", rule_name)


# ── grows ──────────────────────────────────────────────────────────────────


async def start_grow(species: str = "blue_oyster", phase: str | None = None, **kw) -> dict:
    """An active session (phase None: the profile's first)."""
    if phase is not None:
        kw["current_phase"] = phase
    return await create_session(SessionCreate(
        name=kw.pop("name", f"{species}-{phase}"), species_profile_id=species,
        substrate=kw.pop("substrate", "test"), **kw,
    ))


async def age_grow(session_id: int, seconds: float) -> None:
    """Move a grow's start `seconds` into the past (orders grows by age)."""
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = created_at - ? WHERE id = ?",
                         (seconds, session_id))
        await db.commit()


async def enter_open_phase_days_ago(session_id: int, days: float) -> None:
    """Backdate the entry of the phase a grow is in now."""
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (time.time() - days * DAY, session_id),
        )
        await db.commit()


# ── telemetry ──────────────────────────────────────────────────────────────


async def insert_reading(node_id: str, sensor: str, value: float, ts: float | None = None,
                         session_id: int | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time() if ts is None else ts, node_id, sensor, value, session_id),
        )
        await db.commit()


async def insert_rollup(node_id: str, sensor: str, ts: float, avg: float, mn: float | None = None,
                        mx: float | None = None, count: int = 12, resolution: str = "hourly") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, "
            "min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node_id, sensor, resolution, avg, avg if mn is None else mn,
             avg if mx is None else mx, count),
        )
        await db.commit()


async def readings(node_id: str, sensor: str | None = None) -> list[dict]:
    """A node's stored readings (one sensor, or all) as rows
    (timestamp, sensor, value, session_id), oldest first."""
    sql = ("SELECT timestamp, sensor, value, session_id FROM telemetry_readings "
           "WHERE node_id = ?")
    params: tuple = (node_id,)
    if sensor is not None:
        sql += " AND sensor = ?"
        params += (sensor,)
    return await rows(sql + " ORDER BY timestamp, id", *params)


async def stored_readings(node_id: str | None = None) -> set[tuple]:
    """Telemetry rows a poll stored, as a set: ``(sensor, value)`` for one
    node, or ``(node_id, sensor, value)`` for every node."""
    if node_id is None:
        found = await rows("SELECT node_id, sensor, value FROM telemetry_readings")
        return {(r["node_id"], r["sensor"], r["value"]) for r in found}
    found = await rows("SELECT sensor, value FROM telemetry_readings WHERE node_id = ?", node_id)
    return {(r["sensor"], r["value"]) for r in found}


# ── species profiles ───────────────────────────────────────────────────────

COLONIZATION = PhaseParams(
    temp_min_f=68, temp_max_f=75, humidity_min=70, humidity_max=80,
    co2_max_ppm=2000, co2_tolerance="high", light_hours_on=0,
    light_hours_off=24, light_spectrum="none", fae_mode="none",
    expected_duration_days=(10, 14),
)
PRIMORDIA = PhaseParams(
    temp_min_f=50, temp_max_f=55, humidity_min=90, humidity_max=95,
    co2_max_ppm=500, co2_tolerance="low", light_hours_on=12,
    light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
    expected_duration_days=(3, 5),
)
FRUITING = PhaseParams(
    temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
    co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
    light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
    expected_duration_days=(5, 7),
)


def custom_profile(**overrides) -> SpeciesProfile:
    """A valid custom gourmet profile ('custom_test'): substrate colonization
    (10-14 d) then fruiting (55-65 °F, 5-7 d) unless `phases` says otherwise."""
    fields = dict(
        id="custom_test",
        common_name="Test Species",
        scientific_name="Testus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock",
        phases={GrowPhase.SUBSTRATE_COLONIZATION: COLONIZATION, GrowPhase.FRUITING: FRUITING},
        flush_count_typical=3,
        yield_notes="Test yield",
    )
    fields.update(overrides)
    return SpeciesProfile(**fields)


# ── automation rules ───────────────────────────────────────────────────────


def threshold(sensor: str, operator: str, value: float | None = None,
              profile_ref: str | None = None) -> RuleCondition:
    return RuleCondition(type=ConditionType.THRESHOLD, threshold=ThresholdCondition(
        sensor=sensor, operator=operator, value=value, profile_ref=profile_ref))


def make_rule(action, *, condition: RuleCondition | None = None, ceiling: int | None = None,
              name: str = "guard", rule_id: int | None = 1, **kw) -> AutomationRule:
    """A rule on `action` (by default "temp_f below 60"), with a
    safety_max_on_seconds of `ceiling`."""
    return AutomationRule(
        id=rule_id, name=name, condition=condition or threshold("temp_f", "lt", 60),
        action=action, safety_max_on_seconds=ceiling, **kw,
    )
