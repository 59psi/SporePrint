"""The LAN API-key boundary (app/auth.py).

``ApiKeyMiddleware`` is the only per-request gate in front of ``/api/*`` when
``SPOREPRINT_API_KEY`` is set. These tests drive the real middleware through a
TestClient (so a widened whitelist, a mis-parsed bearer, or a broken 401 path
would surface) and unit-test the pure helpers directly — including the
Socket.IO connect rate limiter's trip-and-recover behaviour.

Note conftest sets SPOREPRINT_ALLOW_UNAUTHENTICATED=true and never sets an
api_key, so the gate is OFF by default; each gating test monkeypatches
``settings.api_key`` to switch it on, and the key-unset path is tested too.
"""

import collections

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
import app.cloud.router as cloud_router_mod
import app.cloud.service as cloud_service
from app.auth import (
    ApiKeyMiddleware,
    _connect_rate_ok,
    _extract_bearer,
    _valid_token,
    socketio_auth_ok,
)
from app.config import settings
from app.db import get_db


_KEY = "s3cret-lan-key"


@pytest.fixture
def gated_client(monkeypatch):
    """A minimal app behind ApiKeyMiddleware with the key gate switched ON."""
    monkeypatch.setattr(settings, "api_key", _KEY)

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/api/private")
    async def private():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/vision/frame")
    async def vision_frame():
        return {"ok": True}

    @app.get("/public")   # non-/api path — outside the gate entirely
    async def public():
        return {"ok": True}

    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── ApiKeyMiddleware.dispatch — the 401 gate ───────────────────────────────

def test_no_bearer_is_401(gated_client):
    assert gated_client.get("/api/private").status_code == 401


def test_wrong_bearer_is_401(gated_client):
    assert gated_client.get("/api/private", headers=_auth("nope")).status_code == 401


def test_correct_bearer_passes(gated_client):
    r = gated_client.get("/api/private", headers=_auth(_KEY))
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_public_health_path_bypasses_auth(gated_client):
    # No Authorization header, yet the whitelisted probe must answer.
    assert gated_client.get("/api/health").status_code == 200


# ── /api/vision/frame — the camera's keyless upload path ───────────────────
#
# The ESP32-CAM has no slot for the API key, so the frame upload is exempt
# from the bearer — but ONLY for a node registered in hardware_nodes, and
# with the body size bounded BEFORE it is read into RAM (the whitelist
# comment always claimed this; the check didn't exist).

@pytest.fixture
def frame_client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", _KEY)
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.post("/api/vision/frame")
    async def vision_frame():
        return {"ok": True}

    return TestClient(app)


async def _register_node(node_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, last_seen) VALUES (?, 'camera', 0)",
            (node_id,),
        )
        await db.commit()


async def test_registered_camera_frame_bypasses_bearer(frame_client):
    await _register_node("cam-attic")
    r = frame_client.post("/api/vision/frame", content=b"\xff\xd8jpeg",
                          headers={"X-Node-Id": "cam-attic", "Content-Type": "image/jpeg"})
    assert r.status_code == 200


def test_unregistered_camera_frame_is_rejected(frame_client):
    r = frame_client.post("/api/vision/frame", content=b"\xff\xd8jpeg",
                          headers={"X-Node-Id": "rogue-cam", "Content-Type": "image/jpeg"})
    assert r.status_code == 403


def test_camera_frame_without_node_id_is_401(frame_client):
    r = frame_client.post("/api/vision/frame", content=b"\xff\xd8jpeg",
                          headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 401


async def test_oversized_camera_frame_rejected_before_body_read(frame_client):
    await _register_node("cam-attic")
    r = frame_client.post(
        "/api/vision/frame", content=b"x",
        headers={"X-Node-Id": "cam-attic", "Content-Type": "image/jpeg",
                 "Content-Length": str(auth._MAX_FRAME_UPLOAD_BYTES + 1)},
    )
    assert r.status_code == 413


def test_bearer_holder_can_upload_frames_for_any_node(frame_client):
    r = frame_client.post("/api/vision/frame", content=b"\xff\xd8jpeg",
                          headers={"X-Node-Id": "ui-upload", **_auth(_KEY)})
    assert r.status_code == 200


def test_vision_frame_get_is_not_public(gated_client):
    assert gated_client.get("/api/vision/frame").status_code == 401


# ── cloud pairing endpoints — method-aware whitelist ───────────────────────

@pytest.fixture
def pairing_client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", _KEY)
    monkeypatch.setattr(cloud_router_mod, "_pairing_code", None)
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)
    app.include_router(cloud_router_mod.router, prefix="/api/cloud")
    return TestClient(app)


