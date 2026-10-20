"""Server-triggered ESP32 firmware push — espota client protocol (v4.2).

The network protocol is exercised against a loopback fake device that
implements the ArduinoOTA side: reply ``AUTH <nonce>`` to the UDP
invitation, verify the digest answer, connect back over TCP to the
advertised host port, pull the image in chunks acking byte counts, and
send the final ``OK``. No real sockets to hardware — everything runs on
127.0.0.1 ephemeral ports with short injected timeouts.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import threading
import time

import pytest

from app.db import get_db
from app.hardware import ota_push
from app.hardware.ota_push import (
    OtaPushError,
    auth_answer,
    auth_response,
    auth_response_pbkdf2,
    push_firmware,
)

PASSWORD = "correct-horse-battery-1"
# Generous: they bound a failure, a passing push never waits them out.
_FAST = {"invite_timeout": 2.0, "stall_timeout": 2.0, "bind_host": "127.0.0.1"}


@pytest.fixture(autouse=True)
def _reset_push_state(monkeypatch):
    """Per-node push status is module-level in-memory state — start clean.

    Production binds the fixed, compose-published CALLBACK_PORT; tests use
    ephemeral ports (0) unless they pass callback_port explicitly, so they
    never collide with anything on the host or with each other."""
    ota_push._status.clear()
    ota_push._tasks.clear()
    ota_push._success_waiters.clear()
    monkeypatch.setattr(ota_push, "CALLBACK_PORT", 0)
    monkeypatch.setattr(ota_push, "_callback_port_lock", asyncio.Lock())
    yield
    ota_push._success_waiters.clear()


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ─── Loopback fake device (ArduinoOTA side of espota) ────────────────────


class _FakeDeviceProtocol(asyncio.DatagramProtocol):
    """Mirrors the node's espota receiver — ArduinoOTAClass::_onRx() on
    arduino-esp32 2.x images, firmware/lib/sp_device/ota_service.cpp (the same
    exchange, kept byte-for-byte) on core 3.x images: ONE datagram
    per handle() tick, IDLE → (invitation) → WAITAUTH → (answer) → IDLE.
    Anything but a U_AUTH (200) datagram in WAITAUTH silently drops the
    state back to IDLE; a non-FLASH datagram in IDLE is ignored."""

    def __init__(self, dev: "FakeOtaDevice"):
        self.dev = dev
        self.state = "idle"
        self.nonce: str | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if self.dev.respond:
            self.dev._inbox.put_nowait((data, addr))

    def handle(self, data: bytes, addr) -> None:
        dev = self.dev
        tokens = data.decode(errors="replace").split()
        try:
            cmd = int(tokens[0])
        except (IndexError, ValueError):
            cmd = -1
        if self.state == "idle":
            # Invitation: "<cmd> <host_port> <size> <md5>"
            if cmd != ota_push.FLASH_CMD or len(tokens) != 4 or len(tokens[3]) != 32:
                return
            dev.invitations_seen += 1
            dev.invitation = {"cmd": cmd, "host_port": int(tokens[1]),
                              "size": int(tokens[2]), "md5": tokens[3]}
            if dev.auth == "none":  # ArduinoOTA with no password: no challenge
                self.transport.sendto(b"OK", addr)
                dev._pull_tasks.append(asyncio.get_running_loop().create_task(
                    dev._pull(addr[0], dev.invitation["host_port"])))
                return
            if dev.auth == "pbkdf2":  # arduino-esp32 3.3.1+ stock ArduinoOTA
                self.nonce = hashlib.sha256(os.urandom(8)).hexdigest()
            elif dev.auth == "odd":   # neither espota variant
                self.nonce = os.urandom(20).hex()
            else:
                self.nonce = hashlib.md5(os.urandom(8)).hexdigest()
            for _ in range(2 if dev.duplicate_auth else 1):
                self.transport.sendto(f"AUTH {self.nonce}".encode(), addr)
            self.state = "wait_auth"
        elif self.state == "wait_auth":
            if cmd != ota_push.AUTH_CMD or len(tokens) != 3:
                self.state = "idle"  # e.g. a duplicate invitation
                return
            _, cnonce, response = tokens
            dev.cnonce = cnonce
            if dev.auth == "pbkdf2":
                # ArduinoOTA.cpp (3.3.12) OTA_WAITAUTH: 64-hex cnonce and
                # response or "auth param fail" back to IDLE, silently; then
                # sha256(pbkdf2(sha256hex(pass), nonce:cnonce, 10000):nonce:cnonce)
                if len(cnonce) != 64 or len(response) != 64:
                    self.state = "idle"
                    return
                stored = hashlib.sha256(dev.password.encode()).hexdigest()
                derived = hashlib.pbkdf2_hmac(
                    "sha256", stored.encode(), f"{self.nonce}:{cnonce}".encode(),
                    10000).hex()
                expected = hashlib.sha256(
                    f"{derived}:{self.nonce}:{cnonce}".encode()).hexdigest()
            else:
                # Auth answer: "200 <cnonce> <md5(md5(pass):nonce:cnonce)>"
                pwd_hash = hashlib.md5(dev.password.encode()).hexdigest()
                expected = hashlib.md5(
                    f"{pwd_hash}:{self.nonce}:{cnonce}".encode()).hexdigest()
            self.state = "idle"
            if response == expected:
                dev.auth_ok = True
                if dev.refuse is not None:
                    # Current firmware: every refusal is decided before OK.
                    self.transport.sendto(f"ERR {dev.refuse}".encode(), addr)
                    return
                self.transport.sendto(b"OK", addr)
                if dev.refuse_after_ok is not None:
                    # Older firmware: OK first, then the refusal as an MQTT
                    # OTA "error" event, and no connect-back.
                    ota_push.note_node_event(
                        dev.node_id, {"event": "error", "ts": 0,
                                      "reason": dev.refuse_after_ok})
                    return
                dev._pull_tasks.append(asyncio.get_running_loop().create_task(
                    dev._pull(addr[0], dev.invitation["host_port"])))
            else:
                dev.auth_ok = False
                self.transport.sendto(b"Authentication Failed", addr)


class FakeOtaDevice:
    """Device side of espota on 127.0.0.1 ephemeral ports.

    respond=False   — never answer the invitation (device unreachable).
    busy_s          — the loop is blocked (camera JPEG POST, MQTT reconnect)
                       for this long after start(): datagrams queue in the
                       socket and are then handled one per tick, in order.
    duplicate_auth  — every AUTH challenge datagram arrives twice.
    auth            — "md5" (32-hex nonce: core 2.x ArduinoOTA and
                       ota_service.cpp), "pbkdf2" (64-hex nonce:
                       arduino-esp32 3.3.1+ stock ArduinoOTA), "odd"
                       (a 40-hex nonce neither variant uses) or "none"
                       (no password: a bare OK to the invitation).
    ack_delay_s     — wait this long before acking each chunk.
    ending          — how the transfer ends (TRANSFER_ENDINGS); "ok" acks
                       every chunk and sends the final OK at once.
    node_id         — after the final OK, report "success" for this node the
                       way the node's MQTT OTA event reaches the push.
    refuse          — answer a correct auth with "ERR <reason>" (a push the
                       node turns down: manifest gate, image on probation).
    refuse_after_ok — answer "OK", then report the refusal as an MQTT OTA
                       "error" event for node_id and never connect back (how
                       firmware before the ERR answer refused).
    """

    def __init__(self, password: str = PASSWORD, *, respond: bool = True,
                 busy_s: float = 0.0, duplicate_auth: bool = False, auth: str = "md5",
                 ack_delay_s: float = 0.0, ending: str = "ok", node_id: str | None = None,
                 refuse: str | None = None, refuse_after_ok: str | None = None):
        self.password = password
        self.respond = respond
        self.busy_s = busy_s
        self.duplicate_auth = duplicate_auth
        self.auth = auth
        self.ack_delay_s = ack_delay_s
        self.ending = ending
        self.node_id = node_id
        self.refuse = refuse
        self.refuse_after_ok = refuse_after_ok
        self.cnonce: str | None = None
        self.invitation: dict | None = None
        self.invitations_seen = 0
        self.auth_ok: bool | None = None
        self.received = b""
        self.udp_port: int | None = None
        self._transport = None
        self._proto: _FakeDeviceProtocol | None = None
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._loop_task: asyncio.Task | None = None
        self._pull_tasks: list[asyncio.Task] = []
        self._closed = asyncio.Event()

    async def start(self) -> "FakeOtaDevice":
        loop = asyncio.get_running_loop()
        self._transport, self._proto = await loop.create_datagram_endpoint(
            lambda: _FakeDeviceProtocol(self), local_addr=("127.0.0.1", 0))
        self.udp_port = self._transport.get_extra_info("sockname")[1]
        self._loop_task = loop.create_task(self._handle_loop())
        return self

    async def _handle_loop(self) -> None:
        if self.busy_s:
            await asyncio.sleep(self.busy_s)
        while True:
            data, addr = await self._inbox.get()
            self._proto.handle(data, addr)
            await asyncio.sleep(0.005)  # next loop() → ArduinoOTA.handle()

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
        if self._transport is not None:
            self._transport.close()
        self._closed.set()
        for t in self._pull_tasks:
            try:
                await asyncio.wait_for(t, 2)
            except Exception:
                t.cancel()

    async def _send(self, writer, data: bytes) -> None:
        writer.write(data)
        await writer.drain()

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
                if self.ending == "stall":           # hold the connection, never ack
                    await self._closed.wait()
                    return
                if self.ending == "close-mid":       # drop it without an ack
                    return
                if self.ending == "err-ack":         # the image fails its signed hash
                    await self._send(writer, f"{len(chunk)}ERR manifest_sha256_mismatch".encode())
                    return
                if self.ack_delay_s:
                    await asyncio.sleep(self.ack_delay_s)
                await self._send(writer, str(len(chunk)).encode())
            self.received = buf
            if self.ending == "never-ok":
                await self._closed.wait()
                return
            if self.ending == "close-before-ok":
                return
            if self.ending in ("ok-late", "err-final"):
                await asyncio.sleep(0.02)            # Update.end() takes a moment
            if hashlib.md5(buf).hexdigest() != self.invitation["md5"]:
                return
            if self.ending == "err-final":
                await self._send(writer, b"ERROR[8]: MD5 Check Failed\n")
                return
            await self._send(writer, b"OK")
            if self.node_id is not None:
                # ota_service.cpp publishes it right after the OK.
                ota_push.note_node_event(self.node_id, {"event": "success"})
        finally:
            writer.close()


async def _push(device: FakeOtaDevice, image: bytes, password: str = PASSWORD, **kwargs):
    await push_firmware("climate-01", "127.0.0.1", device.udp_port, password, image,
                        **{**_FAST, **kwargs})


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


def test_auth_response_pbkdf2_matches_an_independent_vector():
    """arduino-esp32 3.3.1+ (stock ArduinoOTA, 64-hex nonce). Vector computed
    with Node's crypto (createHash / pbkdf2Sync), not hashlib:
    sha256(password) = 8468397d…4c4, pbkdf2_sha256(that hex,
    "<nonce>:<cnonce>", 10000, 32 B) = 1a82b4f4…d4e5, then
    sha256("<derived>:<nonce>:<cnonce>")."""
    nonce = "0f1e2d3c4b5a69788796a5b4c3d2e1f0" * 2
    cnonce = "00112233445566778899aabbccddeeff" * 2
    assert auth_response_pbkdf2(PASSWORD, nonce, cnonce) == (
        "75a6c7c4a84e7f00f21316c674038ec8474a63a592b0b7656166d73fa9aa8072")


def test_auth_answer_picks_the_variant_by_nonce_length():
    """espota.py's rule: 32 hex → MD5 with a 32-hex cnonce, 64 hex → PBKDF2
    with a 64-hex cnonce (the 3.3 node drops any other cnonce length)."""
    md5_nonce = "9f2b7c1e4a5d3f60819e2c4b6a8d0e1f"
    cmd, cnonce, response = auth_answer(PASSWORD, md5_nonce).split()
    assert cmd == str(ota_push.AUTH_CMD) and len(cnonce) == 32
    assert response == auth_response(PASSWORD, md5_nonce, cnonce)

    sha_nonce = "0f1e2d3c4b5a69788796a5b4c3d2e1f0" * 2
    cmd, cnonce, response = auth_answer(PASSWORD, sha_nonce).split()
    assert cmd == str(ota_push.AUTH_CMD) and len(cnonce) == 64
    assert response == auth_response_pbkdf2(PASSWORD, sha_nonce, cnonce)
    assert auth_answer(PASSWORD, sha_nonce).endswith("\n")

    for bad in ("", "abc", "0" * 40, "0" * 128):
        with pytest.raises(OtaPushError, match="unsupported AUTH challenge"):
            auth_answer(PASSWORD, bad)


# ─── Protocol against the loopback fake device ───────────────────────────


@pytest.mark.parametrize("auth, cnonce_len", [("md5", 32), ("pbkdf2", 64)])
async def test_push_transfers_the_full_image_to_either_auth_variant(auth, cnonce_len):
    """A node on arduino-esp32 3.3's own ArduinoOTA offers a 64-hex nonce and
    accepts only the PBKDF2 answer; every SporePrint image offers the MD5
    one. The push answers both and transfers."""
    device = await FakeOtaDevice(auth=auth).start()
    try:
        image = os.urandom(2500)  # 2 full chunks + a partial final one
        await _push(device, image)
        assert device.auth_ok is True
        assert len(device.cnonce) == cnonce_len
        assert device.received == image
        assert device.invitation["cmd"] == ota_push.FLASH_CMD
        assert device.invitation["size"] == len(image)
        assert device.invitation["md5"] == hashlib.md5(image).hexdigest()
    finally:
        await device.stop()


@pytest.mark.parametrize("auth", ["md5", "pbkdf2"])
async def test_push_wrong_password_raises_and_never_leaks_it(auth):
    device = await FakeOtaDevice(password="the-real-password-42", auth=auth).start()
    try:
        with pytest.raises(OtaPushError, match="authentication rejected") as exc:
            await _push(device, b"\xe9" * 128, password="wrong-password-123")
        assert "wrong-password-123" not in str(exc.value)
        assert device.auth_ok is False
        assert device.received == b""
    finally:
        await device.stop()


async def test_push_refuses_a_nonce_neither_espota_variant_uses():
    device = await FakeOtaDevice(auth="odd").start()
    try:
        with pytest.raises(OtaPushError, match="unsupported AUTH challenge"):
            await _push(device, os.urandom(100))
        assert device.auth_ok is None and device.received == b""
    finally:
        await device.stop()


async def test_push_no_reply_times_out():
    device = await FakeOtaDevice(respond=False).start()
    try:
        with pytest.raises(OtaPushError, match="invitation timed out"):
            await _push(device, b"\xe9" * 64, invite_timeout=0.1)
    finally:
        await device.stop()


async def test_push_refuses_a_host_that_skips_the_password_challenge():
    """Every node with OTA enabled has a password and challenges for it. A
    bare OK comes from some other host at the node's address, which would
    take the image and confirm a flash that never happened."""
    device = await FakeOtaDevice(auth="none").start()
    try:
        with pytest.raises(OtaPushError, match="without asking for the OTA password"):
            await _push(device, os.urandom(2500))
        await asyncio.gather(*device._pull_tasks, return_exceptions=True)
        assert device.received == b""   # its connect-back found no listener
    finally:
        await device.stop()


async def test_push_reports_the_reason_a_node_refuses_it():
    """Current firmware decides a refusal before its OK and answers
    "ERR <reason>": the push says why, not "authentication rejected"."""
    device = await FakeOtaDevice(refuse="image_on_probation").start()
    try:
        with pytest.raises(OtaPushError) as ei:
            await _push(device, os.urandom(2500))
        msg = str(ei.value)
        assert msg.startswith("node refused the push: image_on_probation")
        assert "power-cycle" in msg
        assert "authentication" not in msg
        assert device.auth_ok is True and device.received == b""
    finally:
        await device.stop()


async def test_push_reports_a_refusal_older_firmware_sends_after_ok():
    """Older firmware answered OK, then published its refusal (e.g. a
    manifest-required image pushed without one) as an MQTT "error" event and
    never connected back. The push reports that reason at once, instead of
    "never connected back" after the full wait."""
    device = await FakeOtaDevice(refuse_after_ok="manifest_required",
                                 node_id="climate-01").start()
    loop = asyncio.get_running_loop()
    try:
        started = loop.time()
        with pytest.raises(OtaPushError,
                           match="node refused the push: manifest_required"):
            await _push(device, os.urandom(2500), invite_timeout=5.0)
        assert loop.time() - started < 4.0  # not the connect-back timeout
        assert ota_push._error_waiters == {}
    finally:
        await device.stop()


async def test_an_error_event_for_another_node_does_not_stop_a_push():
    device = await FakeOtaDevice(node_id="climate-01").start()
    try:
        ota_push.note_node_event("climate-02", {"event": "error", "reason": "x"})
        image = os.urandom(2500)
        task = asyncio.create_task(_push(device, image))
        await asyncio.sleep(0)
        ota_push.note_node_event("climate-02", {"event": "error", "reason": "x"})
        await task
        assert device.received == image
    finally:
        await device.stop()


# ─── How the transfer ends ────────────────────────────────────────────────
#
# The node acks each chunk with the byte count it flashed and says "OK" once
# Update.end() succeeds — on the last chunk's ack or on its own a moment
# later. Anything else is not a flash.


@pytest.mark.parametrize("ending, error", [
    ("ok", None),
    ("ok-late", None),
    ("stall", "transfer stalled at 0/2500 bytes"),
    ("close-mid", "node closed the connection at 0/2500 bytes"),
    ("err-ack", "node refused the image: ERR manifest_sha256_mismatch"),
    ("never-ok", "node received the image but never confirmed flash"),
    ("close-before-ok", "node closed the connection before confirming flash"),
    ("err-final", "node refused the image: ERROR[8]: MD5 Check Failed"),
])
async def test_only_a_transfer_the_node_confirms_counts_as_a_flash(ending, error):
    device = await FakeOtaDevice(ending=ending).start()
    image = os.urandom(2500)
    try:
        if error is None:
            await _push(device, image, stall_timeout=1.0)
            assert device.received == image
            return
        with pytest.raises(OtaPushError) as exc:
            await _push(device, image, stall_timeout=0.1)
        assert str(exc.value) == error
    finally:
        await device.stop()


# ─── Fixed callback port (docker-compose bridge networking) ──────────────


async def test_push_advertises_and_listens_on_the_fixed_callback_port():
    """Behind the compose bridge the node's connect-back reaches the Pi host;
    only a PUBLISHED port is forwarded into the container. The invitation
    must advertise the fixed port and the server must listen on it."""
    fixed = _free_tcp_port()
    device = await FakeOtaDevice().start()
    try:
        image = os.urandom(2500)
        await _push(device, image, callback_port=fixed)
        assert device.invitation["host_port"] == fixed
        assert device.received == image
    finally:
        await device.stop()


async def test_concurrent_pushes_share_the_fixed_callback_port():
    """Two nodes pushed at once cannot both own port 3233 — the second must
    wait for the first instead of failing with EADDRINUSE."""
    fixed = _free_tcp_port()
    dev_a = await FakeOtaDevice().start()
    dev_b = await FakeOtaDevice().start()
    try:
        img_a, img_b = os.urandom(3000), os.urandom(2000)
        await asyncio.gather(
            push_firmware("climate-01", "127.0.0.1", dev_a.udp_port, PASSWORD,
                          img_a, callback_port=fixed, **_FAST),
            push_firmware("relay-01", "127.0.0.1", dev_b.udp_port, PASSWORD,
                          img_b, callback_port=fixed, **_FAST),
        )
        assert dev_a.received == img_a
        assert dev_b.received == img_b
    finally:
        await dev_a.stop()
        await dev_b.stop()


async def test_callback_port_in_use_is_a_clean_push_error():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as squatter:
        squatter.bind(("127.0.0.1", 0))
        squatter.listen()
        taken = squatter.getsockname()[1]
        with pytest.raises(OtaPushError, match="callback port"):
            await push_firmware(
                "climate-01", "127.0.0.1", 9, PASSWORD, b"\xe9" * 64,
                invite_timeout=0.3, stall_timeout=0.3, bind_host="127.0.0.1",
                callback_port=taken)


# ─── Only the target node may take the connect-back ──────────────────────
#
# The fixed callback port is published on every interface. The listener used
# to hand the image to the FIRST TCP peer, from any address: a LAN host that
# kept connecting to :3233 won the race, "flashed" the image (acking chunks
# and sending OK), the real node's connect-back was closed, and the Pi
# reported a successful update that never happened.

_FOREIGN_IP = "10.66.6.6"


@pytest.fixture
def foreign_port(monkeypatch):
    """Connections from this local port come from "another LAN host"."""
    port = _free_tcp_port()
    real_peer_host = ota_push._peer_host

    def _peer_host(writer):
        peer = writer.get_extra_info("peername")
        return _FOREIGN_IP if peer and peer[1] == port else real_peer_host(writer)

    monkeypatch.setattr(ota_push, "_peer_host", _peer_host)
    return port


async def _foreign_peer(port: int, local_port: int, got: dict) -> None:
    """A LAN host that keeps connecting to the callback port and plays node."""
    loop = asyncio.get_running_loop()
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", local_port))
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, ("127.0.0.1", port))
        except OSError:
            sock.close()
            await asyncio.sleep(0.005)
            continue
        reader, writer = await asyncio.open_connection(sock=sock)
        got["connected"] = got.get("connected", 0) + 1
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    return          # closed on us: the Pi refused this peer
                got["bytes"] = got.get("bytes", 0) + len(chunk)
                writer.write(str(len(chunk)).encode() + b"OK")
                await writer.drain()
        finally:
            writer.close()


async def test_foreign_peer_on_the_callback_port_never_gets_the_image(foreign_port, caplog):
    fixed = _free_tcp_port()
    got: dict = {}
    # The node is busy for a moment, so the squatter certainly connects first.
    device = await FakeOtaDevice(busy_s=0.1).start()
    squatter = asyncio.create_task(_foreign_peer(fixed, foreign_port, got))
    try:
        image = os.urandom(2500)
        await _push(device, image, callback_port=fixed)
        assert got.get("connected", 0) >= 1, "the squatter never raced the node"
        assert got.get("bytes", 0) == 0
        assert device.received == image
        assert any(_FOREIGN_IP in r.getMessage() for r in caplog.records
                   if r.levelname == "WARNING")
    finally:
        squatter.cancel()
        await device.stop()


async def _connect_once_from(local_port: int, port: int, got: dict) -> None:
    """One connection to the callback port from `local_port`, held until the
    Pi closes it."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", local_port))
    sock.setblocking(False)
    await loop.sock_connect(sock, ("127.0.0.1", port))
    reader, writer = await asyncio.open_connection(sock=sock)
    got["connected"] = got.get("connected", 0) + 1
    try:
        while await reader.read(4096):
            got["bytes"] = got.get("bytes", 0) + 1
    finally:
        writer.close()


