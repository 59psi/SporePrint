"""Prometheus collectors for the Grafana exporter.

Each scrape calls `collect_samples()`, which queries SQLite for the
latest values per (node, sensor) pair, the per-chamber session state, and
the actuator + contamination counters. We use the Prometheus *registry*
pattern (a fresh registry per scrape) rather than process-global gauges
because:

  1. Sensor labels are dynamic — node ids and chamber memberships can
     change at runtime as the operator pairs/unpairs hardware. Stale
     gauges from a previous scrape would show as constant readings even
     after a node is decommissioned.
  2. Counters need to be derived from rows in the database, not
     incremented per-event in memory — the Pi may restart and the
     counter must survive (the database is the source of truth).

The trade-off is one SQLite read per scrape, which at 30s scrape interval
is well within the Pi's I/O budget.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Info, generate_latest

from ...db import get_db
from .config import GrafanaConfig


logger = logging.getLogger(__name__)


# Prometheus best practice: stable label cardinality. We label by node_id
# and chamber_id rather than chamber_name because names are mutable.
_SENSOR_LABELS = ("node_id", "chamber_id")


# Map from the Pi's internal sensor name (telemetry_readings.sensor) to the
# Prometheus metric name + base unit. SI units everywhere; the Fahrenheit
# columns are dropped — Grafana handles unit display.
_SENSOR_MAP: dict[str, tuple[str, str, str]] = {
    "temp_c": (
        "sporeprint_node_temperature_celsius",
        "Last reading from a temperature sensor on this node",
        "C",
    ),
    "humidity": (
        "sporeprint_node_humidity_percent",
        "Last reading from a humidity sensor on this node",
        "percent",
    ),
    "co2_ppm": (
        "sporeprint_node_co2_ppm",
        "Last CO2 reading from this node",
        "ppm",
    ),
    "lux": (
        "sporeprint_node_lux",
        "Last light-intensity reading from this node",
        "lux",
    ),
    "dew_point_f": (
        # Convert F→C at scrape time so the metric name matches its unit.
        "sporeprint_node_dewpoint_celsius",
        "Last dew-point reading from this node (converted to Celsius)",
        "C",
    ),
}


async def _node_to_chamber_map() -> dict[str, str]:
    """Return {node_id: chamber_id} so sensor metrics can be labelled by
    chamber. Nodes not assigned to any chamber map to ``""`` so the label
    is always present (Prometheus requires consistent label sets per
    metric, missing-label rewrites cost cardinality).
    """
    out: dict[str, str] = {}
    async with get_db() as db:
        cursor = await db.execute("SELECT id, node_ids FROM chambers")
        for row in await cursor.fetchall():
            chamber_id = str(row["id"])
            try:
                node_ids = json.loads(row["node_ids"] or "[]")
            except json.JSONDecodeError:
                node_ids = []
            for node_id in node_ids:
                out[str(node_id)] = chamber_id
    return out


async def _latest_per_sensor() -> list[dict[str, Any]]:
    """One row per (node_id, sensor) — the most recent value."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT node_id, sensor, value, MAX(timestamp) AS timestamp
            FROM telemetry_readings
            WHERE sensor IN ('temp_c','humidity','co2_ppm','lux','dew_point_f')
            GROUP BY node_id, sensor
            """
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def _active_sessions() -> list[dict[str, Any]]:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, chamber_id, species_profile_id, current_phase
            FROM sessions
            WHERE status = 'active' AND chamber_id IS NOT NULL
            """
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def _actuator_event_counts() -> list[tuple[str, str, str, int]]:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT node_id, channel, action, COUNT(*) AS n
            FROM actuator_events
            GROUP BY node_id, channel, action
            """
        )
        rows = await cursor.fetchall()
    return [(r["node_id"], r["channel"] or "", r["action"], r["n"]) for r in rows]


async def _contamination_counts() -> list[tuple[str, int]]:
    """count contaminations per chamber_id (extracted from the session)."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT s.chamber_id AS chamber_id, COUNT(*) AS n
            FROM sessions s
            WHERE s.status = 'contaminated' AND s.chamber_id IS NOT NULL
            GROUP BY s.chamber_id
            """
        )
        rows = await cursor.fetchall()
    return [(str(r["chamber_id"]), r["n"]) for r in rows]


def _f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


async def collect_samples(cfg: GrafanaConfig, *, version: str) -> bytes:
    """Query the DB and return a freshly-rendered Prometheus exposition."""
    registry = CollectorRegistry()

    # Static info.
    info = Info(
        "sporeprint_build",
        "Pi-side build information",
        registry=registry,
    )
    info.info({"version": version})

    sensor_gauges: dict[str, Gauge] = {}
    for prom_name, doc, _unit in _SENSOR_MAP.values():
        sensor_gauges[prom_name] = Gauge(
            prom_name, doc, _SENSOR_LABELS, registry=registry
        )

    chamber_map = await _node_to_chamber_map()

    for row in await _latest_per_sensor():
        sensor = row["sensor"]
        if sensor not in _SENSOR_MAP:
            continue
        prom_name, _doc, _unit = _SENSOR_MAP[sensor]
        value = float(row["value"])
        if sensor == "dew_point_f":
            value = _f_to_c(value)
        node_id = str(row["node_id"])
        chamber_id = chamber_map.get(node_id, "")
        sensor_gauges[prom_name].labels(
            node_id=node_id, chamber_id=chamber_id
        ).set(value)

    session_active = Gauge(
        "sporeprint_chamber_session_active",
        "1 if the chamber currently has an active grow session, else 0",
        ("chamber_id", "species_profile_id", "phase"),
        registry=registry,
    )
    for s in await _active_sessions():
        session_active.labels(
            chamber_id=str(s["chamber_id"]),
            species_profile_id=str(s["species_profile_id"]),
            phase=str(s["current_phase"]),
        ).set(1)

    if cfg.include_actuator_state:
        actuator_count = Counter(
            "sporeprint_actuator_event_count",
            "Lifetime actuator events recorded on this Pi",
            ("node_id", "channel", "action"),
            registry=registry,
        )
        for node_id, channel, action, n in await _actuator_event_counts():
            actuator_count.labels(
                node_id=node_id, channel=channel, action=action
            )._value.set(n)  # type: ignore[attr-defined]

    if cfg.include_contamination_metrics:
        contam = Counter(
            "sporeprint_contamination_events_total",
            "Lifetime sessions ended in 'contaminated' status, by chamber",
            ("chamber_id",),
            registry=registry,
        )
        for chamber_id, n in await _contamination_counts():
            contam.labels(chamber_id=chamber_id)._value.set(n)  # type: ignore[attr-defined]

    return generate_latest(registry)
