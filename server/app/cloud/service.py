"""Cloud connector: pushes telemetry upstream and receives remote commands.

Opt-in — inactive unless SPOREPRINT_CLOUD_URL and SPOREPRINT_CLOUD_TOKEN are set.
Uses python-socketio AsyncClient to maintain a persistent WebSocket to the cloud relay.
Buffers telemetry during disconnects and drains on reconnect.
"""

import asyncio
import json
import logging
import time
from collections import OrderedDict

import socketio

from ..config import settings
from ..health.service import get_system_metrics
from .signing import verify_frame

log = logging.getLogger(__name__)

# Persistent state
_sio: socketio.AsyncClient | None = None
_connected: bool = False
_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
_start_time: float = 0
_last_forward: float = 0
_reconnect_attempts: int = 0
_heartbeat_task: asyncio.Task | None = None
_queue_drops: int = 0

# Replayed-command protection. Cache is a real FIFO/LRU — popitem(last=False)
# evicts the oldest-inserted id. A burst of >1024 distinct ids no longer lets
# an arbitrary earlier id be resurrected (which the prior set.pop() allowed).
#
# v3.3.3 — also write-through to the SQLite `cloud_command_replay` table so
# a Pi restart inside the 30s replay window doesn't re-open the window.
# Rehydration runs once at startup and loads entries ≤60s old.
_seen_command_ids: OrderedDict[str, None] = OrderedDict()
_COMMAND_ID_CACHE_CAP = 1024
_REPLAY_WINDOW_SECONDS = 60  # keep entries 2× the sign window for safety

# Guards concurrent mutation of _seen_command_ids. The replay-cache rehydrator
# populates it at startup while the command handler may already be accepting
# frames, and the popitem eviction sweep can race with a concurrent insert.
_replay_lock = asyncio.Lock()

HEALTH_HEARTBEAT_INTERVAL = 60  # seconds

# Task registry for health reporting
_task_status: dict = {"cloud_connector": {"status": "idle", "last_run": None}}


async def _rehydrate_replay_cache() -> int:
    """Load persisted command ids from SQLite into the in-memory FIFO.

    Called once at connector startup. Entries older than ``_REPLAY_WINDOW_SECONDS``
    are pruned from disk. Returns the number of entries loaded.
    """
    from ..db import get_db  # lazy import — avoid circular with main.py lifespan

    now = time.time()
    loaded = 0
    try:
        async with get_db() as db:
            await db.execute(
                "DELETE FROM cloud_command_replay WHERE received_at < ?",
                (now - _REPLAY_WINDOW_SECONDS,),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT command_id FROM cloud_command_replay ORDER BY received_at ASC"
            )
            rows = await cursor.fetchall()
        async with _replay_lock:
            for row in rows:
                cid = row["command_id"]
                _seen_command_ids[cid] = None
                loaded += 1
            # Trim to cap — should be a no-op unless the persistent store
            # exceeded _COMMAND_ID_CACHE_CAP during the last session.
            while len(_seen_command_ids) > _COMMAND_ID_CACHE_CAP:
                _seen_command_ids.popitem(last=False)
    except Exception as e:
        log.warning("Cloud: replay cache rehydrate failed: %s", e)
    return loaded


