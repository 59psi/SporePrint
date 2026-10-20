"""Cloud pairing flow: /pairing-code → /pair → /configure.

* /configure persisted to `<server>/.env`, which
  is root-owned and ephemeral in the Docker image (500 on every pairing) and
  shadowed by compose's empty SPOREPRINT_CLOUD_* vars. Credentials now go to
  `cloud.env` beside the database (the persistent data volume), 0600.
* #11 — a plaintext http:// cloud_url to a public host is refused (the
  device token doubles as the command-signing key).
* #20 — /pair reports the real server version; /reconnect is honest.
"""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.cloud.router as cloud_router_mod
import app.cloud.service as service
from app.cloud.version import server_version
from app.config import settings


@pytest.fixture
def pair_client(monkeypatch):
    monkeypatch.setattr(cloud_router_mod, "_pairing_code", None)
    monkeypatch.setattr(cloud_router_mod, "_pairing_attempts", 0)
    monkeypatch.setattr(cloud_router_mod, "_pairing_lockout_until", 0.0)
    monkeypatch.setattr(cloud_router_mod, "_configure_tokens", {})
    # Values the overlay may write must be restored after each test.
    for attr in ("cloud_url", "cloud_token", "cloud_device_id"):
        monkeypatch.setattr(settings, attr, getattr(settings, attr))
    # A Pi already paired as dev-42: /pair hands out that id, and /configure
    # accepts only the id its pairing session was opened for.
    monkeypatch.setattr(settings, "cloud_device_id", "dev-42")
    app = FastAPI()
    app.include_router(cloud_router_mod.router, prefix="/api/cloud")
    return TestClient(app)


def _configure_token(client: TestClient) -> tuple[str, dict]:
    code = client.post("/api/cloud/pairing-code").json()["code"]
    r = client.post("/api/cloud/pair", json={"code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["configure_token"], body


def test_configure_persists_to_data_volume(pair_client):
    token, _ = _configure_token(pair_client)
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token,
        "cloud_device_id": "dev-42",
        "device_token": "tok-42",
        "cloud_url": "https://relay.sporeprint.ai",
    })
    assert r.status_code == 200, r.text

    path = service.env_path()
    assert path.parent == Path(settings.database_path).resolve().parent
    text = path.read_text()
    assert "SPOREPRINT_CLOUD_TOKEN=tok-42" in text
    assert "SPOREPRINT_CLOUD_DEVICE_ID=dev-42" in text
    assert "SPOREPRINT_CLOUD_URL=https://relay.sporeprint.ai" in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_persisted_credentials_override_empty_env(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "")    # compose's empty passthrough
    monkeypatch.setattr(settings, "cloud_token", "")
    service.write_cloud_env({
        "SPOREPRINT_CLOUD_URL": "https://relay.sporeprint.ai",
        "SPOREPRINT_CLOUD_TOKEN": "tok-9",
        "SPOREPRINT_CLOUD_DEVICE_ID": "dev-9",
    })
    assert service.load_persisted_cloud_credentials() is True
    assert settings.cloud_url == "https://relay.sporeprint.ai"
    assert settings.cloud_token == "tok-9"
    assert settings.cloud_device_id == "dev-9"


def test_no_persisted_file_leaves_env_untouched(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://from-env.example")
    assert service.load_persisted_cloud_credentials() is False
    assert settings.cloud_url == "https://from-env.example"


def test_configure_rejects_public_plaintext_cloud_url(pair_client):
    token, _ = _configure_token(pair_client)
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token,
        "cloud_device_id": "dev-42",
        "device_token": "tok-42",
        "cloud_url": "http://relay.sporeprint.ai",
    })
    assert r.status_code == 400
    assert "https" in r.json()["detail"]
    assert not service.env_path().exists()


def test_configure_allows_lan_dev_relay(pair_client):
    token, _ = _configure_token(pair_client)
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token,
        "cloud_device_id": "dev-42",
        "device_token": "tok-42",
        "cloud_url": "http://192.168.1.20:8001",
    })
    assert r.status_code == 200, r.text


def test_pair_reports_real_server_version(pair_client):
    _, body = _configure_token(pair_client)
    assert body["device"]["firmware_version"] == server_version()
    assert body["device"]["firmware_version"] != "0.3.0"
    assert server_version() != "unknown"


