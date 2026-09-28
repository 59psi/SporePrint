"""Vendor-health transitions must survive a cloud outage.

`forward_event` drops events while the cloud socket is down (it never
queued, despite the docstrings). The sweeper used to record the new state
regardless, so an ok→error transition that happened while offline was lost
for good — no push, no escalation. It must now retry until delivered, and
error→disabled must resolve the open escalation.
"""

from __future__ import annotations

import pytest

import app.cloud.service as cloud_service
from app.integrations import _health_sweeper as sweeper
from app.integrations._base import IntegrationHealth


class _Drv:
    def __init__(self, state: str) -> None:
        self.state = state

    async def health(self) -> IntegrationHealth:
        return IntegrationHealth(state=self.state)  # type: ignore[arg-type]


@pytest.fixture
def one_driver(monkeypatch):
    drv = _Drv("ok")
    monkeypatch.setattr(sweeper._registry, "registered_drivers", lambda: {"aranet": drv})
    sweeper._last_state.clear()
    yield drv
    sweeper._last_state.clear()


@pytest.fixture
def cloud(monkeypatch):
    """Controllable forward_event: `up` decides delivery; `sent` records."""
    class _Cloud:
        up = False
        sent: list[tuple[str, dict]] = []

    c = _Cloud()
    c.sent = []

    async def fake_forward(event_type, data):
        if not c.up:
            return False
        c.sent.append((event_type, data))
        return True

    monkeypatch.setattr(cloud_service, "forward_event", fake_forward)
    return c


async def test_forward_event_reports_undelivered_when_disconnected(monkeypatch):
    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.example")
    monkeypatch.setattr(cloud_service, "_connected", False)
    assert await cloud_service.forward_event("x", {}) is False


async def test_forward_event_reports_delivered(monkeypatch):
    class _Sio:
        def __init__(self):
            self.emits = []

        async def emit(self, ev, data):
            self.emits.append((ev, data))

    sio = _Sio()
    monkeypatch.setattr(cloud_service.settings, "cloud_url", "https://relay.example")
    monkeypatch.setattr(cloud_service, "_connected", True)
    monkeypatch.setattr(cloud_service, "_sio", sio)
    assert await cloud_service.forward_event("vendor_health_degraded", {"a": 1}) is True
    assert sio.emits and sio.emits[0][0] == "event"


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