async def test_a_foreign_peer_connecting_mid_transfer_is_refused_cleanly(foreign_port, caplog):
    """A peer that connects while the image is already flowing is logged and
    closed like one before it. The per-chunk refusal check must not clobber
    the refused-peer set the connect handler shares, or that handler dies with
    a TypeError and the warning is lost."""
    fixed = _free_tcp_port()
    loop = asyncio.get_running_loop()
    loop_errors: list[dict] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    got: dict = {}
    foreign: list[asyncio.Task] = []

    def _progress(sent: int) -> None:
        if sent == ota_push.CHUNK_SIZE:  # first chunk acked: transfer under way
            foreign.append(asyncio.ensure_future(_connect_once_from(foreign_port, fixed, got)))

    device = await FakeOtaDevice(ack_delay_s=0.02).start()
    try:
        image = os.urandom(ota_push.CHUNK_SIZE * 6)
        await _push(device, image, callback_port=fixed, progress_cb=_progress)
        await asyncio.wait_for(asyncio.gather(*foreign), 2)
        assert got.get("connected") == 1 and got.get("bytes", 0) == 0
        assert device.received == image
        assert loop_errors == []
        refused = [r for r in caplog.records
                   if r.levelname == "WARNING" and _FOREIGN_IP in r.getMessage()]
        assert len(refused) == 1
    finally:
        loop.set_exception_handler(previous_handler)
        await device.stop()


