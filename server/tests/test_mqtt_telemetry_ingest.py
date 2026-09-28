"""Telemetry ingest contract: session tagging, replay/stale frames, node alerts.

Shared wire contract (firmware <-> Pi):
  * `ts` is Unix-epoch seconds once the node's clock is NTP-synced; unsynced
    frames keep an uptime-based ts. Any ts < 1_000_000_000 is unsynced and the
    Pi stamps arrival time.
  * Frames replayed from the node's offline buffer carry `"replay": true`.
  * Replayed frames, and synced frames more than 120 s old, are STORED but never
    evaluated by the rules engine and never overwrite a newer latest reading.
"""

import sqlite3
import time

import pytest

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.db import get_db
from app.mqtt import _handle_message, get_reliability_counters
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, resolve_session_node_id
from app.telemetry.service import get_history, get_latest
from app.transcript.service import export_json


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event):
        return [d for e, d in self.events if e == event]


@pytest.fixture()
def cloud_forwards():
    return []


@pytest.fixture()
def rules_spy(monkeypatch, cloud_forwards):
    calls: list[tuple[str, dict]] = []

    async def _spy(node_id, readings, sio=None):
        calls.append((node_id, dict(readings)))

    async def _record_forward(node_id, payload):
        cloud_forwards.append((node_id, dict(payload)))

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _spy)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _record_forward)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)
    return calls


async def _rows(node_id: str, sensor: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT timestamp, value, session_id FROM telemetry_readings "
            "WHERE node_id = ? AND sensor = ? ORDER BY timestamp",
            (node_id, sensor),
        )
        return [dict(r) for r in await cursor.fetchall()]


def _latest(rows, sensor):
    return next(r["value"] for r in rows if r["sensor"] == sensor)


# ── session tagging (srv-auto#10) ────────────────────────────────


async def test_live_telemetry_is_tagged_with_active_session(rules_spy):
    s = await create_session(SessionCreate(name="Tag me", species_profile_id="blue_oyster"))
    await _handle_message(
        _Sio(), "sporeprint/climate-01/telemetry",
        {"temp_f": 60.0, "humidity": 90.0, "ts": time.time()},
    )
    rows = await _rows("climate-01", "temp_f")
    assert len(rows) == 1
    assert rows[0]["session_id"] == s["id"]


async def test_telemetry_without_active_session_is_untagged(rules_spy):
    await _handle_message(
        _Sio(), "sporeprint/climate-01/telemetry",
        {"temp_f": 60.0, "ts": time.time()},
    )
    rows = await _rows("climate-01", "temp_f")
    assert rows[0]["session_id"] is None


async def test_frame_older_than_session_is_not_tagged(rules_spy):
    await create_session(SessionCreate(name="Late", species_profile_id="blue_oyster"))
    await _handle_message(
        _Sio(), "sporeprint/climate-01/telemetry",
        {"temp_f": 60.0, "ts": time.time() - 3600, "replay": True},
    )
    rows = await _rows("climate-01", "temp_f")
    assert rows[0]["session_id"] is None


async def _chambered_session(name: str, node_ids: list[str]) -> dict:
    chamber = await create_chamber(ChamberCreate(name=name, node_ids=node_ids))
    return await create_session(SessionCreate(
        name=f"{name} grow", species_profile_id="blue_oyster", chamber_id=chamber["id"],
    ))


async def _feed(node_id: str, **readings):
    await _handle_message(_Sio(), f"sporeprint/{node_id}/telemetry",
                          {**readings, "ts": time.time()})


async def test_concurrent_chambered_sessions_tag_their_own_nodes(rules_spy):
    """Each chamber's node is tagged with its own chamber's grow, never the newest."""
    sa = await _chambered_session("A", ["node-a"])
    sb = await _chambered_session("B", ["node-b"])  # created last
    for _ in range(3):
        await _feed("node-b", temp_f=60.0)
        await _feed("node-a", temp_f=85.0)

    assert {r["session_id"] for r in await _rows("node-a", "temp_f")} == {sa["id"]}
    assert {r["session_id"] for r in await _rows("node-b", "temp_f")} == {sb["id"]}
    # Downstream consumers resolve each session to its own chamber's node.
    assert await resolve_session_node_id(sb["id"], "temp_f") == "node-b"
    assert await resolve_session_node_id(sa["id"], "temp_f") == "node-a"
    summary = (await export_json(sb["id"]))["phase_telemetry"][0]["telemetry_summary"]
    assert summary["temp_f"] == {"min": 60.0, "max": 60.0, "avg": 60.0, "count": 3}


