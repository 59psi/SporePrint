"""Frame-level tests for the cloud → Pi remote-command security gate.

``handle_cloud_command(sio, data)`` is the whole premium-gated remote-actuation
boundary: HMAC verify → premium tier → command id → replay dedup →
target_kind resolution → injection guards → registered-target check → MQTT
publish to the RESOLVED node. These drive real signed frames through the
whole gate and assert on the emitted ``command_result`` and the published
MQTT topic.

Canonical-ID masking is avoided: the relay node registers under a MAC-derived id
(``node-relay-7a3f1c``) DISTINCT from the ``relay-01`` placeholder and from the
``relay`` target_kind, so a publish to the wrong id would fail the topic assert.
"""

import asyncio
import time

import pytest

import app.automation.engine as engine
import app.cloud.service as service
from app.automation.engine import is_overridden
from app.cloud import ota
from app.cloud.service import handle_cloud_command
from app.db import get_db
from tests._builders import register_node
from tests._fakes import RecordingSio
from tests._signing import sign

_KEY = "unit-test-cloud-token"

# Real relay node id — MAC-derived, NOT the seeded relay-01 placeholder and NOT
# the "relay" target_kind. A publish to either of those would be a routing bug.
RELAY_NODE = "node-relay-7a3f1c"
LIGHT_NODE = "node-light-4b2e9d"
RELAY_BANK = ["aux", "circulation", "exhaust", "fae"]
LIGHT_BANK = ["blue", "far_red", "red", "white"]
_REPORTED_EARLIER = 1_752_700_000.0


def _cmd(cmd_id: str | None, *, tier: str = "premium", target_kind: str = "relay",
         channel: str | None = "fae", payload=None, ts: float | None = None) -> dict:
    return {
        "id": cmd_id,
        "tier": tier,
        "target_kind": target_kind,
        "channel": channel,
        "payload": payload if payload is not None else {"state": "on"},
        "ts": ts if ts is not None else time.time(),
    }


def _signed(cmd_id: str | None, **kw) -> dict:
    return sign(_cmd(cmd_id, **kw), _KEY)


@pytest.fixture(autouse=True)
def _cloud_env(monkeypatch):
    """Pin the signing key (conftest empties the replay cache)."""
    monkeypatch.setattr(service.settings, "cloud_token", _KEY)


async def _register_relay_node(node_id: str = RELAY_NODE) -> None:
    await register_node(node_id, "relay", channels=["fae", "exhaust"],
                        last_seen=_REPORTED_EARLIER)


# ── happy path: signed premium frame publishes to the RESOLVED node ────────

async def test_valid_premium_frame_publishes_its_payload_to_the_resolved_node(mock_mqtt):
    await _register_relay_node()
    sio = RecordingSio()

    await handle_cloud_command(sio, _signed("cmd-ok", payload={"state": "on", "duration_sec": 90}))

    # Published to the MAC-derived node the "relay" kind resolves to — not the
    # target_kind, not the relay-01 placeholder — with the payload verbatim.
    assert mock_mqtt == [(f"sporeprint/{RELAY_NODE}/cmd/fae", {"state": "on", "duration_sec": 90})]
    result = sio.last("command_result")
    assert result["success"] is True, result
    assert (result["target"], result["target_kind"], result["channel"]) == (RELAY_NODE, "relay", "fae")


# ── a cloud OFF clears the actuator's safety ceiling (automation-safety 3b) ─
#
# The engine's safety_max_on_seconds ceiling counts from the first automation
# ON. An OFF sent outside automation must clear it, or the next automation ON
# inherits the stale deadline and trips early (false WARNING + 15 min lockout).

@pytest.fixture()
def off_hook(monkeypatch):
    calls: list[tuple[str, str | None, float]] = []

    async def _spy(target, channel, *, sent_at=None):
        calls.append((target, channel, sent_at))

    monkeypatch.setattr("app.automation.engine.note_actuator_off", _spy)
    # The cloud's hardware commands publish through hardware.service.send_command.
    monkeypatch.setattr("app.hardware.service.note_actuator_off", _spy)
    return calls


