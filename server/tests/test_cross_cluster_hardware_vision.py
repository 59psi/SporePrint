"""Hardware + vision cross-cluster follow-ups (hardware audit, pass 2).

Hardware:
- a manual node OFF never carries pwm/level (deployed firmware let pwm win),
  and clears the automation safety ceiling on that channel (automation-safety
  #3a) only when it was actually published;
- POST /api/hardware/nodes/{id}/peripherals sends a validated cmd/config
  {"peripherals": {...}} (fw-node-provisioning #4).

Vision (fw-drivers-cam #1, cloud-integrations-auth #5, sessions-species #2):
- a missing / unparseable / < 1e9 X-Timestamp is stamped with arrival time;
- X-Camera-Sensor is recorded on the node and named in the Claude prompt;
- an oversized upload is refused without buffering it;
- frames from a camera listed in a chamber are tagged with that chamber's grow;
- a vision harvest-readiness read goes out through notifications.harvest_ready.
"""

import asyncio
import json
import time

import pytest

import app.automation.engine as engine
import app.vision.router as vision_router
import app.vision.service as vision_service
from app.automation.engine import evaluate_rules
from app.automation.models import (
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
    ThresholdCondition,
)
from app.automation.service import create_rule
from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.config import settings
from app.db import get_db
from app.hardware.service import (
    get_camera_sensor,
    peripherals_command,
    record_camera_sensor,
    send_command,
)
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins
from app.telemetry.service import active_session_for_node

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"


@pytest.fixture(autouse=True)
def _reset_pause_state():
    engine._paused = False
    engine._pause_loaded = False
    yield
    engine._paused = False
    engine._pause_loaded = False


@pytest.fixture(autouse=True)
def _frame_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vision_storage", str(tmp_path / "frames"))


async def _node(node_id, node_type="relay", config=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, last_seen, config) VALUES (?, ?, ?, ?)",
            (node_id, node_type, time.time(), config),
        )
        await db.commit()


# ── manual node commands ───────────────────────────────────────────────────


def test_manual_off_is_published_without_a_duty_value(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-a/command",
                    json={"channel": "fae", "state": "off", "pwm": 120, "level": 900})
    assert r.status_code == 200, r.text
    assert mock_mqtt == [("sporeprint/relay-a/cmd/fae", {"state": "off"})]


def test_manual_on_keeps_its_duty_value(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/relay-a/command",
                    json={"channel": "fae", "state": "on", "pwm": 120})
    assert r.status_code == 200, r.text
    assert mock_mqtt == [("sporeprint/relay-a/cmd/fae", {"state": "on", "pwm": 120})]


async def _arm_fan_ceiling():
    await create_rule(AutomationRule(
        name="fan on", priority=1, safety_max_on_seconds=3600,
        condition=RuleCondition(type=ConditionType.THRESHOLD,
                                threshold=ThresholdCondition(sensor="temp_f", operator="gt", value=0)),
        action=RuleAction(target="relay-a", channel="fae", state="on"),
    ))
    await create_session(SessionCreate(name="s", species_profile_id="unit-a",
                                       current_phase="fruiting"))
    await evaluate_rules("climate-1", {"temp_f": 70})
    assert "relay-a:fae" in engine._safety_tasks


async def _watchdog_rows():
    async with get_db() as db:
        cursor = await db.execute("SELECT target, channel FROM safety_watchdogs")
        return {(r["target"], r["channel"]) for r in await cursor.fetchall()}


async def test_manual_off_clears_the_channels_safety_ceiling(mock_mqtt):
    await _arm_fan_ceiling()
    topic, published = await send_command("relay-a", {"channel": "fae", "state": "off"})
    assert published and topic == "sporeprint/relay-a/cmd/fae"
    assert "relay-a:fae" not in engine._safety_tasks
    assert await _watchdog_rows() == set()


async def test_unpublished_manual_off_keeps_the_ceiling(mock_mqtt):
    await _arm_fan_ceiling()
    mock_mqtt.mock.return_value = False
    _, published = await send_command("relay-a", {"channel": "fae", "state": "off"})
    assert not published
    assert "relay-a:fae" in engine._safety_tasks


async def test_manual_on_or_other_channel_keeps_the_ceiling(mock_mqtt):
    await _arm_fan_ceiling()
    await send_command("relay-a", {"channel": "fae", "state": "on"})
    await send_command("relay-a", {"channel": "exhaust", "state": "off"})
    await send_command("relay-a", {"state": "off"})  # cmd/config carries no switch state
    assert "relay-a:fae" in engine._safety_tasks


