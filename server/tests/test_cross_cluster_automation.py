"""Automation cross-cluster follow-ups (hardware audit, pass 2).

- engine emergency pages carry a per node/parameter/direction ntfy dedup key,
  so a second node's emergency is not swallowed by the first one's title key;
- an OFF never carries a duty value (deployed firmware let pwm win over "off");
- the smart-plug command endpoint tells an unpaired plug (409) from a broker
  that is down (503);
- Tasmota stat/RESULT and tele/STATE JSON reports update the plug's state;
- the chamber coverage verdict resolves placeholders within the chamber.
"""

import json

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
import app.mqtt
import app.notifications.service as notifications
from app.automation.coverage import compute_coverage
from app.automation.engine import evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule, drop_duty_from_off
from app.automation.smart_plugs import get_all_plugs, handle_plug_message
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.config import settings
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import GrowPhase
from app.species.service import get_profile, seed_builtins


@pytest.fixture(autouse=True)
def _reset_pause_state():
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


# ── notify-vision-weather #1: per-node emergency dedup key ─────────────────


class _NtfyRecorder:
    """Stands in for httpx.AsyncClient inside notifications.notify()."""

    posts: list[dict] = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, timeout=None):
        _NtfyRecorder.posts.append(json)

        class _Resp:
            def raise_for_status(self):
                return None

        return _Resp()


@pytest.fixture()
def ntfy(monkeypatch):
    _NtfyRecorder.posts = []
    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr(notifications.httpx, "AsyncClient", _NtfyRecorder)

    async def _forward(event_type, data):
        return None

    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    return _NtfyRecorder.posts


async def test_temperature_emergencies_on_two_nodes_both_reach_ntfy(ntfy, mock_mqtt):
    """Both pages used the title 'Temperature EMERGENCY' as their 15-min dedup
    key, so node B's emergency (same title) was dropped on local ntfy."""
    await seed_builtins()
    await create_session(SessionCreate(
        name="dedup", species_profile_id="cubensis_golden_teacher",
        substrate="CVG", current_phase="substrate_colonization",
    ))
    await evaluate_rules("climate-a", {"temp_f": 120})
    await evaluate_rules("climate-b", {"temp_f": 120})
    titles = [p["title"] for p in ntfy if p["priority"] == 5]
    assert titles.count("Temperature EMERGENCY") == 2, ntfy


async def test_opposite_direction_emergency_is_not_swallowed(ntfy, mock_mqtt):
    await seed_builtins()
    await create_session(SessionCreate(
        name="dedup-dir", species_profile_id="cubensis_golden_teacher",
        substrate="CVG", current_phase="substrate_colonization",
    ))
    await evaluate_rules("climate-a", {"temp_f": 120})
    await evaluate_rules("climate-a", {"temp_f": 30})
    titles = [p["title"] for p in ntfy if p["priority"] == 5]
    assert titles.count("Temperature EMERGENCY") == 2, ntfy


async def test_emergency_dedup_key_names_node_param_and_direction(monkeypatch):
    seen = []

    async def _critical(title, message, tags=None, **kwargs):
        seen.append(kwargs.get("dedup_key"))

    async def _forward(event_type, data):
        return None

    monkeypatch.setattr(engine, "notify_critical", _critical)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    await seed_builtins()
    profile = await get_profile("cubensis_golden_teacher")
    params = profile.phases[GrowPhase.SUBSTRATE_COLONIZATION]
    await engine._check_safety_thresholds("climate-a", params, {"humidity": 5}, None)
    assert seen == ["climate-a:humidity:low:emergency"]


# ── fw-node-safety #2: an OFF never carries a duty value ───────────────────


def test_drop_duty_from_off_strips_pwm_and_level():
    assert drop_duty_from_off({"state": "off", "pwm": 200, "level": 900, "duration_sec": 5}) == {
        "state": "off", "duration_sec": 5,
    }
    assert drop_duty_from_off({"state": "OFF", "pwm": 1}) == {"state": "OFF"}
    on = {"state": "on", "pwm": 200}
    assert drop_duty_from_off(on) == on


async def test_off_rule_with_pwm_publishes_a_bare_off(mock_mqtt):
    """Old node firmware turned {"state":"off","pwm":N} ON at duty N."""
    await create_session(SessionCreate(
        name="off-pwm", species_profile_id="unit-test-species",
        substrate="x", current_phase="fruiting",
    ))
    await create_rule(AutomationRule(
        name="fan off", priority=1,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=0)),
        action=RuleAction(target="relay-a", channel="fae", state="off", pwm=180),
    ))
    await evaluate_rules("climate-1", {"temp_f": 70})
    sent = [p for t, p in mock_mqtt if t == "sporeprint/relay-a/cmd/fae"]
    assert sent == [{"state": "off"}], sent


