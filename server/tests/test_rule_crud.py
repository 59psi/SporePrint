"""Rule CRUD has one implementation (automation/service.py).

The LAN routes (/api/automation/rules, /firings) and the cloud relay's
automation_* requests (cloud/integrations_proxy.py) go through the same
functions, so:

- a rule the LAN route refuses with 422 is refused over the relay too,
  instead of being stored, looking armed and firing into a topic no node reads;
- every write reaches the engine's rule cache at once, so a rule the operator
  just switched off or deleted cannot fire from a stale cache;
- /firings filters and limits the same way everywhere.

Which node channels a rule may name: tests/test_automation_channel_validation.py.
"""

import json

import pytest

from app.automation.engine import evaluate_rules, is_overridden
from app.automation.models import AutomationRule
from app.automation.service import (
    create_rule,
    delete_rule,
    deserialize_rule_row,
    serialize_rule_data,
    toggle_rule,
    update_validated_rule,
)
from app.automation.templates import BUILTIN_RULES
from app.cloud import integrations_proxy
from app.db import get_db
from tests._pi_a_engine import FakeSio, engine_state, register_node, rows, start_grow  # noqa: F401

RELAY = "node-relay-7a3f1c"
RELAY_CHANNELS = ["aux", "circulation", "exhaust", "fae"]


def _rule_body(channel="fae", target=RELAY, name="Vent") -> dict:
    return {
        "name": name, "priority": 5, "cooldown_seconds": 0,
        "condition": {"type": "threshold",
                      "threshold": {"sensor": "temp_f", "operator": "gt", "value": 0}},
        "action": {"target": target, "channel": channel, "state": "on"},
    }


async def _rule_names() -> list[str]:
    return [r["name"] for r in await rows("SELECT name FROM automation_rules")]


async def _write(request, monkeypatch, transport: str, body: dict,
                 rule_id: int | None = None) -> tuple[int, str]:
    """Create (or, with rule_id, update) a rule over the LAN route or the
    cloud relay; (status, error text or "")."""
    if transport == "lan":
        client = request.getfixturevalue("client")
        r = (client.put(f"/api/automation/rules/{rule_id}", json=body) if rule_id
             else client.post("/api/automation/rules", json=body))
        return r.status_code, "" if r.status_code == 200 else r.json()["detail"]
    monkeypatch.setattr(integrations_proxy, "_require_signed_setting", lambda: False)
    sio = FakeSio()
    action, payload = (("automation_update", {"rule_id": rule_id, "rule": body}) if rule_id
                       else ("automation_create", {"rule": body}))
    await integrations_proxy.handle_request(sio, {"id": "req-1", "action": action, "payload": payload})
    ((event, reply),) = sio.events
    assert event == "integrations_response"
    return (200, "") if reply["success"] else (reply["status"], reply["error"])


# ── The relay checks a rule the way the LAN route does ─────────────────────


@pytest.mark.parametrize("transport", ["lan", "relay"])
@pytest.mark.parametrize("channel,target,relay_paired,refusal", [
    # The `mister` / `aux` case: a channel the node lacks; the error names
    # the channels it has.
    ("mister", RELAY, True, "aux"),
    ("fan", RELAY, True, "no channel 'fan'"),
    # A placeholder no node of its role answers: it can reach nothing.
    ("fae", "relay-01", False, "No 'relay' node"),
    ("aux", RELAY, True, None),
])
async def test_a_new_rule_is_checked_the_same_on_every_transport(
        request, monkeypatch, transport, channel, target, relay_paired, refusal):
    if relay_paired:
        await register_node(RELAY, "relay", RELAY_CHANNELS)
    status, error = await _write(request, monkeypatch, transport, _rule_body(channel, target))
    if refusal:
        assert status == 422 and refusal in error
        assert "Vent" not in await _rule_names()
    else:
        assert status == 200
        (stored,) = await rows("SELECT rule_data FROM automation_rules WHERE name = 'Vent'")
        assert json.loads(stored["rule_data"])["action"]["channel"] == channel


@pytest.mark.parametrize("transport", ["lan", "relay"])
async def test_a_refused_edit_keeps_the_stored_rule(request, monkeypatch, transport):
    await register_node(RELAY, "relay", RELAY_CHANNELS)
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    status, _ = await _write(request, monkeypatch, transport, _rule_body("mister"), rule_id)
    assert status == 422
    (stored,) = await rows("SELECT rule_data FROM automation_rules WHERE id = ?", rule_id)
    assert json.loads(stored["rule_data"])["action"]["channel"] == "fae"


