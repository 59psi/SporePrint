"""Safety watchdog (safety_max_on_seconds) hardening.

The watchdog is the fire-risk guard for an actuator automation switched ON and
nothing switched off. Each test below pins one way it used to be a silent
no-op:

  * vendor targets (Kasa/Tapo/Wemo/...) got their auto-OFF published to
    sporeprint/vendor:*/cmd/config — no subscriber — and logged as success
    (srv-cloud-int#0 / srv-auto#3);
  * boot rehydration sent expired OFFs inline before MQTT was connected (and to
    the wrong topic for plugs), then deleted the row regardless (srv-hw#0 /
    srv-auto#1);
  * every re-fire of a held-ON rule re-armed the ceiling, so it never tripped
    (srv-auto#0);
  * channel-less (plug) watchdog upserts never conflicted, piling up rows that
    rehydrate turned into orphaned tasks (srv-auto#20);
  * the Dry Weather Humidity Boost template ran the humidifier with no chamber
    humidity check, phase gate or ceiling, and cancelled Humidity Boost's
    ceiling on every fire (srv-auto#6).

A tripped held-ON ceiling locks automation out of the actuator; the lockout and
the actuator's ON commands are serialized per actuator so a re-fire racing the
trip can never be the last command on the wire.
"""

import asyncio
import json
import time

import pytest

import app.automation.engine as engine
import app.mqtt
from app.automation.engine import (
    _fire_rule,
    _persist_safety_watchdog,
    _safety_deadlines,
    _safety_tasks,
    _evaluate_condition,
    get_overrides,
    is_overridden,
    rehydrate_safety_watchdogs,
    set_override,
    suspend_rule,
)
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
    ManualOverride,
)
from app.automation.router import command_plug
from app.automation.service import create_rule, seed_builtin_rules, serialize_rule_data
from app.automation.templates import BUILTIN_RULES, LEGACY_BUILTIN_RULES
from app.db import get_db
from app.integrations import _actions as _vendor_actions

_real_sleep = asyncio.sleep


# ─── helpers ─────────────────────────────────────────────────────────────


def _rule(action: RuleAction, safety_max: int | None, name: str = "guard", rule_id: int = 1):
    return AutomationRule(
        id=rule_id,
        name=name,
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60),
        ),
        action=action,
        safety_max_on_seconds=safety_max,
        log_to_session=False,
    )


def _kasa(ip: str, on: bool = True, target: str | None = None) -> RuleAction:
    return RuleAction(
        target=target or f"vendor:kasa:{ip}",
        vendor_slug="kasa",
        vendor_action="set_power",
        vendor_params={"ip": ip, "on": on},
    )


@pytest.fixture(autouse=True)
def _fresh_actuator_state():
    """Per-actuator locks bind to the loop they were first contended on, and
    each test gets its own loop — start every test with none."""
    getattr(engine, "_actuator_locks", {}).clear()
    _safety_deadlines.clear()
    yield
    getattr(engine, "_actuator_locks", {}).clear()


@pytest.fixture
def fast_sleep(monkeypatch):
    """Collapse every engine sleep to a loop yield; records requested delays."""
    calls: list[float] = []

    async def _fast(delay):
        calls.append(delay)
        await _real_sleep(0)

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _fast)
    return calls


@pytest.fixture
def gated_sleep(monkeypatch):
    """Engine sleeps block until the returned Event is set, then return at once."""
    gate = asyncio.Event()

    async def _gated(_delay):
        await gate.wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _gated)
    return gate


