import asyncio
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import time

import aiomqtt

from .cloud.service import forward_telemetry, forward_event, forward_component_health
from .config import settings
from .hardware.coredumps import ACK_SUFFIX as COREDUMP_ACK_SUFFIX
from .hardware.coredumps import ingest_chunk as ingest_coredump_chunk
from .hardware.ota_push import note_node_event as note_node_ota_event
from .node_clock import MAX_FUTURE_SKEW_SECONDS, SYNCED_TS_MIN
from .notifications.service import notify
from .provision import served_ca_fingerprint
from .telemetry.service import (
    SENSOR_FIELDS,
    active_session_for_node,
    insert_readings,
    latest_node_timestamp,
    reading_rows,
    skipped_value_count,
)
from .db import get_db

log = logging.getLogger(__name__)

_client: aiomqtt.Client | None = None

# A lighting bank's channel-level report shares the bare `telemetry` topic
# ({<channel>: level 0-1023, ...}; firmware wire_contract.h build_dim_levels).
# Current firmware marks it "report": "dim_levels" and stamps a ts; earlier
# images sent it with neither — and every other frame on that topic, sensor
# reading or not, carries a ts.
_DIM_LEVELS_REPORT = "dim_levels"


def _is_level_report(payload: dict) -> bool:
    """A channel-level report, not a sensor frame: live actuator state with
    no reading to store and nothing for the rules to act on."""
    if payload.get("report") == _DIM_LEVELS_REPORT:
        return True
    return "ts" not in payload and not any(k in payload for k in SENSOR_FIELDS)

# Telemetry `ts` wire contract (firmware <-> Pi; app/node_clock.py):
#   * ts is Unix-epoch seconds once the node's clock is NTP-synced. Anything
#     below 1e9 (2001-09-09) is an unsynced node's uptime, never a real epoch,
#     and is replaced with the Pi's arrival time.
#   * A synced ts more than MAX_FUTURE_SKEW_SECONDS ahead of the Pi (a bogus
#     sync) is stored and shown at the arrival time too: at its own ts the
#     reading stayed "latest" until real time caught up with it, and no
#     retention cutoff reached it. Ordering and skew still go by the node's
#     ts (_classify_frame), so the Pi's clock still decides nothing live.
#   * Frames replayed from the node's offline buffer carry "replay": true.
#   * A frame is NOT live when it carries "replay": true, or when its ts is
#     older than the newest ts already accepted live from the same node (a
#     late, out-of-order frame). Such frames are stored, but the rules engine
#     never evaluates them, they never overwrite a newer "latest reading", and
#     they never reach the local live socket. The cloud relay still receives
#     them (as it always has) with their real ts and "replay": true, so its
#     history has no gaps.
#   * The Pi's own clock never decides liveness. Comparing ts with the Pi's
#     wall clock made a Pi running a few minutes fast skip evaluate_rules —
#     and with it every safety threshold — for every synced node, silently.
#     Pi-vs-node skew is measured per node and reported instead (a rate-
#     limited WARNING past _CLOCK_SKEW_WARN_SECONDS, and reliability.
#     node_clock_skew in GET /api/health/detail/system).
_UNSYNCED_TS_BELOW = SYNCED_TS_MIN
_uptime_ts_clamp_count = 0
_future_ts_clamp_count = 0
_mqtt_restart_count = 0

# Per-node telemetry clock bookkeeping (see the contract above).
# _node_newest_ts: newest node-clock ts accepted live, per node. Frames the
#   Pi stamped with its own arrival time (unsynced) are not recorded: they are
#   on the Pi's clock, not the node's, so they say nothing about ordering.
# _node_clock: node -> {"skew_seconds", "observed_at", "skewed"}, where skew is
#   Pi arrival time minus the node's ts (positive: the node is behind the Pi).
# Both are capped (_NODE_CLOCK_TRACK_CAP, oldest-updated evicted): node ids come
#   from topic names, so an unbounded dict would grow with every junk id.
_CLOCK_SKEW_WARN_SECONDS = 120
_CLOCK_SKEW_LOG_INTERVAL_SECONDS = 15 * 60
# A non-replay frame this much older than the node's newest live ts is not a
# late frame (current firmware flags every buffered frame "replay") but the
# node's clock stepping back — e.g. an NTP correction after a bogus sync into
# the future. Holding every frame non-live until real time caught up with the
# bogus one would stop automation for that long, so it re-baselines instead.
_CLOCK_STEP_BACK_SECONDS = 120
_NODE_CLOCK_TRACK_CAP = 256
_node_newest_ts: dict[str, float] = {}
_node_clock: dict[str, dict] = {}
_skew_logged_at: dict[str, float] = {}
_non_live_counts = {"replay": 0, "out_of_order": 0}

# Broker accounts that are not nodes. The ACL's per-node `pattern` grants
# (config/mosquitto/acl.conf) apply to every user, so each of these can
# publish sporeprint/<its name>/{telemetry,status,health,alert,...}. Frames
# under these names are dropped and the names can never register as nodes: a
# leaked plug credential (sp-3p lives on third-party plug firmware) must not
# become a node, claim a node type, or feed the rules engine. The Pi server's
# own configured account (settings.mqtt_username) is reserved too, and so is
# every per-plug login (settings.mqtt_plug_users, which
# scripts/add-plug-mqtt-user.sh fills): the same patterns let a plug's own
# login, whose password lives in the plug, post as a node.
# tests/test_mqtt_acl_contract.py keeps this in step with acl.conf and
# scripts/rotate-mqtt-creds.sh.
RESERVED_NODE_IDS = frozenset({"server", "sp-3p", "sp-cmd", "sp-telemetry"})
# Reserved ids already warned about, lowercased (so it can only ever hold the
# few reserved names and needs no cap).
_reserved_drop_logged: set[str] = set()


def is_service_account(name: str) -> bool:
    """Is `name` one of the broker's service accounts (RESERVED_NODE_IDS or
    the server's own login)? Case-insensitive. The ACL's per-plug patterns
    let these post plug state under their own name too, so smart_plugs
    ignores such frames."""
    name = str(name or "").strip().lower()
    if not name:
        return False
    return name in RESERVED_NODE_IDS or name == (settings.mqtt_username or "").strip().lower()


def plug_logins() -> frozenset[str]:
    """The per-plug broker logins (settings.mqtt_plug_users), lowercased."""
    return frozenset(n for n in re.split(r"[\s,]+", (settings.mqtt_plug_users or "").lower()) if n)


