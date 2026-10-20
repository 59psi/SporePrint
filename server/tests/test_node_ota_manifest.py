"""Signed manifests for Pi → node firmware pushes (hardware/node_manifest.py,
the manifest step of hardware/ota_push.py, and the optional manifest +
manifest_sig fields of POST /api/hardware/nodes/{id}/ota).

The node half — Ed25519 + canonical-form checks, the artifact / downgrade
policy, and the gate that binds the push to the signed sha256 — is
firmware/lib/sp_core/ota_manifest.h + ota_gate.h, tested natively
(test_core_ota_manifest) against a byte-identical copy of the same vectors.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.cloud import ota_manifest
from app.config import settings
from app.db import get_db
from app.hardware import node_manifest, ota_push
from app.hardware.node_manifest import NodeManifestError, check_node_manifest
from app.mqtt import (
    _NODE_INBOUND_FRAME_CAP,
    _bind_cmd_payload,
    _handle_message,
    _sign_cmd_payload,
)

REPO = Path(__file__).resolve().parents[2]
SERVER_VECTORS = Path(__file__).parent / "fixtures" / "ota_manifest_vectors.json"
FIRMWARE_VECTORS = REPO / "firmware" / "test" / "fixtures" / "ota_manifest_vectors.json"
VECTORS = json.loads(SERVER_VECTORS.read_text())
TEST_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(VECTORS["private_seed_hex"]))
PASSWORD = "correct-horse-battery-1"


@pytest.fixture(autouse=True)
def _pinned_test_key(monkeypatch):
    monkeypatch.setattr(settings, "ota_pubkey_b64", VECTORS["public_key_b64"])
    ota_push._status.clear()
    ota_push._tasks.clear()
    ota_push._manifest_waiters.clear()
    ota_push._success_waiters.clear()
    yield
    ota_push._manifest_waiters.clear()
    ota_push._success_waiters.clear()


def _signed(image: bytes, *, artifact="node_esp32", version="5.1.0",
            key=TEST_KEY, sha256=None, size=None) -> tuple[bytes, bytes]:
    m = ota_manifest.build(
        artifact=artifact, version=version, channel="stable",
        sha256=sha256 or hashlib.sha256(image).hexdigest(),
        size=len(image) if size is None else size,
        published_at="2026-10-05T12:00:00Z")
    return ota_manifest.sign(m, key)


IMAGE = b"\xe9" + bytes(range(256)) * 7


# ── shared vectors ──────────────────────────────────────────────

def test_firmware_vectors_are_a_byte_identical_copy():
    """The node's native test suite checks these exact bytes too."""
    assert FIRMWARE_VECTORS.read_bytes() == SERVER_VECTORS.read_bytes()


def test_firmware_suffix_matches():
    src = (REPO / "firmware" / "lib" / "sp_core" / "ota_gate.h").read_text()
    assert f'kOtaManifestSuffix = "{node_manifest.CMD_SUFFIX}"' in src


# ── check_node_manifest ─────────────────────────────────────────

def test_a_matching_signed_manifest_passes():
    data, sig = _signed(IMAGE)
    signed = check_node_manifest(data, sig, IMAGE, "5.0.0", "climate")
    assert signed.manifest["artifact"] == "node_esp32"
    assert base64.b64decode(signed.manifest_b64) == data
    assert base64.b64decode(signed.sig_b64) == sig
    assert signed.command() == {"manifest_b64": signed.manifest_b64,
                                "sig_b64": signed.sig_b64}


@pytest.mark.parametrize("mutate, needle", [
    (lambda: (_signed(IMAGE + b"x")[0], _signed(IMAGE + b"x")[1], IMAGE), "not the one the manifest signs"),
    (lambda: (*_signed(IMAGE, sha256="0" * 64), IMAGE), "not the one the manifest signs"),
    (lambda: (*_signed(IMAGE, artifact="sporeprint-server"), IMAGE), "for the Pi server"),
    (lambda: (*_signed(IMAGE, version="4.9.9"), IMAGE), "older than the node's firmware"),
    (lambda: (*_signed(IMAGE, key=Ed25519PrivateKey.generate()), IMAGE), "signature verification FAILED"),
    (lambda: (_signed(IMAGE)[0] + b"\n", _signed(IMAGE)[1], IMAGE), "signature"),
])
def test_refusals(mutate, needle):
    data, sig, image = mutate()
    with pytest.raises(NodeManifestError, match=needle):
        check_node_manifest(data, sig, image, "5.0.0", "climate")