async def test_manual_scene_off_clears_a_scene_ceiling(mock_mqtt, monkeypatch):
    calls = []

    async def _spy(target, channel, *, sent_at=None):
        calls.append((target, channel))

    monkeypatch.setattr("app.hardware.service.note_actuator_off", _spy)
    await send_command("light-a", {"channel": "scene", "state": "off", "scene": "colonization_dark"})
    assert calls == [("light-a", None)]


# ── peripherals ────────────────────────────────────────────────────────────


def test_peripherals_command_validation():
    assert peripherals_command({"mhz19": True, "reed": False}) == {
        "peripherals": {"mhz19": True, "reed": False}}
    for bad in ({}, {"mhz19": "yes"}, {"hx711": 1}, {"co2": True}, []):
        with pytest.raises(ValueError):
            peripherals_command(bad)


def test_peripherals_endpoint_publishes_cmd_config(client, mock_mqtt):
    r = client.post("/api/hardware/nodes/node-1/peripherals", json={"hx711": True})
    assert r.status_code == 200, r.text
    assert r.json()["peripherals"] == {"hx711": True}
    assert mock_mqtt == [("sporeprint/node-1/cmd/config", {"peripherals": {"hx711": True}})]


def test_peripherals_endpoint_rejects_bad_input(client, mock_mqtt):
    assert client.post("/api/hardware/nodes/node-1/peripherals",
                       json={"hx711": "on"}).status_code == 422
    assert client.post("/api/hardware/nodes/bad!id/peripherals",
                       json={"hx711": True}).status_code == 400
    assert mock_mqtt == []


def test_peripherals_endpoint_503_when_not_published(client, mock_mqtt):
    mock_mqtt.mock.return_value = False
    r = client.post("/api/hardware/nodes/node-1/peripherals", json={"reed": False})
    assert r.status_code == 503


# ── vision ingest ──────────────────────────────────────────────────────────


def _post(client, headers=None, **kw):
    hdrs = {"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"}
    hdrs.update(headers or {})
    return client.post("/api/vision/frame", content=kw.pop("content", JPEG), headers=hdrs, **kw)


@pytest.mark.parametrize("raw", ["garbage", "nan", "inf", "-5", "1e30", ""])
def test_unusable_x_timestamp_is_stamped_with_arrival_time(client, raw):
    before = time.time()
    r = _post(client, {"X-Timestamp": raw})
    assert r.status_code == 200, r.text
    row = client.get(f"/api/vision/frames/{r.json()['frame_id']}").json()
    assert before - 1 <= row["timestamp"] <= time.time() + 1


def test_camera_sensor_is_recorded_on_a_registered_node(client):
    asyncio.run(_node("cam-01", "camera", config='{"other": 1}'))
    r = _post(client, {"X-Camera-Sensor": "OV3660"})
    assert r.status_code == 200, r.text
    assert r.json()["camera_sensor"] == "ov3660"
    node = client.get("/api/hardware/nodes/cam-01").json()
    assert json.loads(node["config"]) == {"other": 1, "camera_sensor": "ov3660"}


def test_bad_or_absent_camera_sensor_is_ignored(client):
    r = _post(client, {"X-Camera-Sensor": "<script>alert(1)</script>"})
    assert r.status_code == 200, r.text
    assert r.json()["camera_sensor"] is None
    assert _post(client).json()["camera_sensor"] is None


async def test_record_camera_sensor_only_touches_registered_nodes():
    assert await record_camera_sensor("cam-x", "ov2640") is False
    await _node("cam-x", "camera", config="not json")
    assert await record_camera_sensor("cam-x", "ov2640") is True
    assert await get_camera_sensor("cam-x") == "ov2640"


async def test_camera_sensor_reaches_the_claude_prompt(tmp_path, monkeypatch):
    capture: dict = {}

    class _Block:
        type = "text"
        text = '{"health_assessment": "healthy", "summary": "ok"}'

    class _Message:
        content = [_Block()]
        stop_reason = "end_turn"

    class _Messages:
        async def create(self, **kwargs):
            capture.update(kwargs)
            return _Message()

    class _Client:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(settings, "claude_api_key", "k")
    monkeypatch.setattr(vision_service.anthropic, "AsyncAnthropic", _Client)
    img = tmp_path / "f.jpg"
    img.write_bytes(JPEG)
    await vision_service.analyze_frame_claude(
        {"id": 1, "session_id": None, "node_id": "cam-01", "file_path": str(img),
         "camera_sensor": "ov3660"})
    assert "Camera sensor: OV3660" in capture["system"]


