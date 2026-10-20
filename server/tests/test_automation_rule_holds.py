"""GET /api/automation/rules says which holds keep the engine off each rule.

A hold is stored under the name it was placed on. The chamber page pins the
chamber's real node (node-xxxx:fae), a plug is held by its id or its role,
and a scene rule is held by a hold on any channel of its light, while a
seeded rule names the relay-01 / light-01 placeholder. The engine resolves
the rule's target for each chamber and honours a hold under any of those
names; each rule's ``held_by`` lists exactly the holds it honours, so the
dashboard no longer shows a held rule as active.
"""

import json
import time

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import set_override
from app.automation.models import (
    AutomationRule,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.router import list_rules
from app.automation.service import create_rule
from app.automation.smart_plugs import register_plug
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.cloud import integrations_proxy
from app.config import settings
from app.db import get_db


async def _node(node_id: str, node_type: str, seen_ago: float) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]), time.time() - seen_ago),
        )
        await db.commit()


async def _rule(name: str, action: RuleAction) -> int:
    return await create_rule(AutomationRule(
        name=name,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=900)),
        action=action,
    ))


async def _hold(target: str, channel: str | None, reason: str, in_sec: float = 600) -> None:
    await set_override(ManualOverride(target=target, channel=channel, reason=reason,
                                      expires_at=time.time() + in_sec))


async def _held_by() -> dict[int, list[tuple[str, str | None, str]]]:
    return {r["id"]: [(h["target"], h["channel"], h["reason"]) for h in r["held_by"]]
            for r in await list_rules()}


async def _engine_holds(action: RuleAction, chamber_nodes: list[str] | None) -> bool:
    return engine._target_held(action, await engine._resolve_target(action, chamber_nodes))


FAE = RuleAction(target="relay-01", channel="fae", state="on")
AUX = RuleAction(target="relay-01", channel="aux", state="on")


async def test_a_hold_on_the_node_a_placeholder_resolves_to_holds_the_rule():
    # Two chambers, each with its own relay; chamber A also lists an older
    # relay the placeholder never resolves to.
    await _node("node-a1", "relay", seen_ago=5)
    await _node("node-a2", "relay", seen_ago=3600)
    await _node("node-b1", "relay", seen_ago=10)
    a = ["node-a1", "node-a2"]
    b = ["node-b1"]
    await create_chamber(ChamberCreate(name="A", node_ids=a))
    await create_chamber(ChamberCreate(name="B", node_ids=b))
    fae = await _rule("FAE", FAE)
    aux = await _rule("Mist", AUX)

    await _hold("node-a1", "fae", "pi-ui override (fae on)")
    held = await _held_by()
    assert held[fae] == [("node-a1", "fae", "pi-ui override (fae on)")]
    assert held[aux] == []
    # Exactly what the engine does: chamber A's FAE rule is held, B's is not.
    assert await _engine_holds(FAE, a)
    assert not await _engine_holds(FAE, b)

    # A hold on a relay the engine never drives for this rule holds nothing.
    await engine.clear_override("node-a1", "fae")
    await _hold("node-a2", "fae", "bench test")
    assert (await _held_by())[fae] == []
    assert not await _engine_holds(FAE, a)

    # Chamber B's own relay, and the rule's own placeholder name, both hold it.
    await _hold("node-b1", "fae", "B pinned")
    await _hold("relay-01", None, "rule suspended via cloud")
    assert sorted((await _held_by())[fae]) == [
        ("node-b1", "fae", "B pinned"),
        ("relay-01", None, "rule suspended via cloud"),
    ]
    assert (await _held_by())[aux] == [("relay-01", None, "rule suspended via cloud")]


async def test_a_node_in_no_chamber_is_resolved_as_the_engine_resolves_it():
    await _node("node-c1", "relay", seen_ago=5)
    fae = await _rule("FAE", FAE)
    await _hold("node-c1", None, "whole node held")
    assert (await _held_by())[fae] == [("node-c1", None, "whole node held")]
    assert await _engine_holds(FAE, None)