def test_pairing_code_mint_requires_bearer(pairing_client):
    # Unauthenticated minting replaced the operator's code and reset the
    # 8-attempt lockout at will.
    assert pairing_client.post("/api/cloud/pairing-code").status_code == 401
    assert pairing_client.post("/api/cloud/pairing-code",
                               headers=_auth(_KEY)).status_code == 200


def test_pairing_code_read_requires_bearer(pairing_client):
    assert pairing_client.get("/api/cloud/pairing-code").status_code == 401
    assert pairing_client.get("/api/cloud/pairing-code",
                              headers=_auth(_KEY)).status_code == 200


def test_pair_handshake_stays_public(pairing_client):
    # No code active → the handler's own 400, not the auth gate's 401.
    r = pairing_client.post("/api/cloud/pair", json={"code": "000000"})
    assert r.status_code == 400


# The cloud calls pair-verify and configure back while pairing (and rotating
# the device token). It never has the Pi's API key, so behind the gate pairing
# could not finish in API-key mode — the mode the docs say to use while the Pi
# is on the public address pairing needs.

@pytest.fixture
def cloud_callback_client(monkeypatch, pairing_client):
    monkeypatch.setattr(cloud_router_mod, "_pairing_attempts", 0)
    monkeypatch.setattr(cloud_router_mod, "_pairing_lockout_until", 0.0)
    monkeypatch.setattr(cloud_router_mod, "_configure_tokens", {})
    for attr in ("cloud_url", "cloud_token", "cloud_device_id"):
        monkeypatch.setattr(settings, attr, getattr(settings, attr))
    monkeypatch.setattr(settings, "cloud_device_id", "dev-42")
    monkeypatch.setattr(cloud_service, "_connector_running", False)
    return pairing_client


def _configure_token(client: TestClient) -> str:
    code = client.post("/api/cloud/pairing-code", headers=_auth(_KEY)).json()["code"]
    r = client.post("/api/cloud/pair", json={"code": code})
    assert r.status_code == 200, r.text
    return r.json()["configure_token"]


def test_cloud_pairing_callbacks_need_no_bearer(cloud_callback_client):
    client = cloud_callback_client
    token = _configure_token(client)

    verify = client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.status_code == 200, verify.text
    assert verify.json()["valid"] is True

    configure = client.post("/api/cloud/configure", json={
        "configure_token": token, "cloud_device_id": "dev-42",
        "device_token": "tok-42", "cloud_url": "https://relay.sporeprint.ai",
    })
    assert configure.status_code == 200, configure.text
    assert "SPOREPRINT_CLOUD_TOKEN=tok-42" in cloud_service.env_path().read_text()


def test_cloud_pairing_callbacks_still_need_a_live_configure_token(cloud_callback_client):
    client = cloud_callback_client
    # The handlers' own 401s: public route, no token.
    assert client.get("/api/cloud/pair-verify",
                      params={"configure_token": "forged"}).status_code == 401
    r = client.post("/api/cloud/configure", json={
        "configure_token": "forged", "cloud_device_id": "dev-42", "device_token": "x",
    })
    assert r.status_code == 401
    assert "configure_token" in r.json()["detail"]
    assert not cloud_service.env_path().exists()
    # The token is single-use: a replayed configure is refused.
    token = _configure_token(client)
    body = {"configure_token": token, "cloud_device_id": "dev-42", "device_token": "tok"}
    assert client.post("/api/cloud/configure", json=body).status_code == 200
    assert client.post("/api/cloud/configure", json=body).status_code == 401


def test_only_the_callback_methods_are_public(cloud_callback_client):
    client = cloud_callback_client
    assert client.post("/api/cloud/pair-verify").status_code == 401
    assert client.get("/api/cloud/configure").status_code == 401


def test_non_api_path_is_not_gated(gated_client):
    # The middleware only guards /api/*; a non-/api route is untouched.
    assert gated_client.get("/public").status_code == 200


def test_options_preflight_bypasses_auth(gated_client):
    # CORS preflight carries no auth; it must NOT be turned into a 401.
    r = gated_client.options("/api/private")
    assert r.status_code != 401


def test_gate_is_off_when_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/api/private")
    async def private():
        return {"ok": True}

    client = TestClient(app)
    # No bearer, but with no key configured the LAN-trust mode lets it through.
    assert client.get("/api/private").status_code == 200


# ── _extract_bearer — header parsing edge cases ────────────────────────────

