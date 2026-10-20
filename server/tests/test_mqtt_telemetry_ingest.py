"""Telemetry ingest contract: the frame's ts, session tagging, replay/late
frames, storage failures, liveness, outdoor enrichment and node alerts.

Shared wire contract (firmware <-> Pi):
  * `ts` is Unix-epoch seconds once the node's clock is NTP-synced; unsynced
    frames keep an uptime-based ts. Any ts < 1_000_000_000 is unsynced and the
    Pi stamps arrival time.
  * Frames replayed from the node's offline buffer carry `"replay": true`.
  * Replayed frames, and frames older than the node's newest live frame, are
    STORED but never evaluated by the rules engine and never overwrite a newer
    latest reading. How far a ts is from the Pi's clock never matters (see
    test_mqtt_clock_skew.py).
"""

import math
import sqlite3
import time
from contextlib import asynccontextmanager

import pytest

from app.automation import engine
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.db import get_db
from app.mqtt import _handle_message, get_reliability_counters
from app.sessions.models import SessionCreate
from app.sessions.service import create_session, resolve_session_node_id
from app.telemetry.service import get_latest
from app.transcript.service import export_json
from tests._pi_b1_mqtt import (
    RecordingSio,
    capture_ntfy,
    insert_node,
    node_row,
    readings,
    spy_ingest,
)

DAY = 86400


@pytest.fixture()
def ingest(monkeypatch):
    return spy_ingest(monkeypatch)


def _latest(rows, sensor):
    return next(r["value"] for r in rows if r["sensor"] == sensor)


async def _feed(node_id: str, sio=None, **frame):
    await _handle_message(sio or RecordingSio(), f"sporeprint/{node_id}/telemetry",
                          {"ts": time.time(), **frame})


# ── the frame's ts ───────────────────────────────────────────────


@pytest.mark.parametrize("ts,stored_at,clamps", [
    (5000, "arrival", 1),                 # firmware uptime, no NTP sync yet
    (999_999_999, "arrival", 1),          # the last value read as uptime
    (1_000_000_000, "own", 0),            # the epoch floor: a synced (very wrong) clock
    (None, "arrival", 0),                 # no ts at all
    ("soon", "arrival", 0),               # garbled
], ids=["uptime", "below-epoch-floor", "epoch-floor", "missing", "not-a-number"])
async def test_frame_ts_decides_the_stored_time(ingest, ts, stored_at, clamps):
    """An unsynced, missing or garbled ts is replaced with the arrival time;
    a synced one is kept, however far from the Pi's clock. Either way the
    frame is live: the Pi's clock never keeps a frame from the safety checks."""
    sio = RecordingSio()
    before = get_reliability_counters()["uptime_ts_clamps"]
    frame = {"humidity": 50.0} if ts is None else {"humidity": 50.0, "ts": ts}
    t0 = time.time()
    await _handle_message(sio, "sporeprint/n1/telemetry", frame)
    t1 = time.time()

    ((row,),) = [await readings("n1", "humidity")]
    if stored_at == "own":
        assert row["timestamp"] == ts
    else:
        assert t0 <= row["timestamp"] <= t1
    (emitted,) = sio.named("telemetry")
    assert emitted["ts"] == row["timestamp"]
    assert [n for n, _ in ingest.rules] == ["n1"]
    assert get_reliability_counters()["uptime_ts_clamps"] == before + clamps
    # Only the node's own clock is checked for skew.
    skew = get_reliability_counters()["node_clock_skew"]
    assert ("n1" in skew) == (stored_at == "own")
    if stored_at == "own":
        assert skew["n1"]["skewed"] is True


# ── session tagging ──────────────────────────────────────────────


@pytest.mark.parametrize("grow,frame_age,replay,tagged", [
    (False, None, False, False),          # no grow running
    (True, None, False, True),            # a live frame, now
    (True, 3600, True, False),            # replayed from before the grow began
    (True, 600, False, False),            # live, from a clock lagging the grow's start
], ids=["no-grow", "live", "replay-before-grow", "lagging-clock-before-grow"])
async def test_a_reading_is_tagged_with_the_grow_running_at_its_ts(
        ingest, grow, frame_age, replay, tagged):
    """A session started after the frame's ts does not claim the reading."""
    session = (await create_session(SessionCreate(name="Tag me", species_profile_id="blue_oyster"))
               if grow else None)
    # Relative to the session's own created_at (SQLite's clock), never to the
    # test process's clock.
    ts = time.time() if frame_age is None else session["created_at"] - frame_age
    frame = {"temp_f": 60.0, "ts": ts, **({"replay": True} if replay else {})}
    await _handle_message(RecordingSio(), "sporeprint/climate-01/telemetry", frame)
    (row,) = await readings("climate-01", "temp_f")
    assert row["session_id"] == (session["id"] if tagged else None)


