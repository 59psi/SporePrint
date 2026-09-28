"""ESP32 node firmware push — client side of the espota protocol (v4.2).

The nodes run ArduinoOTA (firmware/lib/sp_device/ota_service.*), armed only
when a per-device password >= 12 chars was provisioned via the captive
portal. This module lets the Pi push a firmware ``.bin`` to a node over the
LAN, exactly like Arduino's espota.py sender:

1. UDP invitation to the node's OTA port (default 3232)::

       "<command> <host_port> <file_size> <file_md5>\\n"     (command 0 = FLASH)

2. Node replies ``AUTH <nonce>``; we answer with MD5 digest auth::

       "200 <cnonce> <md5(md5(password):nonce:cnonce)>\\n"

3. Node replies ``OK``, then connects BACK to us over TCP on <host_port>
   and pulls the image. Each chunk is acked with the decimal byte count the
   node flashed; the final ack is ``OK`` once Update.end() succeeds and the
   node reboots into the new image.

<host_port> is the fixed ``CALLBACK_PORT`` (3233), not an ephemeral port:
under docker-compose the server sits on a bridge network, the node's
connect-back reaches the Pi host, and only a port published in
docker-compose.yml is forwarded into the container. One port means one
push at a time — concurrent pushes queue on ``_callback_port_lock``.

The node reports its own lifecycle over MQTT (msg_type "ota" -> ``node_ota``
events), but Pi-side failures — wrong password, unreachable node, stalled
transfer — happen before/around that and never reach MQTT. Those are tracked
in the in-memory per-node status exposed via
``GET /api/hardware/nodes/{node_id}/ota``.

The OTA password is supplied per push and never stored or logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Callable

log = logging.getLogger(__name__)

FLASH_CMD = 0        # U_FLASH — firmware image
AUTH_CMD = 200       # U_AUTH — digest-auth answer
DEFAULT_OTA_PORT = 3232
MAX_UPLOAD_BYTES = 16 * 1024 * 1024  # hard cap; a 4 MB-flash node is ~2 MB
CHUNK_SIZE = 1024    # espota chunk size; the node buffers at most 1460
INVITE_TIMEOUT_S = 10.0
# Wait this long for a reply before re-inviting (on a fresh socket). Long on
# purpose — see _invite(): duplicate invitations queued at a busy node make
# ArduinoOTA hand out nonces the Pi then answers out of order.
INVITE_RETRY_S = 3.0
STALL_TIMEOUT_S = 120.0
# TCP port the node connects back to (published in docker-compose.yml as
# "3233:3233"). 0 = ephemeral, only usable when the node can reach the
# server's own network namespace directly (bare metal, tests).
CALLBACK_PORT = 3233

# One fixed callback port → one transfer at a time across all nodes.
_callback_port_lock = asyncio.Lock()


class OtaPushError(Exception):
    """Pi-side push failure. Messages never contain the password."""


def auth_response(password: str, nonce: str, cnonce: str) -> str:
    """espota digest: ``md5(md5(password) + ':' + nonce + ':' + cnonce)``.

    Matches ArduinoOTA's device-side check — setPassword() stores
    md5(password) and the node compares md5(passmd5:nonce:cnonce). MD5 is
    mandated by the espota wire protocol; it is a challenge-response (the
    password never crosses the wire) and the hash is never stored. The
    12-char minimum enforced by the firmware keeps the brute-force space
    >2^60 (see ota_service.cpp).
    """
    # nosemgrep: python.lang.security.audit.md5-used-as-password.md5-used-as-password
    pwd_hash = hashlib.md5(password.encode()).hexdigest()
    return hashlib.md5(f"{pwd_hash}:{nonce}:{cnonce}".encode()).hexdigest()


# ─── In-memory per-node push status ──────────────────────────────────────
# The UI polls GET .../ota after POSTing a push. state is one of
# idle | running | ok | error. Survives until the next push to that node.

_status: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


def get_status(node_id: str) -> dict:
    return _status.get(node_id) or {
        "node_id": node_id, "state": "idle", "message": None,
        "started_at": None, "finished_at": None,
        "bytes_sent": 0, "total_bytes": 0,
    }


def is_running(node_id: str) -> bool:
    return _status.get(node_id, {}).get("state") == "running"


def start_push(node_id: str, ip: str, port: int, password: str,
               image: bytes) -> None:
    """Begin a background transfer. Caller must have checked is_running()
    — there must be no await between that check and this call."""
    _status[node_id] = {
        "node_id": node_id, "state": "running",
        "message": f"pushing {len(image)} bytes to {ip}:{port}",
        "started_at": time.time(), "finished_at": None,
        "bytes_sent": 0, "total_bytes": len(image),
    }
    _tasks[node_id] = asyncio.create_task(
        _run_push(node_id, ip, port, password, image))


async def _run_push(node_id: str, ip: str, port: int, password: str,
                    image: bytes) -> None:
    st = _status[node_id]

    def _progress(sent: int) -> None:
        st["bytes_sent"] = sent

    try:
        await push_firmware(node_id, ip, port, password, image,
                            progress_cb=_progress)
    except OtaPushError as e:
        st.update(state="error", message=str(e), finished_at=time.time())
        log.warning("OTA push to %s failed: %s", node_id, e)
    except Exception:
        st.update(state="error", message="internal error during push",
                  finished_at=time.time())
        log.exception("OTA push to %s crashed", node_id)
    else:
        st.update(state="ok", message="flash confirmed by node",
                  finished_at=time.time())
        log.info("OTA push to %s complete (%d bytes)", node_id, len(image))
    finally:
        _tasks.pop(node_id, None)


# ─── Protocol implementation ─────────────────────────────────────────────


class _UdpExchange(asyncio.DatagramProtocol):
    """Connected UDP endpoint — queues datagrams from the node."""

    def __init__(self) -> None:
        self.replies: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr) -> None:
        self.replies.put_nowait(data)


async def _invite(ip: str, port: int, invitation: bytes, timeout: float,
                  retry_every: float):
    """Invite the node; return ``(transport, proto, first_reply)``.

    ArduinoOTA handles one datagram per handle() call with a strict state
    machine: an invitation that arrives while it waits for the AUTH answer
    drops it back to IDLE, and the next queued invitation earns a fresh
    nonce. Re-sending every second therefore breaks exactly when the node
    is busy (camera mid-JPEG-POST, PubSubClient blocked reconnecting):
    duplicates queue up, the node answers them in turn, and the Pi answers
    a nonce the node already discarded → a false "authentication rejected"
    or a silent timeout. So, like espota.py: ONE invitation per UDP socket,
    a long wait before re-inviting, and every retry on a FRESH socket (new
    source port) so a late reply to an abandoned invitation can never be
    mistaken for the current exchange.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise OtaPushError("no reply from node (invitation timed out)")
        transport, proto = await loop.create_datagram_endpoint(
            _UdpExchange, remote_addr=(ip, port))
        transport.sendto(invitation)
        try:
            reply = await asyncio.wait_for(proto.replies.get(),
                                           min(retry_every, remaining))
        except asyncio.TimeoutError:
            transport.close()
            continue
        except BaseException:
            transport.close()
            raise
        return transport, proto, reply


