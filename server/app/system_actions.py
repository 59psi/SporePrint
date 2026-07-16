"""System-level actions for the Pi itself, exposed on the LAN API.

These back the Settings page's "System" section: reboot, broker restart,
and hostname management. The reboot mirrors the cloud command channel's
implementation (app/cloud/service.py::_dispatch_system_command, `reboot`
branch) — schedule after a grace period so the HTTP response flushes
before the box goes down.

Every subprocess call uses a static argument list (never shell=True) with
check=False, capturing stderr so failures are reported honestly. The only
user-supplied value that ever reaches an argv is the hostname, and only
after RFC-1123 validation.
"""

import asyncio
import logging
import re
import socket
import subprocess

log = logging.getLogger(__name__)

REBOOT_GRACE_SECONDS = 5

# RFC-1123 label: lowercase alphanumerics + inner hyphens, max 63 chars.
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run a static-argv command, capturing output for error reporting."""
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _stderr(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or "").strip() or f"exit code {proc.returncode}"


def schedule_reboot() -> dict:
    """Schedule `systemctl reboot` after a grace period.

    Mirrors the cloud-channel implementation: the delay lets the HTTP
    response flush before the box goes down, so the UI sees the ack
    instead of a blackholed request.
    """
    async def _reboot_task():
        try:
            await asyncio.sleep(REBOOT_GRACE_SECONDS)
            subprocess.run(["sudo", "systemctl", "reboot"], check=False)
        except Exception as e:
            log.error("Reboot scheduling failed: %s", e)

    asyncio.create_task(_reboot_task())
    return {"status": "scheduled", "grace_seconds": REBOOT_GRACE_SECONDS}


def restart_broker() -> None:
    """Restart the mosquitto broker (immediate — it doesn't kill the API).

    Raises RuntimeError with the captured stderr on failure.
    """
    proc = _run(["sudo", "systemctl", "restart", "mosquitto"])
    if proc.returncode != 0:
        raise RuntimeError(f"mosquitto restart failed: {_stderr(proc)}")


def validate_hostname(hostname: str) -> str:
    """Lowercase and validate against RFC-1123 label rules.

    Returns the normalized hostname. Raises ValueError on rejection —
    this is the ONLY gate between user input and a hostnamectl argv.
    """
    name = hostname.strip().lower()
    if not _HOSTNAME_RE.fullmatch(name):
        raise ValueError(
            "Hostname must be 1-63 characters: lowercase letters, digits, "
            "and hyphens (no leading/trailing hyphen)."
        )
    return name


def set_hostname(hostname: str) -> dict:
    """Apply a validated hostname via hostnamectl, then restart avahi
    (best-effort) so mDNS advertises the new name.

    Raises ValueError on invalid hostname, RuntimeError if hostnamectl
    fails. An avahi restart failure does NOT fail the request — it's
    reported via `avahi_restarted` in the response.
    """
    name = validate_hostname(hostname)

    proc = _run(["sudo", "hostnamectl", "set-hostname", name])
    if proc.returncode != 0:
        raise RuntimeError(f"hostnamectl failed: {_stderr(proc)}")

    avahi = _run(["sudo", "systemctl", "restart", "avahi-daemon"])
    avahi_restarted = avahi.returncode == 0
    if not avahi_restarted:
        log.warning("avahi-daemon restart failed: %s", _stderr(avahi))

    return {"hostname": name, "avahi_restarted": avahi_restarted}


def get_hostname() -> str:
    """Current hostname as the OS reports it."""
    return socket.gethostname()