async def _chambered_session(name: str, node_ids: list[str]) -> dict:
    chamber = await create_chamber(ChamberCreate(name=name, node_ids=node_ids))
    return await create_session(SessionCreate(
        name=f"{name} grow", species_profile_id="blue_oyster", chamber_id=chamber["id"],
    ))


async def test_concurrent_chambered_sessions_tag_their_own_nodes(ingest):
    """Each chamber's node is tagged with its own chamber's grow, never the newest."""
    sa = await _chambered_session("A", ["node-a"])
    sb = await _chambered_session("B", ["node-b"])  # created last
    for _ in range(3):
        await _feed("node-b", temp_f=60.0)
        await _feed("node-a", temp_f=85.0)

    assert {r["session_id"] for r in await readings("node-a", "temp_f")} == {sa["id"]}
    assert {r["session_id"] for r in await readings("node-b", "temp_f")} == {sb["id"]}
    # Downstream consumers resolve each session to its own chamber's node.
    assert await resolve_session_node_id(sb["id"], "temp_f") == "node-b"
    assert await resolve_session_node_id(sa["id"], "temp_f") == "node-a"
    summary = (await export_json(sb["id"]))["phase_telemetry"][0]["telemetry_summary"]
    assert summary["temp_f"] == {"min": 60.0, "max": 60.0, "avg": 60.0, "count": 3}


async def test_node_in_idle_chamber_is_not_tagged_with_another_chambers_grow(ingest):
    await create_chamber(ChamberCreate(name="Idle", node_ids=["node-idle"]))
    await _chambered_session("Busy", ["node-busy"])
    await _feed("node-idle", temp_f=70.0)
    assert (await readings("node-idle", "temp_f"))[0]["session_id"] is None


async def test_chambered_node_is_tagged_with_the_chamberless_grow_it_drives(ingest):
    """A chamber with no grow of its own runs the newest chamberless session
    (sessions.service.get_active_session_for_chambers), and the readings the
    engine runs that grow on belong to its history. A stricter second copy of
    the rule stored them untagged, and the grow's charts stayed empty."""
    await create_chamber(ChamberCreate(name="Tent", node_ids=["node-tent"]))
    loose = await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    await _chambered_session("Closet", ["node-closet"])  # a grow of its own
    await _feed("node-tent", temp_f=70.0)
    await _feed("node-closet", temp_f=50.0)
    assert (await readings("node-tent", "temp_f"))[0]["session_id"] == loose["id"]
    assert (await readings("node-closet", "temp_f"))[0]["session_id"] != loose["id"]
    summary = (await export_json(loose["id"]))["phase_telemetry"][0]["telemetry_summary"]
    assert summary["temp_f"]["count"] == 1
    # Once the raw rows have aged into rollups (which carry no session_id),
    # the grow still resolves to the chamber it runs, not to every node.
    async with get_db() as db:
        await db.execute("UPDATE telemetry_readings SET session_id = NULL")
        await db.commit()
    assert await resolve_session_node_id(loose["id"], "temp_f") == "node-tent"
    summary = (await export_json(loose["id"]))["phase_telemetry"][0]["telemetry_summary"]
    assert summary["temp_f"]["min"] == 70.0


async def test_unchambered_node_goes_to_chamberless_grow_not_a_chambered_one(ingest):
    loose = await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    await _chambered_session("Tent", ["node-tent"])  # newer, but not this node's
    await _feed("node-shelf", temp_f=70.0)
    assert (await readings("node-shelf", "temp_f"))[0]["session_id"] == loose["id"]


async def test_unchambered_node_untagged_when_only_chambered_grows_are_active(ingest):
    await _chambered_session("Tent", ["node-tent"])
    await _feed("node-shelf", temp_f=70.0)
    assert (await readings("node-shelf", "temp_f"))[0]["session_id"] is None


async def test_malformed_chamber_node_ids_do_not_break_ingest(ingest):
    loose = await create_session(SessionCreate(name="Loose", species_profile_id="blue_oyster"))
    async with get_db() as db:
        await db.execute("INSERT INTO chambers (name, node_ids) VALUES ('Bad', 'not json')")
        await db.commit()
    await _feed("climate-01", temp_f=70.0)
    assert (await readings("climate-01", "temp_f"))[0]["session_id"] == loose["id"]
    assert len(ingest.rules) == 1


