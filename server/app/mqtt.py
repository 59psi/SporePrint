import asyncio
import json
import logging
import time

import aiomqtt

from .cloud.service import forward_telemetry, forward_event
from .config import settings
from .telemetry.service import store_bulk_readings
from .db import get_db

log = logging.getLogger(__name__)

_client: aiomqtt.Client | None = None


async def mqtt_publish(topic: str, payload: dict):
    if _client:
        await _client.publish(topic, json.dumps(payload))


async def start_mqtt(sio):
    global _client
    while True:
        try:
            async with aiomqtt.Client(settings.mqtt_host, settings.mqtt_port) as client:
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

                    await _handle_message(sio, topic, payload)

        except aiomqtt.MqttError as e:
            log.warning("MQTT disconnected: %s — reconnecting in 5s", e)
            _client = None
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            _client = None
            return


async def _handle_message(sio, topic: str, payload: dict):
    parts = topic.split("/")
    if len(parts) < 3:
        return

    node_id = parts[1]
    msg_type = parts[2]

    if msg_type == "telemetry":
        ts = payload.get("ts", time.time())
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

    elif msg_type == "alert":
        log.warning("Alert from %s: %s", node_id, payload)
        await sio.emit("alert", {"node_id": node_id, **payload})
        await forward_event("alert", {"node_id": node_id, **payload})

    # Handle smart plug messages (Shelly / Tasmota)
    if topic.startswith("shellies/") or topic.startswith("tasmota/"):
        from .automation.smart_plugs import handle_plug_message
        await handle_plug_message(sio, topic, payload)
