"""Cloud connector loop behaviour, driven with a fake Socket.IO client.

* #9  a relay that accepts then immediately drops the session must meet a
      growing backoff, not a ~1 s reconnect storm; a stable session resets it.
* #20 POST /reconnect must actually wake the retry sleep.
* #8  the integrations snapshot is (re)pushed on every connect.
* #11 the device token is never sent over plaintext to a public host.
* #5  credentials persisted by pairing are loaded at connector start.
* buffered frames go out as replayed history; frames the relay never
  acknowledged are kept for the next connect; the connector does not start
  (or buffer) without all three credentials.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app.cloud.service as service
from app.cloud.version import server_version
from app.integrations import _health_sweeper


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
        self.connected = False


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
    ]:
        monkeypatch.setattr(service, name, value)
    service._inflight.clear()
    _empty_queue()
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


async def test_immediate_server_disconnect_backs_off(connector, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(4, sleeps))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    assert sleeps == [10, 20, 40, 80], (
        "a session the relay drops immediately must grow the backoff, "
        "not reconnect ~1 s later forever"
    )
    assert _FakeClient.instances[0].connect_calls == 4


async def test_stable_session_resets_backoff(connector, monkeypatch):
    monkeypatch.setattr(service, "_STABLE_SESSION_SECONDS", 0)
    sleeps: list[float] = []
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(3, sleeps))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    assert sleeps == [5, 5, 5]


async def test_snapshot_pushed_on_every_connect(connector, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(2, sleeps))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    assert len(connector) == 2


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
])
def test_cloud_url_transport_policy(url, ok):
    assert service.cloud_url_transport_ok(url) is ok


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


def test_request_reconnect_states(monkeypatch):
    monkeypatch.setattr(service, "_connector_running", False)
    assert service.request_reconnect() == "restart_required"
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_connected", True)
    assert service.request_reconnect() == "connected"


async def test_connector_loads_paired_credentials(connector, monkeypatch):
    monkeypatch.setattr(service.settings, "cloud_url", "")
    monkeypatch.setattr(service.settings, "cloud_token", "")
    service.write_cloud_env({
        "SPOREPRINT_CLOUD_URL": "https://relay.example.com",
        "SPOREPRINT_CLOUD_TOKEN": "paired-token",
        "SPOREPRINT_CLOUD_DEVICE_ID": "dev-9",
    })
    sleeps: list[float] = []
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(1, sleeps))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
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


async def test_apply_paired_credentials_without_a_connector_needs_a_restart(connector, monkeypatch):
    service.write_cloud_env({"SPOREPRINT_CLOUD_TOKEN": "fresh"})
    assert await service.apply_paired_credentials() is False
    assert service.settings.cloud_token == "fresh"


async def test_connect_waits_long_enough_for_the_relay(connector, monkeypatch):
    """The relay answers only after two Supabase round trips; the client's
    1 s default failed every slow handshake."""
    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(1, []))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    assert _FakeClient.instances[0].wait_timeout >= 5


@pytest.mark.parametrize("missing", ["cloud_device_id", "cloud_token"])
async def test_connector_needs_all_three_credentials(connector, monkeypatch, missing):
    monkeypatch.setattr(service.settings, missing, "")
    await service.start_cloud_connector()
    assert _FakeClient.instances == [], "a partial pairing can only be refused"
    status = service._task_status["cloud_connector"]["status"]
    var = {"cloud_device_id": "SPOREPRINT_CLOUD_DEVICE_ID",
           "cloud_token": "SPOREPRINT_CLOUD_TOKEN"}[missing]
    assert status == f"disabled — {var} not set"
    # Nothing would ever drain a queue, so nothing is buffered.
    await service.forward_telemetry("climate-01", {"temp_f": 72.0})
    assert service._queue.empty()


async def test_buffered_frames_drain_as_replayed_history(connector, monkeypatch):
    """Frames buffered while the link was down are history: the relay stores
    them at their own ts and never shows them as the current reading."""
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 91.0, "ts": 1_760_000_000.0})
    assert service._queue.qsize() == 1

    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(1, []))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    sent = [data for event, data in _FakeClient.instances[0].emits if event == "telemetry"]
    assert sent == [{"node_id": "climate-01", "ts": 1_760_000_000.0, "temp_f": 91.0,
                     "replay": True}]
    assert service._queue.empty()


class _SilentRelay(_FakeClient):
    """A relay whose socket died without a FIN: emits succeed, nothing acks."""

    def __init__(self, reconnection: bool = False) -> None:
        super().__init__(reconnection)
        self.ack = False


async def test_unacknowledged_frames_are_kept_for_the_next_connect(connector, monkeypatch):
    monkeypatch.setattr(service.socketio, "AsyncClient", _SilentRelay)
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_last_forward", 0)
    await service.forward_telemetry("climate-01", {"temp_f": 70.0, "ts": 1_760_000_000.0})

    monkeypatch.setattr(service, "_backoff_sleep", _stop_after(1, []))
    with pytest.raises(asyncio.CancelledError):
        await service.start_cloud_connector()
    # Sent once into the dead socket, never acknowledged: back in the queue
    # when the disconnect is noticed, and not counted as forwarded.
    assert [e for e, _ in _FakeClient.instances[0].emits].count("telemetry") == 1
    assert service._queue.qsize() == 1
    assert service._queue.get_nowait()["temp_f"] == 70.0
    assert service._last_forward == 0
    assert not service._inflight


async def test_an_acknowledged_frame_is_not_resent(connector, monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 70.0})
    assert not service._inflight
    assert service._requeue_unacked() == 0
    assert service._queue.empty()
    assert service._last_forward > 0


async def test_unacknowledged_frames_past_the_max_age_are_not_resent(connector, monkeypatch):
    client = _SilentRelay()
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
    monkeypatch.setattr(service, "_connector_running", True)
    await service.forward_telemetry("climate-01", {"temp_f": 70.0})
    assert len(service._inflight) == 1
    real_time = time.time
    monkeypatch.setattr(service.time, "time",
                        lambda: real_time() + service._INFLIGHT_MAX_AGE_SECONDS + 1)
    assert service._requeue_unacked() == 0
    assert service._queue.empty()


# ── events ───────────────────────────────────────────────────────────


async def test_integrations_snapshot_rides_its_own_channel(connector, monkeypatch):
    """The relay fills its integrations cache from the dedicated
    `integrations_state` event; the generic `event` copy stays for clouds
    that read it there."""
    client = _FakeClient()
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
    assert await service.forward_event("integrations_state", {"drivers": [{"slug": "kasa"}]})
    events = {event: data for event, data in client.emits}
    assert events["integrations_state"]["drivers"] == [{"slug": "kasa"}]
    assert events["event"]["type"] == "integrations_state"


async def test_a_confirmed_event_counts_only_when_acknowledged(connector, monkeypatch):
    client = _SilentRelay()
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
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
    monkeypatch.setattr(service, "_sio", client)
    monkeypatch.setattr(service, "_connected", True)
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
