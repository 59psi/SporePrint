"""Pulse Grow poller — fetches device readings on a schedule and publishes
them into the existing telemetry pipeline.

Mapped measurement types:

  Pulse 'type'     | SporePrint sensor
  -----------------|--------------------
  temperature      | temp_c
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
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from ...telemetry.service import store_reading
from .client import PulseCloudClient, PulseError
from .config import PulseConfig
from .models import PulseRecentDataResponse


logger = logging.getLogger(__name__)


_TYPE_MAP: dict[str, str] = {
    "temperature": "temp_c",
    "humidity": "humidity",
    "vpd": "vpd_kpa",
    "dew_point": "dew_point_f",
    "light": "lux",
}


def _node_id_for(device_id: str) -> str:
    return f"pulse:{device_id}"


async def _publish_device(
    response: PulseRecentDataResponse,
    *,
    publisher: Callable[[str, str, float, float], Awaitable[None]],
) -> int:
    if response.device_id is None:
        return 0
    node_id = _node_id_for(response.device_id)
    written = 0
    now = time.time()
    for m in response.measurements:
        sp_sensor = _TYPE_MAP.get(m.type)
        if sp_sensor is None:
            logger.debug(
                "pulse: skipping unmapped measurement type %r on device %s",
                m.type,
                response.device_id,
            )
            continue
        value = float(m.value)
        if m.type == "dew_point":
            value = value * 9.0 / 5.0 + 32.0  # Pulse reports metric
        try:
            await publisher(node_id, sp_sensor, value, now)
            written += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "pulse: failed to persist %s/%s for device %s",
                sp_sensor,
                m.value,
                response.device_id,
            )
    return written


def _make_transport_for(cfg: PulseConfig):
    """Construct the right transport for the configured mode. Imported
    lazily to keep the module's import graph cycle-free.
    """
    if cfg.transport == "local":
        from .local_transport import PulseLocalTransport
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
    publisher: Callable[[str, str, float, float], Awaitable[None]] | None = None,
) -> tuple[int, list[PulseRecentDataResponse]]:
    """One poll cycle. Returns (rows_written, [responses])."""
    if client is None:
        client = _make_transport_for(cfg)
    if publisher is None:
        publisher = store_reading

    devices = await client.list_devices()
    responses: list[PulseRecentDataResponse] = []
    written = 0
    for device in devices.devices:
        try:
            response = await client.recent_data(device.id)
        except PulseError:
            logger.exception(
                "pulse: recent-data fetch failed for device %s", device.id
            )
            continue
        responses.append(response)
        written += await _publish_device(response, publisher=publisher)
    return written, responses


async def poll_loop(
    cfg_provider: Callable[[], PulseConfig],
    *,
    record_outcome: Callable[[bool, str | None], None],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    while True:
        cfg = cfg_provider()
        # Cloud transport needs creds before starting; local transport
        # can run with just defaults (operator may have left
        # local_device_urls empty, in which case discovery handles it).
        if cfg.transport == "cloud" and (not cfg.email or not cfg.password):
            await sleep(cfg.poll_seconds)
            continue
        try:
            await run_one_poll(cfg)
            record_outcome(True, None)
        except PulseError as exc:
            logger.warning("pulse poll failed: %s", exc)
            record_outcome(False, str(exc))
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("pulse poll crashed")
            record_outcome(False, str(exc))
        await sleep(cfg.poll_seconds)
