"""A lapsed subscription is a standing condition, not a transient fault.

The cloud now refuses a device whose owner has no active subscription
(`subscription_required` at connect, 402 on REST ingest). The Pi's connect
loop treated every exception identically: exponential backoff capped at
5 minutes, retrying forever. Against a refusal that only
clears when the user resubscribes, that means:

  * a reconnect every 5 minutes, indefinitely, at a relay that has
    reconnect-storm detection — the Pi would look like an attacker;
  * a 10,000-frame telemetry queue filling with data the cloud is refusing on
    principle, churning the drop-oldest ring and inflating the drop counter
    with "data loss" that never happened;
  * a UI stuck on "reconnecting (300s)" with no way to learn why.

Local control never depended on the cloud, and SQLite still holds every
reading — the cloud is a mirror, not the record. So: back off far, say why,
stop buffering, and resume the moment the cloud accepts us again (that last
part: test_cloud_connector_loop.py). A revoked, deleted or rotated device
token ("Invalid device token") is the same kind of refusal, cleared by
re-pairing.

python-socketio reports a refused connect as a generic ConnectionError ("One
or more namespaces failed to connect: /"); the relay's reason arrives only as
the `connect_error` event's payload. The end-to-end tests below drive the real
client against a real Socket.IO server that refuses the way the relay does.
"""

import asyncio
import socket

import pytest
import socketio
import uvicorn

from app.cloud import service


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(service, "_standing_refusal", None)
    monkeypatch.setattr(service, "_connect_error", None)
    monkeypatch.setattr(service, "_connected", False)
    monkeypatch.setattr(service, "_queue_drops", 0)


# ── recognising the refusal ──────────────────────────────────────────────

# What python-socketio 5.x raises for any refused connect.
_REFUSED = ConnectionError("One or more namespaces failed to connect: /")


@pytest.mark.parametrize("payload,reason", [
    ({"message": "subscription_required"}, "subscription_required"),
    ({"message": "Invalid device token"}, "Invalid device token"),
    ("subscription_required", "subscription_required"),
])
def test_recognises_a_standing_refusal_from_connect_error(monkeypatch, payload, reason):
    monkeypatch.setattr(service, "_connect_error", service._connect_error_reason(payload))
    assert service._standing_refusal_of(_REFUSED) == reason


@pytest.mark.parametrize("connect_error", [
    None,               # the exception text alone says nothing
    "Auth required",
    # Too many connects from one address.
    "rate_limited",
    # Any reason this Pi doesn't know (this one the relay gives browsers).
    "auth_unavailable",
])
def test_ordinary_faults_are_not_mistaken_for_a_refusal(monkeypatch, connect_error):
    """A flaky link must keep its fast backoff — do not park a real outage for
    15 minutes."""
    monkeypatch.setattr(service, "_connect_error", connect_error)
    for exc in (
        ConnectionError("Connection refused"),
        TimeoutError("timed out"),
        OSError("Network is unreachable"),
        _REFUSED,
    ):
        assert service._standing_refusal_of(exc) is None, exc


# ── end to end against a real Socket.IO server ───────────────────────────


@pytest.fixture
async def refusing_relay():
    """A Socket.IO server whose connect handler refuses like the relay does
    (cloud/app/relay/service.py): ConnectionRefusedError(<reason>), where
    the reason is set per test."""
    sio = socketio.AsyncServer(async_mode="asgi")
    refusal = {"reason": "subscription_required"}

    @sio.event
    async def connect(sid, environ, auth):
        raise socketio.exceptions.ConnectionRefusedError(refusal["reason"])

    # Bound here and handed to the server, so no other process can take the
    # port between choosing and listening.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        socketio.ASGIApp(sio), host="127.0.0.1", port=port, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(500):
        if server.started or task.done():
            break
        await asyncio.sleep(0.02)
    assert server.started, "the test Socket.IO server did not start"
    refusal["url"] = f"http://127.0.0.1:{port}"
    yield refusal
    server.should_exit = True
    await task


