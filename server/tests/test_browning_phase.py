"""Shiitake browning (popcorning) — a GrowPhase of its own, end to end.

CLAUDE.md §4b: after colonization a shiitake block, out of its bag, develops a
brown outer skin and is NOT ready to fruit until browning completes (60-70 °F,
70-80 % RH, moderate CO2, indirect light, passive FAE, 7-14 d). The pinning
trigger is a manual cold-water soak (35-50 °F, 12-24 h) the system reminds
about and logs. Covered here:

- the enum / lifecycle order and the shiitake profile's browning setpoints
- phase validation: a profile without browning params refuses it (422)
- the suggested transitions substrate_colonization → browning → primordia_induction
- the cold-soak reminder: GET /next-phase, the advance log, the daily check
- automation: the open-substrate rules run in browning, the unbagged block is
  not "sealed", and existing installs upgrade their pre-browning rule copies
- vision: browning is normal for shiitake (prompt), browning_percent → alert
- transcript + planner pick the phase up
"""

import json
import time
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
import app.sessions.service as sessions_service
from app.automation.coverage import compute_coverage
from app.automation.engine import _container_is_sealed, evaluate_rules
from app.automation.service import seed_builtin_rules, serialize_rule_data
from app.automation.smart_plugs import register_plug
from app.automation.templates import (
    _OPEN_SUBSTRATE_PHASES,
    BUILTIN_RULES,
    PRE_BROWNING_BUILTIN_RULES,
    SUPERSEDED_BUILTIN_RULES,
)
from app.config import settings
from app.db import get_db
from app.planner.service import propose_cycle
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import (
    _PHASE_ORDER,
    InvalidPhaseError,
    advance_phase,
    check_phase_reminders,
    create_session,
    get_events,
    phase_error,
    suggested_next_phase,
)
from app.species.models import GrowPhase
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import get_profile, seed_builtins
from app.transcript.service import export_markdown
from app.vision import service as vision_service
from app.vision.service import (
    _maybe_browning_alert,
    _maybe_colonization_alert,
    analyze_frame_claude,
    browning_guidance,
    browning_signal,
)

_PROFILES = {p.id: p for p in BUILTIN_PROFILES}
_SHIITAKE = _PROFILES["shiitake"]
_SHIITAKE_PHASES = [p.value for p in _SHIITAKE.phases]
_BLUE_PHASES = [p.value for p in _PROFILES["blue_oyster"].phases]


async def _session(species="shiitake", phase="substrate_colonization", **kw) -> dict:
    return await create_session(SessionCreate(
        name=f"{species}-{phase}", species_profile_id=species, current_phase=phase, **kw,
    ))


async def _events(session_id: int, type_: str) -> list[dict]:
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM session_events WHERE session_id = ? AND type = ? ORDER BY id",
            (session_id, type_),
        )).fetchall()
    return [dict(r) for r in rows]


# ── enum, lifecycle order, profile data ───────────────────────────────────


def test_browning_sits_between_colonization_and_the_cold_storage_fork():
    order = [p.value for p in GrowPhase]
    assert order.index("browning") == order.index("substrate_colonization") + 1
    assert order.index("browning") < order.index("primordia_induction")
    # The calendar's order is the enum's order — one lifecycle, not two.
    assert _PHASE_ORDER == order


def test_shiitake_browning_setpoints_match_the_spec():
    b = _SHIITAKE.phases[GrowPhase.BROWNING]
    assert (b.temp_min_f, b.temp_max_f) == (60, 70)
    assert (b.humidity_min, b.humidity_max) == (70, 80)
    assert b.co2_tolerance == "moderate"
    assert b.fae_mode == "passive"
    assert b.light_hours_on > 0 and b.light_spectrum != "none"  # indirect light OK
    assert tuple(b.expected_duration_days) == (7, 14)
    assert "NOT contamination" in b.notes
    soak = b.exit_reminder
    assert "Cold-water soak" in soak and "35-50°F" in soak and "12-24 h" in soak
    # Defined in lifecycle order (coverage and the species page list phases so).
    assert _SHIITAKE_PHASES.index("browning") == _SHIITAKE_PHASES.index("substrate_colonization") + 1


def test_only_shiitake_browns_and_only_browning_owes_an_exit_step():
    assert [p.id for p in BUILTIN_PROFILES if GrowPhase.BROWNING in p.phases] == ["shiitake"]
    owing = [(p.id, ph.value) for p in BUILTIN_PROFILES
             for ph, params in p.phases.items() if params.exit_reminder]
    assert owing == [("shiitake", "browning")]


