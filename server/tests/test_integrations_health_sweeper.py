"""Vendor-health transitions must survive a cloud outage.

`forward_event` drops events while the cloud socket is down (it never
queued, despite the docstrings). The sweeper used to record the new state
regardless, so an ok→error transition that happened while offline was lost
for good — no push, no escalation. It must now retry until delivered, and
error→disabled must resolve the open escalation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.cloud.service as cloud_service
from app.integrations import _health_sweeper as sweeper
from app.integrations._base import IntegrationHealth
from tests._fakes import RecordingSio


class _Drv:
    def __init__(self, state: str) -> None:
        self.state = state
        self.error: str | None = None

    async def health(self) -> IntegrationHealth:
        return IntegrationHealth(state=self.state, last_error=self.error)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _fresh_sweeper_state(monkeypatch):
    monkeypatch.setattr(sweeper, "_last_state", {})
    monkeypatch.setattr(sweeper, "_ok_streak", {})


@pytest.fixture
def one_driver(monkeypatch):
    drv = _Drv("ok")
    monkeypatch.setattr(sweeper._registry, "registered_drivers", lambda: {"aranet": drv})
    return drv


@pytest.fixture
def cloud(monkeypatch):
    """Controllable forward_event: `up` decides delivery; `sent` records."""
    class _Cloud:
        up = False
        sent: list[tuple[str, dict]] = []

    c = _Cloud()
    c.sent = []
    c.confirmed: list[bool] = []

    async def fake_forward(event_type, data, *, confirm=False):
        if not c.up:
            return False
        c.sent.append((event_type, data))
        c.confirmed.append(confirm)
        return True

    monkeypatch.setattr(cloud_service, "forward_event", fake_forward)
    return c


async def test_forward_event_reports_undelivered_when_disconnected(monkeypatch):
    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.example")
    monkeypatch.setattr(cloud_service, "_connected", False)
    assert await cloud_service.forward_event("x", {}) is False


async def test_forward_event_reports_delivered(monkeypatch):
    sio = RecordingSio()
    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.example")
    monkeypatch.setattr(cloud_service, "_connected", True)
    monkeypatch.setattr(cloud_service, "_sio", sio)
    assert await cloud_service.forward_event("vendor_health_degraded", {"a": 1}) is True
    assert sio.events and sio.events[0][0] == "event"


async def test_transition_while_offline_is_delivered_after_reconnect(one_driver, cloud):
    await sweeper._sweep_once()          # baseline: ok
    one_driver.state = "error"
    await sweeper._sweep_once()          # cloud down → not delivered
    assert cloud.sent == []
    assert sweeper._last_state["aranet"] == "ok", "undelivered transition must be retried"

    cloud.up = True
    await sweeper._sweep_once()          # cloud back → delivered now
    assert [e for e, _ in cloud.sent] == ["vendor_health_degraded"]
    assert cloud.sent[0][1]["state"] == "error"
    assert sweeper._last_state["aranet"] == "error"

    await sweeper._sweep_once()          # no duplicate
    assert len(cloud.sent) == 1
    # Delivered means acknowledged by the relay: an event sent into a link
    # that died without closing must not count as sent.
    assert cloud.confirmed == [True]


async def test_error_to_disabled_resolves_escalation(one_driver, cloud):
    cloud.up = True
    one_driver.state = "error"
    await sweeper._sweep_once()
    one_driver.state = "disabled"
    await sweeper._sweep_once()
    assert cloud.sent[-1][0] == "vendor_health_degraded"
    assert cloud.sent[-1][1]["resolved"] is True
    assert sweeper._last_state["aranet"] == "disabled"


async def test_ok_to_disabled_needs_no_event(one_driver, cloud):
    await sweeper._sweep_once()
    one_driver.state = "disabled"
    await sweeper._sweep_once()      # cloud down, but nothing to deliver
    assert cloud.sent == []
    assert sweeper._last_state["aranet"] == "disabled"


async def test_disabled_to_ok_needs_no_event(one_driver, cloud):
    # Every boot: the first sweep runs before the drivers are started, so it
    # sees "disabled"; the next sees "ok". That used to send a "resolved"
    # event the cloud pushed as "integration degraded" — on every reboot and
    # every enable.
    cloud.up = True
    one_driver.state = "disabled"
    await sweeper._sweep_once()
    one_driver.state = "ok"
    await sweeper._sweep_once()
    assert cloud.sent == []
    assert sweeper._last_state["aranet"] == "ok"


async def test_degraded_event_carries_the_drivers_error_as_reason(one_driver, cloud):
    cloud.up = True
    await sweeper._sweep_once()
    one_driver.state, one_driver.error = "error", "Quest: connect timeout"
    await sweeper._sweep_once()
    assert cloud.sent == [("vendor_health_degraded", {
        "vendor": "aranet", "state": "error", "reason": "Quest: connect timeout", "resolved": False,
    })]


async def test_a_flapping_driver_is_one_incident(one_driver, cloud):
    cloud.up = True
    await sweeper._sweep_once()                      # baseline ok
    for state in ("error", "ok", "error", "ok", "error"):
        one_driver.state = state
        await sweeper._sweep_once()
    # One page, not one per flap; the incident is still open.
    assert [d["resolved"] for _e, d in cloud.sent] == [False]

    one_driver.state = "ok"
    for _ in range(sweeper._RECOVERED_AFTER_SWEEPS - 1):
        await sweeper._sweep_once()
    assert len(cloud.sent) == 1, "a recovery must hold before it resolves"
    await sweeper._sweep_once()
    assert [d["resolved"] for _e, d in cloud.sent] == [False, True]
    assert sweeper._last_state["aranet"] == "ok"


async def test_a_driver_whose_health_raises_does_not_hide_the_others(monkeypatch, cloud):
    class _Broken:
        async def health(self):
            raise RuntimeError("bug in one driver")

    quest = _Drv("ok")
    monkeypatch.setattr(sweeper._registry, "registered_drivers",
                        lambda: {"broken": _Broken(), "quest": quest})
    cloud.up = True
    await sweeper._sweep_once()
    quest.state = "error"
    await sweeper._sweep_once()
    assert [(d["vendor"], d["state"]) for _e, d in cloud.sent] == [("quest", "error")]
    assert "broken" not in sweeper._last_state


async def test_the_loop_sweeps_every_interval_and_outlives_a_crashing_sweep(monkeypatch):
    """A sweep that raises is logged and the next one runs an interval later;
    a cancellation (the app shutting down) ends the loop cleanly."""
    sweeps: list[int] = []
    pauses: list[float] = []

    async def _sweep():
        sweeps.append(len(sweeps))
        if len(sweeps) == 1:
            raise RuntimeError("a driver's health() blew up")
        if len(sweeps) == 3:
            raise asyncio.CancelledError

    async def _pause(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(sweeper, "_sweep_once", _sweep)
    monkeypatch.setattr(sweeper, "asyncio",
                        SimpleNamespace(sleep=_pause, CancelledError=asyncio.CancelledError))
    await asyncio.wait_for(sweeper.run_health_sweeper(), timeout=2)
    assert len(sweeps) == 3
    assert pauses == [sweeper._SWEEP_INTERVAL_SECONDS] * 2