async def _persist_replay_id(command_id: str) -> None:
    """Persist an accepted command id for replay-cache rehydrate on restart.

    v3.3.4 — also prunes entries older than 2× ``_REPLAY_WINDOW_SECONDS``
    in the same transaction so the table stays bounded. Without this a
    busy Pi accumulates rows forever (the only cleanup was on connector
    start). The prune runs every accepted command which keeps the table
    size O(replay-window × command-rate), typically under 100 rows.
    """
    from ..db import get_db

    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO cloud_command_replay (command_id, received_at) VALUES (?, ?)",
            (command_id, now),
        )
        # Retention: drop anything past 2× the replay window. The rehydrate
        # path already prunes on boot; this keeps steady-state bounded.
        await db.execute(
            "DELETE FROM cloud_command_replay WHERE received_at < ?",
            (now - (_REPLAY_WINDOW_SECONDS * 2),),
        )
        await db.commit()


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

    # v3.3.3 — rehydrate the replay cache from SQLite so a Pi restart inside
    # the sign window still rejects a replayed command id.
    loaded = await _rehydrate_replay_cache()
    if loaded:
        log.info("Cloud: replay cache rehydrated with %d recent command ids", loaded)

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
        """Receive a command from the cloud (relayed from a mobile app).

        Every frame must be signed with HMAC-SHA256 over the canonical
        form of the frame using the Pi's `cloud_token` as the key. An
        unsigned or tampered frame is rejected before any other check —
        signature verification sits outside the tier/target checks so a
        compromised relay cannot reach `mqtt_publish` even with a valid
        tier string.

        Additional defense-in-depth layers applied after signature passes:
        - tier must be 'premium'
        - command id must be present and not replayed (in-memory FIFO cache,
          1024 entries, O(1) OrderedDict with popitem(last=False) eviction —
          oldest-inserted id is always the one that gets evicted)
        - target must match a registered hardware node OR smart plug
        - channel must match the safe-charset regex — no injection into topic
        """
        command_id = data.get("id")
        try:
            ok, reason = verify_frame(settings.cloud_token, data)
            if not ok:
                # v3.3.10 (P2-10 / E-2): classify rejection so cloud can tag the
                # SLO sample. Clock-skew rejection is operationally different
                # from a signature mismatch or a replay attack — the former
                # means "Pi's clock has drifted past the 30s window" and the
                # fix is NTP/chrony, not redeploying the cloud. A signature
                # mismatch after the Pi's .env has the right cloud_token is a
                # signing-contract drift between cloud + Pi — a release bug.
                category = (
                    "clock_skew" if reason and "replay window" in reason
                    else "signature_mismatch" if reason and "signature" in reason
                    else "bad_frame"
                )
                log.warning(
                    "Cloud: rejecting command %s — %s (category=%s)",
                    command_id, reason, category,
                )
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": f"Signature check failed: {reason}",
                    "reject_reason": category,
                })
                return

            tier = data.get("tier", "free")
            if tier != "premium":
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Remote control requires premium tier",
                })
                return

            if not command_id or not isinstance(command_id, str):
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Missing or invalid command id",
                })
                return

            # Atomic check-and-insert under the replay lock so two concurrent
            # frames carrying the same command_id can't both pass the dedup
            # test. Without the lock, both would see "not in cache" and both
            # would proceed to execute the command. We do the socket emit
            # OUTSIDE the lock to avoid holding it across a network await.
            already_seen = False
            async with _replay_lock:
                if command_id in _seen_command_ids:
                    already_seen = True
                else:
                    _seen_command_ids[command_id] = None
                    # Evict the OLDEST entry (FIFO) when the cache is over
                    # capacity. OrderedDict.popitem(last=False) is O(1) and —
                    # unlike set.pop() — removes the insertion-order-oldest,
                    # not an arbitrary element.
                    while len(_seen_command_ids) > _COMMAND_ID_CACHE_CAP:
                        _seen_command_ids.popitem(last=False)
            if already_seen:
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Replayed command id",
                })
                return
            # v3.3.3 — persist so a restart inside the replay window still
            # rejects the replay. Failure to persist is logged but does not
            # reject the command; replay protection in that window falls back
            # to the in-memory cache which is always consistent.
            try:
                await _persist_replay_id(command_id)
            except Exception as e:
                log.warning("Cloud: replay cache persist failed: %s", e)

            target = data.get("target")
            channel = data.get("channel")
            payload = data.get("payload", {})

            if not _is_safe_target(target) or (channel is not None and not _is_safe_channel(channel)):
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Invalid target or channel",
                })
                return

            if not await _target_is_registered(target):
                await _sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": f"Unknown target '{target}'",
                })
                return

            # Late import to avoid circular dependency with mqtt.py
            from ..mqtt import mqtt_publish

            if channel:
                topic = f"sporeprint/{target}/cmd/{channel}"
            else:
                topic = f"sporeprint/{target}/cmd/config"

            published = await mqtt_publish(topic, payload)

            await _sio.emit("command_result", {
                "id": command_id,
                "success": bool(published),
                "target": target,
                "channel": channel,
                "error": None if published else "mqtt_publish failed (broker disconnected?)",
            })
            log.info("Cloud: %s command %s/%s from %s",
                     "executed" if published else "attempted", target, channel, tier)

        except Exception as e:
            log.error("Cloud: command execution failed: %s", e)
            await _sio.emit("command_result", {
                "id": command_id,
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
    global _last_forward, _queue_drops
    if not settings.cloud_url:
        return
    msg = {"node_id": node_id, "ts": time.time(), **payload}
    try:
        if _connected and _sio:
            await _sio.emit("telemetry", msg)
            _last_forward = time.time()
        else:
            try:
                _queue.put_nowait(msg)
            except asyncio.QueueFull:
                # True drop-oldest: evict the stalest item, enqueue the new one.
                try:
                    _queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    _queue.put_nowait(msg)
                    _queue_drops += 1
                    if _queue_drops == 1 or _queue_drops % 100 == 0:
                        log.warning(
                            "Cloud: queue overflow, dropped oldest (total drops=%d)",
                            _queue_drops,
                        )
                except asyncio.QueueFull:
                    pass
    except Exception as e:
        log.debug("Cloud: forward failed: %s", e)


async def forward_component_health(node_id: str, data: dict):
    """Forward ESP32 component health data to cloud relay."""
    if not settings.cloud_url or not _connected or not _sio:
        return
    try:
        await _sio.emit("component_health", {"node_id": node_id, "ts": time.time(), **data})
    except Exception as e:
        log.debug("Cloud: component health forward failed: %s", e)


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
        "queue_drops": _queue_drops,
        "last_forward": _last_forward or None,
        "uptime": time.time() - _start_time if _start_time else 0,
        "reconnect_attempts": _reconnect_attempts,
    }


def get_task_status() -> dict:
    """Return cloud connector task status for health reporting."""
    return dict(_task_status)


import re as _re
_SAFE_ID_RE = _re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _is_safe_target(value) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID_RE.match(value))


