"""Cloud `system/ota` command guards + pipeline failure reporting.

* deps-infra#22 — the shipped Docker install can't self-update (no systemd,
  no sudo, no /opt layout, read-only image): refuse before acking.
* #12 — an unwritable OTA state dir must still produce a `failed` step (it
  used to raise outside the try: success ack, then silence); a failed
  `systemctl restart` must not be recorded as complete/ok; the task is kept
  referenced and a second OTA is refused while one runs.
* #21 — refuse a downgrade to an older (validly signed) release.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest

import app.cloud.service as service
from app.cloud import ota
from app.config import settings


@pytest.fixture
def bare_metal(tmp_path, monkeypatch):
    """A supported (systemd /opt-style) layout, not inside Docker."""
    root = tmp_path / "opt"
    (root / "releases" / "5.0.0").mkdir(parents=True)
    root.joinpath("current").symlink_to(root / "releases" / "5.0.0")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", root)
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ota, "server_version", lambda: "5.0.0")
    monkeypatch.setattr(service, "_ota_task", None)
    return root


async def test_docker_install_refuses_ota_before_ack(tmp_path, monkeypatch):
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.touch()
    monkeypatch.setattr(ota, "_DOCKERENV", dockerenv)
    started: list = []
    monkeypatch.setattr(ota, "run_ota_update", lambda *a: started.append(a))
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.0.1", "channel": "stable"}
    )
    assert ok is False
    assert "Docker" in err
    assert started == []


async def test_missing_install_layout_refuses_ota(tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", tmp_path / "nothing-here")
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.0.1", "channel": "stable"}
    )
    assert ok is False
    assert "current" in err


async def test_invalid_version_rejected_before_ack(bare_metal):
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "../../etc/passwd", "channel": "stable"}
    )
    assert ok is False
    assert "version" in err


async def test_downgrade_refused(bare_metal):
    ok, err = await service._dispatch_system_command(
        "ota", {"firmware_version": "4.9.9", "channel": "stable"}
    )
    assert ok is False
    assert "downgrade" in err


def test_same_or_newer_version_allowed(bare_metal, monkeypatch):
    assert ota.validate_request("5.0.0", "stable") is None
    # A beta request is refused on a stable Pi (channel binding) and
    # allowed once the Pi follows beta.
    assert "channel" in ota.validate_request("v5.1.0-beta.1", "beta")
    monkeypatch.setattr(settings, "ota_channel", "beta")
    assert ota.validate_request("v5.1.0-beta.1", "beta") is None


async def test_second_ota_refused_while_one_runs(bare_metal, monkeypatch):
    gate = asyncio.Event()

    async def slow_update(version, channel):
        await gate.wait()
        return {"ok": True}

    monkeypatch.setattr(ota, "run_ota_update", slow_update)
    ok1, _ = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.0.1", "channel": "stable"}
    )
    assert ok1 is True
    assert service._ota_task is not None, "task must be kept referenced"
    ok2, err2 = await service._dispatch_system_command(
        "ota", {"firmware_version": "5.0.2", "channel": "stable"}
    )
    assert ok2 is False
    assert "in progress" in err2
    task = service._ota_task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_unwritable_state_dir_still_emits_failed_step(tmp_path, monkeypatch):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.setattr(ota, "_DEFAULT_STATE_DIR", blocker / "ota")  # mkdir fails
    steps: list[dict] = []

    async def capture(event_type, data):
        steps.append(data)
        return True

    monkeypatch.setattr(service, "forward_event", capture)
    result = await ota.run_ota_update("5.0.1", "stable")
    assert result["ok"] is False
    assert steps and steps[-1]["step"] == "failed"


def test_failed_restart_is_an_error(monkeypatch):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="sudo: a password is required")

    monkeypatch.setattr(ota.subprocess, "run", fake_run)
    with pytest.raises(ota.OTAError, match="restart failed"):
        ota._restart_unit()


def test_successful_restart_passes(monkeypatch):
    monkeypatch.setattr(
        ota.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""),
    )
    ota._restart_unit()
