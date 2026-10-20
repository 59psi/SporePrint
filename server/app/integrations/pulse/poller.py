"""One Pulse Grow poll: fetch each device's latest sample and store the new
ones in telemetry history.

Mapped measurement types:

  Pulse 'type'     | SporePrint sensor
  -----------------|--------------------
  temperature      | temp_c      (°F converted to °C)
  humidity         | humidity
  vpd              | vpd_kpa     (unit-prefixed name — VPD is not a
                                  legacy SporePrint sensor; new lane)
  dew_point        | dew_point_f (converted C -> F at ingest — the
                                  canonical name the firmware emits, so
                                  Pulse dew point flows through Grafana,
                                  analytics, and export like any other)
  light            | lux

`vpd_kpa` is the one new sensor name this driver introduces into
telemetry (VPD is not a firmware sensor; new lane, invisible to Grafana
until chamber UI grows VPD widgets). Everything else maps onto canonical
firmware names — vendor readings must not mint parallel names for
sensors the firmware already emits, or they fork the pipeline (the old
`dew_point_c` was persisted but invisible to Grafana/export for exactly
that reason).

``recent-data?limit=1`` returns a device's latest sample whether or not it
is new, so a sample already stored is skipped, a new one is stored at the
time the device took it, and a device whose sample stops changing is
reported stale (SampleTracker, ``_samples.py``).
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from ...telemetry.service import store_readings
from .._samples import PollResult, SampleTracker, finite, is_fahrenheit
from .client import PulseCloudClient, PulseError
from .config import PulseConfig
from .local_transport import PulseLocalTransport
from .models import PulseRecentDataResponse


logger = logging.getLogger(__name__)


_TYPE_MAP: dict[str, str] = {
    "temperature": "temp_c",
    "humidity": "humidity",
    "vpd": "vpd_kpa",
    "dew_point": "dew_point_f",
    "light": "lux",
}

# Pulse devices take a sample about every minute: a device's latest sample
# is stale once it is this old (or three polls, when that is longer).
STALE_FLOOR_SECONDS = 10 * 60

Writer = Callable[[list[tuple[float, str, str, float]]], Awaitable[int]]


def _node_id_for(device_id: str) -> str:
    return f"pulse:{device_id}"


def mapped_readings(
    response: PulseRecentDataResponse,
) -> list[tuple[str, str, float, object]]:
    """(node id, SporePrint sensor, value, sample timestamp) for every
    measurement of a mapped type that carries a number, in SporePrint's
    units. Unknown measurement types are skipped (logged at debug)."""
    if response.device_id is None:
        return []
    node_id = _node_id_for(response.device_id)
    readings: list[tuple[str, str, float, object]] = []
    for m in response.measurements:
        sp_sensor = _TYPE_MAP.get(m.type)
        if sp_sensor is None:
            logger.debug(
                "pulse: skipping unmapped measurement type %r on device %s",
                m.type,
                response.device_id,
            )
            continue
        value = finite(m.value)
        if value is None:
            continue
        fahrenheit = is_fahrenheit(m.unit)
        if m.type == "temperature" and fahrenheit:
            value = (value - 32.0) * 5.0 / 9.0
        elif m.type == "dew_point" and not fahrenheit:
            value = value * 9.0 / 5.0 + 32.0  # Pulse reports metric
        readings.append((node_id, sp_sensor, value, m.timestamp))
    return readings


def _make_transport_for(cfg: PulseConfig):
    """Construct the right transport for the configured mode."""
    if cfg.transport == "local":
        return PulseLocalTransport(cfg)
    if not cfg.email or not cfg.password:
        raise PulseError("email and password are required for cloud transport")
    return PulseCloudClient(
        cfg.email,
        cfg.password,
        timeout_s=cfg.request_timeout_seconds,
    )


async def run_one_poll(
    cfg: PulseConfig,
    *,
    client=None,
    tracker: SampleTracker | None = None,
    writer: Writer | None = None,
    now: float | None = None,
) -> PollResult:
    """One poll cycle: list the devices, fetch each one's latest sample, and
    store the new samples in one transaction.

    A device whose fetch fails is reported in the result's ``failed`` and
    does not stop its siblings. `client` (the cloud client must be reused so
    its session token survives between polls), `tracker` and `writer` are
    injectable; without a tracker every sample counts as new.
    """
    if client is None:
        client = _make_transport_for(cfg)
    if tracker is None:
        tracker = SampleTracker(STALE_FLOOR_SECONDS)

    devices = await client.list_devices()
    readings: list[tuple[str, str, float, object]] = []
    failed: dict[str, str] = {}
    for device in devices.devices:
        try:
            response = await client.recent_data(device.id)
        except PulseError as exc:
            logger.warning(
                "pulse: recent-data fetch failed for device %s: %s", device.id, exc
            )
            failed[_node_id_for(device.id)] = str(exc)
            continue
        readings.extend(mapped_readings(response))
    rows, stale = tracker.keep_new(
        readings,
        poll_seconds=cfg.poll_seconds,
        now=time.time() if now is None else now,
    )
    written = await (writer or store_readings)(rows) if rows else 0
    return PollResult(written, len(devices.devices), {**stale, **failed})