async def test_a_cloud_off_goes_out_as_a_plain_off_and_clears_the_ceiling(mock_mqtt, off_hook):
    # Deployed firmware reads {"state":"off","pwm":N} as ON at duty N. The Pi
    # is about to clear the ceiling for this OFF, so it must be a real OFF.
    await _register_relay_node()
    sio = RecordingSio()
    before = time.time()
    await handle_cloud_command(sio, _signed(
        "cmd-off", payload={"state": "OFF", "pwm": 180, "level": 400, "reason": "app"}))
    assert sio.last("command_result")["success"] is True
    # The one node-command publisher spells the state the way the firmware reads it.
    assert mock_mqtt == [(f"sporeprint/{RELAY_NODE}/cmd/fae", {"state": "off", "reason": "app"})]
    assert [(t, c) for t, c, _ in off_hook] == [(RELAY_NODE, "fae")]
    # sent_at is taken just BEFORE the publish, per the hook's contract.
    assert before <= off_hook[0][2] <= time.time()


@pytest.mark.parametrize("payload,channel", [
    ({"state": "on"}, "fae"),                 # not an OFF
    ({"pwm": 0}, "fae"),                      # no explicit state: not a plain OFF
    ({"state": "off"}, None),                 # cmd/config, not an actuator
])
async def test_only_a_plain_channel_off_clears_the_ceiling(mock_mqtt, off_hook, payload, channel):
    await _register_relay_node()
    await handle_cloud_command(RecordingSio(), _signed("cmd-x", channel=channel, payload=payload))
    assert len(mock_mqtt) == 1
    assert off_hook == []


async def test_undelivered_cloud_off_keeps_the_ceiling(mock_mqtt, off_hook):
    await _register_relay_node()
    mock_mqtt.mock.return_value = False
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-off-lost", payload={"state": "off"}))
    result = sio.last("command_result")
    assert result["success"] is False
    assert "mqtt_publish failed" in result["error"]
    assert off_hook == []


async def test_cloud_off_cancels_a_real_armed_ceiling(mock_mqtt, monkeypatch):
    await _register_relay_node()
    key = engine._override_key(RELAY_NODE, "fae")
    armed = asyncio.create_task(asyncio.sleep(3600))
    engine._safety_tasks[key] = armed
    monkeypatch.setitem(engine._safety_last_on, key, time.time() - 60)  # ON went out a minute ago
    async with get_db() as db:
        await db.execute(
            "INSERT INTO safety_watchdogs (target, channel, rule_name, armed_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (RELAY_NODE, "fae", "FAE boost", time.time() - 60, time.time() + 3540),
        )
        await db.commit()

    await handle_cloud_command(RecordingSio(), _signed("cmd-off-real", payload={"state": "off"}))

    await asyncio.sleep(0)
    assert armed.cancelled()
    assert key not in engine._safety_tasks
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM safety_watchdogs")).fetchall()
    assert rows == []


# ── the gate: what a frame must get past before anything is published ──────

def _unsigned() -> dict:
    return _cmd("cmd-unsigned", tier="free")


def _signed_without_ts() -> dict:
    frame = _cmd("cmd-nots", tier="free")
    del frame["ts"]
    return sign(frame, _KEY)