def test_oversized_declared_upload_is_refused_before_reading(client, monkeypatch):
    monkeypatch.setattr(vision_router, "_MAX_UPLOAD_BYTES", 32)
    r = _post(client, content=JPEG + b"x" * 64)
    assert r.status_code == 413


def test_oversized_chunked_upload_is_refused(client, monkeypatch):
    monkeypatch.setattr(vision_router, "_MAX_UPLOAD_BYTES", 32)

    def _chunks():
        yield JPEG
        yield b"x" * 64

    r = _post(client, content=_chunks())
    assert r.status_code == 413, r.text


def test_oversized_multipart_file_is_refused(client, monkeypatch):
    monkeypatch.setattr(vision_router, "_MAX_UPLOAD_BYTES", 32)
    r = client.post("/api/vision/frame", headers={"X-Node-Id": "cam-01"},
                    files={"file": ("f.jpg", JPEG + b"x" * 64, "image/jpeg")})
    assert r.status_code == 413, r.text


def test_multipart_without_a_file_part_is_400(client):
    r = client.post("/api/vision/frame", headers={"X-Node-Id": "cam-01"},
                    data={"note": "no image"}, files={"other": ("x.txt", b"x", "text/plain")})
    assert r.status_code == 400, r.text


def test_frames_are_tagged_with_the_cameras_chamber_session(client):
    async def _setup():
        a = await create_chamber(ChamberCreate(name="A", node_ids=["cam-a"]))
        grow_a = await create_session(SessionCreate(
            name="A grow", species_profile_id="unit-a", chamber_id=a["id"]))
        async with get_db() as db:
            await db.execute("UPDATE sessions SET created_at = created_at - 100 WHERE id = ?",
                             (grow_a["id"],))
            await db.commit()
        newest = await create_session(SessionCreate(name="loose", species_profile_id="unit-b"))
        return grow_a["id"], newest["id"]

    grow_a, newest = asyncio.run(_setup())
    in_chamber = _post(client, {"X-Node-Id": "cam-a"}).json()["frame_id"]
    loose = _post(client, {"X-Node-Id": "cam-z"}).json()["frame_id"]
    assert client.get(f"/api/vision/frames/{in_chamber}").json()["session_id"] == grow_a
    assert client.get(f"/api/vision/frames/{loose}").json()["session_id"] == newest


def test_unlisted_camera_is_never_tagged_with_one_of_two_chambers_grows(client):
    """Two chambered grows: a camera listed in neither used to be tagged with
    (and auto-analysed as) the newer one — wrong species context, wrong
    contamination / harvest alerts — while its node's telemetry stayed untagged."""
    async def _setup():
        for name in ("A", "B"):
            c = await create_chamber(ChamberCreate(name=name, node_ids=[f"cam-{name.lower()}"]))
            await create_session(SessionCreate(
                name=f"{name} grow", species_profile_id="unit-a", chamber_id=c["id"]))

    asyncio.run(_setup())
    loose = _post(client, {"X-Node-Id": "cam-z"}).json()["frame_id"]
    assert client.get(f"/api/vision/frames/{loose}").json()["session_id"] is None
    tagged = asyncio.run(active_session_for_node("cam-z", time.time() + 5))
    assert tagged is None


# ── harvest readiness → notifications.harvest_ready ────────────────────────


async def test_harvest_signal_notifies_through_harvest_ready(monkeypatch):
    await seed_builtins()
    sent = []

    async def _harvest_ready(species, session_name, *, reason=None, dedup_key=None):
        sent.append((species, session_name, reason, dedup_key))

    async def _forward(event_type, data):
        return None

    monkeypatch.setattr(vision_service, "harvest_ready", _harvest_ready)
    monkeypatch.setattr("app.cloud.service.forward_event", _forward)
    s = await create_session(SessionCreate(name="Flush 1", species_profile_id="blue_oyster",
                                           current_phase="fruiting"))
    frame = {"id": 7, "session_id": s["id"], "node_id": "cam-01"}
    await vision_service._maybe_harvest_alert(
        frame, {"harvest_readiness": "overdue", "growth_rate": "stalled"}, "Blue Oyster")
    assert sent == [("Blue Oyster", "Flush 1", "fruit body is overdue for harvest",
                     f"harvest:{s['id']}")]
    # One per session per 12 h.
    await vision_service._maybe_harvest_alert(
        frame, {"harvest_readiness": "overdue"}, "Blue Oyster")
    assert len(sent) == 1
