"""Sessions / chambers cross-cluster follow-ups (hardware audit, pass 2).

- srv-auto#8: POST /phase refuses a phase that isn't a GrowPhase, or one the
  species profile can't run (no setpoints and no fallback); next-phase skips
  phases the profile doesn't define;
- CLAUDE.md §12: the chamber-aware active-session lookup lives in
  sessions.service (get_active_session_for_chambers / _for_node);
- srv-auto#10: a chamberless session's telemetry still resolves a node after
  its tagged raw rows have aged into rollups;
- automation-safety #3c: session-end safing clears the OFF'd actuators'
  safety ceilings;
- chambers: linking a session through PATCH /api/chambers also binds it.
"""

import time

import pytest

import app.automation.engine as engine
import app.sessions.service as sessions_service
from app.automation.engine import evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule
from app.automation.smart_plugs import register_plug
from app.chambers.models import ChamberCreate, ChamberUpdate
from app.cloud.service import _dispatch_system_command
from app.chambers.service import chambers_for_node, create_chamber, update_chamber
from app.db import get_db
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import (
    InvalidPhaseError,
    advance_phase,
    complete_session,
    create_session,
    get_active_session_for_chambers,
    get_active_session_for_node,
    get_session,
    handle_remote_command,
    phase_error,
    resolve_session_node_id,
    suggested_next_phase,
)
from app.species.profiles import BUILTIN_PROFILES
from app.species.service import seed_builtins
from app.telemetry.service import active_session_for_node


@pytest.fixture(autouse=True)
def _reset_pause_state():
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


async def _session(species="blue_oyster", phase="substrate_colonization", **kw):
    return await create_session(SessionCreate(
        name=f"{species}-{phase}-{time.monotonic_ns()}", species_profile_id=species,
        current_phase=phase, **kw,
    ))


# ── srv-auto#8: phase validation ───────────────────────────────────────────


async def test_unknown_phase_is_refused():
    await seed_builtins()
    s = await _session()
    with pytest.raises(InvalidPhaseError, match="fruitng"):
        await advance_phase(s["id"], PhaseAdvance(phase="fruitng"))
    assert (await get_session(s["id"]))["current_phase"] == "substrate_colonization"


async def test_phase_the_profile_cannot_run_is_refused():
    """chaga defines only substrate_colonization: no fruiting / primordia
    setpoints for fruiting, primordia induction or rest to run on."""
    await seed_builtins()
    s = await _session("chaga")
    for phase in ("fruiting", "primordia_induction", "rest"):
        with pytest.raises(InvalidPhaseError, match=phase):
            await advance_phase(s["id"], PhaseAdvance(phase=phase))
    assert (await get_session(s["id"]))["current_phase"] == "substrate_colonization"


async def test_optional_early_stages_walk_through_on_any_profile():
    """CLAUDE.md §6: agar / LC / grain are optional in-vessel stages. blue_oyster
    defines none of them, yet an agar-started session must reach fruiting."""
    await seed_builtins()
    s = await _session("blue_oyster", "agar")
    for phase in ("liquid_culture", "grain_colonization", "substrate_colonization",
                  "primordia_induction", "fruiting"):
        assert (await advance_phase(s["id"], PhaseAdvance(phase=phase)))["current_phase"] == phase


async def test_colonization_stages_are_enterable_on_every_builtin_profile():
    """Four built-ins (the sclerotia species, P. mexicana, antrodia) define no
    substrate_colonization — the SessionCreate default — and most define no
    agar / LC / grain; none of that makes a colonization stage unreachable."""
    await seed_builtins()
    for profile in BUILTIN_PROFILES:
        for phase in ("agar", "liquid_culture", "grain_colonization",
                      "substrate_colonization", "cold_storage", "complete"):
            assert phase_error(phase, profile) is None, (profile.id, phase)


async def test_create_refuses_an_unknown_phase_name():
    await seed_builtins()
    with pytest.raises(InvalidPhaseError, match="fruitng"):
        await _session("blue_oyster", "fruitng")
    with pytest.raises(InvalidPhaseError, match="fruiting"):
        await _session("chaga", "fruiting")
    # Unknown species: only the name is checked.
    assert (await _session("no-such-species", "grain_colonization"))["current_phase"] == "grain_colonization"
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS n FROM sessions WHERE current_phase = 'fruitng'")
        assert (await cursor.fetchone())["n"] == 0


