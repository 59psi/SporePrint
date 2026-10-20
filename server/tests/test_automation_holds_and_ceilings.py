"""Manual holds, safety ceilings and the firing record.

The manual_overrides table and the in-memory cache hold the same one hold per
actuator; a safety lockout is never cut short by a shorter hold; a ceiling's
OFF reaches a scene-driven light; the trip, and every rule firing, is on
record before and whatever happens after the command goes out.
"""

import asyncio
import contextlib
import json
import sqlite3
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
from app.automation.coverage import compute_coverage
from app.automation.engine import (
    _fire_rule,
    _load_overrides_from_db,
    _sleep_until_due,
    evaluate_rules,
    get_overrides,
    is_overridden,
    rehydrate_safety_watchdogs,
    set_override,
)
from app.automation.models import (
    MAX_OVERRIDE_TTL_SECONDS,
    AutomationRule,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.service import seed_builtins

_real_sleep = asyncio.sleep


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "notify_critical", _noop)
    monkeypatch.setattr(engine, "notify_warning", _noop)
    monkeypatch.setattr(engine, "co2_alert", _noop)
    engine._paused = False
    engine._pause_loaded = False
    engine._actuator_locks.clear()
    engine._safety_deadlines.clear()


@pytest.fixture
def frozen_sleep(monkeypatch):
    async def _never(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _never)


@pytest.fixture
def fast_sleep(monkeypatch):
    async def _fast(_delay):
        await _real_sleep(0)

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _fast)


@pytest.fixture
def gated_sleep(monkeypatch):
    gate = asyncio.Event()

    async def _gated(_delay):
        await gate.wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _gated)
    return gate


def _rule(action, safety_max=None, name="guard", rule_id=1, **kw):
    return AutomationRule(
        id=rule_id, name=name,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60)),
        action=action, safety_max_on_seconds=safety_max, **kw,
    )


async def _rows(sql, *params):
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]


async def _drain(key):
    await asyncio.wait_for(asyncio.shield(engine._safety_tasks[key]), 2)


# ── one hold per actuator, in the table and the cache ──────────────────────


async def test_a_new_hold_replaces_the_one_on_the_same_actuator():
    await set_override(ManualOverride(target="node-relay", channel="fae", reason="cloud 2h",
                                      expires_at=time.time() + 7200))
    await set_override(ManualOverride(target="node-relay", channel="fae", reason="lan 1s",
                                      expires_at=time.time() + 1))
    rows = await _rows("SELECT reason FROM manual_overrides")
    assert [r["reason"] for r in rows] == ["lan 1s"]

    # Once the newer hold has run out, nothing comes back on a reload.
    later = time.time() + 5
    with patch.object(engine.time, "time", lambda: later):
        await _load_overrides_from_db()
        assert not is_overridden("node-relay", "fae")
    assert await _rows("SELECT * FROM manual_overrides") == []


async def test_older_duplicate_holds_collapse_to_the_newest_at_load():
    now = time.time()
    async with get_db() as db:
        for reason, expires in (("old 2h", now + 7200), ("new 10m", now + 600)):
            await db.execute(
                "INSERT INTO manual_overrides (target, channel, locked, reason, expires_at) "
                "VALUES ('node-relay', 'fae', 1, ?, ?)", (reason, expires),
            )
        await db.commit()
    await _load_overrides_from_db()
    assert [o.reason for o in await get_overrides()] == ["new 10m"]
    assert [r["reason"] for r in await _rows("SELECT reason FROM manual_overrides")] == ["new 10m"]


