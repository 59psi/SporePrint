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

# The cloud refuses a device whose owner has no active subscription
# (`subscription_required` at connect, 402 on REST ingest). That is a STANDING
# condition, not a transient fault: it clears only when the user resubscribes.
# Treated as a normal error it would mean a 5-minute reconnect storm forever
# against a relay that has storm detection, plus a telemetry queue quietly
# filling with frames that can never be delivered. So: back off far, say why,
# and stop buffering. The Pi itself keeps working — local control never depended
# on the cloud.
_subscription_blocked: bool = False
_SUBSCRIPTION_RETRY_SECONDS = 900  # 15 min — long enough not to be a storm,
                                   # short enough that resubscribing feels instant

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


def _is_subscription_refusal(exc: Exception) -> bool:
    """Did the cloud refuse us because the owner has no active subscription?

    python-socketio surfaces a server-side ConnectionRefusedError as a generic
    ConnectionError carrying the server's rejection payload in its message, so
    the reason is only available as text. Matching on the wire token the cloud
    sends (`subscription_required`) is the whole contract — keep it in step with
    cloud/app/relay/service.py.
    """
    return "subscription_required" in str(exc)


def _drop_undeliverable_queue() -> None:
    """Empty the forward queue when the cloud will not take our data.

    Buffering exists to survive a flaky link, not a lapsed subscription. Holding
    frames the cloud is refusing on principle just churns the drop-oldest ring
    for as long as the lapse lasts, and inflates the drop counter with data loss
    that never actually happened. The readings are still on the Pi — SQLite is
    the record; the cloud is a mirror.
    """
    global _queue_drops
    dropped = 0
    while True:
        try:
            _queue.get_nowait()
            dropped += 1
        except asyncio.QueueEmpty:
            break
    if dropped:
        log.info("Cloud: discarded %d queued frame(s) — cloud sync is paused, "
                 "readings remain in the Pi's local database", dropped)


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


# Allowlist of accepted target_kind values. The Pi resolves the hardware kinds
# to a concrete node_id at publish time via the hardware_nodes registry; the
# `system` and `automation` kinds are virtual targets the Pi server handles
# in-process (no MQTT publish). `system` covers automation pause/resume, session
# start/end, rule suspend, reboot, ota. `automation` carries the manual actuator
# override twin the cloud's POST /devices/{id}/actuator emits alongside the raw
# relay toggle, so the rules engine doesn't re-flip a manual change on its next
# tick. Mobile + cloud-relay + Pi all share this allowlist verbatim.
_VALID_TARGET_KINDS: set[str] = {"climate", "relay", "lighting", "camera", "system", "automation"}