@pytest.mark.parametrize("artifact, node_type", [
    ("cam", "relay"), ("cam_esp32s3", "climate"), ("cam_xiao_esp32s3", "unknown"),
    ("cam", None), ("node_esp32", "camera"), ("node_esp32s3_n32r16v", "camera"),
])
def test_an_image_for_another_kind_of_node_is_refused(artifact, node_type):
    """A node built without the verify key flashes whatever it is sent, so
    the Pi binds the image to the kind of node: a camera image on a relay
    node would drive its MOSFET gate pins as camera bus lines."""
    data, sig = _signed(IMAGE, artifact=artifact)
    with pytest.raises(NodeManifestError, match=f"for {artifact}, not this"):
        check_node_manifest(data, sig, IMAGE, "5.0.0", node_type)


@pytest.mark.parametrize("artifact, node_type", [
    ("cam", "camera"), ("cam_waveshare_s3", "camera"), ("node_esp32", "relay"),
    ("node_esp32s3", "lighting"), ("node_esp32", "climate"),
])
def test_an_image_for_this_kind_of_node_passes(artifact, node_type):
    data, sig = _signed(IMAGE, artifact=artifact)
    assert check_node_manifest(data, sig, IMAGE, "5.0.0", node_type).manifest["artifact"] == artifact


def test_unknown_node_versions_are_not_compared():
    data, sig = _signed(IMAGE, version="1.0.0")
    for fw in (None, "", "dev", "unknown"):
        check_node_manifest(data, sig, IMAGE, fw, "climate")


def test_no_pinned_key_refuses(monkeypatch):
    monkeypatch.setattr(settings, "ota_pubkey_b64", "")
    monkeypatch.delenv("SPOREPRINT_OTA_PUBKEY", raising=False)
    data, sig = _signed(IMAGE)
    with pytest.raises(NodeManifestError, match="no OTA verify key"):
        check_node_manifest(data, sig, IMAGE, "5.0.0", "climate")


def test_oversize_manifest_refused_before_verification():
    with pytest.raises(NodeManifestError, match="a node takes at most"):
        check_node_manifest(b"{" * (node_manifest.MAX_NODE_MANIFEST_BYTES + 1),
                            b"\0" * 64, IMAGE, None, "climate")


def test_a_real_manifest_fits_one_node_command_frame(monkeypatch):
    """The command (b64 manifest + sig, plus the bound topic, nonce, ts and
    HMAC) must stay under the node's 1024-byte inbound cap."""
    monkeypatch.setattr(settings, "mqtt_hmac_key", "k" * 32)
    data, sig = _signed(IMAGE, artifact="node_esp32s3_n32r16v",
                        version="v10.20.30-beta.12")
    cmd = check_node_manifest(data, sig, IMAGE, None, "climate").command()
    topic = "sporeprint/a-long-node-name-0123456789/cmd/ota_manifest"
    frame = json.dumps(_sign_cmd_payload(_bind_cmd_payload(topic, cmd)))
    assert len(frame.encode()) < _NODE_INBOUND_FRAME_CAP


# ── the push: manifest first ───────────────────────────────────

async def _register_node(node_id: str, ip: str = "10.1.2.3", fw: str = "5.0.0",
                         node_type: str = "climate") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, ip_address, "
            "firmware_version, status, last_seen) VALUES (?, ?, ?, ?, 'online', ?)",
            (node_id, node_type, ip, fw, time.time()))
        await db.commit()


def _post(client, node_id, image=IMAGE, manifest=None, sig=None):
    files = {"file": ("firmware.bin", image, "application/octet-stream")}
    if manifest is not None:
        files["manifest"] = ("node_esp32.manifest.json", manifest, "application/json")
    if sig is not None:
        files["manifest_sig"] = ("node_esp32.manifest.json.sig", sig, "application/octet-stream")
    return client.post(f"/api/hardware/nodes/{node_id}/ota",
                       files=files, data={"password": PASSWORD})


async def _wait_final(client, node_id, timeout=5.0):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        st = client.get(f"/api/hardware/nodes/{node_id}/ota").json()
        if st["state"] in ("ok", "error"):
            return st
        await asyncio.sleep(0.02)
    raise AssertionError(f"push to {node_id} never finished: {st}")


