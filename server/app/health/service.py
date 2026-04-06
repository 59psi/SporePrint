"""System health metrics for the admin dashboard.

Provides CPU, memory, disk, temperature via psutil.
MQTT stats via $SYS/# topic subscription (cached).
Socket.IO client tracking via connect/disconnect events.
Background task status via registry.
"""

import logging
import os
import time

import psutil

from ..config import settings
from ..db import get_db

log = logging.getLogger(__name__)

# MQTT broker stats (populated by mqtt.py subscribing to $SYS/#)
_mqtt_stats: dict = {}

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
        "ip": environ.get("REMOTE_ADDR", "unknown") if environ else "unknown",
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


async def get_system_metrics() -> dict:
    """CPU, memory, disk, temperature, uptime, DB size."""
    cpu_percent = psutil.cpu_percent(interval=0.1)
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

    # Table row counts
    table_counts = {}
    try:
        async with get_db() as db:
            for table in ["telemetry_readings", "sessions", "weather_readings",
                          "vision_frames", "automation_firings", "telemetry_rollups"]:
                cursor = await db.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                row = await cursor.fetchone()
                table_counts[table] = row["cnt"]
    except Exception:
        pass

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
    }


def get_mqtt_stats() -> dict:
    return dict(_mqtt_stats)


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
