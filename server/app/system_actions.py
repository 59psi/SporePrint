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
import subprocess

log = logging.getLogger(__name__)

REBOOT_GRACE_SECONDS = 5


def schedule_reboot() -> dict:
    """Schedule `systemctl reboot` after a grace period.

    The delay lets the command ack flush back over the cloud channel
    before the box goes down, so the caller sees the ack instead of a
    blackholed request.
    """
    async def _reboot_task():
        try:
            await asyncio.sleep(REBOOT_GRACE_SECONDS)
            subprocess.run(["sudo", "systemctl", "reboot"], check=False)
        except Exception as e:
            log.error("Reboot scheduling failed: %s", e)

    asyncio.create_task(_reboot_task())
    return {"status": "scheduled", "grace_seconds": REBOOT_GRACE_SECONDS}
