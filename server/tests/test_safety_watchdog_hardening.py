"""The safety ceiling (safety_max_on_seconds) across reboots, re-fires, races
and failures.

Each test pins a way the ceiling used to be a silent no-op:

  * boot rehydration sent expired OFFs inline before MQTT was connected (and
    to the wrong topic for plugs and vendor devices), then deleted the row
    whatever happened;
  * every re-fire of a held-ON rule re-armed the ceiling, so it never tripped;
  * channel-less (plug) rows never conflicted on upsert and piled up, and
    rehydrate turned them into orphaned tasks;
  * a re-fire racing the trip could be the last command on the wire;
  * an OFF sent outside automation left the ceiling armed, so the next
    automation ON tripped early with a false page and a 15-minute lockout;
  * a database error in the bookkeeping could leave a heater with no ceiling.

The ceiling's basic life (arm, trip, lockout, the OFF on each transport, an
OFF ending it): tests/test_safety_max_on.py.
"""

import asyncio
import contextlib
import sqlite3
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
import app.mqtt
from app.automation.engine import (
    _evaluate_condition,
    _fire_rule,
    _persist_safety_watchdog,
    _safety_deadlines,
    _safety_tasks,
    _sleep_until_due,
    is_overridden,
    rehydrate_safety_watchdogs,
)
from app.automation.models import AutomationRule, RuleAction
from app.automation.router import command_plug
from app.automation.service import create_rule
from app.automation.templates import BUILTIN_RULES
from app.integrations import _actions as vendor_actions
from tests._builders import (
    firings,
    insert_plug,
    insert_watchdog,
    make_rule,
    rows,
    watchdog_rows,
)
from tests._timing import REAL_SLEEP, drain, ended

HEATER = RuleAction(target="relay-01", channel="heater")


def _kasa(ip: str, on=True, target: str | None = None) -> RuleAction:
    return RuleAction(
        target=target or f"vendor:kasa:{ip}",
        vendor_slug="kasa",
        vendor_action="set_power",
        vendor_params={"ip": ip, "on": on},
    )


def _powers(raw: list[tuple[str, str]], prefix: str = "tasmota/a1b2c3") -> list[str]:
    return [p for t, p in raw if t == f"{prefix}/cmnd/POWER"]


def _db_failing_on(fragment: str):
    """get_db whose statements containing `fragment` fail like a locked database."""
    real_get_db = engine.get_db

    class _Db:
        def __init__(self, db):
            self._db = db

        def __getattr__(self, name):
            return getattr(self._db, name)

        async def execute(self, sql, *args):
            if fragment in sql:
                raise sqlite3.OperationalError("database is locked")
            return await self._db.execute(sql, *args)

    @contextlib.asynccontextmanager
    async def _get_db():
        async with real_get_db() as db:
            yield _Db(db)

    return _get_db


# ── vendor devices ─────────────────────────────────────────────────────────


async def test_a_vendor_off_that_fails_keeps_the_row_and_pages_critical(
        fast_sleep, monkeypatch, mock_mqtt, alerts):
    calls: list[dict] = []

    async def _dispatch(slug, action, params):
        calls.append(dict(params))
        if params.get("on") is False:
            raise RuntimeError("plug unreachable")
        return {"ok": True}

    monkeypatch.setattr(vendor_actions, "dispatch", _dispatch)
    await _fire_rule(make_rule(_kasa("10.0.0.20"), ceiling=1), {"temp_f": 50}, None)
    await drain("vendor:kasa:10.0.0.20:*")

    off_attempts = [c for c in calls if c.get("on") is False]
    assert len(off_attempts) == len(engine._SAFETY_OFF_RETRY_DELAYS) + 1
    assert len(await watchdog_rows()) == 1, "the row must survive for the next boot's retry"
    assert (await firings())[-1]["status"] == "failed"
    assert [t for t, _ in alerts["critical"]] == ["Safety cutoff FAILED: vendor:kasa:10.0.0.20"]


