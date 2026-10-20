"""Host-header allow-list (app/host_allow.py) — DNS-rebinding protection.

In LAN-trust mode a web page from anywhere could re-point its own hostname
at the Pi's LAN address and drive the whole API as same-origin. The one thing
that page cannot change is the Host header, so the server answers only for
names an outside attacker cannot get a public DNS record for, plus the
operator's own SPOREPRINT_PUBLIC_UI_URL / SPOREPRINT_ALLOWED_HOSTS.
"""

import asyncio

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app import host_allow, main
from app.config import settings
from app.db import get_db
from app.host_allow import HostAllowMiddleware, host_is_allowed


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "")
    monkeypatch.setattr(settings, "public_ui_url", "http://sporeprint.local:3001")
    host_allow._frame_refusals.clear()


@pytest.mark.parametrize("host", [
    None,                          # no Host at all: no browser sends that
    # localhost:8000 is also the server container's compose healthcheck.
    "localhost", "localhost:8000", "LOCALHOST:3001", "localhost.",
    "grow.localhost",
    "127.0.0.1", "127.0.0.1:8000", "127.9.9.9",
    "[::1]", "[::1]:8000",
    "10.0.0.5", "172.16.0.1", "172.31.255.254:3001", "192.168.1.20:3001",
    "169.254.10.1", "[fe80::1]:8000",
    "100.64.0.1", "100.127.255.254:3001",          # CGNAT / Tailscale
    "[fd12:3456::1]",                              # IPv6 ULA
    "[::ffff:192.168.1.20]:8000",                  # IPv4-mapped
    "sporeprint.local", "sporeprint.local:3001", "Sporeprint.Local.",
    "pi.lan", "pi.home", "pi.home.arpa", "pi.internal", "pi.localdomain",
    "raspberrypi", "sporeprint:8000", "server:8000",  # dotless: never public DNS
])
def test_lan_names_are_allowed(host):
    assert host_is_allowed(host) is True


@pytest.mark.parametrize("host", [
    "attacker.example", "attacker.example:8000", "evil.com", "sporeprint.ai",
    "sporeprint.local.evil.com", "localhost.evil.com", "lan.evil.com",
    "1.2.3.4", "8.8.8.8:8000", "172.32.0.1", "100.128.0.1", "0.0.0.0", "0.0.0.0:8000",
    "[2001:db8::1]",
    # Malformed: never guess what the router would make of these.
    "", "   ", "evil.com/api/health?", "user@192.168.1.5", "192.168.1.5:80:80",
    "::1", "[::1", "[evil.com]", "192.168.1.5:port", "a b.local", "host.local:123456",
])
def test_other_names_are_refused(host):
    assert host_is_allowed(host) is False


def test_public_ui_url_host_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "public_ui_url", "https://grow.example.net:8443/")
    assert host_is_allowed("grow.example.net") is True
    assert host_is_allowed("grow.example.net:3001") is True
    assert host_is_allowed("other.example.net") is False
    monkeypatch.setattr(settings, "public_ui_url", "http://203.0.113.9:3001")
    assert host_is_allowed("203.0.113.9:3001") is True


def test_extra_allowed_hosts(monkeypatch):
    monkeypatch.setattr(
        settings, "allowed_hosts",
        " pi.example.net , *.ts.net, .corp.example, 203.0.113.7, 198.51.100.0/24, [2001:db8::5] ,"
        " *.",                       # a bare wildcard admits nothing
    )
    for host in ("pi.example.net:3001", "grow.tail1234.ts.net", "a.b.corp.example",
                 "203.0.113.7", "198.51.100.44:8000", "[2001:db8::5]:8000"):
        assert host_is_allowed(host) is True, host
    for host in ("example.net", "ts.net.evil.com", "203.0.113.8", "198.51.101.1",
                 "corp.example.evil.com", "evil.com"):
        assert host_is_allowed(host) is False, host


def test_allowed_host_entries_may_carry_a_port(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "pi.example.net:3001, [2001:db8::9]:8000, bad/entry")
    assert host_is_allowed("pi.example.net") is True
    assert host_is_allowed("pi.example.net:8000") is True
    assert host_is_allowed("[2001:db8::9]") is True
    assert host_is_allowed("bad") is True       # dotless, allowed anyway
    assert host_is_allowed("entry.example") is False


