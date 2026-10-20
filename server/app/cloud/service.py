"""Cloud connector: pushes telemetry upstream and receives remote commands.

Opt-in — inactive unless SPOREPRINT_CLOUD_URL, SPOREPRINT_CLOUD_TOKEN and
SPOREPRINT_CLOUD_DEVICE_ID are set (pairing writes all three).
Uses python-socketio AsyncClient to maintain a persistent WebSocket to the cloud relay.
Buffers telemetry during disconnects and drains it on reconnect as replayed
history; a frame counts as delivered only once the relay acknowledges it.
"""

import asyncio
import ipaddress
import itertools
import json
import logging
import math
import os
import tempfile
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import Path as _Path
from urllib.parse import urlparse

import socketio
from pydantic import ValidationError

from ..automation.models import ManualOverride
from ..config import settings
from ..db import get_db
from ..health.service import get_system_metrics
from ..integrations import _health_sweeper
from ..integrations._actions import LAX_BOOL
from ..node_ids import is_safe_id
from ..system_actions import reboot_unsupported_reason, schedule_reboot
from . import ota as _ota
from .signing import verify_frame
from .version import server_version

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

# The relay refuses a device at connect for two STANDING reasons (the reason
# string it raises ConnectionRefusedError with, cloud/app/relay/service.py):
# the owner has no active subscription, or the device token is not valid (the
# device was deleted, revoked or its token rotated). Neither is a transient
# fault: one clears when the user resubscribes, the other when the Pi is
# re-paired. Treated as a normal error each would mean a 5-minute reconnect
# storm forever against a relay that has storm detection, plus a telemetry
# queue quietly filling with frames that can never be delivered. So: back off
# far, say why, and stop buffering. The Pi itself keeps working — local
# control never depended on the cloud.
_STANDING_REFUSALS: dict[str, str] = {
    "subscription_required": "paused — subscription required",
    "Invalid device token": "unauthorized — re-pair this Pi with the cloud",
}
_standing_refusal: str | None = None  # the relay's reason, while it stands
_STANDING_REFUSAL_RETRY_SECONDS = 900  # 15 min — long enough not to be a storm,
                                       # short enough that resubscribing feels instant
# "Invalid device token" stands only once it repeats on consecutive attempts;
# until then it is retried like any other failure, so one wrong answer can't
# silence the Pi for 15 minutes. (A relay that could not check the token or
# read the owner's subscription at all, its database unreachable, answers
# service_unavailable: an ordinary failure, like every reason not listed
# above.)
_TOKEN_REFUSALS_TO_STAND = 3
_token_refusals = 0
# python-socketio reports a refused connect as a generic ConnectionError; the
# relay's reason arrives only as the `connect_error` event's payload, kept
# here for the attempt that just failed.
_connect_error: str | None = None

# How long connect() waits for the relay to accept the namespace. The relay
# checks the device token and the owner's tier (Supabase round trips) before
# it answers; python-socketio's default of 1 s fails every attempt whenever
# that takes longer.
_CONNECT_WAIT_TIMEOUT_SECONDS = 10

# Telemetry handed to the socket but not yet acknowledged by the relay, by
# send sequence: (sent_at, frame). A socket that died without a FIN keeps
# accepting emits until the ping timeout notices (~45 s), and those frames
# never arrive; the unacknowledged ones go back into the queue on disconnect.
# A frame unacknowledged for longer than _INFLIGHT_MAX_AGE_SECONDS was sent
# over a live socket and the relay did not ack it (it never will), so it is
# dropped from tracking instead of being resent forever.
_inflight: OrderedDict[int, tuple[float, dict]] = OrderedDict()
_inflight_seq = itertools.count()
_INFLIGHT_MAX_AGE_SECONDS = 120.0

# A confirmed event (forward_event(confirm=True)) waits this long for the
# relay's acknowledgement before it counts as undelivered.
_EVENT_ACK_TIMEOUT_SECONDS = 10.0

# The relay caches the integrations snapshot for 5 minutes; the heartbeat
# re-pushes it inside that window so the fleet view never goes blank.
_INTEGRATIONS_SNAPSHOT_INTERVAL_SECONDS = 240
_last_snapshot_push: float = 0

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

# A session shorter than this that the server (or network) ends is treated as
# a failed attempt: backoff grows instead of reconnecting ~1 s later forever
# (relay kick loops, two Pis sharing a token kicking each other, ...).
_STABLE_SESSION_SECONDS = 60

# Set by request_reconnect() to cut a retry/backoff sleep short.
_wake_event: asyncio.Event | None = None
_connector_running: bool = False

# The single in-flight OTA pipeline (kept referenced so it can't be GC'd
# mid-run, and so a second OTA command is refused while one runs).
_ota_task: asyncio.Task | None = None

# Task registry for health reporting
_task_status: dict = {"cloud_connector": {"status": "idle", "last_run": None}}


def _connect_error_reason(*args) -> str | None:
    """The relay's refusal reason from a `connect_error` event payload.

    The relay's ConnectionRefusedError("<reason>") arrives as
    ``{"message": "<reason>"}``; a transport-level failure as a plain string.
    """
    data = args[0] if args else None
    if isinstance(data, dict):
        data = data.get("message")
    return data if isinstance(data, str) else None


