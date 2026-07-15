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

from app.automation.engine import evaluate_rules  # noqa: F401 (import guard)
from app.automation.smart_plugs import target_is_present
from app.automation.templates import BUILTIN_RULES
from app.db import get_db


def _targets():
    """(target, channel) pairs every seeded rule can actuate."""
    out = set()
    for r in BUILTIN_RULES:
        out.add((r.action.target, r.action.channel))
    return out


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
}


def test_every_bom_actuator_has_a_rule():
    targeted = _targets()
    missing = {label for key, label in BOM_ACTUATORS.items() if key not in targeted}
    assert not missing, f"BOM actuators with no automation rule (never run): {sorted(missing)}"


def test_lighting_is_covered():
    """Lighting is scene-driven (light-01), not per-channel — assert it's driven."""
    assert any(r.action.target == "light-01" for r in BUILTIN_RULES)


# ── capability-aware fallbacks ────────────────────────────────────────────


def test_vent_fallback_is_gated_on_dehumidifier_absence():
    vent = next(r for r in BUILTIN_RULES if r.name == "Humidity Vent (no dehumidifier)")
    assert vent.requires_absent_target == "plug-dehumidifier"
    assert vent.action.channel == "exhaust"


def test_mist_fallback_is_gated_on_humidifier_absence():
    mist = next(r for r in BUILTIN_RULES if r.name == "Mist (no humidifier)")
    assert mist.requires_absent_target == "plug-humidifier"
    assert mist.action.channel == "aux"
    # over-misting is a contamination risk — must be hard-gated
    assert mist.action.duration_sec is not None and mist.action.duration_sec <= 15
    assert mist.safety_max_on_seconds is not None and mist.safety_max_on_seconds <= 60


async def test_target_is_present_true_for_a_registered_dehumidifier():
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name, device_role) "
            "VALUES ('plug-dehumidifier', 'tasmota', 'tasmota/dh', 'DH', 'dehumidifier')",
        )
        await db.commit()
    assert await target_is_present("plug-dehumidifier") is True


async def test_target_is_present_false_when_nothing_paired():
    """No dehumidifier registered → the vent fallback is allowed to run."""
    assert await target_is_present("plug-dehumidifier") is False


async def test_target_is_present_matches_a_node_channel():
    async with get_db() as db:
        import json
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels) VALUES ('relay-01', 'relay', ?)",
            (json.dumps(["fae", "exhaust", "circulation", "aux"]),),
        )
        await db.commit()
    assert await target_is_present("circulation") is True
    assert await target_is_present("nonexistent") is False
