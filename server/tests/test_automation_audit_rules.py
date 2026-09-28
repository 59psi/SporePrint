"""Automation engine — rule selection, arbitration and alerting (hardware audit).

One section per audit finding. Each test drives the real engine
(``evaluate_rules``) against a temp DB with real species profiles and, where
the finding is about the shipped behaviour, the real seeded rule templates:

- srv-auto#4 / srv-rest#2  species-scoped rules never fired (hyphen vs underscore ids)
- srv-auto#5              no per-actuator arbitration (lowest priority sent last)
- srv-auto#7              Scheduled FAE ran in 'passive' FAE phases
- srv-auto#8              a phase the profile doesn't define disabled everything
- srv-auto#9              emergency alerts every frame; sealed containers paged on RH/CO2
- srv-auto#15             the rule `notification` flag was never read
- srv-auto#16             CO2 Hard Ceiling needed a session / open container / FAE phase
- srv-auto#18             cutoffs re-sent OFF every minute (and logged each one)
- srv-auto#19             cron only fired when a frame landed in the matching minute
- srv-auto#21 / srv-rest#20  reishi growth_form (antler vs conk) was never read
- srv-auto#22             every node was evaluated against the newest session
- srv-auto#29             bulk_bag wasn't sealed during colonization
- srv-auto#30             plug command endpoint reported 'sent' for a no-op
"""

import json
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import _container_is_sealed, _eval_schedule, evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ScheduleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule, seed_builtin_rules, serialize_rule_data
from app.automation.smart_plugs import register_plug
from app.automation.templates import BUILTIN_RULES, LEGACY_BUILTIN_RULES
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins

_real_localtime = time.localtime


def _local(hour, minute=0, second=0.0):
    """Epoch seconds for today-ish (a fixed Monday) at a LOCAL clock time."""
    return time.mktime((2026, 7, 13, hour, minute, 0, 0, 0, -1)) + second


def _clock(ts):
    """Freeze the engine's wall clock (time.time and localtime) at `ts`."""
    return patch.multiple(
        time,
        time=lambda: ts,
        localtime=lambda t=None: _real_localtime(ts if t is None else t),
    )


@pytest.fixture(autouse=True)
def _reset_pause_state():
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


@pytest.fixture()
def alerts(monkeypatch):
    """Record every alert the engine emits (ntfy tiers + cloud forward)."""
    rec = {"critical": [], "warning": [], "co2": [], "forward": []}

    async def _critical(title, message, tags=None, **kw):
        rec["critical"].append((title, message))

    async def _warning(title, message, dedup_key=None, **kw):
        rec["warning"].append((title, message))

    async def _co2(ppm):
        rec["co2"].append(ppm)

    async def _forward(event_type, data):
        rec["forward"].append((event_type, data))

    monkeypatch.setattr(engine, "notify_critical", _critical)
    monkeypatch.setattr(engine, "notify_warning", _warning)
    monkeypatch.setattr(engine, "co2_alert", _co2)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    return rec


async def _session(species, phase, **kw):
    return await create_session(SessionCreate(
        name=f"{species}-{phase}", species_profile_id=species,
        substrate="test", current_phase=phase, **kw,
    ))


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


async def _register_node(node_id, node_type, last_seen):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen) VALUES (?, ?, ?, ?)",
            (node_id, node_type, json.dumps([node_type]), last_seen),
        )
        await db.commit()


async def _firings(name):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT status FROM automation_firings WHERE rule_name = ?", (name,)
        )
        return [r["status"] for r in await cursor.fetchall()]


# ── srv-auto#4 / srv-rest#2 — species-scoped rules ─────────────────────────