def _body(state="on", photoperiod="on", compound=False):
    schedule = {"type": "schedule", "schedule": {"photoperiod": photoperiod}}
    condition = ({"type": "compound", "compound": {"op": "AND", "conditions": [
        schedule, {"type": "threshold",
                   "threshold": {"sensor": "temp_f", "operator": "gt", "value": 0}}]}}
                 if compound else schedule)
    return {"name": "probe", "condition": condition,
            "action": {"target": "plug-heater", "state": state}}


def test_rule_writes_refuse_an_unreadable_state_or_photoperiod(client):
    """Anything but on/off used to be read as "off": a photoperiod "bogus"
    inverted the light cycle. Read in any case and spacing, and checked inside
    a compound too."""
    assert client.post("/api/automation/rules", json=_body(state="toggle")).status_code == 422
    assert client.post("/api/automation/rules", json=_body(photoperiod="bogus")).status_code == 422
    assert client.post("/api/automation/rules",
                       json=_body(photoperiod="bogus", compound=True)).status_code == 422
    ok = client.post("/api/automation/rules", json=_body(state="ON"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["action"]["state"] == "on"


# ── Every write reaches the engine's rule cache at once ────────────────────


async def _fires(mock_mqtt) -> bool:
    mock_mqtt.clear()
    await evaluate_rules("climate-1", {"temp_f": 70})
    return any(t == f"sporeprint/{RELAY}/cmd/fae" for t, _ in mock_mqtt)


async def _switch_off(rule_id):
    assert await toggle_rule(rule_id) is False


async def _delete(rule_id):
    assert await delete_rule(rule_id)


async def _edit(rule_id):
    edited = _rule_body("fae")
    edited["condition"]["threshold"]["value"] = 100  # temp_f 70 no longer matches
    assert await update_validated_rule(rule_id, AutomationRule.model_validate(edited))


@pytest.mark.parametrize("write", [_switch_off, _delete, _edit], ids=["toggle", "delete", "edit"])
async def test_a_rule_write_takes_effect_at_once(mock_mqtt, write):
    # A profile the engine does not know still runs every rule (no setpoints).
    await start_grow("unit-test-species", "fruiting")
    await register_node(RELAY, "relay", RELAY_CHANNELS)
    rule_id = await create_rule(AutomationRule.model_validate(_rule_body("fae")))
    assert await _fires(mock_mqtt)          # warms the engine's 5 s rule cache
    await write(rule_id)
    assert not await _fires(mock_mqtt)      # within the cache's lifetime
    # Only the firing before the write is on record.
    assert len(await rows("SELECT id FROM automation_firings WHERE rule_id = ?", rule_id)) == 1


# ── the REST routes ────────────────────────────────────────────────────────


def test_a_rule_lives_and_dies_through_the_rest_routes(client):
    body = _rule_body("fae", target="node-x1")
    rule_id = client.post("/api/automation/rules", json=body).json()["id"]
    assert client.get(f"/api/automation/rules/{rule_id}").json()["name"] == "Vent"
    body["name"] = "Vent (edited)"
    assert client.put(f"/api/automation/rules/{rule_id}", json=body).json() == {
        **AutomationRule.model_validate(body).model_dump(), "id": rule_id}
    assert client.delete(f"/api/automation/rules/{rule_id}").json() == {"status": "deleted"}
    assert client.get(f"/api/automation/rules/{rule_id}").status_code == 404
    assert client.put(f"/api/automation/rules/{rule_id}", json=body).status_code == 404
    assert client.delete(f"/api/automation/rules/{rule_id}").status_code == 404


def test_the_release_route_ends_a_hold(client):
    for channel in ("fae", "aux"):
        client.post("/api/automation/overrides",
                    json={"target": "node-x1", "channel": channel, "reason": "pin"})
    assert client.delete("/api/automation/overrides/node-x1",
                         params={"channel": "fae"}).json() == {"status": "cleared"}
    assert not is_overridden("node-x1", "fae")
    assert [o["channel"] for o in client.get("/api/automation/overrides").json()] == ["aux"]


def test_a_rule_round_trips_through_its_table_row():
    """The metadata columns are the row's own, never duplicated in rule_data."""
    for rule in BUILTIN_RULES:
        data = serialize_rule_data(rule)
        assert not {"id", "name", "description", "enabled", "priority"} & json.loads(data).keys()
        row = {"id": 99, "name": rule.name, "description": rule.description,
               "enabled": int(rule.enabled), "priority": rule.priority, "rule_data": data}
        assert AutomationRule.model_validate(deserialize_rule_row(row)) == rule.model_copy(
            update={"id": 99})


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
