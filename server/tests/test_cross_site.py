"""Requests a page on another site sends to the Pi's real LAN name.

CORS only decides what a cross-origin page may *read*. In LAN-trust mode a
page on any site the operator visits could still *send* a body-less POST to
http://sporeprint.local:3001 (abort a session, mint a new pairing code), and
the Socket.IO server accepted every Origin, so the page could also open and
read the live telemetry / alert / log stream. host_allow.CrossSiteRequestGuard
refuses state-changing requests whose Origin is not a name the Pi answers to,
and Socket.IO checks the handshake's Origin with the same rule.

Also here: the CORS method / header lists and the middleware order (an
API-key 401 still carries the CORS headers a cross-origin client needs).
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.cloud.router as cloud_router_mod
from app import host_allow, main
from app.config import settings
from app.db import get_db
from app.host_allow import origin_is_allowed

LAN = "http://sporeprint.local:3001"
EVIL = "http://evil.example"


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "")
    monkeypatch.setattr(settings, "public_ui_url", LAN)
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(cloud_router_mod, "_pairing_code", None)
    host_allow._logged_origins.clear()


@pytest.fixture
def lan_client():
    """The real ASGI stack (Host allow-list -> cross-site guard -> Socket.IO
    -> FastAPI), reached by the dashboard's name."""
    return TestClient(main.socket_app, base_url=LAN)


async def _session() -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO sessions (name, species_profile_id) VALUES ('tub 1', 'blue_oyster')")
        await db.commit()
        return cursor.lastrowid


async def _status(session_id: int) -> str:
    async with get_db() as db:
        cursor = await db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
        return (await cursor.fetchone())["status"]


# ── state-changing requests ───────────────────────────────────────────────

async def test_a_cross_site_body_less_post_is_refused(lan_client, mock_mqtt):
    sid = await _session()
    r = lan_client.post(f"/api/sessions/{sid}/abort", headers={"Origin": EVIL})
    assert r.status_code == 403
    assert "evil.example" in r.json()["detail"]
    assert await _status(sid) == "active"
    assert mock_mqtt == []


async def test_the_dashboard_itself_still_writes(lan_client, mock_mqtt):
    sid = await _session()
    r = lan_client.post(f"/api/sessions/{sid}/abort", headers={"Origin": LAN})
    assert r.status_code == 200, r.text
    assert await _status(sid) == "aborted"


@pytest.mark.parametrize("origin", [
    None,                              # curl, scripts, the camera, the cloud
    LAN,
    "http://192.168.1.20:3001",        # the dashboard by LAN IP
    "http://100.101.102.103:3001",     # by Tailscale (CGNAT) IP
    "http://[fd12:3456::1]:3001",      # by IPv6 ULA
    "http://localhost:5173",           # the dashboard's dev server
    "capacitor://localhost",
])
def test_writes_from_lan_pages_and_non_browsers_pass(lan_client, origin):
    headers = {"Origin": origin} if origin else {}
    r = lan_client.post("/api/cloud/pairing-code", headers=headers)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("origin", [
    EVIL, "https://sporeprint.ai", "http://sporeprint.local.evil.com",
    "null",                            # sandboxed frame, file:// page
    "http://8.8.8.8", "not a url",
])
def test_writes_from_other_sites_are_refused(lan_client, origin):
    r = lan_client.post("/api/cloud/pairing-code", headers={"Origin": origin})
    assert r.status_code == 403
    assert cloud_router_mod._pairing_code is None  # the operator's code untouched


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_unsafe_method_is_guarded(lan_client, method):
    r = lan_client.request(method, "/api/automation/rules/999", headers={"Origin": EVIL})
    assert r.status_code == 403


def test_two_origin_headers_are_refused(lan_client):
    r = lan_client.post("/api/cloud/pairing-code",
                        headers=[("origin", LAN), ("origin", EVIL)])
    assert r.status_code == 403


def test_reads_are_not_guarded(lan_client):
    # CORS keeps their answers from the page; nothing changes on the Pi.
    assert lan_client.get("/api/species", headers={"Origin": EVIL}).status_code == 200


def test_a_listed_public_name_may_write(lan_client, monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "pi.example.net")
    r = lan_client.post("/api/cloud/pairing-code",
                        headers={"Origin": "https://pi.example.net"})
    assert r.status_code == 200


def test_star_turns_off_the_host_check_not_the_origin_check(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "*")
    client = TestClient(main.socket_app, base_url="https://grow.example.com")
    # The dashboard on its own (unlisted) name still works...
    assert client.post("/api/cloud/pairing-code",
                       headers={"Origin": "https://grow.example.com"}).status_code == 200
    # ...but another site still cannot drive it.
    assert client.post("/api/cloud/pairing-code",
                       headers={"Origin": EVIL}).status_code == 403