# The frames are built inside each test, never when the table is collected:
# a signed frame's ts would age by however long the run takes to reach it.
@pytest.mark.parametrize("make_frame, category", [
    (_unsigned, "signature_mismatch"),
    (lambda: sign(_cmd("cmd-wrongkey", tier="free"), "attacker-key"), "signature_mismatch"),
    # Residual category: the reason names neither the signature nor the window.
    (_signed_without_ts, "bad_frame"),
    (lambda: sign(_cmd("cmd-old", tier="free", ts=time.time() - 3600), _KEY), "clock_skew"),
    (lambda: sign(_cmd("cmd-ahead", tier="free", ts=time.time() + 3600), _KEY), "clock_skew"),
], ids=["unsigned", "wrong-key", "no-ts", "stale", "future"])
async def test_a_frame_failing_the_signature_check_is_refused_first_and_categorised(
        mock_mqtt, make_frame, category):
    """Every frame here is also free tier: refused at the signature layer,
    NOT the tier layer, so a compromised relay cannot reach actuation with a
    forged 'premium'. The category tells the cloud's SLO sample a Pi clock
    drift (fix: NTP) from a signing-contract drift (a release bug)."""
    await _register_relay_node()
    sio = RecordingSio()
    await handle_cloud_command(sio, make_frame())
    assert mock_mqtt == []
    result = sio.last("command_result")
    assert result["success"] is False
    assert result["reject_reason"] == category
    assert result["error"].startswith("Signature check failed")


def _signed_without_tier() -> dict:
    frame = _cmd("cmd-notier")
    del frame["tier"]
    return sign(frame, _KEY)


@pytest.mark.parametrize("make_frame, error", [
    (lambda: _signed("cmd-free", tier="free"), "Remote control requires premium tier"),
    (_signed_without_tier, "Remote control requires premium tier"),
    (lambda: _signed(None), "Missing or invalid command id"),
    (lambda: _signed("cmd-badkind", target_kind="furnace"), "Invalid target_kind or channel"),
    # ';' is outside the safe-id charset — no topic injection allowed.
    (lambda: _signed("cmd-badchan", channel="fae;rm"), "Invalid target_kind or channel"),
    # A regex `$` matches before a trailing newline: "fae\n" used to pass and
    # publish to a topic the node never routes, reported as success.
    (lambda: _signed("cmd-newline", channel="fae\n"), "Invalid target_kind or channel"),
    (lambda: _signed("cmd-list", payload=["on"]), "Command payload must be a JSON object"),
], ids=["free-tier", "no-tier", "no-id", "unknown-kind", "injected-channel",
        "newline-channel", "non-object-payload"])
async def test_a_signed_frame_the_gate_refuses_never_publishes(mock_mqtt, make_frame, error):
    await _register_relay_node()
    sio = RecordingSio()
    await handle_cloud_command(sio, make_frame())
    assert mock_mqtt == []
    result = sio.last("command_result")
    assert result["success"] is False
    assert result["error"].startswith(error), result


async def test_a_failure_inside_the_gate_is_answered_not_raised(mock_mqtt, monkeypatch):
    """The cloud waits on every command_result; a handler that raised would
    leave it to time out and take the socket's event loop task with it."""
    await _register_relay_node()

    async def _broken(node_id, command):
        raise RuntimeError("broker client gone")

    monkeypatch.setattr("app.hardware.service.send_command", _broken)
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-boom"))
    assert sio.last("command_result") == {
        "id": "cmd-boom", "success": False, "error": "broker client gone"}


# ── replay dedup: FIFO eviction, write-through across a restart ────────────

async def test_replayed_command_id_is_rejected(mock_mqtt):
    await _register_relay_node()
    sio = RecordingSio()
    frame = _signed("cmd-dup")

    await handle_cloud_command(sio, frame)      # first: executes
    await handle_cloud_command(sio, frame)      # second: same id → replay

    assert len(mock_mqtt) == 1, "replayed frame must not publish a second time"
    assert sio.events[0][1]["success"] is True
    assert sio.events[1][1]["success"] is False
    assert sio.events[1][1]["error"] == "Replayed command id"