def test_phase_exit_reminder_is_the_profiles_own_step_only():
    assert "Cold-water soak" in _SHIITAKE.phase_exit_reminder("browning")
    assert _SHIITAKE.phase_exit_reminder("substrate_colonization") is None
    assert _SHIITAKE.phase_exit_reminder("rest") is None  # undefined → no inherited step
    assert _SHIITAKE.phase_exit_reminder("not-a-phase") is None


# ── validation: a profile without browning params refuses the phase ──────


def test_phase_error_refuses_browning_for_a_profile_without_it():
    err = phase_error("browning", _PROFILES["blue_oyster"])
    assert err and "defines no 'browning' phase" in err
    assert phase_error("browning", _SHIITAKE) is None
    assert phase_error("browning", None) is None  # unknown species: name check only


async def test_advance_and_create_refuse_browning_without_params():
    await seed_builtins()
    s = await _session("blue_oyster")
    with pytest.raises(InvalidPhaseError):
        await advance_phase(s["id"], PhaseAdvance(phase="browning"))
    with pytest.raises(InvalidPhaseError):
        await _session("blue_oyster", "browning")


def test_rest_api_answers_422_for_browning_on_a_non_browning_species(client):
    created = client.post("/api/sessions", json={"name": "B", "species_profile_id": "blue-oyster"})
    assert created.status_code == 200
    resp = client.post(f"/api/sessions/{created.json()['id']}/phase", json={"phase": "browning"})
    assert resp.status_code == 422
    assert "browning" in resp.json()["detail"]
    assert client.post("/api/sessions", json={
        "name": "B2", "species_profile_id": "blue-oyster", "current_phase": "browning",
    }).status_code == 422


# ── suggested transitions ─────────────────────────────────────────────────


@pytest.mark.parametrize("container", ["grow_bag", "bulk_bag", "monotub"])
def test_shiitake_block_browns_before_it_pins(container):
    assert suggested_next_phase("substrate_colonization", container,
                                profile_phases=_SHIITAKE_PHASES) == "browning"
    assert suggested_next_phase("browning", container,
                                profile_phases=_SHIITAKE_PHASES) == "primordia_induction"


def test_other_transitions_are_unchanged():
    # A species without browning still goes straight to pinning.
    assert suggested_next_phase("substrate_colonization", "grow_bag",
                                profile_phases=_BLUE_PHASES) == "primordia_induction"
    # Shiitake grain in a jar still parks in cold storage.
    assert suggested_next_phase("grain_colonization", "jar",
                                profile_phases=_SHIITAKE_PHASES) == "cold_storage"
    # With no profile there is nothing to brown on.
    assert suggested_next_phase("substrate_colonization", "grow_bag") == "primordia_induction"
    assert suggested_next_phase("browning", "grow_bag") == "primordia_induction"
    # Cold storage's linear successor did not become browning.
    assert suggested_next_phase("cold_storage", "jar",
                                profile_phases=_SHIITAKE_PHASES) == "primordia_induction"


def test_next_phase_endpoint_walks_shiitake_through_browning_with_the_soak(client):
    sid = client.post("/api/sessions", json={
        "name": "Shii", "species_profile_id": "shiitake", "container_type": "grow_bag",
    }).json()["id"]
    first = client.get(f"/api/sessions/{sid}/next-phase").json()
    assert first["suggested_next_phase"] == "browning"
    assert first["exit_reminder"] is None

    assert client.post(f"/api/sessions/{sid}/phase", json={"phase": "browning"}).status_code == 200
    second = client.get(f"/api/sessions/{sid}/next-phase").json()
    assert second["current_phase"] == "browning"
    assert second["suggested_next_phase"] == "primordia_induction"
    assert "Cold-water soak" in second["exit_reminder"]


# ── the cold-soak log on leaving browning ─────────────────────────────────


async def test_leaving_browning_logs_the_cold_soak_with_the_phase_change():
    await seed_builtins()
    s = await _session(container_type="grow_bag")
    s = await advance_phase(s["id"], PhaseAdvance(phase="browning"))
    snap = s["phase_history"][-1]["params_snapshot"]
    assert snap["humidity_max"] == 80 and snap["exit_reminder"].startswith("Cold-water soak")
    assert await _events(s["id"], "phase_exit_reminder") == []  # entering owes nothing

    await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    [ev] = await _events(s["id"], "phase_exit_reminder")
    assert ev["source"] == "system"
    assert ev["description"].startswith("Leaving browning — Cold-water soak")
    assert json.loads(ev["data"]) == {
        "phase": "browning", "next_phase": "primordia_induction",
        "reminder": _SHIITAKE.phase_exit_reminder("browning"),
    }


