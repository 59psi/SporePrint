"""Cloud pairing flow: /pairing-code → /pair → /pair-verify → /configure, and
the /status and /reconnect routes that report on the result.

* The pairing code is single-use, expires, and eight wrong guesses lock
  pairing until the operator makes a new code.
* /configure needs the short-lived, single-use configure token /pair issued,
  for the device id /pair handed out with it.
* Credentials go to `cloud.env` beside the database (the persistent data
  volume), 0600, written atomically; /configure used to write `<server>/.env`,
  root-owned and ephemeral in the Docker image (500 on every pairing) and
  shadowed by compose's empty SPOREPRINT_CLOUD_* vars. A value that would
  smuggle in another line is refused.
* A plaintext http:// cloud_url to a public host is refused (the device token
  doubles as the command-signing key).
* /pair and /pair-verify report the real server version; /status says when
  only a restart will connect; /reconnect is honest about what it did.
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
from app.cloud import integrations_proxy
from app.cloud.version import server_version
from app.config import settings

RELAY = "https://relay.sporeprint.ai"


class _Clock:
    """Stands in for the router's `time` module; each read advances it by
    `step` seconds."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.step = 0.0

    def time(self) -> float:
        now = self.now
        self.now += self.step
        return now


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock(1_800_000_000.0)
    monkeypatch.setattr(cloud_router_mod, "time", clock)
    return clock


@pytest.fixture
def pair_client(monkeypatch):
    monkeypatch.setattr(cloud_router_mod, "_pairing_code", None)
    monkeypatch.setattr(cloud_router_mod, "_pairing_attempts", 0)
    monkeypatch.setattr(cloud_router_mod, "_pairing_lockout_until", 0.0)
    monkeypatch.setattr(cloud_router_mod, "_configure_tokens", {})
    monkeypatch.setattr(settings, "cloud_url", "")
    monkeypatch.setattr(settings, "cloud_token", "")
    # A Pi already paired as dev-42: /pair hands out that id, and /configure
    # accepts only the id its pairing session was opened for.
    monkeypatch.setattr(settings, "cloud_device_id", "dev-42")
    for name, value in (("_connector_running", False), ("_connected", False),
                        ("_sio", None), ("_wake_event", None)):
        monkeypatch.setattr(service, name, value)
    app = FastAPI()
    app.include_router(cloud_router_mod.router, prefix="/api/cloud")
    return TestClient(app)


def _new_code(client: TestClient) -> str:
    return client.post("/api/cloud/pairing-code").json()["code"]


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def _pair(client: TestClient) -> tuple[str, dict]:
    r = client.post("/api/cloud/pair", json={"code": _new_code(client)})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["configure_token"], body


def _configure(client: TestClient, token: str, **fields):
    body = {"configure_token": token, "cloud_device_id": "dev-42",
            "device_token": "tok-42", "cloud_url": RELAY, **fields}
    return client.post("/api/cloud/configure", json={k: v for k, v in body.items() if v is not None})


# ── the pairing code ─────────────────────────────────────────────────────


def test_the_settings_page_sees_the_live_code_until_it_expires(pair_client, clock):
    assert pair_client.get("/api/cloud/pairing-code").json() == {"code": None, "expired": True}
    code = _new_code(pair_client)
    clock.now += 60
    assert pair_client.get("/api/cloud/pairing-code").json() == {"code": code, "expires_in": 540}
    clock.now += 541
    assert pair_client.get("/api/cloud/pairing-code").json() == {"code": None, "expired": True}


def test_a_code_works_once(pair_client):
    code = _new_code(pair_client)
    assert pair_client.post("/api/cloud/pair", json={"code": code}).status_code == 200
    again = pair_client.post("/api/cloud/pair", json={"code": code})
    assert again.status_code == 400
    assert "No pairing code active" in again.json()["detail"]


def test_an_expired_code_is_refused_and_forgotten(pair_client, clock):
    code = _new_code(pair_client)
    clock.now += 601
    r = pair_client.post("/api/cloud/pair", json={"code": code})
    assert (r.status_code, r.json()["detail"]) == (400, "Pairing code expired. Generate a new one.")
    assert "No pairing code active" in pair_client.post(
        "/api/cloud/pair", json={"code": code}).json()["detail"]


