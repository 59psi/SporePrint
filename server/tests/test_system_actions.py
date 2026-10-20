"""Tests for system actions — the grace-period reboot.

The LAN routes (reboot, broker restart, hostname) were removed by product
decision; reboot is now reachable only via the authenticated cloud command
channel, which calls schedule_reboot() directly. Tests monkeypatch
subprocess.run inside app.system_actions so no systemctl ever actually runs.
"""

import asyncio
import subprocess
import threading

import pytest

from app import system_actions
from app.cloud import ota


@pytest.fixture()
def fake_run(monkeypatch):
    """Record subprocess calls instead of executing them.

    Returns the list of argv lists via `fake_run.calls`.
    """
    calls: list[list[str]] = []

    def _fake(args, check=False, capture_output=False, text=False, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(system_actions.subprocess, "run", _fake)
    _fake.calls = calls
    return _fake


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

    # The scheduled task is held until it finishes; let it run to completion.
    (task,) = system_actions._reboot_tasks
    await task

    assert sleeps == [5]
    # -n: never wait for a password prompt nobody can answer.
    assert fake_run.calls == [["sudo", "-n", "systemctl", "reboot"]]
    assert system_actions._reboot_tasks == set()


def _refused(args, **kwargs):
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="sudo: a password is required")


def _no_sudo(args, **kwargs):
    raise FileNotFoundError(2, "No such file or directory: 'sudo'")


@pytest.mark.parametrize("run, logged", [
    (_refused, "Reboot failed: systemctl exited 1 (sudo: a password is required)"),
    (_no_sudo, "Reboot scheduling failed: [Errno 2] No such file or directory: 'sudo'"),
], ids=["sudo-refused", "no-sudo"])
async def test_a_reboot_that_did_not_happen_is_logged(monkeypatch, caplog, run, logged):
    """The ack already went out; the log is the only place a failed reboot
    shows (the cloud command path refuses earlier where it can)."""
    monkeypatch.setattr(system_actions.subprocess, "run", run)
    monkeypatch.setattr(system_actions, "REBOOT_GRACE_SECONDS", 0)
    system_actions.schedule_reboot()
    await asyncio.gather(*system_actions._reboot_tasks)
    assert logged in caplog.text


async def test_the_reboot_command_runs_off_the_event_loop(monkeypatch):
    """A slow systemctl (or a sudo that waits) must not stall MQTT ingest."""
    on_main_thread = []

    def _run(args, **kwargs):
        on_main_thread.append(threading.current_thread() is threading.main_thread())
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(system_actions.subprocess, "run", _run)
    monkeypatch.setattr(system_actions, "REBOOT_GRACE_SECONDS", 0)
    system_actions.schedule_reboot()
    await asyncio.gather(*system_actions._reboot_tasks)
    assert on_main_thread == [False]


# ── refused before the ack where it cannot run ──────────────────────────


@pytest.mark.parametrize("docker, missing, reason", [
    (True, (), "reboot is not supported in the Docker deployment"),
    (False, ("systemctl",), "reboot needs systemctl on this host, which it does not have"),
    (False, (), None),
], ids=["docker", "no-systemctl", "bare-metal"])
def test_reboot_is_refused_where_the_host_cannot_be_rebooted(monkeypatch, tmp_path, docker,
                                                             missing, reason):
    dockerenv = tmp_path / ".dockerenv"
    if docker:
        dockerenv.touch()
    monkeypatch.setattr(ota, "_DOCKERENV", dockerenv)
    monkeypatch.setattr(system_actions.shutil, "which",
                        lambda tool: None if tool in missing else f"/usr/bin/{tool}")
    got = system_actions.reboot_unsupported_reason()
    if reason is None:
        assert got is None
    else:
        assert got.startswith(reason), got
