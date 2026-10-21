"""Hardware-capability verdict — GET /api/chambers/{id}/automation-coverage.

The verdict must be HONEST: an actuator reads "available" only when the paired
smart-plug row or node channel actually says so, and a requirement the chamber
can't meet directly is either flagged unavailable or shown degrading to a real,
present fallback (vent-with-fans for a missing dehumidifier, etc.).
"""

import json
import re
from pathlib import Path

import pytest

from app.automation.coverage import (
    _PERSONALITY_CHANNELS,
    _actuator_present,
    _rule_applies,
    compute_coverage,
)
from app.automation.models import AutomationRule, RuleAction
from app.automation.service import create_rule, seed_builtin_rules
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.db import get_db
from app.integrations import _registry, _settings_store
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile
from app.species.service import get_profile, seed_builtins
from tests._builders import RELAY_CHANNELS, threshold

_PERSONALITY_H = (Path(__file__).resolve().parents[2]
                  / "firmware" / "lib" / "sp_core" / "personality.h")


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


# Real provisioning registers plugs and nodes under hardware-derived ids, never
# the seeded placeholders (plug-dehumidifier / relay-01 / light-01). Coverage
# must still report the placeholder a rule NAMES as available — resolved by
# device_role (plugs) or node_type (nodes) — so these helpers pair hardware the
# way the build guide does, under an id distinct from the rule target.
async def _register_plug(hardware_id: str, role: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name, device_role) "
            "VALUES (?, 'tasmota', ?, ?, ?)",
            (hardware_id, f"tasmota/{hardware_id}", hardware_id, role),
        )
        await db.commit()


async def _register_node(
    node_id: str, channels: list[str] | None = None, node_type: str = "relay"
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type,
             json.dumps(channels) if channels is not None else None, 1_752_700_000.0),
        )
        await db.commit()


def _by_key(requirements):
    return {(r["target"], r["channel"]): r for r in requirements}


async def _fruiting_requirements():
    return _by_key((await compute_coverage(_profile([GrowPhase.FRUITING])))[0]["requirements"])


# ── the phase/species gate (pure) ─────────────────────────────────────────


def _gated(**kw):
    return AutomationRule(name="r", condition=threshold("humidity", "lt", 1),
                          action=RuleAction(target="t"), **kw)


@pytest.mark.parametrize("rule,species,phase,applies", [
    (_gated(), "sp", "fruiting", True),                       # no gates: everything
    (_gated(applies_to_phases=["fruiting"]), "sp", "fruiting", True),
    (_gated(applies_to_phases=["fruiting"]), "sp", "agar", False),
    (_gated(applies_to_species=["sp"]), "sp", "fruiting", True),
    (_gated(applies_to_species=["other"]), "sp", "fruiting", False),
    # Sessions store the hyphenated UI spelling, templates the table id: an
    # exact match never matched, so every species-scoped rule read as absent.
    (_gated(applies_to_species=["lions_mane"]), "lions-mane", "fruiting", True),
    (_gated(applies_to_species=["lions_mane"]), "lions_mane", "fruiting", True),
    (_gated(applies_to_species=["lions_mane"]), "reishi", "fruiting", False),
])
def test_a_rule_counts_for_the_phases_and_species_the_engine_runs_it_for(
        rule, species, phase, applies):
    assert _rule_applies(rule, species, phase) is applies


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


@pytest.mark.parametrize("dehumidifier,relay,available,fallback", [
    # Paired by role under its hardware id; the relay under its MAC-derived id.
    (True, True, True, None),
    # No dehumidifier, but an exhaust fan: unavailable, and the vent covers it.
    (False, True, False, "relay-01/exhaust"),
    # Neither: no fallback is claimed that is not itself present.
    (False, False, False, None),
])
async def test_the_dehumidifier_reads_available_or_degrades_to_a_present_vent(
        dehumidifier, relay, available, fallback):
    await seed_builtin_rules()
    if dehumidifier:
        await _register_plug("plug-a1b2c3", "dehumidifier")
    if relay:
        await _register_node("node-relay-7a3f", RELAY_CHANNELS)
    reqs = await _fruiting_requirements()
    dh = reqs[("plug-dehumidifier", None)]
    assert (dh["available"], dh["fallback"]) == (available, fallback)
    assert reqs[("relay-01", "exhaust")]["available"] is relay
    assert reqs[("relay-01", "fae")]["available"] is relay


async def test_channel_rejected_by_live_node_is_unavailable():
    """A node that has enumerated its channels but LACKS 'exhaust' → the
    exhaust requirement is unavailable even though the node exists."""
    await seed_builtin_rules()
    await _register_node("node-relay-7a3f", ["fae", "circulation"])  # no exhaust/aux
    assert (await _fruiting_requirements())[("relay-01", "exhaust")]["available"] is False


async def test_light_node_presence_uses_the_node_registry():
    """A scene-driven light node has no channel and no plug row — presence is a
    lighting node being registered. The rule names the light-01 placeholder, but
    the real node is MAC-derived, so presence resolves by node_type='lighting',
    NOT by a literal light-01 row (target_is_present can't see it either)."""
    await seed_builtin_rules()
    assert (await _fruiting_requirements())[("light-01", None)]["available"] is False
    # Lighting node reports in under its MAC-derived id, no channels yet.
    await _register_node("node-light-9b2c", node_type="lighting")
    assert (await _fruiting_requirements())[("light-01", None)]["available"] is True


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