async def test_species_rule_fires_for_session_created_with_underscored_id(mock_mqtt):
    """create_session stores 'cordyceps-militaris'; the template says
    'cordyceps_militaris'. The rule must still apply."""
    await _seed_all()
    await _session("cordyceps_militaris", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 64})
    scenes = [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")]
    assert "cordyceps_blue" in scenes


async def test_lions_mane_night_cool_is_selected(mock_mqtt, mock_mqtt_raw):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await _session("lions_mane", "primordia_induction")
    with _clock(_local(23)):
        await evaluate_rules("climate-1", {"temp_f": 63})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on"]


def test_coverage_species_gate_tolerates_separator_drift():
    from app.automation.coverage import _rule_applies

    rule = AutomationRule(
        name="x", applies_to_species=["lions_mane"],
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=1)),
        action=RuleAction(target="relay-01", channel="fae"),
    )
    assert _rule_applies(rule, "lions-mane", "fruiting")
    assert _rule_applies(rule, "lions_mane", "fruiting")
    assert not _rule_applies(rule, "reishi", "fruiting")


# ── srv-auto#5 — per-actuator arbitration ──────────────────────────────────


async def test_cordyceps_blue_is_not_overwritten_by_the_generic_photoperiod(mock_mqtt):
    await _seed_all()
    await _session("cordyceps_militaris", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 64})
    with _clock(_local(12, 40)):  # Photoperiod — Lights On's 1800 s cooldown is over
        await evaluate_rules("climate-1", {"temp_f": 64})
    scenes = [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")]
    assert scenes == ["cordyceps_blue"]


async def test_cordyceps_dark_period_still_goes_dark(mock_mqtt):
    await _seed_all()
    await _session("cordyceps_militaris", "fruiting")  # 16/8 from 06:00 → dark at 23:00
    with _clock(_local(23)):
        await evaluate_rules("climate-1", {"temp_f": 64})
    scenes = [p["scene"] for p in _cmds(mock_mqtt, "/cmd/scene")]
    assert scenes == ["colonization_dark"]


async def test_higher_priority_off_holds_the_actuator_across_frames(mock_mqtt):
    await seed_builtins()
    await _session("cubensis_golden_teacher", "fruiting")
    await create_rule(AutomationRule(
        name="floor", priority=12,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="co2_ppm", operator="lt", value=1000)),
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
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"co2_ppm": 900})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off"]
    with _clock(t0 + 90):  # floor is in cooldown but its condition still holds
        await evaluate_rules("climate-1", {"co2_ppm": 900})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off"]
    with _clock(t0 + 120):  # floor released → the cycle may run
        await evaluate_rules("climate-1", {"co2_ppm": 1200})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["off", "on"]


async def test_emergency_exhaust_is_not_downgraded_by_humidity_vent(mock_mqtt):
    await _seed_all()
    await _session("cubensis_golden_teacher", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 45000, "humidity": 97})
    exhaust = _cmds(mock_mqtt, "/cmd/exhaust")
    assert len(exhaust) == 1
    assert exhaust[0]["pwm"] == 255


async def test_night_cool_holds_the_cooler_against_cooling_cutoff(mock_mqtt, mock_mqtt_raw):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await _session("lions_mane", "primordia_induction")
    t0 = _local(23)
    for dt in (0, 61, 122):
        with _clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 63})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on"]
    with _clock(t0 + 183):  # swing target reached → the cutoff may switch it off
        await evaluate_rules("climate-1", {"temp_f": 59.5})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on", "off"]


async def test_pre_cool_does_not_chill_a_chamber_already_in_the_lower_half(mock_mqtt, mock_mqtt_raw):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await _session("cubensis_golden_teacher", "fruiting")  # 72-76 °F
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 72.5, "forecast_high_f": 97})
    assert "on" not in _plug_cmds(mock_mqtt_raw, "c1")


async def test_hot_forecast_cools_a_warm_chamber_without_the_cutoff_cancelling_it(
    mock_mqtt, mock_mqtt_raw, alerts,
):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    await _session("cubensis_golden_teacher", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 75.5, "forecast_high_f": 97})
    assert _plug_cmds(mock_mqtt_raw, "c1") == ["on"]
    assert any("Heat Wave Warning" in t for t, _ in alerts["warning"])


