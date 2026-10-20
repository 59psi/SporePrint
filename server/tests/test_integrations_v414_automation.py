"""A rule whose action names a vendor goes through the integrations
dispatcher, never MQTT, and its firing records whether the write went out.

(Native rules publishing MQTT: test_automation_fire.py. The integrations
RPC's HMAC signing: test_cloud_integrations_signing.py.)
"""

from __future__ import annotations

from typing import Any

from app.automation.engine import _fire_rule
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.db import get_db
from app.integrations import _actions as _vendor_actions


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


async def _latest_firing() -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT rule_name, status, error FROM automation_firings ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def test_a_vendor_rule_goes_through_the_dispatcher_not_mqtt(monkeypatch, mock_mqtt):
    calls: list[tuple] = []

    async def fake_dispatch(slug, action, params):
        calls.append((slug, action, params))
        return {"ok": True}

    monkeypatch.setattr(_vendor_actions, "dispatch", fake_dispatch)
    rule = _make_vendor_rule("kasa", "set_power", {"ip": "10.0.0.20", "on": True})
    await _fire_rule(rule, readings={"humidity": 90}, session=None, sio=None)

    assert calls == [("kasa", "set_power", {"ip": "10.0.0.20", "on": True})]
    # No meaningless command on a relay topic alongside the vendor call.
    assert mock_mqtt == []
    assert (await _latest_firing())["status"] == "sent"


async def test_a_vendor_write_that_fails_is_a_failed_firing_not_a_crash(monkeypatch, mock_mqtt):
    async def vendor_offline(*args, **kwargs):
        raise RuntimeError("vendor offline")

    monkeypatch.setattr(_vendor_actions, "dispatch", vendor_offline)
    rule = _make_vendor_rule("kasa", "set_power", {"ip": "10.0.0.20", "on": True})
    await _fire_rule(rule, readings={"humidity": 90}, session=None, sio=None)

    firing = await _latest_firing()
    assert firing["status"] == "failed"
    assert "vendor offline" in firing["error"]
    assert mock_mqtt == []