async def test_a_plug_rule_is_held_by_a_hold_on_the_plug_id():
    await register_plug("plug-a1b2c3", "Heater", "tasmota", "tasmota/heater", device_role="heater")
    heat = await _rule("Heat", RuleAction(target="plug-heater", state="on"))
    await _hold("plug-a1b2c3", None, "safety lockout")
    assert (await _held_by())[heat] == [("plug-a1b2c3", None, "safety lockout")]
    assert await _engine_holds(RuleAction(target="plug-heater", state="on"), None)


async def test_a_hold_on_the_plug_nodes_in_no_chamber_drive_holds_the_rule():
    """Nodes in no chamber drive the plug of the role no chamber lists, not
    chamber A's (paired first): a hold on it holds the rule there, and for
    chamber A only A's own plug does."""
    await register_plug("plug-ha", "Heater A", "tasmota", "tasmota/ha", device_role="heater")
    await register_plug("plug-hc", "Heater", "tasmota", "tasmota/hc", device_role="heater")
    a = ["node-a1", "plug-ha"]
    await create_chamber(ChamberCreate(name="A", node_ids=a))
    action = RuleAction(target="plug-heater", state="on")
    heat = await _rule("Heat", action)
    await _hold("plug-hc", None, "closet heater pinned")
    assert (await _held_by())[heat] == [("plug-hc", None, "closet heater pinned")]
    assert await _engine_holds(action, None)
    assert not await _engine_holds(action, a)


async def test_a_scene_rule_is_held_by_a_hold_on_any_channel_of_its_light():
    await _node("node-l1", "lighting", seen_ago=5)
    scene = RuleAction(target="light-01", scene="fruiting_standard", state="on")
    lights = await _rule("Lights", scene)
    red = await _rule("Red", RuleAction(target="light-01", channel="red", state="on"))
    await _hold("node-l1", "white", "white pinned")
    held = await _held_by()
    assert held[lights] == [("node-l1", "white", "white pinned")]
    assert held[red] == []


async def test_nothing_held_and_expired_holds_list_nothing():
    await _node("node-a1", "relay", seen_ago=5)
    fae = await _rule("FAE", FAE)
    assert (await _held_by())[fae] == []
    await _hold("node-a1", "fae", "lapsed", in_sec=-1)
    assert (await _held_by())[fae] == []


def test_every_rule_in_the_list_carries_its_holds(client):
    rule = client.post("/api/automation/rules", json={
        "name": "Vent", "condition": {"type": "schedule", "schedule": {"interval_min": 20}},
        "action": {"target": "node-x1", "channel": "fae", "state": "on"},
    })
    assert rule.status_code == 200, rule.text
    hold = client.post("/api/automation/overrides", json={
        "target": "node-x1", "channel": "fae", "reason": "maintenance", "duration_sec": 300,
    })
    assert hold.status_code == 200
    rules = client.get("/api/automation/rules").json()
    assert all(isinstance(r["held_by"], list) for r in rules)
    (vent,) = [r for r in rules if r["id"] == rule.json()["id"]]
    assert [(h["target"], h["channel"], h["reason"], h["locked"]) for h in vent["held_by"]] == [
        ("node-x1", "fae", "maintenance", True),
    ]
    assert vent["held_by"][0]["expires_at"] == pytest.approx(time.time() + 300, abs=30)


class _FakeSio:
    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))


async def test_the_cloud_rule_list_carries_the_same_holds(monkeypatch):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    cloud_service._seen_command_ids.clear()
    await _node("node-a1", "relay", seen_ago=5)
    fae = await _rule("FAE", FAE)
    await _hold("node-a1", "fae", "pinned")
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, {"id": "list-1", "action": "automation_list"})
    (_, payload), = sio.emits
    assert payload["success"] is True
    (row,) = [r for r in payload["body"] if r["id"] == fae]
    assert [(h["target"], h["channel"]) for h in row["held_by"]] == [("node-a1", "fae")]
    cloud_service._seen_command_ids.clear()
