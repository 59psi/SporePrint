"""A liquid culture is a sealed vessel: the closet's humidity is not its
humidity. The dashboards' "Liquid culture" container ran as an open tub, so
a closet at room humidity paged humidity emergencies for a sealed jar and the
humidifier churned toward the colonization band."""

import json

import pytest

import app.automation.engine as engine
import app.cloud.service as cloud_service
from app.automation.engine import evaluate_rules
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins


@pytest.fixture
def alerts(monkeypatch):
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
    engine._paused = False
    engine._pause_loaded = False
    return sent


async def _closet_running(container: str) -> None:
    await seed_builtins()
    await seed_builtin_rules()
    await register_plug("plug-hum", "Humidifier", "tasmota", "tasmota/hum", device_role="humidifier")
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, node_ids) VALUES (?, ?)", ("Closet", json.dumps(["climate-1"])))
        await db.commit()
        chamber_id = cursor.lastrowid
    await create_session(SessionCreate(
        name="Grow", species_profile_id="blue_oyster", current_phase="substrate_colonization",
        container_type=container, chamber_id=chamber_id))


def _humidity_pages(alerts: list[str]) -> list[str]:
    return [a for a in alerts if "humidity" in a.lower()]


async def test_a_liquid_culture_at_room_humidity_pages_nothing_and_runs_no_humidifier(
        mock_mqtt, mock_mqtt_raw, alerts):
    await _closet_running("liquid_culture")
    await evaluate_rules("climate-1", {"temp_f": 72, "humidity": 45})
    assert _humidity_pages(alerts) == []
    assert [t for t, _ in mock_mqtt_raw if "tasmota/hum" in t] == []


async def test_an_open_monotub_at_the_same_humidity_does_page(mock_mqtt, mock_mqtt_raw, alerts):
    """The control: the same closet with the substrate in its air."""
    await _closet_running("monotub")
    await evaluate_rules("climate-1", {"temp_f": 72, "humidity": 45})
    assert _humidity_pages(alerts) != []
