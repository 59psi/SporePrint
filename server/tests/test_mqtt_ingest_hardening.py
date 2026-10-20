"""MQTT ingest edge cases: frames that must not take the loop down, retained
replays, the topic as the node's identity, OTA and health bookkeeping, the
node's transport security, and firmware alerts that are normal for the grow.
"""

import asyncio
import hashlib
import json
import time

import pytest

import app.cloud.service as cloud_service
import app.mqtt
from app import provision
from app.automation.models import RuleAction
from app.automation.service import validate_action_channel
from app.automation.smart_plugs import target_is_present
from app.chambers.models import ChamberUpdate
from app.chambers.service import update_chamber
from app.db import get_db
from app.mqtt import _decode_payload, _handle_message, start_mqtt
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, create_session
from app.species.service import seed_builtins


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event):
        return [d for e, d in self.events if e == event]


async def _node(node_id: str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _insert_node(node_id: str, **columns):
    cols = {"node_type": "climate", **columns}
    names = ", ".join(["node_id", *cols])
    marks = ", ".join("?" for _ in range(len(cols) + 1))
    async with get_db() as db:
        await db.execute(f"INSERT INTO hardware_nodes ({names}) VALUES ({marks})",
                         (node_id, *cols.values()))
        await db.commit()


# ── frames json.loads cannot build ────────────────────────────────────────


@pytest.mark.parametrize("topic", [
    "tasmota/x/stat/POWER", "shellies/x/relay/0", "sporeprint/node-a1/telemetry",
])
@pytest.mark.parametrize("raw", [
    b"[" * 20_000,                                # nested past the recursion limit
    b'{"ts": ' + b"9" * 5_000 + b"}",             # an integer past the digit limit
])
def test_decode_drops_a_payload_json_cannot_build(topic, raw):
    assert _decode_payload(topic, raw) is None


def test_decode_drops_an_oversized_payload():
    raw = json.dumps({"ts": 1, "msg": "x" * (70 * 1024)}).encode()
    assert _decode_payload("sporeprint/node-a1/logs", raw) is None
    assert _decode_payload("tasmota/x/stat/POWER", b"O" * (70 * 1024)) is None


class _Message:
    def __init__(self, topic: str, payload: bytes, retain: bool = False):
        self.topic = topic
        self.payload = payload
        self.retain = retain


def _client_factory(messages: list[_Message], connects: list[int]):
    """An aiomqtt.Client stand-in that redelivers `messages` on every connect,
    as the broker does a retained frame on every (re)subscribe."""

    class _Client:
        def __init__(self, *args, **kwargs):
            connects.append(1)

        async def __aenter__(self):
            if len(connects) > 1:  # a second session: the loop was restarted
                raise asyncio.CancelledError
            return self

        async def __aexit__(self, *exc):
            return False

        async def subscribe(self, topic):
            return None

        @property
        def messages(self):
            async def _gen():
                for m in messages:
                    yield m
                raise asyncio.CancelledError

            return _gen()

    return _Client


@pytest.mark.parametrize("poison_topic,poison", [
    ("tasmota/x/stat/POWER", b"[" * 20_000),
    ("sporeprint/node-a1/telemetry", b'{"ts": ' + b"9" * 5_000 + b"}"),
])
async def test_a_poison_retained_frame_does_not_restart_the_session(
        monkeypatch, poison_topic, poison):
    connects: list[int] = []
    restarts = app.mqtt._mqtt_restart_count
    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", _client_factory([
        _Message(poison_topic, poison, retain=True),
        _Message("sporeprint/node-b2/status", b'{"status": "online"}'),
    ], connects))
    await asyncio.wait_for(start_mqtt(_Sio()), timeout=3)
    assert connects == [1]
    assert app.mqtt._mqtt_restart_count == restarts
    # The frame after the poison one was handled.
    assert (await _node("node-b2"))["status"] == "online"


async def test_the_retained_flag_reaches_the_status_handler(monkeypatch):
    stale = time.time() - 3 * 86400
    await _insert_node("node-c3", status="online", last_seen=stale)
    connects: list[int] = []
    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", _client_factory([
        _Message("sporeprint/node-c3/status", b'{"status": "online"}', retain=True),
    ], connects))
    await asyncio.wait_for(start_mqtt(_Sio()), timeout=3)
    assert (await _node("node-c3"))["last_seen"] == stale


# ── retained status frames are not the node talking ───────────────────────


