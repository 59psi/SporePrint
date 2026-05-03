"""v4.1.4 — automation engine integrates with vendor write actions,
and integrations RPC frames are HMAC-signed end-to-end.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.automation.engine import _fire_rule
from app.automation.models import (
    AutomationRule,
    RuleAction,
    RuleCondition,
    ConditionType,
    ThresholdCondition,
)
from app.integrations import _actions as _vendor_actions
from app.integrations._keystore import reset_fernet_cache


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


def _make_vendor_rule(slug: str, action: str, params: dict[str, Any]) -> AutomationRule:
    return AutomationRule(
        id=42,
        name="vendor-rule",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", value=80),
        ),
        action=RuleAction(
            target=f"vendor:{slug}",
            channel=None,
            state="on",
            vendor_slug=slug,
            vendor_action=action,
            vendor_params=params,
        ),
        cooldown_seconds=0,
    )


# ── Automation engine routes vendor actions through the dispatcher ──


@pytest.mark.asyncio
async def test_fire_rule_dispatches_to_vendor_action(
    fresh_keystore, monkeypatch
):
    captured: dict[str, Any] = {}

    async def fake_dispatch(slug, action, params):
        captured["slug"] = slug
        captured["action"] = action
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(_vendor_actions, "dispatch", fake_dispatch)
    # Mock mqtt_publish so this test doesn't touch a broker even though
    # the engine should bypass it.
    from app.automation import engine
    monkeypatch.setattr(engine, "mqtt_publish", AsyncMock(return_value=True))

    rule = _make_vendor_rule(
        "kasa", "set_power", {"ip": "10.0.0.20", "on": True}
    )
    await _fire_rule(rule, readings={"humidity": 90}, session=None, sio=None)
    assert captured == {
        "slug": "kasa",
        "action": "set_power",
        "params": {"ip": "10.0.0.20", "on": True},
    }


@pytest.mark.asyncio
async def test_fire_rule_does_not_call_mqtt_for_vendor_actions(
    fresh_keystore, monkeypatch
):
    """The engine should bypass MQTT entirely when the rule is a
    vendor action — otherwise we'd publish a meaningless command to
    the relay topic in addition to the vendor call."""
    fake_mqtt = AsyncMock(return_value=True)
    fake_dispatch = AsyncMock(return_value={"ok": True})

    from app.automation import engine
    monkeypatch.setattr(engine, "mqtt_publish", fake_mqtt)
    monkeypatch.setattr(_vendor_actions, "dispatch", fake_dispatch)

    rule = _make_vendor_rule("wemo", "set_power", {"ip": "10.0.0.10", "on": False})
    await _fire_rule(rule, readings={"humidity": 95}, session=None, sio=None)
    fake_mqtt.assert_not_called()
    fake_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fire_rule_records_failure_when_dispatch_raises(
    fresh_keystore, monkeypatch
):
    from app.automation import engine
    monkeypatch.setattr(engine, "mqtt_publish", AsyncMock(return_value=True))

    async def boom(*args, **kwargs):
        raise RuntimeError("vendor offline")

    monkeypatch.setattr(_vendor_actions, "dispatch", boom)

    rule = _make_vendor_rule("kasa", "set_power", {"ip": "10.0.0.20", "on": True})
    # Should not raise — the engine catches and records "failed" status.
    await _fire_rule(rule, readings={"humidity": 90}, session=None, sio=None)


@pytest.mark.asyncio
async def test_native_action_still_uses_mqtt(fresh_keystore, monkeypatch):
    """Tripwire: existing v3.x rules with no `vendor_slug` continue to
    publish MQTT. We don't accidentally hijack the native path."""
    fake_mqtt = AsyncMock(return_value=True)
    fake_dispatch = AsyncMock()

    from app.automation import engine
    monkeypatch.setattr(engine, "mqtt_publish", fake_mqtt)
    monkeypatch.setattr(_vendor_actions, "dispatch", fake_dispatch)

    rule = AutomationRule(
        id=1,
        name="native-rule",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="humidity", operator="gt", value=80),
        ),
        action=RuleAction(target="climate-01", channel="humidifier", state="on"),
        cooldown_seconds=0,
    )
    await _fire_rule(rule, readings={"humidity": 90}, session=None, sio=None)
    fake_mqtt.assert_awaited_once()
    topic, payload = fake_mqtt.call_args.args
    assert topic == "sporeprint/climate-01/cmd/humidifier"
    assert payload["state"] == "on"
    fake_dispatch.assert_not_called()


# ── HMAC-signed integrations RPC ────────────────────────────────────


class _FakeSio:
    def __init__(self):
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))


@pytest.mark.asyncio
async def test_signed_rpc_frame_passes_verification(fresh_keystore, monkeypatch):
    """Cloud signs the frame; Pi verifies and dispatches."""
    from app.cloud import integrations_proxy
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_token", "shared-secret-key")

    # Build a signed frame the same way the cloud-side proxy does.
    from cryptography.hazmat.primitives import hashes
    import hashlib
    import hmac as _hmac
    import json
    import time

    frame = {
        "id": "abc123",
        "action": "list",
        "slug": None,
        "payload": None,
        "ts": time.time(),
    }
    canonical = json.dumps(
        {k: v for k, v in frame.items() if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sig = _hmac.new(
        b"shared-secret-key", canonical, hashlib.sha256
    ).hexdigest()
    frame["signature"] = sig

    fake_dispatch = AsyncMock(return_value=[{"slug": "wemo"}])
    monkeypatch.setattr(
        integrations_proxy._registry, "list_integrations", fake_dispatch
    )

    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, frame)
    fake_dispatch.assert_awaited_once()
    payload = sio.emits[0][1]
    assert payload["success"] is True


@pytest.mark.asyncio
async def test_unsigned_frame_still_accepted_during_rollout(
    fresh_keystore, monkeypatch
):
    """Pi v4.1.4 still accepts unsigned frames so a cloud running an
    older version doesn't break. Once both sides are at v4.1.4+ we can
    flip to require signatures."""
    from app.cloud import integrations_proxy
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_token", "secret")

    fake_dispatch = AsyncMock(return_value=[])
    monkeypatch.setattr(
        integrations_proxy._registry, "list_integrations", fake_dispatch
    )

    sio = _FakeSio()
    await integrations_proxy.handle_request(
        sio, {"id": "x", "action": "list"}  # no signature
    )
    fake_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_signed_frame_with_bad_signature_is_rejected(
    fresh_keystore, monkeypatch
):
    from app.cloud import integrations_proxy
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_token", "shared-secret")

    sio = _FakeSio()
    await integrations_proxy.handle_request(
        sio,
        {
            "id": "abc",
            "action": "list",
            "ts": 1234567890.0,
            "signature": "not-a-real-signature",
        },
    )
    payload = sio.emits[0][1]
    assert payload["success"] is False
    assert payload["status"] == 401
    assert "signature" in payload["error"]
