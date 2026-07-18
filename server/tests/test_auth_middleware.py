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
from app.auth import (
    ApiKeyMiddleware,
    _connect_rate_ok,
    _extract_bearer,
    _valid_token,
    socketio_auth_ok,
)
from app.config import settings


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


def test_public_vision_frame_path_bypasses_auth(gated_client):
    # /api/vision/frame is whitelisted for the camera node (no key slot).
    assert gated_client.get("/api/vision/frame").status_code == 200


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


# ── _connect_rate_ok — sliding-window limiter ──────────────────────────────

class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def time(self) -> float:
        return self.t


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
