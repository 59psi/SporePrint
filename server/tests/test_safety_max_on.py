"""safety_max_on_seconds: the fire-risk ceiling on an actuator automation switched ON.

A rule with a ceiling arms a watchdog when its ON goes out. Unless an OFF
ends it first, the watchdog switches the actuator OFF when the ceiling runs
out, over the actuator's own transport, and records the trip. An actuator
held ON (a plug, a vendor device, a native channel commanded without a
duration) is a real breach: automation is locked out of it for 15 minutes so
the next frame cannot switch it straight back on, and the operator is paged.

Rehydration after a reboot, re-fires, races and failures:
tests/test_safety_watchdog_hardening.py. Holds: tests/test_automation_holds_and_ceilings.py.
"""

import contextlib
import json

import pytest

import app.automation.engine as engine
from app.automation.engine import _fire_rule, is_overridden
from app.automation.models import RuleAction
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    REAL_SLEEP,
    alerts,
    dispatch_calls,
    drain,
    ended,
    engine_state,
    fast_sleep,
    firings,
    frozen_sleep,
    insert_plug,
    make_rule,
    quiet_alerts,
    watchdog_rows,
)

OFF = {"state": "off", "reason": "safety_max_on_seconds"}


def _kasa(on) -> RuleAction:
    return RuleAction(target="vendor:kasa:10.0.0.20", vendor_slug="kasa", vendor_action="set_power",
                      vendor_params={"ip": "10.0.0.20", "on": on})


def _wire(raw: list[tuple[str, str]]) -> list[tuple[str, object]]:
    """Raw plug publishes, a Gen2 JSON-RPC frame read as (method, params)."""
    out = []
    for topic, payload in raw:
        if topic.endswith("/rpc"):
            frame = json.loads(payload)
            payload = (frame["method"], frame["params"])
        out.append((topic, payload))
    return out


async def test_a_held_on_channel_trips_after_its_ceiling_and_is_locked_out(
        fast_sleep, mock_mqtt, alerts):
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="heater"), ceiling=1800,
                               name="heat"), {"temp_f": 55}, None)
    await drain("relay-01:heater")

    assert fast_sleep == [1800], "the watchdog waits exactly the rule's ceiling"
    assert mock_mqtt == [("sporeprint/relay-01/cmd/heater", {"state": "on"}),
                         ("sporeprint/relay-01/cmd/heater", OFF)]
    assert is_overridden("relay-01", "heater"), "the next frame must not switch it back on"
    assert [t for t, _ in alerts["warning"]] == ["Safety cutoff: relay-01:heater"]
    assert await firings("safety_max_on_seconds:heat") == [
        {"rule_name": "safety_max_on_seconds:heat", "status": "sent", "error": None}]


async def test_a_pulse_trip_is_a_benign_redundant_off(fast_sleep, mock_mqtt, alerts):
    """A native ON with a duration is a firmware-timed pulse that has ended by
    itself: the trip's OFF is redundant, so no lockout and no page."""
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="aux", pwm=255,
                                          duration_sec=8), ceiling=30, name="Mist"), {}, None)
    await drain("relay-01:aux")

    assert mock_mqtt[-1] == ("sporeprint/relay-01/cmd/aux", OFF)
    assert not is_overridden("relay-01", "aux")
    assert alerts["warning"] == [] and alerts["critical"] == []


# Each actuator kind: (its paired plug row, the rule's action, the ceiling's
# key, what reaches the native nodes, the plug's topics, the vendor dispatcher).
_TRANSPORTS = {
    "native channel": (
        None, RuleAction(target="relay-01", channel="heater"), "relay-01:heater",
        [("sporeprint/relay-01/cmd/heater", {"state": "on"}),
         ("sporeprint/relay-01/cmd/heater", OFF)], [], []),
    # A scene rule's OFF is the light's all-off scene on cmd/scene: on
    # cmd/config (which reads no on/off) the light stayed on while the trip
    # read as sent.
    "native scene": (
        None, RuleAction(target="light-01", scene="fruiting_standard"), "light-01:*",
        [("sporeprint/light-01/cmd/scene", {"state": "on", "scene": "fruiting_standard"}),
         ("sporeprint/light-01/cmd/scene", {**OFF, "scene": "colonization_dark"})], [], []),
    # A plug's OFF goes out on its own topic tree: sent to sporeprint/plug-*
    # it reached nothing and the heater stayed on.
    "tasmota plug": (
        ("plug-a1b2c3", "tasmota", "tasmota/a1b2c3"), RuleAction(target="plug-heater"),
        "plug-a1b2c3:*", [],
        [("tasmota/a1b2c3/cmnd/POWER", "ON"), ("tasmota/a1b2c3/cmnd/POWER", "OFF")], []),
    "shelly plug": (
        ("plug-9f7e", "shelly", "shellies/9f7e"), RuleAction(target="plug-heater"),
        "plug-9f7e:*", [],
        [("shellies/9f7e/relay/0/command", "on"), ("shellies/9f7e/relay/0/command", "off")], []),
    "shelly gen2 plug": (
        ("plug-plugsg3-b1", "shelly_gen2", "shellies/plugsg3-b1"), RuleAction(target="plug-heater"),
        "plug-plugsg3-b1:*", [],
        [("shellies/plugsg3-b1/rpc", ("Switch.Set", {"id": 0, "on": True})),
         ("shellies/plugsg3-b1/rpc", ("Switch.Set", {"id": 0, "on": False}))], []),
    # A vendor device's OFF goes through the integrations dispatcher: a
    # publish to sporeprint/vendor:*/cmd/config reached no subscriber.
    "kasa plug": (
        None, _kasa(True), "vendor:kasa:10.0.0.20:*", [], [],
        [("kasa", "set_power", {"ip": "10.0.0.20", "on": True}),
         ("kasa", "set_power", {"ip": "10.0.0.20", "on": False})]),
}


