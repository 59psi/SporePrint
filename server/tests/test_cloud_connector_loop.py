"""Cloud connector loop behaviour, driven with a fake Socket.IO client.

* a relay that accepts then immediately drops the session must meet a
  growing backoff, not a ~1 s reconnect storm; a stable session resets it.
* POST /reconnect must actually wake the retry sleep.
* the integrations snapshot is (re)pushed on every connect, and every
  registered connect listener runs even when one fails.
* the device token is never sent over plaintext to a public host.
* credentials persisted by pairing are loaded at connector start.
* buffered frames go out as replayed history; frames the relay never
  acknowledged, or the socket refused, are kept for the next connect; a full
  buffer drops its oldest frame; the connector does not start (or buffer)
  without all three credentials.
* a command arriving on the socket goes through the security gate and is
  answered on the same socket.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app.cloud.service as service
from app.cloud.version import server_version
from app.integrations import _health_sweeper
from tests._pi_b2_cloud import sign


class _FakeClient:
    """Minimal python-socketio AsyncClient stand-in.

    connect() succeeds and fires the registered `connect` handler; wait()
    returns immediately, i.e. the server ends the session straight away.
    Every emit is recorded; `ack` decides whether the relay acknowledges it.
    """

    instances: list["_FakeClient"] = []

    def __init__(self, reconnection: bool = False) -> None:
        self.handlers: dict = {}
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.auth_seen = None
        self.wait_timeout = None
        self.emits: list[tuple[str, dict]] = []
        self.ack = True
        _FakeClient.instances.append(self)

    def on(self, event, handler=None):
        def deco(fn):
            self.handlers[event] = fn
            return fn
        return deco if handler is None else deco(handler)

    async def connect(self, url, auth=None, transports=None, wait_timeout=1):
        self.connect_calls += 1
        self.auth_seen = auth
        self.wait_timeout = wait_timeout
        self.connected = True
        if "connect" in self.handlers:
            await self.handlers["connect"]()

    async def wait(self):
        self.connected = False
        if "disconnect" in self.handlers:
            await self.handlers["disconnect"]()

    async def emit(self, event, data=None, namespace=None, callback=None):
        self.emits.append((event, data))
        if callback is not None and self.ack:
            callback()

    async def call(self, event, data=None, namespace=None, timeout=60):
        self.emits.append((event, data))
        if not self.ack:
            raise TimeoutError
        return None

    async def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


class _SilentRelay(_FakeClient):
    """A relay whose socket died without a FIN: emits succeed, nothing acks."""

    def __init__(self, reconnection: bool = False) -> None:
        super().__init__(reconnection)
        self.ack = False


class _BrokenSocket(_FakeClient):
    """The socket went away under the connector: every emit raises."""

    async def emit(self, event, data=None, namespace=None, callback=None):
        raise ConnectionError("socket is closed")


@pytest.fixture
def connector(monkeypatch):
    _FakeClient.instances = []
    monkeypatch.setattr(service.socketio, "AsyncClient", _FakeClient)
    monkeypatch.setattr(service.settings, "cloud_url", "https://relay.example.com")
    monkeypatch.setattr(service.settings, "cloud_token", "tok")
    monkeypatch.setattr(service.settings, "cloud_device_id", "dev-1")
    for name, value in [
        ("_sio", None), ("_connected", False), ("_reconnect_attempts", 0),
        ("_heartbeat_task", None), ("_wake_event", None),
        ("_connector_running", False), ("_standing_refusal", None),
        ("_connect_error", None), ("_last_snapshot_push", 0), ("_token_refusals", 0),
        ("_queue_drops", 0), ("_last_forward", 0),
    ]:
        monkeypatch.setattr(service, name, value)
    service._inflight.clear()
    _empty_queue()
    # Listeners other tests registered (the app's session sync) would start
    # catch-ups that outlive the test.
    monkeypatch.setattr(service, "_connect_listeners", [])
    monkeypatch.setattr(service, "_health_heartbeat_loop", _noop_loop)
    monkeypatch.setitem(service._task_status, "cloud_connector",
                        {"status": "idle", "last_run": None})
    snapshots: list[int] = []

    async def fake_snapshot():
        snapshots.append(1)

    monkeypatch.setattr(_health_sweeper, "push_state_snapshot", fake_snapshot)
    yield snapshots
    service._inflight.clear()
    _empty_queue()


def _empty_queue():
    while not service._queue.empty():
        service._queue.get_nowait()


async def _noop_loop():
    return None


def _stop_after(n: int, record: list):
    async def fake_backoff_sleep(seconds):
        record.append(seconds)
        if len(record) >= n:
            raise asyncio.CancelledError
    return fake_backoff_sleep


async def _run_connector(monkeypatch, attempts: int = 1, record: list | None = None) -> None:
    """Run the connector for `attempts` connects, then stop it."""
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(attempts, [] if record is None else record))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()


def _live(monkeypatch, client: _FakeClient) -> _FakeClient:
    """A connector whose session is up on `client`."""
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
    monkeypatch.setattr(service, "_connector_running", True)
    return client


# ── reconnect and backoff ────────────────────────────────────────────


async def test_immediate_server_disconnect_backs_off(connector, monkeypatch):
    sleeps: list[float] = []
    await _run_connector(monkeypatch, 4, sleeps)
    assert sleeps == [10, 20, 40, 80], (
        "a session the relay drops immediately must grow the backoff, "
        "not reconnect ~1 s later forever"
    )
    assert _FakeClient.instances[0].connect_calls == 4


async def test_stable_session_resets_backoff(connector, monkeypatch):
    monkeypatch.setattr(service, "_STABLE_SESSION_SECONDS", 0)
    sleeps: list[float] = []
    await _run_connector(monkeypatch, 3, sleeps)
    assert sleeps == [5, 5, 5]


async def test_backoff_sleep_is_woken_by_reconnect_request(monkeypatch):
    monkeypatch.setattr(service, "_wake_event", asyncio.Event())
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_connected", False)

    async def poke():
        await asyncio.sleep(0.01)
        assert service.request_reconnect() == "reconnecting"

    poker = asyncio.create_task(poke())
    await asyncio.wait_for(service._backoff_sleep(30), timeout=2)
    await poker


async def test_stopping_the_connector_closes_a_live_session(connector, monkeypatch):
    """Shutdown cancels the connector mid-session: it closes the socket and
    returns instead of leaving the relay to time the session out."""

    in_session = asyncio.Event()

    class _HeldSession(_FakeClient):
        async def wait(self):
            in_session.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(service.socketio, "AsyncClient", _HeldSession)
    task = asyncio.create_task(service.start_cloud_connector())
    await asyncio.wait_for(in_session.wait(), timeout=5)
    task.cancel()
    await task
    assert _HeldSession.instances[0].disconnect_calls == 1
    assert service._connector_running is False


# ── what a connect does ──────────────────────────────────────────────


async def test_snapshot_pushed_on_every_connect(connector, monkeypatch):
    await _run_connector(monkeypatch, 2)
    assert len(connector) == 2


async def test_every_connect_listener_runs_even_when_one_fails(connector, monkeypatch):
    ran: list[str] = []

    async def broken():
        raise RuntimeError("catch-up failed")

    async def catch_up():
        ran.append("catch_up")

    for listener in (broken, catch_up, catch_up):   # registering twice is a no-op
        service.add_connect_listener(listener)
    await _run_connector(monkeypatch)
    assert ran == ["catch_up"]


async def test_a_standing_refusal_clears_once_the_relay_accepts_the_pi_again(connector, monkeypatch):
    """A resubscribed owner or a re-paired Pi: the next accepted connect ends
    the pause, and telemetry is buffered again."""
    monkeypatch.setattr(service, "_standing_refusal", "subscription_required")
    await _run_connector(monkeypatch)
    assert service._standing_refusal is None
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 72.0})
    assert service._queue.qsize() == 1


async def test_a_command_on_the_socket_is_answered_on_the_same_socket(connector, monkeypatch):
    """The socket's `command` event runs the whole security gate
    (handle_cloud_command) and the command_result goes back on that socket."""
    frame = sign({"id": "cmd-1", "tier": "premium", "target_kind": "system",
                  "channel": "automation", "payload": {"paused": False},
                  "ts": time.time()}, "tok")

    class _CommandingRelay(_FakeClient):
        async def wait(self):
            await self.handlers["command"](frame)
            await super().wait()

    monkeypatch.setattr(service.socketio, "AsyncClient", _CommandingRelay)
    service._seen_command_ids.clear()
    try:
        await _run_connector(monkeypatch)
    finally:
        service._seen_command_ids.clear()
    results = [data for event, data in _CommandingRelay.instances[0].emits
               if event == "command_result"]
    assert results == [{"id": "cmd-1", "success": True, "target_kind": "system",
                        "channel": "automation", "error": None}]


# ── credentials and transport ────────────────────────────────────────


async def test_public_plaintext_cloud_url_is_refused(connector, monkeypatch):
    monkeypatch.setattr(service.settings, "cloud_url", "http://relay.example.com")
    await service.start_cloud_connector()
    assert _FakeClient.instances == [], "must not connect / send the token"
    assert "insecure" in service._task_status["cloud_connector"]["status"]


@pytest.mark.parametrize("url,ok", [
    ("https://relay.sporeprint.ai", True),
    ("wss://relay.sporeprint.ai", True),
    ("http://relay.sporeprint.ai", False),
    ("http://8.8.8.8:5000", False),
    ("http://192.168.1.20:8001", True),
    ("http://127.0.0.1:8001", True),
    ("http://localhost:8001", True),
    ("http://devbox.local:8001", True),
    ("ftp://relay.sporeprint.ai", False),
    ("http://[::1", False),            # not even a URL
])
def test_cloud_url_transport_policy(url, ok):
    assert service.cloud_url_transport_ok(url) is ok


async def test_connector_loads_paired_credentials(connector, monkeypatch):
    monkeypatch.setattr(service.settings, "cloud_url", "")
    monkeypatch.setattr(service.settings, "cloud_token", "")
    service.write_cloud_env({
        "SPOREPRINT_CLOUD_URL": "https://relay.example.com",
        "SPOREPRINT_CLOUD_TOKEN": "paired-token",
        "SPOREPRINT_CLOUD_DEVICE_ID": "dev-9",
    })
    await _run_connector(monkeypatch)
    assert _FakeClient.instances[0].auth_seen == {"token": "paired-token", "device_id": "dev-9"}


async def test_repairing_reconnects_with_the_new_token(connector, monkeypatch):
    """A token rotation while the connector runs: the next attempt presents
    the new token, not the one the process started with."""
    sleeps: list[float] = []

    async def fake_backoff_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError
        service.write_cloud_env({"SPOREPRINT_CLOUD_TOKEN": "rotated",
                                 "SPOREPRINT_CLOUD_DEVICE_ID": "dev-1"})
        assert await service.apply_paired_credentials() is True

    monkeypatch.setattr(service, "_backoff_sleep", fake_backoff_sleep)
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    client = _FakeClient.instances[0]
    assert client.connect_calls == 2
    assert client.auth_seen == {"token": "rotated", "device_id": "dev-1"}


async def test_connect_waits_long_enough_for_the_relay(connector, monkeypatch):
    """The relay answers only after two Supabase round trips; the client's
    1 s default failed every slow handshake."""
    await _run_connector(monkeypatch)
    assert _FakeClient.instances[0].wait_timeout >= 5


@pytest.mark.parametrize("missing, status", [
    (("cloud_device_id",), "disabled — SPOREPRINT_CLOUD_DEVICE_ID not set"),
    (("cloud_token",), "disabled — SPOREPRINT_CLOUD_TOKEN not set"),
    (("cloud_url", "cloud_token", "cloud_device_id"), "disabled"),   # never paired
], ids=["device-id", "token", "all"])
async def test_connector_needs_all_three_credentials(connector, monkeypatch, missing, status):
    for attr in missing:
        monkeypatch.setattr(service.settings, attr, "")
    await service.start_cloud_connector()
    assert _FakeClient.instances == [], "a partial pairing can only be refused"
    assert service._task_status["cloud_connector"]["status"] == status
    # Nothing would ever drain a queue, so nothing is buffered.
    await service.forward_telemetry("climate-01", {"temp_f": 72.0})
    assert service._queue.empty()


# ── the offline buffer and acknowledgements ──────────────────────────


async def test_buffered_frames_drain_as_replayed_history(connector, monkeypatch):
    """Frames buffered while the link was down are history: the relay stores
    them at their own ts and never shows them as the current reading."""
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 91.0, "ts": 1_760_000_000.0})
    assert service._queue.qsize() == 1

    await _run_connector(monkeypatch)
    sent = [data for event, data in _FakeClient.instances[0].emits if event == "telemetry"]
    assert sent == [{"node_id": "climate-01", "ts": 1_760_000_000.0, "temp_f": 91.0,
                     "replay": True}]
    assert service._queue.empty()


async def test_a_full_offline_buffer_drops_the_oldest_frame_and_counts_it(connector, monkeypatch):
    monkeypatch.setattr(service, "_queue", asyncio.Queue(maxsize=2))
    monkeypatch.setattr(service, "_connector_running", True)
    for ts in (1.0, 2.0, 3.0):
        await service.forward_telemetry("climate-01", {"temp_f": 70.0, "ts": ts})
    assert [service._queue.get_nowait()["ts"] for _ in range(2)] == [2.0, 3.0]
    assert service.get_cloud_status()["queue_drops"] == 1


async def test_a_frame_the_socket_refuses_stays_buffered(connector, monkeypatch):
    """Sent live or drained on connect, a frame the dead socket throws back
    is kept for the next connect — not lost and not left tracked in flight."""
    _live(monkeypatch, _BrokenSocket())
    await service.forward_telemetry("climate-01", {"temp_f": 70.0, "ts": 1.0})
    assert service._queue.qsize() == 1
    assert not service._inflight

    assert await service._drain_queue() == 0
    assert service._queue.get_nowait()["ts"] == 1.0
    assert not service._inflight


async def test_unacknowledged_frames_are_kept_for_the_next_connect(connector, monkeypatch):
    monkeypatch.setattr(service.socketio, "AsyncClient", _SilentRelay)
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 70.0, "ts": 1_760_000_000.0})

    await _run_connector(monkeypatch)
    # Sent once into the dead socket, never acknowledged: back in the queue
    # when the disconnect is noticed, and not counted as forwarded.
    assert [e for e, _ in _FakeClient.instances[0].emits].count("telemetry") == 1
    assert service._queue.qsize() == 1
    assert service._queue.get_nowait()["temp_f"] == 70.0
    assert service._last_forward == 0
    assert not service._inflight


async def test_an_acknowledged_frame_is_not_resent(connector, monkeypatch):
    _live(monkeypatch, _FakeClient())
    await service.forward_telemetry("climate-01", {"temp_f": 70.0})
    assert not service._inflight
    assert service._requeue_unacked() == 0
    assert service._queue.empty()
    assert service._last_forward > 0


class _Clock:
    """Stands in for the service module's `time`."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


