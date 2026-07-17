"""send_plug_command must tell the truth about delivery (V2-3).

A paired Shelly/Tasmota gets a bare-payload publish and a True result; a plug
that was never paired is a no-op that returns False — it does NOT publish into
the void and claim success, which used to log the firing status='sent' for
hardware that isn't there.
"""

from app.automation.smart_plugs import send_plug_command
from app.db import get_db


async def _register_plug(plug_id: str, plug_type: str, prefix: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name) VALUES (?, ?, ?, ?)",
            (plug_id, plug_type, prefix, plug_id),
        )
        await db.commit()


async def test_unpaired_plug_is_a_no_op(mock_mqtt_raw):
    result = await send_plug_command("plug-dehumidifier", "on")
    assert result is False
    # No speculative publish to a device that was never paired.
    assert mock_mqtt_raw == []


async def test_paired_shelly_publishes_bare_and_reports_true(mock_mqtt_raw):
    await _register_plug("plug-humidifier", "shelly", "shellies/humidifier")
    result = await send_plug_command("plug-humidifier", "on")
    assert result is True
    assert mock_mqtt_raw == [("shellies/humidifier/relay/0/command", "on")]


async def test_paired_tasmota_publishes_bare_and_reports_true(mock_mqtt_raw):
    await _register_plug("plug-heater", "tasmota", "tasmota/heater")
    result = await send_plug_command("plug-heater", "off")
    assert result is True
    assert mock_mqtt_raw == [("tasmota/heater/cmnd/POWER", "OFF")]