def test_a_malformed_public_ui_url_does_not_break_requests(monkeypatch):
    monkeypatch.setattr(settings, "public_ui_url", "http://[not-a-url")
    assert host_is_allowed("sporeprint.local") is True
    assert host_is_allowed("evil.com") is False


def test_star_disables_the_check(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "pi.example.net, *")
    assert host_is_allowed("anything.example.com") is True
    assert host_is_allowed("evil.com/x?") is True


# ── the middleware ────────────────────────────────────────────────────────

def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/private")
    async def private():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/provision/ca")
    async def ca():
        return {"pem": "public"}

    @app.get("/api/health/detail/system")
    async def detail():
        return {"cpu": 1}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.add_middleware(HostAllowMiddleware)
    return app


def _client(host: str) -> TestClient:
    return TestClient(_app(), base_url=f"http://{host}")


def test_rebound_host_gets_421_with_a_clear_message():
    r = _client("attacker.example:8000").get("/api/private")
    assert r.status_code == 421
    body = r.json()
    assert "attacker.example" in body["detail"]
    assert "SPOREPRINT_ALLOWED_HOSTS" in body["detail"]


def test_lan_host_passes():
    assert _client("192.168.1.20:8000").get("/api/private").json() == {"ok": True}


def test_health_and_public_ca_answer_any_host():
    """Container/uptime probes and the Secure-MQTT CA fetch (a node may know
    the Pi by any name) — both serve nothing sensitive."""
    client = _client("attacker.example")
    assert client.get("/api/health").status_code == 200
    assert client.head("/api/health").status_code in (200, 405)
    assert client.get("/api/provision/ca").status_code == 200
    assert client.get("/api/health/detail/system").status_code == 421
    assert client.post("/api/provision/ca").status_code == 421


def test_duplicate_host_headers_are_refused():
    client = _client("localhost")
    # Each allowed on its own; together a proxy and the app could disagree.
    r = client.get("/api/private", headers=[("host", "localhost"), ("host", "192.168.1.5")])
    assert r.status_code == 421


# TestClient's websocket_connect ignores base_url for Host (always
# "testserver"), so these set the header explicitly.

def test_websocket_from_a_rebound_host_gets_421():
    client = TestClient(_app())
    with pytest.raises(WebSocketDenialResponse) as exc:
        with client.websocket_connect("/ws", headers={"host": "attacker.example"}):
            pass
    assert exc.value.status_code == 421
    assert "SPOREPRINT_ALLOWED_HOSTS" in exc.value.json()["detail"]


async def test_websocket_refusal_without_the_denial_extension_closes():
    """Servers without websocket.http.response get a policy close (the
    handshake is then answered 403)."""
    sent = []
    scope = {"type": "websocket", "path": "/ws", "headers": [(b"host", b"evil.com")],
             "extensions": {}}

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    async def inner(scope, receive, send):
        raise AssertionError("refused request reached the app")

    await HostAllowMiddleware(inner)(scope, receive, send)
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.parametrize("scope", [
    {"type": "lifespan"},
    # No Host header at all: no browser sends that (curl --http1.0, probes).
    {"type": "http", "method": "GET", "path": "/api/private", "headers": []},
], ids=["lifespan", "no-host-header"])
async def test_a_scope_with_no_host_to_check_passes_through(scope):
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    await HostAllowMiddleware(inner)(scope, None, None)
    assert seen == [scope["type"]]


@pytest.mark.parametrize("host", ["sporeprint.local:3001", "192.168.1.9:8000"])
def test_websocket_from_a_lan_host_connects(host):
    client = TestClient(_app())
    with client.websocket_connect("/ws", headers={"host": host}) as ws:
        assert ws.receive_text() == "hi"


def test_refusals_are_logged_once_per_host(caplog):
    host_allow._logged_hosts.clear()
    client = _client("attacker.example")
    with caplog.at_level("WARNING", logger="app.host_allow"):
        for _ in range(3):
            client.get("/api/private")
    assert sum("attacker.example" in r.getMessage() for r in caplog.records) == 1


# ── a camera that reaches the Pi by a refused name ────────────────────────
#
# Its uploads get 421 while MQTT keeps it looking online, so the vision checks
# stopped with nothing to say why (e.g. a portal "Pi host" of
# sporeprint.fritz.box after the allow-list arrived).