@pytest.fixture
def frozen_sleep(monkeypatch):
    """Engine sleeps never return — a watchdog stays armed for the whole test."""
    async def _never(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", _never)


@pytest.fixture
def dispatch_calls(monkeypatch):
    calls: list[tuple[str, str, dict]] = []

    async def _dispatch(slug, action, params):
        calls.append((slug, action, dict(params)))
        return {"ok": True}

    monkeypatch.setattr(_vendor_actions, "dispatch", _dispatch)
    return calls


class _Notes(list):
    """(tier, title) pairs; the message bodies, in order, in .messages."""

    def __init__(self):
        super().__init__()
        self.messages: list[str] = []


@pytest.fixture
def notes(monkeypatch):
    """Capture engine notifications instead of POSTing to ntfy."""
    sent = _Notes()

    async def _warn(title, message, dedup_key=None):
        sent.append(("warning", title))
        sent.messages.append(message)

    async def _crit(title, message, tags=None, **kwargs):
        sent.append(("critical", title))
        sent.messages.append(message)

    monkeypatch.setattr(engine, "notify_warning", _warn)
    monkeypatch.setattr(engine, "notify_critical", _crit)
    return sent


async def _drain(key: str, timeout: float = 2.0) -> None:
    task = _safety_tasks.get(key)
    assert task is not None, f"no watchdog armed for {key}"
    await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


async def _watchdog_rows() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT target, channel, rule_name, expires_at FROM safety_watchdogs ORDER BY expires_at"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def _insert_watchdog(target: str, channel: str | None, rule_name: str, expires_at: float):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (target, channel, rule_name, expires_at - 60, expires_at),
        )
        await db.commit()


async def _register_plug(plug_id: str, plug_type: str, prefix: str, role: str | None = None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role) "
            "VALUES (?, ?, ?, ?, ?)",
            (plug_id, plug_id, plug_type, prefix, role),
        )
        await db.commit()


async def _firings() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT rule_name, status FROM automation_firings ORDER BY id")
        return [dict(r) for r in await cursor.fetchall()]


# ─── srv-cloud-int#0 / srv-auto#3 — vendor OFF goes through the dispatcher ─────


async def test_vendor_watchdog_dispatches_vendor_off_not_mqtt(
    fast_sleep, dispatch_calls, mock_mqtt, notes,
):
    await _fire_rule(_rule(_kasa("10.0.0.20"), safety_max=1), {"temp_f": 50}, session=None)
    await _drain("vendor:kasa:10.0.0.20:*")

    assert dispatch_calls == [
        ("kasa", "set_power", {"ip": "10.0.0.20", "on": True}),
        ("kasa", "set_power", {"ip": "10.0.0.20", "on": False}),
    ]
    assert mock_mqtt == [], "a vendor OFF must never be published to sporeprint/vendor:*"
    assert await _watchdog_rows() == []
    assert (await _firings())[-1] == {"rule_name": "safety_max_on_seconds:guard", "status": "sent"}


async def test_vendor_off_failure_keeps_row_and_pages_critical(
    fast_sleep, monkeypatch, mock_mqtt, notes,
):
    calls: list[dict] = []

    async def _dispatch(slug, action, params):
        calls.append(dict(params))
        if params.get("on") is False:
            raise RuntimeError("plug unreachable")
        return {"ok": True}

    monkeypatch.setattr(_vendor_actions, "dispatch", _dispatch)
    await _fire_rule(_rule(_kasa("10.0.0.20"), safety_max=1), {"temp_f": 50}, session=None)
    await _drain("vendor:kasa:10.0.0.20:*")

    off_attempts = [c for c in calls if c.get("on") is False]
    assert len(off_attempts) == len(engine._SAFETY_OFF_RETRY_DELAYS) + 1
    assert len(await _watchdog_rows()) == 1, "row must survive for the next boot's retry"
    assert (await _firings())[-1]["status"] == "failed"
    assert ("critical", "Safety cutoff FAILED: vendor:kasa:10.0.0.20") in notes


async def test_vendor_off_command_arms_nothing_and_clears_watchdog(
    frozen_sleep, dispatch_calls, mock_mqtt,
):
    # state defaults to "on" for every rule; set_power(on=False) is still an OFF.
    await _fire_rule(_rule(_kasa("10.0.0.20"), safety_max=600), {}, session=None)
    armed = _safety_tasks["vendor:kasa:10.0.0.20:*"]
    await _fire_rule(_rule(_kasa("10.0.0.20", on=False), safety_max=600), {}, session=None)

    await _real_sleep(0)
    assert armed.cancelled() or armed.done()
    assert "vendor:kasa:10.0.0.20:*" not in _safety_tasks
    assert await _watchdog_rows() == []


