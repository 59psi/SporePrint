"""Grow sessions reach the cloud as ``session_sync`` snapshots.

The cloud's sessions, analytics, planner and chamber tiles fill from these.
Every session change (create, edit, phase, harvest, complete/abort) sends the
session's snapshot; a change made while offline waits in a persisted outbox
and is sent on reconnect, even after a restart; every connect re-checks recent
sessions so grows from before the link existed reach the cloud too, but sends
only what the cloud has not acknowledged in this exact form.
"""
import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.cloud.service as cloud_service
from app.cloud import session_sync
from app.config import settings
from app.db import get_db
from app.sessions import service as sessions_service
from app.sessions.models import HarvestCreate, PhaseAdvance, SessionCreate, SessionUpdate
from app.species.service import get_profile, seed_builtins


def _reset_sync_state() -> None:
    """What a Pi restart forgets (the outbox table is on disk and stays)."""
    session_sync._delivered.clear()
    session_sync._delivered_for = None
    session_sync._sending.clear()
    session_sync._dirty.clear()
    session_sync._catch_up_task = None


@pytest.fixture
async def cloud(monkeypatch):
    """A controllable link: `up` decides delivery, `sent` records payloads;
    a session id in `refuse` (an event id in `refuse_events`) is acknowledged
    as not stored."""
    link = SimpleNamespace(up=True, sent=[], contamination=[], refuse=set(), refuse_events=set())

    async def fake_forward(payload):
        if not link.up or payload["pi_session_id"] in link.refuse:
            return False
        link.sent.append(payload)
        return True

    monkeypatch.setattr(cloud_service, "forward_session_sync", fake_forward)

    async def fake_forward_contamination(payload):
        if not link.up or payload["pi_event_id"] in link.refuse_events:
            return False
        link.contamination.append(payload)
        return True

    monkeypatch.setattr(cloud_service, "forward_contamination_event", fake_forward_contamination)
    monkeypatch.setattr(session_sync, "_link_is_up", lambda: link.up)
    monkeypatch.setattr(settings, "cloud_url", "https://cloud.example")
    await seed_builtins()  # species profiles live in the DB (the app seeds them at boot)
    _reset_sync_state()
    session_sync.attach()
    yield link
    await session_sync.wait_idle()
    _reset_sync_state()


async def _restart() -> None:
    """As after a Pi restart: in-flight work done, in-memory state gone."""
    await session_sync.wait_idle()
    _reset_sync_state()


async def _forget_everything() -> None:
    """As after a restart of a Pi with an empty outbox."""
    await _restart()
    async with get_db() as db:
        await db.execute("DELETE FROM cloud_sync_pending")
        await db.commit()


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


async def test_a_rest_phase_carries_the_window_it_runs_on(cloud):
    """Rest runs on fruiting's setpoints when the profile has no rest phase
    of its own; looked up directly it had no window to send."""
    s = await _create(container_type="grow_bag")
    for phase in ("primordia_induction", "fruiting", "rest"):
        await sessions_service.advance_phase(s["id"], PhaseAdvance(phase=phase))
    snap = await session_sync.build_session_snapshot(s["id"])
    fruiting = (await get_profile("blue_oyster")).phases["fruiting"]
    assert snap["metadata"]["phase_days_expected"] == fruiting.expected_duration_days[1]


async def test_a_missing_session_has_no_snapshot(cloud):
    assert await session_sync.build_session_snapshot(999_999) is None


