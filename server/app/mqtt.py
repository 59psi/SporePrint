import asyncio
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


async def mqtt_publish(topic: str, payload: dict) -> bool:
    if _client is None:
        return False
    try:
        await _client.publish(topic, json.dumps(payload))
        return True
    except Exception as e:
        log.warning("mqtt_publish to %s failed: %s", topic, e)
        return False


async def start_mqtt(sio):
    global _client, _mqtt_restart_count
    while True:
        try:
            mqtt_kwargs = {}
            if settings.mqtt_username:
                mqtt_kwargs["username"] = settings.mqtt_username
                mqtt_kwargs["password"] = settings.mqtt_password
            async with aiomqtt.Client(settings.mqtt_host, settings.mqtt_port, **mqtt_kwargs) as client:
                _client = client
                await client.subscribe("sporeprint/#")
                await client.subscribe("shellies/#")
                await client.subscribe("tasmota/#")
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
            log.warning("MQTT disconnected: %s — reconnecting in 5s", e)
            _client = None
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            _client = None
            return
        except Exception as e:
            _client = None
            _mqtt_restart_count += 1
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
        log.warning("Alert from %s: %s", node_id, payload)
        await sio.emit("alert", {"node_id": node_id, **payload})
        await forward_event("alert", {"node_id": node_id, **payload})

    # Handle smart plug messages (Shelly / Tasmota)
    if topic.startswith("shellies/") or topic.startswith("tasmota/"):
        from .automation.smart_plugs import handle_plug_message
        await handle_plug_message(sio, topic, payload)