async def test_a_replayed_retained_lwt_leaves_last_seen_alone():
    stale = time.time() - 3 * 86400
    await _insert_node("node-d4", status="offline", last_seen=stale)
    await _handle_message(_Sio(), "sporeprint/node-d4/status", {"status": "offline"},
                          retained=True)
    row = await _node("node-d4")
    assert row["status"] == "offline" and row["last_seen"] == stale


async def test_a_live_lwt_records_offline_without_refreshing_last_seen():
    seen = time.time() - 120
    await _insert_node("node-d4", status="online", last_seen=seen)
    await _handle_message(_Sio(), "sporeprint/node-d4/status", {"status": "offline"})
    row = await _node("node-d4")
    assert row["status"] == "offline" and row["last_seen"] == seen


async def test_a_live_online_refreshes_last_seen():
    await _insert_node("node-d4", status="offline", last_seen=time.time() - 3600)
    before = time.time()
    await _handle_message(_Sio(), "sporeprint/node-d4/status", {"status": "online"})
    row = await _node("node-d4")
    assert row["status"] == "online" and row["last_seen"] >= before


async def test_a_retained_status_of_an_unknown_node_does_not_look_fresh():
    await _handle_message(_Sio(), "sporeprint/node-e5/status", {"status": "online"},
                          retained=True)
    row = await _node("node-e5")
    assert row["status"] == "online" and row["last_seen"] is None


# ── the topic names the node, never its payload ───────────────────────────


@pytest.fixture()
def quiet_cloud(monkeypatch):
    forwarded: list[tuple[str, dict]] = []

    async def _event(event_type, data, **kw):
        forwarded.append((event_type, data))
        return True

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr("app.mqtt.forward_event", _event)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _noop)
    monkeypatch.setattr("app.mqtt.forward_component_health", _noop)
    monkeypatch.setattr("app.automation.engine.evaluate_rules", _noop)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)
    return forwarded


async def test_a_payload_node_id_never_names_another_node(quiet_cloud):
    sio = _Sio()
    spoof = {"node_id": "node-b"}
    await _handle_message(sio, "sporeprint/node-a/telemetry",
                          {**spoof, "ts": time.time(), "co2_ppm": 450})
    await _handle_message(sio, "sporeprint/node-a/telemetry/fae",
                          {**spoof, "channel": "fae", "state": "off"})
    await _handle_message(sio, "sporeprint/node-a/health", {**spoof, "uptime_sec": 5})
    await _handle_message(sio, "sporeprint/node-a/alert",
                          {**spoof, "type": "door", "value": 0.0})
    for event in ("telemetry", "actuator_state", "component_health", "alert"):
        assert [d["node_id"] for d in sio.named(event)] == ["node-a"], event
    assert [d["node_id"] for e, d in quiet_cloud if e == "alert"] == ["node-a"]


async def test_cloud_forwards_name_the_topic_node(monkeypatch):
    queue: asyncio.Queue = asyncio.Queue()
    emitted: list[tuple[str, dict]] = []

    class _Relay:
        async def emit(self, event, data):
            emitted.append((event, data))

    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.test")
    monkeypatch.setattr(cloud_service, "_queue", queue)
    monkeypatch.setattr(cloud_service, "_connector_running", True)
    monkeypatch.setattr(cloud_service, "_standing_refusal", None)
    monkeypatch.setattr(cloud_service, "_connected", False)
    await cloud_service.forward_telemetry(
        "node-a", {"node_id": "node-b", "ts": 1_760_000_000.0, "temp_f": 70.0})
    msg = queue.get_nowait()
    assert msg["node_id"] == "node-a" and msg["ts"] == 1_760_000_000.0

    monkeypatch.setattr(cloud_service, "_connected", True)
    monkeypatch.setattr(cloud_service, "_sio", _Relay())
    await cloud_service.forward_component_health("node-a", {"node_id": "node-b"})
    assert [(e, d["node_id"]) for e, d in emitted] == [("component_health", "node-a")]


# ── OTA lifecycle events keep the node_ota envelope ───────────────────────


async def test_an_ota_start_is_forwarded_as_node_ota_with_the_pi_clock(monkeypatch):
    emitted: list[tuple[str, dict]] = []

    class _Relay:
        async def emit(self, event, data):
            emitted.append((event, data))

    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.test")
    monkeypatch.setattr(cloud_service, "_connected", True)
    monkeypatch.setattr(cloud_service, "_sio", _Relay())
    sio = _Sio()
    before = time.time()
    await _handle_message(sio, "sporeprint/node-a/ota",
                          {"event": "start", "ts": 1234, "type": "firmware"})
    ((event, data),) = emitted
    assert event == "event"
    assert data["type"] == "node_ota" and data["event"] == "start"
    assert data["ts"] >= before
    assert data["ota_type"] == "firmware" and data["node_ts"] == 1234
    assert data["node_id"] == "node-a"
    # The local socket still gets the node's own frame.
    assert sio.named("node_ota") == [
        {"event": "start", "ts": 1234, "type": "firmware", "node_id": "node-a"}]