async def test_two_vendor_devices_under_one_target_each_keep_a_ceiling(
        fast_sleep, dispatch_calls, mock_mqtt, quiet_alerts):
    await _fire_rule(make_rule(_kasa("10.0.0.20", target="vendor:kasa"), ceiling=1, name="a"),
                     {}, None)
    first = _safety_tasks["vendor:kasa:10.0.0.20:*"]
    await _fire_rule(make_rule(_kasa("10.0.0.21", target="vendor:kasa"), ceiling=1, name="b",
                               rule_id=2), {}, None)
    second = _safety_tasks["vendor:kasa:10.0.0.21:*"]
    await asyncio.wait_for(asyncio.gather(first, second), timeout=2)

    assert {c[2]["ip"] for c in dispatch_calls if c[2]["on"] is False} == {"10.0.0.20", "10.0.0.21"}


async def test_a_setpoint_vendor_action_arms_no_ceiling(frozen_sleep, dispatch_calls, mock_mqtt):
    action = RuleAction(target="vendor:quest", vendor_slug="quest", vendor_action="set_setpoint",
                        vendor_params={"humidity_pct": 55})
    await _fire_rule(make_rule(action, ceiling=600), {}, None)
    assert _safety_tasks == {}
    assert await watchdog_rows() == []


async def test_a_vendor_lockout_lands_on_the_rules_own_target(
        fast_sleep, dispatch_calls, mock_mqtt, quiet_alerts):
    """The rule's hold check reads its free-form target, not the device key."""
    await _fire_rule(make_rule(_kasa("10.0.0.20", target="vendor:kasa-heater"), ceiling=1),
                     {}, None)
    await drain("vendor:kasa:10.0.0.20:*")
    assert is_overridden("vendor:kasa-heater", None)


# ── boot rehydration ───────────────────────────────────────────────────────


async def test_rehydrate_never_sends_or_deletes_inline(frozen_sleep, mock_mqtt):
    await insert_watchdog("relay-01", "heater", "heater-guard", time.time() - 3600)

    assert await rehydrate_safety_watchdogs() == 1
    assert mock_mqtt == [], "no publish inline: MQTT is not connected yet at this point in boot"
    assert len(await watchdog_rows()) == 1
    assert not _safety_tasks["relay-01:heater"].done()


async def test_an_expired_row_survives_until_its_off_is_delivered(fast_sleep, monkeypatch,
                                                                  quiet_alerts):
    """During boot the broker is not connected: the real mqtt_publish returns
    False. The row must stay so the OFF is retried, not be deleted after one
    miss."""
    monkeypatch.setattr(app.mqtt, "_client", None)
    await insert_watchdog("relay-01", "heater", "Heating Trigger", time.time() - 3600)

    await rehydrate_safety_watchdogs()
    await drain("relay-01:heater")

    assert len(await watchdog_rows()) == 1
    assert (await firings())[-1]["status"] == "failed"


@pytest.mark.parametrize("target,channel", [("relay-01", "heater"), ("plug-heater", None)])
async def test_an_expired_row_switches_its_actuator_off_at_boot(
        fast_sleep, mock_mqtt, mock_mqtt_raw, quiet_alerts, target, channel):
    """A plug's row (kept under the role a rule named it by) goes out on the
    plug's own topic tree, never on sporeprint/plug-*."""
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await insert_watchdog(target, channel, "Heating Trigger", time.time() - 3600)

    await rehydrate_safety_watchdogs()
    await drain(f"{target}:{channel or '*'}")

    if channel:
        assert mock_mqtt == [("sporeprint/relay-01/cmd/heater",
                              {"state": "off", "reason": "safety_max_on_seconds"})]
        assert mock_mqtt_raw == []
    else:
        assert mock_mqtt == []
        assert _powers(mock_mqtt_raw) == ["OFF"]
    assert await watchdog_rows() == []


@pytest.mark.parametrize("row_target,rule_target,ip,locked_out", [
    # Keyed per device: the OFF is rebuilt from the key alone.
    ("vendor:tapo:10.0.0.9", None, "10.0.0.9", "vendor:tapo:10.0.0.9"),
    # Armed before per-device keys: the row holds the rule's free-form
    # target, and the rule says which device it switched.
    ("vendor:kasa", "vendor:kasa", "10.0.0.20", "vendor:kasa"),
    # Keyed per device, the lockout on the key the rule's hold check reads.
    ("vendor:kasa:10.0.0.20", "vendor:kasa-heater", "10.0.0.20", "vendor:kasa-heater"),
])
async def test_an_expired_vendor_row_is_switched_off_through_the_dispatcher(
        fast_sleep, dispatch_calls, mock_mqtt, quiet_alerts, row_target, rule_target, ip,
        locked_out):
    slug = row_target.split(":")[1]
    if rule_target:
        await create_rule(make_rule(_kasa(ip, target=rule_target), ceiling=600,
                                    name="night-heat", rule_id=None))
    await insert_watchdog(row_target, None, "night-heat", time.time() - 10)

    await rehydrate_safety_watchdogs()
    await drain(f"{row_target}:*")

    assert dispatch_calls == [(slug, "set_power", {"ip": ip, "on": False})]
    assert mock_mqtt == []
    assert await watchdog_rows() == []
    assert is_overridden(locked_out, None)


