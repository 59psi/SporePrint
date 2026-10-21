"""Automation engine — rule selection, arbitration and alerting.

One section per behaviour. Each test drives the real engine
(``evaluate_rules``) against a temp DB with real species profiles and, where
the behaviour is the shipped one, the real seeded rule templates:

- species-scoped rules never fired (hyphen vs underscore ids)
- no per-actuator arbitration (lowest priority sent last)
- Scheduled FAE ran in 'passive' FAE phases
- a phase the profile doesn't define disabled everything
- emergency alerts every frame; sealed containers paged on RH/CO2
- the rule `notification` flag was never read
- CO2 Hard Ceiling needed a session / open container / FAE phase
- cutoffs re-sent OFF every minute (and logged each one)
- cron only fired when a frame landed in the matching minute
- reishi growth_form (antler vs conk) was never read
- every node was evaluated against the newest session
- bulk_bag wasn't sealed during colonization
"""

import time

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import _container_is_sealed, evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ScheduleCondition,
)
from app.automation.service import create_rule, seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.automation.templates import BUILTIN_RULES
from app.db import get_db
from app.sessions.models import PhaseAdvance
from app.sessions.service import advance_phase
from app.species.service import seed_builtins
from tests._builders import (
    chamber,
    firings,
    make_rule,
    register_node,
    start_grow,
    threshold,
)
from tests._timing import clock, local


async def _seed_all():
    await seed_builtins()
    await seed_builtin_rules()


async def _pair_plug(role, dev):
    await register_plug(
        plug_id=f"plug-{dev}", name=role, plug_type="shelly",
        mqtt_topic_prefix=f"shellies/{dev}", device_role=role,
    )


def _plug_cmds(raw, dev):
    return [p for t, p in raw if t == f"shellies/{dev}/relay/0/command"]


def _cmds(mqtt, suffix):
    return [p for t, p in mqtt if t.endswith(suffix)]


async def _statuses(name):
    return [f["status"] for f in await firings(name)]


# ── species-scoped rules, and per-actuator arbitration ─────────────────────


async def test_cordyceps_blue_is_not_overwritten_by_the_generic_photoperiod(mock_mqtt):
    """The species rule applies (the session stores the id one way, the
    template the other), and its higher priority owns the light: the white
    photoperiod scene used to be sent after it."""
    await _seed_all()
    await start_grow("cordyceps_militaris", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 64})
    with clock(local(12, 40)):  # Photoperiod — Lights On's 1800 s cooldown is over
        await evaluate_rules("climate-1", {"temp_f": 64})
    assert [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")] == ["cordyceps_blue"]


async def test_cordyceps_dark_period_still_goes_dark(mock_mqtt):
    await _seed_all()
    await start_grow("cordyceps_militaris", "fruiting")  # 16/8 from 06:00 → dark at 23:00
    with clock(local(23)):
        await evaluate_rules("climate-1", {"temp_f": 64})
    assert [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")] == ["colonization_dark"]


async def test_higher_priority_off_holds_the_actuator_across_frames(mock_mqtt):
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "fruiting")
    await create_rule(AutomationRule(
        name="floor", priority=12, condition=threshold("co2_ppm", "lt", 1000),
        action=RuleAction(target="relay-01", channel="fae", state="off"),
        cooldown_seconds=300,
    ))
    await create_rule(AutomationRule(
        name="cycle", priority=5,
        condition=RuleCondition(type=ConditionType.SCHEDULE,
                                schedule=ScheduleCondition(interval_min=20)),
        action=RuleAction(target="relay-01", channel="fae", state="on", pwm=180, duration_sec=300),
        cooldown_seconds=600,
    ))
    t0 = local(12)
    with clock(t0):
        await evaluate_rules("climate-1", {"co2_ppm": 900})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off"]
    with clock(t0 + 90):  # floor is in cooldown but its condition still holds
        await evaluate_rules("climate-1", {"co2_ppm": 900})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off"]
    with clock(t0 + 120):  # floor released → the cycle may run
        await evaluate_rules("climate-1", {"co2_ppm": 1200})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off", "on"]


async def test_emergency_exhaust_is_not_downgraded_by_humidity_vent(mock_mqtt):
    await _seed_all()
    await start_grow("cubensis_golden_teacher", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 45000, "humidity": 97})
    exhaust = _cmds(mock_mqtt, "/cmd/exhaust")
    assert len(exhaust) == 1
    assert exhaust[0]["pwm"] == 255