async def test_the_soak_reads_before_the_phase_change_it_is_owed_for():
    # 2026-10 audit round 2: the reminder was written after "Phase advanced
    # to primordia induction" in the same second, so the timeline and the
    # transcript listed the soak once the grow was already pinning.
    await seed_builtins()
    s = await _session("shiitake", "browning")
    await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    [soak] = await _events(s["id"], "phase_exit_reminder")
    [step] = await _events(s["id"], "phase_change")
    assert soak["id"] < step["id"]
    assert soak["timestamp"] <= step["timestamp"]
    ordered = [e["type"] for e in await get_events(s["id"])]
    assert ordered.index("phase_exit_reminder") < ordered.index("phase_change")
    capped = [e["type"] for e in await get_events(s["id"], limit=10)]
    assert capped.index("phase_exit_reminder") < capped.index("phase_change")


@pytest.mark.parametrize("target", ["substrate_colonization", "cold_storage", "complete"])
async def test_no_soak_logged_going_back_parking_or_ending(target):
    await seed_builtins()
    s = await _session("shiitake", "browning")
    await advance_phase(s["id"], PhaseAdvance(phase=target))
    assert await _events(s["id"], "phase_exit_reminder") == []


# ── the daily phase reminder offers the soak ──────────────────────────────


@pytest.fixture()
def reminders(monkeypatch):
    rec = {"info": [], "overdue": []}

    async def _info(title, message, dedup_key=None):
        rec["info"].append((title, message, dedup_key))

    async def _overdue(*args):
        rec["overdue"].append(args)

    monkeypatch.setattr(sessions_service, "notify_info", _info)
    monkeypatch.setattr(sessions_service, "phase_reminder", _overdue)
    return rec


async def _age_open_phase(session_id: int, days: float) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (time.time() - days * 86400, session_id),
        )
        await db.commit()


async def test_browning_reminder_offers_the_soak_from_the_minimum_duration(reminders):
    await seed_builtins()
    s = await _session("shiitake", "browning")
    await _age_open_phase(s["id"], 3)
    assert await check_phase_reminders() == 0

    await _age_open_phase(s["id"], 8)
    assert await check_phase_reminders() == 1
    [(title, message, key)] = reminders["info"]
    assert title == "Phase check — shiitake-browning"
    assert message.startswith("Day 8 of browning (7-14 d expected). Once it is complete: Cold-water soak")
    assert message.endswith("Then advance the session.")
    assert key == f"phase-exit:{s['id']}:browning"
    assert reminders["overdue"] == []  # one message, not the generic overdue nudge too


async def test_overrun_browning_still_spells_out_the_soak(reminders):
    await seed_builtins()
    s = await _session("shiitake", "browning")
    await _age_open_phase(s["id"], 20)
    assert await check_phase_reminders() == 1
    [(_, message, _)] = reminders["info"]
    assert message.startswith("Day 20 of browning — past its 7-14 d window.")
    assert "Cold-water soak" in message


# ── automation ────────────────────────────────────────────────────────────


def test_open_substrate_rules_run_in_browning_and_scheduled_fae_does_not():
    by_name = {r.name: r for r in BUILTIN_RULES}
    assert set(PRE_BROWNING_BUILTIN_RULES) == {
        r.name for r in BUILTIN_RULES if "browning" in (r.applies_to_phases or [])
    }
    for name in PRE_BROWNING_BUILTIN_RULES:
        assert by_name[name].applies_to_phases == list(_OPEN_SUBSTRATE_PHASES), name
    assert "browning" not in by_name["Scheduled FAE Cycle"].applies_to_phases  # passive FAE
    assert "browning" not in by_name["Dry Weather Humidity Boost"].applies_to_phases


def test_pre_browning_forms_differ_from_current_only_by_the_browning_gate():
    """Transcription guard: each frozen pre-browning copy must be the current
    rule minus "browning", or an unedited install would never upgrade."""
    current = {r.name: r for r in BUILTIN_RULES}
    for name, old in PRE_BROWNING_BUILTIN_RULES.items():
        assert old.applies_to_phases == ["primordia_induction", "fruiting"], name
        rebuilt = old.model_copy(update={"applies_to_phases": list(_OPEN_SUBSTRATE_PHASES)})
        assert rebuilt.model_dump() == current[name].model_dump(), name


async def _store(rule) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) "
            "VALUES (?, ?, 1, ?, ?)",
            (rule.name, rule.description, rule.priority, serialize_rule_data(rule)),
        )
        await db.commit()


