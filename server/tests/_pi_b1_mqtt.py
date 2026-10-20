"""Shared stand-ins for the MQTT ingest tests.

* RecordingSio: a Socket.IO server that records what the ingest emits.
* FakeBroker: an aiomqtt.Client stand-in that plays scripted broker sessions
  through the real start_mqtt loop; run_mqtt_loop drives it.
* spy_ingest / capture_ntfy: what a frame reaches downstream (the rules
  engine, the cloud relay, ntfy), with nothing leaving the process.
* Row helpers for hardware_nodes and telemetry_readings.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.mqtt
from app.config import settings
from app.db import get_db


class RecordingSio:
    """Records (event, data) for every emit."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))

    def named(self, event: str) -> list[dict]:
        return [d for e, d in self.events if e == event]


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
    Records each connect's keyword arguments and every subscription.
    """

    def __init__(self, *sessions) -> None:
        self.sessions = list(sessions)
        self.connects: list[dict] = []
        self.subscriptions: list[str] = []

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
                return None

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
    .forwards [(node_id, payload)] forwarded to the cloud relay.
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


def capture_ntfy(monkeypatch) -> list[dict]:
    """Capture ntfy publishes as {"title", "priority", "message"} (ntfy's JSON
    API); cloud events are dropped."""
    posts: list[dict] = []

    class _Response:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kwargs):
            posts.append({"title": json["title"], "priority": json["priority"],
                          "message": json["message"]})
            return _Response()

    async def _no_cloud(*args, **kwargs):
        return None

    monkeypatch.setattr(settings, "ntfy_url", "http://ntfy.test")
    monkeypatch.setattr("app.notifications.service.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.mqtt.forward_event", _no_cloud)
    return posts


async def insert_node(node_id: str, **columns) -> None:
    cols = {"node_type": "climate", **columns}
    names = ", ".join(["node_id", *cols])
    marks = ", ".join("?" for _ in range(len(cols) + 1))
    async with get_db() as db:
        await db.execute(f"INSERT INTO hardware_nodes ({names}) VALUES ({marks})",
                         (node_id, *cols.values()))
        await db.commit()


async def node_row(node_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM hardware_nodes WHERE node_id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def node_ids() -> list[str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT node_id FROM hardware_nodes ORDER BY node_id")
        return [r["node_id"] for r in await cursor.fetchall()]


async def readings(node_id: str, sensor: str | None = None) -> list[dict]:
    """A node's stored readings (one sensor, or all), oldest first."""
    sql = ("SELECT timestamp, sensor, value, session_id FROM telemetry_readings "
           "WHERE node_id = ?")
    params: tuple = (node_id,)
    if sensor is not None:
        sql += " AND sensor = ?"
        params += (sensor,)
    async with get_db() as db:
        cursor = await db.execute(sql + " ORDER BY timestamp, id", params)
        return [dict(r) for r in await cursor.fetchall()]