def test_peer_matching_normalises_addresses():
    assert ota_push._same_host("::ffff:10.0.0.5", "10.0.0.5")
    assert ota_push._same_host("10.0.0.5", "10.0.0.5")
    assert ota_push._same_host("fe80::1%en0", "fe80::1")
    assert not ota_push._same_host("10.0.0.6", "10.0.0.5")
    assert not ota_push._same_host("", "10.0.0.5")
    assert not ota_push._same_host(None, "10.0.0.5")


async def test_a_hostname_target_accepts_only_its_resolved_addresses(monkeypatch):
    allowed = await ota_push._allowed_peers("localhost")
    assert any(ota_push._same_host("127.0.0.1", a) for a in allowed)
    assert await ota_push._allowed_peers("10.0.0.5") == {"10.0.0.5"}

    async def _no_such_host(*args, **kwargs):
        raise socket.gaierror(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _no_such_host)
    with pytest.raises(OtaPushError, match="cannot resolve node address 'gone.local'"):
        await ota_push._allowed_peers("gone.local")


# ─── Invitation robustness against a busy node ───────────────────────────


async def test_busy_node_shorter_than_the_retry_interval_sees_one_invitation():
    """A node blocked (camera JPEG POST, PubSubClient reconnect) queues
    whatever the Pi sent meanwhile. Re-inviting every second queued a
    duplicate: ArduinoOTA answered the first with AUTH, the duplicate
    knocked it back to IDLE, and the Pi's answer was then ignored → a false
    failure with the right password. The default retry interval outlasts
    the ~1.5 s busy spells seen on real nodes; scaled down here."""
    assert ota_push.INVITE_RETRY_S > 1.5
    device = await FakeOtaDevice(busy_s=0.15).start()
    try:
        image = os.urandom(2500)
        await _push(device, image, invite_retry=0.3)
        assert device.invitations_seen == 1
        assert device.auth_ok is True
        assert device.received == image
    finally:
        await device.stop()