async def test_a_vendor_row_with_no_off_pages_critical_and_stays_for_the_next_boot(
        fast_sleep, dispatch_calls, mock_mqtt, alerts):
    """A vendor the watchdog cannot switch off must not read as handled."""
    await insert_watchdog("vendor:quest:dh-1", None, "dry-out", time.time() - 10)

    await rehydrate_safety_watchdogs()
    await drain("vendor:quest:dh-1:*")

    assert dispatch_calls == [] and mock_mqtt == []
    assert len(await watchdog_rows()) == 1
    assert (await firings())[-1]["status"] == "failed"
    assert [t for t, _ in alerts["critical"]] == ["Safety cutoff FAILED: vendor:quest:dh-1"]


async def test_a_watchdog_armed_in_the_future_fires_at_once(fast_sleep, mock_mqtt, quiet_alerts):
    """The clock is provably behind (a Pi with no real-time clock, booted
    before NTP): the OFF goes out now, not hours later."""
    real_now = time.time()
    await insert_watchdog("relay-01", "heater", "heat", real_now - 400, armed_at=real_now - 4000)
    with patch.object(engine.time, "time", lambda: real_now - 3 * 3600):
        await rehydrate_safety_watchdogs()
        await drain("relay-01:heater")
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


async def test_rehydrate_collapses_legacy_duplicate_rows(frozen_sleep):
    now = time.time()
    for offset in (600, 900, 1200):
        await insert_watchdog("plug-heater", None, "Heating Trigger", now + offset)

    assert await rehydrate_safety_watchdogs() == 1

    (row,) = await watchdog_rows()
    assert row["expires_at"] == pytest.approx(now + 600)
    assert _safety_deadlines["plug-heater:*"] == pytest.approx(now + 600)


async def test_rehydrate_replaces_rather_than_orphans_a_live_task(frozen_sleep):
    await insert_watchdog("relay-01", "heater", "h", time.time() + 600)
    await rehydrate_safety_watchdogs()
    first = _safety_tasks["relay-01:heater"]
    await rehydrate_safety_watchdogs()
    await REAL_SLEEP(0)
    assert ended(first)
    assert _safety_tasks["relay-01:heater"] is not first


async def test_a_channel_less_watchdog_persist_is_an_upsert():
    for _ in range(3):
        await _persist_safety_watchdog("plug-heater", None, "Heating Trigger", 3600)
    assert len(await watchdog_rows()) == 1


async def test_an_off_ends_a_ceiling_rehydrated_under_the_plugs_other_name(
        frozen_sleep, mock_mqtt, mock_mqtt_raw):
    """A ceiling rehydrated under the role it was armed by ends with an OFF
    that names the plug by id."""
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await insert_watchdog("plug-heater", None, "Heating Trigger", time.time() + 3000)
    await rehydrate_safety_watchdogs()
    armed = _safety_tasks["plug-heater:*"]

    await _fire_rule(make_rule(RuleAction(target="plug-a1b2c3", state="off"), name="off"), {}, None)
    await REAL_SLEEP(0)

    assert ended(armed)
    assert await watchdog_rows() == []



async def test_a_trip_that_is_no_longer_the_registered_ceiling_leaves_the_new_one_armed(
        monkeypatch, mock_mqtt, quiet_alerts):
    """An older trip that finishes after a newer ceiling took the actuator
    over must not deregister the newer one: that heater would run unbounded."""
    async def _sleep(delay):  # the newer ceiling waits; the older trip is due now
        if delay:
            await asyncio.Event().wait()
        await REAL_SLEEP(0)

    monkeypatch.setattr(engine.asyncio, "sleep", _sleep)
    await _fire_rule(make_rule(HEATER, ceiling=3600), {}, None)
    newer = _safety_tasks["relay-01:heater"]
    deadline = _safety_deadlines["relay-01:heater"]

    await engine._safety_auto_off("relay-01", "heater", 0, "older", held_on=False)

    assert mock_mqtt[-1] == ("sporeprint/relay-01/cmd/heater",
                             {"state": "off", "reason": "safety_max_on_seconds"})
    assert _safety_tasks["relay-01:heater"] is newer and not newer.done()
    assert _safety_deadlines["relay-01:heater"] == deadline