async def test_existing_installs_upgrade_their_pre_browning_copies(caplog):
    for rule in PRE_BROWNING_BUILTIN_RULES.values():
        await _store(rule)
    with caplog.at_level("WARNING", logger="app.automation.service"):
        await seed_builtin_rules()
    # An unedited copy is upgraded quietly — never flagged as operator-edited.
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
    current = {r.name: r for r in BUILTIN_RULES}
    async with get_db() as db:
        rows = await (await db.execute("SELECT name, rule_data FROM automation_rules")).fetchall()
    for row in rows:
        stored = json.loads(row["rule_data"])
        assert stored == json.loads(serialize_rule_data(current[row["name"]])), row["name"]
        assert "browning" in stored["applies_to_phases"]
    # Dehumidify Cutoff has two superseded forms; both upgrade.
    assert len(SUPERSEDED_BUILTIN_RULES["Dehumidify Cutoff"]) == 2


async def test_an_edited_pre_browning_copy_is_left_alone():
    edited = PRE_BROWNING_BUILTIN_RULES["CO2 FAE Trigger"].model_copy(update={"cooldown_seconds": 900})
    await _store(edited)
    await seed_builtin_rules()
    async with get_db() as db:
        row = await (await db.execute("SELECT rule_data FROM automation_rules")).fetchone()
    stored = json.loads(row["rule_data"])
    assert stored["cooldown_seconds"] == 900
    assert stored["applies_to_phases"] == ["primordia_induction", "fruiting"]


def test_an_unbagged_browning_block_is_not_sealed():
    for bag in ("grow_bag", "bag", "bulk_bag"):
        assert _container_is_sealed(bag, "substrate_colonization") is True
        assert _container_is_sealed(bag, "browning") is False
    assert _container_is_sealed("jar", "browning") is True


@pytest.fixture()
def quiet_alerts(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(engine, "notify_critical", _noop)
    monkeypatch.setattr(engine, "notify_warning", _noop)
    monkeypatch.setattr(engine, "co2_alert", _noop)
    monkeypatch.setattr(cloud_service, "forward_event", _noop)


def _clock(ts):
    real_localtime = time.localtime
    return patch.multiple(
        time, time=lambda: ts, localtime=lambda t=None: real_localtime(ts if t is None else t),
    )


async def test_browning_block_gets_dehumidified_and_vented(mock_mqtt, mock_mqtt_raw, quiet_alerts):
    await seed_builtins()
    await seed_builtin_rules()
    await register_plug(plug_id="plug-d1", name="dehumidifier", plug_type="shelly",
                        mqtt_topic_prefix="shellies/d1", device_role="dehumidifier")
    await _session("shiitake", "browning", container_type="grow_bag")
    noon = time.mktime((2026, 7, 13, 12, 0, 0, 0, 0, -1))
    with _clock(noon):
        await evaluate_rules("climate-1", {"temp_f": 65, "humidity": 86, "co2_ppm": 2400})
    assert [p for t, p in mock_mqtt_raw if t == "shellies/d1/relay/0/command"] == ["on"]
    fae = [p for t, p in mock_mqtt if t.endswith("/cmd/fae")]
    assert fae and fae[0]["state"] == "on"  # CO2 over browning's 2000 ppm ceiling


async def test_browning_appears_in_shiitake_automation_coverage():
    await seed_builtins()
    await seed_builtin_rules()
    phases = await compute_coverage(await get_profile("shiitake"))
    entry = next(p for p in phases if p["phase"] == "browning")
    assert entry["requirements"]  # humidity / CO2 / light rules apply there


# ── vision ────────────────────────────────────────────────────────────────


def test_browning_signal_only_judges_the_browning_phase():
    ok, reason = browning_signal("browning", 93)
    assert ok and "93% browned" in reason
    assert browning_signal("browning", 60) == (False, None)
    assert browning_signal("browning", None) == (False, None)
    assert browning_signal("browning", "n/a") == (False, None)
    assert browning_signal("fruiting", 100) == (False, None)


def test_browning_guidance_only_while_browning():
    text = browning_guidance(_SHIITAKE, "browning")
    assert "do NOT report it as contamination" in text
    assert "browning_percent" in text
    assert browning_guidance(_SHIITAKE, "substrate_colonization") == ""
    assert browning_guidance(_PROFILES["blue_oyster"], "browning") == ""
    assert browning_guidance(None, "browning") == ""


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


def _fake_anthropic(capture: dict, reply: dict):
    class _Messages:
        async def create(self, **kwargs):
            capture.update(kwargs)
            return _FakeMessage(json.dumps(reply))

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    return _Client


def _frame(tmp_path, session_id: int) -> dict:
    img = tmp_path / "cam-01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-body")
    return {"id": 1, "session_id": session_id, "node_id": "cam-01", "file_path": str(img)}