async def test_node_busy_across_several_retries_still_authenticates():
    """Busy longer than the retry interval: several invitations queue up and
    the node answers them in order (AUTH, IDLE, AUTH, …). Each retry uses a
    fresh socket, so replies to abandoned invitations never reach the
    current exchange, and the push still completes."""
    device = await FakeOtaDevice(busy_s=0.25).start()
    try:
        image = os.urandom(1500)
        await _push(device, image, invite_timeout=3.0, invite_retry=0.1)
        assert device.invitations_seen >= 2
        assert device.auth_ok is True
        assert device.received == image
    finally:
        await device.stop()


async def test_duplicate_auth_challenge_is_not_mistaken_for_rejection():
    """After answering the challenge, a stale second 'AUTH <nonce>' must be
    skipped while waiting for OK — not reported as 'authentication
    rejected: AUTH …'."""
    device = await FakeOtaDevice(duplicate_auth=True).start()
    try:
        image = os.urandom(1200)
        await _push(device, image)
        assert device.auth_ok is True
        assert device.received == image
    finally:
        await device.stop()


# ─── Status tracking (start_push lifecycle) ──────────────────────────────


@pytest.fixture
def fast_pushes(monkeypatch):
    """The background push with the test's short timeouts and loopback bind."""
    real = ota_push.push_firmware

    async def _short(*args, **kwargs):
        return await real(*args, **{**kwargs, **_FAST})

    monkeypatch.setattr(ota_push, "push_firmware", _short)
    monkeypatch.setattr(ota_push, "SUCCESS_EVENT_TIMEOUT_S", 0.05)


