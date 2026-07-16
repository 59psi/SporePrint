import asyncio
import hashlib
import hmac
import json
import logging
import time

import aiomqtt

from .cloud.service import forward_telemetry, forward_event, forward_component_health
from .config import settings
from .telemetry.service import store_bulk_readings
from .db import get_db

log = logging.getLogger(__name__)

_client: aiomqtt.Client | None = None

# Any ts < 2020-01-01 is firmware uptime-seconds, not real epoch. Clamp to now.
_EPOCH_2020 = 1577836800
_uptime_ts_clamp_count = 0
_mqtt_restart_count = 0


def get_reliability_counters() -> dict:
    return {
        "uptime_ts_clamps": _uptime_ts_clamp_count,
        "mqtt_supervisor_restarts": _mqtt_restart_count,
    }


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


async def start_mqtt(sio):
    global _client, _mqtt_restart_count
    from .health.service import update_task
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
                    try:
                        payload = json.loads(message.payload.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
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


async def _handle_message(sio, topic: str, payload: dict):
    global _uptime_ts_clamp_count
    parts = topic.split("/")
    if len(parts) < 3:
        return

    node_id = parts[1]
    msg_type = parts[2]

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
            await db.commit()
        await sio.emit("actuator_state", {"node_id": node_id, **payload})
        # Keep the cloud forward — remote clients render live actuator state
        # from these frames; only the pointless local store + rules eval stops.
        await forward_telemetry(node_id, payload)

    elif msg_type == "telemetry":
        received_at = time.time()
        raw_ts = payload.get("ts", received_at)
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            ts = received_at
        if ts < _EPOCH_2020:
            _uptime_ts_clamp_count += 1
            log.warning("uptime-style ts %s from %s, replacing with server time", raw_ts, node_id)
            ts = received_at
        payload["ts"] = ts

        await store_bulk_readings(node_id, payload, ts)
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

    # Handle smart plug messages (Shelly / Tasmota)
    if topic.startswith("shellies/") or topic.startswith("tasmota/"):
        from .automation.smart_plugs import handle_plug_message
        await handle_plug_message(sio, topic, payload)
