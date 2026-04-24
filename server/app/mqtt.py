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
    sporeprint/firmware/lib/sporeprint_common/frame_verify.cpp#canonicalize.

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


async def mqtt_publish(topic: str, payload: dict) -> bool:
    if _client is None:
        return False

    # Sign any cmd/* frame so the firmware can verify authenticity.
    # Non-cmd topics (state/*, telemetry/*) don't need signing because they
    # flow node→Pi, not Pi→node, and the Pi is the trust root.
    outbound = payload
    if "/cmd/" in topic or topic.endswith("/cmd") or "cmd/" in topic.split("/")[-2:][0]:
        outbound = _sign_cmd_payload(payload)

    try:
        await _client.publish(topic, json.dumps(outbound))
        return True
    except Exception as e:
        log.warning("mqtt_publish to %s failed: %s", topic, e)
        return False


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
                update_task("mqtt", "running")
                log.info("MQTT connected to %s:%d", settings.mqtt_host, settings.mqtt_port)

                async for message in client.messages:
                    topic = str(message.topic)
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

    if msg_type == "telemetry":
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
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO hardware_nodes (node_id, node_type, firmware_version, last_seen, ip_address, status)
                       VALUES (?, ?, ?, ?, ?, 'online')
                       ON CONFLICT(node_id) DO UPDATE SET
                         firmware_version=excluded.firmware_version,
                         last_seen=excluded.last_seen,
                         ip_address=excluded.ip_address,
                         status='online'""",
                    (node_id, payload.get("type", "unknown"),
                     payload.get("firmware_version"), time.time(),
                     payload.get("ip")),
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

    # Handle smart plug messages (Shelly / Tasmota)
    if topic.startswith("shellies/") or topic.startswith("tasmota/"):
        from .automation.smart_plugs import handle_plug_message
        await handle_plug_message(sio, topic, payload)
