"""The cloud → Pi session seam and per-session telemetry node resolution.

The remote command dispatcher (target_kind="system", channel
session_start|session_end) used to ImportError because sessions.service had no
``handle_remote_command`` — every remote start/end replied
``success=false 'sessions service not available'``. These tests exercise the
handler through the real cloud dispatcher.

The per-session telemetry endpoint hardcoded node ``climate-01`` and ignored
``session_id``, so it showed the wrong node's data (or nothing) for any node
not named that. These tests prove the node is now resolved from the session's
tagged telemetry, else its chamber's climate/sensor node.
"""

import pytest

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.cloud.service import _dispatch_system_command
from app.sessions.models import SessionCreate
from app.sessions.service import (
    abort_session,
    create_session,
    get_session,
    handle_remote_command,
    list_sessions,
    resolve_session_node_id,
)
from tests._pi_c2_helpers import insert_reading, register_node


def _session(**overrides):
    d = dict(name="Remote Grow", species_profile_id="blue_oyster")
    d.update(overrides)
    return SessionCreate(**d)


# ── cloud → Pi remote session command seam ───────────────────────


async def test_the_cloud_dispatcher_starts_and_ends_a_grow():
    """The real dispatcher finds handle_remote_command (it used to hit an
    ImportError) and reports success for both channels."""
    ok, err = await _dispatch_system_command(
        "session_start", {"name": "Relayed Grow", "species_profile_id": "blue_oyster", "substrate": "CVG"}
    )
    assert (ok, err) == (True, None)
    [started] = await list_sessions()
    assert (started["name"], started["substrate"], started["status"]) == ("Relayed Grow", "CVG", "active")

    ok, err = await _dispatch_system_command("session_end", {"session_id": started["id"]})
    assert (ok, err) == (True, None)
    ended = await get_session(started["id"])
    assert (ended["status"], ended["current_phase"]) == ("completed", "complete")
    assert ended["completed_at"] is not None


async def test_handle_remote_command_unknown_channel_raises():
    with pytest.raises(ValueError):
        await handle_remote_command("session_pause", {})


async def test_remote_end_of_nothing_reports_failure():
    """An end for an unknown session (or one that is not an id) used to ack
    success: the client was told a grow ended when nothing had."""
    for bad in (99999, "abc", None, 1.5, True):
        ok, err = await _dispatch_system_command("session_end", {"session_id": bad})
        assert ok is False and err, bad
    # An aborted grow is not turned into a completed one.
    s = await create_session(_session(name="Lost"))
    await abort_session(s["id"])
    ok, err = await _dispatch_system_command("session_end", {"session_id": str(s["id"])})
    assert ok is False and "aborted" in err
    assert (await get_session(s["id"]))["status"] == "aborted"


# ── per-session telemetry resolves the real node ─────────────────


async def test_session_tagged_telemetry_wins_per_sensor():
    """Readings tagged with the session name its node, sensor by sensor,
    ahead of the chamber's own climate node."""
    chamber = await create_chamber(ChamberCreate(name="Tent A", node_ids=["sensor-9"]))
    await register_node("sensor-9", "climate")
    s = await create_session(_session(chamber_id=chamber["id"]))
    await insert_reading("climate-A", "temp_f", 70.0, session_id=s["id"])
    await insert_reading("plug-B", "power_w", 12.0, session_id=s["id"])
    assert await resolve_session_node_id(s["id"], "temp_f") == "climate-A"
    assert await resolve_session_node_id(s["id"], "power_w") == "plug-B"
    assert await resolve_session_node_id(s["id"], "humidity") == "sensor-9"


@pytest.mark.parametrize(("chamber_nodes", "registered", "expected"), [
    # No tagged telemetry: the chamber topology picks the climate node ...
    (["relay-9", "sensor-9"], [("relay-9", "relay", None), ("sensor-9", "climate", None)], "sensor-9"),
    # ... or a node carrying the climate sensing role whatever its type ...
    (["combo-1", "relay-x"], [("combo-1", "relay", ["climate", "relay"]), ("relay-x", "relay", None)],
     "combo-1"),
    # ... else, with no hardware_nodes rows, the chamber's first node.
    (["node-first", "node-second"], [], "node-first"),
    # No chamber and no tagged telemetry: nothing to show.
    (None, [], None),
], ids=["climate-node", "climate-role", "first-node", "nothing"])
async def test_without_tagged_telemetry_the_chamber_names_the_node(chamber_nodes, registered, expected):
    chamber_id = None
    if chamber_nodes is not None:
        chamber_id = (await create_chamber(ChamberCreate(name="Tent", node_ids=chamber_nodes)))["id"]
    for node_id, node_type, roles in registered:
        await register_node(node_id, node_type, roles=roles)
    s = await create_session(_session(chamber_id=chamber_id))
    assert await resolve_session_node_id(s["id"], "humidity") == expected


async def test_session_telemetry_endpoint_reads_the_resolved_node(client):
    # Chamber whose sensor node is NOT climate-01.
    chamber = await create_chamber(ChamberCreate(name="Tent E", node_ids=["sensor-77"]))
    await register_node("sensor-77", "climate")
    s = await create_session(_session(chamber_id=chamber["id"]))
    loose = await create_session(_session(name="No chamber"))
    # Real data on the resolved node; decoy on climate-01 that the old code returned.
    await insert_reading("sensor-77", "temp_f", 68.5, ts=1000.0)
    await insert_reading("climate-01", "temp_f", 99.9, ts=1000.0)

    resp = client.get(f"/api/sessions/{s['id']}/telemetry", params={"sensor": "temp_f"})
    assert resp.status_code == 200
    values = [r["value"] for r in resp.json()]
    assert 68.5 in values       # resolved node's data
    assert 99.9 not in values   # NOT the old hardcoded climate-01
    # A grow whose node cannot be resolved gets an empty series, not climate-01's.
    resp = client.get(f"/api/sessions/{loose['id']}/telemetry", params={"sensor": "temp_f"})
    assert resp.status_code == 200 and resp.json() == []