@pytest.fixture()
def node_answers(monkeypatch):
    """Publishing cmd/ota_manifest makes the 'node' answer with `answer`
    (None = never answers). Records the order of manifest and push. The push
    runs push_firmware's before-invitation step, as the real one does once it
    holds the callback port, then the node reports the flash: with the
    manifest version when it flashed under an arming (`report`, by default
    "manifest" when armed)."""
    log: list = []
    state = {"answer": "armed", "published": True, "report": None}

    async def _publish(topic, payload):
        log.append(("publish", topic, payload))
        node = topic.split("/")[1]
        sha = json.loads(base64.b64decode(payload["manifest_b64"]))["sha256"]
        answer = state["answer"]
        if answer == "armed":
            ota_push.note_node_event(node, {"event": "manifest_armed", "sha256": sha,
                                            "version": "5.1.0"})
        elif answer is not None:
            ota_push.note_node_event(node, {"event": "manifest_rejected", "reason": answer})
        return state["published"]

    async def _push(node_id, ip, port, password, image, before_invite=None, **kwargs):
        if before_invite is not None:
            await before_invite()
        log.append(("push", node_id, image))
        report = state["report"] or ("manifest" if state["answer"] == "armed" else "plain")
        ota_push.note_node_event(node_id, {"event": "success", "manifest": "5.1.0"}
                                 if report == "manifest" else {"event": "success"})

    monkeypatch.setattr("app.hardware.service.mqtt_publish", _publish)
    monkeypatch.setattr(ota_push, "push_firmware", _push)
    monkeypatch.setattr(ota_push, "MANIFEST_CONFIRM_TIMEOUT_S", 0.05)
    state["log"] = log
    return state


async def test_manifest_is_armed_on_the_node_before_the_push(client, node_answers):
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    resp = _post(client, "climate-01", manifest=data, sig=sig)
    assert resp.status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["manifest"] == "node_verified"
    log = node_answers["log"]
    assert [e[0] for e in log] == ["publish", "push"]
    _, topic, payload = log[0]
    assert topic == "sporeprint/climate-01/cmd/ota_manifest"
    assert base64.b64decode(payload["manifest_b64"]) == data
    assert base64.b64decode(payload["sig_b64"]) == sig
    assert log[1][2] == IMAGE


async def test_a_node_rejection_stops_the_push(client, node_answers):
    node_answers["answer"] = "manifest_wrong_artifact"
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    assert _post(client, "climate-01", manifest=data, sig=sig).status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "error"
    assert "node rejected the signed manifest: manifest_wrong_artifact" in st["message"]
    assert [e[0] for e in node_answers["log"]] == ["publish"]


@pytest.mark.parametrize("answer", [None, "manifest_no_key"])
async def test_a_node_that_cannot_verify_gets_a_pi_verified_push(client, node_answers, answer):
    node_answers["answer"] = answer
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    assert _post(client, "climate-01", manifest=data, sig=sig).status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["manifest"] == "pi_verified"
    assert [e[0] for e in node_answers["log"]] == ["publish", "push"]


async def test_an_unsent_manifest_stops_the_push(client, node_answers):
    node_answers["published"] = False
    node_answers["answer"] = None
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    assert _post(client, "climate-01", manifest=data, sig=sig).status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "error"
    assert "could not send the signed manifest" in st["message"]
    assert [e[0] for e in node_answers["log"]] == ["publish"]


async def test_no_manifest_is_the_old_push(client, node_answers):
    await _register_node("climate-01")
    assert _post(client, "climate-01").status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["manifest"] is None
    assert [e[0] for e in node_answers["log"]] == ["push"]


async def test_a_flash_the_node_reports_without_its_manifest_check_is_pi_verified(client, node_answers):
    """The node armed, but its success report carries no manifest version: it
    flashed the image without its own check (the arming was gone by then)."""
    node_answers["report"] = "plain"
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    assert _post(client, "climate-01", manifest=data, sig=sig).status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["manifest"] == "pi_verified"


