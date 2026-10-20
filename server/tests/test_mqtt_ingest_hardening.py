"""MQTT ingest edge cases: frames Python cannot build, retained status
replays, the topic as the node's identity, OTA and health bookkeeping, the
node's transport security, and firmware alerts that are normal for the grow.
(The supervisor loop itself is tested in test_mqtt.py.)
"""

import asyncio
import hashlib
import json
import logging
import time

import pytest

import app.cloud.service as cloud_service
from app import provision
from app.automation.models import RuleAction
from app.automation.service import validate_action_channel
from app.automation.smart_plugs import target_is_present
from app.chambers.models import ChamberUpdate
from app.chambers.service import update_chamber
from app.db import get_db
from app.mqtt import _decode_payload, _handle_message, get_reliability_counters
from app.sessions.models import PhaseAdvance, SessionCreate
from app.sessions.service import advance_phase, create_session
from app.species.service import seed_builtins
from tests._builders import node_row, register_node
from tests._fakes import RecordingSio

DAY = 86400


# ── frames json.loads cannot build ────────────────────────────────────────

_DEEP = b"[" * 20_000                           # nested past the recursion limit
_HUGE_INT = b'{"ts": ' + b"9" * 5_000 + b"}"    # an integer past the digit limit


@pytest.mark.parametrize("topic,raw", [
    ("tasmota/x/stat/POWER", _DEEP),
    ("sporeprint/node-a1/telemetry", _DEEP),
    ("tasmota/x/stat/POWER", _HUGE_INT),
    ("sporeprint/node-a1/telemetry", _HUGE_INT),
    ("sporeprint/node-a1/logs", json.dumps({"ts": 1, "msg": "x" * (70 * 1024)}).encode()),
    ("tasmota/x/stat/POWER", b"O" * (70 * 1024)),
], ids=["deep-vendor", "deep-node", "huge-int-vendor", "huge-int-node",
        "oversized-node", "oversized-vendor"])
def test_a_frame_that_cannot_be_built_is_dropped_and_counted(topic, raw):
    """Never raised: escaping the message loop, one such retained frame
    restarted the MQTT session on every reconnect. Counted under
    reliability.dropped_frames."""
    before = get_reliability_counters()["dropped_frames"]
    assert _decode_payload(topic, raw) is None
    assert get_reliability_counters()["dropped_frames"] == before + 1


# ── retained status frames are not the node talking ───────────────────────


@pytest.mark.parametrize("prior,status,retained,expected_status,last_seen", [
    (("offline", 3 * DAY), "offline", True, "offline", "kept"),   # a replayed, days-old LWT
    (("online", 120), "offline", False, "offline", "kept"),       # a live LWT: the node stopped
    (("offline", 3600), "online", False, "online", "fresh"),      # the node talking
    (None, "online", True, "online", None),                       # replayed, for an unknown node
], ids=["retained-lwt", "live-lwt", "live-online", "retained-online-unknown-node"])
async def test_only_a_live_online_status_refreshes_last_seen(
        prior, status, retained, expected_status, last_seen):
    """last_seen is when the node was last heard; a retained frame or an LWT
    used to stamp it with now, so a node gone for days read 'seen just now'
    after every Pi restart."""
    seen = None
    if prior:
        seen = time.time() - prior[1]
        await register_node("node-d4", "climate", status=prior[0], last_seen=seen)
    before = time.time()
    await _handle_message(RecordingSio(), "sporeprint/node-d4/status", {"status": status},
                          retained=retained)
    row = await node_row("node-d4")
    assert row["status"] == expected_status
    if last_seen == "fresh":
        assert row["last_seen"] >= before
    else:
        assert row["last_seen"] == seen


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
    sio = RecordingSio()
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
    relay = RecordingSio()
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
    monkeypatch.setattr(cloud_service, "_sio", relay)
    await cloud_service.forward_component_health("node-a", {"node_id": "node-b"})
    assert [(e, d["node_id"]) for e, d in relay.events] == [("component_health", "node-a")]


# ── OTA lifecycle events keep the node_ota envelope ───────────────────────