def test_eight_wrong_codes_lock_pairing_until_the_operator_makes_a_new_code(pair_client, clock):
    """A 6-digit code is a million guesses; eight per code (and a 10-minute
    lockout) keep a LAN guesser far from it."""
    code = _new_code(pair_client)
    for _ in range(cloud_router_mod._MAX_PAIRING_ATTEMPTS - 1):
        r = pair_client.post("/api/cloud/pair", json={"code": _wrong(code)})
        assert (r.status_code, r.json()["detail"]) == (400, "Invalid pairing code.")
    assert pair_client.post("/api/cloud/pair", json={"code": _wrong(code)}).status_code == 429
    # Locked, and the code is gone: even the right one is refused now...
    assert pair_client.post("/api/cloud/pair", json={"code": code}).status_code == 429
    clock.now += 599
    assert pair_client.post("/api/cloud/pair", json={"code": code}).status_code == 429
    # ...until the operator generates a new code, which lifts the lockout.
    assert pair_client.post("/api/cloud/pair", json={"code": _new_code(pair_client)}).status_code == 200


# ── the configure token ──────────────────────────────────────────────────


def test_the_configure_token_expires_for_verify_and_configure(pair_client, clock):
    token, _ = _pair(pair_client)
    assert pair_client.get("/api/cloud/pair-verify",
                           params={"configure_token": token}).json()["expires_in"] == 600
    assert pair_client.get("/api/cloud/pair-verify").status_code == 401
    clock.now += 601
    # Swept on every read: the expired token is simply unknown now.
    assert pair_client.get("/api/cloud/pair-verify",
                           params={"configure_token": token}).status_code == 401
    assert _configure(pair_client, token).status_code == 401
    assert not service.env_path().exists()


def test_a_configure_token_that_runs_out_mid_request_is_refused(pair_client, clock):
    """The sweep and the handler read the clock apart: a token that expires
    in between is refused, not served."""
    for path in ("verify", "configure"):
        token, _ = _pair(pair_client)
        clock.now = cloud_router_mod._configure_tokens[token]["expires_at"] - 0.5
        clock.step = 1.0   # the sweep keeps it; the handler's read is past it
        if path == "verify":
            r = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
            assert (r.status_code, r.json()["detail"]) == (401, "configure_token expired")
        else:
            r = _configure(pair_client, token)
            assert (r.status_code, r.json()["detail"]) == (
                401, "configure_token expired — re-pair the device.")
        clock.step = 0.0
        assert token not in cloud_router_mod._configure_tokens
    assert not service.env_path().exists()


def test_parallel_pairings_keep_their_own_tokens_up_to_a_cap(pair_client):
    """Two phones pairing at once must not invalidate each other's token, and
    a pair-spammer cannot grow the table without bound: past the cap the
    oldest token goes."""
    tokens = [_pair(pair_client)[0] for _ in range(cloud_router_mod._MAX_CONFIGURE_TOKENS + 1)]
    verify = [pair_client.get("/api/cloud/pair-verify", params={"configure_token": t}).status_code
              for t in tokens]
    assert verify == [401] + [200] * cloud_router_mod._MAX_CONFIGURE_TOKENS


@pytest.mark.parametrize("fields, detail", [
    ({"device_token": None}, "Missing cloud_device_id or device_token"),
    ({"cloud_device_id": None}, "Missing cloud_device_id or device_token"),
    # Another id would make this Pi connect as a different device.
    ({"cloud_device_id": "dev-7"}, "cloud_device_id does not match this pairing session"),
    ({"cloud_url": "https://relay.sporeprint.ai/x?y=1"}, "Invalid cloud_url"),
    ({"cloud_url": "http://relay.sporeprint.ai"}, "cloud_url must use https://"),
    # A newline would smuggle a second key into cloud.env.
    ({"device_token": "tok\nSPOREPRINT_CLOUD_URL=http://evil.example"},
     "Invalid character in SPOREPRINT_CLOUD_TOKEN"),
], ids=["no-token", "no-device-id", "other-device-id", "bad-url", "public-plaintext-url",
        "line-injection"])
