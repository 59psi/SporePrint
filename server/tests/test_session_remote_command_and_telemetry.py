"""Cloud → Pi session seam (H4-2) and per-session telemetry node resolution (H4-1).

H4-2: the remote command dispatcher (target_kind="system", channel
session_start|session_end) used to ImportError because sessions.service had no
``handle_remote_command`` — every remote start/end replied
``success=false 'sessions service not available'``. These tests exercise the
handler directly and through the real cloud dispatcher.

H4-1: the per-session telemetry endpoint hardcoded node ``climate-01`` and
ignored ``session_id``, so it showed the wrong node's data (or nothing) for any
node not named that. These tests prove the node is now resolved from the
session's tagged telemetry, else its chamber's climate/sensor node.
"""

import json
import time

import pytest

from app.chambers.models import ChamberCreate
from app.chambers.service import create_chamber
from app.db import get_db
from app.sessions.models import SessionCreate
from app.sessions.service import (
    create_session,
    get_session,
    handle_remote_command,
    resolve_session_node_id,
)


def _session(**overrides):
    d = dict(name="Remote Grow", species_profile_id="blue_oyster")
    d.update(overrides)
    return SessionCreate(**d)


async def _register_node(node_id: str, node_type: str = "climate", roles=None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, roles) VALUES (?, ?, ?)",
            (node_id, node_type, json.dumps(roles) if roles is not None else None),
        )
        await db.commit()


async def _insert_telemetry(node_id, sensor, value, ts=None, session_id=None):
    ts = ts if ts is not None else time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telemetry_readings (timestamp, node_id, sensor, value, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, node_id, sensor, value, session_id),
        )
        await db.commit()


# ── H4-2: cloud → Pi remote session command seam ────────────────


async def test_handle_remote_command_session_start_creates_session():
    result = await handle_remote_command(
        "session_start",
        {"name": "Cloud-started Grow", "species_profile_id": "blue_oyster", "substrate": "CVG"},
    )
    assert result["id"] is not None
    assert result["name"] == "Cloud-started Grow"
    assert result["status"] == "active"
    # It really persisted.
    assert await get_session(result["id"]) is not None


async def test_handle_remote_command_session_end_completes_session():
    s = await create_session(_session())
    assert s["status"] == "active"
    result = await handle_remote_command("session_end", {"session_id": s["id"]})
    assert result["status"] == "completed"
    assert result["current_phase"] == "complete"
    assert result["completed_at"] is not None


async def test_handle_remote_command_unknown_channel_raises():
    with pytest.raises(ValueError):
        await handle_remote_command("session_pause", {})


async def test_cloud_dispatch_system_command_session_seam():
    """The real dispatcher no longer hits ImportError for session channels —
    it finds handle_remote_command and reports success (the H4-2 regression)."""
    from app.cloud.service import _dispatch_system_command

    ok, err = await _dispatch_system_command(
        "session_start", {"name": "Relayed Grow", "species_profile_id": "blue_oyster"}
    )
    assert (ok, err) == (True, None)

    s = await create_session(_session(name="To End"))
    ok, err = await _dispatch_system_command("session_end", {"session_id": s["id"]})
    assert (ok, err) == (True, None)
    assert (await get_session(s["id"]))["status"] == "completed"


# ── H4-1: per-session telemetry resolves the real node ──────────


async def test_resolve_prefers_session_tagged_telemetry():
    s = await create_session(_session())
    # Tagged with this session on a node NOT named climate-01.
    await _insert_telemetry("sensor-42", "temp_f", 71.0, session_id=s["id"])
    assert await resolve_session_node_id(s["id"], "temp_f") == "sensor-42"


async def test_resolve_session_tagged_scopes_by_sensor():
    s = await create_session(_session())
    await _insert_telemetry("climate-A", "temp_f", 70.0, session_id=s["id"])
    await _insert_telemetry("plug-B", "power_w", 12.0, session_id=s["id"])
    assert await resolve_session_node_id(s["id"], "temp_f") == "climate-A"
    assert await resolve_session_node_id(s["id"], "power_w") == "plug-B"


async def test_resolve_falls_back_to_chamber_climate_node():
    chamber = await create_chamber(ChamberCreate(name="Tent B", node_ids=["relay-9", "sensor-9"]))
    await _register_node("relay-9", node_type="relay")
    await _register_node("sensor-9", node_type="climate")
    s = await create_session(_session(chamber_id=chamber["id"]))
    # No session-tagged telemetry → chamber topology picks the climate node.
    assert await resolve_session_node_id(s["id"], "temp_f") == "sensor-9"


async def test_resolve_chamber_node_via_roles():
    chamber = await create_chamber(ChamberCreate(name="Tent C", node_ids=["combo-1", "relay-x"]))
    # combo node's node_type is 'relay' but it carries the 'climate' sensing role.
    await _register_node("combo-1", node_type="relay", roles=["climate", "relay"])
    await _register_node("relay-x", node_type="relay")
    s = await create_session(_session(chamber_id=chamber["id"]))
    assert await resolve_session_node_id(s["id"], "humidity") == "combo-1"


async def test_resolve_chamber_first_node_when_unregistered():
    chamber = await create_chamber(ChamberCreate(name="Tent D", node_ids=["node-first", "node-second"]))
    # No hardware_nodes rows → fall back to the chamber's first node.
    s = await create_session(_session(chamber_id=chamber["id"]))
    assert await resolve_session_node_id(s["id"], "temp_f") == "node-first"


async def test_resolve_none_without_chamber_or_tagged_telemetry():
    s = await create_session(_session())  # no chamber, no tagged telemetry
    assert await resolve_session_node_id(s["id"], "temp_f") is None


async def test_session_telemetry_endpoint_uses_resolved_node(client):
    # Chamber whose sensor node is NOT climate-01.
    chamber = await create_chamber(ChamberCreate(name="Tent E", node_ids=["sensor-77"]))
    await _register_node("sensor-77", node_type="climate")
    s = await create_session(_session(chamber_id=chamber["id"]))
    # Real data on the resolved node; decoy on climate-01 that the old code returned.
    await _insert_telemetry("sensor-77", "temp_f", 68.5, ts=1000.0)
    await _insert_telemetry("climate-01", "temp_f", 99.9, ts=1000.0)

    resp = client.get(f"/api/sessions/{s['id']}/telemetry", params={"sensor": "temp_f"})
    assert resp.status_code == 200
    values = [r["value"] for r in resp.json()]
    assert 68.5 in values       # resolved node's data
    assert 99.9 not in values   # NOT the old hardcoded climate-01


async def test_session_telemetry_endpoint_empty_when_unresolvable(client):
    s = await create_session(_session())  # no chamber, no telemetry
    resp = client.get(f"/api/sessions/{s['id']}/telemetry", params={"sensor": "temp_f"})
    assert resp.status_code == 200
    assert resp.json() == []