async def test_fifo_eviction_evicts_oldest_inserted_id(mock_mqtt, monkeypatch):
    """Past the cache cap the OLDEST-inserted id is evicted (FIFO), so it is no
    longer treated as a replay — while a still-cached recent id is."""
    await _register_relay_node()
    monkeypatch.setattr(service, "_COMMAND_ID_CACHE_CAP", 3)
    sio = RecordingSio()

    # Fill past cap: inserting cmd-3 evicts the oldest (cmd-0).
    for i in range(4):
        await handle_cloud_command(sio, _signed(f"cmd-{i}"))
    assert "cmd-0" not in service._seen_command_ids
    assert "cmd-2" in service._seen_command_ids

    published_before = len(mock_mqtt)

    # cmd-0 was evicted → re-send is NOT a replay → it executes again.
    sio_a = RecordingSio()
    await handle_cloud_command(sio_a, _signed("cmd-0"))
    assert sio_a.last("command_result")["success"] is True
    assert len(mock_mqtt) == published_before + 1

    # cmd-2 is still cached → re-send IS a replay.
    sio_b = RecordingSio()
    await handle_cloud_command(sio_b, _signed("cmd-2"))
    assert sio_b.last("command_result")["error"] == "Replayed command id"


async def test_a_command_seen_before_a_restart_is_still_a_replay_after_it(mock_mqtt):
    """The replay window (30 s of signature validity) outlives a quick Pi
    restart: accepted ids are written through to SQLite and reloaded when the
    connector starts, so the same signed frame is refused after the restart."""
    await _register_relay_node()
    frame = _signed("cmd-before-restart")
    await handle_cloud_command(RecordingSio(), frame)
    async with get_db() as db:  # a row from well outside the window
        await db.execute(
            "INSERT INTO cloud_command_replay (command_id, received_at) VALUES (?, ?)",
            ("cmd-long-ago", time.time() - 2 * service._REPLAY_WINDOW_SECONDS))
        await db.commit()

    service._seen_command_ids.clear()   # the restart
    assert await service._rehydrate_replay_cache() == 1

    sio = RecordingSio()
    await handle_cloud_command(sio, frame)
    assert sio.last("command_result")["error"] == "Replayed command id"
    assert len(mock_mqtt) == 1
    assert "cmd-long-ago" not in service._seen_command_ids
    async with get_db() as db:
        rows = await (await db.execute("SELECT command_id FROM cloud_command_replay")).fetchall()
    assert [r["command_id"] for r in rows] == ["cmd-before-restart"]


async def test_a_replay_id_that_cannot_be_persisted_is_still_refused_in_memory(monkeypatch):
    async def _disk_full(command_id):
        raise OSError("database or disk is full")

    monkeypatch.setattr(service, "_persist_replay_id", _disk_full)
    assert await service.claim_replay_id("cmd-unsaved") is True
    assert await service.claim_replay_id("cmd-unsaved") is False


# ── which node a hardware command reaches ──────────────────────────────────
#
# A frame names a kind and a channel, never a node. The relay bank has fae /
# exhaust / circulation / aux and the lighting bank white / blue / red /
# far_red; resolving by kind alone sent the cloud's light toggle (relay/white)
# to the relay bank, which drops cmd/white, and with two relay nodes sent a
# fan toggle to whichever node reported last.

async def test_a_light_command_reaches_the_lighting_node(mock_mqtt):
    await register_node(RELAY_NODE, "relay", channels=RELAY_BANK)   # reported last
    await register_node(LIGHT_NODE, "lighting", channels=LIGHT_BANK, last_seen=_REPORTED_EARLIER)
    for kind in ("lighting", "relay"):          # older clouds send "relay"
        sio = RecordingSio()
        await handle_cloud_command(sio, _signed(f"cmd-light-{kind}", target_kind=kind,
                                                channel="white"))
        assert sio.last("command_result")["success"] is True
        assert sio.last("command_result")["target"] == LIGHT_NODE
    assert [t for t, _ in mock_mqtt] == [f"sporeprint/{LIGHT_NODE}/cmd/white"] * 2