async def test_unacknowledged_frames_past_the_max_age_are_not_resent(connector, monkeypatch):
    clock = _Clock(1_800_000_000.0)
    monkeypatch.setattr(service, "time", clock)
    _live(monkeypatch, _SilentRelay())
    await service.forward_telemetry("climate-01", {"temp_f": 70.0})
    assert len(service._inflight) == 1
    clock.now += service._INFLIGHT_MAX_AGE_SECONDS + 1
    assert service._requeue_unacked() == 0
    assert service._queue.empty()


# ── events ───────────────────────────────────────────────────────────


async def test_integrations_snapshot_rides_its_own_channel(connector, monkeypatch):
    """The relay fills its integrations cache from the dedicated
    `integrations_state` event; the generic `event` copy stays for clouds
    that read it there."""
    client = _live(monkeypatch, _FakeClient())
    assert await service.forward_event("integrations_state", {"drivers": [{"slug": "kasa"}]})
    events = {event: data for event, data in client.emits}
    assert events["integrations_state"]["drivers"] == [{"slug": "kasa"}]
    assert events["event"]["type"] == "integrations_state"


async def test_a_confirmed_event_counts_only_when_acknowledged(connector, monkeypatch):
    client = _live(monkeypatch, _SilentRelay())
    payload = {"vendor": "kasa", "state": "error", "resolved": False}
    assert await service.forward_event("vendor_health_degraded", payload, confirm=True) is False
    # Unconfirmed sends keep their fire-and-forget meaning.
    assert await service.forward_event("vendor_health_degraded", payload) is True
    client.ack = True
    assert await service.forward_event("vendor_health_degraded", payload, confirm=True) is True