def test_the_endpoint_refuses_an_unknown_chamber_or_species(client):
    assert client.get("/api/chambers/9999/automation-coverage?species=lions_mane").status_code == 404
    cid = client.post("/api/chambers", json={"name": "Tent A"}).json()["id"]
    assert client.get(f"/api/chambers/{cid}/automation-coverage?species=does_not_exist"
                      ).status_code == 404
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


# ── chamber scope, vendor devices, unreported channels ────────────────────


async def _chamber(name, ids):
    async with get_db() as db:
        await db.execute("INSERT INTO chambers (name, node_ids) VALUES (?, ?)",
                         (name, json.dumps(ids)))
        await db.commit()


async def test_another_chambers_relay_does_not_cover_this_chamber():
    """Any node anywhere reporting the channel used to make it read available."""
    await _register_node("clim-a", None, node_type="climate")
    await _register_node("relay-b", RELAY_CHANNELS)
    await _chamber("A", ["clim-a"])
    await _chamber("B", ["relay-b"])
    assert not await _actuator_present(RuleAction(target="node-1", channel="fae"), ["clim-a"])
    assert not await _actuator_present(RuleAction(target="relay-b", channel="fae"), ["clim-a"])
    assert not await _actuator_present(RuleAction(target="relay-01", channel="fae"), ["clim-a"])
    assert await _actuator_present(RuleAction(target="relay-b", channel="fae"), ["relay-b"])
    assert await _actuator_present(RuleAction(target="relay-01", channel="fae"), ["relay-b"])


async def test_another_chambers_light_does_not_cover_this_chambers_scene_rules():
    """The verdict resolves a placeholder within the chamber: chamber B's
    lighting node does not make chamber A's scene rules read as available."""
    await seed_builtins()
    await _register_node("light-b", node_type="lighting")
    await create_chamber(ChamberCreate(name="B", node_ids=["light-b"]))
    await create_rule(AutomationRule(
        name="scene", priority=1, condition=threshold("temp_f", "gt", 0),
        action=RuleAction(target="light-01", scene="fruiting_standard"),
    ))
    profile = await get_profile("blue_oyster")

    def _light(phases):
        return {r["available"] for ph in phases for r in ph["requirements"]
                if r["target"] == "light-01"}

    assert _light(await compute_coverage(profile)) == {True}
    assert _light(await compute_coverage(profile, chamber_nodes=["climate-a"])) == {False}


async def test_nodes_in_no_chamber_are_covered_by_the_relay_they_drive():
    """With no chamber (the verdict the cloud asks for, or a chamber that
    lists no nodes) a placeholder stands for the node that nodes in no
    chamber drive: one no chamber lists. The relay seen last anywhere,
    another chamber's, used to answer for them."""
    await _register_node("relay-closet", ["fae", "exhaust", "circulation"])
    await _register_node("relay-a", RELAY_CHANNELS)
    await _chamber("A", ["relay-a"])
    async with get_db() as db:  # chamber A's relay reported last
        await db.execute("UPDATE hardware_nodes SET last_seen = last_seen + 60 "
                         "WHERE node_id = 'relay-a'")
        await db.commit()
    assert await _actuator_present(RuleAction(target="relay-01", channel="fae"))
    assert not await _actuator_present(RuleAction(target="relay-01", channel="aux"))
    assert await _actuator_present(RuleAction(target="relay-01", channel="aux"), ["relay-a"])


async def test_a_node_that_has_not_reported_channels_offers_its_personalitys():
    await _register_node("relay-x", None)
    assert await _actuator_present(RuleAction(target="relay-x", channel="fae"))
    assert not await _actuator_present(RuleAction(target="relay-x", channel="white"))


def test_personality_channels_match_the_firmware():
    groups = re.findall(r"names\[4\]\s*=\s*\{([^}]+)\}", _PERSONALITY_H.read_text())
    firmware = [frozenset(re.findall(r'"([^"]+)"', g)) for g in groups]
    assert sorted(firmware, key=sorted) == sorted(_PERSONALITY_CHANNELS.values(), key=sorted)


async def test_a_vendor_requirement_reads_available_once_its_integration_is_enabled():
    """A vendor action's vendor:* key was looked up as a node and always read
    unavailable."""
    await create_rule(AutomationRule(
        name="kasa humidifier", condition=threshold("humidity", "lt", 80),
        action=RuleAction(target="vendor:kasa:10.0.0.20", vendor_slug="kasa",
                          vendor_action="set_power", vendor_params={"ip": "10.0.0.20", "on": True}),
    ))
    profile = _profile([GrowPhase.FRUITING])

    async def _kasa_available():
        reqs = _by_key((await compute_coverage(profile))[0]["requirements"])
        return reqs[("vendor:kasa:10.0.0.20", None)]["available"]

    assert await _kasa_available() is False
    secrets = _registry.registered_drivers()["kasa"].secret_fields
    await _settings_store.save("kasa", False, {}, secrets)
    assert await _kasa_available() is False  # configured, not enabled
    await _settings_store.set_enabled("kasa", True)
    assert await _kasa_available() is True


async def test_an_invalid_stored_rule_does_not_break_coverage():
    await seed_builtin_rules()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
            "VALUES ('broken', '', 1, 1, '{\"action\": 3}')",
        )
        await db.commit()
    assert await compute_coverage(_profile([GrowPhase.FRUITING]))