# ── a health doc without channels clears a stale channel list ─────────────


async def test_a_node_reprovisioned_without_channels_loses_its_old_ones(quiet_cloud):
    relay_health = {"channels": {name: {"state": False, "pwm": 0}
                                 for name in ("fae", "exhaust", "circulation", "aux")}}
    await _handle_message(_Sio(), "sporeprint/node-ab12/status/heartbeat",
                          {"type": "relay", "roles": ["relay"]})
    await _handle_message(_Sio(), "sporeprint/node-ab12/health", relay_health)
    assert json.loads((await _node("node-ab12"))["channels"]) == [
        "aux", "circulation", "exhaust", "fae"]
    # Re-provisioned as a climate node: its health doc lists no channels.
    await _handle_message(_Sio(), "sporeprint/node-ab12/status/heartbeat",
                          {"type": "climate", "roles": ["climate"]})
    await _handle_message(_Sio(), "sporeprint/node-ab12/health", {"sensors": {}})
    assert (await _node("node-ab12"))["channels"] == "[]"
    error = await validate_action_channel(
        RuleAction(target="node-ab12", channel="fae", state="on"))
    assert error is not None
    assert await target_is_present("fae") is False


async def test_a_node_that_never_listed_channels_stays_unreported(quiet_cloud):
    await _handle_message(_Sio(), "sporeprint/climate-01/status/heartbeat",
                          {"type": "climate", "roles": ["climate"]})
    await _handle_message(_Sio(), "sporeprint/climate-01/health", {"sensors": {}})
    assert (await _node("climate-01"))["channels"] is None


# ── the node's transport security ─────────────────────────────────────────


_PEM = "-----BEGIN CERTIFICATE-----\nMIIBpi\n-----END CERTIFICATE-----\n"


@pytest.fixture()
def served_ca(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text(_PEM)
    monkeypatch.setattr(provision, "_CA_PATHS", (tmp_path / "absent.crt", ca))
    return hashlib.sha256(_PEM.encode()).hexdigest()


def _heartbeat(**extra):
    return {"type": "climate", "roles": ["climate"], "firmware_version": "5.2.2",
            "ip": "10.0.0.20", **extra}


async def test_heartbeat_records_the_nodes_transport_security(served_ca):
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat", _heartbeat(
        tls=True, board="esp32-wroom-32", ca_fp=served_ca))
    row = await _node("node-f6")
    assert (row["tls"], row["tls_fallback"], row["board"]) == (1, 0, "esp32-wroom-32")
    assert row["ca_fp"] == served_ca and row["ca_fp_match"] == 1


async def test_a_node_pinned_to_another_ca_is_flagged(served_ca, caplog):
    other = hashlib.sha256(b"someone else's CA").hexdigest()
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp=other))
    assert (await _node("node-f6"))["ca_fp_match"] == 0
    assert "node-f6 verifies the broker against CA" in caplog.text
    # Once per fingerprint, not every minute.
    caplog.clear()
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp=other))
    assert "verifies the broker" not in caplog.text


async def test_a_plaintext_fallback_and_an_older_image(served_ca):
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=False, tls_fallback=True))
    row = await _node("node-f6")
    assert (row["tls"], row["tls_fallback"], row["ca_fp"], row["ca_fp_match"]) == (
        0, 1, None, None)
    # An image that reports no transport at all.
    await _handle_message(_Sio(), "sporeprint/node-g7/status/heartbeat", _heartbeat())
    row = await _node("node-g7")
    assert (row["tls"], row["tls_fallback"], row["board"]) == (None, None, None)


async def test_a_malformed_fingerprint_is_not_stored(served_ca):
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp="not-a-digest"))
    row = await _node("node-f6")
    assert row["ca_fp"] is None and row["ca_fp_match"] is None


async def test_the_nodes_api_reports_the_ca_check(served_ca, client):
    await _handle_message(_Sio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp=served_ca))
    (node,) = [n for n in client.get("/api/hardware/nodes").json()
               if n["node_id"] == "node-f6"]
    assert node["ca_fp_match"] == 1 and node["tls"] == 1


# ── firmware limits that are normal for the grow's phase ──────────────────