def test_configure_refuses_credentials_it_must_not_save(pair_client, fields, detail):
    token, _ = _pair(pair_client)
    r = _configure(pair_client, token, **fields)
    assert r.status_code == 400
    assert r.json()["detail"].startswith(detail)
    assert not service.env_path().exists()
    # Refused, not burned: the same session can still finish.
    assert _configure(pair_client, token).status_code == 200


# ── where and how the credentials are saved ─────────────────────────────


async def test_configure_persists_to_data_volume_and_relearns_cloud_signing(pair_client):
    await integrations_proxy._mark_signed_frames_seen()
    token, _ = _pair(pair_client)
    assert _configure(pair_client, token).status_code == 200

    path = service.env_path()
    assert path.parent == Path(settings.database_path).resolve().parent
    text = path.read_text()
    assert "SPOREPRINT_CLOUD_TOKEN=tok-42" in text
    assert "SPOREPRINT_CLOUD_DEVICE_ID=dev-42" in text
    assert f"SPOREPRINT_CLOUD_URL={RELAY}" in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # A (re)pairing may be a different cloud: whether it signs
    # integrations_request frames is learned again.
    assert await integrations_proxy._signed_frames_seen() is False


def test_configure_allows_lan_dev_relay(pair_client):
    token, _ = _pair(pair_client)
    assert _configure(pair_client, token, cloud_url="http://192.168.1.20:8001").status_code == 200


def test_re_pairing_replaces_the_saved_credentials_and_keeps_other_lines(pair_client):
    service.env_path().write_text("# operator note\nSPOREPRINT_CLOUD_TOKEN=old\n")
    for device_token in ("tok-1", "tok-2"):
        token, _ = _pair(pair_client)
        assert _configure(pair_client, token, device_token=device_token).status_code == 200
    lines = service.env_path().read_text().splitlines()
    assert lines[0] == "# operator note"
    assert [line for line in lines if line.startswith("SPOREPRINT_CLOUD_TOKEN=")] == [
        "SPOREPRINT_CLOUD_TOKEN=tok-2"]
    assert len(lines) == 4


def test_a_failed_write_is_a_500_and_leaves_no_partial_file(pair_client, monkeypatch):
    def _refuse(path, mode):
        raise PermissionError(13, "Permission denied")

    token, _ = _pair(pair_client)
    monkeypatch.setattr(service.os, "chmod", _refuse)
    r = _configure(pair_client, token)
    assert r.status_code == 500
    assert r.json()["detail"].startswith("Failed to persist cloud credentials")
    assert sorted(p.name for p in service.env_path().parent.iterdir()
                  if p.name.startswith((".env", "cloud.env"))) == []


def test_persisted_credentials_override_empty_env(pair_client):
    service.write_cloud_env({
        "SPOREPRINT_CLOUD_URL": RELAY,
        "SPOREPRINT_CLOUD_TOKEN": "tok-9",
        "SPOREPRINT_CLOUD_DEVICE_ID": "dev-9",
    })
    # cloud_url / cloud_token are compose's empty passthrough here.
    assert service.load_persisted_cloud_credentials() is True
    assert (settings.cloud_url, settings.cloud_token, settings.cloud_device_id) == (
        RELAY, "tok-9", "dev-9")