def is_reserved_node_id(node_id: str) -> bool:
    """Is `node_id` a broker login that is not a node: a service account or a
    per-plug login? Case-insensitive."""
    name = str(node_id or "").strip().lower()
    return bool(name) and (is_service_account(name) or name in plug_logins())


async def purge_reserved_nodes() -> int:
    """Delete hardware_nodes rows an older server registered under a reserved id.

    Before the filter in _handle_message, any service account's status frame
    upserted a node row, and a row is what admits keyless camera uploads and
    cloud target_kind routing. Returns the number of rows removed.
    """
    names = sorted((RESERVED_NODE_IDS | {(settings.mqtt_username or "").strip().lower()}
                    | plug_logins()) - {""})
    removed = 0
    async with get_db() as db:
        for name in names:
            cursor = await db.execute(
                "DELETE FROM hardware_nodes WHERE lower(node_id) = ?", (name,))
            removed += max(cursor.rowcount or 0, 0)
        await db.commit()
    if removed:
        log.warning("[SEC] removed %d hardware_nodes row(s) registered under a "
                    "broker service account name", removed)
    return removed

# Shelly / Tasmota publish on their own topic trees, often as bare text. A
# Shelly Gen2+ (Plus/Pro/Mini, Gen3, Gen4) is set up with its MQTT prefix
# under shellies/ (shellies/<role>), so shellies/# carries both generations and
# no subscription or ACL grant outside these two trees is needed — see
# automation/smart_plugs.py and config/mosquitto/acl.conf.
_VENDOR_PLUG_PREFIXES = ("shellies/", "tasmota/")

# Telemetry frames also refresh a registered node's liveness: the
# offline sweeper in main.py reads last_seen, which only status/* frames used
# to write. UPDATE only — status changes stay with the heartbeat/LWT path, and
# telemetry never registers a node (registration gates keyless camera uploads).
_TOUCH_LAST_SEEN_SQL = (
    "UPDATE hardware_nodes SET last_seen = MAX(COALESCE(last_seen, 0), ?) "
    "WHERE node_id = ?"
)

# node_logs keeps about the newest _NODE_LOG_KEEP rows per node. Finding the
# cutoff walks the node's whole log, so it runs once _NODE_LOG_TRIM_EVERY rows
# have arrived since the last trim (and on a node's first batch after a
# start), not on every batch: a chatty node flushes up to one every 2 s, and
# the per-batch trim cost several times the batch's own inserts.
_NODE_LOG_KEEP = 10_000
_NODE_LOG_TRIM_EVERY = 500
_node_log_since_trim: dict[str, int] = {}
_TRIM_NODE_LOG_SQL = (
    "DELETE FROM node_logs WHERE node_id = ? AND id <= "
    "(SELECT id FROM node_logs WHERE node_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)"
)

# A switch report's trigger when the node itself switched the channel off
# (firmware wire_contract.h kTriggerSafetyCutoff).
_TRIGGER_SAFETY_CUTOFF = "safety_cutoff"

# Lifetime actuator_events total per (node, channel, action), bumped in the
# same transaction as the row: the Grafana counter reads it, so retention can
# prune old rows without the counter going backwards.
_COUNT_ACTUATOR_EVENT_SQL = (
    "INSERT INTO actuator_event_counts (node_id, channel, action, n) "
    "VALUES (?, ?, ?, 1) "
    "ON CONFLICT(node_id, channel, action) DO UPDATE SET n = n + 1"
)

# Node-side alert types (firmware check_alerts / reed edges) -> ntfy tier.
# Deployed firmware re-emits a standing condition every read cycle (~30 s);
# current firmware latches (entry + hourly). Each (node, type, sensor) is
# deduplicated, so one failed sensor never masks another on the same node.
_NODE_ALERT_PRIORITY = {
    "temperature": "critical",
    "co2": "critical",
    "sensor_failure": "critical",
    "humidity": "warning",
    "door": "info",
}
_NODE_ALERT_DEDUP_SECONDS = {"critical": 900, "warning": 300, "info": 3600}


def get_reliability_counters() -> dict:
    return {
        "uptime_ts_clamps": _uptime_ts_clamp_count,
        # Synced frames dated past MAX_FUTURE_SKEW_SECONDS ahead, stamped
        # with their arrival time instead.
        "future_ts_clamps": _future_ts_clamp_count,
        "mqtt_supervisor_restarts": _mqtt_restart_count,
        # Frames dropped before routing (oversized, or JSON that cannot be
        # built: see _decode_payload).
        "dropped_frames": _dropped_frame_count,
        # Frame fields not stored: not a finite number (telemetry.service).
        "skipped_readings": skipped_value_count(),
        # Frames stored but not evaluated (see the ts contract above).
        "non_live_frames": dict(_non_live_counts),
        # Per node: Pi arrival time minus the node's ts, as last seen.
        "clock_skew_warn_seconds": _CLOCK_SKEW_WARN_SECONDS,
        "node_clock_skew": {node: dict(info) for node, info in _node_clock.items()},
    }


def _remember(table: dict, node_id: str, value) -> None:
    """Set table[node_id] as the most recently updated entry, evicting the
    least recently updated one past _NODE_CLOCK_TRACK_CAP."""
    table.pop(node_id, None)
    while len(table) >= _NODE_CLOCK_TRACK_CAP:
        table.pop(next(iter(table)))
    table[node_id] = value


def _observe_node_clock(node_id: str, ts: float, received_at: float) -> None:
    """Record a synced, non-replayed frame's Pi-vs-node skew; warn when large.

    Observation only — skew never changes whether a frame is evaluated.
    """
    skew = received_at - ts
    skewed = abs(skew) > _CLOCK_SKEW_WARN_SECONDS
    _remember(_node_clock, node_id, {
        "skew_seconds": round(skew, 1),
        "observed_at": received_at,
        "skewed": skewed,
    })
    if not skewed:
        return
    last = _skew_logged_at.get(node_id)
    if last is not None and received_at - last < _CLOCK_SKEW_LOG_INTERVAL_SECONDS:
        return
    _remember(_skew_logged_at, node_id, received_at)
    log.warning(
        "clock skew: node %s telemetry ts is %.0f s %s the Pi's clock (> %d s). "
        "Its frames are still evaluated live. Check NTP on the Pi "
        "(GET /api/health/detail/clock) and on the node.",
        node_id, abs(skew), "behind" if skew > 0 else "ahead of",
        _CLOCK_SKEW_WARN_SECONDS,
    )


