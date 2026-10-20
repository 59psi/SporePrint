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
is well within the Pi's I/O budget: the sensor query reads only the recent
window of readings, and the actuator counter reads a small totals table.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Info, generate_latest

from ...chambers.service import list_chambers
from ...db import get_db
from .. import _registry
from .config import GrafanaConfig


logger = logging.getLogger(__name__)

# A node's last reading stops being exported once the node has been silent
# this long — the Pi calls a node offline after 15 minutes without telemetry
# (main.py's liveness sweeper) — so a dead sensor's last value does not keep
# showing as a live gauge until retention deletes it.
_NODE_READING_MAX_AGE_SECONDS = 900.0
# Vendor readings (node ids "<driver>:<device>") arrive once per driver poll,
# up to an hour apart, and some are stored at the time the sensor took them
# (an Aranet4 radios a sample every 1-10 minutes): they stay current for as
# many polls as the driver's own health allows before it calls the vendor
# stale, and never less than 30 minutes.
_DEFAULT_STALE_POLLS = 3.0
_VENDOR_READING_MIN_AGE_SECONDS = 1800.0


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
    "weight_g": (
        "sporeprint_node_weight_grams",
        "Last calibrated load-cell reading from this node (HX711)",
        "g",
    ),
    "door_open": (
        # Stored 1.0/0.0 by store_bulk_readings — a gauge, not a counter.
        "sporeprint_node_door_open",
        "Door state from this node's reed switch (1 = open, 0 = closed)",
        "bool",
    ),
}


async def _node_to_chamber_map() -> dict[str, str]:
    """Return {node_id: chamber_id} so sensor metrics can be labelled by
    chamber. Nodes not assigned to any chamber map to ``""`` so the label
    is always present (Prometheus requires consistent label sets per
    metric, missing-label rewrites cost cardinality).

    Built from the chambers service's parsed rows; a row whose node_ids is
    not a JSON list (hand-edited, or legacy) contributes no nodes instead of
    failing the scrape. Oldest chamber first, so a node listed in two
    chambers is labelled with the newer one.
    """
    out: dict[str, str] = {}
    for chamber in reversed(await list_chambers()):
        node_ids = chamber.get("node_ids")
        if not isinstance(node_ids, list):
            continue
        for node_id in node_ids:
            out[str(node_id)] = str(chamber["id"])
    return out


def _vendor_max_reading_ages() -> dict[str, float]:
    """{driver slug: seconds} a polled vendor reading stays current."""
    out: dict[str, float] = {}
    for slug, drv in _registry.registered_drivers().items():
        poll = getattr(getattr(drv, "config", None), "poll_seconds", None)
        if isinstance(poll, bool) or not isinstance(poll, (int, float)) or poll <= 0:
            continue
        polls = getattr(drv, "stale_after_multiplier", _DEFAULT_STALE_POLLS)
        out[slug] = max(_VENDOR_READING_MIN_AGE_SECONDS, float(poll) * float(polls))
    return out


def _max_reading_age(node_id: str, vendor_ages: dict[str, float]) -> float:
    slug, sep, _device = node_id.partition(":")
    if sep and slug in vendor_ages:
        return vendor_ages[slug]
    return _NODE_READING_MAX_AGE_SECONDS


async def _latest_per_sensor(since: float) -> list[dict[str, Any]]:
    """One row per (node_id, sensor) with a reading at or after ``since`` —
    the most recent value. Bounding the window keeps the scan to recent rows
    (idx_telemetry_sensor_time) instead of the whole raw table."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT node_id, sensor, value, MAX(timestamp) AS timestamp
            FROM telemetry_readings
            WHERE sensor IN ('temp_c','humidity','co2_ppm','lux','dew_point_f','weight_g','door_open')
              AND timestamp >= ?
            GROUP BY node_id, sensor
            """,
            (since,),
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
    """Lifetime actuator events per (node, channel, action).

    Read from the totals the MQTT ingest keeps beside each actuator_events
    row, never counted from the raw table: that table is pruned nightly, and
    counting it on every scrape cost a full scan that grew without bound.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT node_id, channel, action, n FROM actuator_event_counts"
        )
        rows = await cursor.fetchall()
    return [(r["node_id"], r["channel"] or "", r["action"], r["n"]) for r in rows]


async def _contamination_counts() -> list[tuple[str, int]]:
    """Count contamination per chamber.

    Contamination is recorded in ``contamination_events`` (identify
    detections + manual marks); an event without its own chamber_id is
    attributed to its session's chamber. Sessions carrying the legacy
    ``status = 'contaminated'`` with no logged event are counted once each,
    so nothing is double-counted.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT chamber_id, SUM(n) AS n FROM (
                SELECT COALESCE(ce.chamber_id, s.chamber_id) AS chamber_id,
                       COUNT(*) AS n
                FROM contamination_events ce
                LEFT JOIN sessions s ON s.id = ce.session_id
                WHERE COALESCE(ce.chamber_id, s.chamber_id) IS NOT NULL
                GROUP BY COALESCE(ce.chamber_id, s.chamber_id)
                UNION ALL
                SELECT s.chamber_id AS chamber_id, COUNT(*) AS n
                FROM sessions s
                WHERE s.status = 'contaminated' AND s.chamber_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM contamination_events ce
                      WHERE ce.session_id = s.id
                  )
                GROUP BY s.chamber_id
            )
            GROUP BY chamber_id
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
    reading_time: Gauge | None = None
    if cfg.include_sensor_history:
        reading_time = Gauge(
            "sporeprint_node_reading_timestamp_seconds",
            "Unix time of the exported reading, per node and sensor (diagnostic)",
            (*_SENSOR_LABELS, "sensor"),
            registry=registry,
        )

    chamber_map = await _node_to_chamber_map()

    now = time.time()
    vendor_ages = _vendor_max_reading_ages()
    longest = max([_NODE_READING_MAX_AGE_SECONDS, *vendor_ages.values()])
    for row in await _latest_per_sensor(now - longest):
        sensor = row["sensor"]
        if sensor not in _SENSOR_MAP:
            continue
        node_id = str(row["node_id"])
        if now - float(row["timestamp"]) > _max_reading_age(node_id, vendor_ages):
            continue  # the node (or vendor) went quiet: no live gauge
        prom_name, _doc, _unit = _SENSOR_MAP[sensor]
        value = float(row["value"])
        if sensor == "dew_point_f":
            value = _f_to_c(value)
        chamber_id = chamber_map.get(node_id, "")
        sensor_gauges[prom_name].labels(
            node_id=node_id, chamber_id=chamber_id
        ).set(value)
        if reading_time is not None:
            reading_time.labels(
                node_id=node_id, chamber_id=chamber_id, sensor=sensor
            ).set(float(row["timestamp"]))

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
            "Lifetime contamination events (detections + manual marks), by chamber",
            ("chamber_id",),
            registry=registry,
        )
        for chamber_id, n in await _contamination_counts():
            contam.labels(chamber_id=chamber_id)._value.set(n)  # type: ignore[attr-defined]

    return generate_latest(registry)