async def test_night_cool_holds_the_cooler_against_cooling_cutoff(mock_mqtt, mock_mqtt_raw):
    """Lion's Mane Night Cool (a species-scoped rule) is selected at night,
    and keeps the cooler on against the Cooling Cutoff until its own swing
    target is reached."""
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await start_grow("lions_mane", "primordia_induction")
    t0 = local(23)
    for dt in (0, 61, 122):
        with clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 63})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on"]
    with clock(t0 + 183):  # swing target reached → the cutoff may switch it off
        await evaluate_rules("climate-1", {"temp_f": 59.5})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on", "off"]


async def test_pre_cool_does_not_chill_a_chamber_already_in_the_lower_half(mock_mqtt, mock_mqtt_raw):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await start_grow("cubensis_golden_teacher", "fruiting")  # 72-76 °F
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 72.5, "forecast_high_f": 97})
    assert "on" not in _plug_cmds(mock_mqtt_raw, "c1")


async def test_hot_forecast_cools_a_warm_chamber_without_the_cutoff_cancelling_it(
    mock_mqtt, mock_mqtt_raw, alerts,
):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await start_grow("cubensis_golden_teacher", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 75.5, "forecast_high_f": 97})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on"]
    assert any("Heat Wave Warning" in t for t, _ in alerts["warning"])


# ── Scheduled FAE only where the profile schedules FAE ─────────────────────


@pytest.mark.parametrize("species,co2,expected", [
    ("king_trumpet", 1500, []),      # primordia: passive FAE, CO2 held 1000-2000 on purpose
    ("lions_mane", 400, ["on"]),     # primordia: continuous FAE
])
async def test_scheduled_fae_runs_only_where_the_phase_schedules_fae(mock_mqtt, species, co2,
                                                                    expected):
    await _seed_all()
    await start_grow(species, "primordia_induction")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": co2})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae") if p["state"] == "on"] == expected


# ── phases the profile doesn't define ──────────────────────────────────────


async def test_missing_primordia_phase_falls_back_to_fruiting(mock_mqtt, mock_mqtt_raw, alerts):
    await _seed_all()
    await _pair_plug("heater", "h1")
    await start_grow("pink_oyster", "primordia_induction")  # pink oyster has no primordia phase
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 45})
    assert alerts["critical"], "a 45 °F pink oyster (dies < 40 °F) must page"
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]


async def test_missing_rest_phase_falls_back_to_fruiting(mock_mqtt, alerts):
    await _seed_all()
    await start_grow("lions_mane", "rest")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert any(e == "temperature_alert" for e, _ in alerts["forward"])


async def test_a_grow_advanced_to_rest_in_its_light_window_goes_dark(mock_mqtt, alerts):
    """Rest runs with the lights off, but no light rule covered rest: the
    fruiting scene stayed on for the whole rest."""
    await _seed_all()
    s = await start_grow("blue_oyster", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")] == ["fruiting_standard"]
    await advance_phase(s["id"], PhaseAdvance(phase="rest"))
    with clock(local(13)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _cmds(mock_mqtt, "/cmd/scene")[-1] == {"state": "off", "scene": "colonization_dark"}


# ── alert dedup + sealed containers ────────────────────────────────────────


async def test_sealed_grow_bag_does_not_page_on_room_humidity(alerts):
    """The same 45 % RH pages an open colonizing grow
    (tests/test_automation_safety_always_on.py)."""
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "substrate_colonization", container_type="grow_bag")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"humidity": 45, "temp_f": 77})
    assert alerts["critical"] == [] and alerts["warning"] == [] and alerts["forward"] == []


async def test_persisting_emergency_pages_once_per_window(alerts):
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "substrate_colonization")
    t0 = local(12)
    for dt in (0, 60, 120):
        with clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 95})
    assert len(alerts["critical"]) == 1
    assert [e for e, _ in alerts["forward"]] == ["temperature_alert"]
    with clock(t0 + 16 * 60):  # window over → the still-hot closet re-pages
        await evaluate_rules("climate-1", {"temp_f": 95})
    assert len(alerts["critical"]) == 2


