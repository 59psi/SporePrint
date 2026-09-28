"""Cloud connector loop behaviour, driven with a fake Socket.IO client.

* #9  a relay that accepts then immediately drops the session must meet a
      growing backoff, not a ~1 s reconnect storm; a stable session resets it.
* #20 POST /reconnect must actually wake the retry sleep.
* #8  the integrations snapshot is (re)pushed on every connect.
* #11 the device token is never sent over plaintext to a public host.
* #5  credentials persisted by pairing are loaded at connector start.
"""

from __future__ import annotations

import asyncio

import pytest

import app.cloud.service as service
from app.integrations import _health_sweeper


class _FakeClient:
    """Minimal python-socketio AsyncClient stand-in.

    connect() succeeds and fires the registered `connect` handler; wait()
    returns immediately, i.e. the server ends the session straight away.
    """

    instances: list["_FakeClient"] = []

    def __init__(self, reconnection: bool = False) -> None:
        self.handlers: dict = {}
        self.connected = False
        self.connect_calls = 0
        self.auth_seen = None
        _FakeClient.instances.append(self)

    def on(self, event, handler=None):
        def deco(fn):
            self.handlers[event] = fn
            return fn
        return deco if handler is None else deco(handler)

    async def connect(self, url, auth=None, transports=None):
        self.connect_calls += 1
        self.auth_seen = auth
        self.connected = True
        if "connect" in self.handlers:
            await self.handlers["connect"]()

    async def wait(self):
        self.connected = False
        if "disconnect" in self.handlers:
            await self.handlers["disconnect"]()

    async def emit(self, *a, **k):
        pass

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
        ("_connector_running", False), ("_subscription_blocked", False),
    ]:
        monkeypatch.setattr(service, name, value)
    monkeypatch.setattr(service, "_health_heartbeat_loop", _noop_loop)
    monkeypatch.setitem(service._task_status, "cloud_connector",
                        {"status": "idle", "last_run": None})
    snapshots: list[int] = []

    async def fake_snapshot():
        snapshots.append(1)

    monkeypatch.setattr(_health_sweeper, "push_state_snapshot", fake_snapshot)
    return snapshots


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