async def test_node_in_idle_chamber_is_not_tagged_with_another_chambers_grow(rules_spy):
    await create_chamber(ChamberCreate(name="Idle", node_ids=["node-idle"]))
    await _chambered_session("Busy", ["node-busy"])
    await _feed("node-idle", temp_f=70.0)
    assert (await _rows("node-idle", "temp_f"))[0]["session_id"] is None


async def test_chambered_node_is_not_claimed_by_a_chamberless_grow(rules_spy):
    await create_chamber(ChamberCreate(name="Tent", node_ids=["node-tent"]))
    await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    await _feed("node-tent", temp_f=70.0)
    assert (await _rows("node-tent", "temp_f"))[0]["session_id"] is None


async def test_unchambered_node_goes_to_chamberless_grow_not_a_chambered_one(rules_spy):
    loose = await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    await _chambered_session("Tent", ["node-tent"])  # newer, but not this node's
    await _feed("node-shelf", temp_f=70.0)
    assert (await _rows("node-shelf", "temp_f"))[0]["session_id"] == loose["id"]


async def test_unchambered_node_untagged_when_only_chambered_grows_are_active(rules_spy):
    await _chambered_session("Tent", ["node-tent"])
    await _feed("node-shelf", temp_f=70.0)
    assert (await _rows("node-shelf", "temp_f"))[0]["session_id"] is None


async def test_malformed_chamber_node_ids_do_not_break_ingest(rules_spy):
    loose = await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    async with get_db() as db:
        await db.execute("INSERT INTO chambers (name, node_ids) VALUES ('Bad', 'not json')")
        await db.commit()
    await _feed("climate-01", temp_f=70.0)
    rows = await _rows("climate-01", "temp_f")
    assert rows[0]["session_id"] == loose["id"]
    assert len(rules_spy) == 1


# ── replay / stale frames (srv-hw#11) ────────────────────────────


async def test_synced_replay_frame_stored_at_its_time_not_evaluated(rules_spy, cloud_forwards):
    sio = _Sio()
    now = time.time()
    # Fresh reading first (the firmware publishes live, then flushes its buffer).
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 88.0, "ts": now})
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 70.0, "ts": now - 1800, "replay": True})

    # Rules ran on the live frame only.
    assert [r["humidity"] for _, r in rules_spy] == [88.0]
    # Only the live frame went out on the local live socket.
    assert [d["humidity"] for d in sio.named("telemetry")] == [88.0]
    # The cloud relay gets both (its history stays whole), the late one with
    # its real ts and marked as not live.
    assert [(p["humidity"], round(p["ts"]), p.get("replay")) for _, p in cloud_forwards] == [
        (88.0, round(now), None), (70.0, round(now - 1800), True)
    ]
    # Both are stored, each at its own time.
    rows = await _rows("climate-01", "humidity")
    assert [(round(r["timestamp"]), r["value"]) for r in rows] == [
        (round(now - 1800), 70.0), (round(now), 88.0)
    ]
    # The latest reading is still the fresh one.
    assert _latest(await get_latest("climate-01"), "humidity") == 88.0


async def test_stale_synced_frame_without_replay_flag_not_evaluated(rules_spy, cloud_forwards):
    sio = _Sio()
    old = time.time() - 600  # > 120 s old
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 70.0, "ts": old})
    assert rules_spy == []
    assert sio.named("telemetry") == []
    rows = await _rows("climate-01", "humidity")
    assert len(rows) == 1 and abs(rows[0]["timestamp"] - old) < 0.01
    # Forwarded to the cloud at its real time, flagged as not live.
    assert [(p["ts"], p["replay"]) for _, p in cloud_forwards] == [(old, True)]


async def test_recent_synced_frame_is_live(rules_spy):
    sio = _Sio()
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 80.0, "ts": time.time() - 30})
    assert len(rules_spy) == 1
    assert len(sio.named("telemetry")) == 1


