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
STALL_TIMEOUT_S = 120.0


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


async def _invite(transport, proto: _UdpExchange, invitation: bytes,
                  timeout: float) -> bytes:
    """Send the invitation, re-sending every ~1s (espota retries too — the
    node may miss a datagram while servicing WiFi), until a reply or the
    deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        transport.sendto(invitation)
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise OtaPushError("no reply from node (invitation timed out)")
        try:
            return await asyncio.wait_for(proto.replies.get(),
                                          min(1.0, remaining))
        except asyncio.TimeoutError:
            if loop.time() >= deadline:
                raise OtaPushError(
                    "no reply from node (invitation timed out)")


async def push_firmware(node_id: str, ip: str, port: int, password: str,
                        image: bytes, *,
                        invite_timeout: float = INVITE_TIMEOUT_S,
                        stall_timeout: float = STALL_TIMEOUT_S,
                        progress_cb: Callable[[int], None] | None = None,
                        bind_host: str = "0.0.0.0",
                        ) -> None:
    """Run one espota push. Raises OtaPushError on any failure."""
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

    server = await asyncio.start_server(_on_connect, host=bind_host, port=0)
    try:
        host_port = server.sockets[0].getsockname()[1]

        transport, proto = await loop.create_datagram_endpoint(
            _UdpExchange, remote_addr=(ip, port))
        try:
            invitation = f"{FLASH_CMD} {host_port} {size} {file_md5}\n"
            reply = (await _invite(transport, proto, invitation.encode(),
                                   invite_timeout)).decode(
                                       errors="replace").strip()
            if reply.startswith("AUTH"):
                parts = reply.split()
                if len(parts) != 2:
                    raise OtaPushError("malformed AUTH challenge from node")
                nonce = parts[1]
                cnonce = hashlib.md5(os.urandom(32)).hexdigest()
                answer = (f"{AUTH_CMD} {cnonce} "
                          f"{auth_response(password, nonce, cnonce)}\n")
                transport.sendto(answer.encode())
                try:
                    reply = (await asyncio.wait_for(
                        proto.replies.get(), invite_timeout)).decode(
                            errors="replace").strip()
                except asyncio.TimeoutError:
                    raise OtaPushError(
                        "no reply to authentication (timed out)")
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