async def _await_auth_result(proto: _UdpExchange, timeout: float) -> str:
    """After answering the challenge, wait for ``OK`` (or the node's
    failure text). A further ``AUTH <nonce>`` here is a stale duplicate
    challenge (a duplicated invitation datagram) — answering it would only
    desync the node again, so it is skipped."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise OtaPushError("no reply to authentication (timed out)")
        try:
            reply = (await asyncio.wait_for(proto.replies.get(),
                                            remaining)).decode(
                                                errors="replace").strip()
        except asyncio.TimeoutError:
            raise OtaPushError("no reply to authentication (timed out)")
        if reply.startswith("AUTH"):
            continue
        return reply


async def push_firmware(node_id: str, ip: str, port: int, password: str,
                        image: bytes, *,
                        invite_timeout: float = INVITE_TIMEOUT_S,
                        stall_timeout: float = STALL_TIMEOUT_S,
                        progress_cb: Callable[[int], None] | None = None,
                        bind_host: str = "0.0.0.0",
                        invite_retry: float = INVITE_RETRY_S,
                        callback_port: int | None = None,
                        ) -> None:
    """Run one espota push. Raises OtaPushError on any failure.

    ``callback_port`` defaults to the module's CALLBACK_PORT; pushes that
    share a fixed port are serialized (only one listener can own it)."""
    cb_port = CALLBACK_PORT if callback_port is None else callback_port
    args = (node_id, ip, port, password, image, invite_timeout,
            invite_retry, stall_timeout, progress_cb, bind_host, cb_port)
    if cb_port == 0:
        await _push_once(*args)
        return
    if _callback_port_lock.locked():
        log.info("OTA push to %s waiting for another push to release "
                 "callback port %d", node_id, cb_port)
    async with _callback_port_lock:
        await _push_once(*args)


async def _push_once(node_id: str, ip: str, port: int, password: str,
                     image: bytes, invite_timeout: float,
                     invite_retry: float, stall_timeout: float,
                     progress_cb: Callable[[int], None] | None,
                     bind_host: str, cb_port: int) -> None:
    loop = asyncio.get_running_loop()
    size = len(image)
    file_md5 = hashlib.md5(image).hexdigest()

    # TCP server first — the invitation advertises its port and the node
    # connects back to the source IP of our UDP datagram.
    conn_fut: asyncio.Future = loop.create_future()

    async def _on_connect(reader, writer):
        if conn_fut.done():
            writer.close()
            return
        conn_fut.set_result((reader, writer))

    try:
        server = await asyncio.start_server(_on_connect, host=bind_host,
                                            port=cb_port)
    except OSError as e:
        raise OtaPushError(
            f"cannot listen on OTA callback port {cb_port}: {e.strerror or e}")
    try:
        host_port = server.sockets[0].getsockname()[1]

        invitation = f"{FLASH_CMD} {host_port} {size} {file_md5}\n"
        transport, proto, raw = await _invite(
            ip, port, invitation.encode(), invite_timeout, invite_retry)
        try:
            reply = raw.decode(errors="replace").strip()
            if reply.startswith("AUTH"):
                parts = reply.split()
                if len(parts) != 2:
                    raise OtaPushError("malformed AUTH challenge from node")
                nonce = parts[1]
                cnonce = hashlib.md5(os.urandom(32)).hexdigest()
                answer = (f"{AUTH_CMD} {cnonce} "
                          f"{auth_response(password, nonce, cnonce)}\n")
                transport.sendto(answer.encode())
                reply = await _await_auth_result(proto, invite_timeout)
                if reply != "OK":
                    # Node says "Authentication Failed" — wrong password.
                    raise OtaPushError(
                        f"authentication rejected: {reply or 'no detail'}")
            elif reply != "OK":
                raise OtaPushError(
                    f"unexpected invitation reply: {reply[:64]!r}")
        finally:
            transport.close()

        # Node connects back over TCP and pulls the image.
        try:
            reader, writer = await asyncio.wait_for(conn_fut, invite_timeout)
        except asyncio.TimeoutError:
            raise OtaPushError(
                "node accepted the invitation but never connected back")

        try:
            sent = 0
            saw_ok = False
            for off in range(0, size, CHUNK_SIZE):
                chunk = image[off:off + CHUNK_SIZE]
                writer.write(chunk)
                await writer.drain()
                # Lockstep ack, as in espota — the node prints the byte
                # count it flashed after each chunk.
                try:
                    ack = await asyncio.wait_for(reader.read(64),
                                                 stall_timeout)
                except asyncio.TimeoutError:
                    raise OtaPushError(
                        f"transfer stalled at {sent}/{size} bytes")
                if not ack:
                    raise OtaPushError(
                        f"node closed the connection at {sent}/{size} bytes")
                sent += len(chunk)
                if progress_cb is not None:
                    progress_cb(sent)
                if b"OK" in ack:
                    saw_ok = True

            # Final OK arrives once Update.end() succeeds (may ride on the
            # last chunk's ack).
            deadline = loop.time() + stall_timeout
            while not saw_ok:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise OtaPushError(
                        "node received the image but never confirmed flash")
                try:
                    data = await asyncio.wait_for(reader.read(64), remaining)
                except asyncio.TimeoutError:
                    raise OtaPushError(
                        "node received the image but never confirmed flash")
                if not data:
                    raise OtaPushError(
                        "node closed the connection before confirming flash")
                if b"OK" in data:
                    saw_ok = True
        finally:
            writer.close()
    finally:
        server.close()
        await server.wait_closed()