async def test_two_vendor_devices_under_one_target_each_keep_a_watchdog(
    fast_sleep, dispatch_calls, mock_mqtt, notes,
):
    await _fire_rule(_rule(_kasa("10.0.0.20", target="vendor:kasa"), 1, "a"), {}, session=None)
    first = _safety_tasks["vendor:kasa:10.0.0.20:*"]
    await _fire_rule(_rule(_kasa("10.0.0.21", target="vendor:kasa"), 1, "b", 2), {}, session=None)
    second = _safety_tasks["vendor:kasa:10.0.0.21:*"]
    await asyncio.wait_for(asyncio.gather(first, second), timeout=2)

    offs = {c[2]["ip"] for c in dispatch_calls if c[2]["on"] is False}
    assert offs == {"10.0.0.20", "10.0.0.21"}


async def test_setpoint_vendor_action_is_not_armed(frozen_sleep, dispatch_calls, mock_mqtt):
    action = RuleAction(
        target="vendor:quest", vendor_slug="quest", vendor_action="set_setpoint",
        vendor_params={"humidity_pct": 55},
    )
    await _fire_rule(_rule(action, safety_max=600), {}, session=None)
    assert _safety_tasks == {}
    assert await _watchdog_rows() == []


async def test_vendor_lockout_lands_on_rule_override_key(fast_sleep, dispatch_calls, mock_mqtt, notes):
    await _fire_rule(_rule(_kasa("10.0.0.20", target="vendor:kasa-heater"), 1), {}, session=None)
    await _drain("vendor:kasa:10.0.0.20:*")
    assert is_overridden("vendor:kasa-heater", None)


# ─── srv-hw#0 / srv-auto#1 — boot rehydration ────────────────────────────


async def test_rehydrate_never_sends_or_deletes_inline(frozen_sleep, mock_mqtt):
    await _insert_watchdog("relay-01", "heater", "heater-guard", time.time() - 3600)

    count = await rehydrate_safety_watchdogs()

    assert count == 1
    assert mock_mqtt == [], "no publish inline — MQTT is not connected yet at this point in boot"
    assert len(await _watchdog_rows()) == 1
    assert not _safety_tasks["relay-01:heater"].done()


async def test_rehydrate_expired_row_survives_until_off_is_delivered(fast_sleep, monkeypatch, notes):
    """mqtt._client is None during boot: the real mqtt_publish returns False.
    The row must stay so the OFF is retried, not be deleted after one miss."""
    monkeypatch.setattr(app.mqtt, "_client", None)
    await _insert_watchdog("plug-heater", None, "Heating Trigger", time.time() - 3600)

    await rehydrate_safety_watchdogs()
    await _drain("plug-heater:*")

    assert len(await _watchdog_rows()) == 1
    assert (await _firings())[-1]["status"] == "failed"


async def test_rehydrate_expired_plug_row_turns_plug_off(fast_sleep, mock_mqtt, mock_mqtt_raw, notes):
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await _insert_watchdog("plug-heater", None, "Heating Trigger", time.time() - 3600)

    await rehydrate_safety_watchdogs()
    await _drain("plug-heater:*")

    assert ("tasmota/a1b2c3/cmnd/POWER", "OFF") in mock_mqtt_raw
    assert [t for t, _ in mock_mqtt if t.startswith("sporeprint/plug-")] == []
    assert await _watchdog_rows() == []


async def test_rehydrate_expired_vendor_row_uses_dispatcher(fast_sleep, dispatch_calls, mock_mqtt, notes):
    await _insert_watchdog("vendor:tapo:10.0.0.9", None, "fogger", time.time() - 10)

    await rehydrate_safety_watchdogs()
    await _drain("vendor:tapo:10.0.0.9:*")

    assert dispatch_calls == [("tapo", "set_power", {"ip": "10.0.0.9", "on": False})]
    assert mock_mqtt == []
    assert await _watchdog_rows() == []


async def test_rehydrate_legacy_vendor_row_recovers_device_from_rule(
    fast_sleep, dispatch_calls, mock_mqtt, notes,
):
    """Rows armed before per-device keys carry the rule's free-form target."""
    await create_rule(_rule(_kasa("10.0.0.20", target="vendor:kasa"), 600, "night-heat"))
    await _insert_watchdog("vendor:kasa", None, "night-heat", time.time() - 10)

    await rehydrate_safety_watchdogs()
    await _drain("vendor:kasa:*")

    assert dispatch_calls == [("kasa", "set_power", {"ip": "10.0.0.20", "on": False})]


