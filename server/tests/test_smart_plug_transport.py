"""How a smart plug's transport is resolved, checked and kept.

- A command only goes to a prefix the broker lets the server publish to:
  one level under shellies/ or tasmota/, for every plug type. Elsewhere
  Mosquitto drops it silently and the firing would read 'sent'.
- One resolution of a plug target (paired_plug): commands, presence checks,
  aliases and the engine's plug-state read agree on which row a target means.
- A report on another transport re-points a plug only once its stored
  transport has gone quiet; while it is live the report is ignored.
- A report that changes nothing is not written on every message.
"""

import logging
import time
from unittest.mock import patch

import pytest

import app.automation.engine as engine
import app.automation.smart_plugs as smart_plugs
from app.automation.smart_plugs import (
    handle_plug_message,
    paired_plug,
    plug_aliases,
    plug_prefix_error,
    register_plug,
    send_plug_command,
    target_is_present,
)
from app.db import get_db


class _Sio:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event, data):
        self.events.append((event, data))


@pytest.fixture(autouse=True)
def _reset_conflict_log():
    smart_plugs._transport_conflict_logged.clear()
    yield
    smart_plugs._transport_conflict_logged.clear()


async def _insert(plug_id, plug_type, prefix, *, role=None, status="unknown",
                  last_state=None, last_seen=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO smart_plugs (plug_id, name, plug_type, mqtt_topic_prefix, device_role, "
            "status, last_state, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plug_id, plug_id, plug_type, prefix, role, status, last_state, last_seen),
        )
        await db.commit()


async def _row(plug_id):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM smart_plugs WHERE plug_id = ?", (plug_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


def _at(ts: float):
    return patch.object(time, "time", lambda: ts)


# ── Commands reach only prefixes the broker grants ─────────────────────────


@pytest.mark.parametrize("plug_type,prefix", [
    ("tasmota", "home/heater"),
    ("tasmota", "tasmota/closet/heater"),
    ("tasmota", "shellies/heater"),
    ("shelly", "shellies/closet/heater"),
    ("shelly", "tasmota/heater"),
    ("shelly", ""),
])
async def test_a_command_to_a_prefix_the_broker_drops_is_not_sent(
        mock_mqtt_raw, plug_type, prefix, caplog):
    await _insert("plug-heater", plug_type, prefix)
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        assert await send_plug_command("plug-heater", "on") is False
    assert mock_mqtt_raw == []
    assert "one level under" in caplog.text


@pytest.mark.parametrize("plug_type,prefix,topic,payload", [
    ("tasmota", "tasmota/heater", "tasmota/heater/cmnd/POWER", "ON"),
    ("shelly", "shellies/heater", "shellies/heater/relay/0/command", "on"),
])
async def test_a_one_level_prefix_is_commanded(mock_mqtt_raw, plug_type, prefix, topic, payload):
    await _insert("plug-heater", plug_type, prefix)
    assert await send_plug_command("plug-heater", "on") is True
    assert mock_mqtt_raw == [(topic, payload)]


def test_prefix_error_names_the_fix():
    assert plug_prefix_error("tasmota", "tasmota/heater") is None
    assert plug_prefix_error("shelly_gen2", "shellies/heater") is None
    assert "tasmota/<role>" in plug_prefix_error("tasmota", "home/heater")
    assert "shellies/<role>" in plug_prefix_error("shelly", "shellies/a/b")
    assert "Unknown plug_type" in plug_prefix_error("kasa", "kasa/heater")


@pytest.mark.parametrize("body", [
    {"plug_type": "tasmota", "mqtt_topic_prefix": "home/closet/heater"},
    {"plug_type": "shelly", "mqtt_topic_prefix": "shellies/closet/heater"},
    {"plug_type": "tasmota", "mqtt_topic_prefix": "tasmota/heater/"},
    {"plug_type": "wemo", "mqtt_topic_prefix": "tasmota/heater"},
])
def test_registering_a_plug_no_command_could_reach_is_422(client, body):
    r = client.post("/api/automation/plugs",
                    json={"plug_id": "plug-heater", "name": "heater", **body})
    assert r.status_code == 422, r.text
    assert client.get("/api/automation/plugs").json() == []


def test_registering_a_one_level_prefix_is_accepted(client):
    r = client.post("/api/automation/plugs", json={
        "plug_id": "plug-heater", "name": "heater", "plug_type": "tasmota",
        "mqtt_topic_prefix": "tasmota/heater", "device_role": "heater"})
    assert r.status_code == 200, r.text


# ── One resolution of a plug target ────────────────────────────────────────


async def test_every_reader_resolves_a_target_to_the_same_plug():
    # "plug-heater" is one row's exact id AND another row's role: the exact id wins.
    await _insert("plug-heater", "tasmota", "tasmota/heater", last_state="off")
    await _insert("plug-a1b2", "tasmota", "tasmota/a1b2", role="heater", last_state="on")
    row = await paired_plug("plug-heater")
    assert row["plug_id"] == "plug-heater"
    assert await plug_aliases("plug-heater") == {"plug-heater"}
    assert await engine._plug_reports_on("plug-heater") is False  # the exact row's state
    assert await target_is_present("plug-heater") is True
    # A role resolves to the row holding it.
    assert await plug_aliases("plug-cooler") == {"plug-cooler"}
    assert await target_is_present("plug-cooler") is False


async def test_a_role_target_reads_the_role_holder():
    await _insert("plug-a1b2", "tasmota", "tasmota/a1b2", role="heater", last_state="on")
    assert await plug_aliases("plug-heater") == {"plug-heater", "plug-a1b2"}
    assert await engine._plug_reports_on("plug-heater") is True
    assert await target_is_present("plug-heater") is True


# ── A second device, or a forged report, never re-points a live plug ───────


async def test_a_report_on_another_transport_leaves_a_live_plug_alone(mock_mqtt_raw, caplog):
    now = time.time()
    await _insert("plug-heater", "tasmota", "tasmota/heater",
                  status="online", last_state="on", last_seen=now - 30)
    sio = _Sio()
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(sio, "shellies/heater/relay/0", "off")
    row = await _row("plug-heater")
    assert (row["plug_type"], row["mqtt_topic_prefix"], row["last_state"]) == (
        "tasmota", "tasmota/heater", "on")
    assert sio.events == []
    assert "was ignored" in caplog.text
    # The Pi's OFF still reaches the plug that is really there.
    assert await send_plug_command("plug-heater", "off") is True
    assert mock_mqtt_raw == [("tasmota/heater/cmnd/POWER", "OFF")]


async def test_the_conflict_is_logged_once_per_window(caplog):
    await _insert("plug-heater", "tasmota", "tasmota/heater",
                  status="online", last_seen=time.time())
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        for _ in range(5):
            await handle_plug_message(_Sio(), "shellies/heater/relay/0", "off")
    assert caplog.text.count("was ignored") == 1


@pytest.mark.parametrize("status,age", [("offline", 30), ("online", 700), ("unknown", None)])
async def test_a_quiet_plug_follows_its_new_transport(status, age, caplog):
    """A Gen1 swapped for a Gen2 (or a Tasmota for a Shelly) under the same
    name heals as soon as the old device is gone: offline, silent for over
    ten minutes, or registered by hand and never seen."""
    last_seen = None if age is None else time.time() - age
    await _insert("plug-heater", "tasmota", "tasmota/heater", status=status, last_seen=last_seen)
    sio = _Sio()
    with caplog.at_level(logging.WARNING, logger="app.automation.smart_plugs"):
        await handle_plug_message(sio, "shellies/heater/relay/0", "on")
    row = await _row("plug-heater")
    assert (row["plug_type"], row["mqtt_topic_prefix"], row["status"], row["last_state"]) == (
        "shelly", "shellies/heater", "online", "on")
    assert sio.events == [("plug_state", {"plug_id": "plug-heater", "state": "on"})]
    assert "now reports as shelly" in caplog.text


# ── A report that changes nothing is not written each time ─────────────────


async def test_unchanged_reports_do_not_write_until_last_seen_is_due():
    t0 = 1_800_000_000.0
    with _at(t0):
        await handle_plug_message(_Sio(), "shellies/h1/relay/0", "off")
        await handle_plug_message(_Sio(), "shellies/h1/relay/0/power", "0.00")
    assert (await _row("plug-h1"))["last_seen"] == t0
    with _at(t0 + 30):  # Gen1 republishes both every 30 s
        await handle_plug_message(_Sio(), "shellies/h1/relay/0", "off")
        await handle_plug_message(_Sio(), "shellies/h1/relay/0/power", "0.00")
    assert (await _row("plug-h1"))["last_seen"] == t0  # nothing written
    with _at(t0 + 60):  # a change is written at once
        await handle_plug_message(_Sio(), "shellies/h1/relay/0", "on")
    row = await _row("plug-h1")
    assert (row["last_state"], row["last_seen"]) == ("on", t0 + 60)
    with _at(t0 + 90):
        await handle_plug_message(_Sio(), "shellies/h1/relay/0/power", "41.5")
    row = await _row("plug-h1")
    assert (row["last_power_w"], row["last_seen"]) == (41.5, t0 + 90)
    with _at(t0 + 90 + smart_plugs._LAST_SEEN_REFRESH_SECONDS):  # refresh is due
        await handle_plug_message(_Sio(), "shellies/h1/relay/0", "on")
    assert (await _row("plug-h1"))["last_seen"] == t0 + 90 + smart_plugs._LAST_SEEN_REFRESH_SECONDS


async def test_an_unchanged_report_from_an_offline_plug_brings_it_online():
    await _insert("plug-h1", "shelly", "shellies/h1", status="offline", last_state="off",
                  last_seen=time.time())
    await handle_plug_message(_Sio(), "shellies/h1/relay/0", "off")
    assert (await _row("plug-h1"))["status"] == "online"


async def test_a_power_report_for_another_transport_is_not_recorded():
    await _insert("plug-heater", "tasmota", "tasmota/heater", status="online",
                  last_seen=time.time())
    await handle_plug_message(_Sio(), "shellies/heater/relay/0/power", "1500")
    assert (await _row("plug-heater"))["last_power_w"] is None


async def test_register_plug_refuses_a_prefix_no_command_reaches():
    with pytest.raises(ValueError):
        await register_plug("plug-heater", "heater", "tasmota", "home/heater")
    assert await _row("plug-heater") is None