@pytest.fixture()
def ntfy_posts(monkeypatch):
    posts: list[dict] = []

    class _Response:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, timeout=None, **kw):
            posts.append({"title": json["title"], "priority": json["priority"]})
            return _Response()

    from app.config import settings
    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr("app.notifications.service.httpx.AsyncClient", _Client)

    async def _noop_forward(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_event", _noop_forward)
    return posts


async def _alert(node_id: str, alert_type: str, value: float):
    await _handle_message(_Sio(), f"sporeprint/{node_id}/alert",
                          {"type": alert_type, "value": value, "message": "limit"})


async def _grow(species: str, phase: str, container: str = "monotub", chamber_id=None):
    await seed_builtins()
    return await create_session(SessionCreate(
        name=species, species_profile_id=species, substrate="straw",
        current_phase=phase, container_type=container, chamber_id=chamber_id))


async def test_colonization_co2_without_fresh_air_is_not_paged(ntfy_posts):
    await _grow("shaggy_mane", "substrate_colonization")  # fae none, up to 10000 ppm
    await _alert("climate-01", "co2", 9800.0)
    assert ntfy_posts == []


async def test_co2_within_the_phase_ceiling_is_not_paged_but_above_it_is(ntfy_posts):
    await _grow("blue_oyster", "substrate_colonization")  # passive, up to 5000 ppm
    await _alert("climate-01", "co2", 4500.0)
    assert ntfy_posts == []
    await _alert("climate-01", "co2", 6000.0)
    assert [p["priority"] for p in ntfy_posts] == [5]


async def test_a_temperature_outside_the_phase_band_still_pages(ntfy_posts):
    await _grow("blue_oyster", "fruiting")  # 55-65 °F
    await _alert("climate-01", "temperature", 39.0)
    assert [p["priority"] for p in ntfy_posts] == [5]


async def test_a_fridge_at_cold_storage_temperature_is_not_paged(ntfy_posts):
    await seed_builtins()
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES ('Fridge', ?)",
            (json.dumps(["fridge-1"]),))
        await db.commit()
        fridge = cursor.lastrowid
    jar = await _grow("blue_oyster", "grain_colonization", container="grain_jar")
    await advance_phase(jar["id"], PhaseAdvance(phase="cold_storage"))
    await update_chamber(fridge, ChamberUpdate(active_session_id=jar["id"]))
    await _alert("fridge-1", "temperature", 36.0)   # inside 35-40 °F
    await _alert("fridge-1", "humidity", 25.0)      # a fridge idles dry
    assert ntfy_posts == []
    await _alert("fridge-1", "temperature", 33.0)   # freezing the jar
    assert [p["priority"] for p in ntfy_posts] == [5]


async def test_a_sealed_vessel_makes_room_co2_and_humidity_quiet(ntfy_posts):
    await _grow("blue_oyster", "substrate_colonization", container="grow_bag")
    await _alert("climate-01", "co2", 8000.0)
    await _alert("climate-01", "humidity", 20.0)
    assert ntfy_posts == []


async def test_with_no_grow_every_limit_pages(ntfy_posts):
    await _alert("climate-01", "co2", 4500.0)
    await _alert("climate-01", "temperature", 36.0)
    assert [p["priority"] for p in ntfy_posts] == [5, 5]


# ── node log retention ────────────────────────────────────────────────────


async def _log_count(node_id: str) -> int:
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM node_logs WHERE node_id = ?", (node_id,))
        return (await cursor.fetchone())[0]


async def _log_batch(node_id: str, n: int):
    await _handle_message(_Sio(), f"sporeprint/{node_id}/logs",
                          {"entries": [{"ts_ms": i, "level": 1, "msg": "x"} for i in range(n)]})


async def test_node_logs_are_trimmed_every_few_hundred_rows_not_every_batch():
    keep, every = app.mqtt._NODE_LOG_KEEP, app.mqtt._NODE_LOG_TRIM_EVERY
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO node_logs (node_id, ts_ms, level, msg) VALUES ('node-l1', ?, 1, 'old')",
            [(i,) for i in range(keep + 300)])
        await db.commit()
    await _log_batch("node-l1", 8)  # a node's first batch since the start trims
    assert await _log_count("node-l1") == keep
    batches = (every - 1) // 8
    for _ in range(batches):  # below the cadence: no trim, rows accumulate
        await _log_batch("node-l1", 8)
    assert await _log_count("node-l1") == keep + batches * 8
    await _log_batch("node-l1", 8)  # crosses it: trimmed back to the newest
    assert await _log_count("node-l1") == keep
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM node_logs WHERE node_id = 'node-l1' AND msg = 'old'")
        assert (await cursor.fetchone())[0] == keep - (batches + 2) * 8
