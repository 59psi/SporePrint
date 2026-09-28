"""Host-header allow-list (app/host_allow.py) — DNS-rebinding protection.

In LAN-trust mode a web page from anywhere could re-point its own hostname
at the Pi's LAN address and drive the whole API as same-origin. The one thing
that page cannot change is the Host header, so the server answers only for
names an outside attacker cannot get a public DNS record for, plus the
operator's own SPOREPRINT_PUBLIC_UI_URL / SPOREPRINT_ALLOWED_HOSTS.
"""

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app import host_allow, main
from app.config import settings
from app.host_allow import HostAllowMiddleware, host_is_allowed


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "")
    monkeypatch.setattr(settings, "public_ui_url", "http://sporeprint.local:3001")


@pytest.mark.parametrize("host", [
    None,                          # no Host at all: no browser sends that
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
        " pi.example.net , *.ts.net, .corp.example, 203.0.113.7, 198.51.100.0/24, [2001:db8::5] ,",
    )
    for host in ("pi.example.net:3001", "grow.tail1234.ts.net", "a.b.corp.example",
                 "203.0.113.7", "198.51.100.44:8000", "[2001:db8::5]:8000"):
        assert host_is_allowed(host) is True, host
    for host in ("example.net", "ts.net.evil.com", "203.0.113.8", "198.51.101.1",
                 "corp.example.evil.com"):
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


async def test_lifespan_passes_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    await HostAllowMiddleware(inner)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]


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


# ── wired into the real app, HTTP + Socket.IO ─────────────────────────────

def test_socket_app_is_wrapped():
    assert isinstance(main.socket_app, HostAllowMiddleware)


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


def test_compose_healthcheck_host_is_allowed():
    """The server container's healthcheck probes http://localhost:8000."""
    assert host_is_allowed("localhost:8000") is True
