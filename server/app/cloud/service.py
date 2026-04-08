"""Cloud connector: pushes telemetry upstream and receives remote commands.

Opt-in — inactive unless SPOREPRINT_CLOUD_URL and SPOREPRINT_CLOUD_TOKEN are set.
Uses python-socketio AsyncClient to maintain a persistent WebSocket to the cloud relay.
Buffers telemetry during disconnects and drains on reconnect.
"""

import asyncio
import json
import logging
import time

import socketio

from ..config import settings
from ..health.service import get_system_metrics

log = logging.getLogger(__name__)

# Persistent state
_sio: socketio.AsyncClient | None = None
_connected: bool = False
_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
_start_time: float = 0
_last_forward: float = 0
_reconnect_attempts: int = 0
_heartbeat_task: asyncio.Task | None = None

HEALTH_HEARTBEAT_INTERVAL = 60  # seconds

# Task registry for health reporting
_task_status: dict = {"cloud_connector": {"status": "idle", "last_run": None}}


async def start_cloud_connector():
    """Background task started in main.py lifespan. No-op if cloud not configured."""
    global _sio, _connected, _start_time, _reconnect_attempts

    if not settings.cloud_url or not settings.cloud_token:
        log.info("Cloud connector disabled — set SPOREPRINT_CLOUD_URL and _TOKEN to enable")
        _task_status["cloud_connector"]["status"] = "disabled"
        return

    _start_time = time.time()
    _task_status["cloud_connector"]["status"] = "connecting"
    log.info("Cloud connector starting: %s", settings.cloud_url)

    _sio = socketio.AsyncClient(reconnection=False)

    @_sio.on("connect")
    async def on_connect():
        global _connected, _reconnect_attempts, _heartbeat_task
        _connected = True
        _reconnect_attempts = 0
        _task_status["cloud_connector"]["status"] = "connected"
        log.info("Cloud: connected to %s", settings.cloud_url)
        # Drain buffered telemetry
        drained = 0
        while not _queue.empty():
            try:
                item = _queue.get_nowait()
                await _sio.emit("telemetry", item)
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            log.info("Cloud: drained %d buffered messages", drained)
        # Start health heartbeat
        if _heartbeat_task is None or _heartbeat_task.done():
            _heartbeat_task = asyncio.create_task(_health_heartbeat_loop())

    @_sio.on("disconnect")
    async def on_disconnect():
        global _connected, _heartbeat_task
        if _heartbeat_task and not _heartbeat_task.done():
            _heartbeat_task.cancel()
        _connected = False
        _task_status["cloud_connector"]["status"] = "disconnected"
        log.warning("Cloud: disconnected")

    @_sio.on("command")
    async def on_command(data):
        """Receive a command from the cloud (relayed from a mobile app)."""
        try:
            tier = data.get("tier", "free")
            if tier != "premium":
                await _sio.emit("command_result", {
                    "id": data.get("id"),
                    "success": False,
                    "error": "Remote control requires premium tier",
                })
                return

            target = data.get("target")
            channel = data.get("channel")
            payload = data.get("payload", {})

            if not target:
                await _sio.emit("command_result", {
                    "id": data.get("id"),
                    "success": False,
                    "error": "Missing target",
                })
                return

            # Late import to avoid circular dependency with mqtt.py
            from ..mqtt import mqtt_publish

            if channel:
                topic = f"sporeprint/{target}/cmd/{channel}"
            else:
                topic = f"sporeprint/{target}/cmd/config"

            await mqtt_publish(topic, payload)

            await _sio.emit("command_result", {
                "id": data.get("id"),
                "success": True,
                "target": target,
                "channel": channel,
            })
            log.info("Cloud: executed command %s/%s from %s", target, channel, tier)

        except Exception as e:
            log.error("Cloud: command execution failed: %s", e)
            await _sio.emit("command_result", {
                "id": data.get("id"),
                "success": False,
                "error": str(e),
            })

    # Connection loop with exponential backoff
    while True:
        try:
            await _sio.connect(
                settings.cloud_url,
                auth={"token": settings.cloud_token, "device_id": settings.cloud_device_id},
                transports=["websocket"],
            )
            await _sio.wait()
        except asyncio.CancelledError:
            if _sio.connected:
                await _sio.disconnect()
            return
        except Exception as e:
            _reconnect_attempts += 1
            backoff = min(300, 5 * (2 ** min(_reconnect_attempts, 6)))
            log.warning("Cloud: connection failed (%s), retry in %ds", e, backoff)
            _task_status["cloud_connector"]["status"] = f"reconnecting ({backoff}s)"
            await asyncio.sleep(backoff)


async def forward_telemetry(node_id: str, payload: dict):
    """Called from mqtt.py after every telemetry ingest. Enqueues for cloud."""
    global _last_forward
    if not settings.cloud_url:
        return
    msg = {"node_id": node_id, "ts": time.time(), **payload}
    try:
        if _connected and _sio:
            await _sio.emit("telemetry", msg)
            _last_forward = time.time()
        else:
            _queue.put_nowait(msg)
    except asyncio.QueueFull:
        pass  # Drop oldest-style: queue is bounded
    except Exception as e:
        log.debug("Cloud: forward failed: %s", e)


async def forward_event(event_type: str, data: dict):
    """Forward session events, alerts, vision results to cloud."""
    if not settings.cloud_url or not _connected or not _sio:
        return
    try:
        await _sio.emit("event", {"type": event_type, "ts": time.time(), **data})
    except Exception as e:
        log.debug("Cloud: event forward failed: %s", e)


async def _health_heartbeat_loop():
    """Periodically push Pi system health to cloud so mobile app can see it remotely."""
    while _connected and _sio:
        try:
            system = await get_system_metrics()
            cloud = get_cloud_status()
            await _sio.emit("device_health", {
                "ts": time.time(),
                "device_id": settings.cloud_device_id,
                "system": system,
                "cloud": {
                    "connected": cloud["connected"],
                    "queue_depth": cloud["queue_depth"],
                    "uptime": cloud["uptime"],
                    "last_forward": cloud["last_forward"],
                    "reconnect_attempts": cloud["reconnect_attempts"],
                },
            })
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("Cloud: health heartbeat failed: %s", e)
        await asyncio.sleep(HEALTH_HEARTBEAT_INTERVAL)


def get_cloud_status() -> dict:
    """Returns connection status for health endpoint."""
    return {
        "configured": bool(settings.cloud_url),
        "connected": _connected,
        "cloud_url": settings.cloud_url or None,
        "device_id": settings.cloud_device_id or None,
        "queue_depth": _queue.qsize(),
        "last_forward": _last_forward or None,
        "uptime": time.time() - _start_time if _start_time else 0,
        "reconnect_attempts": _reconnect_attempts,
    }


def get_task_status() -> dict:
    """Return cloud connector task status for health reporting."""
    return dict(_task_status)