async def test_escalation_from_warning_to_emergency_is_immediate(alerts):
    await seed_builtins()
    await start_grow("cubensis_golden_teacher", "substrate_colonization")  # 75-80 °F
    t0 = local(12)
    with clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 83})  # warning
    with clock(t0 + 60):
        await evaluate_rules("climate-1", {"temp_f": 95})  # emergency
    assert len(alerts["warning"]) == 1
    assert len(alerts["critical"]) == 1


# ── notification flag ──────────────────────────────────────────────────────


def _rule(name, priority, *, notification):
    return AutomationRule(
        name=name, priority=priority, notification=notification,
        condition=threshold("temp_f", "gt", 50),
        action=RuleAction(target="relay-01", channel=f"ch{priority}", state="on"),
    )


async def test_notification_rules_notify_when_they_fire(mock_mqtt, alerts):
    """Priority 20 and up pages critical, below that a warning; each rule
    at most once per window, though it re-fires every cooldown."""
    await start_grow("unit-test-species", "fruiting")
    await create_rule(_rule("tell me", 5, notification=True))
    await create_rule(_rule("page me", 25, notification=True))
    await create_rule(_rule("quiet", 6, notification=False))
    for dt in (0, 61):
        with clock(local(12) + dt):
            await evaluate_rules("climate-1", {"temp_f": 60})
    assert len(_cmds(mock_mqtt, "/cmd/ch5")) == 2, "the rule fired on both frames"
    assert [t for t, _ in alerts["warning"]] == ["Rule fired: tell me"]
    assert [t for t, _ in alerts["critical"]] == ["Rule fired: page me"]


async def test_rule_notification_is_sent_outside_the_actuator_lock(mock_mqtt, monkeypatch):
    """ntfy is an HTTP call (5 s timeout); a safety ceiling tripping on the
    same actuator must not wait behind it."""
    held = []

    async def _warning(title, message, dedup_key=None, **kw):
        held.append(any(lock.locked() for lock in engine._actuator_locks.values()))

    monkeypatch.setattr(engine, "notify_warning", _warning)
    await start_grow("unit-test-species", "fruiting")
    await create_rule(_rule("tell me", 5, notification=True))
    await evaluate_rules("climate-1", {"temp_f": 60})
    assert held == [False]


# ── CO2 Hard Ceiling is species/phase/container independent ────────────────


def _pages(alerts):
    return alerts["co2"] + [t for t, _ in alerts["critical"]]


async def test_co2_hard_ceiling_pages_once(mock_mqtt, alerts):
    """It vents with no active session at all, and the life-safety CO2 page
    and the rule's own notification are one event."""
    await _seed_all()
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
    assert _pages(alerts) == [45000]


async def test_co2_hard_ceiling_vents_a_sealed_colonization_closet(mock_mqtt, alerts):
    await _seed_all()
    await start_grow("cubensis_golden_teacher", "substrate_colonization", container_type="grow_bag")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
    assert alerts["co2"] or alerts["critical"]


async def test_emergency_co2_exhaust_pages_once(mock_mqtt, alerts):
    await _seed_all()
    await start_grow("cubensis_golden_teacher", "fruiting")  # co2_max 800 → emergency > 1800
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 2500})
    assert "on" in [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")]
    assert _pages(alerts) == [2500]


async def test_undelivered_co2_exhaust_still_pages(mock_mqtt, alerts):
    """The CO2 page says CO2 is high; only the rule's page says the exhaust
    command never went out."""
    mock_mqtt.mock.return_value = False
    await _seed_all()
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert alerts["co2"] == [45000]
    assert [m for t, m in alerts["critical"] if "CO2 Hard Ceiling" in t and "NOT delivered" in m]


@pytest.mark.parametrize("co2,trips", [(40000, True), (39999, False)])
async def test_a_saturated_co2_sensor_trips_the_life_safety_backstop(mock_mqtt, alerts, co2, trips):
    """The SCD30 / SCD4x report a saturated reading as exactly 40000 ppm, so
    the level is reached AT 40000 ("above 40000" could never trip); below it,
    with no grow, nothing does."""
    await _seed_all()
    await evaluate_rules("climate-1", {"co2_ppm": co2})
    if trips:
        assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
        assert alerts["co2"] == [40000]
        assert [e for e, _ in alerts["forward"]] == ["co2_alert"]
    else:
        assert mock_mqtt == []
        assert alerts["co2"] == [] and alerts["forward"] == []


async def test_a_climb_to_the_life_safety_level_pages_inside_the_stage_window(mock_mqtt, alerts):
    """A stage CO2 page must not hold back the page for a climb to a level
    dangerous to people; the Hard Ceiling's own notice stays covered by it."""
    await _seed_all()
    await start_grow("blue_oyster", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 3000})
    with clock(local(12, 2)):
        await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert alerts["co2"] == [3000, 45000]
    assert [kw["life_safety"] for _, node, kw in alerts["co2_pages"]] == [False, True]
    assert {node for _, node, _ in alerts["co2_pages"]} == {"climate-1"}
    assert [d["co2_ppm"] for e, d in alerts["forward"] if e == "co2_alert"] == [3000, 45000]
    assert not [t for t, _ in alerts["critical"] if "CO2 Hard Ceiling" in t]
    with clock(local(12, 4)):  # the same reading again pages nothing new
        await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert alerts["co2"] == [3000, 45000]