async def _dispatch_system_command(channel: str | None, payload: dict) -> tuple[bool, str | None]:
    """Handle a chamber-level "system" command in-process — no MQTT publish.
    These are operations on the Pi server itself rather than a hardware node.

    Returns `(ok, error)`. The cloud `command_result` ack carries this back
    to the originating client.

    Channels:
      - automation: payload `{paused: bool}` — pause/resume the chamber's
        automation engine.
      - session_start / session_end: forward to the sessions service.
      - rule: payload `{rule_id: str, minutes: int}` — temporarily suspend
        a single automation rule.
      - reboot: schedule `systemctl reboot` after a 5s grace period so the
        ack flushes before the box goes down.
      - ota: schedule a firmware update (placeholder — Pi-side updater
        is the next piece).
    """
    if not channel:
        return False, "system command requires a channel"

    if channel == "automation":
        try:
            from ..automation.engine import set_paused
        except ImportError:
            return False, "automation engine not available on this Pi"
        try:
            await set_paused(bool(payload.get("paused", False)))
            return True, None
        except Exception as e:
            return False, f"automation toggle failed: {type(e).__name__}: {e}"

    if channel in ("session_start", "session_end"):
        try:
            from ..sessions.service import handle_remote_command
        except ImportError:
            return False, "sessions service not available on this Pi"
        try:
            await handle_remote_command(channel, payload)
            return True, None
        except Exception as e:
            return False, f"session command failed: {type(e).__name__}: {e}"

    if channel == "rule":
        try:
            from ..automation.engine import suspend_rule
            from ..automation.service import normalize_rule_id
        except ImportError:
            return False, "automation engine not available on this Pi"
        # Accept a numeric rule id in either wire form (int or numeric string) —
        # the automation CRUD paths use int, so normalising here keeps a single
        # caller from being stranded by a type mismatch across surfaces.
        rule_id = normalize_rule_id(payload.get("rule_id"))
        minutes = int(payload.get("minutes", 30))
        if rule_id is None:
            return False, "rule_suspend requires payload.rule_id"
        try:
            await suspend_rule(rule_id, minutes)
            return True, None
        except Exception as e:
            return False, f"rule suspend failed: {type(e).__name__}: {e}"

    if channel == "reboot":
        # Canonical grace-period reboot lives in system_actions (shared
        # with the LAN REST route) — the delay lets this ack flush before
        # the box goes down.
        from ..system_actions import schedule_reboot

        schedule_reboot()
        return True, None

    if channel == "ota":
        firmware_version = payload.get("firmware_version")
        channel_str = payload.get("channel", "stable")
        if not isinstance(firmware_version, str) or not firmware_version:
            return False, "ota requires payload.firmware_version"
        if channel_str not in ("stable", "beta", "dev"):
            return False, "ota channel must be one of: stable | beta | dev"

        # Run the full OTA pipeline (download → verify Ed25519 → stage →
        # promote → systemctl restart) as a background task so the
        # command_result ack flushes BEFORE we restart ourselves. Failure
        # state is persisted to /var/lib/sporeprint/ota/state.json — the
        # next-boot health check surfaces it. The running install is
        # never touched if any step fails.
        from . import ota as _ota
        log.info(
            "OTA pipeline starting: version=%s channel=%s",
            firmware_version, channel_str,
        )
        async def _ota_task():
            await asyncio.sleep(2)  # let the ack flush
            try:
                result = await _ota.run_ota_update(firmware_version, channel_str)
                if result.get("ok"):
                    log.info("OTA pipeline complete: %s", result)
                else:
                    log.error(
                        "OTA pipeline failed at step=%s: %s",
                        result.get("step"), result.get("error"),
                    )
            except Exception as e:
                log.exception("OTA pipeline raised: %s", e)
        asyncio.create_task(_ota_task())
        return True, None

    return False, f"Unknown system channel '{channel}'"


# Firmware actuator channel → the hardware node type that drives it. The cloud's
# POST /devices/{id}/actuator maps a design ActuatorKey to a firmware channel
# (mister→aux, fan→fae, light→white — see cloud devices/service.py
# ACTUATOR_CHANNELS) and emits the override twin carrying that firmware channel.
# We map it back to a node type so the override pins the SAME (node, channel) a
# rule's action targets. heater/pump are smart plugs the cloud rejects (400)
# before emit; any channel absent here has no relay/lighting node to pin, so the
# override degrades to a logged no-op rather than crashing.
_OVERRIDE_CHANNEL_NODE_TYPE: dict[str, str] = {
    "aux": "relay",
    "fae": "relay",
    "white": "lighting",
}


async def _dispatch_automation_command(channel: str | None, payload: dict) -> tuple[bool, str | None]:
    """Handle a chamber-level "automation" command in-process — no MQTT publish.

    The relay-path twin of the Pi's LAN ``POST/DELETE /api/automation/overrides``.
    The cloud's ``POST /devices/{id}/actuator`` emits this alongside the raw relay
    toggle so the rules engine leaves the manually-driven channel alone until the
    hold expires (set) or is cleared (release).

    Returns ``(ok, error)``; the cloud ``command_result`` ack carries this back.

    Channel:
      - override:
          set     payload ``{channel, state, duration_sec, expires_at}`` — register
                  an expiring manual override on the actuator's node/channel.
          release payload ``{channel, release: true}`` — clear it; automation resumes.
    """
    if channel != "override":
        return False, f"Unknown automation channel '{channel}'"

    fw_channel = payload.get("channel")
    if not isinstance(fw_channel, str) or not fw_channel:
        return False, "automation override requires payload.channel"

    node_type = _OVERRIDE_CHANNEL_NODE_TYPE.get(fw_channel)
    if node_type is None:
        # A smart-plug actuator (heater/pump) or a channel this Pi can't pin on a
        # relay/lighting node. Degrade honestly — log + no-op, never crash.
        log.warning(
            "Cloud: automation override for unmappable channel %r — no-op "
            "(not a relay/lighting channel)", fw_channel,
        )
        return False, f"Channel '{fw_channel}' maps to no relay/lighting node — override not registered"

    node_id = await _resolve_node_id_by_type(node_type)
    if not node_id:
        log.warning(
            "Cloud: automation override for %r — no registered %s node — no-op",
            fw_channel, node_type,
        )
        return False, f"No registered {node_type} node to override"

    # Reuse the engine's override API — the exact mechanism the LAN UI's
    # /api/automation/overrides endpoint and suspend_rule already drive.
    from ..automation.engine import clear_override, set_override
    from ..automation.models import ManualOverride

    if payload.get("release"):
        await clear_override(node_id, fw_channel)
        log.info("Cloud: cleared manual override %s:%s", node_id, fw_channel)
        return True, None

    # set — pin the channel out of automation's reach until it expires. The cloud
    # sends an absolute `expires_at`; fall back to duration-from-now, then to None
    # (ManualOverride clamps None / over-long to its 24h TTL ceiling, so a hold
    # can never go sticky-forever).
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        duration = payload.get("duration_sec")
        expires_at = (
            time.time() + duration
            if isinstance(duration, (int, float)) and not isinstance(duration, bool)
            else None
        )
    state = payload.get("state")
    await set_override(ManualOverride(
        target=node_id,
        channel=fw_channel,
        locked=True,
        reason=f"cloud manual override ({fw_channel}={state})" if state else "cloud manual override",
        expires_at=expires_at,
    ))
    log.info(
        "Cloud: registered manual override %s:%s (state=%s expires_at=%s)",
        node_id, fw_channel, state, expires_at,
    )
    return True, None