async def test_unsynced_replay_frame_never_becomes_latest(rules_spy):
    sio = _Sio()
    # Deployed firmware: uptime ts on both the live frame and the buffered one.
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 88.0, "ts": 5000})
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 70.0, "ts": 4000, "replay": True})

    assert [r["humidity"] for _, r in rules_spy] == [88.0]
    assert _latest(await get_latest("climate-01"), "humidity") == 88.0
    rows = await _rows("climate-01", "humidity")
    assert len(rows) == 2
    assert all(r["timestamp"] > 1_000_000_000 for r in rows)


async def test_unsynced_live_frame_still_evaluated(rules_spy):
    """Backward compat: deployed nodes send uptime ts with no replay flag."""
    before = get_reliability_counters()["uptime_ts_clamps"]
    await _handle_message(_Sio(), "sporeprint/climate-01/telemetry",
                          {"humidity": 88.0, "ts": 5000})
    assert len(rules_spy) == 1
    assert get_reliability_counters()["uptime_ts_clamps"] == before + 1


async def test_unsynced_threshold_is_one_billion(rules_spy):
    # 999_999_999 is unsynced -> arrival time; 1_000_000_000 is a real epoch.
    t0 = time.time()
    await _handle_message(_Sio(), "sporeprint/n1/telemetry",
                          {"humidity": 50.0, "ts": 999_999_999})
    await _handle_message(_Sio(), "sporeprint/n2/telemetry",
                          {"humidity": 50.0, "ts": 1_000_000_000})
    assert (await _rows("n1", "humidity"))[0]["timestamp"] >= t0 - 1
    assert (await _rows("n2", "humidity"))[0]["timestamp"] == 1_000_000_000
    # n2's 2001 timestamp is a (very) stale synced frame: stored, not evaluated.
    assert [n for n, _ in rules_spy] == ["n1"]


async def test_locked_database_does_not_skip_rules(rules_spy, monkeypatch):
    """A write lock held by the nightly retention job must not skip automation."""
    async def _locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("app.mqtt.store_bulk_readings", _locked)
    sio = _Sio()
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"temp_f": 95.0, "ts": time.time()})
    assert [r["temp_f"] for _, r in rules_spy] == [95.0]
    assert len(sio.named("telemetry")) == 1


async def test_replay_history_lands_in_the_past(rules_spy):
    now = time.time()
    await _handle_message(_Sio(), "sporeprint/climate-01/telemetry",
                          {"temp_f": 70.0, "ts": now - 900, "replay": True})
    hist = await get_history("climate-01", "temp_f", from_ts=now - 1000, to_ts=now - 800)
    assert len(hist) == 1 and hist[0]["value"] == 70.0


# ── node alerts reach ntfy (srv-hw#12) ───────────────────────────


@pytest.fixture()
def ntfy_posts(monkeypatch):
    """Capture ntfy publishes as {"title", "priority", "message"}.

    Accepts both ntfy publish styles (header API: Title/Priority headers with
    the message as the body; JSON API: title/priority/message in the body).
    """
    posts: list[dict] = []

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, content=None, headers=None, json=None, timeout=None, **kw):
            if json is not None:
                posts.append({"title": json.get("title", ""),
                              "priority": str(json.get("priority")),
                              "message": json.get("message", "")})
            else:
                h = headers or {}
                posts.append({"title": h.get("Title", ""),
                              "priority": str(h.get("Priority")),
                              "message": content})
            return _Response()

    from app.config import settings
    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr("app.notifications.service.httpx.AsyncClient", _FakeClient)

    async def _noop_forward(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_event", _noop_forward)
    return posts


@pytest.mark.parametrize("alert_type,value", [
    ("temperature", 93.0),
    ("co2", 4500.0),
    ("sensor_failure", 0.0),
])
async def test_safety_alert_pages_critical(ntfy_posts, alert_type, value):
    await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                          {"type": alert_type, "value": value, "message": "bad"})
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == "5"
    assert "climate-01" in ntfy_posts[0]["title"]


async def test_repeated_alert_is_deduped_per_node_and_type(ntfy_posts):
    for _ in range(5):  # the firmware re-emits every read cycle
        await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                              {"type": "temperature", "value": 95.0, "message": "hot"})
    await _handle_message(_Sio(), "sporeprint/climate-02/alert",
                          {"type": "temperature", "value": 95.0, "message": "hot"})
    await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                          {"type": "co2", "value": 5000.0, "message": "co2"})
    assert len(ntfy_posts) == 3