def test_reconnect_reports_restart_required_when_connector_not_running(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://relay.sporeprint.ai")
    monkeypatch.setattr(service, "_connector_running", False)
    r = pair_client.post("/api/cloud/reconnect")
    assert r.status_code == 200
    assert r.json()["status"] == "restart_required"


def test_reconnect_wakes_running_connector(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://relay.sporeprint.ai")
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_connected", False)
    event = asyncio.Event()
    monkeypatch.setattr(service, "_wake_event", event)
    r = pair_client.post("/api/cloud/reconnect")
    assert r.json()["status"] == "reconnecting"
    assert event.is_set()


def test_reconnect_retries_with_the_saved_credentials(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://relay.sporeprint.ai")
    monkeypatch.setattr(settings, "cloud_token", "boot-token")
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_connected", False)
    monkeypatch.setattr(service, "_wake_event", asyncio.Event())
    service.write_cloud_env({"SPOREPRINT_CLOUD_TOKEN": "paired-later"})
    assert pair_client.post("/api/cloud/reconnect").json()["status"] == "reconnecting"
    assert settings.cloud_token == "paired-later"


class _LiveSocket:
    def __init__(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


def test_configure_applies_new_credentials_to_a_running_connector(pair_client, monkeypatch):
    """A token rotation reaches a connected Pi: the session that used the old
    token is closed and the retry wakes with the new one (it used to retry
    the dead token until someone restarted the Pi)."""
    monkeypatch.setattr(settings, "cloud_token", "old-token")
    monkeypatch.setattr(service, "_connector_running", True)
    socket = _LiveSocket()
    monkeypatch.setattr(service, "_sio", socket)
    event = asyncio.Event()
    monkeypatch.setattr(service, "_wake_event", event)
    token, _ = _configure_token(pair_client)
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token,
        "cloud_device_id": "dev-42",
        "device_token": "rotated-token",
        "cloud_url": "https://relay.sporeprint.ai",
    })
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    assert settings.cloud_token == "rotated-token"
    assert settings.cloud_device_id == "dev-42"
    assert socket.connected is False
    assert event.is_set()


def test_configure_without_a_running_connector_asks_for_a_restart(pair_client, monkeypatch):
    monkeypatch.setattr(service, "_connector_running", False)
    token, _ = _configure_token(pair_client)
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token,
        "cloud_device_id": "dev-42",
        "device_token": "tok-42",
    })
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is False
    assert "Restart" in r.json()["message"]


def test_pair_verify_reports_the_server_version(pair_client):
    token, _ = _configure_token(pair_client)
    r = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == server_version()


def test_an_unpaired_pi_binds_the_session_to_the_id_it_handed_out(pair_client, monkeypatch):
    """A Pi with no device id hands out a fresh one with the configure token;
    pair-verify reports it (so the cloud pairs that id) and /configure takes
    no other."""
    monkeypatch.setattr(settings, "cloud_device_id", "")
    monkeypatch.setattr(service, "_connector_running", False)
    token, body = _configure_token(pair_client)
    issued = body["device"]["cloud_device_id"]
    assert issued

    verify = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.json()["cloud_device_id"] == issued

    other = pair_client.post("/api/cloud/configure", json={
        "configure_token": token, "cloud_device_id": "someone-elses-id", "device_token": "tok",
    })
    assert other.status_code == 400
    assert not service.env_path().exists()

    ok = pair_client.post("/api/cloud/configure", json={
        "configure_token": token, "cloud_device_id": issued, "device_token": "tok",
    })
    assert ok.status_code == 200, ok.text
    assert f"SPOREPRINT_CLOUD_DEVICE_ID={issued}" in service.env_path().read_text()


def test_a_paired_pi_keeps_its_id(pair_client):
    token, body = _configure_token(pair_client)
    assert body["device"]["cloud_device_id"] == "dev-42"
    verify = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.json()["cloud_device_id"] == "dev-42"
    r = pair_client.post("/api/cloud/configure", json={
        "configure_token": token, "cloud_device_id": "dev-7", "device_token": "tok",
    })
    assert r.status_code == 400