# ─── srv-auto#0 — a re-fired held-ON keeps its ceiling ───────────────────


async def test_refire_of_held_on_plug_keeps_original_deadline(frozen_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch):
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = _rule(RuleAction(target="plug-heater", state="on", duration_sec=600), 3600, "Heating Trigger")

    t0 = time.time()
    monkeypatch.setattr(engine.time, "time", lambda: t0)
    await _fire_rule(heat, {"temp_f": 50}, session=None)
    first = _safety_tasks["plug-heater:*"]
    rows_before = await _watchdog_rows()

    # Heating Trigger's cooldown is 300 s: it re-fires while temp stays low.
    for k in range(1, 12):
        monkeypatch.setattr(engine.time, "time", lambda k=k: t0 + 300 * k)
        await _fire_rule(heat, {"temp_f": 50}, session=None)

    assert _safety_tasks["plug-heater:*"] is first, "re-fire must not re-arm the ceiling"
    assert not first.done()
    assert _safety_deadlines["plug-heater:*"] == pytest.approx(t0 + 3600)
    assert await _watchdog_rows() == rows_before


async def test_tighter_ceiling_from_another_rule_wins(frozen_sleep, mock_mqtt):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 7200, "long"), {}, None)
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 600, "short", 2), {}, None)
    assert _safety_deadlines["relay-01:heater"] <= time.time() + 600
    assert (await _watchdog_rows())[0]["rule_name"] == "short"


async def test_native_pulse_refire_rearms_from_its_own_start(frozen_sleep, mock_mqtt, monkeypatch):
    """A native ON with a duration is a firmware-timed pulse: each pulse gets
    its own ceiling, as before (the firmware ends it and backstops max-on)."""
    pulse = _rule(RuleAction(target="relay-01", channel="fae", pwm=200, duration_sec=300), 1800)
    t0 = time.time()
    monkeypatch.setattr(engine.time, "time", lambda: t0)
    await _fire_rule(pulse, {}, session=None)
    first = _safety_tasks["relay-01:fae"]
    monkeypatch.setattr(engine.time, "time", lambda: t0 + 310)
    await _fire_rule(pulse, {}, session=None)
    await _real_sleep(0)
    assert first.cancelled() or first.done()
    assert _safety_deadlines["relay-01:fae"] == pytest.approx(t0 + 310 + 1800)


async def test_held_on_trip_locks_out_automation_and_warns(fast_sleep, mock_mqtt, notes):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 1, "heat"), {}, None)
    await _drain("relay-01:heater")

    assert mock_mqtt[-1] == ("sporeprint/relay-01/cmd/heater",
                             {"state": "off", "reason": "safety_max_on_seconds"})
    assert is_overridden("relay-01", "heater"), "next frame must not switch it straight back on"
    assert ("warning", "Safety cutoff: relay-01:heater") in notes


async def test_pulse_trip_is_a_benign_redundant_off(fast_sleep, mock_mqtt, notes):
    pulse = _rule(RuleAction(target="relay-01", channel="aux", pwm=255, duration_sec=8), 30, "Mist")
    await _fire_rule(pulse, {}, None)
    await _drain("relay-01:aux")

    assert mock_mqtt[-1][1]["state"] == "off"
    assert not is_overridden("relay-01", "aux")
    assert notes == []


async def test_on_without_ceiling_leaves_running_watchdog(frozen_sleep, mock_mqtt, mock_mqtt_raw):
    """Dry Weather Humidity Boost firing after Humidity Boost used to cancel
    Humidity Boost's 1800 s ceiling and arm nothing (srv-auto#6)."""
    await _register_plug("plug-9f7e", "shelly", "shellies/9f7e", role="humidifier")
    boost = _rule(RuleAction(target="plug-humidifier", state="on"), 1800, "Humidity Boost")
    extra = _rule(RuleAction(target="plug-humidifier", state="on"), None, "No Ceiling", 2)

    await _fire_rule(boost, {}, None)
    armed = _safety_tasks["plug-humidifier:*"]
    await _fire_rule(extra, {}, None)

    assert _safety_tasks["plug-humidifier:*"] is armed and not armed.done()
    assert len(await _watchdog_rows()) == 1