@pytest.mark.parametrize("device_kw, password, state, message", [
    ({"node_id": "climate-01"}, PASSWORD, "ok", "flash confirmed by node"),
    ({"password": "the-real-password-42"}, "wrong-password-123", "error",
     "authentication rejected"),
    # The espota exchange cannot tell the node from another host at its
    # address; the node's own MQTT "success" event (its broker login) can. A
    # transfer that ends in OK without that event is not reported as a flash.
    ({}, PASSWORD, "error", "the node took the image but never reported a successful flash"),
], ids=["flashed", "wrong-password", "flash-never-reported"])
async def test_a_push_runs_in_the_background_and_ends_in_its_status(
        fast_pushes, device_kw, password, state, message):
    device = await FakeOtaDevice(**device_kw).start()
    try:
        image = os.urandom(2500)
        ota_push.start_push("climate-01", "127.0.0.1", device.udp_port, password, image)
        assert ota_push.is_running("climate-01")
        st = ota_push.get_status("climate-01")
        assert (st["state"], st["total_bytes"]) == ("running", len(image))
        await ota_push._tasks["climate-01"]
        st = ota_push.get_status("climate-01")
        assert st["state"] == state
        assert st["message"].startswith(message)
        assert password not in st["message"]
        assert st["finished_at"] >= st["started_at"]
        assert ota_push._success_waiters == {}
        if state == "ok":
            assert st["bytes_sent"] == len(image) and device.received == image
    finally:
        await device.stop()


