"""Shared fakes for the integrations tests: a per-test integrations key, an
httpx transport for the vendor APIs, the telemetry a poll stored, and a fake
KLAP v2 (Tapo) plug.

Not collected (no ``test_`` prefix). A test module that imports
``fresh_keystore_fixture`` gets the ``fresh_keystore`` fixture (pytest
registers an imported fixture for the importing module).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.config import settings
from app.db import get_db
from app.integrations import _registry
from app.integrations._keystore import reset_fernet_cache
from app.integrations.tapo import klap
from app.integrations.tapo.config import TapoConfig

# The real client class, taken once: route_httpx may be called again in one
# test, and must not wrap its own earlier fake.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(name="fresh_keystore")
def fresh_keystore_fixture(tmp_path, monkeypatch):
    """A per-test integrations key file (never the checkout's data/db one).

    Yields the directory it lives in, so a test can swap in another key
    (a restore onto a Pi without the original key file).
    """
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield tmp_path
    reset_fernet_cache()


def route_httpx(monkeypatch, handler: Callable) -> None:
    """Send every httpx.AsyncClient the code under test builds to ``handler``
    (sync or async, ``httpx.Request -> httpx.Response``)."""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(*a, **{**k, "transport": transport}),
    )


def use_drivers(monkeypatch, *drivers) -> None:
    """Make ``drivers`` the registered set the dispatcher and sweeper see,
    so a test never configures the process-wide driver singletons."""
    monkeypatch.setattr(_registry, "registered_drivers", lambda: {d.name: d for d in drivers})


async def stored_readings(node_id: str | None = None) -> set[tuple]:
    """Telemetry rows a poll stored: ``(sensor, value)`` for one node, or
    ``(node_id, sensor, value)`` for every node."""
    async with get_db() as db:
        if node_id is None:
            cursor = await db.execute("SELECT node_id, sensor, value FROM telemetry_readings")
            return {(r["node_id"], r["sensor"], r["value"]) for r in await cursor.fetchall()}
        cursor = await db.execute(
            "SELECT sensor, value FROM telemetry_readings WHERE node_id = ?", (node_id,)
        )
        return {(r["sensor"], r["value"]) for r in await cursor.fetchall()}


async def health_after_one_poll(drv):
    """Run the driver's real poll loop for one cycle and read its health."""
    await drv.start()
    try:
        for _ in range(300):
            if drv._last_poll_at is not None:
                break
            await asyncio.sleep(0.01)
        return await drv.health()
    finally:
        await drv.stop()


# ── A fake KLAP v2 Tapo plug ──────────────────────────────────────────

EMAIL, PASSWORD = "user@example.com", "hunter2"
REMOTE = bytes(range(16, 32))


def klap_reply(local: bytes, seq: int, body: dict) -> bytes:
    """A plug's encrypted answer to the request sent with ``seq``."""
    session = klap.derive_session(local, REMOTE, EMAIL, PASSWORD)
    iv = session.iv_prefix + seq.to_bytes(4, "big", signed=True)
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(session.encrypt_key), modes.CBC(iv)).encryptor()
    plain = json.dumps(body).encode()
    return b"\x00" * 32 + enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()


class FakeKlapPlugs:
    """KLAP v2 plugs behind an httpx MockTransport, keyed by host.

    ``answer(host, request_json)`` returns the reply body; hosts in ``down``
    refuse connections; ``hold`` maps a method to an asyncio.Event its reply
    waits for; ``cookie=False`` is firmware that sets no session cookie;
    ``request_status`` answers every encrypted request with that status
    instead. ``calls`` lists each decrypted ``(host, request_json)``.
    """

    def __init__(self, answer, *, down=(), hold=None, cookie=True):
        self.answer = answer
        self.down = set(down)
        self.hold: dict[str, asyncio.Event] = hold or {}
        self.cookie = cookie
        self.request_status: int | None = None
        self.local: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/app/handshake1":
            local = request.content
            self.local[host] = local
            proof = klap.auth_hash(local, REMOTE, EMAIL, PASSWORD)
            headers = {"Set-Cookie": "TP_SESSIONID=s1;TIMEOUT=86400"} if self.cookie else {}
            return httpx.Response(200, content=REMOTE + proof, headers=headers)
        if path == "/app/handshake2":
            return httpx.Response(200)
        if path == "/app/request":
            if self.request_status is not None:
                return httpx.Response(self.request_status)
            seq = int(request.url.params["seq"])
            session = klap.derive_session(self.local[host], REMOTE, EMAIL, PASSWORD)
            body = json.loads(session.decrypt(request.content, seq))
            self.calls.append((host, body))
            gate = self.hold.get(body["method"])
            if gate is not None:
                await gate.wait()
            reply = self.answer(host, body)
            return httpx.Response(200, content=klap_reply(self.local[host], seq, reply))
        return httpx.Response(404)


def tapo_ok(result: dict | None = None) -> dict:
    return {"error_code": 0, "result": result or {}}


def tapo_cfg(*ips: str, **device) -> TapoConfig:
    return TapoConfig(email=EMAIL, password=PASSWORD,
                      devices=[{"ip": ip, **device} for ip in ips])
