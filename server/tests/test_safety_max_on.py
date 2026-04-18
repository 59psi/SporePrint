"""safety_max_on_seconds enforcement (P14 / R15).

A rule with `safety_max_on_seconds` must schedule an auto-off publish after
the declared delay so a stuck-on heater can't become a fire. The tests
monkeypatch `asyncio.sleep` through a short-circuit so we don't actually
wait in test time.
"""

import asyncio

import app.automation.engine as engine
from app.automation.engine import _fire_rule, _safety_tasks, set_override
from app.automation.models import (
    AutomationRule,
    ConditionType,
    ManualOverride,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.sessions.models import SessionCreate
from app.sessions.service import create_session


async def _make_session():
    return await create_session(SessionCreate(
        name="safety-max-on",
        species_profile_id="blue_oyster",
        substrate="CVG",
        substrate_volume="1 quart",
    ))


def _rule(state: str, safety_max: int | None):
    return AutomationRule(
        id=1,
        name="heater-watchdog",
        condition=RuleCondition(
            type=ConditionType.THRESHOLD,
            threshold=ThresholdCondition(sensor="temp_f", operator="lt", value=60),
        ),
        action=RuleAction(target="relay-01", channel="heater", state=state),
        safety_max_on_seconds=safety_max,
    )


_real_sleep = asyncio.sleep


async def _wait_done(task: asyncio.Task, timeout: float = 1.0) -> None:
    """Wait for a task to fully finish (including cancelling→cancelled transition)."""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass


async def test_safety_auto_off_publishes_off_after_delay(monkeypatch, mock_mqtt):
    """A rule with safety_max_on_seconds must publish OFF when the delay elapses."""
    sleep_calls: list[float] = []

    async def fast_sleep(delay):
        sleep_calls.append(delay)
        # Use the captured real sleep so we don't recurse into ourselves.
        await _real_sleep(0)

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", fast_sleep)

    session = await _make_session()
    rule = _rule(state="on", safety_max=1800)
    await _fire_rule(rule, {"temp_f": 55}, session)

    task = _safety_tasks.get("relay-01:heater")
    assert task is not None
    await _wait_done(task)

    assert sleep_calls == [1800], "scheduled delay should match rule.safety_max_on_seconds"
    # First call is the heater ON, second is the auto-off.
    assert len(mock_mqtt) >= 2
    last_topic, last_payload = mock_mqtt[-1]
    assert last_topic == "sporeprint/relay-01/cmd/heater"
    assert last_payload == {"state": "off", "reason": "safety_max_on_seconds"}


async def test_off_action_cancels_pending_watchdog(monkeypatch, mock_mqtt):
    """A subsequent OFF rule must cancel the pending auto-off task."""
    async def never_finishes(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", never_finishes)

    session = await _make_session()
    on_rule = _rule(state="on", safety_max=1800)
    off_rule = _rule(state="off", safety_max=None)

    await _fire_rule(on_rule, {"temp_f": 55}, session)
    assert "relay-01:heater" in _safety_tasks
    pending = _safety_tasks["relay-01:heater"]

    await _fire_rule(off_rule, {"temp_f": 75}, session)
    await _wait_done(pending)
    assert pending.cancelled() or pending.done()


async def test_manual_override_cancels_watchdog(monkeypatch, mock_mqtt):
    """set_override cancels any pending safety auto-off (operator owns timing)."""
    async def never_finishes(_delay):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.automation.engine.asyncio.sleep", never_finishes)

    session = await _make_session()
    await _fire_rule(_rule(state="on", safety_max=1800), {"temp_f": 55}, session)
    pending = _safety_tasks.get("relay-01:heater")
    assert pending is not None and not pending.done()

    await set_override(ManualOverride(target="relay-01", channel="heater", reason="operator holds"))

    await _wait_done(pending)
    assert pending.cancelled() or pending.done()


async def test_no_watchdog_when_publish_failed(monkeypatch, mock_mqtt):
    """If the ON publish failed, don't schedule a phantom auto-off."""
    mock_mqtt.mock.return_value = False

    session = await _make_session()
    await _fire_rule(_rule(state="on", safety_max=1800), {"temp_f": 55}, session)

    assert "relay-01:heater" not in _safety_tasks
