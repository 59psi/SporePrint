"""Hardware-capability verdict — GET /api/chambers/{id}/automation-coverage (V2-1).

The verdict must be HONEST: an actuator reads "available" only when the paired
smart-plug row or node channel actually says so, and a requirement the chamber
can't meet directly is either flagged unavailable or shown degrading to a real,
present fallback (vent-with-fans for a missing dehumidifier, etc.).
"""

import json

from app.automation.coverage import _rule_applies, compute_coverage
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import seed_builtin_rules
from app.db import get_db
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile


# ── builders ──────────────────────────────────────────────────────────────


def _phase_params() -> PhaseParams:
    return PhaseParams(
        temp_min_f=60, temp_max_f=75,
        humidity_min=85, humidity_max=95,
        co2_max_ppm=800, co2_tolerance="low",
        light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
        fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
        expected_duration_days=(7, 14),
    )


def _profile(phases, species_id="test_sp", cultivable=True) -> SpeciesProfile:
    pp = _phase_params()
    return SpeciesProfile(
        id=species_id,
        common_name="Test Fungus",
        scientific_name="Testus testus",
        category="gourmet",
        chamber_cultivable=cultivable,
        substrate_types=["straw"],
        colonization_visual_description="x",
        contamination_risk_notes="x",
        pinning_trigger_description="x",
        phases={p: pp for p in phases},
        flush_count_typical=2,
        yield_notes="x",
    )


async def _register_plug(plug_id: str, role: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name, device_role) "
            "VALUES (?, 'tasmota', ?, ?, ?)",
            (plug_id, f"tasmota/{plug_id}", plug_id, role),
        )
        await db.commit()


async def _register_node(node_id: str, channels: list[str] | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels) VALUES (?, 'relay', ?)",
            (node_id, json.dumps(channels) if channels is not None else None),
        )
        await db.commit()


def _by_key(requirements):
    return {(r["target"], r["channel"]): r for r in requirements}


# ── the phase/species gate (pure) ─────────────────────────────────────────


def test_rule_applies_matches_engine_gate():
    def mk(**kw):
        return AutomationRule(
            name="r",
            condition=RuleCondition(
                type=ConditionType.THRESHOLD,
                threshold=ThresholdCondition(sensor="humidity", operator="lt", value=1),
            ),
            action=RuleAction(target="t"),
            **kw,
        )

    # No gates → applies to every phase/species.
    assert _rule_applies(mk(), "sp", "fruiting")
    # Phase gate.
    assert _rule_applies(mk(applies_to_phases=["fruiting"]), "sp", "fruiting")
    assert not _rule_applies(mk(applies_to_phases=["fruiting"]), "sp", "agar")
    # Species gate.
    assert _rule_applies(mk(applies_to_species=["sp"]), "sp", "fruiting")
    assert not _rule_applies(mk(applies_to_species=["other"]), "sp", "fruiting")


# ── compute_coverage core ─────────────────────────────────────────────────


async def test_reference_only_species_has_no_phases():
    await seed_builtin_rules()
    assert await compute_coverage(_profile([GrowPhase.FRUITING], cultivable=False)) == []


async def test_bare_chamber_marks_every_requirement_unavailable():
    await seed_builtin_rules()
    phases = await compute_coverage(_profile([GrowPhase.FRUITING]))
    assert len(phases) == 1
    assert phases[0]["phase"] == "fruiting"
    reqs = _by_key(phases[0]["requirements"])
    # The fruiting actuators are all required but nothing is paired.
    for key in [("plug-dehumidifier", None), ("plug-humidifier", None),
                ("relay-01", "exhaust"), ("light-01", None)]:
        assert key in reqs, key
        assert reqs[key]["available"] is False
        assert reqs[key]["fallback"] is None


async def test_paired_plug_and_channel_read_available():
    await seed_builtin_rules()
    await _register_plug("plug-dehumidifier", "dehumidifier")
    await _register_node("relay-01", ["fae", "exhaust", "circulation", "aux"])
    reqs = _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])
    dh = reqs[("plug-dehumidifier", None)]
    assert dh["available"] is True and dh["fallback"] is None
    assert reqs[("relay-01", "exhaust")]["available"] is True
    assert reqs[("relay-01", "fae")]["available"] is True


async def test_dehumidifier_degrades_to_exhaust_when_absent():
    """No dehumidifier, but the exhaust fan is present → the requirement is
    unavailable BUT the vent fallback (relay-01/exhaust) covers it."""
    await seed_builtin_rules()
    await _register_node("relay-01", ["fae", "exhaust", "circulation", "aux"])
    reqs = _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])
    dh = reqs[("plug-dehumidifier", None)]
    assert dh["available"] is False
    assert dh["fallback"] == "relay-01/exhaust"


