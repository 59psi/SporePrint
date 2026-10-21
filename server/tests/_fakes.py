"""Stand-ins for what the server talks to: a Socket.IO server, the MQTT
broker, the Anthropic API, vendor HTTP APIs and KLAP v2 (Tapo) plugs.

Not collected (no ``test_`` prefix). The pytest fixtures built on these
(ntfy_posts, ingest, kasa_wire, ...) live in tests/_fixtures.py.
"""

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import app.mqtt
from app.integrations import _registry
from app.integrations.tapo import klap
from app.integrations.tapo.config import TapoConfig

# The real client class, taken once: route_httpx may be called again in one
# test, and must not wrap its own earlier fake.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ── Socket.IO ──────────────────────────────────────────────────────────────


class RecordingSio:
    """A Socket.IO server, or the cloud socket, that records every emit as
    (event, data)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event: str) -> list[dict]:
        return [d for e, d in self.events if e == event]

    def last(self, event: str) -> dict:
        """The data of the last emit, which must be `event`."""
        assert self.events, "nothing was emitted"
        name, data = self.events[-1]
        assert name == event, (name, data)
        return data


# ── the MQTT broker ────────────────────────────────────────────────────────


class Message:
    """One broker delivery, as aiomqtt hands it to the loop."""

    def __init__(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self.topic = topic
        self.payload = payload
        self.retain = retain


class FakeBroker:
    """Plays one scripted session per connect of the real start_mqtt loop.

    Each session is either a list of Messages (delivered in order, after which
    the loop is stopped the way a shutdown stops it) or an exception, raised
    when the loop connects. A connect past the script stops the loop too.
    Records each connect's keyword arguments, every subscription and every
    (topic, payload) the server publishes.
    """

    def __init__(self, *sessions) -> None:
        self.sessions = list(sessions)
        self.connects: list[dict] = []
        self.subscriptions: list[str] = []
        self.published: list[tuple[str, str]] = []

    @property
    def client(self):
        broker = self

        class _Client:
            def __init__(self, host, port, **kwargs):
                broker.connects.append(kwargs)
                self._n = len(broker.connects) - 1

            async def __aenter__(self):
                if self._n >= len(broker.sessions):
                    raise asyncio.CancelledError
                session = broker.sessions[self._n]
                if isinstance(session, BaseException):
                    raise session
                return self

            async def __aexit__(self, *exc):
                return False

            async def subscribe(self, topic):
                broker.subscriptions.append(topic)

            async def publish(self, topic, payload):
                broker.published.append((topic, payload))

            @property
            def messages(self):
                async def _deliver():
                    for message in broker.sessions[self._n]:
                        yield message
                    raise asyncio.CancelledError  # start_mqtt returns on it

                return _deliver()

        return _Client


async def run_mqtt_loop(monkeypatch, broker: FakeBroker, sio=None) -> list[float]:
    """Run start_mqtt against `broker` until its script ends; returns the
    reconnect pauses the loop asked for (it never really sleeps)."""
    pauses: list[float] = []

    async def _pause(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(app.mqtt.aiomqtt, "Client", broker.client)
    monkeypatch.setattr(app.mqtt, "asyncio",
                        SimpleNamespace(sleep=_pause, CancelledError=asyncio.CancelledError))
    await asyncio.wait_for(app.mqtt.start_mqtt(sio or RecordingSio()), timeout=5)
    return pauses


def spy_ingest(monkeypatch) -> SimpleNamespace:
    """Stub the rules engine and the cloud relay for the ingest path.

    Returns .rules [(node_id, readings)] the engine was handed and
    .forwards [(node_id, payload)] forwarded to the cloud relay. Most tests
    ask for the ``ingest`` fixture instead; one that wraps the real engine
    takes its reference first, then calls this.
    """
    seen = SimpleNamespace(rules=[], forwards=[])

    async def _rules(node_id, readings, sio=None, **kwargs):
        seen.rules.append((node_id, dict(readings)))

    async def _forward(node_id, payload):
        seen.forwards.append((node_id, dict(payload)))

    monkeypatch.setattr("app.automation.engine.evaluate_rules", _rules)
    monkeypatch.setattr("app.mqtt.forward_telemetry", _forward)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)
    return seen


# ── the Anthropic API ──────────────────────────────────────────────────────


def fake_anthropic(reply, *, captured: dict | None = None, stop_reason: str = "end_turn"):
    """A stand-in for ``anthropic.AsyncAnthropic``. messages.create() records
    its keyword arguments in `captured` and answers `reply` as one text block
    (a dict is sent as JSON); an exception `reply` is raised instead."""
    captured = {} if captured is None else captured

    class _Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            if isinstance(reply, BaseException):
                raise reply
            text = reply if isinstance(reply, str) else json.dumps(reply)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                   stop_reason=stop_reason)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    return _Client


# ── vendor HTTP APIs and the integration drivers ───────────────────────────


def route_httpx(monkeypatch, handler: Callable) -> None:
    """Send every httpx.AsyncClient the code under test builds to ``handler``
    (sync or async, ``httpx.Request -> httpx.Response``): real requests, so
    encoding errors surface as they would against the live service."""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(*a, **{**k, "transport": transport}),
    )


def use_drivers(monkeypatch, *drivers) -> None:
    """Make ``drivers`` the registered set the dispatcher and sweeper see,
    so a test never configures the process-wide driver singletons."""
    monkeypatch.setattr(_registry, "registered_drivers", lambda: {d.name: d for d in drivers})


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


# ── KLAP v2 (Tapo) plugs ───────────────────────────────────────────────────

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
