import asyncio
import hashlib
import hmac
import json
import logging
import math
import secrets
import time

import aiomqtt

from .cloud.service import forward_telemetry, forward_event, forward_component_health
from .config import settings
from .notifications.service import notify
from .telemetry.service import (
    active_session_for_node,
    latest_node_timestamp,
    store_bulk_readings,
)
from .db import get_db

log = logging.getLogger(__name__)

_client: aiomqtt.Client | None = None

# Telemetry `ts` wire contract (firmware <-> Pi):
#   * ts is Unix-epoch seconds once the node's clock is NTP-synced. Anything
#     below 1e9 (2001-09-09) is an unsynced node's uptime, never a real epoch,
#     and is replaced with the Pi's arrival time.
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
_UNSYNCED_TS_BELOW = 1_000_000_000
_uptime_ts_clamp_count = 0
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
# own configured account (settings.mqtt_username) is reserved too.
# tests/test_mqtt_acl_contract.py keeps this in step with acl.conf and
# scripts/rotate-mqtt-creds.sh.
RESERVED_NODE_IDS = frozenset({"server", "sp-3p", "sp-cmd", "sp-telemetry"})
# Reserved ids already warned about, lowercased (so it can only ever hold the
# few reserved names and needs no cap).
_reserved_drop_logged: set[str] = set()


def is_reserved_node_id(node_id: str) -> bool:
    """Is `node_id` a broker service account name (never a node)? Case-insensitive."""
    name = str(node_id or "").strip().lower()
    if not name:
        return False
    return name in RESERVED_NODE_IDS or name == (settings.mqtt_username or "").strip().lower()


async def purge_reserved_nodes() -> int:
    """Delete hardware_nodes rows an older server registered under a reserved id.

    Before the filter in _handle_message, any service account's status frame
    upserted a node row, and a row is what admits keyless camera uploads and
    cloud target_kind routing. Returns the number of rows removed.
    """
    names = sorted(RESERVED_NODE_IDS | {(settings.mqtt_username or "").strip().lower()} - {""})
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

# Shelly / Tasmota publish on their own topic trees, often as bare text.
_VENDOR_PLUG_PREFIXES = ("shellies/", "tasmota/")

