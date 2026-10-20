"""A liquid culture is a sealed vessel: the closet's humidity is not its
humidity. The dashboards' "Liquid culture" container ran as an open tub, so
a closet at room humidity paged humidity emergencies for a sealed jar and the
humidifier churned toward the colonization band."""

import json

import pytest

from app.automation.engine import evaluate_rules
from app.automation.service import seed_builtin_rules
from app.automation.smart_plugs import register_plug
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins
from tests._pi_c2_helpers import alerts  # noqa: F401  (fixture)


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


# The open monotub is the control: the same closet with the substrate in its air.
@pytest.mark.parametrize(("container", "managed"), [("liquid_culture", False), ("monotub", True)])
async def test_room_humidity_pages_and_humidifies_only_an_open_substrate(
        container, managed, mock_mqtt, mock_mqtt_raw, alerts):  # noqa: F811
    await _closet_running(container)
    await evaluate_rules("climate-1", {"temp_f": 72, "humidity": 45})
    humidity_pages = [a for a in alerts if "humidity" in a.lower()]
    humidifier = [p for t, p in mock_mqtt_raw if t.startswith("tasmota/hum")]
    assert bool(humidity_pages) is managed
    assert bool(humidifier) is managed