@pytest.mark.parametrize("header,expected", [
    ("Bearer abc123", "abc123"),
    ("bearer abc123", "abc123"),          # scheme is case-insensitive
    ("Bearer   abc123  ", "abc123"),      # surrounding whitespace stripped
    (None, None),
    ("", None),
    ("abc123", None),                     # no scheme
    ("Basic abc123", None),               # wrong scheme
    ("Bearer", None),                     # scheme only, no token
])
def test_extract_bearer(header, expected):
    assert _extract_bearer(header) == expected


# ── _valid_token — constant-time compare, key set vs unset ─────────────────

def test_valid_token_unset_key_accepts_anything(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    assert _valid_token(None) is True
    assert _valid_token("whatever") is True


def test_valid_token_set_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", _KEY)
    assert _valid_token(_KEY) is True
    assert _valid_token("wrong") is False
    assert _valid_token(None) is False
    # Length mismatch must not crash compare_digest — just returns False.
    assert _valid_token(_KEY + "x") is False


def test_valid_token_rejects_non_ascii_and_non_str_without_raising(monkeypatch):
    # compare_digest raises TypeError on non-ASCII str and on mixed types;
    # every odd token must simply be wrong.
    monkeypatch.setattr(settings, "api_key", _KEY)
    assert _valid_token("éé") is False
    assert _valid_token("s3cret-lan-kéy") is False
    for odd in (123, 1.5, b"s3cret-lan-key", ["s3cret-lan-key"], {"t": 1}, True):
        assert _valid_token(odd) is False, odd


def test_non_ascii_key_matches_itself(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "tök€n-key")
    assert _valid_token("tök€n-key") is True
    assert _valid_token("tok€n-key") is False


def test_non_ascii_bearer_is_401_not_500(gated_client):
    # Header bytes are decoded as latin-1, so \xe9 arrives as a non-ASCII str.
    client = TestClient(gated_client.app, raise_server_exceptions=False)
    r = client.get("/api/private", headers={"Authorization": b"Bearer \xe9\xe9"})
    assert r.status_code == 401


# ── _connect_rate_ok — sliding-window limiter ──────────────────────────────

class _Clock:
    """Stands in for the `time` module: `t` is the monotonic clock, `wall`
    the wall clock (equal unless a test steps it)."""

    def __init__(self, t: float) -> None:
        self.t = t
        self.wall = t

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.wall


@pytest.fixture(autouse=True)
def _clear_rate_state():
    auth._connect_attempts.clear()
    yield
    auth._connect_attempts.clear()


def test_rate_limiter_none_addr_always_ok():
    # No remote addr (e.g. unix socket) → never rate-limited.
    for _ in range(auth._CONNECT_RATE_CAP + 5):
        assert _connect_rate_ok(None) is True


def test_rate_limiter_trips_at_cap_and_recovers(monkeypatch):
    clock = _Clock(1000.0)
    monkeypatch.setattr(auth, "time", clock)
    ip = "192.168.1.50"

    # The first CAP attempts pass; the next one trips.
    for _ in range(auth._CONNECT_RATE_CAP):
        assert _connect_rate_ok(ip) is True
    assert _connect_rate_ok(ip) is False, "the (cap+1)th attempt in-window must trip"

    # Still tripped a moment later, inside the window.
    clock.t += auth._CONNECT_RATE_WINDOW / 2
    assert _connect_rate_ok(ip) is False

    # Advance past the window → the old timestamps age out → recovers.
    clock.t += auth._CONNECT_RATE_WINDOW + 1
    assert _connect_rate_ok(ip) is True


def test_rate_limiter_is_per_ip(monkeypatch):
    clock = _Clock(2000.0)
    monkeypatch.setattr(auth, "time", clock)

    for _ in range(auth._CONNECT_RATE_CAP):
        assert _connect_rate_ok("10.0.0.1") is True
    assert _connect_rate_ok("10.0.0.1") is False
    # A different IP has its own budget.
    assert _connect_rate_ok("10.0.0.2") is True


def test_a_backward_wall_clock_step_does_not_lock_clients_out(monkeypatch):
    """Windows were measured on the wall clock: after it stepped back, the
    entries stamped before the step never aged out, and a dashboard
    reconnecting every 2 min (far under the cap) was refused until the wall
    clock caught up again."""
    clock = _Clock(10_000.0)
    monkeypatch.setattr(auth, "time", clock)
    ip = "192.168.1.60"
    for _ in range(5):
        assert _connect_rate_ok(ip) is True
    clock.wall -= 3600  # NTP / `date -s` / an RTC that ran ahead
    for _ in range(35):
        clock.t += 120
        clock.wall += 120
        assert _connect_rate_ok(ip) is True


def test_rate_limiter_forgets_idle_clients(monkeypatch):
    clock = _Clock(5000.0)
    monkeypatch.setattr(auth, "time", clock)
    monkeypatch.setattr(auth, "_CONNECT_RATE_MAX_CLIENTS", 8)
    for i in range(8):
        assert _connect_rate_ok(f"10.0.1.{i}") is True
    clock.t += auth._CONNECT_RATE_WINDOW + 1
    assert _connect_rate_ok("10.0.2.1") is True
    # Every address idle for a whole window was dropped to make room.
    assert set(auth._connect_attempts) == {"10.0.2.1"}
    # Still bounded when every remembered client is active.
    for i in range(20):
        assert _connect_rate_ok(f"10.0.3.{i}") is True
    assert len(auth._connect_attempts) <= 8


# ── socketio_auth_ok — honours key + rate limit ────────────────────────────

def test_socketio_auth_unset_key_accepts(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    assert socketio_auth_ok({"token": "anything"}) is True
    assert socketio_auth_ok(None) is True


def test_socketio_auth_checks_token(monkeypatch):
    monkeypatch.setattr(settings, "api_key", _KEY)
    assert socketio_auth_ok({"token": _KEY}) is True
    assert socketio_auth_ok({"token": "wrong"}) is False
    assert socketio_auth_ok({}) is False
    assert socketio_auth_ok(None) is False


def test_socketio_auth_odd_tokens_are_refused_not_raised(monkeypatch):
    # The Socket.IO auth payload is client JSON: the token can be any type.
    monkeypatch.setattr(settings, "api_key", _KEY)
    for odd in ("éé", "\ud800", 42, None, [_KEY], {"k": _KEY}, True):
        assert socketio_auth_ok({"token": odd}) is False, odd
    assert socketio_auth_ok("not-a-dict") is False


def test_socketio_auth_rate_limited_even_with_valid_token(monkeypatch):
    clock = _Clock(3000.0)
    monkeypatch.setattr(auth, "time", clock)
    monkeypatch.setattr(settings, "api_key", _KEY)
    ip = "192.168.1.77"

    # Exhaust the connect budget with valid tokens.
    for _ in range(auth._CONNECT_RATE_CAP):
        assert socketio_auth_ok({"token": _KEY}, remote_addr=ip) is True
    # A valid token no longer helps once the IP is over the cap.
    assert socketio_auth_ok({"token": _KEY}, remote_addr=ip) is False


# ── Socket.IO peer address ─────────────────────────────────────────────────
#
# python-engineio's ASGI driver hardcodes environ['REMOTE_ADDR'] = '127.0.0.1',
# so keying the connect rate-limit on it put every dashboard in ONE bucket.
# These build the environ with the real driver so the placeholder is exercised.

async def _engineio_environ(client, headers=()):
    from engineio.async_drivers.asgi import translate_request

    scope = {
        "type": "http",
        "path": "/socket.io/",
        "query_string": b"EIO=4&transport=polling",
        "headers": list(headers),
        "client": client,
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    return await translate_request(scope, receive, send)


async def test_socketio_client_addr_is_the_asgi_peer_not_the_placeholder():
    environ = await _engineio_environ(("192.168.1.50", 50123))
    assert environ["REMOTE_ADDR"] == "127.0.0.1"  # the driver's placeholder
    assert auth.socketio_client_addr(environ) == "192.168.1.50"


async def test_socketio_client_addr_ignores_a_forged_forwarded_for():
    # uvicorn rewrites scope['client'] from X-Forwarded-For only for a trusted
    # proxy hop; the raw header from a LAN client on :8000 must not be trusted.
    environ = await _engineio_environ(
        ("192.168.1.50", 50123), [(b"x-forwarded-for", b"10.9.9.9")])
    assert auth.socketio_client_addr(environ) == "192.168.1.50"


def test_socketio_client_addr_falls_back_to_remote_addr():
    assert auth.socketio_client_addr({"REMOTE_ADDR": "192.168.1.10"}) == "192.168.1.10"
    assert auth.socketio_client_addr({}) is None
    assert auth.socketio_client_addr(None) is None


async def test_sio_connect_rate_limits_each_client_separately():
    import app.health.service as health_service
    from app import main

    health_service._sio_clients.clear()
    try:
        first = await _engineio_environ(("192.168.1.50", 40000))
        for i in range(auth._CONNECT_RATE_CAP):
            assert await main._sio_connect(f"a{i}", first) is None
        assert await main._sio_connect("a-over", first) is False

        # A second dashboard has its own budget, and is tracked by its own IP.
        second = await _engineio_environ(("192.168.1.51", 40001))
        assert await main._sio_connect("b0", second) is None
        assert health_service._sio_clients["b0"]["ip"] == "192.168.1.51"
    finally:
        health_service._sio_clients.clear()