async def _post_frame(node_id: str | None, host: str = "sporeprint.fritz.box:8000") -> int:
    headers = [(b"host", host.encode())]
    if node_id is not None:
        headers.append((b"x-node-id", node_id.encode()))
    scope = {"type": "http", "method": "POST", "path": "/api/vision/frame",
             "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def inner(scope, receive, send):
        raise AssertionError("refused request reached the app")

    await HostAllowMiddleware(inner)(scope, receive, send)
    await asyncio.gather(*host_allow._background_pages)
    return sent[0]["status"]


@pytest.fixture()
def pages(monkeypatch):
    sent = []

    async def _notify_warning(title, message, dedup_key=None, dedup_seconds=300):
        sent.append({"title": title, "message": message, "dedup_key": dedup_key,
                     "dedup_seconds": dedup_seconds})

    monkeypatch.setattr(host_allow, "notify_warning", _notify_warning)
    return sent


async def _register(node_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, last_seen, status) "
            "VALUES (?, 'camera', 0, 'online')", (node_id,))
        await db.commit()


async def test_a_registered_camera_with_a_refused_name_is_logged_and_paged(pages, caplog):
    await _register("cam-01")
    with caplog.at_level("WARNING", logger="app.host_allow"):
        for _ in range(3):
            assert await _post_frame("cam-01") == 421
    logged = [r.getMessage() for r in caplog.records if "cam-01" in r.getMessage()]
    assert len(logged) == 1, logged
    assert "sporeprint.fritz.box:8000" in logged[0]
    assert len(pages) == 1
    assert pages[0]["dedup_key"] == "frame-host:cam-01"
    assert pages[0]["dedup_seconds"] == 86400
    assert "SPOREPRINT_ALLOWED_HOSTS" in pages[0]["message"]
    assert "sporeprint.fritz.box:8000" in pages[0]["message"]


async def test_an_unregistered_node_id_is_logged_but_never_pages(pages, caplog):
    with caplog.at_level("WARNING", logger="app.host_allow"):
        assert await _post_frame("made-up-01") == 421
    assert any("made-up-01" in r.getMessage() for r in caplog.records)
    assert pages == []


@pytest.mark.parametrize("node_id", [None, "bad id", "x" * 40])
async def test_a_frame_without_a_valid_node_id_is_only_the_usual_refusal(pages, caplog, node_id):
    with caplog.at_level("WARNING", logger="app.host_allow"):
        assert await _post_frame(node_id) == 421
    assert not any("camera" in r.getMessage() for r in caplog.records)
    assert pages == []
    assert host_allow._frame_refusals == {}


class _Monotonic:
    def __init__(self, now: float) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


async def test_camera_refusal_memory_is_bounded(pages, monkeypatch):
    """Capped, so invented node ids cannot grow it; entries older than the
    log interval make room for new cameras."""
    clock = _Monotonic(1000.0)
    monkeypatch.setattr(host_allow, "time", clock)
    monkeypatch.setattr(host_allow, "_FRAME_REFUSAL_CAP", 4)
    for i in range(10):
        assert await _post_frame(f"cam-{i}") == 421
    assert {node for node, _ in host_allow._frame_refusals} == {"cam-0", "cam-1", "cam-2", "cam-3"}

    clock.now += host_allow._FRAME_REFUSAL_LOG_SECONDS
    assert await _post_frame("cam-new") == 421
    assert {node for node, _ in host_allow._frame_refusals} == {"cam-new"}


# ── wired into the real app, HTTP + Socket.IO ─────────────────────────────

def test_real_app_refuses_a_rebound_host_on_api_and_socketio():
    client = TestClient(main.socket_app, base_url="http://attacker.example:8000")
    assert client.get("/api/species").status_code == 421
    assert client.get("/socket.io/", params={"EIO": "4", "transport": "polling"}).status_code == 421
    assert client.get("/api/health").status_code == 200


def test_real_app_refuses_a_socketio_websocket_from_a_rebound_host():
    client = TestClient(main.socket_app)
    with pytest.raises(WebSocketDenialResponse) as exc:
        with client.websocket_connect("/socket.io/?EIO=4&transport=websocket",
                                      headers={"host": "attacker.example:3001"}):
            pass
    assert exc.value.status_code == 421


def test_real_app_serves_socketio_to_a_lan_host():
    client = TestClient(main.socket_app, base_url="http://192.168.1.20:8000")
    r = client.get("/socket.io/", params={"EIO": "4", "transport": "polling"})
    assert r.status_code == 200
    assert '"sid"' in r.text
