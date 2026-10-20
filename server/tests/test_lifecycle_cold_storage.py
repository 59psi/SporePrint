"""Cold storage, the colonization fork, and sealed-container gating.

The product spec: a user inoculates something (agar / LC / grain / bag) and
colonizes it. A grow BAG then goes on to fruit (pinning → flushes). Everything
else is pulled once colonized and parked in the FRIDGE until used. And because
the CO2/RH sensors read chamber air — not the inside of a sealed vessel — the
chamber's environmental control is meaningless for a sealed bag or jar and must
not churn the fans against it.
"""

import json

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import (
    _acts_on_chamber_environment,
    _cold_storage_params,
    _container_is_sealed,
    evaluate_rules,
)
from app.automation.models import RuleAction
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.chambers.models import ChamberUpdate
from app.chambers.service import update_chamber
from app.db import get_db
from app.sessions.models import (
    CULTURE_CONTAINERS,
    FRUITING_CONTAINERS,
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
from app.species.service import seed_builtins


# ── the colonization fork ─────────────────────────────────────────────────


def test_colonized_bag_advances_to_fruiting():
    for phase in ("grain_colonization", "substrate_colonization"):
        assert suggested_next_phase(phase, "grow_bag") == "primordia_induction"


def test_colonized_monotub_and_tray_fruit_in_place():
    # Bulk substrate (monotub, tray) fruits in place like a cut bag — it must not
    # be parked in cold storage. Regression for the container-fork fix.
    for container in ("monotub", "tray"):
        assert suggested_next_phase("substrate_colonization", container) == "primordia_induction"


def test_colonized_jar_and_agar_go_to_cold_storage():
    assert suggested_next_phase("grain_colonization", "jar") == "cold_storage"
    assert suggested_next_phase("agar", "agar_plate") == "cold_storage"
    assert suggested_next_phase("liquid_culture", "jar") == "cold_storage"


def test_non_colonization_transitions_stay_linear():
    assert suggested_next_phase("primordia_induction", "grow_bag") == "fruiting"
    assert suggested_next_phase("fruiting", "grow_bag") == "rest"


# ── cold storage params ───────────────────────────────────────────────────


def test_cold_storage_is_a_fridge_with_nothing_else_running():
    p = _cold_storage_params()
    assert 35 <= p.temp_min_f <= p.temp_max_f <= 45
    assert p.fae_mode == "none"
    assert p.light_hours_on == 0
    # never vent a fridge to "lower CO2"
    assert p.co2_max_ppm >= 10000


# ── sealed-container gating ────────────────────────────────────────────────


def test_a_sealed_bag_during_colonization_is_sealed():
    assert _container_is_sealed("grow_bag", "substrate_colonization") is True


def test_the_bag_is_open_once_it_fruits():
    """You cut the bag to fruit — CO2 control becomes real again."""
    assert _container_is_sealed("grow_bag", "fruiting") is False
    assert _container_is_sealed("grow_bag", "primordia_induction") is False


def test_jars_and_agar_are_always_sealed():
    assert _container_is_sealed("jar", "fruiting") is True
    assert _container_is_sealed("agar_plate", "primordia_induction") is True


def test_a_monotub_is_never_sealed():
    for phase in ("substrate_colonization", "fruiting"):
        assert _container_is_sealed("monotub", phase) is False
        assert _container_is_sealed("tray", phase) is False


def test_unknown_container_is_treated_as_open():
    """Don't over-gate — an unknown/legacy container keeps full control."""
    assert _container_is_sealed(None, "fruiting") is False


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


@pytest.mark.parametrize("phase", [p.value for p in GrowPhase])
def test_a_liquid_culture_is_sealed_in_every_phase(phase):
    assert _container_is_sealed("liquid_culture", phase) is True


@pytest.mark.parametrize("container", _ACCEPTED)
def test_every_container_is_classified(container):
    """A culture vessel goes to cold storage, bulk substrate fruits — the
    engine's sealed gate and the advance suggestion read the same classes."""
    assert (container in CULTURE_CONTAINERS) != (container in FRUITING_CONTAINERS)
    sealed_at_fruiting = _container_is_sealed(container, "fruiting")
    next_phase = suggested_next_phase("substrate_colonization", container)
    assert sealed_at_fruiting == (next_phase == "cold_storage")


# ── a jar in cold storage has left the chamber it grew in ──────────────────


@pytest.fixture
def alerts(monkeypatch):
    sent: list[str] = []

    async def _page(title, message, tags=None, **kw):
        sent.append(title)

    async def _forward(event_type, data):
        sent.append(event_type)

    async def _co2(ppm, *args, **kw):
        sent.append("co2")

    monkeypatch.setattr(engine, "notify_critical", _page)
    monkeypatch.setattr(engine, "notify_warning", _page)
    monkeypatch.setattr(engine, "co2_alert", _co2)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    engine._paused = False
    engine._pause_loaded = False
    return sent


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
    assert alerts == []


async def test_a_grow_sharing_the_closet_stays_managed(mock_mqtt, mock_mqtt_raw, alerts):
    """A newer jar parked in cold storage no longer takes the closet's nodes
    from the grow still fruiting there."""
    await _closet_with_plugs()
    await _grow("tub", "fruiting", "monotub")
    jar = await _grow("spawn jar", "grain_colonization", "grain_jar")
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await evaluate_rules("climate-1", {"temp_f": 50})  # the tub's band is 55-65 °F
    assert ("tasmota/h1/cmnd/POWER", "ON") in mock_mqtt_raw


async def test_a_fridge_chamber_linked_to_the_jar_runs_cold_storage(alerts):
    await _closet_with_plugs()
    closet = await _chamber("Closet", ["climate-1"])
    fridge = await _chamber("Fridge", ["fridge-1"])
    jar = await _grow("spawn jar", "grain_colonization", "grain_jar", chamber_id=closet)
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await update_chamber(fridge, ChamberUpdate(active_session_id=jar["id"]))
    await evaluate_rules("fridge-1", {"temp_f": 52})  # far above the 35-40 °F band
    assert "temperature_alert" in alerts


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
    assert mock_mqtt_raw == [] and alerts == []
