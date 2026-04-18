"""Regression tests for automation rule-fire ordering (P4b).

Pre-v3.3.0 behaviour: _fire_rule published the MQTT command, then wrote
`automation_firings` status='fired'. If MQTT was disconnected (publish was a
no-op) the row still claimed success — the audit log lied. The new flow
writes `status='pending'`, attempts the publish, then updates to `sent` or
`failed` based on the real result.
"""

import json

from app.automation.engine import _fire_rule
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session


async def _make_session_and_rule(mock_mqtt):
    session = await create_session(SessionCreate(
        name="fire-ordering",
        species_profile_id="blue_oyster",
        substrate="CVG",
        substrate_volume="1 quart",
    ))
    rule = AutomationRule(
        id=1,
        name="fae-on",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="co2_ppm", operator="gt", value=1000),
        ),
        action=RuleAction(target="relay-01", channel="fae", state="on", pwm=255),
    )
    return session, rule


async def _latest_firing() -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, rule_name, status, error FROM automation_firings ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def test_fire_rule_marks_sent_when_publish_succeeds(mock_mqtt):
    session, rule = await _make_session_and_rule(mock_mqtt)
    await _fire_rule(rule, {"co2_ppm": 1500}, session, sio=None)

    firing = await _latest_firing()
    assert firing is not None
    assert firing["status"] == "sent"
    assert firing["error"] is None
    assert mock_mqtt and mock_mqtt[-1][0] == "sporeprint/relay-01/cmd/fae"


async def test_fire_rule_marks_failed_when_broker_disconnected(mock_mqtt):
    """Broker down during publish must NOT be recorded as a successful fire."""
    session, rule = await _make_session_and_rule(mock_mqtt)
    mock_mqtt.mock.return_value = False  # simulate MQTT reconnect window

    await _fire_rule(rule, {"co2_ppm": 1500}, session, sio=None)

    firing = await _latest_firing()
    assert firing is not None
    assert firing["status"] == "failed"
    assert firing["error"] and "mqtt_publish" in firing["error"]