async def test_a_live_frame_resolves_its_grow_once_for_the_tag_and_the_rules(monkeypatch):
    """The readings' tag and the rules engine share one lookup of the node's
    grow: the ingest hands the grow it tagged with to the real evaluate_rules,
    which used to resolve it again (two more database connections on every
    frame)."""
    grow = await _chambered_session("Tent", ["node-tent"])
    lookups, handed = [], []
    resolve, run_rules = engine._session_for_node, engine.evaluate_rules
    spy_ingest(monkeypatch)  # the cloud relay and weather; the engine is wrapped below

    async def _counted(node_id):
        lookups.append(node_id)
        return await resolve(node_id)

    async def _rules(node_id, readings, sio=None, *, node_session=None):
        handed.append(node_session)
        await run_rules(node_id, readings, sio, node_session=node_session)

    monkeypatch.setattr("app.automation.engine._session_for_node", _counted)
    monkeypatch.setattr("app.automation.engine.evaluate_rules", _rules)
    capture_ntfy(monkeypatch)

    await _feed("node-tent", temp_f=70.0)

    assert lookups == ["node-tent"]
    ((session, chamber_nodes),) = handed
    assert session["id"] == grow["id"] and chamber_nodes == ["node-tent"]
    assert (await readings("node-tent", "temp_f"))[0]["session_id"] == grow["id"]


# ── replay / late frames ─────────────────────────────────────────


async def test_synced_replay_frame_stored_at_its_time_not_evaluated(ingest):
    sio = RecordingSio()
    now = time.time()
    # Fresh reading first (the firmware publishes live, then flushes its buffer).
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 88.0, "ts": now})
    await _handle_message(sio, "sporeprint/climate-01/telemetry",
                          {"humidity": 70.0, "ts": now - 1800, "replay": True})

    # Rules ran on the live frame only.
    assert [r["humidity"] for _, r in ingest.rules] == [88.0]
    # Only the live frame went out on the local live socket.
    assert [d["humidity"] for d in sio.named("telemetry")] == [88.0]
    # The cloud relay gets both (its history stays whole), the late one with
    # its real ts and marked as not live.
    assert [(p["humidity"], round(p["ts"]), p.get("replay")) for _, p in ingest.forwards] == [
        (88.0, round(now), None), (70.0, round(now - 1800), True)
    ]
    # Both are stored, each at its own time.
    rows = await readings("climate-01", "humidity")
    assert [(round(r["timestamp"]), r["value"]) for r in rows] == [
        (round(now - 1800), 70.0), (round(now), 88.0)
    ]
    # The latest reading is still the fresh one.
    assert _latest(await get_latest("climate-01"), "humidity") == 88.0


@pytest.mark.parametrize("live_ts,late_ts", [
    (lambda now: 5000, lambda now: 4000),            # both on uptime clocks
    (lambda now: now, lambda now: now + 30 * DAY),   # a replay from a bogus future sync
    (None, lambda now: 4000),                        # nothing stored before it
], ids=["uptime-replay", "far-future-replay", "first-frame-replay"])
async def test_a_late_frame_stamped_on_arrival_never_shadows_the_latest_reading(
        ingest, live_ts, late_ts):
    """A replayed frame whose own ts cannot be stored (unsynced, or far in
    the future) is stamped just before the node's newest stored reading, so
    the live reading stays the latest."""
    now = time.time()
    if live_ts is not None:
        await _feed("climate-01", humidity=88.0, ts=live_ts(now))
    t0 = time.time()
    await _feed("climate-01", humidity=70.0, ts=late_ts(now), replay=True)

    rows = await readings("climate-01", "humidity")
    late = next(r for r in rows if r["value"] == 70.0)
    assert late["timestamp"] <= time.time()
    assert [r["humidity"] for _, r in ingest.rules] == ([88.0] if live_ts else [])
    if live_ts is None:
        assert late["timestamp"] >= t0
    else:
        assert _latest(await get_latest("climate-01"), "humidity") == 88.0
        assert late["timestamp"] < next(r for r in rows if r["value"] == 88.0)["timestamp"]


