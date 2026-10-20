"""Every actuator the BOM sells must be reachable by automation.

We ship circulation fans, a dehumidifier plug, and a misting pump — and until
now the seeded rules drove NONE of them. A user buys the hardware and the
software never actuates it. This is the guard that would have caught that: it
enumerates every actuator in the bill of materials and asserts at least one
seeded rule targets it.

It also pins the capability-aware humidity fallbacks: vent-with-fans stands in
for a missing dehumidifier, mist-pump stands in for a missing humidifier, and
neither fires when the real device is present.
"""

import pytest

from app.automation.smart_plugs import target_is_present
from app.automation.templates import BUILTIN_RULES
from tests._pi_a_engine import RELAY_CHANNELS, insert_plug, register_node

# Every actuator the BOM sells, as (target, channel). Keep in step with
# server/app/builder/hardware_guides.py — if the BOM grows an actuator, add it
# here and this test forces a rule to exist for it.
BOM_ACTUATORS = {
    ("relay-01", "fae"): "FAE fan (Tier 2+)",
    ("relay-01", "exhaust"): "Exhaust fan (Tier 2+)",
    ("relay-01", "circulation"): "Circulation fan (Tier 2+)",
    ("relay-01", "aux"): "Misting pump (Tier 3)",
    ("plug-humidifier", None): "Humidifier plug (Tier 1+)",
    ("plug-dehumidifier", None): "Dehumidifier plug (Tier 3)",
    ("plug-heater", None): "Heater plug (Tier 2+)",
    ("plug-cooler", None): "Peltier cooler plug (Tier 3)",
    # Lighting is scene-driven (light-01), not per channel.
    ("light-01", None): "LED lighting node",
}


def test_every_bom_actuator_has_a_rule():
    targeted = {(r.action.target, r.action.channel) for r in BUILTIN_RULES}
    missing = {label for key, label in BOM_ACTUATORS.items() if key not in targeted}
    assert not missing, f"BOM actuators with no automation rule (never run): {sorted(missing)}"


@pytest.mark.parametrize("name,absent,channel", [
    ("Humidity Vent (no dehumidifier)", "plug-dehumidifier", "exhaust"),
    ("Mist (no humidifier)", "plug-humidifier", "aux"),
])
def test_a_humidity_fallback_runs_only_while_its_device_is_absent(name, absent, channel):
    rule = next(r for r in BUILTIN_RULES if r.name == name)
    assert rule.requires_absent_target == absent
    assert rule.action.channel == channel
    if channel == "aux":
        # Over-misting is a contamination risk: hard-gated.
        assert rule.action.duration_sec is not None and rule.action.duration_sec <= 15
        assert rule.safety_max_on_seconds is not None and rule.safety_max_on_seconds <= 60


@pytest.mark.parametrize("paired,target,present", [
    (None, "plug-dehumidifier", False),               # nothing paired: the vent may run
    ("plug", "plug-dehumidifier", True),
    ("relay", "circulation", True),                   # a channel some node reports
    ("relay", "nonexistent", False),
])
async def test_target_is_present_reads_the_paired_plug_or_node_channel(paired, target, present):
    if paired == "plug":
        await insert_plug("plug-dehumidifier", "tasmota", "tasmota/dh", role="dehumidifier")
    elif paired == "relay":
        await register_node("relay-01", "relay", RELAY_CHANNELS)
    assert await target_is_present(target) is present
