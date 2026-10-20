"""Rule CRUD has one implementation (automation/service.py).

The LAN routes (/api/automation/rules, /firings) and the cloud relay's
automation_* requests (cloud/integrations_proxy.py) go through the same
functions, so:

- a rule the LAN route refuses with 422 is refused over the relay too,
  instead of being stored, looking armed and firing into a topic no node reads;
- every write reaches the engine's rule cache at once, so a rule the operator
  just switched off or deleted cannot fire from a stale cache;
- /firings filters and limits the same way everywhere.
"""

import json
import time

from app.automation import engine
from app.automation.engine import evaluate_rules
from app.automation.models import AutomationRule
from app.automation.service import (
    create_rule,
    delete_rule,
    rules_generation,
    toggle_rule,
    update_validated_rule,
)
from app.cloud import integrations_proxy
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session

RELAY = "node-relay-7a3f1c"
RELAY_CHANNELS = ["aux", "circulation", "exhaust", "fae"]


class _Sio:
    def __init__(self):
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.emits.append((event, data))


async def _register_relay(channels=RELAY_CHANNELS):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) VALUES (?, ?, ?, ?)",
            (RELAY, "relay", json.dumps(channels), time.time()),
        )
        await db.commit()


def _rule_body(channel="fae", target=RELAY, name="Vent") -> dict:
    return {
        "name": name, "priority": 5, "cooldown_seconds": 0,
        "condition": {"type": "threshold",
                      "threshold": {"sensor": "temp_f", "operator": "gt", "value": 0}},
        "action": {"target": target, "channel": channel, "state": "on"},
    }


async def _rule_names() -> list[str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT name FROM automation_rules")
        return [r["name"] for r in await cursor.fetchall()]


async def _relay(monkeypatch, action: str, payload: dict) -> dict:
    """One automation_* request through the real relay handler."""
    monkeypatch.setattr(integrations_proxy, "_require_signed_setting", lambda: False)
    sio = _Sio()
    await integrations_proxy.handle_request(sio, {"id": "req-1", "action": action, "payload": payload})
    assert sio.emits and sio.emits[0][0] == "integrations_response"
    return sio.emits[0][1]


# ── The relay checks a rule the way the LAN route does ─────────────────────


async def test_relay_create_refuses_a_channel_the_node_lacks(client, monkeypatch):
    await _register_relay()
    lan = client.post("/api/automation/rules", json=_rule_body("fan"))
    assert lan.status_code == 422
    reply = await _relay(monkeypatch, "automation_create", {"rule": _rule_body("fan")})
    assert (reply["success"], reply["status"]) == (False, 422)
    assert "no channel 'fan'" in reply["error"]
    assert "Vent" not in await _rule_names()


async def test_relay_create_refuses_a_placeholder_with_no_node(monkeypatch):
    reply = await _relay(monkeypatch, "automation_create",
                         {"rule": _rule_body("fae", target="relay-01")})
    assert (reply["success"], reply["status"]) == (False, 422)
    assert "No 'relay' node" in reply["error"]
    assert "Vent" not in await _rule_names()


async def test_relay_update_refuses_and_keeps_the_stored_rule(monkeypatch):
    await _register_relay()
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    reply = await _relay(monkeypatch, "automation_update",
                         {"rule_id": rule_id, "rule": _rule_body("mister")})
    assert (reply["success"], reply["status"]) == (False, 422)
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT rule_data FROM automation_rules WHERE id = ?", (rule_id,))).fetchone()
    assert json.loads(row["rule_data"])["action"]["channel"] == "fae"


async def test_relay_create_accepts_a_rule_the_lan_route_accepts(monkeypatch):
    await _register_relay()
    reply = await _relay(monkeypatch, "automation_create", {"rule": _rule_body("aux")})
    assert reply["success"] is True and reply["body"]["action"]["channel"] == "aux"
    assert "Vent" in await _rule_names()


# ── Every write reaches the engine's rule cache at once ────────────────────


async def _fires(mock_mqtt) -> bool:
    mock_mqtt.clear()
    await evaluate_rules("climate-1", {"temp_f": 70})
    return any(t == f"sporeprint/{RELAY}/cmd/fae" for t, _ in mock_mqtt)


async def _managed_grow():
    # A profile the engine does not know still runs every rule (no setpoints).
    await create_session(SessionCreate(name="crud", species_profile_id="unit-test-species",
                                       substrate="x", current_phase="fruiting"))


async def test_a_rule_switched_off_stops_firing_at_once(mock_mqtt):
    await _managed_grow()
    await _register_relay()
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    assert await _fires(mock_mqtt)          # warms the engine's 5 s rule cache
    assert await toggle_rule(rule_id) is False
    assert not await _fires(mock_mqtt)      # within the cache's lifetime


async def test_a_deleted_rule_stops_firing_at_once(mock_mqtt):
    await _managed_grow()
    await _register_relay()
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    assert await _fires(mock_mqtt)
    assert await delete_rule(rule_id)
    assert not await _fires(mock_mqtt)
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS n FROM automation_firings WHERE rule_id = ?",
                                  (rule_id,))
        assert (await cursor.fetchone())["n"] == 1  # only the firing before the delete


async def test_an_edit_takes_effect_at_once(mock_mqtt):
    await _managed_grow()
    await _register_relay()
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    assert await _fires(mock_mqtt)
    edited = _rule_body("fae")
    edited["condition"]["threshold"]["value"] = 100  # temp_f 70 no longer matches
    assert await update_validated_rule(rule_id, AutomationRule.model_validate(edited))
    assert not await _fires(mock_mqtt)


async def test_the_route_toggle_moves_the_generation(client):
    rule_id = client.get("/api/automation/rules").json()[0]["id"]
    before = rules_generation()
    r = client.patch(f"/api/automation/rules/{rule_id}/toggle")
    assert r.status_code == 200 and r.json()["id"] == rule_id
    assert rules_generation() > before
    assert engine._cache_generation != rules_generation()  # the next load reads the table


# ── /firings ───────────────────────────────────────────────────────────────


async def _firing_rows(n: int, rule_id: int = 7) -> None:
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO automation_firings (rule_id, rule_name, timestamp, status) "
            "VALUES (?, 'r', ?, 'sent')",
            [(rule_id, 1_800_000_000.0 + i) for i in range(n)],
        )
        await db.commit()


async def test_firings_limit_is_clamped(client):
    await _firing_rows(1005)
    assert len(client.get("/api/automation/firings?limit=-1").json()) == 1
    assert len(client.get("/api/automation/firings?limit=5000").json()) == 1000
    newest = client.get("/api/automation/firings?limit=2").json()
    assert [f["timestamp"] for f in newest] == [1_800_000_000.0 + 1004, 1_800_000_000.0 + 1003]


async def test_firings_filter_by_rule_id_zero(client):
    await _firing_rows(3, rule_id=7)
    assert client.get("/api/automation/firings?rule_id=0").json() == []
    assert len(client.get("/api/automation/firings?rule_id=7").json()) == 3