async def test_a_reading_that_is_not_a_finite_number_does_not_cost_the_frame(ingest):
    """A NaN dew point arrives as JSON null (RH read 0): it is skipped, and
    the frame's other readings are stored. One NOT NULL failure used to roll
    back the whole frame. A door state is stored as 1.0 / 0.0."""
    before = get_reliability_counters()["skipped_readings"]
    await _feed("climate-01", temp_f=71.0, humidity=0.0, co2_ppm=812, door_open=True,
                dew_point_f=None, lux=float("nan"), temp_c=float("inf"),
                weight_g="12", pressure_hpa=10 ** 400, unrelated=5)
    stored = {r["sensor"]: r["value"] for r in await readings("climate-01")}
    assert stored == {"temp_f": 71.0, "humidity": 0.0, "co2_ppm": 812.0, "door_open": 1.0}
    assert get_reliability_counters()["skipped_readings"] == before + 5


@asynccontextmanager
async def _locked_db():
    raise sqlite3.OperationalError("database is locked")
    yield  # pragma: no cover


@pytest.mark.parametrize("failure", ["insert", "transaction"])
async def test_a_storage_failure_never_costs_a_live_frame_its_rules(
        ingest, monkeypatch, failure):
    """A write lock held by the nightly retention job must not skip
    automation (safety cutoffs included). A failed insert alone does not
    cost the node its liveness either."""
    async def _insert_fails(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    if failure == "insert":
        monkeypatch.setattr("app.mqtt.insert_readings", _insert_fails)
    else:
        monkeypatch.setattr("app.mqtt.get_db", _locked_db)
    stale = time.time() - 3600
    await insert_node("climate-01", last_seen=stale)
    before = time.time()
    sio = RecordingSio()
    await _feed("climate-01", sio, temp_f=95.0)

    assert [r["temp_f"] for _, r in ingest.rules] == [95.0]
    assert len(sio.named("telemetry")) == 1
    assert await readings("climate-01") == []
    last_seen = (await node_row("climate-01"))["last_seen"]
    assert last_seen >= before if failure == "insert" else last_seen == stale


async def test_outdoor_weather_joins_the_readings_the_rules_see(ingest, monkeypatch):
    """The rules may threshold on outdoor_* / forecast_* values; they are
    added for the rules only, never stored as the node's readings."""
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: {
        "outdoor_temp_f": 41.0, "outdoor_humidity": None, "forecast_high_f": 55.0,
        "condition": "rain"})
    await _feed("climate-01", temp_f=70.0)
    ((_, seen),) = ingest.rules
    assert seen["outdoor_temp_f"] == 41.0 and seen["forecast_high_f"] == 55.0
    assert "outdoor_humidity" not in seen and "condition" not in seen
    assert {r["sensor"] for r in await readings("climate-01")} == {"temp_f"}


# ── liveness: telemetry refreshes last_seen ──────────────────────
#
# The liveness sweeper (main._node_liveness_sweeper) pages node_offline once
# hardware_nodes.last_seen is 15 min stale. Only status/* frames used to touch
# it, so a node whose heartbeats stop reaching the Pi (or older firmware) was
# paged offline while its telemetry was arriving every minute.


@pytest.mark.parametrize("suffix,frame", [
    ("telemetry", {"temp_f": 71.5}),
    ("telemetry/fae", {"channel": "fae", "state": "on", "pwm": 255, "trigger": "report"}),
    # The reading is old, but its arrival is now.
    ("telemetry", {"temp_f": 70.0, "ts_age": 1800, "replay": True}),
], ids=["sensor-frame", "switch-report", "replayed-frame"])
async def test_every_telemetry_frame_refreshes_a_registered_nodes_last_seen(
        ingest, suffix, frame):
    await insert_node("node-1", last_seen=time.time() - 3600)
    frame = dict(frame)
    if suffix == "telemetry":
        frame["ts"] = time.time() - frame.pop("ts_age", 0)
    before = time.time()
    await _handle_message(RecordingSio(), f"sporeprint/node-1/{suffix}", frame)
    assert (await node_row("node-1"))["last_seen"] >= before


async def test_telemetry_does_not_change_status_or_register_nodes(ingest):
    # Recovery (status 'online') stays with the heartbeat/status path, and an
    # unknown node id is never registered from telemetry — registration gates
    # keyless camera uploads (auth._camera_frame_rejection).
    await insert_node("climate-01", last_seen=time.time() - 3600, status="offline")
    await _feed("climate-01", temp_f=71.5)
    assert (await node_row("climate-01"))["status"] == "offline"

    await _feed("stranger-01", temp_f=71.5)
    await _handle_message(RecordingSio(), "sporeprint/stranger-02/telemetry/fae",
                          {"channel": "fae", "state": "off"})
    assert await node_row("stranger-01") is None
    assert await node_row("stranger-02") is None


# ── node alerts reach ntfy ───────────────────────────────────────


@pytest.fixture()
def ntfy_posts(monkeypatch):
    return capture_ntfy(monkeypatch)