@pytest.mark.parametrize("nodes, error", [
    ([], "No registered relay node"),
    ([(RELAY_NODE, RELAY_BANK)], "No registered relay node has a 'mister' channel"),
    # Two chambers, one relay node each: the frame cannot say which.
    ([("relay-chamber-a", RELAY_BANK), ("relay-chamber-b", RELAY_BANK)], "Ambiguous target"),
], ids=["no-node", "no-such-channel", "two-candidates"])
async def test_a_command_with_no_single_target_is_refused_not_guessed(mock_mqtt, nodes, error):
    for node_id, channels in nodes:
        await register_node(node_id, "relay", channels=channels)
    channel = "mister" if error.endswith("channel") else "fae"
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-unresolved", channel=channel))
    assert mock_mqtt == []
    result = sio.last("command_result")
    assert result["success"] is False
    assert result["error"].startswith(error)
    if len(nodes) > 1:
        assert all(node_id in result["error"] for node_id, _ in nodes), result["error"]


async def test_a_node_that_never_reported_channels_still_resolves(mock_mqtt):
    await register_node(RELAY_NODE, "relay", channels=None)
    await handle_cloud_command(RecordingSio(), _signed("cmd-old-fw"))
    assert [t for t, _ in mock_mqtt] == [f"sporeprint/{RELAY_NODE}/cmd/fae"]


async def test_the_override_pins_the_node_the_command_reached(mock_mqtt):
    await register_node(RELAY_NODE, "relay", channels=RELAY_BANK)
    await register_node(LIGHT_NODE, "lighting", channels=LIGHT_BANK, last_seen=_REPORTED_EARLIER)
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-on", target_kind="relay", channel="white",
                                            payload={"state": "on", "duration_sec": 600}))
    await handle_cloud_command(sio, _signed(
        "cmd-hold", target_kind="automation", channel="override",
        payload={"channel": "white", "state": "on", "duration_sec": 600,
                 "expires_at": time.time() + 600}))
    assert sio.last("command_result")["success"] is True
    assert sio.events[0][1]["target"] == LIGHT_NODE
    assert is_overridden(LIGHT_NODE, "white") is True
    assert is_overridden(RELAY_NODE, "white") is False


# ── system commands ────────────────────────────────────────────────────────


async def test_reboot_is_refused_on_the_docker_install(mock_mqtt, monkeypatch, tmp_path):
    """The shipped install cannot reboot the host; a success ack followed by
    nothing told the operator it did."""
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.touch()
    monkeypatch.setattr(ota, "_DOCKERENV", dockerenv)
    scheduled = []
    monkeypatch.setattr(service, "schedule_reboot", lambda: scheduled.append(1))
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-reboot", target_kind="system",
                                            channel="reboot", payload={}))
    result = sio.last("command_result")
    assert result["success"] is False
    assert "Docker" in result["error"]
    assert scheduled == []


async def test_reboot_is_acked_and_scheduled_where_it_can_run(mock_mqtt, monkeypatch, tmp_path):
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr("app.system_actions.shutil.which", lambda tool: f"/usr/bin/{tool}")
    scheduled = []
    monkeypatch.setattr(service, "schedule_reboot", lambda: scheduled.append(1))
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-reboot-ok", target_kind="system",
                                            channel="reboot", payload={}))
    assert sio.last("command_result")["success"] is True
    assert scheduled == [1]


@pytest.mark.parametrize("channel, payload, error", [
    (None, {}, "system command requires a channel"),
    # Older clouds sent the grow advisor's suggestion as rule_apply_diff with
    # only free text; the Pi cannot apply that, and says so.
    ("rule_apply_diff", {"rule_label": "RH floor", "current": "92%", "proposed": "94%"},
     "Unknown system channel 'rule_apply_diff'"),
    # `bool("false")` is True: a plain cast would PAUSE automation.
    ("automation", {"paused": "maybe"}, "automation.paused must be a boolean"),
], ids=["no-channel", "descriptive-rule-change", "non-boolean-pause"])
async def test_a_system_command_the_pi_cannot_carry_out_is_never_acked_as_done(
        mock_mqtt, channel, payload, error):
    sio = RecordingSio()
    await handle_cloud_command(sio, _signed("cmd-sys", target_kind="system",
                                            channel=channel, payload=payload))
    result = sio.last("command_result")
    assert result["success"] is False
    assert result["error"].startswith(error)