async def test_an_ota_start_is_forwarded_as_node_ota_with_the_pi_clock(monkeypatch):
    relay = RecordingSio()
    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.test")
    monkeypatch.setattr(cloud_service, "_connected", True)
    monkeypatch.setattr(cloud_service, "_sio", relay)
    sio = RecordingSio()
    before = time.time()
    await _handle_message(sio, "sporeprint/node-a/ota",
                          {"event": "start", "ts": 1234, "type": "firmware"})
    ((event, data),) = relay.events
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
    await _handle_message(RecordingSio(), "sporeprint/node-ab12/status/heartbeat",
                          {"type": "relay", "roles": ["relay"]})
    await _handle_message(RecordingSio(), "sporeprint/node-ab12/health", relay_health)
    assert json.loads((await node_row("node-ab12"))["channels"]) == [
        "aux", "circulation", "exhaust", "fae"]
    # A channels value of a shape the Pi does not understand changes nothing.
    await _handle_message(RecordingSio(), "sporeprint/node-ab12/health", {"channels": ["fae"]})
    assert json.loads((await node_row("node-ab12"))["channels"]) == [
        "aux", "circulation", "exhaust", "fae"]
    # Re-provisioned as a climate node: its health doc lists no channels.
    await _handle_message(RecordingSio(), "sporeprint/node-ab12/status/heartbeat",
                          {"type": "climate", "roles": ["climate"]})
    await _handle_message(RecordingSio(), "sporeprint/node-ab12/health", {"sensors": {}})
    assert (await node_row("node-ab12"))["channels"] == "[]"
    error = await validate_action_channel(
        RuleAction(target="node-ab12", channel="fae", state="on"))
    assert error is not None
    assert await target_is_present("fae") is False


async def test_a_node_that_never_listed_channels_stays_unreported(quiet_cloud):
    await _handle_message(RecordingSio(), "sporeprint/climate-01/status/heartbeat",
                          {"type": "climate", "roles": ["climate"]})
    await _handle_message(RecordingSio(), "sporeprint/climate-01/health", {"sensors": {}})
    assert (await node_row("climate-01"))["channels"] is None


# ── the node's transport security ─────────────────────────────────────────


_PEM = "-----BEGIN CERTIFICATE-----\nMIIBpi\n-----END CERTIFICATE-----\n"
_SERVED = hashlib.sha256(_PEM.encode()).hexdigest()
_OTHER = hashlib.sha256(b"someone else's CA").hexdigest()


@pytest.fixture()
def served_ca(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text(_PEM)
    monkeypatch.setattr(provision, "_CA_PATHS", (tmp_path / "absent.crt", ca))


def _heartbeat(**extra):
    return {"type": "climate", "roles": ["climate"], "firmware_version": "5.2.2",
            "ip": "10.0.0.20", **extra}


@pytest.mark.parametrize("extra,expected", [
    (dict(tls=True, board="esp32-wroom-32", ca_fp=_SERVED), (1, 0, "esp32-wroom-32", _SERVED, 1)),
    (dict(tls=True, ca_fp=_OTHER), (1, 0, None, _OTHER, 0)),
    (dict(tls=False, tls_fallback=True), (0, 1, None, None, None)),
    ({}, (None, None, None, None, None)),
    (dict(tls=True, ca_fp="not-a-digest"), (1, 0, None, None, None)),
], ids=["pinned-to-this-pi", "pinned-to-another-ca", "plaintext-fallback",
        "image-reports-no-transport", "malformed-fingerprint"])
async def test_heartbeat_records_the_nodes_transport_security(served_ca, extra, expected):
    await _handle_message(RecordingSio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(**extra))
    row = await node_row("node-f6")
    assert (row["tls"], row["tls_fallback"], row["board"], row["ca_fp"],
            row["ca_fp_match"]) == expected


async def test_a_ca_check_is_unknown_while_the_pi_serves_no_ca(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "_CA_PATHS", (tmp_path / "absent.crt",))
    await _handle_message(RecordingSio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp=_OTHER))
    row = await node_row("node-f6")
    assert row["ca_fp"] == _OTHER and row["ca_fp_match"] is None