async def test_a_push_that_crashes_ends_in_error_not_running(monkeypatch):
    async def _broken(*args, **kwargs):
        raise RuntimeError("socket module exploded")

    monkeypatch.setattr(ota_push, "push_firmware", _broken)
    ota_push.start_push("climate-01", "10.1.2.3", 3232, PASSWORD, b"\xe9" * 64)
    await ota_push._tasks["climate-01"]
    st = ota_push.get_status("climate-01")
    assert (st["state"], st["message"]) == ("error", "internal error during push")
    assert not ota_push.is_running("climate-01")


def test_a_manifest_push_needs_a_way_to_send_the_manifest():
    with pytest.raises(ValueError, match="needs send_command"):
        ota_push.start_push("climate-01", "10.1.2.3", 3232, PASSWORD, b"\xe9", manifest=object())
    assert ota_push.get_status("climate-01")["state"] == "idle"


def test_target_refusal_needs_an_online_node_heard_from_recently():
    now = 1_800_000_000.0
    fresh = {"status": "online", "last_seen": now - 30}
    assert ota_push.target_refusal(fresh, now=now) is None
    assert "offline" in ota_push.target_refusal({**fresh, "status": "offline"}, now=now)
    assert ota_push.target_refusal({**fresh, "status": None}, now=now)
    assert ota_push.target_refusal({**fresh, "last_seen": None}, now=now)
    stale = {**fresh, "last_seen": now - ota_push.TARGET_MAX_AGE_S - 60}
    assert "min ago" in ota_push.target_refusal(stale, now=now)


