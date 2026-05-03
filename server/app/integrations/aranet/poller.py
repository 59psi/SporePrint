"""Background poller — fetches Aranet readings on a schedule and publishes
them into the existing telemetry pipeline.

Aranet measurement types we map into SporePrint sensor names:

  Aranet 'type'         | SporePrint sensor
  ----------------------|--------------------
  temperature           | temp_c
  humidity              | humidity
  co2                   | co2_ppm

Other types (atmospheric_pressure, radiation_dose_rate, soil_*) are
returned by ``GET /api/integrations/aranet/discover`` so the operator
can see them, but they don't drive automation in this phase. Adding
them is a one-line entry in `_TYPE_MAP` once the chamber UI grows
support for the corresponding sensor name.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from ...telemetry.service import store_reading
from .client import AranetClient, AranetError
from .config import AranetConfig
from .models import AranetMeasurementsResponse, AranetSensor


logger = logging.getLogger(__name__)


# Aranet measurement-type → SporePrint sensor name. Aranet returns
# Celsius/percent/ppm natively, so no unit conversion is needed.
_TYPE_MAP: dict[str, str] = {
    "temperature": "temp_c",
    "humidity": "humidity",
    "co2": "co2_ppm",
}


def _node_id_for(sensor_id: str) -> str:
    """Synthetic node id used when writing Aranet rows into telemetry."""
    return f"aranet:{sensor_id}"


async def _publish_sensor(
    sensor: AranetSensor,
    chamber_id: str | None,
    *,
    publisher: Callable[[str, str, float, float], Awaitable[None]],
) -> int:
    """Publish all mapped measurements for one sensor. Returns count
    written. Unknown measurement types are skipped (logged at debug).
    """
    written = 0
    now = time.time()
    node_id = _node_id_for(sensor.id)
    for m in sensor.measurements:
        sp_sensor = _TYPE_MAP.get(m.type)
        if sp_sensor is None:
            logger.debug(
                "aranet: skipping unmapped measurement type %r on sensor %s",
                m.type,
                sensor.id,
            )
            continue
        try:
            await publisher(node_id, sp_sensor, float(m.value), now)
            written += 1
        except Exception:  # noqa: BLE001 — must not poison sibling sensors
            logger.exception(
                "aranet: failed to persist %s/%s for sensor %s",
                sp_sensor,
                m.value,
                sensor.id,
            )
    return written


async def run_one_poll(
    cfg: AranetConfig,
    *,
    client: AranetClient | None = None,
    publisher: Callable[[str, str, float, float], Awaitable[None]] | None = None,
) -> tuple[int, AranetMeasurementsResponse]:
    """One poll cycle. Returns (rows_written, raw_response).

    Both `client` and `publisher` are injectable so the poller can be
    driven from a unit test without an HTTP server.
    """
    own_client = client is None
    if own_client:
        client = AranetClient(
            cfg.base_url, cfg.api_key, timeout_s=cfg.request_timeout_seconds
        )
    if publisher is None:
        publisher = store_reading

    try:
        response = await client.fetch_latest()
    except AranetError:
        raise

    written = 0
    for sensor in response.sensors:
        chamber_id = cfg.sensor_mappings.get(sensor.id)
        written += await _publish_sensor(
            sensor, chamber_id, publisher=publisher
        )
    return written, response


async def poll_loop(
    cfg_provider: Callable[[], AranetConfig],
    *,
    record_outcome: Callable[[bool, str | None], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Long-running poll task. Reads config on each tick so config
    edits take effect within one interval without restarting the task.
    """
    while True:
        cfg = cfg_provider()
        # Defensive: an empty base_url means the operator disabled the
        # driver mid-loop. Sleep one interval and re-check.
        if not cfg.base_url or not cfg.api_key:
            await sleep(cfg.poll_seconds)
            continue
        try:
            await run_one_poll(cfg)
            record_outcome(True, None)
        except AranetError as exc:
            logger.warning("aranet poll failed: %s", exc)
            record_outcome(False, str(exc))
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("aranet poll crashed")
            record_outcome(False, str(exc))
        await sleep(cfg.poll_seconds)
