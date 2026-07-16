"""Server-triggered ESP32 firmware push — espota client protocol (v4.2).

The network protocol is exercised against a loopback fake device that
implements the ArduinoOTA side: reply ``AUTH <nonce>`` to the UDP
invitation, verify the MD5 digest answer, connect back over TCP to the
advertised host port, pull the image in chunks acking byte counts, and
send the final ``OK``. No real sockets to hardware — everything runs on
127.0.0.1 ephemeral ports with short injected timeouts.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time

import pytest

from app.db import get_db
from app.hardware import ota_push
from app.hardware.ota_push import OtaPushError, auth_response, push_firmware

PASSWORD = "correct-horse-battery-1"


@pytest.fixture(autouse=True)
def _reset_push_state():
    """Per-node push status is module-level in-memory state — start clean."""
    ota_push._status.clear()
    ota_push._tasks.clear()
    yield


# ─── Loopback fake device (ArduinoOTA side of espota) ────────────────────


class _FakeDeviceProtocol(asyncio.DatagramProtocol):
    def __init__(self, dev: "FakeOtaDevice"):
        self.dev = dev
        self.state = "idle"
        self.nonce: str | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        dev = self.dev
        if not dev.respond:
            return
        text = data.decode().strip()
        if self.state == "idle":
            # Invitation: "<cmd> <host_port> <size> <md5>"
            cmd, host_port, size, md5 = text.split()
            dev.invitation = {"cmd": int(cmd), "host_port": int(host_port),
                              "size": int(size), "md5": md5}
            self.nonce = hashlib.md5(os.urandom(8)).hexdigest()
            self.transport.sendto(f"AUTH {self.nonce}".encode(), addr)
            self.state = "wait_auth"
        elif self.state == "wait_auth":
            # Auth answer: "200 <cnonce> <md5(md5(pass):nonce:cnonce)>"
            cmd, cnonce, response = text.split()
            pwd_hash = hashlib.md5(dev.password.encode()).hexdigest()
            expected = hashlib.md5(
                f"{pwd_hash}:{self.nonce}:{cnonce}".encode()).hexdigest()
            self.state = "idle"
            if int(cmd) == ota_push.AUTH_CMD and response == expected:
                dev.auth_ok = True
                self.transport.sendto(b"OK", addr)
                dev._pull_tasks.append(asyncio.get_running_loop().create_task(
                    dev._pull(addr[0], dev.invitation["host_port"])))
            else:
                dev.auth_ok = False
                self.transport.sendto(b"Authentication Failed", addr)


class FakeOtaDevice:
    """Device side of espota on 127.0.0.1 ephemeral ports.

    respond=False   — never answer the invitation (device unreachable).
    ack_chunks=False — accept the TCP connection, read data, never ack
                       (stalled transfer; connection held open).
    """

    def __init__(self, password: str = PASSWORD, *, respond: bool = True,
                 ack_chunks: bool = True):
        self.password = password
        self.respond = respond
        self.ack_chunks = ack_chunks
        self.invitation: dict | None = None
        self.auth_ok: bool | None = None
        self.received = b""
        self.udp_port: int | None = None
        self._transport = None
        self._pull_tasks: list[asyncio.Task] = []
        self._closed = asyncio.Event()

    async def start(self) -> "FakeOtaDevice":
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeDeviceProtocol(self), local_addr=("127.0.0.1", 0))
        self.udp_port = self._transport.get_extra_info("sockname")[1]
        return self

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self._closed.set()
        for t in self._pull_tasks:
            try:
                await asyncio.wait_for(t, 2)
            except Exception:
                t.cancel()

    async def _pull(self, host: str, port: int) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            size = self.invitation["size"]
            buf = b""
            while len(buf) < size:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                buf += chunk
                if not self.ack_chunks:
                    # Stall: hold the connection open, never ack.
                    await self._closed.wait()
                    return
                writer.write(str(len(chunk)).encode())
                await writer.drain()
            self.received = buf
            if hashlib.md5(buf).hexdigest() == self.invitation["md5"]:
                writer.write(b"OK")
                await writer.drain()
        finally:
            writer.close()


# ─── Auth digest ──────────────────────────────────────────────────────────


def test_auth_response_matches_hand_computed_vector():
    """Pin the espota digest against an independently computed vector:
    md5(password) = fbfd6ee1e6bf1f0c50b4d59008a7c204, then
    md5("<pwd_hash>:<nonce>:<cnonce>")."""
    digest = auth_response(
        PASSWORD,
        "9f2b7c1e4a5d3f60819e2c4b6a8d0e1f",
        "00112233445566778899aabbccddeeff",
    )
    assert digest == "97df929dcacb74585cad22727a4e29e7"


# ─── Protocol against the loopback fake device ───────────────────────────


async def test_push_happy_path_transfers_full_image():
    device = await FakeOtaDevice().start()
    try:
        image = os.urandom(2500)  # 2 full chunks + a partial final one
        await push_firmware(
            "climate-01", "127.0.0.1", device.udp_port, PASSWORD, image,
            invite_timeout=2.0, stall_timeout=2.0, bind_host="127.0.0.1")
        assert device.auth_ok is True
        assert device.received == image
        assert device.invitation["cmd"] == ota_push.FLASH_CMD
        assert device.invitation["size"] == len(image)
        assert device.invitation["md5"] == hashlib.md5(image).hexdigest()
    finally:
        await device.stop()


async def test_push_wrong_password_raises_and_never_leaks_it():
    device = await FakeOtaDevice(password="the-real-password-42").start()
    try:
        with pytest.raises(OtaPushError, match="authentication rejected") as ei:
            await push_firmware(
                "climate-01", "127.0.0.1", device.udp_port,
                "wrong-password-123", b"\xe9" * 128,
                invite_timeout=2.0, stall_timeout=2.0,
                bind_host="127.0.0.1")
        assert device.auth_ok is False
        assert device.received == b""
        assert "wrong-password-123" not in str(ei.value)
    finally:
        await device.stop()


async def test_push_no_reply_times_out():
    device = await FakeOtaDevice(respond=False).start()
    try:
        with pytest.raises(OtaPushError, match="invitation timed out"):
            await push_firmware(
                "climate-01", "127.0.0.1", device.udp_port, PASSWORD,
                b"\xe9" * 64, invite_timeout=0.4, stall_timeout=0.4,
                bind_host="127.0.0.1")
    finally:
        await device.stop()


async def test_push_stalled_transfer_times_out():
    device = await FakeOtaDevice(ack_chunks=False).start()
    try:
        with pytest.raises(OtaPushError, match="stalled"):
            await push_firmware(
                "climate-01", "127.0.0.1", device.udp_port, PASSWORD,
                os.urandom(4096), invite_timeout=2.0, stall_timeout=0.3,
                bind_host="127.0.0.1")
    finally:
        await device.stop()


# ─── Status tracking (start_push lifecycle) ──────────────────────────────


async def test_start_push_status_lifecycle_ok():
    device = await FakeOtaDevice().start()
    try:
        image = os.urandom(2500)
        # Short timeouts for determinism — patch the module defaults the
        # background task uses.
        async def _short(*args, **kwargs):
            kwargs.setdefault("invite_timeout", 2.0)
            kwargs.setdefault("stall_timeout", 2.0)
            kwargs["bind_host"] = "127.0.0.1"
            return await push_firmware(*args, **kwargs)

        orig = ota_push.push_firmware
        ota_push.push_firmware = _short
        try:
            ota_push.start_push("climate-01", "127.0.0.1", device.udp_port,
                                PASSWORD, image)
            assert ota_push.is_running("climate-01")
            st = ota_push.get_status("climate-01")
            assert st["state"] == "running"
            assert st["total_bytes"] == len(image)
            await ota_push._tasks["climate-01"]
        finally:
            ota_push.push_firmware = orig
        st = ota_push.get_status("climate-01")
        assert st["state"] == "ok"
        assert st["bytes_sent"] == len(image)
        assert st["finished_at"] >= st["started_at"]
        assert device.received == image
    finally:
        await device.stop()


async def test_start_push_status_error_never_contains_password():
    device = await FakeOtaDevice(password="the-real-password-42").start()
    try:
        async def _short(*args, **kwargs):
            kwargs.setdefault("invite_timeout", 2.0)
            kwargs.setdefault("stall_timeout", 2.0)
            kwargs["bind_host"] = "127.0.0.1"
            return await push_firmware(*args, **kwargs)

        orig = ota_push.push_firmware
        ota_push.push_firmware = _short
        try:
            ota_push.start_push("climate-01", "127.0.0.1", device.udp_port,
                                "wrong-password-123", b"\xe9" * 64)
            await ota_push._tasks["climate-01"]
        finally:
            ota_push.push_firmware = orig
        st = ota_push.get_status("climate-01")
        assert st["state"] == "error"
        assert "authentication rejected" in st["message"]
        assert "wrong-password-123" not in st["message"]
    finally:
        await device.stop()


def test_get_status_defaults_to_idle():
    st = ota_push.get_status("never-pushed-01")
    assert st["state"] == "idle"
    assert st["bytes_sent"] == 0


# ─── Routes ──────────────────────────────────────────────────────────────


async def _register_node(node_id: str, ip: str | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, ip_address, "
            "firmware_version) VALUES (?, 'climate', ?, '2.0.0')",
            (node_id, ip),
        )
        await db.commit()


def _post_ota(client, node_id, *, filename="firmware.bin",
              content=b"\xe9" * 64, password=PASSWORD, extra=None):
    data = {"password": password}
    if extra:
        data.update(extra)
    return client.post(
        f"/api/hardware/nodes/{node_id}/ota",
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
    )


async def _wait_final(client, node_id, timeout=5.0):
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        st = client.get(f"/api/hardware/nodes/{node_id}/ota").json()
        if st["state"] in ("ok", "error"):
            return st
        await asyncio.sleep(0.02)
    raise AssertionError(f"push to {node_id} never finished: {st}")


def test_post_ota_unknown_node_404(client):
    resp = _post_ota(client, "ghost-01")
    assert resp.status_code == 404


async def test_post_ota_node_without_ip_400(client):
    await _register_node("climate-01", ip=None)
    resp = _post_ota(client, "climate-01")
    assert resp.status_code == 400
    assert "IP" in resp.json()["detail"]


async def test_post_ota_rejects_non_bin_upload(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = _post_ota(client, "climate-01", filename="firmware.exe")
    assert resp.status_code == 400
    assert ".bin" in resp.json()["detail"]


async def test_post_ota_rejects_empty_upload(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = _post_ota(client, "climate-01", content=b"")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"]


async def test_post_ota_caps_upload_at_16mb(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = _post_ota(client, "climate-01",
                     content=b"\x00" * (ota_push.MAX_UPLOAD_BYTES + 1))
    assert resp.status_code == 413


async def test_post_ota_rejects_bad_port(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = _post_ota(client, "climate-01", extra={"port": "70000"})
    assert resp.status_code == 400


async def test_post_ota_missing_password_422(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = client.post(
        "/api/hardware/nodes/climate-01/ota",
        files={"file": ("firmware.bin", b"\xe9" * 64,
                        "application/octet-stream")},
    )
    assert resp.status_code == 422


async def test_post_ota_concurrent_push_conflicts(client, monkeypatch):
    await _register_node("relay-01", ip="127.0.0.1")
    release = threading.Event()

    async def _gated_push(*args, **kwargs):
        while not release.is_set():
            await asyncio.sleep(0.01)

    monkeypatch.setattr(ota_push, "push_firmware", _gated_push)
    try:
        r1 = _post_ota(client, "relay-01")
        assert r1.status_code == 202
        r2 = _post_ota(client, "relay-01")
        assert r2.status_code == 409
    finally:
        release.set()
    st = await _wait_final(client, "relay-01")
    assert st["state"] == "ok"


async def test_post_ota_starts_push_with_registry_ip(client, monkeypatch):
    """202 immediately; the background transfer gets the node's IP from
    the registry, the default port, and the exact uploaded bytes."""
    await _register_node("climate-01", ip="10.1.2.3")
    calls: dict = {}

    async def _capture(node_id, ip, port, password, image, **kwargs):
        calls.update(node_id=node_id, ip=ip, port=port, image=image)

    monkeypatch.setattr(ota_push, "push_firmware", _capture)
    image = b"\xe9" + os.urandom(300)
    resp = _post_ota(client, "climate-01", content=image)
    assert resp.status_code == 202
    assert resp.json() == {"status": "started", "node_id": "climate-01"}

    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["total_bytes"] == len(image)
    assert calls["node_id"] == "climate-01"
    assert calls["ip"] == "10.1.2.3"
    assert calls["port"] == ota_push.DEFAULT_OTA_PORT
    assert calls["image"] == image


async def test_post_ota_honours_port_form_field(client, monkeypatch):
    await _register_node("climate-01", ip="10.1.2.3")
    calls: dict = {}

    async def _capture(node_id, ip, port, password, image, **kwargs):
        calls["port"] = port

    monkeypatch.setattr(ota_push, "push_firmware", _capture)
    resp = _post_ota(client, "climate-01", extra={"port": "8266"})
    assert resp.status_code == 202
    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert calls["port"] == 8266


def test_get_ota_status_unknown_node_404(client):
    resp = client.get("/api/hardware/nodes/ghost-01/ota")
    assert resp.status_code == 404


async def test_get_ota_status_idle_before_any_push(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = client.get("/api/hardware/nodes/climate-01/ota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "idle"
    assert body["node_id"] == "climate-01"