def _is_safe_channel(value) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID_RE.match(value))


async def _target_is_registered(target: str) -> bool:
    """A cloud command can only target a known hardware node or smart plug."""
    from ..db import get_db
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM hardware_nodes WHERE node_id = ? LIMIT 1", (target,)
        )
        if await cursor.fetchone():
            return True
        cursor = await db.execute(
            "SELECT 1 FROM smart_plugs WHERE plug_id = ? LIMIT 1", (target,)
        )
        return (await cursor.fetchone()) is not None


# ─── Pairing / cloud-configure helpers ───────────────────────────

# The `.env` lives next to the `server/` package root, not next to whatever the
# systemd unit chose as CWD (which is often `/`). Resolve from this file so the
# path is stable regardless of invocation context.
#  cloud/service.py -> app/ -> server/ -> repo-root
from pathlib import Path as _Path
_ENV_PATH = _Path(__file__).resolve().parents[2] / ".env"


def env_path() -> _Path:
    return _ENV_PATH


_FORBIDDEN_VALUE_CHARS = ("\n", "\r", "=", "\x00")


def _validate_env_value(key: str, value: str) -> None:
    for ch in _FORBIDDEN_VALUE_CHARS:
        if ch in value:
            raise ValueError(f"Invalid character in {key}")


def write_cloud_env(updates: dict) -> _Path:
    """Atomically merge `updates` into .env. Rejects newline-injection values."""
    import os
    import tempfile

    path = env_path()
    for key, value in updates.items():
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        _validate_env_value(key, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    env_content = path.read_text() if path.exists() else ""
    lines = env_content.splitlines()
    seen: set[str] = set()
    merged: list[str] = []
    for line in lines:
        matched = False
        for key, value in updates.items():
            if line.startswith(f"{key}="):
                merged.append(f"{key}={value}")
                seen.add(key)
                matched = True
                break
        if not matched:
            merged.append(line)
    for key, value in updates.items():
        if key not in seen:
            merged.append(f"{key}={value}")

    body = "\n".join(merged).rstrip("\n") + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