async def test_a_camera_image_for_a_relay_node_is_a_400(client, node_answers):
    await _register_node("relay-01", node_type="relay")
    data, sig = _signed(IMAGE, artifact="cam")
    r = _post(client, "relay-01", manifest=data, sig=sig)
    assert r.status_code == 400
    assert r.json()["detail"] == "Signed manifest refused: this manifest is for cam, not this relay node"
    assert node_answers["log"] == []
    await _register_node("cam-01", node_type="camera")
    assert _post(client, "cam-01", manifest=data, sig=sig).status_code == 202
    assert (await _wait_final(client, "cam-01"))["state"] == "ok"


async def test_the_manifest_is_armed_only_once_the_callback_port_is_free(monkeypatch):
    """The node keeps an arming for 5 minutes. A push queued behind others on
    the one callback port must not arm before it gets the port, or the arming
    can lapse and the node flashes the image unchecked."""
    order: list[str] = []
    sha = hashlib.sha256(IMAGE).hexdigest()

    async def _send(topic, payload):
        order.append("arm")
        ota_push.note_node_event("climate-01", {"event": "manifest_armed", "sha256": sha})
        return True

    async def _push_once(node_id, *args):
        order.append("invite")
        ota_push.note_node_event(node_id, {"event": "success", "manifest": "5.1.0"})

    monkeypatch.setattr(ota_push, "CALLBACK_PORT", 3233)  # the shared, locked port
    monkeypatch.setattr(ota_push, "_callback_port_lock", asyncio.Lock())
    monkeypatch.setattr(ota_push, "_push_once", _push_once)
    signed = check_node_manifest(*_signed(IMAGE), IMAGE, "5.0.0", "climate")

    await ota_push._callback_port_lock.acquire()  # another node's push holds it
    ota_push.start_push("climate-01", "10.1.2.3", 3232, PASSWORD, IMAGE,
                        manifest=signed, send_command=_send)
    task = ota_push._tasks["climate-01"]
    for _ in range(20):          # every chance to run: it is held at the lock
        await asyncio.sleep(0)
    assert order == []
    ota_push._callback_port_lock.release()
    await asyncio.wait_for(task, 2)
    assert order == ["arm", "invite"]
    st = ota_push.get_status("climate-01")
    assert st["state"] == "ok" and st["manifest"] == "node_verified"


async def test_bad_or_half_manifest_is_a_400(client, node_answers):
    await _register_node("climate-01")
    data, sig = _signed(IMAGE)
    r = _post(client, "climate-01", manifest=data)
    assert r.status_code == 400 and "go together" in r.json()["detail"]
    r = _post(client, "climate-01", image=IMAGE + b"!", manifest=data, sig=sig)
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Signed manifest refused:")
    old, old_sig = _signed(IMAGE, version="4.0.0")
    r = _post(client, "climate-01", manifest=old, sig=old_sig)
    assert r.status_code == 400 and "older than the node's firmware" in r.json()["detail"]
    assert node_answers["log"] == []
    assert client.get("/api/hardware/nodes/climate-01/ota").json()["state"] == "idle"


# ── the node's answer arrives over MQTT ────────────────────────

async def test_mqtt_ota_events_resolve_the_waiting_push(monkeypatch):
    monkeypatch.setattr("app.mqtt.forward_event", AsyncMock())
    fut = asyncio.get_running_loop().create_future()
    ota_push._manifest_waiters["cam-01"] = ("a" * 64, fut)
    sio = AsyncMock()
    # Another image's arming, and unrelated lifecycle events, are not the answer.
    await _handle_message(sio, "sporeprint/cam-01/ota",
                          {"event": "manifest_armed", "sha256": "b" * 64})
    await _handle_message(sio, "sporeprint/cam-01/ota", {"event": "start"})
    assert not fut.done()
    await _handle_message(sio, "sporeprint/cam-01/ota",
                          {"event": "manifest_armed", "sha256": "a" * 64,
                           "version": "5.1.0"})
    assert fut.result()["event"] == "manifest_armed"
    # Still forwarded as node_ota like every OTA event.
    assert sio.emit.await_args.args[0] == "node_ota"


def test_node_refusal_text_is_surfaced():
    assert ota_push._refusal(b"1460") is None
    assert ota_push._refusal(b"OK") is None
    err = ota_push._refusal(b"2920ERR manifest_sha256_mismatch")
    assert "node refused the image: ERR manifest_sha256_mismatch" in str(err)
    err = ota_push._refusal(b"ERROR[8]: MD5 Check Failed\n")
    assert "ERROR[8]: MD5 Check Failed" in str(err)