async def test_legacy_builtins_upgrade_to_the_current_templates():
    current = {r.name: r for r in BUILTIN_RULES}
    async with get_db() as db:
        for legacy in LEGACY_BUILTIN_RULES.values():
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
                "VALUES (?, ?, 1, ?, ?)",
                (legacy.name, legacy.description, legacy.priority, serialize_rule_data(legacy)),
            )
        await db.commit()
    await seed_builtin_rules()
    async with get_db() as db:
        cursor = await db.execute("SELECT name, priority, rule_data FROM automation_rules")
        rows = {r["name"]: r for r in await cursor.fetchall()}
    for name in LEGACY_BUILTIN_RULES:
        assert rows[name]["priority"] == current[name].priority, name
        assert json.loads(rows[name]["rule_data"]) == json.loads(serialize_rule_data(current[name])), name
    for name in ("Lion's Mane Night Cool", "Cordyceps Blue Light", "Pre-cool for Hot Forecast",
                 "Heat Wave Warning", "Dehumidify Cutoff"):
        assert name in LEGACY_BUILTIN_RULES


async def test_operator_edited_legacy_rule_is_left_alone():
    legacy = LEGACY_BUILTIN_RULES["Lion's Mane Night Cool"]
    edited = legacy.model_copy(update={"cooldown_seconds": 900})
    async with get_db() as db:
        await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
            "VALUES (?, ?, 1, ?, ?)",
            (edited.name, edited.description, edited.priority, serialize_rule_data(edited)),
        )
        await db.commit()
    await seed_builtin_rules()
    async with get_db() as db:
        cursor = await db.execute("SELECT priority, rule_data FROM automation_rules")
        row = await cursor.fetchone()
    assert row["priority"] == legacy.priority
    assert json.loads(row["rule_data"])["cooldown_seconds"] == 900


async def test_edited_legacy_rule_is_flagged_at_boot(caplog):
    """An edited copy keeps its old logic — e.g. a forecast-only Pre-cool that,
    under priority arbitration, now holds the cooler against the Cutoff — so
    the operator is told it was not upgraded. Upgraded copies stay quiet."""
    legacy = LEGACY_BUILTIN_RULES["Pre-cool for Hot Forecast"]
    edited = legacy.model_copy(update={"cooldown_seconds": 900})
    current = {r.name: r for r in BUILTIN_RULES}["Heat Wave Warning"]
    async with get_db() as db:
        for rule in (edited, current):
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
                "VALUES (?, ?, 1, ?, ?)",
                (rule.name, rule.description, rule.priority, serialize_rule_data(rule)),
            )
        await db.commit()
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    flagged = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(flagged) == 1 and "Pre-cool for Hot Forecast" in flagged[0]


# ── srv-auto#7 — Scheduled FAE only where the profile schedules FAE ────────


async def test_scheduled_fae_does_not_run_in_a_passive_phase(mock_mqtt):
    await _seed_all()
    await _session("king_trumpet", "primordia_induction")  # passive, CO2 held 1000-2000
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 1500})
    assert [p for p in _cmds(mock_mqtt, "/cmd/fae") if p["state"] == "on"] == []


async def test_scheduled_fae_still_runs_in_a_continuous_phase(mock_mqtt):
    await _seed_all()
    await _session("lions_mane", "primordia_induction")  # continuous
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 400})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")] == ["on"]


# ── srv-auto#8 — phases the profile doesn't define ─────────────────────────


async def test_missing_primordia_phase_falls_back_to_fruiting(mock_mqtt, mock_mqtt_raw, alerts):
    await _seed_all()
    await _pair_plug("heater", "h1")
    await _session("pink_oyster", "primordia_induction")  # pink oyster has no primordia phase
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 45})
    assert alerts["critical"], "a 45 °F pink oyster (dies < 40 °F) must page"
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]


async def test_missing_rest_phase_falls_back_to_fruiting(mock_mqtt, alerts):
    await _seed_all()
    await _session("lions_mane", "rest")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 90})
    assert any(e == "temperature_alert" for e, _ in alerts["forward"])


# ── srv-auto#9 — alert dedup + sealed containers ───────────────────────────


async def test_sealed_grow_bag_does_not_page_on_room_humidity(alerts):
    await seed_builtins()
    await _session("cubensis_golden_teacher", "substrate_colonization", container_type="grow_bag")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"humidity": 45, "temp_f": 77})
    assert alerts["critical"] == [] and alerts["warning"] == [] and alerts["forward"] == []


