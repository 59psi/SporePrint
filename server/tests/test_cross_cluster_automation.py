"""Automation follow-ups from the hardware audit's second pass.

- An emergency page on one node, parameter or direction never silences
  another: each is its own ntfy dedup key (a page keyed by its title alone
  swallowed a second node's emergency for 15 minutes).
- An OFF never carries a duty value: deployed firmware let pwm win over "off".
- The smart-plug command endpoint tells an unpaired plug (409) from a broker
  that did not take the command (503).
"""

import pytest

import app.cloud.service as cloud_service
import app.mqtt
import app.notifications.service as notifications
from app.automation.engine import evaluate_rules
from app.automation.models import RuleAction
from app.automation.service import create_rule, drop_duty_from_off
from app.config import settings
from app.species.service import seed_builtins
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    NtfyRecorder,
    engine_state,
    make_rule,
    start_grow,
    threshold,
)


@pytest.fixture()
def ntfy(monkeypatch):
    """The real notifier, its POSTs recorded."""
    NtfyRecorder.posts = []
    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr(notifications.httpx, "AsyncClient", NtfyRecorder)

    async def _forward(event_type, data):
        return None

    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    return NtfyRecorder.posts


@pytest.mark.parametrize("frames,pages", [
    # Two nodes: the same title used to be the dedup key.
    ([("climate-a", {"temp_f": 120}), ("climate-b", {"temp_f": 120})],
     ["Temperature EMERGENCY on climate-a", "Temperature EMERGENCY on climate-b"]),
    # One node, the opposite excursion inside the 15-minute window.
    ([("climate-a", {"temp_f": 120}), ("climate-a", {"temp_f": 30})],
     ["Temperature EMERGENCY on climate-a"] * 2),
    # One node, another parameter in the same direction.
    ([("climate-a", {"temp_f": 120}), ("climate-a", {"humidity": 99})],
     ["Humidity EMERGENCY on climate-a", "Temperature EMERGENCY on climate-a"]),
    # A CO2 level dangerous to people, on two nodes: one shared key silenced
    # every other node's CO2 page.
    ([("node-a", {"co2_ppm": 45000}), ("node-b", {"co2_ppm": 45000})],
     ["CO2 CRITICAL on node-a: 45000 ppm", "CO2 CRITICAL on node-b: 45000 ppm"]),
])
async def test_an_emergency_never_silences_another_nodes_parameters_or_directions(
        ntfy, mock_mqtt, frames, pages):
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "substrate_colonization")  # 75-80 °F, RH 70-80
    for node, readings in frames:
        await evaluate_rules(node, readings)
    assert sorted(p["title"] for p in ntfy if p["priority"] == 5) == pages


# ── an OFF never carries a duty value ──────────────────────────────────────


def test_drop_duty_from_off_strips_pwm_and_level():
    assert drop_duty_from_off({"state": "off", "pwm": 200, "level": 900, "duration_sec": 5}) == {
        "state": "off", "duration_sec": 5,
    }
    assert drop_duty_from_off({"state": "OFF", "pwm": 1}) == {"state": "OFF"}
    on = {"state": "on", "pwm": 200}
    assert drop_duty_from_off(on) == on


async def test_an_off_rule_with_a_pwm_publishes_a_bare_off(mock_mqtt):
    """Old node firmware turned {"state": "off", "pwm": N} ON at duty N."""
    await start_grow("unit-test-species", "fruiting")
    await create_rule(make_rule(RuleAction(target="relay-a", channel="fae", state="off", pwm=180),
                                condition=threshold("temp_f", "gt", 0), name="fan off",
                                rule_id=None, priority=1))
    await evaluate_rules("climate-1", {"temp_f": 70})
    assert [p for t, p in mock_mqtt if t == "sporeprint/relay-a/cmd/fae"] == [{"state": "off"}]


# ── the plug endpoint: 409 unpaired, 503 not taken ─────────────────────────


def _pair(client, dev="h1", role="heater"):
    r = client.post("/api/automation/plugs", json={
        "plug_id": f"plug-{dev}", "name": role, "plug_type": "shelly",
        "mqtt_topic_prefix": f"shellies/{dev}", "device_role": role,
    })
    assert r.status_code == 200, r.text


def test_plug_command_unpaired_is_409(client, mock_mqtt_raw):
    r = client.post("/api/automation/plugs/plug-nope/command", json={"state": "on"})
    assert r.status_code == 409
    assert mock_mqtt_raw == []


class _BrokenClient:
    async def publish(self, topic, payload):
        raise RuntimeError("broker gone")


@pytest.mark.parametrize("client_now", [None, _BrokenClient()], ids=["not connected", "raises"])
def test_a_plug_command_the_broker_did_not_take_is_503(client, monkeypatch, client_now):
    _pair(client)
    monkeypatch.setattr(app.mqtt, "_client", client_now)
    r = client.post("/api/automation/plugs/plug-h1/command", json={"state": "off"})
    assert r.status_code == 503, r.text


def test_plug_command_paired_is_sent(client, mock_mqtt_raw):
    _pair(client)
    r = client.post("/api/automation/plugs/plug-h1/command", json={"state": "on"})
    assert r.status_code == 200, r.text
    assert mock_mqtt_raw == [("shellies/h1/relay/0/command", "on")]