# ─── Routes ──────────────────────────────────────────────────────────────


async def _register_node(node_id: str, ip: str | None = None, *,
                         status: str = "online", last_seen: float | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, ip_address, "
            "firmware_version, status, last_seen) VALUES (?, 'climate', ?, '2.0.0', ?, ?)",
            (node_id, ip, status, time.time() if last_seen is None else last_seen),
        )
        await db.commit()


def _reports_success(node_id: str) -> None:
    """The node's MQTT "success" OTA event, as app/mqtt.py feeds it in."""
    ota_push.note_node_event(node_id, {"event": "success"})


def _post_ota(client, node_id, *, filename="firmware.bin",
              content=b"\xe9" * 64, password=PASSWORD, extra=None):
    data = {"password": password} if password is not None else {}
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


@pytest.fixture
def captured_push(monkeypatch):
    """The background push the route starts: its arguments, reported as a
    flash at once."""
    calls: list[dict] = []

    async def _capture(node_id, ip, port, password, image, **kwargs):
        calls.append({"node_id": node_id, "ip": ip, "port": port, "image": image})
        _reports_success(node_id)

    monkeypatch.setattr(ota_push, "push_firmware", _capture)
    return calls


@pytest.mark.parametrize("ip, post_kw, status, detail", [
    ("10.1.2.3", {"filename": "firmware.exe"}, 400, ".bin"),
    ("10.1.2.3", {"content": b""}, 400, "empty"),
    ("10.1.2.3", {"content": b"\x00" * (ota_push.MAX_UPLOAD_BYTES + 1)}, 413, None),
    ("10.1.2.3", {"extra": {"port": "70000"}}, 400, None),
    ("10.1.2.3", {"password": None}, 422, None),
    (None, {}, 400, "IP"),
], ids=["not-a-bin", "empty", "over-16mb", "bad-port", "no-password", "node-without-ip"])
async def test_a_push_the_route_cannot_start_is_refused(client, captured_push, ip, post_kw,
                                                        status, detail):
    await _register_node("climate-01", ip=ip)
    resp = _post_ota(client, "climate-01", **post_kw)
    assert resp.status_code == status
    if detail is not None:
        assert detail in resp.json()["detail"]
    assert captured_push == []