async def test_sensor_failures_of_different_sensors_each_page(ntfy_posts):
    """One alert type covers several sensors; one failure must not mask the next."""
    for sensor in ("SCD4x", "SCD4x", "BH1750", "HX711"):
        await _handle_message(_Sio(), "sporeprint/climate-01/alert", {
            "type": "sensor_failure", "value": 0.0,
            "message": "sensor stale - no fresh reading", "sensor": sensor,
        })
    assert len(ntfy_posts) == 3
    assert [p["title"] for p in ntfy_posts] == [
        "Node climate-01: sensor failure alert (SCD4x)",
        "Node climate-01: sensor failure alert (BH1750)",
        "Node climate-01: sensor failure alert (HX711)",
    ]


async def test_humidity_alert_pages_warning(ntfy_posts):
    await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                          {"type": "humidity", "value": 25.0, "message": "dry"})
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == "4"


async def test_door_open_is_info_and_close_is_silent(ntfy_posts):
    await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                          {"type": "door", "value": 1.0, "message": "Chamber door opened"})
    await _handle_message(_Sio(), "sporeprint/climate-01/alert",
                          {"type": "door", "value": 0.0, "message": "Chamber door closed"})
    assert len(ntfy_posts) == 1
    assert ntfy_posts[0]["priority"] == "3"


# ── Liveness: telemetry refreshes last_seen (srv-hw#22 hardening) ─────────
#
# The liveness sweeper (main._node_liveness_sweeper) pages node_offline once
# hardware_nodes.last_seen is 15 min stale. Only status/* frames used to touch
# it, so a node whose heartbeats stop reaching the Pi (or older firmware) was
# paged offline while its telemetry was arriving every minute.

async def _register_node(node_id: str, last_seen: float, status: str = "online"):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, last_seen, status) "
            "VALUES (?, 'climate', ?, ?)",
            (node_id, last_seen, status),
        )
        await db.commit()


async def _node_row(node_id: str):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT last_seen, status FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def test_sensor_telemetry_refreshes_last_seen(rules_spy):
    await _register_node("climate-01", time.time() - 3600)
    before = time.time()
    await _handle_message(_Sio(), "sporeprint/climate-01/telemetry",
                          {"ts": time.time(), "temp_f": 71.5})
    assert (await _node_row("climate-01"))["last_seen"] >= before


async def test_switch_state_report_refreshes_last_seen(rules_spy):
    await _register_node("relay-01", time.time() - 3600)
    before = time.time()
    await _handle_message(_Sio(), "sporeprint/relay-01/telemetry/fae",
                          {"channel": "fae", "state": "on", "pwm": 255, "trigger": "report"})
    assert (await _node_row("relay-01"))["last_seen"] >= before


async def test_replayed_telemetry_still_proves_the_node_is_alive(rules_spy):
    # The frame's reading is old, but its arrival is now.
    await _register_node("climate-01", time.time() - 3600)
    before = time.time()
    await _handle_message(_Sio(), "sporeprint/climate-01/telemetry",
                          {"ts": time.time() - 1800, "temp_f": 70.0, "replay": True})
    assert (await _node_row("climate-01"))["last_seen"] >= before


async def test_telemetry_does_not_change_status_or_register_nodes(rules_spy):
    # Recovery (status 'online') stays with the heartbeat/status path, and an
    # unknown node id is never registered from telemetry — registration gates
    # keyless camera uploads (auth._camera_frame_rejection).
    await _register_node("climate-01", time.time() - 3600, status="offline")
    await _handle_message(_Sio(), "sporeprint/climate-01/telemetry",
                          {"ts": time.time(), "temp_f": 71.5})
    assert (await _node_row("climate-01"))["status"] == "offline"

    await _handle_message(_Sio(), "sporeprint/stranger-01/telemetry",
                          {"ts": time.time(), "temp_f": 71.5})
    await _handle_message(_Sio(), "sporeprint/stranger-02/telemetry/fae",
                          {"channel": "fae", "state": "off"})
    assert await _node_row("stranger-01") is None
    assert await _node_row("stranger-02") is None


async def test_alert_still_emitted_to_socket(ntfy_posts):
    sio = _Sio()
    await _handle_message(sio, "sporeprint/climate-01/alert",
                          {"type": "temperature", "value": 93.0, "message": "hot"})
    assert sio.named("alert") == [
        {"node_id": "climate-01", "type": "temperature", "value": 93.0, "message": "hot"}
    ]