async def test_cloud_session_start_with_a_typo_is_reported_not_stored():
    await seed_builtins()
    with pytest.raises(InvalidPhaseError):
        await handle_remote_command("session_start", {
            "name": "cloud", "species_profile_id": "blue_oyster", "current_phase": "fruitng",
        })
    ok, reason = await _dispatch_system_command("session_start", {
        "name": "cloud", "species_profile_id": "blue_oyster", "current_phase": "fruitng",
    })
    assert ok is False and "fruitng" in reason
    ok, reason = await _dispatch_system_command("session_start", {
        "name": "cloud", "species_profile_id": "blue_oyster",
    })
    assert ok is True, reason


@pytest.mark.parametrize("phase", ["rest", "primordia_induction", "fruiting", "cold_storage", "complete"])
async def test_phases_the_engine_can_run_are_accepted(phase):
    """pink_oyster has no primordia_induction or rest phase, but the engine
    runs both on its fruiting setpoints; cold_storage/complete need none."""
    await seed_builtins()
    s = await _session("pink_oyster")
    updated = await advance_phase(s["id"], PhaseAdvance(phase=phase))
    assert updated["current_phase"] == phase


async def test_unknown_species_only_checks_the_phase_name():
    s = await _session("no-such-species")
    assert (await advance_phase(s["id"], PhaseAdvance(phase="agar")))["current_phase"] == "agar"
    with pytest.raises(InvalidPhaseError):
        await advance_phase(s["id"], PhaseAdvance(phase="sporulating"))


async def test_unknown_session_is_still_none_before_phase_validation():
    assert await advance_phase(9999, PhaseAdvance(phase="fruitng")) is None


def test_phase_endpoint_returns_422_for_a_typo(client):
    sid = client.post("/api/sessions", json={
        "name": "typo", "species_profile_id": "blue_oyster",
    }).json()["id"]
    r = client.post(f"/api/sessions/{sid}/phase", json={"phase": "fruitng"})
    assert r.status_code == 422, r.text
    assert "fruitng" in r.json()["detail"]
    assert client.post("/api/sessions/9999/phase", json={"phase": "fruitng"}).status_code == 404
    r = client.post("/api/sessions", json={
        "name": "typo", "species_profile_id": "blue_oyster", "current_phase": "fruitng",
    })
    assert r.status_code == 422, r.text
    assert "fruitng" in r.json()["detail"]


# ── srv-auto#8: next-phase skips undefined phases ──────────────────────────


def test_suggestion_without_a_profile_is_unchanged():
    assert suggested_next_phase("substrate_colonization", "grow_bag") == "primordia_induction"
    assert suggested_next_phase("fruiting", "grow_bag") == "rest"


def test_suggestion_skips_a_primordia_phase_the_profile_folds_into_fruiting():
    pink = {"substrate_colonization", "fruiting"}
    assert suggested_next_phase("substrate_colonization", "grow_bag", profile_phases=pink) == "fruiting"
    # REST between flushes runs on fruiting's setpoints, so the loop is kept.
    assert suggested_next_phase("fruiting", "grow_bag", profile_phases=pink) == "rest"
    assert suggested_next_phase("rest", "grow_bag", True, profile_phases=pink) == "fruiting"
    assert suggested_next_phase("rest", "grow_bag", False, profile_phases=pink) == "complete"
    # Cold storage needs no species setpoints.
    assert suggested_next_phase("grain_colonization", "jar", profile_phases=pink) == "cold_storage"


def test_suggestion_ends_when_nothing_after_is_defined():
    """psilocybe_tampanensis only defines grain_colonization (sclerotia)."""
    grain_only = {"grain_colonization"}
    assert suggested_next_phase("grain_colonization", "grow_bag", profile_phases=grain_only) == "complete"
    assert suggested_next_phase("cold_storage", None, profile_phases=grain_only) == "complete"


def test_suggestion_keeps_defined_primordia():
    blue = {"substrate_colonization", "primordia_induction", "fruiting"}
    assert suggested_next_phase("substrate_colonization", "grow_bag",
                                profile_phases=blue) == "primordia_induction"


def test_next_phase_endpoint_uses_the_species_profile(client):
    sid = client.post("/api/sessions", json={
        "name": "pink", "species_profile_id": "pink_oyster", "container_type": "grow_bag",
    }).json()["id"]
    r = client.get(f"/api/sessions/{sid}/next-phase")
    assert r.status_code == 200, r.text
    assert r.json()["suggested_next_phase"] == "fruiting"


# ── CLAUDE.md §12: chamber-aware active session lookup ─────────────────────


