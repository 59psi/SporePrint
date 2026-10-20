"""Cold storage, the advance suggestion's forks, and sealed-container gating.

The product spec: a user inoculates something (agar / LC / grain / bag) and
colonizes it. A grow BAG then goes on to fruit (pinning → flushes). Everything
else is pulled once colonized and parked in the FRIDGE until used. And because
the CO2/RH sensors read chamber air — not the inside of a sealed vessel — the
chamber's environmental control is meaningless for a sealed bag or jar and must
not churn the fans against it.

The whole suggested_next_phase table (both forks, the flush loop, the phases a
species profile skips, shiitake browning) lives here.
"""

import json

import pytest

from app.automation.engine import (
    _acts_on_chamber_environment,
    _cold_storage_params,
    _container_is_sealed,
    evaluate_rules,
)
from app.automation.models import RuleAction
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.db import get_db
from app.sessions.models import (
    BAG_CONTAINERS,
    CULTURE_CONTAINERS,
    FRUITING_CONTAINERS,
    OPEN_CONTAINERS,
    PhaseAdvance,
    SessionCreate,
)
from app.sessions.service import (
    advance_phase,
    create_session,
    release_cold_storage_links,
    suggested_next_phase,
)
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins

_PHASES = {p.id: [ph.value for ph in p.phases] for p in BUILTIN_PROFILES}
_PINK = _PHASES["pink_oyster"]          # pinning folded into fruiting, no rest
_BLUE = _PHASES["blue_oyster"]          # defines primordia induction
_SHIITAKE = _PHASES["shiitake"]         # browns before it pins
_GRAIN_ONLY = ["grain_colonization"]    # a sclerotia species

# ── the advance suggestion ────────────────────────────────────────────────


@pytest.mark.parametrize(("current", "container", "more_flushes", "profile_phases", "expected"), [
    # The colonization fork: bulk substrate goes on to pin, a culture vessel
    # to the fridge (every container spelling: test_every_container_is_classified).
    ("substrate_colonization", "grow_bag", True, None, "primordia_induction"),
    ("grain_colonization", "jar", True, None, "cold_storage"),
    # You rest after every flush, then go again until the bag is spent.
    ("fruiting", "grow_bag", True, None, "rest"),
    ("rest", "grow_bag", True, None, "fruiting"),
    ("rest", "grow_bag", False, None, "complete"),
    # Phases the profile does not define are skipped ...
    ("substrate_colonization", "grow_bag", True, _PINK, "fruiting"),
    ("substrate_colonization", "grow_bag", True, _BLUE, "primordia_induction"),
    ("grain_colonization", "grow_bag", True, _GRAIN_ONLY, "complete"),
    ("cold_storage", None, True, _GRAIN_ONLY, "complete"),
    # ... but rest runs on fruiting's setpoints, so the flush loop is kept.
    ("fruiting", "grow_bag", True, _PINK, "rest"),
    ("rest", "grow_bag", True, _PINK, "fruiting"),
    # Browning is suggested only to a profile that defines it.
    ("substrate_colonization", "grow_bag", True, _SHIITAKE, "browning"),
    ("browning", "grow_bag", True, _SHIITAKE, "primordia_induction"),
    ("browning", "grow_bag", True, None, "primordia_induction"),
    ("grain_colonization", "jar", True, _SHIITAKE, "cold_storage"),
    ("cold_storage", "jar", True, _SHIITAKE, "primordia_induction"),
], ids=[
    "bag-pins", "jar-to-fridge", "fruiting-rests", "rest-refruits", "spent-bag-completes",
    "pink-skips-pinning", "blue-keeps-pinning", "grain-only-completes", "fridge-with-nothing-after",
    "pink-still-rests", "pink-rest-refruits", "shiitake-browns", "browned-block-pins",
    "browning-without-profile", "shiitake-jar-to-fridge", "fridge-is-not-followed-by-browning",
])
def test_suggested_next_phase(current, container, more_flushes, profile_phases, expected):
    assert suggested_next_phase(current, container, more_flushes,
                                profile_phases=profile_phases) == expected


# ── cold storage params ───────────────────────────────────────────────────


def test_cold_storage_is_a_fridge_with_nothing_else_running():
    p = _cold_storage_params()
    assert 35 <= p.temp_min_f <= p.temp_max_f <= 45
    assert p.fae_mode == "none"
    assert p.light_hours_on == 0
    # never vent a fridge to "lower CO2"
    assert p.co2_max_ppm >= 10000


# ── sealed-container gating ────────────────────────────────────────────────


def test_culture_vessels_are_sealed_in_every_phase():
    unsealed = [(c, p.value) for c in CULTURE_CONTAINERS for p in GrowPhase
                if not _container_is_sealed(c, p.value)]
    assert unsealed == []


