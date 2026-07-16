"""Tests for system actions — the grace-period reboot.

The LAN routes (reboot, broker restart, hostname) were removed by product
decision; reboot is now reachable only via the authenticated cloud command
channel, which calls schedule_reboot() directly. Tests monkeypatch
subprocess.run inside app.system_actions so no systemctl ever actually runs.
"""

import asyncio
import subprocess

import pytest

from app import system_actions


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

    # Let the scheduled task run to completion
    for _ in range(5):
        await real_sleep(0)

    assert sleeps == [5]
    assert fake_run.calls == [["sudo", "systemctl", "reboot"]]