# ── deps-platform #2: plug endpoint 409 unpaired / 503 broker down ─────────


def _pair(client, dev="h1", role="heater"):
    r = client.post("/api/automation/plugs", json={
        "plug_id": f"plug-{dev}", "name": role, "plug_type": "shelly",
        "mqtt_topic_prefix": f"shellies/{dev}", "device_role": role,
    })
    assert r.status_code == 200, r.text


def test_plug_command_unpaired_is_409(client):
    r = client.post("/api/automation/plugs/plug-nope/command", json={"state": "on"})
    assert r.status_code == 409


def test_plug_command_with_broker_down_is_503(client, monkeypatch):
    _pair(client)
    monkeypatch.setattr(app.mqtt, "_client", None)
    r = client.post("/api/automation/plugs/plug-h1/command", json={"state": "on"})
    assert r.status_code == 503, r.text


def test_plug_command_publish_error_is_503(client, monkeypatch):
    class _Broken:
        async def publish(self, topic, payload):
            raise RuntimeError("broker gone")

    _pair(client)
    monkeypatch.setattr(app.mqtt, "_client", _Broken())
    r = client.post("/api/automation/plugs/plug-h1/command", json={"state": "off"})
    assert r.status_code == 503, r.text


def test_plug_command_paired_is_sent(client, mock_mqtt_raw):
    _pair(client)
    r = client.post("/api/automation/plugs/plug-h1/command", json={"state": "on"})
    assert r.status_code == 200, r.text
    assert mock_mqtt_raw == [("shellies/h1/relay/0/command", "on")]


# ── ingest-telemetry #2: Tasmota RESULT / STATE JSON ───────────────────────


async def _plug_state(plug_id):
    return {p["plug_id"]: p for p in await get_all_plugs()}.get(plug_id, {}).get("last_state")


async def test_tasmota_stat_result_json_updates_state(mock_sio):
    await handle_plug_message(mock_sio, "tasmota/heat1/stat/RESULT", {"POWER": "ON"})
    assert await _plug_state("plug-heat1") == "on"
    await handle_plug_message(mock_sio, "tasmota/heat1/stat/RESULT", {"POWER1": "OFF"})
    assert await _plug_state("plug-heat1") == "off"


async def test_tasmota_tele_state_json_updates_state(mock_sio):
    await handle_plug_message(mock_sio, "tasmota/heat2/tele/STATE",
                              {"Time": "2026-09-27T10:00:00", "Uptime": "0T01:00:00", "POWER": "ON"})
    assert await _plug_state("plug-heat2") == "on"
    mock_sio.emit.assert_any_await("plug_state", {"plug_id": "plug-heat2", "state": "on"})


async def test_tasmota_result_without_power_is_ignored(mock_sio):
    await handle_plug_message(mock_sio, "tasmota/heat3/stat/RESULT", {"Dimmer": 40})
    await handle_plug_message(mock_sio, "tasmota/heat3/stat/RESULT", "not json")
    assert await _plug_state("plug-heat3") is None


async def test_tasmota_plain_stat_power_still_works(mock_sio):
    await handle_plug_message(mock_sio, "tasmota/heat4/stat/POWER", "ON")
    assert await _plug_state("plug-heat4") == "on"


# ── automation-rules minor: coverage resolves placeholders per chamber ─────


async def _node(node_id, node_type, channels=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) VALUES (?, ?, ?, 1)",
            (node_id, node_type, json.dumps(channels) if channels else None),
        )
        await db.commit()


async def test_coverage_counts_only_the_chambers_own_lighting_node():
    """Chamber A has no lighting node; chamber B's light must not make A's
    scene rules read as available."""
    await seed_builtins()
    await _node("light-b", "lighting")
    await create_chamber(ChamberCreate(name="B", node_ids=["light-b"]))
    await create_rule(AutomationRule(
        name="scene", priority=1,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=0)),
        action=RuleAction(target="light-01", scene="fruiting_standard"),
    ))
    profile = await get_profile("blue_oyster")

    unscoped = await compute_coverage(profile)
    scoped = await compute_coverage(profile, chamber_nodes=["climate-a"])

    def _light(phases):
        return {r["available"] for ph in phases for r in ph["requirements"] if r["target"] == "light-01"}

    assert _light(unscoped) == {True}
    assert _light(scoped) == {False}
