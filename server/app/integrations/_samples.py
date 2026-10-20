"""When a vendor reading was taken, and whether this poll is the first to see it.

Aranet and Pulse serve each sensor's LATEST sample, so successive polls
return the same reading until the sensor takes a new one: an Aranet4 radios
every 1-10 minutes while the Pi polls every minute. Stamping every poll with
the Pi's clock stored one reading as many fresh-looking rows, and kept a
sensor that had died (flat battery, out of radio range) looking live in
history and Grafana. SampleTracker remembers the sample each (node, sensor)
last stored: a repeat is not stored again, a new sample is stored at the time
the sensor took it, and a sample that stops changing is reported stale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, NamedTuple

from pydantic import BaseModel, ValidationError


# A vendor clock this far ahead of the Pi's is wrong: such a reading is
# stored at the Pi's time instead.
_MAX_CLOCK_AHEAD_SECONDS = 120.0
# Epoch seconds before this (2001) are not a real sample time.
_MIN_EPOCH_SECONDS = 1e9
# Epoch values above this are milliseconds.
_MILLISECONDS_ABOVE = 1e11

_FAHRENHEIT_UNITS = frozenset({"f", "degf", "deg f", "fahrenheit", "degrees f", "degrees fahrenheit"})


def sample_time(raw: object) -> float | None:
    """The epoch seconds a vendor timestamp names, or None.

    Accepts epoch seconds or milliseconds (a number or a numeric string) and
    ISO-8601 text that carries a UTC offset. A naive ISO time gives None: its
    zone is unknown, so it can tell two samples apart but not date them.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        text = raw.strip()
        try:
            raw = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return None
            return parsed.timestamp() if parsed.tzinfo is not None else None
    if not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return None
    seconds = raw / 1000.0 if raw > _MILLISECONDS_ABOVE else float(raw)
    return seconds if seconds >= _MIN_EPOCH_SECONDS else None


def is_fahrenheit(unit: object) -> bool:
    """Whether a vendor's unit string means degrees Fahrenheit."""
    if not isinstance(unit, str):
        return False
    return unit.strip().lower().replace("°", "") in _FAHRENHEIT_UNITS


def finite(value: object) -> float | None:
    """`value` as a float, or None when it is missing or not a finite number."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def valid_items(model: type[BaseModel], items: Any) -> list[BaseModel]:
    """The entries of a vendor list that validate as `model`; the rest are
    dropped, so one malformed sensor or measurement (a null value, a missing
    type) cannot fail a whole poll. A non-list is an empty list."""
    if not isinstance(items, list):
        return []
    kept: list[BaseModel] = []
    for item in items:
        try:
            kept.append(item if isinstance(item, model) else model.model_validate(item))
        except ValidationError:
            continue
    return kept


@dataclass
class _Seen:
    identity: object
    # When the sample was taken, or first seen when it carries no usable time.
    since: float


class PollResult(NamedTuple):
    """What one vendor poll did."""

    written: int
    # Vendor nodes (sensors, devices) the poll asked for or got a reading from.
    devices: int
    # Node id -> why it gave no fresh reading (stale sample, fetch error).
    failed: dict[str, str]


class SampleTracker:
    """Per-driver memory of the sample each (node, sensor) last stored."""

    def __init__(self, stale_floor_seconds: float) -> None:
        self._floor = stale_floor_seconds
        self._seen: dict[tuple[str, str], _Seen] = {}

    def stale_after(self, poll_seconds: float) -> float:
        """A sample older than this is stale: three polls, but never less
        than the floor (the sensor's own reporting interval)."""
        return max(3.0 * poll_seconds, self._floor)

    def take(
        self, node_id: str, sensor: str, raw_ts: object, now: float, poll_seconds: float,
    ) -> tuple[float | None, bool]:
        """What to do with one reading a poll returned.

        Returns (the time to store it at, or None to skip it; whether the
        sensor's sample is stale). A reading with no timestamp at all cannot
        be told apart from the previous one, so it is stored at `now`.
        """
        if raw_ts is None:
            return now, False
        window = self.stale_after(poll_seconds)
        taken = sample_time(raw_ts)
        identity = taken if taken is not None else raw_ts
        key = (node_id, sensor)
        seen = self._seen.get(key)
        if seen is not None and seen.identity == identity:
            return None, now - seen.since > window
        if seen is None and taken is not None and now - taken > window:
            # The first sight of an old sample: a sensor that died before the
            # Pi (re)started, or a vendor clock far behind. Store nothing
            # until the sample changes, which proves the sensor alive.
            self._seen[key] = _Seen(identity, taken)
            return None, True
        dated = taken is not None and now - window <= taken <= now + _MAX_CLOCK_AHEAD_SECONDS
        stamp = min(taken, now) if dated else now
        self._seen[key] = _Seen(identity, stamp)
        return stamp, False

    def keep_new(
        self,
        readings: Iterable[tuple[str, str, float, object]],
        *,
        poll_seconds: float,
        now: float,
    ) -> tuple[list[tuple[float, str, str, float]], dict[str, str]]:
        """Split a poll's (node id, sensor, value, sample timestamp) readings
        into the rows to store (timestamp, node id, sensor, value) and the
        nodes whose sample is stale."""
        rows: list[tuple[float, str, str, float]] = []
        stale: dict[str, str] = {}
        minutes = round(self.stale_after(poll_seconds) / 60)
        for node_id, sensor, value, raw_ts in readings:
            stamp, is_stale = self.take(node_id, sensor, raw_ts, now, poll_seconds)
            if is_stale:
                stale[node_id] = f"no new reading for over {minutes} min"
            if stamp is not None:
                rows.append((stamp, node_id, sensor, value))
        return rows, stale