async def test_every_session_change_reaches_the_cloud_newest_last(cloud):
    s = await _create()
    await sessions_service.update_session(s["id"], SessionUpdate(substrate="hardwood"))
    await sessions_service.advance_phase(s["id"], PhaseAdvance(phase="primordia_induction", trigger="user"))
    await sessions_service.add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=50))
    await sessions_service.abort_session(s["id"])
    await session_sync.wait_idle()

    assert cloud.sent and all(p["pi_session_id"] == s["id"] for p in cloud.sent)
    # Changes made while a send is in flight go out together in the next one,
    # so the count varies; the order never goes backwards.
    progress = [(p["substrate"] == "hardwood", p["current_phase"] == "primordia_induction",
                 p["flush_count"], p["status"] == "aborted") for p in cloud.sent]
    assert progress == sorted(progress)
    assert progress[-1] == (True, True, 1, True)
    assert await session_sync.pending_ids(session_sync.SESSION) == []


async def test_changes_made_offline_are_sent_on_reconnect(cloud):
    cloud.up = False
    s = await _create()
    await session_sync.wait_idle()
    assert cloud.sent == [] and await session_sync.pending_ids(session_sync.SESSION) == [s["id"]]

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [s["id"]]
    assert await session_sync.pending_ids(session_sync.SESSION) == []


