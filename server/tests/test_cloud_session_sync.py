"""Grow sessions reach the cloud as ``session_sync`` snapshots.

The cloud's sessions, analytics, planner and chamber tiles fill from these.
Every session change (create, edit, phase, harvest, complete/abort) sends the
session's snapshot; a change made while offline is sent on reconnect, and
every connect backfills recent sessions so grows from before the link existed
reach the cloud too.
"""
from datetime import datetime

import pytest

import app.cloud.service as cloud_service
from app.cloud import session_sync
from app.config import settings
from app.db import get_db
from app.sessions import service as sessions_service
from app.sessions.models import HarvestCreate, PhaseAdvance, SessionCreate, SessionUpdate
from app.species.service import get_profile, seed_builtins


@pytest.fixture
async def cloud(monkeypatch):
    """A controllable link: `up` decides delivery, `sent` records payloads."""
    class _Cloud:
        up = True

    link = _Cloud()
    link.sent = []

    async def fake_forward(payload):
        if not link.up:
            return False
        link.sent.append(payload)
        return True

    monkeypatch.setattr(cloud_service, "forward_session_sync", fake_forward)

    async def fake_forward_contamination(payload):
        if not link.up:
            return False
        link.contamination.append(payload)
        return True

    link.contamination = []
    monkeypatch.setattr(cloud_service, "forward_contamination_event", fake_forward_contamination)
    monkeypatch.setattr(settings, "cloud_url", "https://cloud.example")
    await seed_builtins()  # species profiles live in the DB (the app seeds them at boot)
    session_sync._pending.clear()
    session_sync._pending_contamination.clear()
    session_sync.attach()
    yield link
    await session_sync.wait_idle()
    session_sync._pending.clear()
    session_sync._pending_contamination.clear()


async def _create(**kw):
    data = dict(name="North tub", species_profile_id="blue_oyster", substrate="straw")
    data.update(kw)
    return await sessions_service.create_session(SessionCreate(**data))


def _parses(ts):
    return datetime.fromisoformat(ts) is not None


async def test_snapshot_carries_the_session_profile_and_phase_timing(cloud):
    s = await _create()
    snap = await session_sync.build_session_snapshot(s["id"])
    profile = await get_profile("blue_oyster")
    phase = profile.phases[s["current_phase"]]

    assert snap["pi_session_id"] == s["id"]
    assert snap["status"] == "active"
    assert snap["species_profile_id"] == s["species_profile_id"] == "blue-oyster"
    assert snap["species_name"] == profile.common_name
    assert snap["substrate"] == "straw"
    assert snap["current_phase"] == s["current_phase"]
    assert _parses(snap["started_at"]) and snap["completed_at"] is None
    assert snap["metadata"]["species"] == {"binomial": profile.scientific_name, "common": profile.common_name}
    assert snap["metadata"]["name"] == "North tub"
    assert _parses(snap["metadata"]["phase_entered_at"])
    assert snap["metadata"]["phase_days_expected"] == phase.expected_duration_days[1]
    assert snap["harvests"] == [] and snap["flush_count"] == 0


async def test_harvests_totals_and_completion_are_in_the_snapshot(cloud):
    s = await _create()
    h1 = await sessions_service.add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=300, quality_rating=4))
    await sessions_service.add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=120, quality_rating=2))
    await sessions_service.complete_session(s["id"])
    snap = await session_sync.build_session_snapshot(s["id"])

    assert snap["status"] == "completed" and _parses(snap["completed_at"])
    assert snap["total_wet_yield_g"] == 420
    assert snap["flush_count"] == 2
    assert snap["quality_rating"] == 3
    first = snap["harvests"][0]
    assert first["pi_harvest_id"] == h1["id"] and first["flush_number"] == 1
    assert first["wet_weight_g"] == 300 and _parses(first["harvested_at"])


async def test_a_session_on_a_profile_this_pi_lacks_still_syncs(cloud):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, current_phase) VALUES (?, ?, ?)",
            ("Custom", "someones-custom-strain", "fruiting"),
        )
        await db.commit()
        session_id = cursor.lastrowid
    snap = await session_sync.build_session_snapshot(session_id)
    assert snap["species_name"] == "someones-custom-strain"
    assert snap["metadata"]["species"] is None
    assert snap["metadata"]["phase_days_expected"] is None


async def test_a_missing_session_has_no_snapshot(cloud):
    assert await session_sync.build_session_snapshot(999_999) is None