async def _link(chamber_id, session_id):
    async with get_db() as db:
        await db.execute("UPDATE chambers SET active_session_id = ? WHERE id = ?",
                         (session_id, chamber_id))
        await db.commit()


async def _age(session_id, seconds):
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = created_at - ? WHERE id = ?",
                         (seconds, session_id))
        await db.commit()


async def test_session_for_chambers_prefers_bound_then_linked_then_unbound():
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    unbound_old = await _session("unit-a")
    await _age(unbound_old["id"], 300)
    bound = await _session("unit-c", chamber_id=a)
    await _age(bound["id"], 100)
    linked = await _session("unit-b")
    await _age(linked["id"], 200)
    # Linked after `bound` was created (creating a bound session links it too).
    await _link(a, linked["id"])
    newest_unbound = await _session("unit-d")

    assert (await get_active_session_for_chambers([a]))["id"] == bound["id"]
    await complete_session(bound["id"])
    assert (await get_active_session_for_chambers([a]))["id"] == linked["id"]
    await complete_session(linked["id"])
    assert (await get_active_session_for_chambers([a]))["id"] == newest_unbound["id"]


async def test_session_for_chambers_never_takes_another_chambers_grow():
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    b = (await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"])))["id"]
    await _session("unit-b", chamber_id=b)
    linked_to_b = await _session("unit-x")
    await _link(b, linked_to_b["id"])
    assert await get_active_session_for_chambers([a]) is None


async def test_session_for_node_outside_any_chamber_is_the_newest():
    older = await _session("unit-a")
    await _age(older["id"], 100)
    newest = await _session("unit-b")
    assert (await get_active_session_for_node("climate-loose"))["id"] == newest["id"]
    assert (await get_active_session_for_chambers([]))["id"] == newest["id"]
    assert await chambers_for_node("climate-loose") == []


async def test_unchambered_node_prefers_the_chamberless_grow_like_the_tagger():
    b = (await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"])))["id"]
    closet = await _session("unit-a")
    await _age(closet["id"], 100)
    await _session("unit-b", chamber_id=b)  # newer, but chamber B's
    assert (await get_active_session_for_node("climate-loose"))["id"] == closet["id"]
    assert await active_session_for_node("climate-loose", time.time() + 5) == closet["id"]


async def test_unchambered_node_takes_the_only_chambers_grow():
    """A chamber whose node list is incomplete: the unlisted node can only be
    that grow's (the tagger leaves its readings untagged until it's listed)."""
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["cam-a"])))["id"]
    s = await _session("unit-a", chamber_id=a)
    await _age(s["id"], 50)
    newer = await _session("unit-b", chamber_id=a)
    assert (await get_active_session_for_node("climate-loose"))["id"] == newer["id"]


