"""send_plug_command must tell the truth about delivery AND resolve the way
target_is_present does (V2-3 + V3-1).

A paired Shelly/Tasmota gets a bare-payload publish and a True result; a plug
that was never paired is a no-op that returns False — it does NOT publish into
the void and claim success, which used to log the firing status='sent' for
hardware that isn't there.

Real provisioning matters here: per the build guide a plug auto-registers as a
`plug-<hwid>` row (its real id) with a `device_role` assigned, while the seeded
rules fire the friendly role target (`plug-heater`, `plug-humidifier`, …). That
friendly target is NOT the row's plug_id — only its role. Resolving by plug_id
alone found nothing and no-op'd even though the plug was paired and
target_is_present reported it available. These tests pair plugs the way the
hardware actually does — by role, under a hardware id — so the resolution is
proven, not masked. (V3-1)
"""

from app.automation.smart_plugs import send_plug_command, target_is_present
from app.db import get_db


async def _register_plug(
    plug_id: str, plug_type: str, prefix: str, role: str | None = None
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, plug_type, mqtt_topic_prefix, name, device_role) "
            "VALUES (?, ?, ?, ?, ?)",
            (plug_id, plug_type, prefix, plug_id, role),
        )
        await db.commit()


async def test_unpaired_plug_is_a_no_op(mock_mqtt_raw):
    result = await send_plug_command("plug-dehumidifier", "on")
    assert result is False
    # No speculative publish to a device that was never paired.
    assert mock_mqtt_raw == []


async def test_role_registered_plug_resolves_by_device_role(mock_mqtt_raw):
    """THE V3-1 bug: the plug is paired under its hardware id with a role, and
    the seeded rule fires the friendly role target — which is not the plug_id.
    It must resolve by device_role, publish, and report True (not silently
    no-op an actuator target_is_present says is available)."""
    await _register_plug("plug-a1b2c3", "tasmota", "tasmota/a1b2c3", role="heater")
    # Sanity: presence and delivery must AGREE — both resolve by role.
    assert await target_is_present("plug-heater") is True
    result = await send_plug_command("plug-heater", "on")
    assert result is True
    assert mock_mqtt_raw == [("tasmota/a1b2c3/cmnd/POWER", "ON")]


async def test_shelly_role_registered_plug_publishes_bare(mock_mqtt_raw):
    await _register_plug("plug-9f7e", "shelly", "shellies/9f7e", role="humidifier")
    result = await send_plug_command("plug-humidifier", "on")
    assert result is True
    # Bare payload, not JSON: Shelly rejects `"on"` (quoted).
    assert mock_mqtt_raw == [("shellies/9f7e/relay/0/command", "on")]


async def test_exact_plug_id_wins_the_tie_break(mock_mqtt_raw):
    """When both an exact plug_id match and a different device_role match exist,
    the exact id wins (ORDER BY plug_id = ? DESC)."""
    await _register_plug("plug-other", "shelly", "shellies/other", role="heater")
    await _register_plug("plug-heater", "tasmota", "tasmota/heater", role=None)
    result = await send_plug_command("plug-heater", "off")
    assert result is True
    assert mock_mqtt_raw == [("tasmota/heater/cmnd/POWER", "OFF")]


async def test_plug_paired_by_id_only_still_resolves(mock_mqtt_raw):
    """A plug whose id IS the friendly name (no device_role) keeps working —
    the OR clause still matches on plug_id."""
    await _register_plug("plug-heater", "tasmota", "tasmota/heater")
    result = await send_plug_command("plug-heater", "off")
    assert result is True
    assert mock_mqtt_raw == [("tasmota/heater/cmnd/POWER", "OFF")]
