"""A lapsed subscription is a standing condition, not a transient fault.

The cloud now refuses a device whose owner has no active subscription
(`subscription_required` at connect, 402 on REST ingest — sporeprint-cloud
PR #48). The Pi's connect loop treated every exception identically: exponential
backoff capped at 5 minutes, retrying forever. Against a refusal that only
clears when the user resubscribes, that means:

  * a reconnect every 5 minutes, indefinitely, at a relay that has
    reconnect-storm detection — the Pi would look like an attacker;
  * a 10,000-frame telemetry queue filling with data the cloud is refusing on
    principle, churning the drop-oldest ring and inflating the drop counter
    with "data loss" that never happened;
  * a UI stuck on "reconnecting (300s)" with no way to learn why.

Local control never depended on the cloud, and SQLite still holds every
reading — the cloud is a mirror, not the record. So: back off far, say why,
stop buffering, and resume the moment the cloud accepts us again.
"""

import asyncio

import pytest

from app.cloud import service


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(service, "_subscription_blocked", False)
    monkeypatch.setattr(service, "_connected", False)
    monkeypatch.setattr(service, "_queue_drops", 0)
    while not service._queue.empty():
        service._queue.get_nowait()
    yield


# ── recognising the refusal ──────────────────────────────────────────────


def test_recognises_the_subscription_refusal():
    """python-socketio flattens a server ConnectionRefusedError into a generic
    ConnectionError, so the reason survives only as text."""
    assert service._is_subscription_refusal(
        ConnectionError("Connection rejected by server: {'error': 'subscription_required'}")
    )


def test_ordinary_faults_are_not_mistaken_for_a_refusal():
    """A flaky link must keep its fast backoff — do not park a real outage for
    15 minutes."""
    for exc in (
        ConnectionError("Connection refused"),
        TimeoutError("timed out"),
        OSError("Network is unreachable"),
        ConnectionError("Connection rejected by server: {'error': 'invalid_token'}"),
    ):
        assert not service._is_subscription_refusal(exc), exc


# ── behaviour while blocked ──────────────────────────────────────────────


async def test_blocked_telemetry_is_not_queued(monkeypatch):
    """Buffering exists to survive a flaky link, not a lapsed subscription."""
    monkeypatch.setattr(service.settings, "cloud_url", "https://sporeprint.ai")
    monkeypatch.setattr(service, "_subscription_blocked", True)

    await service.forward_telemetry("climate-01", {"temp_f": 72.0})

    assert service._queue.empty(), "queued a frame the cloud is refusing to accept"


async def test_telemetry_is_queued_normally_when_not_blocked(monkeypatch):
    """The offline buffer must still work for its actual purpose."""
    monkeypatch.setattr(service.settings, "cloud_url", "https://sporeprint.ai")
    monkeypatch.setattr(service, "_subscription_blocked", False)
    monkeypatch.setattr(service, "_connected", False)

    await service.forward_telemetry("climate-01", {"temp_f": 72.0})

    assert service._queue.qsize() == 1


def test_the_undeliverable_queue_is_discarded_not_hoarded():
    for i in range(5):
        service._queue.put_nowait({"node_id": f"n{i}"})

    service._drop_undeliverable_queue()

    assert service._queue.empty()


def test_discarding_does_not_inflate_the_drop_counter():
    """These frames are not lost — they are in the Pi's database. Counting them
    as drops would make the health page report data loss that never happened."""
    before = service._queue_drops
    service._queue.put_nowait({"node_id": "climate-01"})

    service._drop_undeliverable_queue()

    assert service._queue_drops == before


# ── the storm the old code would have caused ─────────────────────────────


def test_the_refusal_backoff_is_far_longer_than_the_fault_backoff():
    """The old loop retried a refusal every 5 minutes forever. The relay has
    reconnect-storm detection — the Pi would have looked like an attacker."""
    worst_fault_backoff = min(300, 5 * (2 ** 6))  # the loop's own cap
    assert service._SUBSCRIPTION_RETRY_SECONDS > worst_fault_backoff

    # …but still short enough that resubscribing feels immediate, not "tomorrow".
    assert service._SUBSCRIPTION_RETRY_SECONDS <= 3600
