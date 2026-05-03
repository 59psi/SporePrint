"""Tests for the Pi-side integrations RPC handler."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.cloud import integrations_proxy
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