# Telemetry frames also refresh a registered node's liveness (srv-hw#22): the
# offline sweeper in main.py reads last_seen, which only status/* frames used
# to write. UPDATE only — status changes stay with the heartbeat/LWT path, and
# telemetry never registers a node (registration gates keyless camera uploads).
_TOUCH_LAST_SEEN_SQL = (
    "UPDATE hardware_nodes SET last_seen = MAX(COALESCE(last_seen, 0), ?) "
    "WHERE node_id = ?"
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
        "mqtt_supervisor_restarts": _mqtt_restart_count,
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

    v3.4.9 C-1 — the firmware's verifyFrame expects:
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
      channel or node (fw-node#11).
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
            # command silently (the archaeology's top finding).
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


def _decode_payload(topic: str, raw: bytes):
    """Decode one MQTT payload for routing; None means drop the frame.

    sporeprint/* frames are JSON objects, nothing else. Shelly and Tasmota
    publish their relay state as bare text (`on`/`off`, `ON`/`OFF`), so for
    those topics a payload that isn't JSON is passed through as the stripped
    string. Numeric power reports and Tasmota's JSON telemetry still parse.
    """
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
                    topic = str(message.topic)
                    # $SYS payloads are plain text — handle before the JSON
                    # parse below would silently drop them.
                    if topic.startswith("$SYS/"):
                        _handle_sys_message(topic, bytes(message.payload or b""))
                        continue
                    payload = _decode_payload(topic, bytes(message.payload or b""))
                    if payload is None:
                        continue

                    try:
                        await _handle_message(sio, topic, payload)
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


async def _handle_message(sio, topic: str, payload):
    global _uptime_ts_clamp_count
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
        # A service account publishing through the per-node ACL patterns
        # (see RESERVED_NODE_IDS): never a node, never rules input.
        if node_id.lower() not in _reserved_drop_logged:
            _reserved_drop_logged.add(node_id.lower())
            log.warning("[SEC] dropping sporeprint/%s/%s frames: %r is a broker "
                        "service account, not a node", node_id, msg_type, node_id)
        return

    if msg_type == "telemetry" and len(parts) == 4:
        # telemetry/<channel> — a relay-bank switch-state report
        # {channel, state, pwm, trigger}, published on every command, safety
        # cutoff, and 60s cadence. These used to funnel through the sensor
        # path below, where store_bulk_readings stored nothing (no key overlaps
        # SENSOR_FIELDS) — so the actuator_events table, built for exactly this
        # feed, had no writer and Grafana's actuator_event_count sat at zero.
        received_at = time.time()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO actuator_events (timestamp, node_id, channel, action, value, trigger)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    received_at, node_id,
                    payload.get("channel", parts[3]),
                    payload.get("state", "unknown"),
                    payload.get("pwm"),
                    payload.get("trigger", "report"),
                ),
            )
            await db.execute(_TOUCH_LAST_SEEN_SQL, (received_at, node_id))
            await db.commit()
        await sio.emit("actuator_state", {"node_id": node_id, **payload})
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

    elif msg_type == "telemetry":
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
        if not node_clock:
            if math.isfinite(ts):
                # Unsynced node clock: the ts is uptime, not wall time.
                _uptime_ts_clamp_count += 1
                log.debug("unsynced ts %s from %s, stamping arrival time", raw_ts, node_id)
            ts = received_at
            if replay:
                # A replayed unsynced frame's real time is unrecoverable but is
                # certainly older than what the node already reported live.
                # Never let it land after (and so shadow) the latest reading.
                newest = await latest_node_timestamp(node_id)
                if newest is not None and newest <= ts:
                    ts = newest - 0.001
        not_live = _classify_frame(node_id, ts, replay=replay, node_clock=node_clock,
                                   received_at=received_at)
        payload["ts"] = ts

        # Tag the reading with the grow its node was part of at `ts`
        # (transcripts and the per-session telemetry endpoint resolve by
        # session_id). Per node: chambered grows can run side by side.
        session_id = await active_session_for_node(node_id, ts)

        try:
            await store_bulk_readings(node_id, payload, ts, session_id=session_id)
        except Exception as e:
            # e.g. "database is locked" while the nightly retention job holds
            # the write lock. Losing the history row must not also cost a live
            # frame its rules evaluation (safety cutoffs included).
            log.warning("storing telemetry from %s failed: %s", node_id, e)
        # Any frame (replayed ones too) proves the node is up right now.
        try:
            async with get_db() as db:
                await db.execute(_TOUCH_LAST_SEEN_SQL, (received_at, node_id))
                await db.commit()
        except Exception as e:
            log.warning("refreshing last_seen for %s failed: %s", node_id, e)
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
        await sio.emit("telemetry", {"node_id": node_id, **payload})
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

        # Evaluate automation rules against enriched readings
        from .automation.engine import evaluate_rules
        try:
            await evaluate_rules(node_id, enriched, sio)
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
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, firmware_version, last_seen, ip_address, status, roles, reset_reason, mqtt_reconnects)
                       VALUES (?, ?, ?, ?, ?, 'online', ?, ?, ?)
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
                         mqtt_reconnects=COALESCE(excluded.mqtt_reconnects, hardware_nodes.mqtt_reconnects)""",
                    (node_id, payload.get("type", "unknown"),
                     payload.get("firmware_version"), time.time(),
                     payload.get("ip"), roles_json,
                     payload.get("reset_reason"), payload.get("mqtt_reconnects")),
                )
                await db.commit()
        else:
            status = payload.get("status", "unknown")
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, status, last_seen)
                       VALUES (?, 'unknown', ?, ?)
                       ON CONFLICT(node_id) DO UPDATE SET status=excluded.status, last_seen=excluded.last_seen""",
                    (node_id, status, time.time()),
                )
                await db.commit()
            await sio.emit("node_status", {"node_id": node_id, "status": status})

    elif msg_type == "health":
        # Component-level health from ESP32 nodes
        await sio.emit("component_health", {"node_id": node_id, **payload})
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
        await sio.emit("alert", {"node_id": node_id, **payload})
        await forward_event("alert", {"node_id": node_id, **payload})
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
                # Retention: keep the newest ~10k rows per node.
                await db.execute(
                    """DELETE FROM node_logs WHERE node_id = ? AND id NOT IN
                       (SELECT id FROM node_logs WHERE node_id = ?
                        ORDER BY id DESC LIMIT 10000)""",
                    (node_id, node_id),
                )
                await db.commit()
            dropped = payload.get("dropped")
            if dropped:
                log.warning("node %s dropped %s log entries on-device",
                            node_id, dropped)
            await sio.emit("node_log", {"node_id": node_id,
                                        "count": len(entries)})

    elif msg_type == "coredump":
        # v4.2 — {seq,total,size,b64_data} chunks; reassembled to
        # data/coredumps/. A completed dump means the node panicked on its
        # previous run — surface it as an alert event.
        if len(parts) == 4 and parts[3] == "chunk":
            from .hardware.coredumps import ingest_chunk
            written = ingest_chunk(node_id, payload)
            if written is not None:
                evt = {"node_id": node_id, "type": "coredump",
                       "message": "Node panicked last boot — coredump saved",
                       "filename": written.name}
                await sio.emit("alert", evt)
                await forward_event("alert", evt)

    elif msg_type == "ota":
        # v4.2 — node firmware OTA lifecycle visibility (start/success/
        # error from ArduinoOTA). Forwarded as a node_ota event so remote
        # operators can see node updates; this is visibility only — pushing
        # images stays a LAN operation.
        evt = {"node_id": node_id, **payload}
        await sio.emit("node_ota", evt)
        await forward_event("node_ota", evt)


async def _notify_node_alert(node_id: str, alert_type: str, payload: dict) -> None:
    """Push a firmware alert frame to ntfy, tiered and deduplicated.

    temperature / co2 / sensor_failure page CRITICAL, humidity WARNING, and a
    door opening INFO (a door closing is not pushed). Unknown types from newer
    firmware page WARNING rather than being dropped. The dedup key includes the
    frame's `sensor`, since one alert type (sensor_failure) covers several.
    """
    if alert_type == "door":
        try:
            opened = float(payload.get("value", 0)) >= 1.0
        except (TypeError, ValueError):
            opened = False
        if not opened:
            return
    priority = _NODE_ALERT_PRIORITY.get(alert_type, "warning")
    message = str(payload.get("message") or alert_type.replace("_", " "))
    value = payload.get("value")
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