# ── a re-fired held-ON keeps its ceiling ───────────────────────────────────


async def test_a_refire_of_a_held_on_plug_keeps_its_original_deadline(
        frozen_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch):
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = make_rule(RuleAction(target="plug-heater", state="on", duration_sec=600), ceiling=3600,
                     name="Heating Trigger")

    t0 = time.time()
    monkeypatch.setattr(engine.time, "time", lambda: t0)
    await _fire_rule(heat, {"temp_f": 50}, None)
    # Kept under the plug's own id, whichever name the rule used.
    first = _safety_tasks["plug-a1b2c3:*"]
    rows_before = await watchdog_rows()

    # Heating Trigger's cooldown is 300 s: it re-fires while the closet stays cold.
    for k in range(1, 12):
        monkeypatch.setattr(engine.time, "time", lambda k=k: t0 + 300 * k)
        await _fire_rule(heat, {"temp_f": 50}, None)

    assert _safety_tasks["plug-a1b2c3:*"] is first, "a re-fire must not re-arm the ceiling"
    assert not first.done()
    assert _safety_deadlines["plug-a1b2c3:*"] == pytest.approx(t0 + 3600)
    assert await watchdog_rows() == rows_before


async def test_a_tighter_ceiling_from_another_rule_wins(frozen_sleep, mock_mqtt):
    await _fire_rule(make_rule(HEATER, ceiling=7200, name="long"), {}, None)
    await _fire_rule(make_rule(HEATER, ceiling=600, name="short", rule_id=2), {}, None)
    assert _safety_deadlines["relay-01:heater"] <= time.time() + 600
    assert (await watchdog_rows())[0]["rule_name"] == "short"


async def test_a_native_pulse_refire_rearms_from_its_own_start(frozen_sleep, mock_mqtt, monkeypatch):
    """A native ON with a duration is a firmware-timed pulse: each pulse gets
    its own ceiling (the firmware ends it, and backstops max-on)."""
    pulse = make_rule(RuleAction(target="relay-01", channel="fae", pwm=200, duration_sec=300),
                      ceiling=1800)
    t0 = time.time()
    monkeypatch.setattr(engine.time, "time", lambda: t0)
    await _fire_rule(pulse, {}, None)
    first = _safety_tasks["relay-01:fae"]
    monkeypatch.setattr(engine.time, "time", lambda: t0 + 310)
    await _fire_rule(pulse, {}, None)
    await REAL_SLEEP(0)
    assert ended(first)
    assert _safety_deadlines["relay-01:fae"] == pytest.approx(t0 + 310 + 1800)


async def test_an_on_without_a_ceiling_leaves_the_running_one(frozen_sleep, mock_mqtt,
                                                             mock_mqtt_raw):
    """Dry Weather Humidity Boost firing after Humidity Boost used to cancel
    Humidity Boost's 1800 s ceiling and arm nothing."""
    await insert_plug("plug-9f7e", "shelly", "shellies/9f7e", role="humidifier")
    await _fire_rule(make_rule(RuleAction(target="plug-humidifier"), ceiling=1800,
                               name="Humidity Boost"), {}, None)
    armed = _safety_tasks["plug-9f7e:*"]
    await _fire_rule(make_rule(RuleAction(target="plug-humidifier"), name="No Ceiling",
                               rule_id=2), {}, None)

    assert _safety_tasks["plug-9f7e:*"] is armed and not armed.done()
    assert len(await watchdog_rows()) == 1


async def test_overlapping_arms_leave_exactly_one_live_watchdog(frozen_sleep):
    a = make_rule(HEATER, ceiling=600, name="a")
    b = make_rule(HEATER, ceiling=300, name="b", rule_id=2)
    await asyncio.gather(
        engine._arm_safety_watchdog("relay-01", "heater", a, held_on=True),
        engine._arm_safety_watchdog("relay-01", "heater", b, held_on=True),
    )
    await REAL_SLEEP(0)
    live = [
        t for t in asyncio.all_tasks()
        if getattr(t.get_coro(), "__qualname__", "") == "_safety_auto_off" and not t.done()
    ]
    assert live == [_safety_tasks["relay-01:heater"]]


