"""Tests for LAN system actions — reboot, broker restart, hostname.

Every test monkeypatches subprocess.run inside app.system_actions so no
systemctl/hostnamectl ever actually runs.
"""

import asyncio
import subprocess

import pytest

from app import system_actions


@pytest.fixture()
def fake_run(monkeypatch):
    """Record subprocess calls instead of executing them.

    Returns the list of argv lists. Set `fake_run.returncodes[argv0]` to a
    non-zero value to simulate that command failing (matched on the first
    two argv elements after sudo, e.g. "systemctl restart").
    """
    calls: list[list[str]] = []
    returncodes: dict[str, int] = {}
    stderrs: dict[str, str] = {}

    def _fake(args, check=False, capture_output=False, text=False, **kwargs):
        calls.append(list(args))
        key = " ".join(args[1:3]) if args[0] == "sudo" else " ".join(args[:2])
        rc = returncodes.get(key, 0)
        return subprocess.CompletedProcess(args, rc, stdout="", stderr=stderrs.get(key, ""))

    monkeypatch.setattr(system_actions.subprocess, "run", _fake)
    _fake.calls = calls
    _fake.returncodes = returncodes
    _fake.stderrs = stderrs
    return _fake


# ── Reboot ──────────────────────────────────────────────────────


async def test_schedule_reboot_runs_systemctl_after_grace(fake_run, monkeypatch):
    """The scheduled task sleeps the grace period, then calls the exact argv."""
    real_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = system_actions.schedule_reboot()
    assert result == {"status": "scheduled", "grace_seconds": 5}

    # Nothing runs until the grace elapses
    assert fake_run.calls == []

    # Let the scheduled task run to completion
    for _ in range(5):
        await real_sleep(0)

    assert sleeps == [5]
    assert fake_run.calls == [["sudo", "systemctl", "reboot"]]


def test_reboot_endpoint_returns_scheduled(client, fake_run):
    r = client.post("/api/settings/system/reboot")
    assert r.status_code == 200
    assert r.json() == {"status": "scheduled", "grace_seconds": 5}
    # Grace period hasn't elapsed — nothing executed yet
    assert fake_run.calls == []


# ── Broker restart ──────────────────────────────────────────────


def test_restart_broker_success(client, fake_run):
    r = client.post("/api/settings/system/restart-broker")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert fake_run.calls == [["sudo", "systemctl", "restart", "mosquitto"]]


def test_restart_broker_failure_returns_500(client, fake_run):
    fake_run.returncodes["systemctl restart"] = 1
    fake_run.stderrs["systemctl restart"] = "Unit mosquitto.service not found."
    r = client.post("/api/settings/system/restart-broker")
    assert r.status_code == 500
    assert "Unit mosquitto.service not found." in r.json()["detail"]


# ── Hostname ────────────────────────────────────────────────────


def test_set_hostname_valid(client, fake_run):
    r = client.put("/api/settings/hostname", json={"hostname": "chamber-01"})
    assert r.status_code == 200
    assert r.json() == {"hostname": "chamber-01", "avahi_restarted": True}
    assert fake_run.calls == [
        ["sudo", "hostnamectl", "set-hostname", "chamber-01"],
        ["sudo", "systemctl", "restart", "avahi-daemon"],
    ]


def test_set_hostname_uppercase_coerced(client, fake_run):
    r = client.put("/api/settings/hostname", json={"hostname": "Chamber-01"})
    assert r.status_code == 200
    assert r.json()["hostname"] == "chamber-01"
    assert fake_run.calls[0] == ["sudo", "hostnamectl", "set-hostname", "chamber-01"]


@pytest.mark.parametrize("bad", [
    "",                       # empty
    "under_score",            # invalid char
    "has.dot",                # invalid char (label rules, not FQDN)
    "-leading",               # leading hyphen
    "trailing-",              # trailing hyphen
    "sp ace",                 # space
    "a" * 64,                 # too long (max 63)
    "pi;reboot",              # injection attempt
])
def test_set_hostname_invalid_rejected_422(client, fake_run, bad):
    r = client.put("/api/settings/hostname", json={"hostname": bad})
    assert r.status_code == 422
    # Validation failed BEFORE any subprocess ran
    assert fake_run.calls == []


def test_set_hostname_max_length_accepted(client, fake_run):
    name = "a" * 63
    r = client.put("/api/settings/hostname", json={"hostname": name})
    assert r.status_code == 200
    assert r.json()["hostname"] == name


def test_set_hostname_avahi_failure_still_200(client, fake_run):
    fake_run.returncodes["systemctl restart"] = 1
    fake_run.stderrs["systemctl restart"] = "avahi-daemon.service not found"
    r = client.put("/api/settings/hostname", json={"hostname": "shroombox"})
    assert r.status_code == 200
    assert r.json() == {"hostname": "shroombox", "avahi_restarted": False}


def test_set_hostname_hostnamectl_failure_returns_500(client, fake_run):
    fake_run.returncodes["hostnamectl set-hostname"] = 1
    fake_run.stderrs["hostnamectl set-hostname"] = "Could not set hostname: Access denied"
    r = client.put("/api/settings/hostname", json={"hostname": "shroombox"})
    assert r.status_code == 500
    assert "Access denied" in r.json()["detail"]
    # avahi restart is never attempted after a hostnamectl failure
    assert fake_run.calls == [["sudo", "hostnamectl", "set-hostname", "shroombox"]]


def test_get_hostname(client, monkeypatch):
    monkeypatch.setattr(system_actions.socket, "gethostname", lambda: "testpi")
    r = client.get("/api/settings/system/hostname")
    assert r.status_code == 200
    assert r.json() == {"hostname": "testpi"}


def test_hostname_route_not_shadowed_by_key_catchall(client, fake_run):
    """PUT /api/settings/hostname must hit set_hostname, not the /{key}
    settings catch-all (which would 400 with 'Unknown setting')."""
    r = client.put("/api/settings/hostname", json={"hostname": "edge-case"})
    assert r.status_code == 200
    assert r.json()["hostname"] == "edge-case"

    # The generic settings PUT still works for real settings keys
    r2 = client.put("/api/settings/ntfy_topic", json={"value": "mytopic"})
    assert r2.status_code == 200