@pytest.fixture
def relay_connector(refusing_relay, monkeypatch):
    """The real connector pointed at the refusing relay with one frame
    buffered; `stop_when(predicate)` ends the loop at the first backoff
    sleep the predicate accepts and returns every sleep it saw."""
    monkeypatch.setattr(service.settings, "cloud_url", refusing_relay["url"])
    monkeypatch.setattr(service.settings, "cloud_token", "tok")
    monkeypatch.setattr(service.settings, "cloud_device_id", "dev-1")
    monkeypatch.setattr(service, "_reconnect_attempts", 0)
    monkeypatch.setattr(service, "_token_refusals", 0)
    monkeypatch.setitem(service._task_status, "cloud_connector",
                        {"status": "idle", "last_run": None})
    service._queue.put_nowait({"node_id": "climate-01", "temp_f": 72.0})

    async def run(reason, stop_when):
        refusing_relay["reason"] = reason
        slept: list[float] = []

        async def _sleep(seconds):
            slept.append(seconds)
            if stop_when(seconds, slept):
                raise asyncio.CancelledError

        monkeypatch.setattr(service, "_backoff_sleep", _sleep)
        with pytest.raises(asyncio.CancelledError):
            await service.start_cloud_connector()
        return slept

    return run


@pytest.mark.parametrize("reason,status,retries_first", [
    ("subscription_required", "paused — subscription required", []),
    # Older relays gave this reason too when they could not check the token,
    # so it stands only once it repeats (normal 10 s and 20 s retries first).
    ("Invalid device token", "unauthorized — re-pair this Pi with the cloud", [10, 20]),
])
async def test_a_real_refusal_pauses_cloud_sync(relay_connector, reason, status, retries_first):
    slept = await relay_connector(reason, lambda seconds, slept: (
        seconds == service._STANDING_REFUSAL_RETRY_SECONDS or len(slept) > 5))

    assert service._standing_refusal == reason
    assert service._task_status["cloud_connector"]["status"] == status
    assert slept == [*retries_first, service._STANDING_REFUSAL_RETRY_SECONDS]
    assert service._queue.empty(), "kept frames the cloud refuses on principle"


async def test_a_refusal_that_can_clear_keeps_buffering_on_the_normal_backoff(relay_connector):
    """Only a lapsed subscription and a wrong token stand. Taken for one, a
    cloud database outage (the relay could not check the device token or
    read its owner's subscription: service_unavailable) would pause cloud
    sync for 15 minutes after it ended and drop every frame buffered
    through it."""
    slept = await relay_connector("service_unavailable", lambda seconds, slept: len(slept) >= 3)

    assert service._standing_refusal is None
    assert slept == [10, 20, 40]
    assert service._queue.qsize() == 1, "dropped frames buffered through a transient refusal"
    assert service._task_status["cloud_connector"]["status"] == "reconnecting (40s)"


# ── behaviour while refused ──────────────────────────────────────────────


@pytest.mark.parametrize("reason", list(service._STANDING_REFUSALS))
async def test_refused_telemetry_is_not_queued(monkeypatch, reason):
    """Buffering exists to survive a flaky link, not a standing refusal."""
    monkeypatch.setattr(service.settings, "cloud_url", "https://sporeprint.ai")
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_standing_refusal", reason)

    await service.forward_telemetry("climate-01", {"temp_f": 72.0})

    assert service._queue.empty(), "queued a frame the cloud is refusing to accept"


def test_the_undeliverable_queue_is_discarded_without_counting_drops():
    """These frames are not lost — they are in the Pi's database. Counting them
    as drops would make the health page report data loss that never happened."""
    for i in range(5):
        service._queue.put_nowait({"node_id": f"n{i}"})

    service._drop_undeliverable_queue()

    assert service._queue.empty()
    assert service._queue_drops == 0


# ── the storm the old code would have caused ─────────────────────────────


def test_the_refusal_backoff_is_far_longer_than_the_fault_backoff():
    """The old loop retried a refusal every 5 minutes forever. The relay has
    reconnect-storm detection — the Pi would have looked like an attacker."""
    worst_fault_backoff = service._backoff_seconds(1000)  # the loop's own cap
    assert service._STANDING_REFUSAL_RETRY_SECONDS > worst_fault_backoff

    # …but still short enough that resubscribing feels immediate, not "tomorrow".
    assert service._STANDING_REFUSAL_RETRY_SECONDS <= 3600
