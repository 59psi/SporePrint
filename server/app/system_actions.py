"""System-level actions for the Pi itself.

The LAN OS-mutation routes (reboot, broker restart, hostname management)
were removed from the REST surface by product decision. Reboot remains
available ONLY via the authenticated cloud command channel — HMAC-signed
commands dispatched by app/cloud/service.py, which imports
schedule_reboot() from here.

The subprocess call uses a static argument list (never shell=True) with
check=False.
"""

import asyncio
import logging
import shutil
import subprocess

from .cloud.ota import running_in_docker

log = logging.getLogger(__name__)

REBOOT_GRACE_SECONDS = 5

# Scheduled reboot tasks, held until they finish: the event loop keeps only a
# weak reference to a task, so a fire-and-forget one may be collected.
_reboot_tasks: set[asyncio.Task] = set()


def reboot_unsupported_reason() -> str | None:
    """Why this process cannot reboot the host, or None when it can.

    Checked before a reboot command is acknowledged: the reboot runs after
    the ack, so a refusal has to come first or the cloud reports a reboot
    that never happens. The shipped install (install.sh → docker compose)
    runs the server as a non-root user in a slim image with no sudo, no
    systemd and no access to the host.
    """
    if running_in_docker():
        return ("reboot is not supported in the Docker deployment (the server "
                "runs in a container with no access to the host) — reboot the "
                "Pi on the LAN")
    missing = [tool for tool in ("sudo", "systemctl") if shutil.which(tool) is None]
    if missing:
        return f"reboot needs {' and '.join(missing)} on this host, which it does not have"
    return None


def schedule_reboot() -> dict:
    """Schedule `systemctl reboot` after a grace period.

    The delay lets the command ack flush back over the cloud channel
    before the box goes down, so the caller sees the ack instead of a
    blackholed request. `sudo -n` never prompts: without a NOPASSWD rule
    it fails at once, and the failure is logged with its exit status. The
    command runs in a worker thread, so however long it takes, MQTT ingest
    and the rules keep running on the event loop.
    """
    async def _reboot_task():
        try:
            await asyncio.sleep(REBOOT_GRACE_SECONDS)
            result = await asyncio.to_thread(
                subprocess.run,
                ["sudo", "-n", "systemctl", "reboot"],
                check=False, capture_output=True, text=True,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[:200]
                log.error("Reboot failed: systemctl exited %s%s", result.returncode,
                          f" ({detail})" if detail else "")
        except Exception as e:
            log.error("Reboot scheduling failed: %s", e)

    task = asyncio.create_task(_reboot_task())
    _reboot_tasks.add(task)
    task.add_done_callback(_reboot_tasks.discard)
    return {"status": "scheduled", "grace_seconds": REBOOT_GRACE_SECONDS}
