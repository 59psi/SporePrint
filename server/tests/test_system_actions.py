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


async def test_a_failed_reboot_is_logged_with_its_exit_status(monkeypatch, caplog):
    def _refused(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="sudo: a password is required")

    monkeypatch.setattr(system_actions.subprocess, "run", _refused)
    monkeypatch.setattr(system_actions, "REBOOT_GRACE_SECONDS", 0)
    system_actions.schedule_reboot()
    await asyncio.gather(*system_actions._reboot_tasks)
    assert "systemctl exited 1 (sudo: a password is required)" in caplog.text


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


def test_reboot_is_unsupported_in_the_docker_deployment(monkeypatch, tmp_path):
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.touch()
    monkeypatch.setattr(ota, "_DOCKERENV", dockerenv)
    reason = system_actions.reboot_unsupported_reason()
    assert reason and "Docker" in reason


def test_reboot_needs_sudo_and_systemctl(monkeypatch, tmp_path):
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(system_actions.shutil, "which",
                        lambda tool: None if tool == "systemctl" else f"/usr/bin/{tool}")
    assert system_actions.reboot_unsupported_reason() == (
        "reboot needs systemctl on this host, which it does not have")
    monkeypatch.setattr(system_actions.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    assert system_actions.reboot_unsupported_reason() is None