def test_a_bag_is_sealed_until_it_is_opened_to_brown_or_fruit():
    """You cut the bag to fruit (and a shiitake block comes out of it to
    brown): CO2 control becomes real again."""
    expected = {"grain_colonization": True, "substrate_colonization": True,
                "browning": False, "primordia_induction": False, "fruiting": False}
    for bag in BAG_CONTAINERS:
        assert {p: _container_is_sealed(bag, p) for p in expected} == expected, bag


def test_open_and_unknown_containers_are_never_sealed():
    """Don't over-gate: an unknown or legacy container keeps full control."""
    for container in (*OPEN_CONTAINERS, None, "bucket"):
        assert not any(_container_is_sealed(container, p.value) for p in GrowPhase), container


def test_environmental_actions_are_recognised():
    for chan in ("fae", "exhaust", "circulation", "aux"):
        assert _acts_on_chamber_environment(RuleAction(target="relay-01", channel=chan))
    for plug in ("plug-humidifier", "plug-dehumidifier"):
        assert _acts_on_chamber_environment(RuleAction(target=plug))
    # temperature actuators are NOT chamber-air — a heater warms the vessel too
    assert not _acts_on_chamber_environment(RuleAction(target="plug-heater"))
    assert not _acts_on_chamber_environment(RuleAction(target="light-01", scene="x"))


# ── one container taxonomy ─────────────────────────────────────────────────

# Every container the dashboards offer, and the older spellings the session
# code still accepts.
_OFFERED = ("agar_plate", "liquid_culture", "grain_jar", "grow_bag", "monotub", "tray")
_ACCEPTED = _OFFERED + ("jar", "agar", "bag", "bulk_bag")


@pytest.mark.parametrize("container", _ACCEPTED)
def test_every_container_is_classified(container):
    """A culture vessel goes to cold storage, bulk substrate fruits — the
    engine's sealed gate and the advance suggestion read the same classes."""
    assert (container in CULTURE_CONTAINERS) != (container in FRUITING_CONTAINERS)
    sealed_at_fruiting = _container_is_sealed(container, "fruiting")
    next_phase = suggested_next_phase("substrate_colonization", container)
    assert sealed_at_fruiting == (next_phase == "cold_storage")


# ── a jar in cold storage has left the chamber it grew in ──────────────────


async def _chamber(name, ids):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES (?, ?)", (name, json.dumps(ids)))
        await db.commit()
        return cursor.lastrowid


async def _grow(name, phase, container, chamber_id=None):
    return await create_session(SessionCreate(
        name=name, species_profile_id="blue_oyster", substrate="rye",
        current_phase=phase, container_type=container, chamber_id=chamber_id))


async def _closet_with_plugs():
    await seed_builtins()
    await seed_builtin_rules()
    await register_plug("plug-c1", "Cooler", "tasmota", "tasmota/c1", device_role="cooler")
    await register_plug("plug-h1", "Heater", "tasmota", "tasmota/h1", device_role="heater")


async def test_a_jar_in_cold_storage_does_not_drive_the_closet_it_left(
        mock_mqtt, mock_mqtt_raw, alerts):
    await _closet_with_plugs()
    closet = await _chamber("Closet", ["climate-1", "relay-1"])
    jar = await _grow("spawn jar", "grain_colonization", "grain_jar", chamber_id=closet)
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await evaluate_rules("climate-1", {"temp_f": 72, "humidity": 45})
    assert mock_mqtt_raw == [], "the closet ran the fridge's 35-40 °F band"
    assert not any(alerts.values()), alerts


async def test_a_grow_sharing_the_closet_stays_managed(mock_mqtt, mock_mqtt_raw, alerts):
    """A newer jar parked in cold storage no longer takes the closet's nodes
    from the grow still fruiting there."""
    await _closet_with_plugs()
    await _grow("tub", "fruiting", "monotub")
    jar = await _grow("spawn jar", "grain_colonization", "grain_jar")
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await evaluate_rules("climate-1", {"temp_f": 50})  # the tub's band is 55-65 °F
    assert ("tasmota/h1/cmnd/POWER", "ON") in mock_mqtt_raw


async def test_a_jar_already_in_cold_storage_is_released_at_start_up(mock_mqtt_raw, alerts):
    """A grow that entered cold storage before advancing dropped the link
    still held the chamber it grew in."""
    await _closet_with_plugs()
    closet = await _chamber("Closet", ["climate-1"])
    jar = await _grow("spawn jar", "grain_colonization", "grain_jar", chamber_id=closet)
    async with get_db() as db:  # the phase change as an older release made it
        await db.execute("UPDATE sessions SET current_phase = 'cold_storage' WHERE id = ?",
                         (jar["id"],))
        await db.commit()
    assert await release_cold_storage_links() == 1
    await evaluate_rules("climate-1", {"temp_f": 72})
    assert mock_mqtt_raw == [] and not any(alerts.values()), alerts