async def test_an_offline_change_to_an_old_session_survives_a_restart(cloud):
    """A grow finished 400 days ago is outside the connect backfill. An edit
    made to it while the link was down used to live only in memory, so a
    restart before the link came back lost it for good."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, current_phase, status, created_at, completed_at) "
            "VALUES ('Old tub', 'blue-oyster', 'complete', 'completed', ?, ?)",
            (time.time() - 400 * 86400, time.time() - 380 * 86400),
        )
        await db.commit()
        old_id = cursor.lastrowid
    cloud.up = False
    await sessions_service.update_session(old_id, SessionUpdate(name="Old tub, weighed"))
    await _restart()

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    [snapshot] = [p for p in cloud.sent if p["pi_session_id"] == old_id]
    assert snapshot["metadata"]["name"] == "Old tub, weighed"
    assert await session_sync.pending_ids(session_sync.SESSION) == []


async def test_connect_backfills_recent_sessions_newest_first(cloud):
    cloud.up = False
    first = await _create(name="First")
    second = await _create(name="Second")
    await sessions_service.complete_session(first["id"])
    await _forget_everything()

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [second["id"], first["id"]]


async def test_a_reconnect_resends_only_what_changed(cloud):
    """Every (re)connect used to re-upload every recent session and event,
    each a cloud write, even when nothing had changed."""
    first = await _create(name="First")
    second = await _create(name="Second")
    await _record(source="manual", session_id=first["id"], contamination_type="cobweb")
    await session_sync.wait_idle()
    await session_sync.on_cloud_connect()  # the cloud already has all of it
    await session_sync.wait_idle()
    sent, events = len(cloud.sent), len(cloud.contamination)

    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert (len(cloud.sent), len(cloud.contamination)) == (sent, events)

    await sessions_service.update_session(second["id"], SessionUpdate(substrate="hardwood"))
    await session_sync.wait_idle()
    del cloud.sent[:]
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert cloud.sent == []  # that change was acknowledged when it was made

    await _restart()  # the first connect after boot checks everything once
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert sorted(p["pi_session_id"] for p in cloud.sent) == sorted([first["id"], second["id"]])


async def test_a_new_link_gets_everything_again(cloud, monkeypatch):
    s = await _create()
    await session_sync.wait_idle()
    monkeypatch.setattr(settings, "cloud_device_id", "another-device")
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [s["id"], s["id"]]


async def test_a_change_during_a_send_goes_out_after_it(cloud, monkeypatch):
    """Two sends of one session used to run at once and could land in either
    order, leaving the cloud on the older snapshot. Now a change made while
    a send is in flight waits for it, then goes out freshly built."""
    s = await _create(name="v1")
    await session_sync.wait_idle()
    release = asyncio.Event()
    in_flight = {"now": 0, "max": 0}
    real_forward = cloud_service.forward_session_sync

    async def slow_forward(payload):
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        try:
            await release.wait()
            return await real_forward(payload)
        finally:
            in_flight["now"] -= 1

    monkeypatch.setattr(cloud_service, "forward_session_sync", slow_forward)
    del cloud.sent[:]
    await sessions_service.update_session(s["id"], SessionUpdate(name="v2"))
    for _ in range(20):  # the v2 send is now waiting on the cloud
        await asyncio.sleep(0)
    await sessions_service.update_session(s["id"], SessionUpdate(name="v3"))
    await sessions_service.update_session(s["id"], SessionUpdate(name="v4"))
    for _ in range(20):
        await asyncio.sleep(0)
    release.set()
    await session_sync.wait_idle()
    assert in_flight["max"] == 1
    names = [p["metadata"]["name"] for p in cloud.sent]
    assert names[-1] == "v4" and names == sorted(names) and len(names) <= 2


async def test_a_new_connect_replaces_a_catch_up_still_running(cloud, monkeypatch):
    for n in range(3):
        await _create(name=f"tub {n}")
    await _forget_everything()
    del cloud.sent[:]
    gate = asyncio.Event()
    real_forward = cloud_service.forward_session_sync

    async def stuck_forward(payload):
        await gate.wait()
        return await real_forward(payload)

    monkeypatch.setattr(cloud_service, "forward_session_sync", stuck_forward)
    await session_sync.on_cloud_connect()
    first = session_sync._catch_up_task
    await asyncio.sleep(0.05)
    await session_sync.on_cloud_connect()  # the link dropped and came back
    second = session_sync._catch_up_task
    await asyncio.sleep(0)
    assert first.cancelled() or first.done()
    gate.set()
    await session_sync.wait_idle()
    assert second.done() and not second.cancelled()
    assert len(cloud.sent) == 3


async def test_a_session_the_cloud_will_not_store_stays_queued_and_the_rest_go(cloud):
    a = await _create(name="A")
    b = await _create(name="B")
    await _forget_everything()
    del cloud.sent[:]
    async with get_db() as db:
        await db.execute("INSERT INTO cloud_sync_pending (kind, local_id) VALUES ('session', ?)", (b["id"],))
        await db.commit()
    cloud.refuse = {b["id"]}
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [a["id"]]
    assert await session_sync.pending_ids(session_sync.SESSION) == [b["id"]]


async def test_a_deleted_session_leaves_the_outbox(cloud):
    async with get_db() as db:
        await db.execute("INSERT INTO cloud_sync_pending (kind, local_id) VALUES ('session', 424242)")
        await db.execute("INSERT INTO cloud_sync_pending (kind, local_id) VALUES ('contamination', 434343)")
        await db.commit()
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert cloud.sent == [] and cloud.contamination == []
    assert await session_sync.pending_ids(session_sync.SESSION) == []
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == []


async def test_connect_hook_is_registered_with_the_connector(cloud):
    assert session_sync.on_cloud_connect in cloud_service._connect_listeners


async def test_nothing_piles_up_when_no_cloud_is_configured(cloud, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "")
    cloud.up = False
    await _create()
    await session_sync.wait_idle()
    assert await session_sync.pending_ids(session_sync.SESSION) == []


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
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == [ev["id"]]

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
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == []


async def test_connect_backfills_recent_contamination_events(cloud):
    cloud.up = False
    ev = await _record(source="manual", contamination_type="bacterial")
    await _forget_everything()

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_event_id"] for p in cloud.contamination] == [ev["id"]]


async def test_an_event_goes_out_after_its_session(cloud, monkeypatch):
    """The cloud links an event to its session's row and keeps an event whose
    session it lacks unlinked; an acknowledged event is not sent again, so its
    session goes first."""
    async with get_db() as db:  # a session this process never sent
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, current_phase) "
            "VALUES ('Quiet tub', 'blue-oyster', 'fruiting')")
        await db.commit()
        session_id = cursor.lastrowid
    order: list[tuple[str, int]] = []
    real_session, real_event = cloud_service.forward_session_sync, cloud_service.forward_contamination_event

    async def session_first(payload):
        order.append(("session", payload["pi_session_id"]))
        return await real_session(payload)

    async def event_after(payload):
        order.append(("event", payload["pi_event_id"]))
        return await real_event(payload)

    monkeypatch.setattr(cloud_service, "forward_session_sync", session_first)
    monkeypatch.setattr(cloud_service, "forward_contamination_event", event_after)
    ev = await _record(source="manual", session_id=session_id, contamination_type="cobweb")
    await session_sync.wait_idle()
    assert order == [("session", session_id), ("event", ev["id"])]
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == []


async def test_an_event_whose_session_is_not_confirmed_is_sent_again(cloud):
    """Sent while its session's snapshot was refused: the event may be stored
    unlinked, so it stays queued and goes again (after its session) next time."""
    s = await _create()
    await _forget_everything()
    cloud.refuse = {s["id"]}  # the cloud does not store the session (yet)
    ev = await _record(source="manual", session_id=s["id"], contamination_type="trich")
    await session_sync.wait_idle()
    assert [p["pi_event_id"] for p in cloud.contamination] == [ev["id"]]
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == [ev["id"]]

    cloud.refuse = set()
    del cloud.sent[:]
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_session_id"] for p in cloud.sent] == [s["id"]]
    assert [p["pi_event_id"] for p in cloud.contamination] == [ev["id"], ev["id"]]
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == []


async def test_an_old_offline_contamination_event_survives_a_restart(cloud):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO contamination_events (source, contamination_type, detected_at) "
            "VALUES ('manual', 'trich', ?)", (time.time() - 400 * 86400,))
        await db.commit()
        old_id = cursor.lastrowid
    cloud.up = False
    # As record_event's listener call does for a newly recorded event.
    await session_sync._on_contamination_recorded(
        {"id": old_id, "source": "manual", "contamination_type": "trich",
         "detected_at": time.time() - 400 * 86400})
    await _restart()

    cloud.up = True
    await session_sync.on_cloud_connect()
    await session_sync.wait_idle()
    assert [p["pi_event_id"] for p in cloud.contamination] == [old_id]
    assert await session_sync.pending_ids(session_sync.CONTAMINATION) == []


# ── the relay's acknowledgement (app.cloud.service) ─────────────────

class _AckingSio:
    def __init__(self, answer=None, error: Exception | None = None):
        self.answer, self.error, self.calls = answer, error, []

    async def call(self, event, data, timeout=None):
        self.calls.append((event, timeout))
        if self.error is not None:
            raise self.error
        return self.answer

    async def emit(self, *args, **kwargs):  # pragma: no cover — must not be used
        raise AssertionError("session_sync must wait for the relay's acknowledgement")


@pytest.mark.parametrize("answer, delivered", [
    ({"ok": True}, True), (None, True), ({"ok": False}, False),
])
async def test_a_snapshot_counts_only_once_the_relay_acknowledges_it(monkeypatch, answer, delivered):
    """A socket that died without a FIN takes emits it never delivers; a
    relay answering {"ok": false} took the frame but did not store it."""
    sio = _AckingSio(answer)
    monkeypatch.setattr(settings, "cloud_url", "https://cloud.example")
    monkeypatch.setattr(cloud_service, "_sio", sio)
    monkeypatch.setattr(cloud_service, "_connected", True)
    assert await cloud_service.forward_session_sync({"pi_session_id": 1}) is delivered
    assert await cloud_service.forward_contamination_event({"pi_event_id": 1}) is delivered
    assert [event for event, _ in sio.calls] == ["session_sync", "contamination_event"]


async def test_no_acknowledgement_is_not_a_delivery(monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://cloud.example")
    monkeypatch.setattr(cloud_service, "_sio", _AckingSio(error=TimeoutError()))
    monkeypatch.setattr(cloud_service, "_connected", True)
    assert await cloud_service.forward_session_sync({"pi_session_id": 1}) is False