def test_refusals_are_logged_once_per_origin(lan_client, caplog):
    with caplog.at_level("WARNING", logger="app.host_allow"):
        for _ in range(3):
            lan_client.post("/api/cloud/pairing-code", headers={"Origin": EVIL})
    assert sum("evil.example" in r.getMessage() for r in caplog.records) == 1


# The deprecated GET form of experiment analysis spends Claude credit. A
# cross-site <img> load of it carries no Origin, only Sec-Fetch-Site.

@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": EVIL, "Sec-Fetch-Site": "cross-site"},
])
def test_a_cross_site_load_of_the_paid_get_is_refused(lan_client, headers):
    assert lan_client.get("/api/experiments/1/analyze", headers=headers).status_code == 403


@pytest.mark.parametrize("headers", [
    {}, {"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"},
    {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "cross-site"},
])
def test_the_paid_get_still_serves_the_dashboard_and_scripts(lan_client, headers):
    # Reaches the handler: no such experiment.
    assert lan_client.get("/api/experiments/1/analyze", headers=headers).status_code == 404


# ── Socket.IO ─────────────────────────────────────────────────────────────

_HANDSHAKE = {"EIO": "4", "transport": "polling"}


def test_socketio_refuses_a_page_on_another_site(lan_client):
    r = lan_client.get("/socket.io/", params=_HANDSHAKE, headers={"Origin": EVIL})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("origin", [None, LAN, "http://192.168.1.77:8123"])
def test_socketio_serves_lan_pages_and_native_clients(lan_client, origin):
    headers = {"Origin": origin} if origin else {}
    r = lan_client.get("/socket.io/", params=_HANDSHAKE, headers=headers)
    assert r.status_code == 200, r.text
    assert '"sid"' in r.text
    if origin:
        assert r.headers["access-control-allow-origin"] == origin


def _ws_headers(origin: str | None) -> dict:
    headers = {"host": "sporeprint.local:3001", "upgrade": "websocket",
               "connection": "upgrade"}
    if origin:
        headers["origin"] = origin
    return headers


@pytest.mark.parametrize("origin", [None, LAN])
def test_socketio_websocket_from_the_lan_connects(lan_client, origin):
    with lan_client.websocket_connect("/socket.io/?EIO=4&transport=websocket",
                                      headers=_ws_headers(origin)) as ws:
        assert '"sid"' in ws.receive_text()


def test_socketio_websocket_from_another_site_is_refused(lan_client):
    with pytest.raises(WebSocketDisconnect):
        with lan_client.websocket_connect("/socket.io/?EIO=4&transport=websocket",
                                          headers=_ws_headers(EVIL)) as ws:
            ws.receive_text()


@pytest.mark.parametrize("origin,host,allowed", [
    (None, None, True),
    (LAN, "sporeprint.local", True),         # nginx forwards Host without the port
    ("https://grow.example.com", "grow.example.com:443", True),  # same host
    ("https://grow.example.com", "sporeprint.local", False),
    ("http://[fd00::5]:3001", "[fd00::5]", True),
    ("null", "sporeprint.local", False),
    ("http://user@192.168.1.5", None, False),
    ("http://[not-an-ip", "sporeprint.local", False),   # unparseable
])
def test_origin_rule(origin, host, allowed):
    assert origin_is_allowed(origin, host) is allowed


# ── CORS lists and the middleware order ───────────────────────────────────

def test_cors_preflight_allows_put_and_the_request_id(lan_client):
    r = lan_client.options("/api/settings/ntfy_topic", headers={
        "Origin": "capacitor://localhost",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type, x-request-id",
    })
    assert r.status_code == 200, r.text
    assert "PUT" in r.headers["access-control-allow-methods"]
    assert "x-request-id" in r.headers["access-control-allow-headers"].lower()


def test_cross_origin_clients_can_read_the_request_id(lan_client):
    r = lan_client.get("/api/species", headers={"Origin": "http://192.168.1.50:5173"})
    assert "x-request-id" in r.headers["access-control-expose-headers"].lower()


def test_an_api_key_401_carries_the_cors_headers(lan_client, monkeypatch):
    """ApiKeyMiddleware sat outside CORSMiddleware, so a cross-origin client
    saw an opaque CORS failure instead of the 401."""
    monkeypatch.setattr(settings, "api_key", "s3cret")
    origin = "http://192.168.1.77:8123"
    r = lan_client.get("/api/species", headers={
        "Origin": origin, "Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == origin
    assert r.headers.get("x-request-id")
    ok = lan_client.get("/api/species", headers={
        "Origin": origin, "Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