async def test_every_session_change_is_sent(cloud):
    s = await _create()
    await sessions_service.update_session(s["id"], SessionUpdate(substrate="hardwood"))
    await sessions_service.advance_phase(s["id"], PhaseAdvance(phase="primordia_induction", trigger="user"))
    await sessions_service.add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=50))
    await sessions_service.abort_session(s["id"])
    await session_sync.wait_idle()

    assert all(p["pi_session_id"] == s["id"] for p in cloud.sent)
    assert len(cloud.sent) == 5
    assert cloud.sent[1]["substrate"] == "hardwood"
    assert cloud.sent[2]["current_phase"] == "primordia_induction"
    assert cloud.sent[3]["flush_count"] == 1
    assert cloud.sent[-1]["status"] == "aborted"


async def test_changes_made_offline_are_sent_on_reconnect(cloud):
    cloud.up = False
    s = await _create()
    await session_sync.wait_idle()
    assert cloud.sent == [] and s["id"] in session_sync._pending

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [s["id"]]
    assert session_sync._pending == set()


async def test_connect_backfills_recent_sessions_newest_first(cloud):
    cloud.up = False
    first = await _create(name="First")
    second = await _create(name="Second")
    await sessions_service.complete_session(first["id"])
    await session_sync.wait_idle()
    session_sync._pending.clear()  # as after a Pi restart: nothing remembered

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [second["id"], first["id"]]


async def test_connect_hook_is_registered_with_the_connector(cloud):
    assert session_sync.on_cloud_connect in cloud_service._connect_listeners


async def test_nothing_piles_up_when_no_cloud_is_configured(cloud, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "")
    cloud.up = False
    await _create()
    await session_sync.wait_idle()
    assert session_sync._pending == set()


def test_the_app_lifespan_attaches_the_sync(client):
    # `client` runs the real lifespan.
    from app.contamination import service as contamination_service
    assert session_sync._on_session_changed in sessions_service._session_change_listeners
    assert session_sync._on_contamination_recorded in contamination_service._recorded_listeners
    assert session_sync.on_cloud_connect in cloud_service._connect_listeners


async def _record(**kw):
    from app.contamination.service import record_event
    return await record_event(**kw)


async def test_every_recorded_contamination_event_is_sent(cloud):
    s = await _create()
    await session_sync.wait_idle()
    ev = await _record(source="manual", session_id=s["id"], contamination_type="cobweb",
                       confidence=None, notes="grey wisps on the casing")
    await session_sync.wait_idle()
    [payload] = cloud.contamination
    assert payload["pi_event_id"] == ev["id"]
    assert payload["pi_session_id"] == s["id"]
    assert payload["source"] == "manual"
    assert payload["classification"] == "cobweb"
    assert payload["notes"] == "grey wisps on the casing"
    assert _parses(payload["detected_at"])


@pytest.mark.parametrize("pi_source,cloud_source", [
    ("vision", "claude"), ("identify", "claude"), ("manual", "manual"), ("something-new", "local_cnn"),
])
async def test_pi_sources_map_onto_the_cloud_column(cloud, pi_source, cloud_source):
    await _record(source=pi_source, contamination_type="trich", confidence=0.8)
    await session_sync.wait_idle()
    assert cloud.contamination[-1]["source"] == cloud_source


async def test_offline_contamination_is_sent_after_the_sessions_on_reconnect(cloud):
    cloud.up = False
    s = await _create()
    ev = await _record(source="vision", session_id=s["id"], contamination_type="trich", confidence=0.9)
    await session_sync.wait_idle()
    assert ev["id"] in session_sync._pending_contamination

    order: list[str] = []
    real_session, real_contam = cloud_service.forward_session_sync, cloud_service.forward_contamination_event

    async def session_first(payload):
        order.append("session")
        return await real_session(payload)

    async def contam_after(payload):
        order.append("contamination")
        return await real_contam(payload)

    cloud_service.forward_session_sync = session_first
    cloud_service.forward_contamination_event = contam_after
    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert order == ["session", "contamination"]
    assert [p["pi_event_id"] for p in cloud.contamination] == [ev["id"]]
    assert session_sync._pending_contamination == set()


async def test_connect_backfills_recent_contamination_events(cloud):
    cloud.up = False
    ev = await _record(source="manual", contamination_type="bacterial")
    await session_sync.wait_idle()
    session_sync._pending_contamination.clear()  # as after a Pi restart

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_event_id"] for p in cloud.contamination] == [ev["id"]]