async def test_fallback_is_none_when_the_fallback_actuator_is_also_absent():
    """No dehumidifier AND no exhaust channel → genuinely unavailable, no
    fallback to name (we never claim a fallback that isn't itself present)."""
    await seed_builtin_rules()
    reqs = _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])
    dh = reqs[("plug-dehumidifier", None)]
    assert dh["available"] is False
    assert dh["fallback"] is None


async def test_present_dehumidifier_suppresses_the_fallback():
    await seed_builtin_rules()
    await _register_plug("plug-dehumidifier", "dehumidifier")
    await _register_node("relay-01", ["fae", "exhaust", "circulation", "aux"])
    reqs = _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])
    dh = reqs[("plug-dehumidifier", None)]
    assert dh["available"] is True
    assert dh["fallback"] is None


async def test_channel_rejected_by_live_node_is_unavailable():
    """A node that has enumerated its channels but LACKS 'exhaust' → the
    exhaust requirement is unavailable even though the node exists."""
    await seed_builtin_rules()
    await _register_node("relay-01", ["fae", "circulation"])  # no exhaust/aux
    reqs = _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])
    assert reqs[("relay-01", "exhaust")]["available"] is False


async def test_light_node_presence_uses_the_node_registry():
    """A scene-driven light node has no channel and no plug row — presence is
    the node being registered, not target_is_present (which can't see it)."""
    await seed_builtin_rules()
    profile = _profile([GrowPhase.FRUITING])
    reqs = _by_key((await compute_coverage(profile))[0]["requirements"])
    assert reqs[("light-01", None)]["available"] is False
    await _register_node("light-01")  # lighting node reports in, no channels yet
    reqs2 = _by_key((await compute_coverage(profile))[0]["requirements"])
    assert reqs2[("light-01", None)]["available"] is True


async def test_colonization_excludes_fruiting_only_actuators():
    await seed_builtin_rules()
    phases = await compute_coverage(_profile([GrowPhase.SUBSTRATE_COLONIZATION]))
    keys = {(r["target"], r["channel"]) for r in phases[0]["requirements"]}
    # Circulation + the dehumidifier are fruiting-phase only.
    assert ("relay-01", "circulation") not in keys
    assert ("plug-dehumidifier", None) not in keys
    # Temperature/humidity + the profile-independent CO2 hard ceiling apply always.
    assert ("plug-humidifier", None) in keys
    assert ("relay-01", "exhaust") in keys


async def test_requirements_are_deduped_by_target_channel():
    """Humidifier is driven by several rules (boost/cut/dry-weather) — it must
    appear exactly once."""
    await seed_builtin_rules()
    reqs = (await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"]
    hum = [r for r in reqs if (r["target"], r["channel"]) == ("plug-humidifier", None)]
    assert len(hum) == 1


async def test_all_profile_phases_are_reported_in_order():
    await seed_builtin_rules()
    ordered = [GrowPhase.SUBSTRATE_COLONIZATION, GrowPhase.PRIMORDIA_INDUCTION, GrowPhase.FRUITING]
    phases = await compute_coverage(_profile(ordered))
    assert [p["phase"] for p in phases] == [g.value for g in ordered]


# ── HTTP contract ─────────────────────────────────────────────────────────


def test_endpoint_404_unknown_chamber(client):
    r = client.get("/api/chambers/9999/automation-coverage?species=lions_mane")
    assert r.status_code == 404


def test_endpoint_404_unknown_species(client):
    cid = client.post("/api/chambers", json={"name": "Tent A"}).json()["id"]
    r = client.get(f"/api/chambers/{cid}/automation-coverage?species=does_not_exist")
    assert r.status_code == 404


def test_endpoint_requires_species_param(client):
    cid = client.post("/api/chambers", json={"name": "Tent B"}).json()["id"]
    assert client.get(f"/api/chambers/{cid}/automation-coverage").status_code == 422


def test_endpoint_happy_path_shape(client):
    cid = client.post("/api/chambers", json={"name": "Tent C"}).json()["id"]
    r = client.get(f"/api/chambers/{cid}/automation-coverage?species=lions_mane")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("phases"), list) and body["phases"]
    phase = body["phases"][0]
    assert set(phase.keys()) == {"phase", "requirements"}
    req = phase["requirements"][0]
    assert set(req.keys()) == {"target", "channel", "available", "fallback"}
    # A freshly-created chamber has no paired hardware.
    assert req["available"] is False
