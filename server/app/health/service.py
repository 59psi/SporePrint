"""System health metrics for the admin dashboard.

Provides CPU, memory, disk, temperature via psutil.
MQTT stats via $SYS/# topic subscription (cached).
Socket.IO client tracking via connect/disconnect events.
Background task status via registry.
"""

import asyncio
import logging
import os
import subprocess
import time

import psutil

from ..auth import socketio_client_addr
from ..config import settings
from ..db import get_db

log = logging.getLogger(__name__)

# MQTT broker stats (populated by mqtt.py subscribing to $SYS/#)
_mqtt_stats: dict = {}

# table_counts in get_system_metrics: six COUNT(*) scans (telemetry_readings
# runs to millions of rows; seconds on a cold SD card), while the Fleet page
# polls every 15 s and the cloud heartbeat every 60 s, and no client reads
# the counts. Still sent (REST responses are additive-only), but recounted at
# most this often.
_TABLE_COUNTS_TTL_SECONDS = 600
_COUNTED_TABLES = ("telemetry_readings", "sessions", "weather_readings",
                   "vision_frames", "automation_firings", "telemetry_rollups")
_table_counts_cache: dict = {"at": None, "counts": {}}

# Socket.IO client tracking
_sio_clients: dict[str, dict] = {}  # sid → {connected_at, ip, platform}

# Background task registry
_task_registry: dict[str, dict] = {}  # name → {status, last_run, error}


def update_mqtt_stat(key: str, value):
    """Called from mqtt.py when a $SYS/# message arrives."""
    _mqtt_stats[key] = value


def track_client_connect(sid: str, environ: dict | None = None):
    _sio_clients[sid] = {
        "connected_at": time.time(),
        # The ASGI peer, not engineio's hardcoded REMOTE_ADDR placeholder.
        "ip": socketio_client_addr(environ) or "unknown",
    }


def track_client_disconnect(sid: str):
    _sio_clients.pop(sid, None)


def register_task(name: str, status: str = "idle"):
    _task_registry[name] = {"status": status, "last_run": None, "error": None}


def update_task(name: str, status: str, error: str | None = None):
    if name in _task_registry:
        _task_registry[name]["status"] = status
        _task_registry[name]["last_run"] = time.time()
        _task_registry[name]["error"] = error


async def _table_counts() -> dict:
    """Row counts of the big tables, recounted at most every
    _TABLE_COUNTS_TTL_SECONDS. A failed count keeps the last good ones."""
    now = time.monotonic()
    at = _table_counts_cache["at"]
    if at is not None and now - at < _TABLE_COUNTS_TTL_SECONDS:
        return dict(_table_counts_cache["counts"])
    counts: dict[str, int] = {}
    try:
        async with get_db() as db:
            for name in _COUNTED_TABLES:
                cursor = await db.execute(f"SELECT COUNT(*) AS cnt FROM {name}")
                counts[name] = (await cursor.fetchone())["cnt"]
    except Exception as e:
        log.debug("table row counts failed: %s", e)
        return dict(_table_counts_cache["counts"]) or counts
    _table_counts_cache.update(at=now, counts=counts)
    return dict(counts)


async def get_system_metrics() -> dict:
    """CPU, memory, disk, temperature, uptime, DB size."""
    # cpu_percent(interval=0.1) sleeps 100 ms to sample — keep it off the loop.
    cpu_percent = await asyncio.to_thread(psutil.cpu_percent, interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = psutil.boot_time()

    # CPU temperature (Raspberry Pi — not available on macOS)
    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    cpu_temp = entries[0].current
                    break
    except (AttributeError, OSError):
        pass

    # Database size
    db_size_bytes = 0
    db_path = settings.database_path
    if os.path.exists(db_path):
        db_size_bytes = os.path.getsize(db_path)

    table_counts = await _table_counts()

    from ..mqtt import get_reliability_counters
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "memory_used_mb": round(mem.used / 1024 / 1024),
        "memory_total_mb": round(mem.total / 1024 / 1024),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
        "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
        "cpu_temp_c": cpu_temp,
        "uptime_hours": round((time.time() - boot_time) / 3600, 1),
        "db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
        "table_counts": table_counts,
        "reliability": get_reliability_counters(),
    }


def get_mqtt_stats() -> dict:
    return dict(_mqtt_stats)


def _parse_chrony_tracking(stdout: str) -> dict:
    """`chronyc -n tracking` output, keyed by lowercased field name."""
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            parsed[k.strip().lower().replace(" ", "_")] = v.strip()
    return {
        "available": True,
        "reference_id":        parsed.get("reference_id"),
        "stratum":             parsed.get("stratum"),
        "system_time_offset":  parsed.get("system_time"),
        "last_offset":         parsed.get("last_offset"),
        "rms_offset":          parsed.get("rms_offset"),
        "frequency":           parsed.get("frequency"),
        "residual_freq":       parsed.get("residual_freq"),
        "update_interval":     parsed.get("update_interval"),
        "leap_status":         parsed.get("leap_status"),
    }


async def get_clock_status() -> dict:
    """v3.3.3 — the Pi's wall clock and chrony tracking state.

    The cloud relay signs every command frame with a `ts` field. If the Pi
    clock drifts more than 30 s from wall-clock truth every cloud-issued
    command fails with "ts outside replay window" and the failure surface
    is a user-reported support ticket. This makes drift directly observable:

      * ``pi_ts`` — current Pi epoch seconds. Compare against the caller's
        clock for a quick delta without needing chrony present.
      * ``chrony.*`` — ``chronyc -n tracking`` output parsed into the key
        fields (system_time, last_offset, rms_offset, update_interval,
        leap_status). ``available: false`` (with a ``reason``) if chrony is
        not installed or the socket is not accessible.

    Never returns secrets; safe for unauthenticated LAN scrape by a local
    Prometheus / UptimeRobot.
    """
    pi_ts = time.time()
    chrony: dict[str, object] = {"available": False}
    try:
        # -n: numeric addresses (no DNS). 1.5 s is well inside any reasonable
        # healthcheck budget. Run in a worker thread: a blocking call here
        # would stall MQTT ingest, automation and Socket.IO for up to the
        # timeout on every poll.
        result = await asyncio.to_thread(
            subprocess.run,
            ["chronyc", "-n", "tracking"],
            capture_output=True, text=True, timeout=1.5,
        )
        if result.returncode == 0:
            chrony = _parse_chrony_tracking(result.stdout)
    except FileNotFoundError:
        chrony = {"available": False, "reason": "chrony not installed"}
    except subprocess.TimeoutExpired:
        chrony = {"available": False, "reason": "chronyc timeout"}
    except Exception as e:
        chrony = {"available": False, "reason": type(e).__name__}

    return {
        "pi_ts": pi_ts,
        "pi_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pi_ts)),
        "timezone": os.environ.get("TZ", "UTC"),
        "chrony": chrony,
    }


def get_client_list() -> list[dict]:
    now = time.time()
    return [
        {"sid": sid, **info, "duration_sec": round(now - info["connected_at"])}
        for sid, info in _sio_clients.items()
    ]


def get_task_statuses() -> dict:
    # Merge cloud connector status
    from ..cloud.service import get_task_status
    merged = dict(_task_registry)
    merged.update(get_task_status())
    return merged
