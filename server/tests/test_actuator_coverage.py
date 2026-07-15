"""Every actuator the BOM sells must be driven by at least one rule.

This is the guard that would have caught the audit finding: the circulation
fan, the dehumidifier, and the misting pump were all sold hardware that no rule
ever actuated. Plus the capability-aware humidity-removal degradation
(dehumidifier when present, exhaust-fan evacuation when not) and the vendor
(Kasa/Tapo/…) action path.
"""

import json

import pytest

from app.automation.engine import evaluate_rules
from app.automation.models import (
    AutomationRule, ConditionType, RuleAction, RuleCondition, ThresholdCondition,
)
from app.automation.service import create_rule, seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.automation.templates import BUILTIN_RULES
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins


# (target, channel) — None channel = plug. Every one is on the BOM.
BOM_ACTUATORS = [
    ("relay-01", "fae"),
    ("relay-01", "exhaust"),
    ("relay-01", "circulation"),
    ("relay-01", "aux"),          # misting pump
    ("plug-humidifier", None),
    ("plug-dehumidifier", None),
    ("plug-heater", None),
    ("plug-cooler", None),
]


def test_every_bom_actuator_has_a_seeded_rule():
    covered = {(r.action.target, r.action.channel) for r in BUILTIN_RULES}
    missing = [a for a in BOM_ACTUATORS if tuple(a) not in covered]
    assert not missing, f"BOM actuators with no rule: {missing}"


async def _register_exhaust_node():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels) VALUES ('relay-01','relay',?)",
            (json.dumps(["fae", "exhaust", "circulation", "aux"]),),
        )
        await db.commit()


async def _fired_rule_names() -> set[str]:
    async with get_db() as db:
        cur = await db.execute("SELECT DISTINCT rule_name FROM automation_firings")
        return {r["rule_name"] for r in await cur.fetchall()}


async def _drive_high_humidity():
    await seed_builtins()
    await seed_builtin_rules()
    await _register_exhaust_node()
    await create_session(SessionCreate(
        name="rh", species_profile_id="blue_oyster",
        current_phase="fruiting", container_type="monotub"))
    # blue_oyster fruiting humidity_max = 92; 98 is over the ceiling.
    await evaluate_rules("relay-01", {"humidity": 98}, sio=None)
    return await _fired_rule_names()


async def test_humidity_removal_prefers_dehumidifier_when_present(mock_mqtt):
    await register_plug("plug-dehumidifier", "Dehum", "shelly", "shellies/dehum",
                        device_role="dehumidifier")
    fired = await _drive_high_humidity()
    assert "Dehumidifier On" in fired
    # Must NOT also vent — the two would fight (venting sheds CO2/temp too).
    assert "High Humidity Fan Evacuation" not in fired


async def test_humidity_removal_falls_back_to_fan_when_no_dehumidifier(mock_mqtt):
    fired = await _drive_high_humidity()   # no dehumidifier registered
    assert "High Humidity Fan Evacuation" in fired
    assert "Dehumidifier On" not in fired


async def test_fan_evacuation_targets_a_valid_channel(mock_mqtt):
    """The evacuation fallback must pass channel validation (exhaust is real)."""
    from app.automation.service import validate_action_channel
    await _register_exhaust_node()
    evac = next(r for r in BUILTIN_RULES if r.name == "High Humidity Fan Evacuation")
    assert await validate_action_channel(evac.action) is None


async def test_vendor_dehumidifier_path_dispatches(monkeypatch, mock_mqtt):
    """A dehumidifier driven via a vendor plug (Kasa) fires through the
    integrations dispatcher, not MQTT — the vendor path works for new rules."""
    from app.integrations import _actions
    calls = []

    async def _fake_dispatch(slug, action, params):
        calls.append((slug, action, params))

    monkeypatch.setattr(_actions, "dispatch", _fake_dispatch)

    await seed_builtins()
    await create_rule(AutomationRule(
        name="Vendor Dehumidifier On", priority=10,
        applies_to_phases=["fruiting"],
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="humidity", operator="gt",
                                                             profile_ref="humidity_max")),
        action=RuleAction(target="vendor:kasa:10.0.0.9", vendor_slug="kasa",
                          vendor_action="set_power", vendor_params={"on": True}),
    ))
    await create_session(SessionCreate(name="v", species_profile_id="blue_oyster",
                                       current_phase="fruiting", container_type="monotub"))
    await evaluate_rules("relay-01", {"humidity": 98}, sio=None)
    assert calls == [("kasa", "set_power", {"on": True})]