def test_a_push_to_an_unknown_node_is_a_404(client, captured_push):
    assert _post_ota(client, "ghost-01").status_code == 404
    assert client.get("/api/hardware/nodes/ghost-01/ota").status_code == 404


async def test_the_status_of_a_node_never_pushed_to_is_idle(client):
    await _register_node("climate-01", ip="10.1.2.3")
    resp = client.get("/api/hardware/nodes/climate-01/ota")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["state"], body["node_id"], body["bytes_sent"]) == ("idle", "climate-01", 0)


async def test_post_ota_concurrent_push_conflicts(client, monkeypatch):
    await _register_node("relay-01", ip="127.0.0.1")
    release = threading.Event()

    async def _gated_push(node_id, *args, **kwargs):
        while not release.is_set():
            await asyncio.sleep(0.01)
        _reports_success(node_id)

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


@pytest.mark.parametrize("extra, port", [(None, ota_push.DEFAULT_OTA_PORT), ({"port": "8266"}, 8266)],
                         ids=["default-port", "port-field"])
async def test_post_ota_starts_the_push_at_the_registry_ip(client, captured_push, extra, port):
    """202 immediately; the background transfer gets the node's IP from
    the registry, the port, and the exact uploaded bytes."""
    await _register_node("climate-01", ip="10.1.2.3")
    image = b"\xe9" + os.urandom(300)
    resp = _post_ota(client, "climate-01", content=image, extra=extra)
    assert resp.status_code == 202
    assert resp.json() == {"status": "started", "node_id": "climate-01"}

    st = await _wait_final(client, "climate-01")
    assert st["state"] == "ok"
    assert st["total_bytes"] == len(image)
    assert captured_push == [{"node_id": "climate-01", "ip": "10.1.2.3", "port": port,
                              "image": image}]


@pytest.mark.parametrize("status, age_s", [("offline", 30), ("online", 3600), ("unknown", 30)])
async def test_post_ota_refuses_a_node_that_is_not_online_now(client, captured_push, status, age_s):
    """The push goes to the IP from the node's last heartbeat; once the node
    is offline or quiet, another host may hold that address and would get the
    OTA password challenge."""
    await _register_node("climate-01", ip="10.1.2.3", status=status,
                         last_seen=time.time() - age_s)
    resp = _post_ota(client, "climate-01")
    assert resp.status_code == 409
    assert "last heartbeat" in resp.json()["detail"]
    assert captured_push == []
    assert client.get("/api/hardware/nodes/climate-01/ota").json()["state"] == "idle"