# ─── srv-auto#2 — holds / suspends leave the ceiling armed ────────────────


async def test_cloud_suspend_rule_keeps_watchdog(frozen_sleep, mock_mqtt):
    rule = _rule(RuleAction(target="relay-01", channel="heater"), 1800, "Heating Trigger")
    rule_id = await create_rule(rule)
    rule.id = rule_id
    await _fire_rule(rule, {}, None)
    armed = _safety_tasks["relay-01:heater"]

    await suspend_rule(rule_id, minutes=30)

    await _real_sleep(0)
    assert not armed.done()
    assert len(await _watchdog_rows()) == 1


# ─── srv-auto#20 — channel-less rows are replaced, not piled up ──────────


async def test_channel_less_watchdog_persist_is_an_upsert():
    for _ in range(3):
        await _persist_safety_watchdog("plug-heater", None, "Heating Trigger", 3600)
    assert len(await _watchdog_rows()) == 1


async def test_rehydrate_collapses_legacy_duplicate_rows(frozen_sleep):
    now = time.time()
    for offset in (600, 900, 1200):
        await _insert_watchdog("plug-heater", None, "Heating Trigger", now + offset)

    count = await rehydrate_safety_watchdogs()

    assert count == 1
    rows = await _watchdog_rows()
    assert len(rows) == 1 and rows[0]["expires_at"] == pytest.approx(now + 600)
    assert _safety_deadlines["plug-heater:*"] == pytest.approx(now + 600)


async def test_rehydrate_replaces_rather_than_orphans_a_live_task(frozen_sleep):
    await _insert_watchdog("relay-01", "heater", "h", time.time() + 600)
    await rehydrate_safety_watchdogs()
    first = _safety_tasks["relay-01:heater"]
    await rehydrate_safety_watchdogs()
    await _real_sleep(0)
    assert first.cancelled() or first.done()
    assert _safety_tasks["relay-01:heater"] is not first


# ─── srv-auto#6 — Dry Weather Humidity Boost template ────────────────────


def _dry_weather() -> AutomationRule:
    return next(r for r in BUILTIN_RULES if r.name == "Dry Weather Humidity Boost")


def test_dry_weather_boost_is_gated_and_bounded():
    rule = _dry_weather()
    assert rule.safety_max_on_seconds and rule.safety_max_on_seconds <= 1800
    assert set(rule.applies_to_phases or []) == {"primordia_induction", "fruiting"}

    class _Phase:
        humidity_max = 95.0

    dry_outside = {"outdoor_humidity": 20.0}
    assert _evaluate_condition(rule.condition, {**dry_outside, "humidity": 85.0}, _Phase())
    # Chamber already at its ceiling — dry outdoor air is no reason to add more.
    assert not _evaluate_condition(rule.condition, {**dry_outside, "humidity": 96.0}, _Phase())
    # No chamber humidity reading on this frame — never fire blind.
    assert not _evaluate_condition(rule.condition, dry_outside, _Phase())


async def _seed_rows(rules: list[AutomationRule]) -> None:
    async with get_db() as db:
        for r in rules:
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
                "VALUES (?, ?, ?, ?, ?)",
                (r.name, r.description, int(r.enabled), r.priority, serialize_rule_data(r)),
            )
        await db.commit()


async def _stored(name: str) -> AutomationRule:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data FROM automation_rules WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
    data = json.loads(row["rule_data"])
    data.update(id=row["id"], name=row["name"], enabled=bool(row["enabled"]), priority=row["priority"])
    return AutomationRule.model_validate(data)


async def test_seed_upgrades_unedited_legacy_dry_weather_rule():
    await _seed_rows([LEGACY_BUILTIN_RULES["Dry Weather Humidity Boost"]])
    await seed_builtin_rules()
    stored = await _stored("Dry Weather Humidity Boost")
    assert stored.condition == _dry_weather().condition
    assert stored.safety_max_on_seconds == _dry_weather().safety_max_on_seconds
    assert stored.applies_to_phases == _dry_weather().applies_to_phases