def test_no_persisted_file_leaves_env_untouched(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", "https://from-env.example")
    assert service.load_persisted_cloud_credentials() is False
    assert settings.cloud_url == "https://from-env.example"


# ── the device id and version the session carries ───────────────────────


def test_pair_and_pair_verify_report_the_real_server_version(pair_client):
    token, body = _pair(pair_client)
    assert body["device"]["firmware_version"] == server_version() != "unknown"
    verify = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.json()["version"] == server_version()


def test_an_unpaired_pi_binds_the_session_to_the_id_it_handed_out(pair_client, monkeypatch):
    """A Pi with no device id hands out a fresh one with the configure token;
    pair-verify reports it (so the cloud pairs that id) and /configure takes
    no other."""
    monkeypatch.setattr(settings, "cloud_device_id", "")
    token, body = _pair(pair_client)
    issued = body["device"]["cloud_device_id"]
    assert issued

    verify = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.json()["cloud_device_id"] == issued

    assert _configure(pair_client, token, cloud_device_id="someone-elses-id").status_code == 400
    assert not service.env_path().exists()
    assert _configure(pair_client, token, cloud_device_id=issued).status_code == 200
    assert f"SPOREPRINT_CLOUD_DEVICE_ID={issued}" in service.env_path().read_text()


def test_a_paired_pi_keeps_its_id(pair_client):
    token, body = _pair(pair_client)
    assert body["device"]["cloud_device_id"] == "dev-42"
    verify = pair_client.get("/api/cloud/pair-verify", params={"configure_token": token})
    assert verify.json()["cloud_device_id"] == "dev-42"


# ── taking the new credentials into use; what /status reports ───────────


def test_an_unpaired_pi_reports_no_cloud_and_no_restart_due(pair_client):
    status = pair_client.get("/api/cloud/status").json()
    assert (status["configured"], status["connected"], status["restart_required"]) == (
        False, False, False)


class _LiveSocket:
    def __init__(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


@pytest.mark.parametrize("connector", ["connected", "between-retries", "starting"])
def test_configure_applies_new_credentials_to_a_running_connector(pair_client, monkeypatch,
                                                                  connector):
    """A token rotation reaches a running connector: a session that used the
    old token is closed, and a retry sleep is cut short so the next attempt
    uses the new one (it used to retry the dead token until someone
    restarted the Pi). A connector still starting up reads them on its
    first attempt. No restart is due in any of these."""
    monkeypatch.setattr(settings, "cloud_token", "old-token")
    monkeypatch.setattr(service, "_connector_running", True)
    socket, event = _LiveSocket(), asyncio.Event()
    socket.connected = connector == "connected"
    if connector != "starting":
        monkeypatch.setattr(service, "_sio", socket)
        monkeypatch.setattr(service, "_wake_event", event)
    token, _ = _pair(pair_client)
    r = _configure(pair_client, token, device_token="rotated-token")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    assert (settings.cloud_token, settings.cloud_device_id) == ("rotated-token", "dev-42")
    assert socket.connected is False
    assert event.is_set() is (connector != "starting")
    assert pair_client.get("/api/cloud/status").json()["restart_required"] is False


def test_pairing_a_pi_that_booted_unpaired_asks_for_a_restart(pair_client):
    """A Pi unpaired at boot runs no connector: pairing saves and loads the
    credentials, and both /configure and /status say only a restart connects
    them (the setup wizard used to wait for a connection that never came)."""
    token, _ = _pair(pair_client)
    r = _configure(pair_client, token)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is False
    assert "Restart" in r.json()["message"]
    assert settings.cloud_token == "tok-42"
    status = pair_client.get("/api/cloud/status").json()
    assert (status["configured"], status["connected"], status["restart_required"]) == (
        True, False, True)


@pytest.mark.parametrize("cloud_url, running, connected, status", [
    ("", False, False, "not_configured"),
    (RELAY, False, False, "restart_required"),
    (RELAY, True, False, "reconnecting"),
    (RELAY, True, True, "connected"),
])
def test_reconnect_reports_what_it_did(pair_client, monkeypatch, cloud_url, running, connected,
                                       status):
    monkeypatch.setattr(settings, "cloud_url", cloud_url)
    monkeypatch.setattr(service, "_connector_running", running)
    monkeypatch.setattr(service, "_connected", connected)
    event = asyncio.Event()
    monkeypatch.setattr(service, "_wake_event", event)
    assert pair_client.post("/api/cloud/reconnect").json()["status"] == status
    assert event.is_set() is (status == "reconnecting")


def test_reconnect_retries_with_the_saved_credentials(pair_client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_url", RELAY)
    monkeypatch.setattr(settings, "cloud_token", "boot-token")
    monkeypatch.setattr(service, "_connector_running", True)
    monkeypatch.setattr(service, "_wake_event", asyncio.Event())
    service.write_cloud_env({"SPOREPRINT_CLOUD_TOKEN": "paired-later"})
    assert pair_client.post("/api/cloud/reconnect").json()["status"] == "reconnecting"
    assert settings.cloud_token == "paired-later"