async def test_persisting_emergency_pages_once_per_window(alerts):
    await seed_builtins()
    await _session("cubensis_golden_teacher", "substrate_colonization")
    t0 = _local(12)
    for dt in (0, 60, 120):
        with _clock(t0 + dt):
            await evaluate_rules("climate-1", {"temp_f": 95})
    assert len(alerts["critical"]) == 1
    assert [e for e, _ in alerts["forward"]] == ["temperature_alert"]
    with _clock(t0 + 16 * 60):  # window over → the still-hot closet re-pages
        await evaluate_rules("climate-1", {"temp_f": 95})
    assert len(alerts["critical"]) == 2


async def test_escalation_from_warning_to_emergency_is_immediate(alerts):
    await seed_builtins()
    await _session("cubensis_golden_teacher", "substrate_colonization")  # 75-80 °F
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"temp_f": 83})  # warning
    with _clock(t0 + 60):
        await evaluate_rules("climate-1", {"temp_f": 95})  # emergency
    assert len(alerts["warning"]) == 1
    assert len(alerts["critical"]) == 1


# ── srv-auto#15 — notification flag ────────────────────────────────────────


def _rule(name, priority, *, notification):
    return AutomationRule(
        name=name, priority=priority, notification=notification,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=50)),
        action=RuleAction(target="relay-01", channel=f"ch{priority}", state="on"),
    )


async def test_notification_rules_notify_when_they_fire(mock_mqtt, alerts):
    await _session("unit-test-species", "fruiting")
    await create_rule(_rule("tell me", 5, notification=True))
    await create_rule(_rule("page me", 25, notification=True))
    await create_rule(_rule("quiet", 6, notification=False))
    await evaluate_rules("climate-1", {"temp_f": 60})
    assert [t for t, _ in alerts["warning"] if "tell me" in t]
    assert [t for t, _ in alerts["critical"] if "page me" in t]
    assert not [t for t, _ in alerts["warning"] + alerts["critical"] if "quiet" in t]


async def test_rule_notification_is_sent_outside_the_actuator_lock(mock_mqtt, monkeypatch):
    """ntfy is an HTTP call (5 s timeout); a safety ceiling tripping on the
    same actuator must not wait behind it."""
    held = []

    async def _warning(title, message, dedup_key=None, **kw):
        held.append(any(lock.locked() for lock in engine._actuator_locks.values()))

    monkeypatch.setattr(engine, "notify_warning", _warning)
    await _session("unit-test-species", "fruiting")
    await create_rule(_rule("tell me", 5, notification=True))
    await evaluate_rules("climate-1", {"temp_f": 60})
    assert held == [False]


# ── srv-auto#16 — CO2 Hard Ceiling is species/phase/container independent ──


async def test_co2_hard_ceiling_vents_with_no_active_session(mock_mqtt, alerts):
    await _seed_all()
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    exhaust = _cmds(mock_mqtt, "/cmd/exhaust")
    assert [p["state"] for p in exhaust] == ["on"]
    assert alerts["co2"] or alerts["critical"]


async def test_co2_hard_ceiling_vents_a_sealed_colonization_closet(mock_mqtt, alerts):
    await _seed_all()
    await _session("cubensis_golden_teacher", "substrate_colonization", container_type="grow_bag")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
    assert alerts["co2"] or alerts["critical"]


def _pages(alerts):
    return alerts["co2"] + [t for t, _ in alerts["critical"]]


async def test_co2_hard_ceiling_pages_once(mock_mqtt, alerts):
    """The life-safety CO2 page and the rule's own notification are one event."""
    await _seed_all()
    await evaluate_rules("climate-1", {"co2_ppm": 45000})
    assert [p["state"] for p in _cmds(mock_mqtt, "/cmd/exhaust")] == ["on"]
    assert _pages(alerts) == [45000]


async def test_emergency_co2_exhaust_pages_once(mock_mqtt, alerts):
    await _seed_all()
    await _session("cubensis_golden_teacher", "fruiting")  # co2_max 800 → emergency > 1800
    with _clock(_local(12)):
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


# ── srv-auto#18 — redundant cutoffs ────────────────────────────────────────


