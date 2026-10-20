"""GET /api/cloud/status says when pairing saved credentials that only a
server restart will connect with.

A Pi that was unpaired when its server started runs no cloud connector, so
after the cloud's /configure it held its new credentials but stayed
disconnected: the dashboard's setup wizard waited for a connection that never
came and then called the (consumed) pairing code expired.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.cloud.router as cloud_router_mod
import app.cloud.service as service
from app.config import settings


@pytest.fixture
def cloud_client(monkeypatch):
    monkeypatch.setattr(cloud_router_mod, "_pairing_code", None)
    monkeypatch.setattr(cloud_router_mod, "_pairing_attempts", 0)
    monkeypatch.setattr(cloud_router_mod, "_pairing_lockout_until", 0.0)
    monkeypatch.setattr(cloud_router_mod, "_configure_tokens", {})
    for attr in ("cloud_url", "cloud_token", "cloud_device_id"):
        monkeypatch.setattr(settings, attr, "")
    monkeypatch.setattr(service, "_connected", False)
    app = FastAPI()
    app.include_router(cloud_router_mod.router, prefix="/api/cloud")
    return TestClient(app)


def _pair(client: TestClient) -> None:
    code = client.post("/api/cloud/pairing-code").json()["code"]
    paired = client.post("/api/cloud/pair", json={"code": code}).json()
    r = client.post("/api/cloud/configure", json={
        "configure_token": paired["configure_token"],
        "cloud_device_id": paired["device"]["cloud_device_id"],
        "device_token": "tok-1",
        "cloud_url": "https://relay.sporeprint.ai",
    })
    assert r.status_code == 200, r.text


def test_an_unpaired_pi_reports_no_restart_due(cloud_client, monkeypatch):
    monkeypatch.setattr(service, "_connector_running", False)
    status = cloud_client.get("/api/cloud/status").json()
    assert status["configured"] is False
    assert status["restart_required"] is False


def test_pairing_a_pi_that_booted_unpaired_asks_for_a_restart(cloud_client, monkeypatch):
    monkeypatch.setattr(service, "_connector_running", False)
    _pair(cloud_client)
    status = cloud_client.get("/api/cloud/status").json()
    assert status["configured"] is True
    assert status["connected"] is False
    assert status["restart_required"] is True


def test_a_running_connector_needs_no_restart(cloud_client, monkeypatch):
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_wake_event", None)
    monkeypatch.setattr(service, "_sio", None)
    _pair(cloud_client)
    status = cloud_client.get("/api/cloud/status").json()
    assert status["configured"] is True
    assert status["restart_required"] is False