@pytest.mark.parametrize("ntfy_down", ["answers no", "raises"])
async def test_an_undelivered_co2_page_is_retried_without_reforwarding(monkeypatch, ntfy_down):
    pages: list[int] = []
    forwards: list[str] = []

    async def _co2(ppm, node_id=None, **kw):
        pages.append(ppm)
        if len(pages) == 1:  # ntfy down for the first attempt
            if ntfy_down == "raises":
                raise ConnectionError("ntfy unreachable")
            return False
        return True

    async def _forward(event_type, data):
        forwards.append(event_type)

    monkeypatch.setattr(engine, "co2_alert", _co2)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    for _ in range(3):
        await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert pages == [45000, 45000]  # retried once, then delivered
    assert forwards == ["co2_alert"]


# ── redundant cutoffs ──────────────────────────────────────────────────────


async def test_cutoff_for_an_unpaired_plug_writes_nothing(mock_mqtt):
    await _seed_all()
    await start_grow("cubensis_golden_teacher", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"humidity": 88})
    assert await _statuses("Dehumidify Cutoff") == []


async def test_cutoff_is_not_resent_or_logged_while_the_plug_is_known_off(mock_mqtt, mock_mqtt_raw):
    """A plug reporting itself back ON re-arms the OFF at once:
    tests/test_smart_plug_transport.py."""
    await _seed_all()
    await _pair_plug("dehumidifier", "d1")
    await start_grow("cubensis_golden_teacher", "fruiting")
    t0 = local(12)
    with clock(t0):
        await evaluate_rules("climate-1", {"humidity": 88})
    with clock(t0 + 61):
        await evaluate_rules("climate-1", {"humidity": 88})
    assert _plug_cmds(mock_mqtt_raw, "d1") == ["off"]
    assert await _statuses("Dehumidify Cutoff") == ["sent"]


def test_dehumidify_cutoff_does_not_log_to_the_session():
    rule = next(r for r in BUILTIN_RULES if r.name == "Dehumidify Cutoff")
    assert rule.log_to_session is False


# ── cron catch-up ──────────────────────────────────────────────────────────


async def test_cron_rule_fires_when_frames_straddle_the_matching_minute(mock_mqtt):
    """Frames at 12:19:59.6 and 12:21:00.3 straddle 12:20: it fires once,
    and not again at 12:21:59. (The minute arithmetic:
    tests/test_automation_scheduling.py.)"""
    await start_grow("unit-test-species", "fruiting")
    await create_rule(AutomationRule(
        name="cron heater",
        condition=RuleCondition(type=ConditionType.SCHEDULE,
                                schedule=ScheduleCondition(cron="*/20 * * * *")),
        action=RuleAction(target="relay-01", channel="heater", state="on"),
        cooldown_seconds=0,
    ))
    for ts in (local(12, 19, 59.6), local(12, 21, 0.3), local(12, 21, 59)):
        with clock(ts):
            await evaluate_rules("climate-1", {"temp_f": 60})
    assert len(_cmds(mock_mqtt, "/cmd/heater")) == 1


# ── reishi growth_form ─────────────────────────────────────────────────────