async def test_cutoff_for_an_unpaired_plug_writes_nothing(mock_mqtt):
    await _seed_all()
    await _session("cubensis_golden_teacher", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"humidity": 88})
    assert await _firings("Dehumidify Cutoff") == []


async def test_cutoff_is_not_resent_while_the_plug_is_known_off(mock_mqtt, mock_mqtt_raw):
    await _seed_all()
    await _pair_plug("dehumidifier", "d1")
    await _session("cubensis_golden_teacher", "fruiting")
    t0 = _local(12)
    with _clock(t0):
        await evaluate_rules("climate-1", {"humidity": 88})
    with _clock(t0 + 61):
        await evaluate_rules("climate-1", {"humidity": 88})
    assert _plug_cmds(mock_mqtt_raw, "d1") == ["off"]
    assert await _firings("Dehumidify Cutoff") == ["sent"]
    # The plug reports it was switched ON outside automation → OFF goes out again.
    async with get_db() as db:
        await db.execute("UPDATE smart_plugs SET last_state = 'on' WHERE plug_id = 'plug-d1'")
        await db.commit()
    with _clock(t0 + 122):
        await evaluate_rules("climate-1", {"humidity": 88})
    assert _plug_cmds(mock_mqtt_raw, "d1") == ["off", "off"]


def test_dehumidify_cutoff_does_not_log_to_the_session():
    rule = next(r for r in BUILTIN_RULES if r.name == "Dehumidify Cutoff")
    assert rule.log_to_session is False


# ── srv-auto#19 — cron catch-up ────────────────────────────────────────────


def test_cron_matches_a_minute_between_two_frames():
    sched = ScheduleCondition(cron="*/20 * * * *")
    with _clock(_local(12, 21, 0.3)):
        assert _eval_schedule(sched, None, None, cron_since=_local(12, 19, 59.6)) is True
        assert _eval_schedule(sched, None, None, cron_since=_local(12, 20, 5)) is False


async def test_cron_rule_fires_when_frames_straddle_the_matching_minute(mock_mqtt):
    await _session("unit-test-species", "fruiting")
    await create_rule(AutomationRule(
        name="cron heater",
        condition=RuleCondition(type=ConditionType.SCHEDULE,
                                schedule=ScheduleCondition(cron="*/20 * * * *")),
        action=RuleAction(target="relay-01", channel="heater", state="on"),
        cooldown_seconds=0,
    ))
    for ts in (_local(12, 19, 59.6), _local(12, 21, 0.3), _local(12, 21, 59)):
        with _clock(ts):
            await evaluate_rules("climate-1", {"temp_f": 60})
    assert len(_cmds(mock_mqtt, "/cmd/heater")) == 1


# ── srv-auto#21 / srv-rest#20 — reishi growth_form ─────────────────────────


async def test_antler_reishi_keeps_elevated_co2_while_fruiting(mock_mqtt):
    await _seed_all()
    await _session("reishi", "fruiting", growth_form="antler")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 1000})
    fae = [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")]
    assert "on" not in fae, "antler form vented by the conk (fruiting) CO2 ceiling"


async def test_conk_reishi_gets_fresh_air_during_primordia(mock_mqtt):
    await _seed_all()
    await _session("reishi", "primordia_induction", growth_form="conk")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"co2_ppm": 1000})
    fae = [p["state"] for p in _cmds(mock_mqtt, "/cmd/fae")]
    assert "off" not in fae
    assert "on" in fae


# ── srv-auto#22 — per-chamber session + node resolution ────────────────────


async def _chamber(name, node_ids):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES (?, ?)", (name, json.dumps(node_ids)),
        )
        await db.commit()
        return cursor.lastrowid


