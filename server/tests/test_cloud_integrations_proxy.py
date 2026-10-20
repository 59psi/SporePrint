"""Tests for the Pi-side integrations RPC handler.

These exercise dispatch, so they send unsigned frames with strict signing
turned off; the signature and replay gate (on by default) has its own suite,
test_cloud_integrations_signing.py.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import app.cloud.service as cloud_service
from app.automation.models import AutomationRule
from app.automation.service import create_rule
from app.cloud import integrations_proxy
from app.config import settings
from app.db import get_db
from app.integrations import _registry


class _FakeSio:
    """Captures emitted events so each test can assert on the payload."""

    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))


@pytest.fixture
def fake_sio() -> _FakeSio:
    return _FakeSio()


@pytest.fixture(autouse=True)
def _dispatch_only(monkeypatch):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)
    cloud_service._seen_command_ids.clear()
    yield
    cloud_service._seen_command_ids.clear()


@pytest.mark.asyncio
async def test_dropped_when_no_id(fake_sio):
    await integrations_proxy.handle_request(fake_sio, {"action": "list"})
    assert fake_sio.emits == []


@pytest.mark.asyncio
async def test_unknown_action_responds_with_error(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio, {"id": "x", "action": "nuke"}
    )
    assert len(fake_sio.emits) == 1
    event, payload = fake_sio.emits[0]
    assert event == "integrations_response"
    assert payload["success"] is False
    assert "unknown action" in payload["error"]


@pytest.mark.asyncio
async def test_list_dispatches_to_registry(monkeypatch, fake_sio):
    fake_list = AsyncMock(return_value=[{"slug": "grafana"}])
    monkeypatch.setattr(_registry, "list_integrations", fake_list)

    await integrations_proxy.handle_request(
        fake_sio, {"id": "x", "action": "list"}
    )
    fake_list.assert_awaited_once()
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"] == [{"slug": "grafana"}]


@pytest.mark.asyncio
async def test_get_config_requires_slug(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio, {"id": "x", "action": "get_config"}
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400


@pytest.mark.asyncio
async def test_put_config_forwards_payload(monkeypatch, fake_sio):
    captured = {}

    async def fake_put(slug: str, payload):
        captured["slug"] = slug
        captured["payload"] = payload
        return {"slug": slug, "enabled": True, "ok": True}

    monkeypatch.setattr(_registry, "put_config", fake_put)

    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "put_config",
            "slug": "grafana",
            "payload": {"enabled": True, "config": {}},
        },
    )
    assert captured["slug"] == "grafana"
    assert captured["payload"] == {"enabled": True, "config": {}}
    assert fake_sio.emits[0][1]["success"] is True


@pytest.mark.asyncio
async def test_test_action_serialises_health(monkeypatch, fake_sio):
    from app.integrations._base import IntegrationHealth

    async def fake_test(slug: str):
        return IntegrationHealth(state="degraded", last_error="slow")

    monkeypatch.setattr(_registry, "test_connection", fake_test)
    await integrations_proxy.handle_request(
        fake_sio,
        {"id": "x", "action": "test", "slug": "grafana"},
    )
    body = fake_sio.emits[0][1]["body"]
    assert body == {
        "state": "degraded",
        "last_error": "slow",
        "details": {},
    }


@pytest.mark.asyncio
async def test_http_exception_preserves_status(monkeypatch, fake_sio):
    async def fake_get(slug: str):
        raise HTTPException(status_code=404, detail="unknown slug")

    monkeypatch.setattr(_registry, "get_config", fake_get)
    await integrations_proxy.handle_request(
        fake_sio,
        {"id": "x", "action": "get_config", "slug": "nope"},
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 404
    assert payload["error"] == "unknown slug"


@pytest.mark.asyncio
async def test_unexpected_exception_returns_500(monkeypatch, fake_sio):
    async def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(_registry, "list_integrations", explode)
    await integrations_proxy.handle_request(
        fake_sio, {"id": "x", "action": "list"}
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 500
    assert "boom" in payload["error"]


@pytest.mark.asyncio
async def test_attach_registers_handler():
    """`attach()` must wire up `integrations_request` on the socket."""

    handlers: dict[str, callable] = {}

    class _Recorder:
        def on(self, event: str):
            def _decorator(fn):
                handlers[event] = fn
                return fn
            return _decorator

    integrations_proxy.attach(_Recorder())
    assert "integrations_request" in handlers


# ── v4.1.5 automation rule CRUD via the same proxy ──────────────────


@pytest.mark.asyncio
async def test_automation_list_dispatches_to_service(monkeypatch, fake_sio):
    from app.automation import service as automation_service

    fake = AsyncMock(return_value=[
        {
            "id": 1,
            "name": "humidity floor",
            "description": "",
            "enabled": True,
            "priority": 0,
            "condition": {
                "type": "threshold",
                "threshold": {"sensor": "humidity", "operator": "lt", "value": 92},
            },
            "action": {"target": "node-1"},
        }
    ])
    monkeypatch.setattr(automation_service, "list_rules_with_created_at", fake)

    await integrations_proxy.handle_request(
        fake_sio, {"id": "x", "action": "automation_list"}
    )
    fake.assert_awaited_once()
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"][0]["id"] == 1


@pytest.mark.asyncio
async def test_automation_create_hydrates_model(monkeypatch, fake_sio):
    from app.automation import service as automation_service

    captured = {}

    async def fake_create(rule):
        captured["rule"] = rule
        return 42

    monkeypatch.setattr(automation_service, "create_rule", fake_create)

    rule_payload = {
        "name": "co2 ceiling",
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "co2_ppm", "operator": "gt", "value": 1200},
        },
        "action": {
            "target": "vendor:wemo:10.0.0.20",
            "vendor_slug": "wemo",
            "vendor_action": "set_power",
            "vendor_params": {"on": True},
        },
    }

    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "automation_create",
            "payload": {"rule": rule_payload},
        },
    )
    assert captured["rule"].name == "co2 ceiling"
    assert captured["rule"].action.vendor_slug == "wemo"
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"]["id"] == 42


@pytest.mark.asyncio
async def test_automation_create_rejects_missing_rule(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio,
        {"id": "x", "action": "automation_create", "payload": {}},
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400


@pytest.mark.asyncio
async def test_automation_update_returns_404_when_missing(monkeypatch, fake_sio):
    from app.automation import service as automation_service

    monkeypatch.setattr(
        automation_service, "update_rule", AsyncMock(return_value=False)
    )

    rule_payload = {
        "name": "x",
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "humidity", "operator": "lt", "value": 90},
        },
        "action": {"target": "node-1"},
    }
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "automation_update",
            "payload": {"rule_id": 999, "rule": rule_payload},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 404


@pytest.mark.asyncio
async def test_automation_delete_dispatches(monkeypatch, fake_sio):
    from app.automation import service as automation_service

    monkeypatch.setattr(
        automation_service, "delete_rule", AsyncMock(return_value=True)
    )

    await integrations_proxy.handle_request(
        fake_sio,
        {"id": "x", "action": "automation_delete", "payload": {"rule_id": 7}},
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"]["id"] == 7


@pytest.mark.asyncio
async def test_automation_delete_rejects_non_int(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "automation_delete",
            "payload": {"rule_id": "seven"},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400


# ── v5.0.0 pre-grow: chamber coverage + planner propose via the proxy ──
#
# The cloud-web wizard/planner forward these over the same RPC channel;
# without a Pi-side branch the operator got "unknown action" at runtime
# even though the cloud routes and Pi helpers both existed.


@pytest.mark.asyncio
async def test_chamber_coverage_dispatches(monkeypatch, fake_sio):
    fake_profile = object()
    monkeypatch.setattr(
        "app.species.service.get_profile",
        AsyncMock(return_value=fake_profile),
    )
    captured = {}

    async def fake_coverage(profile):
        captured["profile"] = profile
        return [{"phase": "fruiting", "requirements": []}]

    monkeypatch.setattr("app.automation.coverage.compute_coverage", fake_coverage)

    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "chamber_automation_coverage",
            "payload": {"chamber_id": "dev-1", "species": "blue_oyster"},
        },
    )
    # Resolved profile is what the coverage computer receives; the cloud
    # device id ("dev-1") is intentionally not used for the computation.
    assert captured["profile"] is fake_profile
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"] == {"phases": [{"phase": "fruiting", "requirements": []}]}


@pytest.mark.asyncio
async def test_chamber_coverage_unknown_species_404(monkeypatch, fake_sio):
    monkeypatch.setattr(
        "app.species.service.get_profile", AsyncMock(return_value=None)
    )
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "chamber_automation_coverage",
            "payload": {"chamber_id": "dev-1", "species": "ghost"},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 404


@pytest.mark.asyncio
async def test_chamber_coverage_requires_species(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "chamber_automation_coverage",
            "payload": {"chamber_id": "dev-1"},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400


@pytest.mark.asyncio
async def test_planner_propose_dispatches_json_safe(monkeypatch, fake_sio):
    from datetime import date

    class _FakeCycle:
        def __init__(self) -> None:
            self.dump_mode = "unset"

        def model_dump(self, mode=None):
            self.dump_mode = mode
            return {
                "species_id": "blue_oyster",
                "start_date": "2026-08-01",
                "phases": [],
            }

    fake_cycle = _FakeCycle()
    captured = {}

    async def fake_propose(species_id, start):
        captured["species_id"] = species_id
        captured["start"] = start
        return fake_cycle

    monkeypatch.setattr(
        "app.planner.service.propose_cycle_for_species", fake_propose
    )

    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "planner_propose",
            "payload": {"species": "blue_oyster", "start": "2026-08-01"},
        },
    )
    assert captured["species_id"] == "blue_oyster"
    assert captured["start"] == date(2026, 8, 1)
    # The ProposedCycle carries date objects — it MUST be dumped mode="json"
    # or socket.io's JSON encoder chokes on the wire.
    assert fake_cycle.dump_mode == "json"
    payload = fake_sio.emits[0][1]
    assert payload["success"] is True
    assert payload["body"]["start_date"] == "2026-08-01"


@pytest.mark.asyncio
async def test_planner_propose_unknown_species_404(monkeypatch, fake_sio):
    monkeypatch.setattr(
        "app.planner.service.propose_cycle_for_species",
        AsyncMock(return_value=None),
    )
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "planner_propose",
            "payload": {"species": "ghost", "start": "2026-08-01"},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 404


@pytest.mark.asyncio
async def test_planner_propose_bad_date_400(fake_sio):
    await integrations_proxy.handle_request(
        fake_sio,
        {
            "id": "x",
            "action": "planner_propose",
            "payload": {"species": "blue_oyster", "start": "not-a-date"},
        },
    )
    payload = fake_sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 400


# ── rules saved from the cloud get the LAN editor's checks ──────────────
#
# A rule for a channel its node does not have looks armed and never moves
# anything (the node drops cmd/<unknown>). The LAN route refuses it with 422;
# the relay path stored it. Driven with real signed frames, strict mode on.

_KEY = "unit-test-cloud-token"


def _signed(frame: dict) -> dict:
    frame = {**frame, "ts": time.time()}
    body = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**frame, "signature": hmac.new(_KEY.encode(), body, hashlib.sha256).hexdigest()}


def _mister_rule(name: str) -> dict:
    return {
        "name": name,
        "condition": {
            "type": "threshold",
            "threshold": {"sensor": "humidity", "operator": "lt", "value": 85},
        },
        # The relay bank is fae / exhaust / circulation / aux: no "mister".
        "action": {"target": "relay-01", "channel": "mister", "state": "on"},
    }


async def _rule_rows() -> list[tuple]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id, name, rule_data FROM automation_rules ORDER BY id")
        return [tuple(r) for r in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_relay_rule_writes_refuse_a_channel_the_node_lacks(monkeypatch, fake_sio):
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", True)
    monkeypatch.setattr(settings, "cloud_token", _KEY)
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) VALUES (?, ?, ?, ?)",
            ("node-relay-1", "relay", json.dumps(["aux", "circulation", "exhaust", "fae"]), time.time()),
        )
        await db.commit()
    good = _mister_rule("fan")
    good["action"]["channel"] = "fae"
    rule_id = await create_rule(AutomationRule(**good))
    before = await _rule_rows()

    await integrations_proxy.handle_request(fake_sio, _signed(
        {"id": "create-1", "action": "automation_create", "payload": {"rule": _mister_rule("mist")}}))
    await integrations_proxy.handle_request(fake_sio, _signed(
        {"id": "update-1", "action": "automation_update",
         "payload": {"rule_id": rule_id, "rule": _mister_rule("fan")}}))

    for _event, payload in fake_sio.emits:
        assert payload["success"] is False, payload
        assert payload["status"] == 422, payload
        assert "mister" in payload["error"]
    assert len(fake_sio.emits) == 2
    assert await _rule_rows() == before, "a refused rule must not be written"