# ── a re-fire racing the trip ──────────────────────────────────────────────


async def test_a_refire_right_after_the_trip_off_is_refused(
        fast_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch, alerts):
    """The next frame lands just after the trip's OFF went out. It must not
    switch the heater straight back on (with no ceiling left)."""
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = make_rule(RuleAction(target="plug-heater"), ceiling=1, name="Heating Trigger")
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
    await drain("plug-a1b2c3:*")  # the plug's own id, whichever name the rule used

    assert raced
    assert _powers(mock_mqtt_raw) == ["ON", "OFF"]
    assert is_overridden("plug-a1b2c3", None)
    assert [t for t, _ in alerts["warning"]] == ["Safety cutoff: plug-a1b2c3"]


async def test_a_trip_waits_for_an_in_flight_on_then_switches_it_off(
        gated_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch, quiet_alerts):
    """The ceiling trips while a re-fire's ON is still on the wire: the trip's
    OFF must land after that ON, not before it."""
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    heat = make_rule(RuleAction(target="plug-heater"), ceiling=3600, name="Heating Trigger")
    await _fire_rule(heat, {"temp_f": 50}, None)
    trip = _safety_tasks["plug-a1b2c3:*"]

    real_send, real_lock = engine.send_plug_command, engine._actuator_lock
    on_in_flight, release_on, off_sent = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trip_at_lock = asyncio.Event()
    trip_lock: list[asyncio.Lock] = []

    async def _send(target, state):
        if state == "on":
            on_in_flight.set()
            await release_on.wait()
        else:
            off_sent.set()
        return await real_send(target, state)

    def _lock(key):
        lock = real_lock(key)
        if asyncio.current_task() is trip:
            trip_lock.append(lock)
            trip_at_lock.set()
        return lock

    monkeypatch.setattr(engine, "send_plug_command", _send)
    monkeypatch.setattr(engine, "_actuator_lock", _lock)
    refire = asyncio.create_task(_fire_rule(heat, {"temp_f": 50}, None))
    await asyncio.wait_for(on_in_flight.wait(), 2)
    gated_sleep.set()  # the ceiling trips now
    # Let the trip get as far as it can: queued behind the ON (its actuator
    # lock is held), or, with nothing holding it back, all the way to its OFF.
    await asyncio.wait_for(trip_at_lock.wait(), 2)
    if not trip_lock[0].locked():
        await asyncio.wait_for(off_sent.wait(), 2)
    release_on.set()
    await asyncio.wait_for(refire, 2)
    await asyncio.wait_for(asyncio.shield(trip), 2)

    assert _powers(mock_mqtt_raw) == ["ON", "ON", "OFF"]
    assert is_overridden("plug-a1b2c3", None)


# ── an OFF from outside automation ends the ceiling ────────────────────────


@pytest.mark.parametrize("plug_id,plug_type,prefix,named", [
    ("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", "plug-heater"),           # by its role
    ("plug-plugsg3-b1", "shelly_gen2", "shellies/plugsg3-b1", "plug-plugsg3-b1"),  # by its id
])
async def test_a_manual_plug_off_clears_the_ceiling_a_rule_armed(
        frozen_sleep, mock_mqtt, mock_mqtt_raw, plug_id, plug_type, prefix, named):
    """Otherwise the next automation ON keeps the stale deadline and trips
    early with a false page. A plug ON is held on (plugs ignore duration_sec),
    so its ceiling is kept under the plug's own id."""
    await insert_plug(plug_id, plug_type, prefix, role="heater")
    await _fire_rule(make_rule(RuleAction(target="plug-heater"), ceiling=3600,
                               name="Heating Trigger"), {}, None)
    armed = _safety_tasks[f"{plug_id}:*"]

    assert (await command_plug(named, {"state": "off"}))["status"] == "sent"
    await REAL_SLEEP(0)

    assert ended(armed)
    assert f"{plug_id}:*" not in _safety_tasks
    assert await watchdog_rows() == []