async def test_seed_leaves_operator_edited_rule_alone():
    edited = LEGACY_BUILTIN_RULES["Dry Weather Humidity Boost"].model_copy(
        update={"cooldown_seconds": 1200}
    )
    await _seed_rows([edited])
    await seed_builtin_rules()
    stored = await _stored("Dry Weather Humidity Boost")
    assert stored.cooldown_seconds == 1200
    assert stored.safety_max_on_seconds is None


# ─── srv-auto#0 follow-up — a re-fire racing the trip ─────────────────────


def _powers(raw: list[tuple[str, str]], prefix: str = "tasmota/a1b2c3") -> list[str]:
    return [p for t, p in raw if t == f"{prefix}/cmnd/POWER"]


async def test_refire_right_after_the_trip_off_is_refused(
    fast_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch, notes,
):
    """The next telemetry frame lands just after the trip's OFF went out. It
    must not switch the heater straight back on (with no ceiling left)."""
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = _rule(RuleAction(target="plug-heater", state="on"), 1, "Heating Trigger")
    real_send = engine.send_plug_command
    raced: list[bool] = []

    async def _send(target, state):
        ok = await real_send(target, state)
        if state == "off" and not raced:
            raced.append(True)
            await asyncio.create_task(_fire_rule(heat, {"temp_f": 50}, None))
        return ok

    monkeypatch.setattr(engine, "send_plug_command", _send)
    await _fire_rule(heat, {"temp_f": 50}, None)
    await _drain("plug-heater:*")

    assert raced
    assert _powers(mock_mqtt_raw) == ["ON", "OFF"]
    assert is_overridden("plug-heater", None)
    assert ("warning", "Safety cutoff: plug-heater") in notes


async def test_trip_waits_for_an_in_flight_on_then_switches_it_off(
    gated_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch, notes,
):
    """The ceiling trips while a re-fire's ON is still on the wire: the trip's
    OFF must land after that ON, not before it."""
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = _rule(RuleAction(target="plug-heater", state="on"), 3600, "Heating Trigger")
    await _fire_rule(heat, {"temp_f": 50}, None)
    trip = _safety_tasks["plug-heater:*"]

    real_send = engine.send_plug_command
    on_in_flight, release_on = asyncio.Event(), asyncio.Event()

    async def _send(target, state):
        if state == "on":
            on_in_flight.set()
            await release_on.wait()
        return await real_send(target, state)

    monkeypatch.setattr(engine, "send_plug_command", _send)
    refire = asyncio.create_task(_fire_rule(heat, {"temp_f": 50}, None))
    await asyncio.wait_for(on_in_flight.wait(), 2)
    gated_sleep.set()  # the ceiling trips now
    for _ in range(50):
        await _real_sleep(0.001)
    release_on.set()
    await asyncio.wait_for(refire, 2)
    await asyncio.wait_for(asyncio.shield(trip), 2)

    assert _powers(mock_mqtt_raw) == ["ON", "ON", "OFF"]
    assert is_overridden("plug-heater", None)


async def test_trip_under_an_operator_hold_keeps_the_hold_and_says_so(
    gated_sleep, mock_mqtt, notes,
):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 60, "heat"), {}, None)
    trip = _safety_tasks["relay-01:heater"]
    await set_override(ManualOverride(target="relay-01", channel="heater", reason="operator"))
    gated_sleep.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)

    assert [o.reason for o in await get_overrides()] == ["operator"]
    assert ("warning", "Safety cutoff: relay-01:heater") in notes
    assert "15 min" not in notes.messages[-1]
    assert "hold" in notes.messages[-1]


async def test_overlapping_arms_leave_exactly_one_live_watchdog(frozen_sleep):
    a = _rule(RuleAction(target="relay-01", channel="heater"), 600, "a")
    b = _rule(RuleAction(target="relay-01", channel="heater"), 300, "b", 2)
    await asyncio.gather(
        engine._arm_safety_watchdog("relay-01", "heater", a, held_on=True),
        engine._arm_safety_watchdog("relay-01", "heater", b, held_on=True),
    )
    await _real_sleep(0)
    live = [
        t for t in asyncio.all_tasks()
        if getattr(t.get_coro(), "__qualname__", "") == "_safety_auto_off" and not t.done()
    ]
    assert live == [_safety_tasks["relay-01:heater"]]