async def test_a_ca_mismatch_is_warned_once_per_fingerprint(served_ca, caplog):
    warned = []
    for fingerprint in (_OTHER, _OTHER, _OTHER[::-1], _SERVED, _OTHER):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.mqtt"):
            await _handle_message(RecordingSio(), "sporeprint/node-f6/status/heartbeat",
                                  _heartbeat(tls=True, ca_fp=fingerprint))
        warned.append(len(caplog.records))
    # Not every minute; again for a new fingerprint, and again after a match.
    assert warned == [1, 0, 1, 0, 1]


async def test_the_nodes_api_reports_the_ca_check(served_ca, client):
    await _handle_message(RecordingSio(), "sporeprint/node-f6/status/heartbeat",
                          _heartbeat(tls=True, ca_fp=_SERVED))
    (node,) = [n for n in client.get("/api/hardware/nodes").json()
               if n["node_id"] == "node-f6"]
    assert node["ca_fp_match"] == 1 and node["tls"] == 1


# ── firmware limits that are normal for the grow's phase ──────────────────


async def _alert(node_id: str, alert_type: str, value):
    await _handle_message(RecordingSio(), f"sporeprint/{node_id}/alert",
                          {"type": alert_type, "value": value, "message": "limit"})


async def _grow(species: str, phase: str, container: str = "monotub"):
    await seed_builtins()
    return await create_session(SessionCreate(
        name=species, species_profile_id=species, substrate="straw",
        current_phase=phase, container_type=container))


_PRIORITY = {"temperature": 5, "co2": 5, "humidity": 4}


@pytest.mark.parametrize("grow,alert_type,value,paged", [
    # Colonization runs no fresh air: CO2 builds by design (up to 10000 ppm).
    (("shaggy_mane", "substrate_colonization", "monotub"), "co2", 9800.0, False),
    # Passive fresh air, ceiling 5000 ppm.
    (("blue_oyster", "substrate_colonization", "monotub"), "co2", 4500.0, False),
    (("blue_oyster", "substrate_colonization", "monotub"), "co2", 6000.0, True),
    # Fruiting band: 55-65 °F, 85-92 % RH.
    (("blue_oyster", "fruiting", "monotub"), "temperature", 39.0, True),
    (("blue_oyster", "fruiting", "monotub"), "humidity", 88.0, False),
    (("blue_oyster", "fruiting", "monotub"), "humidity", 96.0, True),
    (("blue_oyster", "fruiting", "monotub"), "temperature", "hot", True),
    # A sealed bag: the room's CO2 and humidity say nothing about its inside.
    (("blue_oyster", "substrate_colonization", "grow_bag"), "co2", 8000.0, False),
    (("blue_oyster", "substrate_colonization", "grow_bag"), "humidity", 20.0, False),
    # A reference-only species: the engine manages nothing, so nothing is normal.
    (("chaga", "substrate_colonization", "monotub"), "temperature", 75.0, True),
    # No grow: between grows these are a headless Pi's only pages.
    (None, "co2", 4500.0, True),
    (None, "temperature", 36.0, True),
], ids=["co2-no-fae", "co2-under-ceiling", "co2-over-ceiling", "temp-out-of-band",
        "rh-in-band", "rh-over-band", "temp-not-a-reading", "sealed-co2", "sealed-rh",
        "reference-only-species", "no-grow-co2", "no-grow-temp"])
async def test_a_firmware_limit_pages_unless_normal_for_the_grow(
        ntfy_posts, grow, alert_type, value, paged):
    if grow:
        await _grow(*grow)
    await _alert("climate-01", alert_type, value)
    assert [p["priority"] for p in ntfy_posts] == ([_PRIORITY[alert_type]] if paged else [])


async def test_a_limit_pages_when_the_grow_lookup_fails(ntfy_posts, monkeypatch):
    async def _fails(node_id):
        raise RuntimeError("database is locked")

    await _grow("blue_oyster", "substrate_colonization")
    monkeypatch.setattr("app.automation.engine._session_for_node", _fails)
    await _alert("climate-01", "co2", 4500.0)  # normal for the grow, were it known
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