def _classify_frame(node_id: str, ts: float, *, replay: bool, node_clock: bool,
                    received_at: float) -> str | None:
    """Why a telemetry frame is not live ("replay" / "out_of_order"), or None.

    ``node_clock`` is False when ``ts`` was stamped by the Pi (unsynced node):
    such a frame is live unless replayed and does not move the node's newest
    ts. A live node-clock frame becomes the node's newest ts.
    """
    if replay:
        return "replay"
    if not node_clock:
        return None
    newest = _node_newest_ts.get(node_id)
    if newest is not None and ts < newest:
        if newest - ts <= _CLOCK_STEP_BACK_SECONDS:
            return "out_of_order"
        log.warning(
            "clock: node %s ts stepped back %.0f s (newest %.0f, now %.0f); "
            "re-baselining so its frames stay live",
            node_id, newest - ts, newest, ts,
        )
    _remember(_node_newest_ts, node_id, ts)
    _observe_node_clock(node_id, ts, received_at)
    return None


def _sign_cmd_payload(payload: dict) -> dict:
    """Sign a cmd/* payload with HMAC-SHA256 over canonical JSON.

    The firmware's verifyFrame expects:
      * `ts` epoch seconds (Pi wall-clock, NTP-disciplined)
      * `signature` = HMAC-SHA256(settings.mqtt_hmac_key, canonical_body)

    The canonical body is the JSON with keys sorted and no whitespace
    between separators, minus the `signature` field itself. Mirrors
    sporeprint/firmware/lib/sp_core/canonical_json.cpp (raw-token transform;
    golden vectors in tests/fixtures/signing_vectors.json pin the contract).

    If `settings.mqtt_hmac_key` is unset, the payload ships unsigned —
    matches the firmware's migration-period "warn and accept" behavior so
    upgrades don't break existing deployments. Set the key on both sides
    (Pi env + firmware NVS via provisioning tool) to enable strict mode.
    """
    signed = dict(payload)
    signed.setdefault("ts", int(time.time()))

    key = settings.mqtt_hmac_key or ""
    if not key:
        return signed

    canonical = json.dumps(
        {k: v for k, v in signed.items() if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signed["signature"] = hmac.new(
        key.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    return signed


# The node's MqttLink drops any inbound frame of kInboundCap (1024) bytes or
# more (firmware/lib/sp_device/mqtt_link.h), so a bound frame must stay below.
_NODE_INBOUND_FRAME_CAP = 1024


def _bind_cmd_payload(topic: str, payload: dict) -> dict:
    """Add the destination-binding members to a cmd/* body before signing.

    * "topic" — the full `sporeprint/<node>/cmd/<suffix>` it is published on.
      Current firmware rejects a signed frame whose "topic" differs from the
      topic it arrived on, so a captured frame can't be redirected to another
      channel or node.
    * "nonce" — 64 random bits. The node remembers each accepted (topic, MAC)
      for the replay window; without a nonce, two legitimate identical
      commands in the same `ts` second (on/off/on) are byte-identical and
      the repeat is dropped as a replay.

    Backward compatible: every deployed firmware canonicalizes ALL members
    except "signature", so older nodes verify these frames and ignore the
    extra keys. The Pi's values always win over same-named payload keys.
    """
    return {**payload, "topic": topic, "nonce": secrets.token_hex(8)}


def _is_cmd_topic(topic: str) -> bool:
    """A Pi→node command frame (`.../cmd/<channel>` or `.../cmd`)."""
    return "/cmd/" in topic or topic.endswith("/cmd")


def _signing_enforced() -> bool:
    """Whether an unsigned cmd/* publish should be REFUSED when no key is set.

    "always"/"never" are explicit; "auto" enforces iff the Pi is cloud-
    configured (a paired/managed deployment) — using the stable `cloud_url`
    config, not the live connection, so a cloud outage can't downgrade signing.
    """
    mode = settings.mqtt_require_signing
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(settings.cloud_url)  # "auto"


def command_signing_status() -> dict:
    """Pi→ESP32 command-signing posture — for /health + the startup log."""
    key_set = bool(settings.mqtt_hmac_key)
    if key_set:
        mode = "active"                 # frames are signed
    elif _signing_enforced():
        mode = "enforced_blocking"      # unsigned cmd/* frames are refused
    else:
        mode = "permissive_unsigned"    # unsigned cmd/* frames are sent (LAN-trust)
    return {
        "key_set": key_set,
        "policy": settings.mqtt_require_signing,
        "cloud_configured": bool(settings.cloud_url),
        "mode": mode,
    }


# Warn-once guards so a command every few seconds doesn't spam the log; the
# persistent state is always visible at GET /api/health/detail/mqtt.
_signing_block_logged = False
_unsigned_ship_logged = False


def _log_signing_block(topic: str) -> None:
    global _signing_block_logged
    if not _signing_block_logged:
        _signing_block_logged = True
        log.critical(
            "[SEC] REFUSING unsigned command to %s — mqtt_hmac_key is unset and "
            "signing is enforced (policy=%s). Provision the key "
            "(scripts/provision-node.sh) or set SPOREPRINT_MQTT_REQUIRE_SIGNING=never "
            "for trusted-LAN operation. Commands are dropped until then.",
            topic, settings.mqtt_require_signing,
        )


def _log_unsigned_ship() -> None:
    global _unsigned_ship_logged
    if not _unsigned_ship_logged:
        _unsigned_ship_logged = True
        log.warning(
            "[SEC] shipping UNSIGNED cmd/* frames — mqtt_hmac_key unset and signing "
            "not enforced (trusted-LAN mode). A provisioned node will reject these. "
            "Set SPOREPRINT_MQTT_HMAC_KEY to sign.",
        )


async def mqtt_publish(topic: str, payload: dict) -> bool:
    if _client is None:
        return False

    # Sign any cmd/* frame so the firmware can verify authenticity.
    # Non-cmd topics (state/*, telemetry/*) don't need signing because they
    # flow node→Pi, not Pi→node, and the Pi is the trust root.
    outbound = payload
    if _is_cmd_topic(topic):
        if not settings.mqtt_hmac_key:
            # Fail closed when enforced — never ship an unsigned actuator
            # command silently.
            if _signing_enforced():
                _log_signing_block(topic)
                return False
            _log_unsigned_ship()
            outbound = _sign_cmd_payload(payload)
        else:
            outbound = _sign_cmd_payload(_bind_cmd_payload(topic, payload))
            if len(json.dumps(outbound).encode("utf-8")) >= _NODE_INBOUND_FRAME_CAP:
                # Deliverable beats bound: the node would drop the whole frame.
                log.warning("cmd frame to %s too large for topic binding; "
                            "sending it signed but unbound", topic)
                outbound = _sign_cmd_payload(payload)
        size = len(json.dumps(outbound).encode("utf-8"))
        if size >= _NODE_INBOUND_FRAME_CAP:
            # Even unbound, the node would drop it unread: report it as not
            # sent (send_command answers 503) rather than "sent" and lost.
            log.error("cmd frame to %s is %d bytes; nodes drop frames of %d "
                      "bytes or more, so it was not sent", topic, size,
                      _NODE_INBOUND_FRAME_CAP)
            return False

    try:
        await _client.publish(topic, json.dumps(outbound))
        return True
    except Exception as e:
        log.warning("mqtt_publish to %s failed: %s", topic, e)
        return False


# Broker $SYS stats — health/service.update_mqtt_stat was designed for this
# feed but the subscription was never wired, so GET /api/health/detail/mqtt
# always returned {}. Curated topics only: the full $SYS/broker/# firehose is
# ~50 topics the UI would never render.
_SYS_TOPICS = (
    "$SYS/broker/version",
    "$SYS/broker/uptime",
    "$SYS/broker/clients/connected",
    "$SYS/broker/messages/received",
    "$SYS/broker/messages/sent",
    "$SYS/broker/bytes/received",
    "$SYS/broker/bytes/sent",
    "$SYS/broker/load/messages/received/1min",
    "$SYS/broker/load/messages/sent/1min",
)


def _handle_sys_message(topic: str, raw: bytes) -> None:
    """Store one $SYS/broker/* payload (plain text, not JSON) as an mqtt stat."""
    from .health.service import update_mqtt_stat

    try:
        update_mqtt_stat(topic.removeprefix("$SYS/broker/"), raw.decode().strip())
    except Exception:  # never let a stats update disturb the message loop
        pass


def _is_vendor_plug_topic(topic: str) -> bool:
    return topic.startswith(_VENDOR_PLUG_PREFIXES)


# Frames larger than this are dropped unread. A node's MQTT buffer holds about
# 1 KB and the largest plug frames (Tasmota status, Shelly Gen2 RPC) a few KB,
# so nothing legitimate comes close; the broker sets no packet size limit.
_MAX_PAYLOAD_BYTES = 64 * 1024
# Frames dropped before routing: oversized, or JSON that Python refuses to
# build (nesting past the recursion limit, an integer past the 4300-digit
# limit). Reported under reliability in GET /api/health/detail/system.
_dropped_frame_count = 0


def _decode_payload(topic: str, raw: bytes):
    """Decode one MQTT payload for routing; None means drop the frame.

    sporeprint/* frames are JSON objects, nothing else. Shelly Gen1 and Tasmota
    publish their relay state as bare text (`on`/`off`, `ON`/`OFF`), so for
    those topics a payload that isn't JSON is passed through as the stripped
    string. Numeric power reports, the `true`/`false` online flag and the JSON
    of Tasmota telemetry and Shelly Gen2 RPC frames still parse.

    Never raises. A payload json.loads cannot build — nested deeper than the
    recursion limit (RecursionError) or holding an integer past Python's
    digit limit (a ValueError that is not a JSONDecodeError) — is dropped on
    every topic: escaping the message loop, one such retained frame restarted
    the MQTT session on every reconnect, and ingest never recovered.
    """
    global _dropped_frame_count
    if len(raw) > _MAX_PAYLOAD_BYTES:
        _dropped_frame_count += 1
        log.warning("dropping a %d-byte frame on %s (limit %d bytes)",
                    len(raw), topic[:120], _MAX_PAYLOAD_BYTES)
        return None
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if not _is_vendor_plug_topic(topic):
            return None
        # Empty/whitespace (e.g. a retained message being cleared) is no state.
        return text.strip() or None
    except (ValueError, RecursionError) as e:
        _dropped_frame_count += 1
        log.warning("dropping an undecodable frame on %s: %s",
                    topic[:120], type(e).__name__)
        return None
    if not _is_vendor_plug_topic(topic) and not isinstance(payload, dict):
        return None
    return payload


async def start_mqtt(sio):
    global _client, _mqtt_restart_count
    from .health.service import update_task
    try:
        await purge_reserved_nodes()
    except Exception as e:  # housekeeping only; never block the MQTT supervisor
        log.warning("purging service-account node rows failed: %s", e)
    while True:
        try:
            update_task("mqtt", "connecting")
            mqtt_kwargs = {}
            if settings.mqtt_username:
                mqtt_kwargs["username"] = settings.mqtt_username
                mqtt_kwargs["password"] = settings.mqtt_password
            async with aiomqtt.Client(settings.mqtt_host, settings.mqtt_port, **mqtt_kwargs) as client:
                _client = client
                await client.subscribe("sporeprint/#")
                await client.subscribe("shellies/#")
                await client.subscribe("tasmota/#")
                for sys_topic in _SYS_TOPICS:
                    await client.subscribe(sys_topic)
                update_task("mqtt", "running")
                log.info("MQTT connected to %s:%d", settings.mqtt_host, settings.mqtt_port)

                # Announce the command-signing posture once per (re)connect so a
                # misconfigured Pi is never silently unsigned.
                _sig = command_signing_status()
                if _sig["mode"] == "active":
                    log.info("[SEC] cmd/* signing ACTIVE (mqtt_hmac_key set)")
                elif _sig["mode"] == "enforced_blocking":
                    log.critical(
                        "[SEC] cmd/* signing ENFORCED but mqtt_hmac_key is UNSET "
                        "(policy=%s) — commands will be REFUSED. Provision the key "
                        "or set SPOREPRINT_MQTT_REQUIRE_SIGNING=never.",
                        settings.mqtt_require_signing,
                    )
                else:
                    log.warning(
                        "[SEC] cmd/* signing DISABLED — frames ship UNSIGNED "
                        "(trusted-LAN mode). Set SPOREPRINT_MQTT_HMAC_KEY to enable.",
                    )

                async for message in client.messages:
                    # Everything one frame does stays inside this try: an
                    # exception escaping it ends the session (and with it the
                    # subscriptions), and a retained frame that raises again on
                    # every redelivery would keep ingest down for good.
                    topic = "?"
                    try:
                        topic = str(message.topic)
                        raw = bytes(message.payload or b"")
                        # $SYS payloads are plain text — handle before the
                        # JSON parse below would silently drop them.
                        if topic.startswith("$SYS/"):
                            _handle_sys_message(topic, raw)
                            continue
                        payload = _decode_payload(topic, raw)
                        if payload is None:
                            continue
                        await _handle_message(
                            sio, topic, payload,
                            retained=getattr(message, "retain", False) is True,
                        )
                    except Exception as e:
                        log.exception("_handle_message(%s) crashed: %s", topic, e)

        except aiomqtt.MqttError as e:
            update_task("mqtt", "disconnected", error=str(e))
            log.warning("MQTT disconnected: %s — reconnecting in 5s", e)
            _client = None
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            _client = None
            update_task("mqtt", "stopped")
            return
        except Exception as e:
            _client = None
            _mqtt_restart_count += 1
            update_task("mqtt", "error", error=str(e))
            log.exception("start_mqtt fatal error (restart=%d): %s", _mqtt_restart_count, e)
            await asyncio.sleep(5)


async def _handle_message(sio, topic: str, payload, *, retained: bool = False):
    """Route one decoded frame. ``retained`` is True when the broker delivers
    a stored retained message on (re)subscribe rather than a live publish."""
    global _uptime_ts_clamp_count, _future_ts_clamp_count
    # Smart plug messages (Shelly / Tasmota) live on the vendor's own topic
    # tree and are often bare text; they never enter the sporeprint/* branches.
    if _is_vendor_plug_topic(topic):
        from .automation.smart_plugs import handle_plug_message
        await handle_plug_message(sio, topic, payload)
        return

    parts = topic.split("/")
    if len(parts) < 3:
        return

    node_id = parts[1]
    msg_type = parts[2]

    if is_reserved_node_id(node_id):
        # A service account or plug login publishing through the per-node ACL
        # patterns (see RESERVED_NODE_IDS): never a node, never rules input.
        if node_id.lower() not in _reserved_drop_logged:
            _reserved_drop_logged.add(node_id.lower())
            log.warning("[SEC] dropping sporeprint/%s/%s frames: %r is a broker "
                        "service account or plug login, not a node", node_id, msg_type, node_id)
        return

    if msg_type == "telemetry" and len(parts) == 4:
        # telemetry/<channel> — a relay-bank switch-state report
        # {channel, state, pwm, trigger}, published on every command, safety
        # cutoff, and 60s cadence. These used to funnel through the sensor
        # path below, where store_bulk_readings stored nothing (no key overlaps
        # SENSOR_FIELDS) — so the actuator_events table, built for exactly this
        # feed, had no writer and Grafana's actuator_event_count sat at zero.
        received_at = time.time()
        channel = payload.get("channel", parts[3])
        action = payload.get("state", "unknown")
        async with get_db() as db:
            await db.execute(
                """INSERT INTO actuator_events (timestamp, node_id, channel, action, value, trigger)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    received_at, node_id, channel, action,
                    payload.get("pwm"),
                    payload.get("trigger", "report"),
                ),
            )
            await db.execute(_COUNT_ACTUATOR_EVENT_SQL, (node_id, channel, action))
            await db.execute(_TOUCH_LAST_SEEN_SQL, (received_at, node_id))
            await db.commit()
        await sio.emit("actuator_state", {**payload, "node_id": node_id})
        # Keep the cloud forward — remote clients render live actuator state
        # from these frames; only the pointless local store + rules eval stops.
        await forward_telemetry(node_id, payload)
        # The node says the channel is ON — however it got there (a physical
        # override button, a command from another tool). A rule cutoff must
        # not stay suppressed as a "redundant" repeat of its last OFF.
        if str(payload.get("state", "")).strip().lower() == "on":
            # Late import: the engine imports this module (mqtt_publish).
            from .automation.engine import note_actuator_on
            try:
                await note_actuator_on(node_id, str(payload.get("channel") or parts[3]))
            except Exception as e:
                log.warning("noting %s/%s ON failed: %s", node_id, parts[3], e)
        elif payload.get("trigger") == _TRIGGER_SAFETY_CUTOFF:
            # The node's own cutoff (max-on backstop, safe mode, OTA start)
            # switched the channel off: a manual ON hold on it is over.
            from .automation.engine import end_on_hold_after_cutoff
            try:
                await end_on_hold_after_cutoff(node_id, str(payload.get("channel") or parts[3]))
            except Exception as e:
                log.warning("ending the ON hold on %s/%s failed: %s", node_id, parts[3], e)

    elif msg_type == "telemetry" and _is_level_report(payload):
        # A lighting bank's channel levels: shown and forwarded live, as
        # before, but not a reading — no session to tag, nothing to store,
        # nothing for the rules (which run on the node's periodic telemetry
        # frame, schedules included, at its own cadence). Every ramp step
        # used to run the whole sensor path.
        received_at = time.time()
        try:
            ts = float(payload.get("ts"))
        except (TypeError, ValueError):
            ts = math.nan
        payload["ts"] = ts if math.isfinite(ts) and ts >= _UNSYNCED_TS_BELOW else received_at
        try:
            async with get_db() as db:
                await db.execute(_TOUCH_LAST_SEEN_SQL, (received_at, node_id))
                await db.commit()
        except Exception as e:
            log.warning("refreshing last_seen for %s failed: %s", node_id, e)
        await sio.emit("telemetry", {**payload, "node_id": node_id})
        await forward_telemetry(node_id, payload)

    elif msg_type == "telemetry":
        # Late import: the engine imports this module (mqtt_publish).
        from .automation.engine import _session_for_node, evaluate_rules

        received_at = time.time()
        replay = payload.get("replay") is True
        raw_ts = payload.get("ts")
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            ts = math.nan
        # True when ts is the node's own synced clock; False when the Pi
        # stamps its arrival time (no/garbled ts, or an unsynced uptime ts).
        node_clock = math.isfinite(ts) and ts >= _UNSYNCED_TS_BELOW
        if not node_clock and math.isfinite(ts):
            # Unsynced node clock: the ts is uptime, not wall time.
            _uptime_ts_clamp_count += 1
            log.debug("unsynced ts %s from %s, stamping arrival time", raw_ts, node_id)
        # A synced clock far ahead of the Pi (see the contract above): ordered
        # and skew-checked on the node's ts below, stored at arrival time.
        future = node_clock and ts > received_at + MAX_FUTURE_SKEW_SECONDS
        not_live = _classify_frame(node_id, ts if node_clock else received_at,
                                   replay=replay, node_clock=node_clock,
                                   received_at=received_at)
        if future:
            _future_ts_clamp_count += 1
            log.debug("ts %s from %s is %.0f s ahead of the Pi; stamping arrival time",
                      raw_ts, node_id, ts - received_at)
        if future or not node_clock:
            ts = received_at
            if not_live:
                # A late frame's real time is unrecoverable but is certainly
                # older than what the node already reported live. Never let
                # it land after (and so shadow) the latest reading.
                newest = await latest_node_timestamp(node_id)
                if newest is not None and newest <= ts:
                    ts = newest - 0.001
        payload["ts"] = ts

        # Tag the reading with the grow its node was part of at `ts`
        # (transcripts and the per-session telemetry endpoint resolve by
        # session_id): the grow the rules engine drives with the node's
        # readings (sessions.service.get_active_session_for_node). A live
        # frame resolves it once for the tag and the engine both; a session
        # started after the frame's ts (a replay, a lagging clock) does not
        # claim the reading.
        node_session = None
        if not_live:
            session_id = await active_session_for_node(node_id, ts)
        else:
            node_session = await _session_for_node(node_id)
            session = node_session[0]
            if session and (session.get("created_at") or 0) <= ts:
                session_id = session["id"]
            else:
                session_id = await active_session_for_node(node_id, ts)

        # The readings and the last_seen touch are one transaction (one
        # commit on the SD card per frame). A failed insert is rolled back
        # on its own (insert_readings' savepoint), and losing the history
        # row must not also cost the node its liveness or a live frame its
        # rules evaluation (safety cutoffs included); e.g. "database is
        # locked" while the nightly retention job holds the write lock.
        rows = reading_rows(node_id, payload, ts, session_id)
        try:
            async with get_db() as db:
                await db.execute("BEGIN")
                try:
                    await insert_readings(db, rows)
                except Exception as e:
                    log.warning("storing telemetry from %s failed: %s", node_id, e)
                # Any frame (replayed ones too) proves the node is up right now.
                await db.execute(_TOUCH_LAST_SEEN_SQL, (received_at, node_id))
                await db.commit()
        except Exception as e:
            log.warning("storing telemetry from %s failed: %s", node_id, e)
        if not_live:
            # History only: the local socket feed renders each frame as the
            # current reading and the rules engine acts on it, so a late frame
            # would roll the displayed/acted-on state back. The cloud relay has
            # always received late frames (with their real ts), so keep its
            # history whole and mark the frame as not live.
            _non_live_counts[not_live] += 1
            log.debug("stored %s telemetry from %s (ts %.0f); not live",
                      not_live, node_id, ts)
            await forward_telemetry(node_id, {**payload, "replay": True})
            return
        await sio.emit("telemetry", {**payload, "node_id": node_id})
        await forward_telemetry(node_id, payload)

        # Enrich readings with outdoor weather (virtual sensors for automation rules)
        from .weather.service import get_current_weather
        enriched = dict(payload)
        weather = get_current_weather()
        if weather:
            for key in ("outdoor_temp_f", "outdoor_humidity", "outdoor_dew_point_f",
                        "outdoor_wind_mph", "forecast_high_f", "forecast_low_f"):
                if weather.get(key) is not None:
                    enriched[key] = weather[key]

        # Evaluate automation rules against enriched readings, on the grow
        # already resolved for the tag above.
        try:
            await evaluate_rules(node_id, enriched, sio, node_session=node_session)
        except Exception as e:
            log.error("Automation engine error: %s", e)

    elif msg_type == "status":
        if len(parts) == 4 and parts[3] == "heartbeat":
            # v4.2: node_type + roles update on every heartbeat. The old
            # upsert never refreshed node_type on conflict, so rows decayed
            # to whatever the first insert guessed (usually 'unknown') and
            # type-based command routing quietly broke. v2 firmware always
            # sends `type` (the provisioned personality) and `roles` (the
            # full capability list for combined nodes).
            roles = payload.get("roles")
            roles_json = json.dumps(roles) if isinstance(roles, list) else None
            # reset_reason + mqtt_reconnects were emitted on every heartbeat and
            # dropped on the floor. reset_reason is the panic-loop tell: a node
            # stuck in a WDT/brownout reboot cycle looks "online" on every other
            # signal — this column is the only place that failure is visible.
            # tls / tls_fallback / board / ca_fp (and ca_fp_match, the Pi's
            # check of ca_fp) are the node's transport security, as of its
            # latest heartbeat (see _heartbeat_tls_fields).
            tls, tls_fallback, board, ca_fp, ca_fp_match = _heartbeat_tls_fields(
                node_id, payload)
            # A heartbeat is never retained, so it is the node alive right now:
            # it re-arms the liveness sweeper's offline page
            # (offline_notified_at, main._sweep_stale_nodes).
            async with get_db() as db:
                cursor = await db.execute(
                    "SELECT status FROM hardware_nodes WHERE node_id = ?", (node_id,))
                prior = await cursor.fetchone()
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, firmware_version, last_seen, ip_address, status, roles, reset_reason, mqtt_reconnects,
                                                   tls, tls_fallback, board, ca_fp, ca_fp_match)
                       VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(node_id) DO UPDATE SET
                         node_type=CASE WHEN excluded.node_type != 'unknown'
                                        THEN excluded.node_type
                                        ELSE hardware_nodes.node_type END,
                         firmware_version=excluded.firmware_version,
                         last_seen=excluded.last_seen,
                         ip_address=excluded.ip_address,
                         status='online',
                         roles=COALESCE(excluded.roles, hardware_nodes.roles),
                         reset_reason=COALESCE(excluded.reset_reason, hardware_nodes.reset_reason),
                         mqtt_reconnects=COALESCE(excluded.mqtt_reconnects, hardware_nodes.mqtt_reconnects),
                         tls=excluded.tls,
                         tls_fallback=excluded.tls_fallback,
                         board=excluded.board,
                         ca_fp=excluded.ca_fp,
                         ca_fp_match=excluded.ca_fp_match,
                         offline_notified_at=NULL""",
                    (node_id, payload.get("type", "unknown"),
                     payload.get("firmware_version"), time.time(),
                     payload.get("ip"), roles_json,
                     payload.get("reset_reason"), payload.get("mqtt_reconnects"),
                     tls, tls_fallback, board, ca_fp, ca_fp_match),
                )
                await db.commit()
            if prior is None or prior["status"] != "online":
                # A node back from offline (or heard for the first time) is
                # news to local Socket.IO clients, as a status frame is.
                await sio.emit("node_status", {"node_id": node_id, "status": "online"})
        else:
            status = payload.get("status", "unknown")
            # last_seen is when the node was last heard. Only a live "online"
            # is the node talking: a retained frame is the broker replaying a
            # stored one on (re)subscribe — a dead node's days-old LWT among
            # them — and an "offline" is the broker's LWT for a node that has
            # stopped. Either used to stamp last_seen with now, so a node gone
            # for days read "seen just now" after every Pi restart.
            heard_now = status == "online" and not retained
            async with get_db() as db:
                # A live "online" also re-arms the liveness sweeper's offline
                # page (offline_notified_at); a replayed one must not, or a
                # dead node would page again after every Pi restart.
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, status, last_seen)
                       VALUES (?, 'unknown', ?, ?)
                       ON CONFLICT(node_id) DO UPDATE SET
                         status=excluded.status,
                         last_seen=COALESCE(excluded.last_seen, hardware_nodes.last_seen),
                         offline_notified_at=CASE WHEN excluded.last_seen IS NULL
                                                  THEN hardware_nodes.offline_notified_at
                                                  END""",
                    (node_id, status, time.time() if heard_now else None),
                )
                await db.commit()
            await sio.emit("node_status", {"node_id": node_id, "status": status})

    elif msg_type == "health":
        # Component-level health from ESP32 nodes
        await sio.emit("component_health", {**payload, "node_id": node_id})
        # v4.2: the health doc is the only place a node enumerates the channel
        # names it answers to (an object keyed by name). Persist those names —
        # the node routes `cmd/<channel>` by exact match and drops anything it
        # doesn't recognise, so an automation rule naming a channel that isn't
        # here is a silent no-op. See automation.service.validate_action_channel.
        channels = payload.get("channels")
        if isinstance(channels, dict) and channels:
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, channels, last_seen)
                       VALUES (?, 'unknown', ?, ?)
                       ON CONFLICT(node_id) DO UPDATE SET channels=excluded.channels""",
                    (node_id, json.dumps(sorted(channels)), time.time()),
                )
                await db.commit()
        elif channels is None or channels == {}:
            # No channel object: the node answers to no channel (a climate
            # node, a camera; every switch or dim image always lists its
            # channels). A node re-provisioned from relay to climate kept its
            # old list, so rules on channels it no longer has still passed
            # validate_action_channel. '[]', not NULL: NULL means "never
            # reported" and passes every channel. A `channels` of any other
            # shape is not understood, so it changes nothing.
            async with get_db() as db:
                await db.execute(
                    "UPDATE hardware_nodes SET channels = '[]' "
                    "WHERE node_id = ? AND channels IS NOT NULL AND channels != '[]'",
                    (node_id,),
                )
                await db.commit()
        try:
            await forward_component_health(node_id, payload)
        except Exception as e:
            log.warning("Failed to forward component health: %s", e)

    elif msg_type == "alert":
        # v3.3.4 — log the alert-type only, not the full payload.
        # Users may include sensor thresholds in payload that, while local,
        # should still not land in journalctl verbatim at WARNING level.
        alert_kind = payload.get("kind") or payload.get("type") or "unknown"
        log.warning("Alert from node=%s kind=%s", node_id, alert_kind)
        # Every event names the node by its topic, the identity the broker's
        # per-node ACL vouches for, never by a node_id inside its payload
        # (which would let one node raise alerts in a sibling's name).
        alert = {**payload, "node_id": node_id}
        await sio.emit("alert", alert)
        await forward_event("alert", alert)
        # Local push: the engine's species-range alerts need an active session,
        # so these firmware absolute-limit alerts are the only page a headless
        # Pi sends between grows (or for a dead sensor).
        try:
            await _notify_node_alert(node_id, str(alert_kind), payload)
        except Exception as e:
            log.warning("node alert notification failed: %s", e)

    elif msg_type == "logs":
        # v4.2 — firmware log batches ({entries:[{ts_ms,level,msg}],dropped?}).
        # Previously published by nodes and consumed by nobody.
        entries = payload.get("entries")
        if isinstance(entries, list) and entries:
            async with get_db() as db:
                stored = 0
                for e in entries[:64]:  # batch sanity cap
                    if not isinstance(e, dict):
                        continue
                    msg = str(e.get("msg", ""))[:300]
                    await db.execute(
                        "INSERT INTO node_logs (node_id, ts_ms, level, msg) "
                        "VALUES (?, ?, ?, ?)",
                        (node_id, int(e.get("ts_ms", 0) or 0),
                         int(e.get("level", 1) or 1), msg),
                    )
                    stored += 1
                # Retention, in the batch's transaction: see _NODE_LOG_KEEP.
                since = _node_log_since_trim.get(node_id)
                if since is None or since + stored >= _NODE_LOG_TRIM_EVERY:
                    await db.execute(_TRIM_NODE_LOG_SQL, (node_id, node_id, _NODE_LOG_KEEP))
                    since = 0
                else:
                    since += stored
                _remember(_node_log_since_trim, node_id, since)
                await db.commit()
            dropped = payload.get("dropped")
            if dropped:
                log.warning("node %s dropped %s log entries on-device",
                            node_id, dropped)
            await sio.emit("node_log", {"node_id": node_id,
                                        "count": len(entries)})

    elif msg_type == "coredump":
        # {seq,total,size,b64_data,coredump_id} chunks, reassembled to the
        # coredump directory (hardware/coredumps.py). A completed dump means
        # the node panicked on an earlier run — surface it as an alert event.
        if len(parts) == 4 and parts[3] == "chunk":
            stored = await ingest_coredump_chunk(node_id, payload)
            if stored is None:
                return
            if stored.coredump_id is not None:
                # Store-then-ack: ingest returned only once the dump is
                # durably on disk, and only now may the node erase its flash
                # copy. A re-upload (lost ack) is acknowledged again.
                acked = await mqtt_publish(
                    f"sporeprint/{node_id}/cmd/{COREDUMP_ACK_SUFFIX}",
                    {"coredump_id": stored.coredump_id},
                )
                if not acked:
                    log.warning("coredump ack to %s not sent — the node keeps "
                                "its dump and uploads it again", node_id)
            if stored.new:
                evt = {"node_id": node_id, "type": "coredump",
                       "message": "Node panicked last boot — coredump saved",
                       "filename": stored.path.name}
                await sio.emit("alert", evt)
                await forward_event("alert", evt)

    elif msg_type == "ota":
        # v4.2 — node firmware OTA lifecycle visibility (start/success/
        # error from ArduinoOTA). Forwarded as a node_ota event so remote
        # operators can see node updates; this is visibility only — pushing
        # images stays a LAN operation.
        evt = {**payload, "node_id": node_id}
        # A push waiting for the node's answer to its signed manifest.
        note_node_ota_event(node_id, payload)
        await sio.emit("node_ota", evt)
        # forward_event's envelope is {"type": "node_ota", "ts": <Pi time>,
        # **data}, so the node's own keys must not shadow it: a start event's
        # `type` (firmware | filesystem) turned the event into a "firmware"
        # one, and the node's `ts` (uptime before an NTP sync) replaced the
        # Pi's. They ride along as ota_type / node_ts.
        relay = {k: v for k, v in payload.items() if k not in ("type", "ts")}
        await forward_event("node_ota", {
            **relay, "node_id": node_id,
            "ota_type": payload.get("type"), "node_ts": payload.get("ts"),
        })


_CA_FP_RE = re.compile(r"^[0-9a-f]{64}$")
# node -> the ca_fp last warned about (capped like the clock tables).
_ca_mismatch_logged: dict[str, str] = {}


def _heartbeat_tls_fields(node_id: str, payload: dict) -> tuple:
    """(tls, tls_fallback, board, ca_fp, ca_fp_match) for the heartbeat upsert.

    tls / tls_fallback are 1/0, or None from an image that reports neither.
    ca_fp is the SHA-256 of the CA PEM the node's TLS link pinned; ca_fp_match
    is 1 when it is the CA this Pi serves (GET /api/provision/ca), 0 when it
    is another one — the node trusted a different CA on first use, or the
    broker's certificate no longer comes from the CA the Pi serves — and None
    when either side is unknown. A mismatch is logged once per fingerprint.
    """
    tls_raw = payload.get("tls")
    tls = int(tls_raw) if isinstance(tls_raw, bool) else None
    # Emitted only when true, so its absence means false on an image that
    # reports tls at all.
    if payload.get("tls_fallback") is True:
        tls_fallback = 1
    else:
        tls_fallback = 0 if tls is not None else None
    board_raw = payload.get("board")
    board = board_raw[:64] if isinstance(board_raw, str) and board_raw else None
    fp_raw = payload.get("ca_fp")
    ca_fp = fp_raw if isinstance(fp_raw, str) and _CA_FP_RE.match(fp_raw) else None
    served = served_ca_fingerprint() if ca_fp is not None else None
    if ca_fp is None or served is None:
        _ca_mismatch_logged.pop(node_id, None)
        return tls, tls_fallback, board, ca_fp, None
    if ca_fp == served:
        _ca_mismatch_logged.pop(node_id, None)
        return tls, tls_fallback, board, ca_fp, 1
    if _ca_mismatch_logged.get(node_id) != ca_fp:
        _remember(_ca_mismatch_logged, node_id, ca_fp)
        log.warning(
            "[SEC] node %s verifies the broker against CA %s…, not the CA this "
            "Pi serves (%s…): it trusted a different CA when it was set up, or "
            "the broker's certificate is not from this Pi's CA. Re-provision the "
            "node's Secure MQTT if the CA was regenerated.",
            node_id, ca_fp[:16], served[:16],
        )
    return tls, tls_fallback, board, ca_fp, 0


async def _reading_normal_for_grow(node_id: str, alert_type: str, value) -> bool:
    """Is a firmware absolute-limit reading normal for the grow the node drives?

    The node's limits are fixed (above 4000 ppm CO2, below 40 °F or above
    90 °F, RH below 30 % or above 99 %), and phases the engine treats as normal
    cross them: colonization holds CO2 at 5000-15000 ppm with no fresh air, cold
    storage holds 35-40 °F. Paged regardless, they sent a CRITICAL every hour
    for the whole phase. So, with a grow the engine manages (the same session,
    phase setpoints and container rule as evaluate_rules):
      * co2 is normal while the phase runs no fresh air (fae_mode "none") or is
        within its ceiling; the engine's life-safety check still pages a level
        dangerous to people;
      * temperature and humidity are normal inside the phase's band, and a
        low humidity also in a phase that does not drive humidity (cold
        storage: a fridge idles dry);
      * co2 and humidity say nothing about a sealed vessel's interior (the
        engine's stage alerts skip them too).
    With no managed grow, or when the lookup fails, nothing is normal and the
    alert pages as before: between grows these are a headless Pi's only pages.
    """
    if alert_type not in ("temperature", "co2", "humidity"):
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return False
    # Late import: the engine imports this module (mqtt_publish).
    from .automation import engine
    try:
        session, _ = await engine._session_for_node(node_id)
        if not session:
            return False
        profile = await engine.get_profile(session["species_profile_id"])
        if profile is not None and not getattr(profile, "chamber_cultivable", True):
            return False  # reference-only species: the engine manages nothing
        params = engine._resolve_phase_params(session, profile)
        if params is None:
            return False
        sealed = engine._container_is_sealed(session.get("container_type"),
                                             session["current_phase"])
    except Exception as e:
        log.warning("resolving %s's grow for its %s alert failed: %s", node_id, alert_type, e)
        return False
    if alert_type == "temperature":
        return params.temp_min_f <= value <= params.temp_max_f
    if sealed:
        return True
    if alert_type == "co2":
        return getattr(params, "fae_mode", None) == "none" or value <= params.co2_max_ppm
    low_ok = (not getattr(params, "humidity_driven", True)
              or value >= params.humidity_min)
    return low_ok and value <= params.humidity_max


async def _notify_node_alert(node_id: str, alert_type: str, payload: dict) -> None:
    """Push a firmware alert frame to ntfy, tiered and deduplicated.

    temperature / co2 / sensor_failure page CRITICAL, humidity WARNING, and a
    door opening INFO (a door closing is not pushed). Unknown types from newer
    firmware page WARNING rather than being dropped. The dedup key includes the
    frame's `sensor`, since one alert type (sensor_failure) covers several.
    A temperature, co2 or humidity reading the node's grow treats as normal
    is not pushed (see _reading_normal_for_grow).
    """
    if alert_type == "door":
        try:
            opened = float(payload.get("value", 0)) >= 1.0
        except (TypeError, ValueError):
            opened = False
        if not opened:
            return
    value = payload.get("value")
    if await _reading_normal_for_grow(node_id, alert_type, value):
        log.debug("node %s %s alert (value %s) is normal for its grow's phase; not paged",
                  node_id, alert_type, value)
        return
    priority = _NODE_ALERT_PRIORITY.get(alert_type, "warning")
    message = str(payload.get("message") or alert_type.replace("_", " "))
    has_reading = alert_type not in ("door", "sensor_failure")
    if has_reading and isinstance(value, (int, float)) and not isinstance(value, bool):
        message = f"{message} (value {value:g})"
    sensor = str(payload.get("sensor") or "")[:32]
    title = f"Node {node_id}: {alert_type.replace('_', ' ')} alert"
    if sensor:
        title += f" ({sensor})"
    await notify(
        title,
        message,
        priority=priority,
        tags=["warning"] if priority == "critical" else ["mushroom"],
        dedup_key=f"node_alert:{node_id}:{alert_type}:{sensor}",
        dedup_seconds=_NODE_ALERT_DEDUP_SECONDS[priority],
    )