async def test_node_is_evaluated_against_its_own_chambers_session(mock_mqtt, mock_mqtt_raw, alerts):
    await _seed_all()
    await _pair_plug("cooler", "c1")
    now = time.time()
    await _register_node("relay-a", "relay", now - 300)
    await _register_node("relay-b", "relay", now)  # seen most recently
    a = await _chamber("A", ["climate-a", "relay-a"])
    b = await _chamber("B", ["climate-b", "relay-b"])
    sa = await _session("cubensis_golden_teacher", "substrate_colonization", chamber_id=a)
    sb = await _session("lions_mane", "fruiting", chamber_id=b)
    async with get_db() as db:  # B is the newest active session
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (now - 100, sa["id"]))
        await db.execute("UPDATE sessions SET created_at = ? WHERE id = ?", (now, sb["id"]))
        await db.commit()
    await create_rule(AutomationRule(
        name="relay probe", priority=1,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=70)),
        action=RuleAction(target="relay-01", channel="heater", state="on"),
    ))
    with _clock(_local(12)):
        await evaluate_rules("climate-a", {"temp_f": 78})
    assert "on" not in _plug_cmds(mock_mqtt_raw, "c1"), "chamber B's 68 °F ceiling applied to A"
    assert not [e for e, _ in alerts["forward"] if e.startswith("temperature")]
    assert [t for t, _ in mock_mqtt if t.endswith("/cmd/heater")] == ["sporeprint/relay-a/cmd/heater"]


async def test_unassigned_node_still_drives_the_newest_session(mock_mqtt):
    """Single-closet installs (no chambers) keep working unchanged."""
    await _session("unit-test-species", "fruiting")
    await create_rule(_rule("probe", 1, notification=False))
    await evaluate_rules("climate-1", {"temp_f": 60})
    assert _cmds(mock_mqtt, "/cmd/ch1")


async def test_chambered_node_drives_a_session_created_without_chamber_id(
        mock_mqtt, mock_mqtt_raw, alerts):
    """A chamber lists the node but the running session carries no chamber_id
    (a pre-migration session, an API or cloud session_start that omitted it).
    The grow must still be managed — heater on, stage alert paged."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    await _chamber("Closet", ["climate-1"])
    await _session("cubensis_golden_teacher", "fruiting")
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]
    assert alerts["critical"]


async def test_chambered_node_drives_the_session_its_chamber_links(
        mock_mqtt, mock_mqtt_raw, alerts):
    """PATCH /api/chambers links a session only through chambers.active_session_id."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    cid = await _chamber("Closet", ["climate-1"])
    s = await _session("cubensis_golden_teacher", "fruiting")
    # A newer unbound session whose band (55-65 °F) is happy at 60 °F: the
    # link, not recency, decides which grow this chamber runs.
    await _session("blue_oyster", "fruiting")
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = created_at - 100 WHERE id = ?", (s["id"],))
        await db.execute("UPDATE chambers SET active_session_id = ? WHERE id = ?", (s["id"], cid))
        await db.commit()
    with _clock(_local(12)):
        await evaluate_rules("climate-1", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == ["on"]
    assert alerts["critical"]


async def test_chambered_node_never_borrows_another_chambers_session(
        mock_mqtt, mock_mqtt_raw, alerts):
    """Chamber A has no grow; chamber B's sessions (bound by chamber_id, or
    linked only through B's active_session_id) are not A's."""
    await _seed_all()
    await _pair_plug("heater", "h1")
    await _chamber("A", ["climate-a"])
    b = await _chamber("B", ["climate-b"])
    await _session("cubensis_golden_teacher", "fruiting", chamber_id=b)
    linked = await _session("cubensis_golden_teacher", "fruiting")
    async with get_db() as db:
        await db.execute("UPDATE chambers SET active_session_id = ? WHERE id = ?", (linked["id"], b))
        await db.commit()
    with _clock(_local(12)):
        await evaluate_rules("climate-a", {"temp_f": 60})
    assert _plug_cmds(mock_mqtt_raw, "h1") == []
    assert not alerts["critical"] and not alerts["forward"]


# ── srv-auto#29 — bulk bags are sealed until fruiting ──────────────────────


def test_bulk_bag_is_sealed_until_fruiting():
    assert _container_is_sealed("bulk_bag", "substrate_colonization") is True
    assert _container_is_sealed("bulk_bag", "fruiting") is False


# ── srv-auto#30 — plug command endpoint is honest ──────────────────────────


def test_plug_command_for_an_unpaired_plug_is_an_error(client):
    r = client.post("/api/automation/plugs/plug-nope/command", json={"state": "on"})
    assert r.status_code == 409