def _standing_refusal_of(exc: Exception) -> str | None:
    """The standing refusal behind a failed connect, or None for a transient fault.

    python-socketio raises a generic ConnectionError ("One or more namespaces
    failed to connect") for a refused connect and delivers the relay's reason
    only through `connect_error`, captured in ``_connect_error``. The reason
    strings are the contract — keep them in step with
    cloud/app/relay/service.py. An exception text that carries a reason is
    accepted too, for a client library that reports it there.
    """
    for reason in _STANDING_REFUSALS:
        if _connect_error == reason or (_connect_error is None and reason in str(exc)):
            return reason
    return None


def _drop_undeliverable_queue() -> None:
    """Empty the forward queue when the cloud will not take our data.

    Buffering exists to survive a flaky link, not a standing refusal (a lapsed
    subscription, a revoked device). Holding frames the cloud is refusing on
    principle just churns the drop-oldest ring for as long as the refusal
    lasts, and inflates the drop counter with data loss that never actually
    happened. The readings are still on the Pi — SQLite is the record; the
    cloud is a mirror.
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


def _enqueue(msg: dict) -> None:
    """Buffer a telemetry frame for the next connect (drop-oldest when full)."""
    global _queue_drops
    try:
        _queue.put_nowait(msg)
        return
    except asyncio.QueueFull:
        pass
    # True drop-oldest: evict the stalest item, enqueue the new one.
    try:
        _queue.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        _queue.put_nowait(msg)
    except asyncio.QueueFull:
        return
    _queue_drops += 1
    if _queue_drops == 1 or _queue_drops % 100 == 0:
        log.warning(
            "Cloud: queue overflow, dropped oldest (total drops=%d)",
            _queue_drops,
        )


def _prune_inflight(now: float) -> None:
    """Forget frames the relay never acknowledged within the max age."""
    while _inflight:
        seq, (sent_at, _msg) = next(iter(_inflight.items()))
        if now - sent_at <= _INFLIGHT_MAX_AGE_SECONDS and len(_inflight) <= _queue.maxsize:
            return
        _inflight.pop(seq, None)


async def _emit_telemetry(msg: dict) -> None:
    """Hand a telemetry frame to the socket, tracked until the relay acks it."""
    now = time.time()
    seq = next(_inflight_seq)
    _inflight[seq] = (now, msg)
    _prune_inflight(now)

    def _acked(*_args) -> None:
        global _last_forward
        if _inflight.pop(seq, None) is not None:
            _last_forward = time.time()

    try:
        await _sio.emit("telemetry", msg, callback=_acked)
    except Exception:
        _inflight.pop(seq, None)
        raise


def _requeue_unacked() -> int:
    """Move frames the relay never acknowledged back into the queue.

    Called when the socket drops: they were sent into a dead connection (or
    their ack was lost with it) and go out again, as replayed history, on the
    next connect. A rare duplicate is the price of not losing them.
    """
    now = time.time()
    frames = [msg for sent_at, msg in _inflight.values()
              if now - sent_at <= _INFLIGHT_MAX_AGE_SECONDS]
    _inflight.clear()
    for msg in frames:
        _enqueue(msg)
    return len(frames)


async def _drain_queue() -> int:
    """Send the frames buffered while the link was down; returns how many.

    They go out flagged ``"replay": true`` (the flag the Pi already puts on a
    node's own late frames): the relay then stores each at its own ``ts`` and
    neither broadcasts it as the current reading nor runs alert rules on it,
    so hours-old values never show as live or page anyone.
    """
    drained = 0
    while _connected and _sio:
        try:
            item = _queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        try:
            await _emit_telemetry({**item, "replay": True})
        except Exception as e:
            _enqueue(item)
            log.debug("Cloud: buffered frame not sent: %s", e)
            break
        drained += 1
    return drained


async def _rehydrate_replay_cache() -> int:
    """Load persisted command ids from SQLite into the in-memory FIFO.

    Called once at connector startup. Entries older than ``_REPLAY_WINDOW_SECONDS``
    are pruned from disk. Returns the number of entries loaded.
    """
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
      - reboot: `systemctl reboot` after a 5 s grace period so the ack flushes
        before the box goes down; refused before the ack where the host
        cannot be rebooted from here (the Docker install).
      - ota: self-update the Pi server (cloud/ota.py): the signed release
        manifest is verified against the locally pinned key, then the bundle
        is downloaded, checked against it, staged, promoted and the service
        restarted. Refused before the ack on the Docker install, for another
        release channel, for a downgrade, and while an update is running.
    """
    if not channel:
        return False, "system command requires a channel"

    if channel == "automation":
        try:
            from ..automation.engine import set_paused
        except ImportError:
            return False, "automation engine not available on this Pi"
        try:
            # Lax: `bool("false")` is True — a plain cast would PAUSE
            # automation on {"paused": "false"}.
            paused = LAX_BOOL.validate_python(payload.get("paused", False))
        except ValidationError:
            return False, f"automation.paused must be a boolean, got {payload.get('paused')!r}"
        try:
            await set_paused(paused)
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
        # Refuse BEFORE acking when this process cannot reboot the host (the
        # Docker install has no sudo, no systemd and no host access): a
        # success ack followed by nothing would tell the operator it worked.
        unsupported = reboot_unsupported_reason()
        if unsupported:
            return False, unsupported
        # Canonical grace-period reboot lives in system_actions — the delay
        # lets this ack flush before the box goes down.
        schedule_reboot()
        return True, None

    if channel == "ota":
        firmware_version = payload.get("firmware_version")
        channel_str = payload.get("channel", "stable")
        if not isinstance(firmware_version, str) or not firmware_version:
            return False, "ota requires payload.firmware_version"
        if channel_str not in ("stable", "beta", "dev"):
            return False, "ota channel must be one of: stable | beta | dev"

        # Refuse BEFORE acking when the pipeline cannot possibly succeed, so
        # the cloud gets a failure instead of a success ack followed by
        # silence: unsupported install layout (Docker), bad version string,
        # a downgrade, or an OTA already running.
        unsupported = _ota.self_update_unsupported_reason()
        if unsupported:
            return False, unsupported
        invalid = _ota.validate_request(firmware_version, channel_str)
        if invalid:
            return False, invalid
        global _ota_task
        if _ota_task is not None and not _ota_task.done():
            return False, "an OTA update is already in progress"

        # Run the full OTA pipeline (download → verify Ed25519 → stage →
        # promote → systemctl restart) as a background task so the
        # command_result ack flushes BEFORE we restart ourselves. Failure
        # state is persisted to the OTA state.json and emitted as an
        # `ota_step: failed` event. The running install is never touched
        # if any step before promote fails.
        log.info(
            "OTA pipeline starting: version=%s channel=%s",
            firmware_version, channel_str,
        )

        async def _run_ota():
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

        _ota_task = asyncio.create_task(_run_ota())
        return True, None

    return False, f"Unknown system channel '{channel}'"


# Firmware actuator channel → the personality of the node bank that has it,
# for nodes that have not reported their channels yet (a node that has is
# matched on its own list). The cloud's POST /devices/{id}/actuator maps a
# design ActuatorKey to a firmware channel (mister→aux, fan→fae, light→white —
# see cloud devices/service.py ACTUATOR_CHANNELS) and sends the hardware
# command plus an override twin carrying that channel; both resolve through
# _fitting_nodes, so the override pins the SAME (node, channel) the command
# reached and a rule's action targets. heater/pump are smart plugs the cloud
# rejects (400) before emit.
_OVERRIDE_CHANNEL_NODE_TYPE: dict[str, str] = {
    "aux": "relay",
    "fae": "relay",
    "white": "lighting",
}

# Command suffixes addressed to the node itself, not to one of its channels
# (builder/service.py _HARDWARE_CONTRACT: cmd/config, cmd/scene, ...).
_NODE_COMMANDS = frozenset({"config", "scene", "coredump_ack", "ota_manifest"})


def _json_list(raw) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


async def _fitting_nodes(kind: str | None, channel: str | None) -> tuple[list[str], bool]:
    """Registered nodes a cloud command or override for ``channel`` may mean.

    Returns ``(node_ids, any_of_kind)``; the second is whether any node of
    ``kind`` is registered at all (for the error message).

    - ``kind`` (a hardware target_kind) is matched against the node's
      personality or its roles: a combined sensors+relay node reports
      node_type 'relay' and roles ['climate', 'relay']. An override has no
      kind (None).
    - A channel command fits a node whose reported channels list it. Channel
      names are bank-specific, so this finds the lighting node for 'white'
      even when the frame says target_kind 'relay' (older clouds send that).
      A node that has never reported its channels fits when it is of
      ``kind`` or of the channel's bank (_OVERRIDE_CHANNEL_NODE_TYPE).
    - A node-level command (no channel, cmd/config, cmd/scene) fits every
      node of ``kind``.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT node_id, node_type, roles, channels FROM hardware_nodes ORDER BY node_id"
        )
        rows = await cursor.fetchall()

    def is_kind(row, wanted: str | None) -> bool:
        return wanted is not None and (row["node_type"] == wanted or wanted in _json_list(row["roles"]))

    any_of_kind = any(is_kind(row, kind) for row in rows)
    if not channel or channel in _NODE_COMMANDS:
        return [row["node_id"] for row in rows if is_kind(row, kind)], any_of_kind
    bank = _OVERRIDE_CHANNEL_NODE_TYPE.get(channel)
    fits = []
    for row in rows:
        reported = _json_list(row["channels"])
        if channel in reported or (not reported and (is_kind(row, kind) or is_kind(row, bank))):
            fits.append(row["node_id"])
    return fits, any_of_kind


def _ambiguous(node_ids: list[str], channel: str | None) -> str:
    what = f"channel '{channel}'" if channel else "this command"
    return (
        f"Ambiguous target: {len(node_ids)} registered nodes have {what} "
        f"({', '.join(node_ids)}) — refusing to guess; control it from the Pi"
    )


async def _resolve_command_node(kind: str, channel: str | None) -> tuple[str | None, str | None]:
    """The one node a hardware cloud command addresses: ``(node_id, None)``,
    or ``(None, error)`` when none or several fit. The cloud frame names no
    node, so on a Pi with two relay nodes (two chambers, or two banks in one)
    it is refused rather than sent to whichever node reported last."""
    fits, any_of_kind = await _fitting_nodes(kind, channel)
    if len(fits) == 1:
        return fits[0], None
    if fits:
        return None, _ambiguous(fits, channel)
    if any_of_kind and channel and channel not in _NODE_COMMANDS:
        return None, f"No registered {kind} node has a '{channel}' channel"
    return None, f"No registered {kind} node"


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

    # The same resolution as the hardware command this override accompanies,
    # so the hold pins the node the command actually reached.
    fits, _ = await _fitting_nodes(None, fw_channel)
    if len(fits) > 1:
        log.warning("Cloud: automation override for %r — %d nodes have it — no-op",
                    fw_channel, len(fits))
        return False, _ambiguous(fits, fw_channel)
    if not fits:
        node_type = _OVERRIDE_CHANNEL_NODE_TYPE.get(fw_channel)
        if node_type is None:
            # A smart-plug actuator (heater/pump) or a channel no registered
            # relay/lighting node has. Degrade honestly — log + no-op, never crash.
            log.warning(
                "Cloud: automation override for unmappable channel %r — no-op "
                "(not a relay/lighting channel)", fw_channel,
            )
            return False, f"Channel '{fw_channel}' maps to no relay/lighting node — override not registered"
        log.warning(
            "Cloud: automation override for %r — no registered %s node — no-op",
            fw_channel, node_type,
        )
        return False, f"No registered {node_type} node to override"
    node_id = fits[0]

    # Reuse the engine's override API — the exact mechanism the LAN UI's
    # /api/automation/overrides endpoint and suspend_rule already drive. Late
    # import: the engine imports mqtt.py, which imports this module.
    from ..automation.engine import clear_override, set_override

    if payload.get("release"):
        await clear_override(node_id, fw_channel)
        log.info("Cloud: cleared manual override %s:%s", node_id, fw_channel)
        return True, None

    # set — pin the channel out of automation's reach until it expires. The hold
    # runs `duration_sec` from now on the Pi's own clock; the absolute
    # `expires_at` the cloud sends with it is read off the cloud's clock, which
    # a Pi with no battery-backed clock that booted without NTP can be hours
    # away from, so it is only the fallback. Then None (ManualOverride clamps
    # None / over-long to its 24h TTL ceiling, so a hold can never go
    # sticky-forever). A non-finite number (NaN / inf) is no expiry at all:
    # NaN compares false against every deadline, so it would never read as
    # expired.
    duration = payload.get("duration_sec")
    if _finite_number(duration):
        expires_at = time.time() + duration
    else:
        expires_at = payload.get("expires_at")
        if not _finite_number(expires_at):
            expires_at = None
    state = payload.get("state")
    await set_override(ManualOverride(
        target=node_id,
        channel=fw_channel,
        locked=True,
        reason=f"cloud manual override ({fw_channel}={state})" if state else "cloud manual override",
        expires_at=expires_at,
        # An ON pin ends when the node's own safety cutoff switches the
        # channel off (engine.end_on_hold_after_cutoff).
        held_state=state,
    ))
    log.info(
        "Cloud: registered manual override %s:%s (state=%s expires_at=%s)",
        node_id, fw_channel, state, expires_at,
    )
    return True, None


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


async def claim_replay_id(key: str) -> bool:
    """Record ``key`` as seen. False when it was seen already: a replay.

    The one replay gate for signed cloud frames: command ids and (namespaced
    by the caller) integrations request ids share this FIFO and the SQLite
    table that keeps the window shut across a restart. The check and the
    insert happen under one lock, so two concurrent frames carrying the same
    id can't both pass. Persisting is best effort: if it fails, the in-memory
    cache still rejects the replay until this process restarts.
    """
    async with _replay_lock:
        if key in _seen_command_ids:
            return False
        _seen_command_ids[key] = None
        # Evict the OLDEST entry (FIFO) when the cache is over capacity.
        # OrderedDict.popitem(last=False) is O(1) and — unlike set.pop() —
        # removes the insertion-order-oldest, not an arbitrary element.
        while len(_seen_command_ids) > _COMMAND_ID_CACHE_CAP:
            _seen_command_ids.popitem(last=False)
    try:
        await _persist_replay_id(key)
    except Exception as e:
        log.warning("Cloud: replay cache persist failed: %s", e)
    return True


async def _persist_replay_id(command_id: str) -> None:
    """Persist an accepted command id for replay-cache rehydrate on restart.

    v3.3.4 — also prunes entries older than 2× ``_REPLAY_WINDOW_SECONDS``
    in the same transaction so the table stays bounded. Without this a
    busy Pi accumulates rows forever (the only cleanup was on connector
    start). The prune runs every accepted command which keeps the table
    size O(replay-window × command-rate), typically under 100 rows.
    """
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

        # Atomic check-and-insert (claim_replay_id), written through to
        # SQLite so a restart inside the replay window still rejects it.
        if not await claim_replay_id(command_id):
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": "Replayed command id",
            })
            return

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

        if target_kind not in _VALID_TARGET_KINDS or (channel is not None and not is_safe_id(channel)):
            await sio.emit("command_result", {
                "id": command_id,
                "success": False,
                "error": f"Invalid target_kind or channel (target_kind={target_kind!r})",
            })
            return

        # Resolve target_kind + channel → the one MQTT node_id it addresses.
        # "system" and "automation" are virtual in-process targets — no
        # hardware node, no MQTT publish.
        if target_kind in ("system", "automation"):
            target = target_kind
        else:
            target, unresolved = await _resolve_command_node(target_kind, channel)
            if not target:
                await sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": unresolved,
                })
                return
            # Sanity check the resolved node id against the safety regex.
            if not is_safe_id(target):
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
            # A node drops any body that is not a JSON object.
            if not isinstance(payload, dict):
                await sio.emit("command_result", {
                    "id": command_id,
                    "success": False,
                    "error": "Command payload must be a JSON object",
                })
                return
            # The one node-command publisher (topic, OFF without pwm/level,
            # and the automation bookkeeping every non-automation publish
            # owes the engine). Late import: hardware.service imports
            # mqtt.py, which imports this module at top level.
            from ..hardware.service import send_command

            _topic, published = await send_command(target, {**payload, "channel": channel})

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


def cloud_url_transport_ok(url: str) -> bool:
    """May the device token be sent to ``url``?

    The token authenticates the socket AND is the HMAC key for every signed
    command frame, so it must never cross the internet in plaintext:
    https/wss always; plain http/ws only to a loopback, private-range or
    mDNS (``.local``) host — a dev relay on the operator's own LAN.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme in ("https", "wss"):
        return bool(parsed.hostname)
    if parsed.scheme not in ("http", "ws"):
        return False
    host = parsed.hostname or ""
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _backoff_seconds(attempts: int) -> int:
    return min(300, 5 * (2 ** min(attempts, 6)))


async def _backoff_sleep(seconds: float) -> None:
    """Retry sleep that request_reconnect() can cut short."""
    event = _wake_event
    if event is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        event.clear()


def request_reconnect() -> str:
    """Wake the connector out of its retry/backoff sleep.

    The retry uses the credentials pairing last saved (cloud.env), not the
    ones this process started with. Returns ``"reconnecting"`` when a retry
    was triggered, ``"connected"`` when already connected (nothing to do), or
    ``"restart_required"`` when the connector is not running in this process
    (e.g. credentials were paired after boot).
    """
    if not _connector_running:
        return "restart_required"
    load_persisted_cloud_credentials()
    if _connected:
        return "connected"
    if _wake_event is not None:
        _wake_event.set()
    return "reconnecting"


async def apply_paired_credentials() -> bool:
    """Make credentials pairing just saved (cloud.env) take effect now.

    Returns True when a running connector will use them: the live session,
    which authenticated with the old token, is closed and the retry sleep cut
    short, so the connector reconnects with the new token at once (connect()
    reads settings on every attempt). Without this a re-paired or
    token-rotated Pi kept retrying its dead token until a restart. False when
    no connector runs in this process (the Pi was unpaired at boot): a
    restart starts it.
    """
    global _token_refusals
    load_persisted_cloud_credentials()
    _token_refusals = 0  # refusals of the old token say nothing about the new one
    if not _connector_running:
        return False
    if _sio is not None and _sio.connected:
        try:
            await _sio.disconnect()
        except Exception as e:  # noqa: BLE001 — the wake below still retries
            log.warning("Cloud: closing the old session failed: %s", e)
    if _wake_event is not None:
        _wake_event.set()
    return True


# Awaited on every (re)connect, after the buffered telemetry drains. Modules
# that must catch the cloud up after a gap register here (app.cloud.session_sync)
# instead of this module importing them.
ConnectListener = Callable[[], Awaitable[None]]
_connect_listeners: list[ConnectListener] = []


def add_connect_listener(listener: ConnectListener) -> None:
    """Register `listener` to run on every cloud connect (idempotent)."""
    if listener not in _connect_listeners:
        _connect_listeners.append(listener)


async def _run_connect_listeners() -> None:
    for listener in list(_connect_listeners):
        try:
            await listener()
        except Exception as e:  # noqa: BLE001 — one listener must not stop the rest
            log.warning("Cloud: connect listener %s failed: %s", getattr(listener, "__name__", listener), e)


async def _push_integrations_snapshot() -> None:
    """(Re)warm the cloud's integrations fleet cache — on every connect (the
    boot-time snapshot is emitted before the socket exists and is dropped)
    and from the heartbeat, inside the relay's cache lifetime."""
    global _last_snapshot_push
    _last_snapshot_push = time.time()
    try:
        await _health_sweeper.push_state_snapshot()
    except Exception as e:  # noqa: BLE001 — best effort
        log.debug("Cloud: integrations snapshot push failed: %s", e)


_CLOUD_CREDENTIAL_VARS = (
    ("SPOREPRINT_CLOUD_URL", "cloud_url"),
    ("SPOREPRINT_CLOUD_TOKEN", "cloud_token"),
    ("SPOREPRINT_CLOUD_DEVICE_ID", "cloud_device_id"),
)


def _enter_standing_refusal(reason: str) -> None:
    """The relay refused this Pi for a reason that only the operator clears."""
    global _standing_refusal
    _standing_refusal = reason
    _drop_undeliverable_queue()
    if reason == "subscription_required":
        log.warning(
            "Cloud: subscription required — cloud sync paused (local control "
            "is unaffected). Rechecking every %ds; resubscribe to resume.",
            _STANDING_REFUSAL_RETRY_SECONDS,
        )
    else:
        log.warning(
            "Cloud: the relay refused this Pi's device token (%s: the device was "
            "removed or its token revoked or rotated) — cloud sync paused (local "
            "control is unaffected). Re-pair this Pi; rechecking every %ds.",
            reason, _STANDING_REFUSAL_RETRY_SECONDS,
        )
    _task_status["cloud_connector"]["status"] = _STANDING_REFUSALS[reason]


async def start_cloud_connector():
    """Background task started in main.py lifespan. No-op if cloud not configured."""
    global _sio, _connected, _start_time, _reconnect_attempts
    global _wake_event, _connector_running, _connect_error, _token_refusals

    # Credentials paired via /api/cloud/configure live on the data volume
    # (see env_path) and override the process env.
    load_persisted_cloud_credentials()

    missing = [var for var, attr in _CLOUD_CREDENTIAL_VARS if not getattr(settings, attr)]
    if len(missing) == len(_CLOUD_CREDENTIAL_VARS):
        log.info("Cloud connector disabled — pair this Pi, or set SPOREPRINT_CLOUD_URL, "
                 "SPOREPRINT_CLOUD_TOKEN and SPOREPRINT_CLOUD_DEVICE_ID, to enable")
        _task_status["cloud_connector"]["status"] = "disabled"
        return
    if missing:
        # The relay authenticates a Pi by device id AND token, so a partial
        # configuration could only ever be refused, every retry, forever.
        log.error(
            "Cloud connector disabled — %s not set (SPOREPRINT_CLOUD_URL, "
            "SPOREPRINT_CLOUD_TOKEN and SPOREPRINT_CLOUD_DEVICE_ID are all "
            "needed; pairing writes them together)", ", ".join(missing),
        )
        _task_status["cloud_connector"]["status"] = f"disabled — {', '.join(missing)} not set"
        return

    if not cloud_url_transport_ok(settings.cloud_url):
        log.error(
            "Cloud connector disabled — refusing to send the device token over "
            "plaintext to %s (cloud_url must be https://, or http:// only to a "
            "LAN/loopback dev relay)", settings.cloud_url,
        )
        _task_status["cloud_connector"]["status"] = "disabled — insecure cloud_url (https required)"
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
    _wake_event = asyncio.Event()
    _connector_running = True

    # v4.1 — register the integrations RPC handler so cloud-web can read
    # this Pi's /api/integrations state through the relay.
    from . import integrations_proxy as _integrations_proxy
    _integrations_proxy.attach(_sio)

    @_sio.on("connect")
    async def on_connect():
        global _connected, _heartbeat_task, _standing_refusal, _token_refusals
        _connected = True
        _token_refusals = 0
        # _reconnect_attempts is reset by the connection loop only once a
        # session proves stable — a relay that accepts then immediately kicks
        # us must keep growing the backoff.
        # A successful connect means the cloud accepted us — a refusal that
        # stood (lapsed subscription, revoked token) has cleared. Resume
        # buffering.
        if _standing_refusal:
            _standing_refusal = None
            log.info("Cloud: the relay accepts this Pi again — cloud sync resumed")
        _task_status["cloud_connector"]["status"] = "connected"
        log.info("Cloud: connected to %s", settings.cloud_url)
        drained = await _drain_queue()
        if drained:
            log.info("Cloud: drained %d buffered messages", drained)
        # Start health heartbeat
        if _heartbeat_task is None or _heartbeat_task.done():
            _heartbeat_task = asyncio.create_task(_health_heartbeat_loop())
        await _push_integrations_snapshot()
        await _run_connect_listeners()

    @_sio.on("disconnect")
    async def on_disconnect(*_reason):
        global _connected, _heartbeat_task
        if _heartbeat_task and not _heartbeat_task.done():
            _heartbeat_task.cancel()
        _connected = False
        requeued = _requeue_unacked()
        _task_status["cloud_connector"]["status"] = "disconnected"
        log.warning("Cloud: disconnected%s",
                    f" — {requeued} unacknowledged frame(s) queued for resend" if requeued else "")

    @_sio.on("connect_error")
    async def on_connect_error(*args):
        global _connect_error
        _connect_error = _connect_error_reason(*args)

    @_sio.on("command")
    async def on_command(data):
        # Thin socket wrapper — the whole security gate lives in the importable
        # module-level handle_cloud_command so it can be frame-tested directly
        # (the nested closure was untestable). Pass the live client so every
        # command_result ack goes back over the same socket.
        await handle_cloud_command(_sio, data)

    # Connection loop with exponential backoff
    try:
        while True:
            _connect_error = None
            try:
                await _sio.connect(
                    settings.cloud_url,
                    auth={"token": settings.cloud_token, "device_id": settings.cloud_device_id},
                    transports=["websocket"],
                    wait_timeout=_CONNECT_WAIT_TIMEOUT_SECONDS,
                )
                connected_at = time.time()
                await _sio.wait()
            except asyncio.CancelledError:
                if _sio.connected:
                    await _sio.disconnect()
                return
            except Exception as e:
                refusal = _standing_refusal_of(e)
                if refusal == "Invalid device token":
                    _token_refusals += 1
                    if _token_refusals < _TOKEN_REFUSALS_TO_STAND:
                        refusal = None
                else:
                    _token_refusals = 0
                if refusal:
                    # Not a fault — the cloud is correctly refusing this Pi until
                    # the operator acts. Retrying hard would achieve nothing but
                    # noise; re-pairing (/api/cloud/configure) wakes the sleep.
                    _enter_standing_refusal(refusal)
                    await _backoff_sleep(_STANDING_REFUSAL_RETRY_SECONDS)
                    continue

                _reconnect_attempts += 1
                backoff = _backoff_seconds(_reconnect_attempts)
                # The relay's own reason, when it gave one, beats the client
                # library's generic "One or more namespaces failed to connect".
                log.warning("Cloud: connection failed (%s), retry in %ds",
                            _connect_error or e, backoff)
                _task_status["cloud_connector"]["status"] = f"reconnecting ({backoff}s)"
                await _backoff_sleep(backoff)
                continue

            # wait() returned: an established session was ended by the server
            # or the network. Without a delay here the loop reconnects ~1 s
            # later forever. A stable session resets the backoff; a short one
            # counts as a failed attempt.
            session_seconds = time.time() - connected_at
            if session_seconds >= _STABLE_SESSION_SECONDS:
                _reconnect_attempts = 0
            else:
                _reconnect_attempts += 1
            backoff = _backoff_seconds(_reconnect_attempts)
            log.warning(
                "Cloud: session ended after %.0fs, reconnecting in %ds",
                session_seconds, backoff,
            )
            _task_status["cloud_connector"]["status"] = f"reconnecting ({backoff}s)"
            await _backoff_sleep(backoff)
    finally:
        _connector_running = False


async def forward_telemetry(node_id: str, payload: dict):
    """Called from mqtt.py after every telemetry ingest. Enqueues for cloud."""
    if not settings.cloud_url or not _connector_running:
        # No connector runs in this process (unpaired, partly configured or
        # refused at start), so nothing would ever drain a queue.
        return
    if _standing_refusal:
        # The cloud is refusing this Pi's data. Queueing it would fill the
        # ring with frames that can never be delivered. SQLite already has them.
        return
    # The topic's node id goes last: it is the identity the broker's per-node
    # ACL vouches for, and a node_id inside the node's own payload must not
    # name a sibling. ts stays before the payload so a frame's own ts wins.
    msg = {"ts": time.time(), **payload, "node_id": node_id}
    if not (_connected and _sio):
        _enqueue(msg)
        return
    try:
        await _emit_telemetry(msg)
    except Exception as e:
        # The socket went away under us: keep the frame for the next connect.
        log.debug("Cloud: forward failed, buffered: %s", e)
        _enqueue(msg)


async def _emit_if_connected(event: str, payload: dict, *, confirm: bool = False) -> bool:
    """Send one relay event if the socket is up; never raises.

    Returns True when the event was handed to the socket, or — with
    ``confirm`` — only once the relay acknowledged it, within
    _EVENT_ACK_TIMEOUT_SECONDS. A socket that died without a FIN takes
    emits for up to the ping timeout and delivers none of them, so a caller
    that must not lose an event asks for the acknowledgement. An
    acknowledgement of ``{"ok": false}`` (the relay took the event but did
    not store it) counts as undelivered too.
    """
    if not settings.cloud_url or not _connected or not _sio:
        return False
    try:
        if confirm:
            answer = await _sio.call(event, payload, timeout=_EVENT_ACK_TIMEOUT_SECONDS)
            if isinstance(answer, dict) and answer.get("ok") is False:
                log.debug("Cloud: relay did not store %s", event)
                return False
        else:
            await _sio.emit(event, payload)
        return True
    except Exception as e:
        log.debug("Cloud: %s forward failed: %s", event, e)
        return False


async def forward_component_health(node_id: str, data: dict):
    """Forward ESP32 component health data to cloud relay (the topic's node id
    wins over any node_id in the payload, as in forward_telemetry)."""
    await _emit_if_connected("component_health", {"ts": time.time(), **data, "node_id": node_id})


# Events that ride their own Socket.IO channel, whose relay handler stores
# them: `ota_step` persists pipeline progress into `ota_progress_events`;
# `integrations_state` fills the relay's integrations cache (the web app's
# fleet view reads it). `integrations_state` also keeps going out in the
# legacy `event` envelope that older Pis sent it in.
_DEDICATED_EVENT_CHANNELS = frozenset({"ota_step", "integrations_state"})


async def forward_event(event_type: str, data: dict, *, confirm: bool = False) -> bool:
    """Forward session events, alerts, vision results to cloud.

    Everything outside _DEDICATED_EVENT_CHANNELS uses the legacy `event`
    envelope so existing push/escalation handlers fire unchanged.

    Events are NOT queued: while the socket is down they are dropped. Returns
    True only when the event was handed to the socket — with ``confirm``,
    only once the relay acknowledged it — so callers that must not lose a
    transition (the vendor-health sweeper) can retry.
    """
    ts = time.time()
    if event_type == "ota_step":
        return await _emit_if_connected("ota_step", {"ts": ts, **data}, confirm=confirm)
    if event_type in _DEDICATED_EVENT_CHANNELS:
        await _emit_if_connected(event_type, {"ts": ts, **data}, confirm=confirm)
    return await _emit_if_connected("event", {"type": event_type, "ts": ts, **data},
                                    confirm=confirm)


async def forward_session_sync(payload: dict) -> bool:
    """Send one grow-session snapshot (app.cloud.session_sync) to the cloud.

    Not queued: the caller keeps the session in its outbox and resends it on
    reconnect. Returns True only once the relay acknowledged it (and, on a
    relay that answers {"ok": ...}, stored it); the caller sends a session's
    next snapshot only after that, so they are written in order.
    """
    return await _emit_if_connected("session_sync", payload, confirm=True)


async def forward_contamination_event(payload: dict) -> bool:
    """Send one recorded contamination event (app.cloud.session_sync).

    Not queued: the caller keeps the event in its outbox and resends it on
    reconnect. Returns True only once the relay acknowledged it (and, on a
    relay that answers {"ok": ...}, stored it).
    """
    return await _emit_if_connected("contamination_event", payload, confirm=True)


async def _health_heartbeat_loop():
    """Periodically push Pi system health to cloud so mobile app can see it remotely.

    The beat carries the running server version (additive ``version``), the
    only place the cloud learns it after pairing — an OTA or a reinstall
    otherwise left the cloud showing the pairing-time version. It also
    re-pushes the integrations snapshot inside the relay's cache lifetime.
    """
    while _connected and _sio:
        try:
            system = await get_system_metrics()
            cloud = get_cloud_status()
            await _sio.emit("device_health", {
                "ts": time.time(),
                "device_id": settings.cloud_device_id,
                "version": server_version(),
                "system": system,
                "cloud": {
                    "connected": cloud["connected"],
                    "queue_depth": cloud["queue_depth"],
                    "uptime": cloud["uptime"],
                    "last_forward": cloud["last_forward"],
                    "reconnect_attempts": cloud["reconnect_attempts"],
                },
            })
            if time.time() - _last_snapshot_push >= _INTEGRATIONS_SNAPSHOT_INTERVAL_SECONDS:
                await _push_integrations_snapshot()
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.debug("Cloud: health heartbeat failed: %s", e)
        await asyncio.sleep(HEALTH_HEARTBEAT_INTERVAL)


def get_cloud_status() -> dict:
    """Returns connection status for health endpoint.

    ``restart_required``: the Pi holds a full set of cloud credentials but no
    connector runs in this process — it was unpaired when the server started,
    and pairing saved them since (apply_paired_credentials loads them; only a
    connector started at boot uses them), so a server restart connects it.
    """
    credentials = all(getattr(settings, attr) for _, attr in _CLOUD_CREDENTIAL_VARS)
    return {
        "configured": bool(settings.cloud_url),
        "connected": _connected,
        "restart_required": credentials and not _connector_running,
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


async def _target_is_registered(target: str) -> bool:
    """A cloud command can only target a known hardware node or smart plug."""
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

# Paired cloud credentials are persisted to `cloud.env` NEXT TO THE DATABASE —
# i.e. on the persistent data volume (/data/db in Docker). The old location,
# `<server>/.env` beside the code, is root-owned and ephemeral in the
# container (PermissionError → HTTP 500 on /configure, and lost on rebuild),
# and even when writable it was shadowed by the empty SPOREPRINT_CLOUD_* vars
# docker-compose injects. The connector loads this file at startup and it
# OVERRIDES the process env (see load_persisted_cloud_credentials).
_CLOUD_ENV_FILENAME = "cloud.env"
_CLOUD_ENV_KEYS: dict[str, str] = {
    "SPOREPRINT_CLOUD_URL": "cloud_url",
    "SPOREPRINT_CLOUD_TOKEN": "cloud_token",
    "SPOREPRINT_CLOUD_DEVICE_ID": "cloud_device_id",
}


def env_path() -> _Path:
    """Where pairing writes cloud credentials: beside the SQLite DB."""
    return _Path(settings.database_path).resolve().parent / _CLOUD_ENV_FILENAME


def load_persisted_cloud_credentials() -> bool:
    """Apply credentials saved by /api/cloud/configure onto ``settings``.

    Returns True when at least one value was applied. Non-empty values in
    the file win over the environment (a fresh pairing must take effect even
    though compose passes empty SPOREPRINT_CLOUD_* variables).
    """
    path = env_path()
    try:
        text = path.read_text()
    except FileNotFoundError:
        return False
    except OSError as e:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure — logs an identifier/path/field names only, never a secret value
        log.warning("Cloud: cannot read persisted credentials at %s: %s", path, e)
        return False
    applied = False
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        attr = _CLOUD_ENV_KEYS.get(key.strip())
        value = value.strip()
        if sep and attr and value:
            setattr(settings, attr, value)
            applied = True
    if applied:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure — logs an identifier/path/field names only, never a secret value
        log.info("Cloud: loaded paired credentials from %s", path)
    return applied


_FORBIDDEN_VALUE_CHARS = ("\n", "\r", "=", "\x00")


def _validate_env_value(key: str, value: str) -> None:
    for ch in _FORBIDDEN_VALUE_CHARS:
        if ch in value:
            raise ValueError(f"Invalid character in {key}")


def write_cloud_env(updates: dict) -> _Path:
    """Atomically merge `updates` into the persisted cloud.env (mode 0600).
    Rejects newline-injection values."""
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