async def test_vision_prompt_knows_browning_is_normal_and_alerts_with_the_soak(tmp_path, monkeypatch):
    await seed_builtins()
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    capture: dict = {}
    reply = {"health_assessment": "healthy", "browning_percent": 95, "summary": "evenly brown"}
    monkeypatch.setattr(vision_service.anthropic, "AsyncAnthropic", _fake_anthropic(capture, reply))
    info, forward = AsyncMock(), AsyncMock()
    monkeypatch.setattr(vision_service, "notify_info", info)
    monkeypatch.setattr("app.cloud.service.forward_event", forward)

    s = await _session("shiitake", "browning")
    result = await analyze_frame_claude(_frame(tmp_path, s["id"]))
    assert result["browning_percent"] == 95
    assert "do NOT report it as contamination" in capture["system"]
    assert "browning_percent" in capture["system"]

    [ev] = await _events(s["id"], "browning_complete")
    assert json.loads(ev["data"])["browning_percent"] == 95
    info.assert_awaited_once()
    title, message = info.await_args.args
    assert title == "Browning complete — Shiitake"
    assert "Next: Cold-water soak" in message
    event, payload = forward.await_args.args
    assert event == "phase_reminder"  # a type the cloud already pushes
    assert payload["phase"] == "browning" and "Cold-water soak" in payload["reminder"]


async def test_other_phases_keep_their_prompt_and_raise_no_browning_alert(tmp_path, monkeypatch):
    await seed_builtins()
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    capture: dict = {}
    reply = {"health_assessment": "healthy", "browning_percent": 99}
    monkeypatch.setattr(vision_service.anthropic, "AsyncAnthropic", _fake_anthropic(capture, reply))
    info = AsyncMock()
    monkeypatch.setattr(vision_service, "notify_info", info)
    monkeypatch.setattr("app.cloud.service.forward_event", AsyncMock())

    s = await _session("blue_oyster", "substrate_colonization")
    await analyze_frame_claude(_frame(tmp_path, s["id"]))
    assert "browning_percent" not in capture["system"]
    assert await _events(s["id"], "browning_complete") == []
    info.assert_not_awaited()


async def test_browning_alert_is_deduped(monkeypatch):
    await seed_builtins()
    info = AsyncMock()
    monkeypatch.setattr(vision_service, "notify_info", info)
    monkeypatch.setattr("app.cloud.service.forward_event", AsyncMock())
    s = await _session("shiitake", "browning")
    for frame_id in (1, 2):
        await _maybe_browning_alert({"id": frame_id, "session_id": s["id"], "node_id": "cam-01"},
                                    {"browning_percent": 100}, "Shiitake")
    assert len(await _events(s["id"], "browning_complete")) == 1
    info.assert_awaited_once()


async def test_colonized_shiitake_is_ready_to_brown_not_to_fruit(monkeypatch):
    await seed_builtins()
    warn = AsyncMock()
    monkeypatch.setattr(vision_service, "notify_warning", warn)
    monkeypatch.setattr("app.cloud.service.forward_event", AsyncMock())
    s = await _session("shiitake", "substrate_colonization")
    await _maybe_colonization_alert({"id": 1, "session_id": s["id"], "node_id": "cam-01"},
                                    {"colonization_percent": 99, "surface": "bag"}, "Shiitake")
    _, message = warn.await_args.args
    assert "ready to brown" in message and "Ready to move to browning." in message
    [ev] = await _events(s["id"], "colonization_complete")
    assert ev["description"].endswith("ready to brown")


# ── transcript + planner ──────────────────────────────────────────────────


async def test_transcript_key_events_record_the_soak():
    await seed_builtins()
    s = await _session("shiitake", "browning")
    await advance_phase(s["id"], PhaseAdvance(phase="primordia_induction"))
    md = await export_markdown(s["id"])
    assert "Leaving browning — Cold-water soak" in md
    # the soak is owed before pinning, so it reads before the phase change
    assert md.index("Leaving browning — Cold-water soak") < md.index("Phase advanced to primordia induction")


def test_planner_lays_browning_out_between_colonization_and_pinning():
    cycle = propose_cycle(_SHIITAKE, date(2026, 10, 1))
    assert [p.phase for p in cycle.phases] == [
        "substrate_colonization", "browning", "primordia_induction", "fruiting",
    ]
    browning = cycle.phases[1]
    assert (browning.min_days, browning.max_days) == (7, 14)
