"""Cloud `system/ota` command guards + pipeline failure reporting.

* A command that cannot succeed is refused BEFORE the ack, so the cloud gets
  a failure instead of an accepted update followed by silence: the shipped
  Docker install can't self-update (no systemd, no sudo, no /opt layout,
  read-only image), and neither a malformed request, another release
  channel nor a downgrade (even one the command asks for) is acted on.
* An unwritable OTA state dir must still produce a `failed` step (it used to
  raise outside the try: success ack, then silence); a failed
  `systemctl restart` must not be recorded as complete/ok; the task is kept
  referenced and a second OTA is refused while one runs.
"""

from __future__ import annotations

import asyncio
import re
import subprocess

import pytest

import app.cloud.service as service
from app.cloud import ota
from app.config import settings


@pytest.fixture
def bare_metal(tmp_path, monkeypatch):
    """A supported (systemd /opt-style) layout on 5.0.0 following stable, not
    inside Docker; `started` records any pipeline the command starts."""
    root = tmp_path / "opt"
    (root / "releases" / "5.0.0").mkdir(parents=True)
    root.joinpath("current").symlink_to(root / "releases" / "5.0.0")
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", root)
    monkeypatch.setattr(ota, "_DOCKERENV", tmp_path / "no-dockerenv")
    monkeypatch.setattr(ota, "server_version", lambda: "5.0.0")
    monkeypatch.setattr(settings, "ota_channel", "stable")
    monkeypatch.setattr(settings, "ota_allow_downgrade", False)
    monkeypatch.setattr(service, "_ota_task", None)
    started: list = []
    monkeypatch.setattr(ota, "run_ota_update", lambda *a, **k: started.append(a))
    return started


def _in_docker(tmp_path, monkeypatch):
    dockerenv = tmp_path / ".dockerenv"
    dockerenv.touch()
    monkeypatch.setattr(ota, "_DOCKERENV", dockerenv)


def _no_install_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(ota, "_DEFAULT_INSTALL_ROOT", tmp_path / "nothing-here")


@pytest.mark.parametrize("setup, payload, error", [
    (_in_docker, {"firmware_version": "5.0.1", "channel": "stable"}, "Docker"),
    (_no_install_layout, {"firmware_version": "5.0.1", "channel": "stable"}, "current"),
    (None, {"channel": "stable"}, "ota requires payload.firmware_version"),
    (None, {"firmware_version": "5.0.1", "channel": "nightly"}, "ota channel must be one of"),
    (None, {"firmware_version": "../../etc/passwd", "channel": "stable"}, "version must match"),
    (None, {"firmware_version": "5.1.0-beta.1", "channel": "beta"},
     "this Pi follows the 'stable' OTA channel; refusing a 'beta' release "
     "(set SPOREPRINT_OTA_CHANNEL=beta on the Pi"),
    # Only the Pi's own setting allows a downgrade; payload keys don't.
    (None, {"firmware_version": "4.9.9", "channel": "stable",
            "allow_downgrade": True, "ota_allow_downgrade": True}, "downgrade"),
], ids=["docker", "no-install-layout", "no-version", "unknown-channel", "bad-version",
        "other-channel", "downgrade"])
async def test_an_ota_command_that_cannot_succeed_is_refused_before_the_ack(
        bare_metal, tmp_path, monkeypatch, setup, payload, error):
    if setup is not None:
        setup(tmp_path, monkeypatch)
    ok, err = await service._dispatch_system_command("ota", payload)
    assert ok is False
    assert error in err
    assert bare_metal == [] and service._ota_task is None


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


def _exits(code: int, stderr: str = ""):
    return lambda *a, **k: subprocess.CompletedProcess(a[0], code, stdout="", stderr=stderr)


def _missing(*a, **k):
    raise FileNotFoundError(2, "No such file or directory: 'sudo'")


@pytest.mark.parametrize("run, error", [
    (_exits(0), None),
    # -n: no prompt, so a missing NOPASSWD rule fails fast instead of hanging.
    (_exits(1, "sudo: a password is required"),
     "restart failed: systemctl exited 1 (sudo: a password is required)"),
    (_missing, "restart failed"),
], ids=["restarted", "sudo-refused", "no-sudo"])
def test_a_restart_that_did_not_happen_is_an_error(monkeypatch, run, error):
    """A failed `systemctl restart` used to be recorded as complete/ok."""
    monkeypatch.setattr(ota.subprocess, "run", run)
    if error is None:
        ota._restart_unit()
        return
    with pytest.raises(ota.OTAError, match=re.escape(error)):
        ota._restart_unit()