async def test_antler_reishi_keeps_elevated_co2_while_fruiting(mock_mqtt):
    await _seed_all()
    await start_grow("reishi", "fruiting", growth_form="antler")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 1000})
    fae = [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")]
    assert "on" not in fae, "antler form vented by the conk (fruiting) CO2 ceiling"


async def test_conk_reishi_gets_fresh_air_during_primordia(mock_mqtt):
    await _seed_all()
    await start_grow("reishi", "primordia_induction", growth_form="conk")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 1000})
    fae = [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")]
    assert "off" not in fae
    assert "on" in fae


# ── per-chamber session + node resolution ──────────────────────────────────


async def test_node_is_evaluated_against_its_own_chambers_session(mock_mqtt, mock_mqtt_raw, alerts):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    now = time.time()
    await register_node("relay-a", "relay", last_seen=now - 300)
    await register_node("relay-b", "relay", last_seen=now)  # seen most recently
    a = await chamber("A", ["climate-a", "relay-a"])
    b = await chamber("B", ["climate-b", "relay-b"])
    sa = await start_grow("cubensis_golden_teacher", "substrate_colonization", chamber_id=a)
    sb = await start_grow("lions_mane", "fruiting", chamber_id=b)
    async with get_db() as db:  # B is the newest active session
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (now - 100, sa["id"]))
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (now, sb["id"]))
        await db.commit()
    await create_rule(make_rule(RuleAction(target="relay-01", channel="heater", state="on"),
                                condition=threshold("temp_f", "gt", 70), name="relay probe",
                                rule_id=None, priority=1))
    with clock(local(12)):
        await evaluate_rules("climate-a", {"temp_f": 78})
    assert "on" not in _plug_cmds(mock_mqtt_raw, "c1"), "chamber B's 68 °F ceiling applied to A"
    assert not [e for e, _ in alerts["forward"] if e.startswith("temperature")]
    assert [t for t, _ in mock_mqtt if t.endswith("/cmd/heater")] == ["sporeprint/relay-a/cmd/heater"]


async def test_chambered_node_drives_a_session_created_without_chamber_id(
        mock_mqtt, mock_mqtt_raw, alerts):
    """A chamber lists the node but the running session carries no chamber_id
    (a pre-migration session, an API or cloud session_start that omitted it).
    The grow must still be managed — heater on, stage alert paged."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    await chamber("Closet", ["climate-1"])
    await start_grow("cubensis_golden_teacher", "fruiting")
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]
    assert alerts["critical"]


async def test_chambered_node_drives_the_session_its_chamber_links(
        mock_mqtt, mock_mqtt_raw, alerts):
    """PATCH /api/chambers links a session only through chambers.active_session_id."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    cid = await chamber("Closet", ["climate-1"])
    s = await start_grow("cubensis_golden_teacher", "fruiting")
    # A newer unbound session whose band (55-65 °F) is happy at 60 °F: the
    # link, not recency, decides which grow this chamber runs.
    await start_grow("blue_oyster", "fruiting")
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = created_at - 100 WHERE id = ?", (s["id"],))
        await db.execute("UPDATE chambers SET active_session_id = ? WHERE id = ?", (s["id"], cid))
        await db.commit()
    with clock(local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]
    assert alerts["critical"]


async def test_chambered_node_never_borrows_another_chambers_session(
        mock_mqtt, mock_mqtt_raw, alerts):
    """Chamber A has no grow; chamber B's sessions (bound by chamber_id, or
    linked only through B's active_session_id) are not A's."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    await chamber("A", ["climate-a"])
    b = await chamber("B", ["climate-b"])
    await start_grow("cubensis_golden_teacher", "fruiting", chamber_id=b)
    linked = await start_grow("cubensis_golden_teacher", "fruiting")
    async with get_db() as db:
        await db.execute("UPDATE chambers SET active_session_id = ? WHERE id = ?", (linked["id"], b))
        await db.commit()
    with clock(local(12)):
        await evaluate_rules("climate-a", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == []
    assert not alerts["critical"] and not alerts["forward"]


# ── sealed containers ──────────────────────────────────────────────────────


@pytest.mark.parametrize("container,phase,sealed", [
    ("bulk_bag", "substrate_colonization", True),   # under its filter patch until it fruits
    ("bulk_bag", "fruiting", False),
    ("grow_bag", "browning", False),                # a shiitake block leaves its bag to brown
    ("grain_jar", "fruiting", True),                # a culture vessel never opens in-chamber
    ("Monotub", "substrate_colonization", False),   # the substrate is in the sensed air
    (None, "substrate_colonization", False),        # unknown: never over-gate
])
def test_which_containers_keep_the_substrate_out_of_the_chambers_air(container, phase, sealed):
    assert _container_is_sealed(container, phase) is sealed