@pytest.mark.parametrize("alert_type,value,priority", [
    ("temperature", 93.0, 5),
    ("co2", 4500.0, 5),
    ("sensor_failure", 0.0, 5),
    ("humidity", 25.0, 4),
    ("door", 1.0, 3),                  # opened
    ("door", 0.0, None),               # closed: not pushed
    ("door", "ajar", None),            # not a reading: not an opening
    ("smoke", 1.0, 4),                 # a type from newer firmware pages, as a warning
])
async def test_a_node_alert_pages_at_its_tier(ntfy_posts, alert_type, value, priority):
    sio = RecordingSio()
    frame = {"type": alert_type, "value": value, "message": "limit"}
    await _handle_message(sio, "sporeprint/climate-01/alert", frame)
    assert [p["priority"] for p in ntfy_posts] == ([priority] if priority else [])
    if priority:
        assert "climate-01" in ntfy_posts[0]["title"]
    # Every alert reaches local clients, named by its topic.
    assert sio.named("alert") == [{**frame, "node_id": "climate-01"}]


async def test_repeated_alert_is_deduped_per_node_and_type(ntfy_posts):
    for _ in range(5):  # the firmware re-emits every read cycle
        await _handle_message(RecordingSio(), "sporeprint/climate-01/alert",
                              {"type": "temperature", "value": 95.0, "message": "hot"})
    await _handle_message(RecordingSio(), "sporeprint/climate-02/alert",
                          {"type": "temperature", "value": 95.0, "message": "hot"})
    await _handle_message(RecordingSio(), "sporeprint/climate-01/alert",
                          {"type": "co2", "value": 5000.0, "message": "co2"})
    assert len(ntfy_posts) == 3


async def test_sensor_failures_of_different_sensors_each_page(ntfy_posts):
    """One alert type covers several sensors; one failure must not mask the next."""
    for sensor in ("SCD4x", "SCD4x", "BH1750", "HX711"):
        await _handle_message(RecordingSio(), "sporeprint/climate-01/alert", {
            "type": "sensor_failure", "value": 0.0,
            "message": "sensor stale - no fresh reading", "sensor": sensor,
        })
    assert [p["title"] for p in ntfy_posts] == [
        "Node climate-01: sensor failure alert (SCD4x)",
        "Node climate-01: sensor failure alert (BH1750)",
        "Node climate-01: sensor failure alert (HX711)",
    ]


# ── lighting channel-level reports ────────────────────────────────
# A lighting bank publishes its channel levels on the bare telemetry topic
# (on every command and every ramp step). They are live actuator state, not
# readings: each used to run the full sensor path (session lookup, store,
# weather enrichment, rules).


@pytest.mark.parametrize("payload", [
    # Current firmware: marked, with the node's ts.
    {"ts": 1_760_000_000, "report": "dim_levels", "white": 800, "blue": 0,
     "red": 120, "far_red": 40},
    # Earlier images: channel keys only, no ts.
    {"white": 800, "blue": 0, "red": 120, "far_red": 40},
])
async def test_level_report_is_forwarded_live_but_never_evaluated_or_stored(
        ingest, payload, monkeypatch):
    sessions_looked_up = []

    async def _no_session_lookup(node_id, ts):
        sessions_looked_up.append(node_id)
        return None

    monkeypatch.setattr("app.mqtt.active_session_for_node", _no_session_lookup)
    await insert_node("light-01", last_seen=time.time() - 3600)
    sio = RecordingSio()
    before = time.time()
    await _handle_message(sio, "sporeprint/light-01/telemetry", dict(payload))

    assert ingest.rules == []           # no rules evaluated on it
    assert sessions_looked_up == []     # no grow to tag it with
    assert await readings("light-01") == []
    # Still live: the socket and the cloud get it, with a usable ts.
    (emitted,) = sio.named("telemetry")
    assert emitted["node_id"] == "light-01" and emitted["white"] == 800
    assert math.isfinite(emitted["ts"]) and emitted["ts"] >= 1_000_000_000
    assert [n for n, _ in ingest.forwards] == ["light-01"]
    assert (await node_row("light-01"))["last_seen"] >= before


async def test_sensorless_periodic_frame_still_drives_the_rules(ingest):
    # A relay or lighting node's periodic frame carries only its ts. The rules
    # engine runs per telemetry frame, so schedule rules (photoperiod, the
    # scheduled FAE cycle) in a chamber without a climate node depend on it.
    await _feed("light-01")
    assert [n for n, _ in ingest.rules] == ["light-01"]