async def test_unchambered_node_never_guesses_between_two_chambers():
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    b = (await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"])))["id"]
    await _session("unit-a", chamber_id=a)
    await _session("unit-b", chamber_id=b)
    assert await get_active_session_for_node("cam-loose") is None
    assert await get_active_session_for_chambers([]) is None
    assert await active_session_for_node("cam-loose", time.time() + 5) is None


async def test_unchambered_node_drives_no_other_chambers_grow(mock_mqtt):
    """A loose room sensor at 50 °F used to evaluate the newest chamber's rules
    and switch its heater, resolved to whichever relay heartbeated last."""
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    b = (await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"])))["id"]
    await _session("unit-a", "fruiting", chamber_id=a)
    await _session("unit-b", "fruiting", chamber_id=b)
    await create_rule(_on_rule("heat", "relay-b", "heater", ceiling=None))
    await evaluate_rules("climate-room", {"temp_f": 50})
    assert not [t for t, _ in mock_mqtt if t.endswith("/cmd/heater")]
    await evaluate_rules("climate-b", {"temp_f": 50})
    assert [t for t, _ in mock_mqtt if t.endswith("/cmd/heater")] == ["sporeprint/relay-b/cmd/heater"]


async def test_tagger_is_a_subset_of_the_session_rule():
    """Wherever telemetry tagging names a session for a live reading, the
    engine / vision rule names the same one (CLAUDE.md §12: one definition)."""
    a = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    b = (await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"])))["id"]
    nodes = ("climate-a", "climate-b", "climate-loose")

    async def _check():
        for node in nodes:
            tagged = await active_session_for_node(node, time.time() + 5)
            if tagged is not None:
                assert (await get_active_session_for_node(node))["id"] == tagged, node

    await _check()
    sa = await _session("unit-a", chamber_id=a)
    await _check()
    free = await _session("unit-x")
    await _check()
    await _session("unit-b", chamber_id=b)
    await _check()
    await complete_session(free["id"])
    await _check()
    await complete_session(sa["id"])
    await _check()


async def test_chambers_for_node_tolerates_malformed_node_ids():
    good = (await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"])))["id"]
    async with get_db() as db:
        await db.execute("INSERT INTO chambers (name, node_ids) VALUES ('bad', 'not json')")
        await db.commit()
    found = await chambers_for_node("climate-a")
    assert found == [{"id": good, "node_ids": ["climate-a"]}]


# ── srv-auto#10: chamberless session telemetry after raw rows age out ──────


async def _rollup(node, sensor, ts, value=70.0):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, "
            "min_value, max_value, count) VALUES (?, ?, ?, 'hourly', ?, ?, ?, 12)",
            (ts, node, sensor, value, value, value),
        )
        await db.commit()


async def test_chamberless_session_resolves_a_node_from_rollups():
    s = await _session("unit-a")
    await _age(s["id"], 20 * 86400)
    start = (await get_session(s["id"]))["created_at"]
    await _rollup("climate-1", "temp_f", start + 3600)
    await _rollup("climate-1", "temp_f", start + 7200)
    await _rollup("relay-1", "fae", start + 3600, 1)
    assert await resolve_session_node_id(s["id"], "temp_f") == "climate-1"


async def test_rollup_fallback_ignores_chambered_nodes_and_other_windows():
    await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"]))
    s = await _session("unit-a")
    await _age(s["id"], 20 * 86400)
    start = (await get_session(s["id"]))["created_at"]
    await _rollup("climate-a", "temp_f", start + 3600)      # a chamber's node
    await _rollup("climate-old", "temp_f", start - 86400)   # before this grow
    assert await resolve_session_node_id(s["id"], "temp_f") is None
    await _rollup("climate-1", "temp_f", start + 60)
    assert await resolve_session_node_id(s["id"], "temp_f") == "climate-1"


async def test_rollup_fallback_prefers_the_node_with_most_data():
    s = await _session("unit-a")
    await _age(s["id"], 20 * 86400)
    start = (await get_session(s["id"]))["created_at"]
    await _rollup("climate-1", "temp_f", start + 3600)
    for h in range(2, 5):
        await _rollup("climate-2", "temp_f", start + h * 3600)
    assert await resolve_session_node_id(s["id"], "temp_f") == "climate-2"


# ── automation-safety #3c: session end clears safety ceilings ──────────────


@pytest.fixture()
def json_publishes(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def _fake_publish(topic, payload):
        calls.append((topic, payload))
        return True

    monkeypatch.setattr(sessions_service, "mqtt_publish", _fake_publish)
    return calls


def _on_rule(name, target, channel=None, ceiling=3600):
    return AutomationRule(
        name=name, priority=1, safety_max_on_seconds=ceiling,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=0)),
        action=RuleAction(target=target, channel=channel, state="on"),
    )


async def _watchdog_rows():
    async with get_db() as db:
        cursor = await db.execute("SELECT target, channel FROM safety_watchdogs")
        return {(r["target"], r["channel"]) for r in await cursor.fetchall()}


async def test_session_end_clears_the_ceilings_of_what_it_switched_off(
        mock_mqtt, mock_mqtt_raw, json_publishes):
    await register_plug("plug-h1", "Heater", "shelly", "shellies/h1", device_role="heater")
    await create_rule(_on_rule("heat", "plug-heater"))
    await create_rule(_on_rule("fan", "relay-a", "fae"))
    s = await _session("unit-a", "fruiting")
    await evaluate_rules("climate-1", {"temp_f": 70})
    assert {"plug-heater:*", "relay-a:fae"} <= set(engine._safety_tasks)
    assert await _watchdog_rows() == {("plug-heater", None), ("relay-a", "fae")}

    await complete_session(s["id"])

    assert ("shellies/h1/relay/0/command", "off") in mock_mqtt_raw
    assert ("sporeprint/relay-a/cmd/fae", {"state": "off", "reason": "session_ended"}) in json_publishes
    assert "plug-heater:*" not in engine._safety_tasks
    assert "relay-a:fae" not in engine._safety_tasks
    assert await _watchdog_rows() == set()


async def test_session_end_keeps_the_ceiling_when_the_off_was_not_published(
        mock_mqtt, mock_mqtt_raw, monkeypatch):
    async def _down(topic, payload):
        return False

    monkeypatch.setattr(sessions_service, "mqtt_publish", _down)
    await create_rule(_on_rule("fan", "relay-a", "fae"))
    s = await _session("unit-a", "fruiting")
    await evaluate_rules("climate-1", {"temp_f": 70})
    await complete_session(s["id"])
    assert "relay-a:fae" in engine._safety_tasks
    assert await _watchdog_rows() == {("relay-a", "fae")}


async def _two_chamber_rules():
    a = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a", "relay-a"]))
    b = await create_chamber(ChamberCreate(name="B", node_ids=["climate-b", "relay-b"]))
    await register_plug("plug-h1", "Heater", "shelly", "shellies/h1", device_role="heater")
    await create_rule(_on_rule("heat", "plug-heater"))
    await create_rule(_on_rule("fan-a", "relay-a", "fae"))
    await create_rule(_on_rule("fan-b", "relay-b", "fae"))
    await create_rule(_on_rule("fan-loose", "relay-z", "fae"))
    return a["id"], b["id"]


def _offs(json_publishes, mock_mqtt_raw):
    return ([t for t, p in json_publishes if p.get("state") == "off"]
            + [t for t, p in mock_mqtt_raw if p == "off"])


async def test_ending_one_chambers_grow_safes_only_that_chambers_nodes(
        mock_mqtt, mock_mqtt_raw, json_publishes):
    """Chamber B still runs: ending A's grow used to skip safing entirely,
    leaving A's fan / light scene in the grow's last state."""
    a, b = await _two_chamber_rules()
    sa = await _session("unit-a", "fruiting", chamber_id=a)
    await _session("unit-b", "fruiting", chamber_id=b)
    await complete_session(sa["id"])
    # Never B's relay, an unlisted node, or a plug B's grow may be using.
    assert _offs(json_publishes, mock_mqtt_raw) == ["sporeprint/relay-a/cmd/fae"]


async def test_ending_a_grow_its_chamber_still_runs_safes_nothing(
        mock_mqtt, mock_mqtt_raw, json_publishes):
    a, b = await _two_chamber_rules()
    first = await _session("unit-a", "fruiting", chamber_id=a)
    await _session("unit-a2", "fruiting", chamber_id=a)
    await _session("unit-b", "fruiting", chamber_id=b)
    await complete_session(first["id"])
    assert _offs(json_publishes, mock_mqtt_raw) == []


async def test_last_grow_ending_still_safes_everything(
        mock_mqtt, mock_mqtt_raw, json_publishes):
    a, b = await _two_chamber_rules()
    sa = await _session("unit-a", "fruiting", chamber_id=a)
    await complete_session(sa["id"])
    assert sorted(_offs(json_publishes, mock_mqtt_raw)) == [
        "shellies/h1/relay/0/command", "sporeprint/relay-a/cmd/fae",
        "sporeprint/relay-b/cmd/fae", "sporeprint/relay-z/cmd/fae"]


# ── chambers: PATCH active_session_id also binds sessions.chamber_id ───────


async def test_linking_an_unbound_session_binds_it_to_the_chamber():
    c = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"]))
    s = await _session("unit-a")
    await update_chamber(c["id"], ChamberUpdate(active_session_id=s["id"]))
    assert (await get_session(s["id"]))["chamber_id"] == c["id"]


async def test_linking_never_moves_a_session_bound_to_another_chamber():
    a = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"]))
    b = await create_chamber(ChamberCreate(name="B", node_ids=["climate-b"]))
    s = await _session("unit-a", chamber_id=b["id"])
    updated = await update_chamber(a["id"], ChamberUpdate(active_session_id=s["id"]))
    assert updated["active_session_id"] == s["id"]
    assert (await get_session(s["id"]))["chamber_id"] == b["id"]


async def test_detaching_leaves_the_session_binding_alone():
    c = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"]))
    s = await _session("unit-a", chamber_id=c["id"])
    await update_chamber(c["id"], ChamberUpdate(active_session_id=None))
    assert (await get_session(s["id"]))["chamber_id"] == c["id"]


async def test_linked_session_telemetry_is_tagged_to_it():
    """The telemetry tagger reads sessions.chamber_id only; a PATCH link used
    to leave a chamber's readings untagged."""
    c = await create_chamber(ChamberCreate(name="A", node_ids=["climate-a"]))
    s = await _session("unit-a")
    assert await active_session_for_node("climate-a", time.time() + 5) is None
    await update_chamber(c["id"], ChamberUpdate(active_session_id=s["id"]))
    assert await active_session_for_node("climate-a", time.time() + 5) == s["id"]
