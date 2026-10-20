"""A node command's state means the same thing to every firmware and to the Pi.

Node firmware reads a string state as ON only when it is "on" (after
lower-casing) and as an explicit OFF otherwise; firmware before the hardware
audit let a pwm in the same command win. The Pi's bookkeeping read only
"off" as an OFF. So {"state": "false", "pwm": 200} went out unchanged: OFF on
current firmware, ON at duty 200 on older images, and an ON to the Pi, which
kept a safety ceiling armed that the next automation ON then tripped early.
Every node command is now sent as "on" or "off" (normalize_node_command).
"""

import json

import pytest

from app.automation.engine import _fire_rule, _safety_tasks
from app.automation.models import AutomationRule, RuleAction
from app.automation.service import is_off_command, node_command_state, normalize_node_command
from app.hardware.service import send_command
from tests._pi_a_engine import (  # noqa: F401 (fixtures)
    REAL_SLEEP,
    ended,
    engine_state,
    frozen_sleep,
    make_rule,
    rows,
    threshold,
    watchdog_rows,
)


@pytest.mark.parametrize("state,sent", [
    ("on", "on"), ("ON", "on"), (" On ", "on"),
    ("off", "off"), ("OFF", "off"), ("false", "off"), ("0", "off"), ("", "off"),
    ("toggle", "off"), (" on x", "off"),
])
def test_a_string_state_is_sent_as_the_firmware_reads_it(state, sent):
    assert node_command_state(state) == sent
    out = normalize_node_command({"state": state, "pwm": 200})
    assert out["state"] == sent
    # An OFF never carries a duty value; an ON keeps it.
    assert ("pwm" in out) == (sent == "on")
    assert is_off_command(out) == (sent == "off")


def test_a_non_string_state_is_left_to_the_firmware():
    # The firmware ignores a state that is not a string (pwm alone decides).
    for state in (True, False, 1, None):
        assert node_command_state(state) == state
    assert normalize_node_command({"pwm": 0}) == {"pwm": 0}
    assert normalize_node_command({"state": False, "pwm": 9}) == {"state": False, "pwm": 9}


def test_the_callers_command_is_not_modified():
    command = {"state": "False", "pwm": 200}
    assert normalize_node_command(command) == {"state": "off"}
    assert command == {"state": "False", "pwm": 200}
    on = {"state": "on", "pwm": 200}
    assert normalize_node_command(on) is on


def _ceiling_rule(state: str = "on") -> AutomationRule:
    return make_rule(RuleAction(target="relay-01", channel="fae", state=state, pwm=200),
                     condition=threshold("temp_f", "gt", 0), ceiling=3600, name="fan guard",
                     log_to_session=False)


async def test_a_manual_false_goes_out_as_off_and_clears_the_ceiling(frozen_sleep, mock_mqtt):
    await _fire_rule(_ceiling_rule(), {}, None)
    armed = _safety_tasks["relay-01:fae"]

    topic, published = await send_command("relay-01", {"channel": "fae", "state": "false",
                                                       "pwm": 200})

    assert published and topic == "sporeprint/relay-01/cmd/fae"
    assert mock_mqtt[-1] == (topic, {"state": "off"})
    await REAL_SLEEP(0)
    assert ended(armed)
    assert "relay-01:fae" not in _safety_tasks
    assert await watchdog_rows() == []


async def test_a_manual_uppercase_on_keeps_its_duty(mock_mqtt):
    await send_command("relay-01", {"channel": "fae", "state": "ON", "pwm": 180})
    assert mock_mqtt[-1] == ("sporeprint/relay-01/cmd/fae", {"state": "on", "pwm": 180})


async def test_a_stored_rule_with_an_off_spelling_publishes_off_and_clears_the_ceiling(
        frozen_sleep, mock_mqtt):
    """A rule stored before states were checked can still say "false": its
    node is sent a plain OFF, and the ceiling an earlier ON armed is cleared."""
    await _fire_rule(_ceiling_rule(), {}, None)
    armed = _safety_tasks["relay-01:fae"]
    stored = _ceiling_rule().model_dump()
    stored["action"]["state"] = "false"
    await _fire_rule(AutomationRule.model_validate(stored), {}, None)

    sent = [p for t, p in mock_mqtt if t == "sporeprint/relay-01/cmd/fae"]
    assert sent[-1] == {"state": "off"}
    await REAL_SLEEP(0)
    assert ended(armed)
    assert await watchdog_rows() == []
    (row,) = await rows("SELECT action_taken FROM automation_firings ORDER BY id DESC LIMIT 1")
    assert json.loads(row["action_taken"]) == {"state": "off"}