async def test_note_actuator_off_clears_a_native_channel(frozen_sleep, mock_mqtt):
    await _fire_rule(make_rule(HEATER, ceiling=3600), {}, None)
    armed = _safety_tasks["relay-01:heater"]

    await engine.note_actuator_off("relay-01", "heater")

    await REAL_SLEEP(0)
    assert ended(armed)
    assert await watchdog_rows() == []


async def test_note_actuator_off_keeps_a_ceiling_whose_on_went_out_later(frozen_sleep, mock_mqtt):
    """The manual OFF started before an automation ON finished: that ON may be
    the last command on the wire, so its ceiling must stay armed."""
    off_started = time.time() - 5
    await _fire_rule(make_rule(HEATER, ceiling=3600), {}, None)
    armed = _safety_tasks["relay-01:heater"]

    await engine.note_actuator_off("relay-01", "heater", sent_at=off_started)

    await REAL_SLEEP(0)
    assert _safety_tasks["relay-01:heater"] is armed and not armed.done()
    assert len(await watchdog_rows()) == 1


# ── a database error never costs the heater its ceiling ────────────────────


@pytest.mark.parametrize("failing", ["recording the firing", "persisting the ceiling"])
async def test_a_ceiling_is_armed_even_when_its_bookkeeping_fails(
        frozen_sleep, mock_mqtt, mock_mqtt_raw, monkeypatch, failing):
    """The ON is already on the wire: a heater switched on under a ceiling
    still needs its watchdog."""
    await insert_plug("plug-h1", "tasmota", "tasmota/h1", role="heater")
    if failing == "recording the firing":
        monkeypatch.setattr(engine, "get_db", _db_failing_on("UPDATE automation_firings"))
    else:
        async def _broken(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(engine, "_persist_safety_watchdog", _broken)

    await _fire_rule(make_rule(RuleAction(target="plug-heater"), ceiling=3600), {}, None)

    assert ("tasmota/h1/cmnd/POWER", "ON") in mock_mqtt_raw
    assert not _safety_tasks["plug-h1:*"].done()


async def test_a_lockout_that_cannot_be_stored_is_held_in_memory(
        fast_sleep, mock_mqtt, monkeypatch, quiet_alerts):
    async def _broken(override):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(engine, "set_override", _broken)
    await _fire_rule(make_rule(HEATER, ceiling=1, name="heat"), {}, None)
    await drain("relay-01:heater")

    assert mock_mqtt[-1][1]["state"] == "off"
    assert is_overridden("relay-01", "heater"), "automation stays off it until a restart"
    assert await rows("SELECT * FROM manual_overrides") == []


async def test_a_trip_whose_pending_row_cannot_be_written_still_goes_out_and_is_recorded(
        fast_sleep, mock_mqtt, monkeypatch, quiet_alerts):
    # The trip reserves its row with a NULL rule id; a rule's own firing does not.
    monkeypatch.setattr(engine, "get_db", _db_failing_on("NULL, 'pending'"))
    await _fire_rule(make_rule(HEATER, ceiling=1, name="heat"), {}, None)
    await drain("relay-01:heater")

    assert mock_mqtt[-1] == ("sporeprint/relay-01/cmd/heater",
                             {"state": "off", "reason": "safety_max_on_seconds"})
    assert [f["status"] for f in await firings("safety_max_on_seconds:heat")] == ["sent"]


# ── Dry Weather Humidity Boost ─────────────────────────────────────────────


def test_the_dry_weather_boost_is_gated_and_bounded():
    """It ran the humidifier with no chamber humidity check, no phase gate
    and no ceiling."""
    rule: AutomationRule = next(r for r in BUILTIN_RULES if r.name == "Dry Weather Humidity Boost")
    assert rule.safety_max_on_seconds and rule.safety_max_on_seconds <= 1800
    assert set(rule.applies_to_phases or []) == {"primordia_induction", "fruiting"}

    class _Phase:
        humidity_max = 95.0

    dry_outside = {"outdoor_humidity": 20.0}
    assert _evaluate_condition(rule.condition, {**dry_outside, "humidity": 85.0}, _Phase())
    # The chamber is already at its ceiling: dry air outside is no reason to add more.
    assert not _evaluate_condition(rule.condition, {**dry_outside, "humidity": 96.0}, _Phase())
    # No chamber humidity on this frame: never fire blind.
    assert not _evaluate_condition(rule.condition, dry_outside, _Phase())