async def test_manual_plug_off_clears_the_ceiling_armed_under_its_role(
    frozen_sleep, mock_mqtt, mock_mqtt_raw,
):
    """An OFF sent outside automation must clear the ceiling, or the next
    automation ON keeps the stale deadline and trips early with a false page."""
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await _fire_rule(_rule(RuleAction(target="plug-heater", state="on"), 3600, "Heating Trigger"), {}, None)
    armed = _safety_tasks["plug-heater:*"]

    await command_plug("plug-a1b2c3", {"state": "off"})

    await _real_sleep(0)
    assert armed.cancelled() or armed.done()
    assert "plug-heater:*" not in _safety_tasks
    assert await _watchdog_rows() == []


async def test_note_actuator_off_clears_a_native_channel(frozen_sleep, mock_mqtt):
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 3600), {}, None)
    armed = _safety_tasks["relay-01:heater"]

    await engine.note_actuator_off("relay-01", "heater")

    await _real_sleep(0)
    assert armed.cancelled() or armed.done()
    assert await _watchdog_rows() == []


async def test_note_actuator_off_keeps_a_ceiling_whose_on_went_out_later(frozen_sleep, mock_mqtt):
    """The manual OFF started before an automation ON finished: that ON may be
    the last command on the wire, so its ceiling must stay armed."""
    off_started = time.time() - 5
    await _fire_rule(_rule(RuleAction(target="relay-01", channel="heater"), 3600), {}, None)
    armed = _safety_tasks["relay-01:heater"]

    await engine.note_actuator_off("relay-01", "heater", sent_at=off_started)

    await _real_sleep(0)
    assert _safety_tasks["relay-01:heater"] is armed and not armed.done()
    assert len(await _watchdog_rows()) == 1


# ─── srv-cloud-int#0 follow-up — vendor on/off meaning, reboot lockout ─────


async def test_vendor_string_false_is_read_as_an_off(frozen_sleep, dispatch_calls, mock_mqtt):
    """The dispatcher coerces lax booleans ("false"/"off"/"0" → False), so the
    watchdog must read set_power's `on` the same way."""
    await _fire_rule(_rule(_kasa("10.0.0.20"), 600), {}, None)
    armed = _safety_tasks["vendor:kasa:10.0.0.20:*"]
    off = RuleAction(
        target="vendor:kasa:10.0.0.20", vendor_slug="kasa", vendor_action="set_power",
        vendor_params={"ip": "10.0.0.20", "on": "false"},
    )
    await _fire_rule(_rule(off, 600, "off-rule", 2), {}, None)

    await _real_sleep(0)
    assert armed.cancelled() or armed.done()
    assert "vendor:kasa:10.0.0.20:*" not in _safety_tasks
    assert await _watchdog_rows() == []


async def test_vendor_string_on_arms_a_ceiling(frozen_sleep, dispatch_calls, mock_mqtt):
    on = RuleAction(
        target="vendor:kasa:10.0.0.20", vendor_slug="kasa", vendor_action="set_power",
        vendor_params={"ip": "10.0.0.20", "on": "on"},
    )
    await _fire_rule(_rule(on, 600), {}, None)
    assert "vendor:kasa:10.0.0.20:*" in _safety_tasks


async def test_rehydrated_vendor_trip_locks_out_the_rules_own_target(
    fast_sleep, dispatch_calls, mock_mqtt, notes,
):
    await create_rule(_rule(_kasa("10.0.0.20", target="vendor:kasa-heater"), 600, "night-heat"))
    await _insert_watchdog("vendor:kasa:10.0.0.20", None, "night-heat", time.time() - 10)

    await rehydrate_safety_watchdogs()
    await _drain("vendor:kasa:10.0.0.20:*")

    assert dispatch_calls == [("kasa", "set_power", {"ip": "10.0.0.20", "on": False})]
    assert is_overridden("vendor:kasa-heater", None)