async def _resolve_node_id_by_type(node_type: str) -> str | None:
    """Pick the chamber's hardware node of the given type. Most chambers
    have exactly one of each kind; we pick the most-recently-seen if
    multiple are registered. Returns None when no matching node exists,
    in which case the command is rejected upstream.

    v4.2: combined firmware-v2 nodes report a single `node_type` (their
    actuator personality) plus a `roles` JSON list of every capability —
    e.g. a sensors+relay node has node_type='relay', roles=["climate",
    "relay"]. The roles match makes climate-targeted commands reach it.
    """
    from ..db import get_db
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT node_id FROM hardware_nodes
               WHERE node_type = ?
                  OR EXISTS (SELECT 1 FROM json_each(hardware_nodes.roles)
                             WHERE json_each.value = ?)
               ORDER BY last_seen DESC LIMIT 1""",
            (node_type, node_type),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return row["node_id"] if hasattr(row, "keys") else row[0]


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


async def handle_cloud_command(sio, data):
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

    `sio` is the connected socket client every `command_result` ack is
    emitted on — passed in (rather than read from the module global) so the
    gate is importable and frame-testable with a stub client.
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
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": f"Signature check failed: {reason}",
                "reject_reason": category,
            })
            return

        tier = data.get("tier", "free")
        if tier != "premium":
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": "Remote control requires premium tier",
            })
            return

        if not command_id or not isinstance(command_id, str):
            await sio.emit("command_result", {
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
            await sio.emit("command_result", {
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

        # v3.4.x coordinated wire shape: every command frame carries
        # `{device_id, target_kind, channel, payload}`. mobile, cloud
        # relay, and Pi all speak this shape — no translation anywhere.
        # The Pi resolves `target_kind` → MQTT node_id at publish time
        # via the hardware_nodes registry (internal data lookup, not
        # cross-shape mapping). `target_kind == "system"` is a Pi-
        # internal pseudo-target for chamber-level commands handled by
        # the Pi server itself (automation, session, rule, reboot,
        # ota), routed in-process rather than to MQTT.
        target_kind = data.get("target_kind")
        channel = data.get("channel")
        payload = data.get("payload", {})

        if target_kind not in _VALID_TARGET_KINDS or (channel is not None and not _is_safe_channel(channel)):
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": f"Invalid target_kind or channel (target_kind={target_kind!r})",
            })
            return

        # Resolve target_kind → MQTT node_id. "system" and "automation" are
        # virtual in-process targets — no hardware node, no MQTT publish.
        if target_kind in ("system", "automation"):
            target = target_kind
        else:
            target = await _resolve_node_id_by_type(target_kind)
            if not target:
                await sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": f"No registered {target_kind} node",
                })
                return
            # Sanity check the resolved node id against the safety regex.
            if not _is_safe_target(target):
                await sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Resolved node id failed safety check",
                })
                return

        # `system` / `automation` skip the registered-target check — they're
        # Pi-internal virtual targets, not hardware_nodes rows. The
        # downstream MQTT publish path also treats them specially
        # (see below).
        if target not in ("system", "automation") and not await _target_is_registered(target):
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": f"Unknown target '{target}'",
            })
            return

        # Dispatch:
        #   - target == "system"     → in-process system handler
        #     (automation pause/resume, session start/end, rule
        #     suspend, reboot, ota). No MQTT publish.
        #   - target == "automation" → in-process manual-override handler
        #     (the /actuator override twin). No MQTT publish.
        #   - hardware target        → MQTT publish to
        #     `sporeprint/{node_id}/cmd/{channel}` per the existing
        #     contract.
        if target == "system":
            ok, err = await _dispatch_system_command(channel, payload)
            await sio.emit("command_result", {
                "id": command_id,
                "success": ok,
                "target_kind": target_kind,
                "channel": channel,
                "error": err,
            })
            log.info(
                "Cloud: %s system command %s from %s",
                "executed" if ok else "rejected", channel, tier,
            )
        elif target == "automation":
            ok, err = await _dispatch_automation_command(channel, payload)
            await sio.emit("command_result", {
                "id": command_id,
                "success": ok,
                "target_kind": target_kind,
                "channel": channel,
                "error": err,
            })
            log.info(
                "Cloud: %s automation command %s from %s",
                "executed" if ok else "rejected", channel, tier,
            )
        else:
            # Late import to avoid circular dependency with mqtt.py
            from ..mqtt import mqtt_publish

            if channel:
                topic = f"sporeprint/{target}/cmd/{channel}"
            else:
                topic = f"sporeprint/{target}/cmd/config"

            published = await mqtt_publish(topic, payload)

            await sio.emit("command_result", {
                "id": command_id,
                "success": bool(published),
                "target_kind": target_kind,
                "target": target,
                "channel": channel,
                "error": None if published else "mqtt_publish failed (broker disconnected?)",
            })
            log.info(
                "Cloud: %s command %s/%s/%s from %s",
                "executed" if published else "attempted",
                target_kind, target, channel, tier,
            )

    except Exception as e:
        log.error("Cloud: command execution failed: %s", e)
        await sio.emit("command_result", {
            "id": command_id,
            "success": False,
            "error": str(e),
        })


async def start_cloud_connector():
    """Background task started in main.py lifespan. No-op if cloud not configured."""
    global _sio, _connected, _start_time, _reconnect_attempts, _subscription_blocked

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

    # v4.1 — register the integrations RPC handler so cloud-web can read
    # this Pi's /api/integrations state through the relay.
    from . import integrations_proxy as _integrations_proxy
    _integrations_proxy.attach(_sio)

    @_sio.on("connect")
    async def on_connect():
        global _connected, _reconnect_attempts, _heartbeat_task, _subscription_blocked
        _connected = True
        _reconnect_attempts = 0
        # A successful connect means the cloud accepted us — the subscription is
        # live again (or never lapsed). Resume buffering.
        if _subscription_blocked:
            _subscription_blocked = False
            log.info("Cloud: subscription active again — cloud sync resumed")
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
        # Thin socket wrapper — the whole security gate lives in the importable
        # module-level handle_cloud_command so it can be frame-tested directly
        # (the nested closure was untestable). Pass the live client so every
        # command_result ack goes back over the same socket.
        await handle_cloud_command(_sio, data)

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
            if _is_subscription_refusal(e):
                # Not a fault — the cloud is correctly refusing an unsubscribed
                # account. Retrying hard would achieve nothing but noise.
                _subscription_blocked = True
                _drop_undeliverable_queue()
                log.warning(
                    "Cloud: subscription required — cloud sync paused (local control "
                    "is unaffected). Rechecking every %ds; resubscribe to resume.",
                    _SUBSCRIPTION_RETRY_SECONDS,
                )
                _task_status["cloud_connector"]["status"] = "paused — subscription required"
                await asyncio.sleep(_SUBSCRIPTION_RETRY_SECONDS)
                continue

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
    if _subscription_blocked:
        # The cloud is refusing this account's data. Queueing it would fill the
        # ring with frames that can never be delivered. SQLite already has them.
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
    """Forward session events, alerts, vision results to cloud.

    `ota_step` rides its own Socket.IO channel so the cloud relay can persist
    pipeline progress into `ota_progress_events`. Everything else uses the
    legacy `event` envelope so existing push/escalation handlers fire unchanged.
    """
    if not settings.cloud_url or not _connected or not _sio:
        return
    try:
        if event_type == "ota_step":
            await _sio.emit("ota_step", {"ts": time.time(), **data})
        else:
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