_REAL_HEARTBEAT = service._health_heartbeat_loop


async def _one_beat(monkeypatch, client):
    async def _metrics():
        return {"cpu_percent": 1.0}

    async def _emit(event, data=None, namespace=None, callback=None):
        client.emits.append((event, data))
        if event == "device_health":
            service._connected = False   # stop after this beat

    monkeypatch.setattr(service, "get_system_metrics", _metrics)
    monkeypatch.setattr(service, "HEALTH_HEARTBEAT_INTERVAL", 0)
    monkeypatch.setattr(client, "emit", _emit)
    _live(monkeypatch, client)
    await _REAL_HEARTBEAT()


async def test_heartbeat_reports_the_running_server_version(connector, monkeypatch):
    client = _FakeClient()
    await _one_beat(monkeypatch, client)
    beat = next(data for event, data in client.emits if event == "device_health")
    assert beat["version"] == server_version() != "unknown"


async def test_heartbeat_keeps_the_integrations_cache_warm(connector, monkeypatch):
    monkeypatch.setattr(service, "_last_snapshot_push", time.time())
    await _one_beat(monkeypatch, _FakeClient())
    assert connector == [], "pushed again well inside the relay's cache lifetime"

    monkeypatch.setattr(service, "_last_snapshot_push",
                        time.time() - service._INTEGRATIONS_SNAPSHOT_INTERVAL_SECONDS)
    await _one_beat(monkeypatch, _FakeClient())
    assert connector == [1]
