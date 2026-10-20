"""The firing record, and a frame whose rules keep running whatever breaks.

Every rule firing and every safety trip is written to automation_firings as
'pending' before its command goes out, then updated to 'sent' or 'failed'
from what the publish really did (AGENTS.md). Before v3.3.0 the row was
written after the publish and claimed success when MQTT was disconnected:
the audit log lied. Only a command that went out reaches the grow's
timeline.

One stored rule that no longer validates, a rule whose evaluation raises, or
a cloud forward that fails never stops the other rules on the frame: the CO2
Hard Ceiling among them.
"""

import asyncio
import json

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import _fire_rule, evaluate_rules
from app.automation.models import RuleAction
from app.automation.service import create_rule, seed_builtin_rules
from app.db import get_db
from app.integrations import _actions as vendor_actions
from app.species.service import seed_builtins
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    RELAY_CHANNELS,
    alerts,
    engine_state,
    fast_sleep,
    firings,
    frozen_sleep,
    make_rule,
    quiet_alerts,
    register_node,
    rows,
    start_grow,
    threshold,
)

# The rule names the relay-01 placeholder; the real relay is MAC-derived.
RELAY_NODE = "node-relay-7a3f1c"


def _fan(name: str = "fan", rule_id: int = 1):
    return make_rule(RuleAction(target="relay-01", channel="fae", state="on", pwm=255),
                     condition=threshold("co2_ppm", "gt", 1000), name=name, rule_id=rule_id)


@pytest.mark.parametrize("published,status", [(True, "sent"), (False, "failed")])
async def test_a_firing_is_recorded_as_what_the_publish_did(mock_mqtt, published, status):
    """A broker that is down (publish returns False) must not read as a fire."""
    session = await start_grow("blue_oyster", "fruiting")
    await register_node(RELAY_NODE, "relay", RELAY_CHANNELS)
    mock_mqtt.mock.return_value = published

    await _fire_rule(_fan(), {"co2_ppm": 1500}, session)

    assert mock_mqtt[-1][0] == f"sporeprint/{RELAY_NODE}/cmd/fae"
    (firing,) = await firings("fan")
    assert firing["status"] == status
    assert (firing["error"] is None) is published
    if not published:
        assert "mqtt_publish" in firing["error"]


async def test_a_trip_is_recorded_pending_before_its_off_goes_out(fast_sleep, mock_mqtt,
                                                                   monkeypatch, quiet_alerts):
    """The trip's row used to be written only after the OFF and up to ~10 min
    of retries: a restart in between left no record of the trip."""
    sending, release = asyncio.Event(), asyncio.Event()
    real_send = engine._send_safety_off

    async def _blocked(target, channel, vendor_off):
        sending.set()
        await release.wait()
        return await real_send(target, channel, vendor_off)

    monkeypatch.setattr(engine, "_send_safety_off", _blocked)
    await _fire_rule(make_rule(RuleAction(target="relay-01", channel="heater"), ceiling=1,
                               name="heat"), {}, None)
    trip = engine._safety_tasks["relay-01:heater"]
    await asyncio.wait_for(sending.wait(), 2)  # the OFF is on its way out, not out yet
    assert [f["status"] for f in await firings("safety_max_on_seconds:heat")] == ["pending"]
    release.set()
    await asyncio.wait_for(asyncio.shield(trip), 2)
    assert [f["status"] for f in await firings("safety_max_on_seconds:heat")] == ["sent"]


async def _timeline(session_id: int) -> list[str]:
    return [r["description"] for r in await rows(
        "SELECT description FROM session_events WHERE session_id = ? AND type = 'automation'",
        session_id)]


async def test_only_a_command_that_went_out_reaches_the_grow_timeline(mock_mqtt, mock_mqtt_raw):
    """session_events is append-only: a "Rule fired" row written before a
    publish that then failed stayed for good (an unpaired plug or a broker
    outage added a false actuation every cooldown)."""
    session = await start_grow("blue_oyster", "fruiting")
    # No humidifier paired: the command reaches nothing.
    await _fire_rule(make_rule(RuleAction(target="plug-humidifier", state="on"), name="boost"),
                     {"humidity": 70}, session)
    # The broker is down.
    mock_mqtt.mock.return_value = False
    await _fire_rule(_fan(rule_id=2), {"co2_ppm": 1500}, session)
    assert await _timeline(session["id"]) == []
    assert [f["status"] for f in await firings()] == ["failed", "failed"]

    mock_mqtt.mock.return_value = True
    await _fire_rule(_fan(rule_id=2), {"co2_ppm": 1500}, session)
    assert await _timeline(session["id"]) == ["Rule 'fan' fired: relay-01/fae → on"]


async def test_a_vendor_write_that_fails_is_recorded_failed_and_arms_no_ceiling(
        frozen_sleep, mock_mqtt, monkeypatch):
    async def _unreachable(slug, action, params):
        raise RuntimeError("plug unreachable")

    monkeypatch.setattr(vendor_actions, "dispatch", _unreachable)
    heater = RuleAction(target="vendor:kasa:10.0.0.20", vendor_slug="kasa",
                        vendor_action="set_power", vendor_params={"ip": "10.0.0.20", "on": True})
    await _fire_rule(make_rule(heater, ceiling=3600, name="kasa heat"), {}, None)

    assert await firings("kasa heat") == [
        {"rule_name": "kasa heat", "status": "failed", "error": "plug unreachable"}]
    assert engine._safety_tasks == {}


# ── one broken rule never stops another ────────────────────────────────────


def _exhaust_states(mock_mqtt) -> list[str]:
    return [p["state"] for t, p in mock_mqtt if t.endswith("/cmd/exhaust")]


async def test_an_invalid_stored_rule_does_not_stop_the_co2_hard_ceiling(mock_mqtt, quiet_alerts):
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
    assert _exhaust_states(mock_mqtt) == ["on"]


async def test_a_rule_that_raises_does_not_stop_the_co2_hard_ceiling(mock_mqtt, monkeypatch,
                                                                     quiet_alerts):
    await seed_builtin_rules()
    await create_rule(make_rule(RuleAction(target="relay-broken", channel="fae"),
                                condition=threshold("co2_ppm", "gt", 1), name="first",
                                rule_id=None, priority=50))
    real_resolve = engine._resolve_target

    async def _resolve(action, chamber_nodes, **kw):
        if action.target == "relay-broken":
            raise RuntimeError("lookup failed")
        return await real_resolve(action, chamber_nodes, **kw)

    monkeypatch.setattr(engine, "_resolve_target", _resolve)
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert _exhaust_states(mock_mqtt) == ["on"]


async def test_a_cloud_forward_that_fails_never_stops_paging_or_actuation(mock_mqtt, alerts,
                                                                          monkeypatch):
    """The stage alerts run before the rules: an exception escaping the cloud
    forward would have ended the frame before a single rule ran."""
    async def _offline(event_type, data):
        raise ConnectionError("relay unreachable")

    monkeypatch.setattr(cloud_service, "forward_event", _offline)
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "substrate_colonization")  # 75-80 °F
    await create_rule(make_rule(RuleAction(target="relay-01", channel="heater", state="off"),
                                condition=threshold("temp_f", "gt", 90), name="cut heat",
                                rule_id=None))
    await evaluate_rules("climate-1", {"temp_f": 120})

    assert [t for t, _ in alerts["critical"]] == ["Temperature EMERGENCY on climate-1"]
    assert ("sporeprint/relay-01/cmd/heater", {"state": "off"}) in mock_mqtt
