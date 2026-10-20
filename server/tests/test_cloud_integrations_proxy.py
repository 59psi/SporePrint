"""The Pi-side integrations RPC handler: what each cloud action reaches and
how a refusal is reported back.

These exercise dispatch, so they send unsigned frames with strict signing
turned off; the signature and replay gate (on by default) has its own suite,
test_cloud_integrations_signing.py, and the rule-id wire forms theirs,
test_cloud_rule_id_contract.py.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi import HTTPException

import app.cloud.service as cloud_service
from app.automation.models import AutomationRule
from app.automation.service import create_rule, get_rule
from app.cloud import integrations_proxy
from app.config import settings
from app.db import get_db
from app.integrations import _registry
from app.integrations._base import IntegrationHealth
from tests._pi_b2_cloud import FakeSio, register_node, sign

_KEY = "unit-test-cloud-token"
RELAY_BANK = ["aux", "circulation", "exhaust", "fae"]


@pytest.fixture(autouse=True)
def _dispatch_only(monkeypatch):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    cloud_service._seen_command_ids.clear()
    yield
    cloud_service._seen_command_ids.clear()


async def _send(frame: dict) -> dict:
    sio = FakeSio()
    await integrations_proxy.handle_request(sio, {"id": "x", **frame})
    assert len(sio.emits) == 1, sio.emits
    return sio.last("integrations_response")


def _rule_payload(name: str = "fan", channel: str = "fae") -> dict:
    return {
        "name": name,
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "humidity", "operator": "lt", "value": 85},
        },
        "action": {"target": "relay-01", "channel": channel, "state": "on"},
    }


async def test_a_frame_without_an_id_is_dropped_unanswered():
    sio = FakeSio()
    await integrations_proxy.handle_request(sio, {"action": "list"})
    assert sio.emits == []


async def test_unknown_action_responds_with_error():
    resp = await _send({"action": "nuke"})
    assert resp["success"] is False
    assert resp["error"] == "unknown action 'nuke'"


# ── integration actions reach the registry ─────────────────────────────────


@pytest.fixture
def registry(monkeypatch):
    """Registry calls as (name, args); each returns a recognisable body."""
    calls: list[tuple] = []

    def _fake(name, result):
        async def call(*args):
            calls.append((name, *args))
            return result
        monkeypatch.setattr(_registry, name, call)

    _fake("list_integrations", [{"slug": "grafana"}])
    _fake("get_config", {"slug": "grafana", "config": {}})
    _fake("put_config", {"slug": "grafana", "enabled": True, "ok": True})
    _fake("enable", {"slug": "grafana", "enabled": True})
    _fake("disable", {"slug": "grafana", "enabled": False})
    _fake("test_connection", IntegrationHealth(state="degraded", last_error="slow"))
    return calls


@pytest.mark.parametrize("frame, call, body", [
    ({"action": "list"}, ("list_integrations",), [{"slug": "grafana"}]),
    ({"action": "get_config", "slug": "grafana"}, ("get_config", "grafana"),
     {"slug": "grafana", "config": {}}),
    ({"action": "put_config", "slug": "grafana", "payload": {"enabled": True, "config": {}}},
     ("put_config", "grafana", {"enabled": True, "config": {}}),
     {"slug": "grafana", "enabled": True, "ok": True}),
    ({"action": "enable", "slug": "grafana"}, ("enable", "grafana"),
     {"slug": "grafana", "enabled": True}),
    ({"action": "disable", "slug": "grafana"}, ("disable", "grafana"),
     {"slug": "grafana", "enabled": False}),
    # IntegrationHealth is a dataclass: serialised for the wire.
    ({"action": "test", "slug": "grafana"}, ("test_connection", "grafana"),
     {"state": "degraded", "last_error": "slow", "details": {}}),
], ids=["list", "get_config", "put_config", "enable", "disable", "test"])
async def test_each_integration_action_reaches_its_registry_call(registry, frame, call, body):
    resp = await _send(frame)
    assert resp == {"id": "x", "success": True, "body": body}
    assert registry == [call]


async def test_a_registry_http_error_keeps_its_status_and_detail(monkeypatch):
    async def fake_get(slug: str):
        raise HTTPException(status_code=404, detail="unknown slug")

    monkeypatch.setattr(_registry, "get_config", fake_get)
    resp = await _send({"action": "get_config", "slug": "nope"})
    assert (resp["success"], resp["status"], resp["error"]) == (False, 404, "unknown slug")


async def test_unexpected_exception_returns_500(monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_registry, "list_integrations", explode)
    resp = await _send({"action": "list"})
    assert (resp["success"], resp["status"]) == (False, 500)
    assert "boom" in resp["error"]


async def test_attach_answers_integrations_requests_on_the_socket(registry):
    """`attach()` wires `integrations_request` on the connector socket to the
    handler, answering on that same socket."""

    class _Socket(FakeSio):
        def __init__(self) -> None:
            super().__init__()
            self.handlers: dict = {}

        def on(self, event: str):
            def _decorator(fn):
                self.handlers[event] = fn
                return fn
            return _decorator

    socket = _Socket()
    integrations_proxy.attach(socket)
    await socket.handlers["integrations_request"]({"id": "via-socket", "action": "list"})
    assert socket.last("integrations_response")["id"] == "via-socket"
    assert registry == [("list_integrations",)]


# ── v4.1.5 automation rule CRUD via the same proxy ──────────────────


@pytest.fixture
async def relay_node():
    await register_node("node-relay-1", "relay", channels=RELAY_BANK)


async def test_automation_list_returns_the_rules_with_their_holds(relay_node):
    rid = await create_rule(AutomationRule(**_rule_payload("humidity floor")))
    resp = await _send({"action": "automation_list"})
    assert resp["success"] is True
    [rule] = [r for r in resp["body"] if r["id"] == rid]
    assert rule["name"] == "humidity floor"
    assert rule["held_by"] == []


async def test_automation_create_stores_the_rule_it_was_sent():
    """A vendor action (a smart plug through its integration) is not a node
    channel, so it is stored without the channel check."""
    rule = {**_rule_payload("co2 ceiling"), "action": {
        "target": "vendor:wemo:10.0.0.20", "vendor_slug": "wemo",
        "vendor_action": "set_power", "vendor_params": {"on": True}}}
    resp = await _send({"action": "automation_create", "payload": {"rule": rule}})
    assert resp["success"] is True, resp
    stored = await get_rule(resp["body"]["id"])
    assert stored["name"] == "co2 ceiling"
    assert resp["body"]["action"]["vendor_slug"] == "wemo"


@pytest.mark.parametrize("frame, status, error", [
    ({"action": "get_config"}, 400, "slug is required"),
    ({"action": "automation_create", "payload": {}}, 400, "automation_create requires payload.rule"),
    ({"action": "automation_update", "payload": {"rule": _rule_payload()}}, 400,
     "automation_update requires payload.rule_id"),
    ({"action": "automation_update", "payload": {"rule_id": 1}}, 400,
     "automation_update requires payload.rule"),
    ({"action": "automation_update", "payload": {"rule_id": 999, "rule": _rule_payload()}}, 404,
     "Rule not found"),
    ({"action": "automation_delete", "payload": {"rule_id": 999}}, 404, "Rule not found"),
    ({"action": "vendor_action", "slug": "kasa", "payload": {"ip": "10.0.0.20"}}, 400,
     "vendor_action requires payload.action"),
    ({"action": "chamber_automation_coverage", "payload": {"chamber_id": "dev-1"}}, 400,
     "chamber_automation_coverage requires payload.species"),
    ({"action": "planner_propose", "payload": {"start": "2026-08-01"}}, 400,
     "planner_propose requires payload.species"),
    ({"action": "planner_propose", "payload": {"species": "blue_oyster"}}, 400,
     "planner_propose requires payload.start"),
    ({"action": "planner_propose", "payload": {"species": "blue_oyster", "start": "not-a-date"}},
     400, "planner_propose start must be YYYY-MM-DD"),
], ids=["get-config-no-slug", "create-no-rule", "update-no-id", "update-no-rule",
        "update-unknown-rule", "delete-unknown-rule", "vendor-no-action",
        "coverage-no-species", "planner-no-species", "planner-no-start", "planner-bad-date"])
async def test_a_request_the_pi_cannot_serve_is_answered_with_its_status(
        relay_node, frame, status, error):
    resp = await _send(frame)
    assert (resp["success"], resp["status"]) == (False, status), resp
    assert resp["error"].startswith(error), resp["error"]


# ── v5.0.0 pre-grow: chamber coverage + planner propose via the proxy ──
#
# The cloud-web wizard/planner forward these over the same RPC channel;
# without a Pi-side branch the operator got "unknown action" at runtime
# even though the cloud routes and Pi helpers both existed.


@pytest.fixture
def pregrow(monkeypatch):
    """Profiles and planner results by species id; `ghost` is unknown."""
    seen: dict = {}
    profile = object()

    async def fake_get_profile(species):
        seen["species"] = species
        return None if species == "ghost" else profile

    async def fake_coverage(p):
        seen["profile"] = p
        return [{"phase": "fruiting", "requirements": []}]

    class _Cycle:
        def model_dump(self, mode=None):
            # The ProposedCycle carries date objects: it MUST be dumped
            # mode="json" or socket.io's JSON encoder chokes on the wire.
            seen["dump_mode"] = mode
            return {"species_id": "blue_oyster", "start_date": "2026-08-01", "phases": []}

    async def fake_propose(species_id, start):
        seen.update(species=species_id, start=start)
        return None if species_id == "ghost" else _Cycle()

    monkeypatch.setattr("app.species.service.get_profile", fake_get_profile)
    monkeypatch.setattr("app.automation.coverage.compute_coverage", fake_coverage)
    monkeypatch.setattr("app.planner.service.propose_cycle_for_species", fake_propose)
    seen["profile_obj"] = profile
    return seen


async def test_chamber_coverage_is_computed_for_the_species_profile(pregrow):
    resp = await _send({"action": "chamber_automation_coverage",
                        "payload": {"chamber_id": "dev-1", "species": "blue_oyster"}})
    # The cloud device id ("dev-1") is not used: coverage reads the live
    # hardware registries.
    assert resp["body"] == {"phases": [{"phase": "fruiting", "requirements": []}]}
    assert pregrow["species"] == "blue_oyster"
    assert pregrow["profile"] is pregrow["profile_obj"]


async def test_planner_propose_dispatches_json_safe(pregrow):
    resp = await _send({"action": "planner_propose",
                        "payload": {"species": "blue_oyster", "start": "2026-08-01"}})
    assert resp["success"] is True
    assert resp["body"]["start_date"] == "2026-08-01"
    assert (pregrow["species"], pregrow["start"]) == ("blue_oyster", date(2026, 8, 1))
    assert pregrow["dump_mode"] == "json"


@pytest.mark.parametrize("frame", [
    {"action": "chamber_automation_coverage", "payload": {"chamber_id": "dev-1", "species": "ghost"}},
    {"action": "planner_propose", "payload": {"species": "ghost", "start": "2026-08-01"}},
], ids=["coverage", "planner"])
async def test_an_unknown_species_profile_is_a_404(pregrow, frame):
    resp = await _send(frame)
    assert (resp["success"], resp["status"]) == (False, 404)
    assert "ghost" in resp["error"]


# ── rules saved from the cloud get the LAN editor's checks ──────────────
#
# A rule for a channel its node does not have looks armed and never moves
# anything (the node drops cmd/<unknown>). The LAN route refuses it with 422;
# the relay path stored it. Driven with real signed frames, strict mode on.


async def _rule_rows() -> list[tuple]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id, name, rule_data FROM automation_rules ORDER BY id")
        return [tuple(r) for r in await cursor.fetchall()]


async def test_relay_rule_writes_refuse_a_channel_the_node_lacks(monkeypatch, relay_node):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", True)
    monkeypatch.setattr(settings, "cloud_token", _KEY)
    rule_id = await create_rule(AutomationRule(**_rule_payload("fan")))
    before = await _rule_rows()
    # The relay bank is fae / exhaust / circulation / aux: no "mister".
    mister = _rule_payload("mist", channel="mister")

    sio = FakeSio()
    for frame in (
        {"id": "create-1", "action": "automation_create", "payload": {"rule": mister}},
        {"id": "update-1", "action": "automation_update",
         "payload": {"rule_id": rule_id, "rule": mister}},
    ):
        await integrations_proxy.handle_request(sio, sign({**frame, "ts": time.time()}, _KEY))

    assert len(sio.emits) == 2
    for _event, payload in sio.emits:
        assert (payload["success"], payload["status"]) == (False, 422), payload
        assert "mister" in payload["error"]
    assert await _rule_rows() == before, "a refused rule must not be written"