async def test_an_until_cancelled_hold_gets_its_ceiling_written_back():
    """Clamped in memory only, a hold with no expiry was re-clamped at every
    boot and never ended."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO manual_overrides (target, channel, locked, reason, expires_at) "
            "VALUES ('plug-heater', NULL, 1, 'forgotten', NULL)",
        )
        await db.commit()
    before = time.time()
    await _load_overrides_from_db()
    (row,) = await _rows("SELECT expires_at FROM manual_overrides")
    assert row["expires_at"] == pytest.approx(before + MAX_OVERRIDE_TTL_SECONDS, abs=60)


def test_an_expiry_of_zero_reads_as_expired(client):
    r = client.post("/api/automation/overrides",
                    json={"target": "plug-heater", "channel": None, "expires_at": 0})
    assert r.status_code == 200
    assert not is_overridden("plug-heater", None)
    assert client.get("/api/automation/overrides").json() == []


def test_a_nan_expiry_is_clamped_to_the_ceiling():
    ov = ManualOverride(target="plug-heater", expires_at=float("nan"))
    assert ov.expires_at == pytest.approx(time.time() + MAX_OVERRIDE_TTL_SECONDS, abs=5)


# ── the safety lockout is never shorter than its 15 minutes ────────────────


async def test_a_hold_about_to_end_does_not_cut_the_lockout_short(gated_sleep, mock_mqtt):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 60, "heat"), {}, None)
    trip = engine._safety_tasks["relay-01:heater"]
    await set_override(ManualOverride(target="relay-01", channel="heater", reason="maintenance",
                                      expires_at=time.time() + 1))
    gated_sleep.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)
    later = time.time() + 5
    with patch.object(engine.time, "time", lambda: later):
        assert is_overridden("relay-01", "heater")


# ── the trip is on record from the start ───────────────────────────────────


async def test_a_trip_is_recorded_pending_before_its_off_goes_out(fast_sleep, mock_mqtt, monkeypatch):
    sending, release = asyncio.Event(), asyncio.Event()
    real_send = engine._send_safety_off

    async def _blocked(target, channel, vendor_off):
        sending.set()
        await release.wait()
        return await real_send(target, channel, vendor_off)

    monkeypatch.setattr(engine, "_send_safety_off", _blocked)
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 1, "heat"), {}, None)
    trip = engine._safety_tasks["relay-01:heater"]
    await asyncio.wait_for(sending.wait(), 2)  # the OFF is on its way out, not out yet
    sql = "SELECT status FROM automation_firings WHERE rule_name = 'safety_max_on_seconds:heat'"
    assert [r["status"] for r in await _rows(sql)] == ["pending"]
    release.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)
    assert [r["status"] for r in await _rows(sql)] == ["sent"]


# ── a rehydrated ceiling does not trust a clock that is behind ─────────────


async def test_a_watchdog_armed_in_the_future_fires_at_once(fast_sleep, mock_mqtt):
    """The clock is provably behind (a Pi with no real-time clock, booted
    before NTP): the OFF goes out now, not hours later."""
    real_now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at) "
            "VALUES ('relay-01', 'heater', 'heat', ?, ?)", (real_now - 4000, real_now - 400),
        )
        await db.commit()
    with patch.object(engine.time, "time", lambda: real_now - 3 * 3600):
        await rehydrate_safety_watchdogs()
        await _drain("relay-01:heater")
    assert ("sporeprint/relay-01/cmd/heater",
            {"state": "off", "reason": "safety_max_on_seconds"}) in mock_mqtt


async def test_a_rehydrated_wait_ends_when_the_clock_catches_up(monkeypatch):
    """The wait re-checks the wall clock: a correcting NTP step ends it within
    one slice instead of after the overstated delay."""
    clock = {"wall": 1000.0, "mono": 0.0}
    slept: list[float] = []

    async def _sleep(delay):
        slept.append(delay)
        clock["mono"] += delay
        clock["wall"] += delay
        if len(slept) == 1:
            clock["wall"] += 3300  # NTP steps the clock forward

    monkeypatch.setattr(engine.asyncio, "sleep", _sleep)
    with patch.object(engine.time, "time", lambda: clock["wall"]), \
            patch.object(engine.time, "monotonic", lambda: clock["mono"]):
        await _sleep_until_due(3900.0, deadline=clock["wall"] + 600)
    assert sum(slept) <= 2 * engine._REHYDRATED_SLICE_SECONDS


# ── a ceiling on a scene rule switches the light off ───────────────────────


async def test_a_scene_rule_ceiling_trips_with_the_all_off_scene(fast_sleep, mock_mqtt):
    rule = _rule(RuleAction(target="light-01", scene="fruiting_standard"), 1, "lights")
    await _fire_rule(rule, {}, None)
    await _drain("light-01:*")
    assert mock_mqtt[0] == ("sporeprint/light-01/cmd/scene",
                            {"state": "on", "scene": "fruiting_standard"})
    assert mock_mqtt[-1] == ("sporeprint/light-01/cmd/scene",
                             {"state": "off", "scene": "colonization_dark",
                              "reason": "safety_max_on_seconds"})
    assert not [t for t, _ in mock_mqtt if t.endswith("/cmd/config")]


# ── the firing record and the bookkeeping after a publish ──────────────────


def _failing_update(real_get_db):
    """get_db whose firing-outcome UPDATE fails like a locked database."""
    class _Db:
        def __init__(self, db):
            self._db = db

        def __getattr__(self, name):
            return getattr(self._db, name)

        async def execute(self, sql, *args):
            if sql.startswith("UPDATE automation_firings"):
                raise sqlite3.OperationalError("database is locked")
            return await self._db.execute(sql, *args)

    @contextlib.asynccontextmanager
    async def _get_db():
        async with real_get_db() as db:
            yield _Db(db)

    return _get_db


async def test_a_ceiling_is_armed_even_when_recording_the_firing_fails(
        frozen_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch):
    await register_plug("plug-h1", "Heater", "tasmota", "tasmota/h1", device_role="heater")
    monkeypatch.setattr(engine, "get_db", _failing_update(engine.get_db))
    await _fire_rule(_rule(RuleAction(target="plug-heater", state="on"), 3600), {}, None)
    assert ("tasmota/h1/cmnd/POWER", "ON") in mock_mqtt_raw
    assert "plug-h1:*" in engine._safety_tasks


async def test_an_off_with_no_watchdog_deletes_nothing(mock_mqtt, monkeypatch):
    statements: list[str] = []
    real_get_db = engine.get_db

    class _Spy:
        def __init__(self, db):
            self._db = db

        def __getattr__(self, name):
            return getattr(self._db, name)

        async def execute(self, sql, *args):
            statements.append(sql)
            return await self._db.execute(sql, *args)

    @contextlib.asynccontextmanager
    async def _get_db():
        async with real_get_db() as db:
            yield _Spy(db)

    monkeypatch.setattr(engine, "get_db", _get_db)
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater", state="off")), {}, None)
    assert not [s for s in statements if "DELETE FROM safety_watchdogs" in s]


async def test_an_off_still_clears_a_persisted_watchdog(frozen_sleep, mock_mqtt):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 3600, "on"), {}, None)
    assert await _rows("SELECT * FROM safety_watchdogs")
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater", state="off"),
                           name="off", rule_id=2), {}, None)
    assert await _rows("SELECT * FROM safety_watchdogs") == []


async def _session_events(sid):
    return await _rows("SELECT description FROM session_events WHERE session_id = ? "
                       "AND type = 'automation'", sid)


async def test_only_a_command_that_went_out_reaches_the_grow_timeline(mock_mqtt, mock_mqtt_raw):
    await seed_builtins()
    session = await create_session(SessionCreate(
        name="timeline", species_profile_id="blue_oyster", substrate="straw",
        current_phase="fruiting"))
    # No humidifier paired: the command reaches nothing.
    await _fire_rule(_rule(RuleAction(target="plug-humidifier", state="on"), name="boost"),
                     {"humidity": 70}, session)
    # The broker is down.
    mock_mqtt.mock.return_value = False
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="fae"), name="fan", rule_id=2),
                     {"co2_ppm": 1500}, session)
    assert await _session_events(session["id"]) == []
    statuses = await _rows("SELECT status FROM automation_firings ORDER BY id")
    assert [r["status"] for r in statuses] == ["failed", "failed"]

    mock_mqtt.mock.return_value = True
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="fae"), name="fan", rule_id=2),
                     {"co2_ppm": 1500}, session)
    assert [e["description"] for e in await _session_events(session["id"])] == [
        "Rule 'fan' fired: relay-01/fae → on"]


# ── one invalid stored rule does not stop the others ───────────────────────


async def test_an_invalid_stored_rule_does_not_stop_the_co2_hard_ceiling(mock_mqtt):
    await seed_builtin_rules()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
            "VALUES ('broken', '', 1, 50, ?)",
            (json.dumps({"condition": {"type": "threshold"}, "action": {"target": "x"},
                         "cooldown_seconds": "often"}),),
        )
        await db.commit()
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert [p["state"] for t, p in mock_mqtt if t.endswith("/cmd/exhaust")] == ["on"]

    phases = [GrowPhase.FRUITING]
    pp = PhaseParams(temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                     co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
                     light_hours_off=12, light_spectrum="daylight_6500k",
                     fae_mode="continuous", expected_duration_days=(5, 10))
    profile = SpeciesProfile(
        id="test_sp", common_name="Test", scientific_name="Testus", category="gourmet",
        substrate_types=["straw"], colonization_visual_description="x",
        contamination_risk_notes="x", pinning_trigger_description="x",
        phases={p: pp for p in phases}, flush_count_typical=1, yield_notes="x",
    )
    assert await compute_coverage(profile)


# ── on/off values the engine cannot read are refused ───────────────────────


async def test_an_uppercase_on_arms_a_ceiling_and_an_uppercase_off_clears_it(
        frozen_sleep, mock_mqtt, mock_mqtt_raw):
    await register_plug("plug-h1", "Heater", "tasmota", "tasmota/h1", device_role="heater")
    on = _rule(RuleAction(target="plug-heater", state="ON"), 3600, "on")
    assert on.action.state == "on"
    await _fire_rule(on, {}, None)
    armed = engine._safety_tasks["plug-h1:*"]
    await _fire_rule(_rule(RuleAction(target="plug-heater", state=" OFF"), name="off",
                           rule_id=2), {}, None)
    await _real_sleep(0)
    assert armed.cancelled() or armed.done()
    assert await _rows("SELECT * FROM safety_watchdogs") == []


def _rule_body(**action):
    return {
        "name": "probe",
        "condition": {"type": "schedule", "schedule": {"photoperiod": "on"}},
        "action": {"target": "plug-heater", **action},
    }


def test_rule_writes_refuse_an_unreadable_state_or_photoperiod(client):
    assert client.post("/api/automation/rules", json=_rule_body(state="toggle")).status_code == 422
    body = _rule_body()
    body["condition"]["schedule"]["photoperiod"] = "bogus"
    assert client.post("/api/automation/rules", json=body).status_code == 422
    ok = client.post("/api/automation/rules", json=_rule_body(state="ON"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["action"]["state"] == "on"
