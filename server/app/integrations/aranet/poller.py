"""One Aranet PRO poll: fetch each sensor's latest sample and store the new
ones in telemetry history.

Aranet measurement types we map into SporePrint sensor names:

  Aranet 'type'         | SporePrint sensor
  ----------------------|--------------------
  temperature           | temp_c
  humidity              | humidity
  co2                   | co2_ppm

The PRO serves each sensor's latest sample, and an Aranet4 radios one only
every 1-10 minutes, so most polls return a sample that is already stored.
A new sample is stored once, at the time the sensor took it, and a sensor
whose sample stops changing is reported stale instead of being stored again
as if it were fresh (SampleTracker, ``_samples.py``). A temperature the PRO
reports in °F is converted to °C.

Other types (atmospheric_pressure, radiation_dose_rate, soil_*) are
returned by ``GET /api/integrations/aranet/discover`` so the operator
can see them, but they are not stored. Adding them is a one-line entry
in `_TYPE_MAP` once the chamber UI grows support for the corresponding
sensor name.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from ...telemetry.service import store_readings
from .._samples import PollResult, SampleTracker, finite, is_fahrenheit
from .client import AranetClient
from .config import AranetConfig
from .models import AranetMeasurementsResponse


logger = logging.getLogger(__name__)


# Aranet measurement-type → SporePrint sensor name.
_TYPE_MAP: dict[str, str] = {
    "temperature": "temp_c",
    "humidity": "humidity",
    "co2": "co2_ppm",
}

# An Aranet4 radios a sample every 1-10 minutes, so a healthy sensor's latest
# sample can be 10 minutes old: it is stale only after three of those.
STALE_FLOOR_SECONDS = 30 * 60

Writer = Callable[[list[tuple[float, str, str, float]]], Awaitable[int]]


def _node_id_for(sensor_id: str) -> str:
    """Synthetic node id used when writing Aranet rows into telemetry."""
    return f"aranet:{sensor_id}"


def mapped_readings(
    response: AranetMeasurementsResponse,
) -> list[tuple[str, str, float, object]]:
    """(node id, SporePrint sensor, value, sample timestamp) for every
    measurement of a mapped type that carries a number. Unknown measurement
    types are skipped (logged at debug)."""
    readings: list[tuple[str, str, float, object]] = []
    for sensor in response.sensors:
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
            value = finite(m.value)
            if value is None:
                continue
            if sp_sensor == "temp_c" and is_fahrenheit(m.unit):
                value = (value - 32.0) * 5.0 / 9.0
            readings.append((node_id, sp_sensor, value, m.timestamp))
    return readings


async def run_one_poll(
    cfg: AranetConfig,
    *,
    client: AranetClient | None = None,
    tracker: SampleTracker | None = None,
    writer: Writer | None = None,
    now: float | None = None,
) -> PollResult:
    """One poll cycle: fetch, keep the new samples, store them in one
    transaction.

    `client`, `tracker` and `writer` are injectable so the poller can be
    driven from a unit test without an HTTP server or a database. Without a
    tracker every sample counts as new.
    """
    if client is None:
        client = AranetClient(
            cfg.base_url, cfg.api_key, timeout_s=cfg.request_timeout_seconds
        )
    if tracker is None:
        tracker = SampleTracker(STALE_FLOOR_SECONDS)
    response = await client.fetch_latest()
    readings = mapped_readings(response)
    rows, stale = tracker.keep_new(
        readings,
        poll_seconds=cfg.poll_seconds,
        now=time.time() if now is None else now,
    )
    written = await (writer or store_readings)(rows) if rows else 0
    return PollResult(written, len({node_id for node_id, *_ in readings}), stale)
