"""Builders and fixtures shared by the sessions, species, chambers, planner and
transcript tests (not collected: the name does not start with ``test_``).

A test module uses a fixture from here by importing it by name, e.g.
``from tests._pi_c2_helpers import alerts``.
"""

import json
import os
import time
from types import SimpleNamespace

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.models import GrowPhase, PhaseParams, SpeciesProfile

DAY = 86_400

# ── species profiles ──────────────────────────────────────────────────────

COLONIZATION = PhaseParams(
    temp_min_f=68, temp_max_f=75, humidity_min=70, humidity_max=80,
    co2_max_ppm=2000, co2_tolerance="high", light_hours_on=0,
    light_hours_off=24, light_spectrum="none", fae_mode="none",
    expected_duration_days=(10, 14),
)
PRIMORDIA = PhaseParams(
    temp_min_f=50, temp_max_f=55, humidity_min=90, humidity_max=95,
    co2_max_ppm=500, co2_tolerance="low", light_hours_on=12,
    light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
    expected_duration_days=(3, 5),
)
FRUITING = PhaseParams(
    temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
    co2_max_ppm=700, co2_tolerance="low", light_hours_on=12,
    light_hours_off=12, light_spectrum="daylight_6500k", fae_mode="continuous",
    expected_duration_days=(5, 7),
)


def custom_profile(**overrides) -> SpeciesProfile:
    """A valid custom gourmet profile ('custom_test'): substrate colonization
    (10-14 d) then fruiting (55-65 °F, 5-7 d) unless `phases` says otherwise."""
    fields = dict(
        id="custom_test",
        common_name="Test Species",
        scientific_name="Testus testii",
        category="gourmet",
        substrate_types=["straw"],
        colonization_visual_description="White mycelium",
        contamination_risk_notes="Watch for trich",
        pinning_trigger_description="Cold shock",
        phases={GrowPhase.SUBSTRATE_COLONIZATION: COLONIZATION, GrowPhase.FRUITING: FRUITING},
        flush_count_typical=3,
        yield_notes="Test yield",
    )
    fields.update(overrides)
    return SpeciesProfile(**fields)


# ── grows ─────────────────────────────────────────────────────────────────


def grow(name: str = "Test Grow", species: str = "blue_oyster", **fields) -> SessionCreate:
    return SessionCreate(name=name, species_profile_id=species, **fields)


async def start_grow(name: str = "Test Grow", species: str = "blue_oyster", **fields) -> dict:
    return await create_session(grow(name, species, **fields))


async def age_grow(session_id: int, seconds: float) -> None:
    """Move a grow's start `seconds` into the past (orders grows by age)."""
    async with get_db() as db:
        await db.execute("UPDATE sessions SET created_at = created_at - ? WHERE id = ?",
                         (seconds, session_id))
        await db.commit()


async def enter_open_phase_days_ago(session_id: int, days: float) -> None:
    """Backdate the entry of the phase a grow is in now."""
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ? WHERE session_id = ? AND exited_at IS NULL",
            (time.time() - days * DAY, session_id),
        )
        await db.commit()


# ── telemetry and nodes ───────────────────────────────────────────────────


async def insert_reading(node_id: str, sensor: str, value: float, ts: float | None = None,
                         session_id: int | None = None) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time() if ts is None else ts, node_id, sensor, value, session_id),
        )
        await db.commit()


async def insert_rollup(node_id: str, sensor: str, ts: float, avg: float, mn: float | None = None,
                        mx: float | None = None, count: int = 12, resolution: str = "hourly") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_rollups (timestamp, node_id, sensor, resolution, avg_value, "
            "min_value, max_value, count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, node_id, sensor, resolution, avg, avg if mn is None else mn,
             avg if mx is None else mx, count),
        )
        await db.commit()


async def register_node(node_id: str, node_type: str = "climate", *, roles: list[str] | None = None,
                        seen_ago: float | None = None) -> None:
    """A hardware_nodes row; `seen_ago` (seconds) marks it online, seen then."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles, last_seen, status) VALUES (?, ?, ?, ?, ?)",
            (node_id, node_type, json.dumps(roles) if roles is not None else None,
             None if seen_ago is None else time.time() - seen_ago,
             "unknown" if seen_ago is None else "online"),
        )
        await db.commit()


# ── fakes ─────────────────────────────────────────────────────────────────


def fake_anthropic(reply, *, captured: dict | None = None, stop_reason: str = "end_turn"):
    """A stand-in for ``anthropic.AsyncAnthropic``. messages.create() records
    its keyword arguments in `captured` and answers `reply` as one text block
    (a dict is sent as JSON); an exception `reply` is raised instead."""
    captured = {} if captured is None else captured

    class _Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            if isinstance(reply, BaseException):
                raise reply
            text = reply if isinstance(reply, str) else json.dumps(reply)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                   stop_reason=stop_reason)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    return _Client


@pytest.fixture()
def alerts(monkeypatch):
    """Every page, warning, CO2 alert and cloud event the engine sends, by
    title or event type; the engine unpaused."""
    sent: list[str] = []

    async def _page(title, message, tags=None, **kw):
        sent.append(title)

    async def _forward(event_type, data):
        sent.append(event_type)

    async def _co2(ppm, *args, **kw):
        sent.append("co2")

    monkeypatch.setattr(engine, "notify_critical", _page)
    monkeypatch.setattr(engine, "notify_warning", _page)
    monkeypatch.setattr(engine, "co2_alert", _co2)
    monkeypatch.setattr(cloud_service, "forward_event", _forward)
    monkeypatch.setattr(engine, "_paused", False)
    monkeypatch.setattr(engine, "_pause_loaded", False)
    return sent


@pytest.fixture()
def pacific_time():
    """The Pi's zone (setup.sh hands the host's TZ to the container)."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()