@pytest.mark.parametrize("kind", list(_TRANSPORTS))
async def test_the_ceiling_switches_off_every_kind_of_actuator(
        kind, fast_sleep, mock_mqtt, mock_mqtt_raw, dispatch_calls, quiet_alerts):
    plug, action, key, native, plugs, vendor = _TRANSPORTS[kind]
    if plug:
        await insert_plug(*plug, role="heater")
    await _fire_rule(make_rule(action, ceiling=1, name="heat"), {"temp_f": 50}, None)
    await drain(key)

    assert mock_mqtt == native
    assert _wire(mock_mqtt_raw) == plugs
    assert dispatch_calls == vendor
    assert await watchdog_rows() == []
    assert [f["status"] for f in await firings("safety_max_on_seconds:heat")] == ["sent"]


# (the ON's action, the OFF's action, the ceiling's key)
_ON_THEN_OFF = {
    "native": (RuleAction(target="relay-01", channel="heater"),
               RuleAction(target="relay-01", channel="heater", state="off"), "relay-01:heater"),
    # The model reads states in any case and spacing; the engine used to read
    # only "on"/"off" literally.
    "plug, any case": (RuleAction(target="plug-heater", state="ON"),
                       RuleAction(target="plug-heater", state=" OFF"), "plug-a1b2c3:*"),
    # A plug is one actuator whichever name a rule gives it.
    "plug by role, then by id": (RuleAction(target="plug-heater", state="on"),
                                 RuleAction(target="plug-a1b2c3", state="off"), "plug-a1b2c3:*"),
    # A vendor rule's state is always "on"; set_power(on=False) is its OFF,
    # and the dispatcher reads "false" / "off" / "0" as False too.
    "kasa": (_kasa(True), _kasa(False), "vendor:kasa:10.0.0.20:*"),
    "kasa, text false": (_kasa(True), _kasa("false"), "vendor:kasa:10.0.0.20:*"),
}


@pytest.mark.parametrize("case", list(_ON_THEN_OFF))
async def test_an_off_ends_the_ceiling_its_on_armed(
        case, frozen_sleep, mock_mqtt, mock_mqtt_raw, dispatch_calls):
    on, off, key = _ON_THEN_OFF[case]
    await insert_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    await _fire_rule(make_rule(on, ceiling=3600, name="on"), {}, None)
    armed = engine._safety_tasks[key]
    assert len(await watchdog_rows()) == 1

    await _fire_rule(make_rule(off, ceiling=3600, name="off", rule_id=2), {}, None)
    await REAL_SLEEP(0)

    assert ended(armed)
    assert key not in engine._safety_tasks, "an OFF arms nothing"
    assert await watchdog_rows() == []


@pytest.mark.parametrize("failure", ["broker down", "plug not paired"])
async def test_an_on_that_never_went_out_arms_no_ceiling(mock_mqtt, mock_mqtt_raw, failure):
    """An OFF with no ON before it would be a phantom trip."""
    if failure == "broker down":
        mock_mqtt.mock.return_value = False
        action, key = RuleAction(target="relay-01", channel="heater"), "relay-01:heater"
    else:
        action, key = RuleAction(target="plug-heater"), "plug-heater:*"
    await _fire_rule(make_rule(action, ceiling=1800), {"temp_f": 55}, None)
    assert key not in engine._safety_tasks
    assert await watchdog_rows() == []
    assert [f["status"] for f in await firings()] == ["failed"]


async def test_an_off_with_no_ceiling_touches_no_watchdog_row(mock_mqtt, monkeypatch):
    """Most OFFs have no ceiling; each used to cost a connection, a DELETE and
    a commit on the telemetry path."""
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
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="heater", state="off")),
                     {}, None)
    assert mock_mqtt == [("sporeprint/relay-01/cmd/heater", {"state": "off"})]
    assert not [s for s in statements if "DELETE FROM safety_watchdogs" in s]
