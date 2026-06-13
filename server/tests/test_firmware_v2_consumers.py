"""v4.2 — Pi-side consumers for the firmware-v2 topics (logs, coredump,
ota), the heartbeat type/roles upsert, and roles-aware command routing.
"""

import base64
import time
from unittest.mock import AsyncMock

import pytest

from app.db import get_db
from app.mqtt import _handle_message


@pytest.fixture(autouse=True)
def _mute_downstream(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_telemetry", _noop)
    monkeypatch.setattr("app.mqtt.forward_event", _noop)
    monkeypatch.setattr("app.mqtt.forward_component_health", _noop)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)


# ── heartbeat: type + roles refresh ─────────────────────────────

async def test_heartbeat_updates_node_type_and_roles():
    sio = AsyncMock()
    # First contact: a bare status insert leaves node_type 'unknown' (the
    # v1 decay path this fix exists for).
    await _handle_message(sio, "sporeprint/node-a1/status", {"status": "online"})

    await _handle_message(
        sio,
        "sporeprint/node-a1/status/heartbeat",
        {"type": "relay", "roles": ["climate", "relay"],
         "firmware_version": "4.2.0", "ip": "10.0.0.9"},
    )
    async with get_db() as db:
        cur = await db.execute(
            "SELECT node_type, roles FROM hardware_nodes WHERE node_id = ?",
            ("node-a1",))
        row = await cur.fetchone()
    assert row["node_type"] == "relay"
    assert "climate" in row["roles"]


async def test_heartbeat_without_type_does_not_clobber():
    """A v1 heartbeat (no `type` key) must not reset a known node_type."""
    sio = AsyncMock()
    await _handle_message(
        sio, "sporeprint/node-a2/status/heartbeat",
        {"type": "lighting", "firmware_version": "4.2.0"})
    await _handle_message(
        sio, "sporeprint/node-a2/status/heartbeat",
        {"firmware_version": "4.1.5"})  # v1-style: no type
    async with get_db() as db:
        cur = await db.execute(
            "SELECT node_type FROM hardware_nodes WHERE node_id = ?",
            ("node-a2",))
        row = await cur.fetchone()
    assert row["node_type"] == "lighting"


# ── roles-aware command routing ─────────────────────────────────

async def test_resolve_node_by_role_matches_combined_node():
    from app.cloud.service import _resolve_node_id_by_type

    sio = AsyncMock()
    await _handle_message(
        sio, "sporeprint/combo-1/status/heartbeat",
        {"type": "relay", "roles": ["climate", "relay"]})

    assert await _resolve_node_id_by_type("relay") == "combo-1"
    # The combined node also answers climate-targeted commands via roles.
    assert await _resolve_node_id_by_type("climate") == "combo-1"
    assert await _resolve_node_id_by_type("camera") is None


async def test_resolve_node_null_roles_does_not_crash():
    from app.cloud.service import _resolve_node_id_by_type

    sio = AsyncMock()
    await _handle_message(
        sio, "sporeprint/old-1/status/heartbeat",
        {"type": "climate", "firmware_version": "4.1.5"})  # roles NULL
    assert await _resolve_node_id_by_type("climate") == "old-1"


# ── logs consumer ───────────────────────────────────────────────

async def test_logs_batch_stored_and_emitted():
    sio = AsyncMock()
    await _handle_message(
        sio,
        "sporeprint/node-a3/logs",
        {"entries": [
            {"ts_ms": 1000, "level": 2, "msg": "[SENSOR] SHT3x read error"},
            {"ts_ms": 1100, "level": 1, "msg": "[BOOT] node ready"},
        ], "dropped": 3},
    )
    async with get_db() as db:
        cur = await db.execute(
            "SELECT ts_ms, level, msg FROM node_logs WHERE node_id = ? "
            "ORDER BY id", ("node-a3",))
        rows = await cur.fetchall()
    assert len(rows) == 2
    assert rows[0]["msg"].startswith("[SENSOR]")
    sio.emit.assert_awaited_with("node_log", {"node_id": "node-a3", "count": 2})


async def test_logs_malformed_entries_tolerated():
    sio = AsyncMock()
    await _handle_message(
        sio, "sporeprint/node-a4/logs",
        {"entries": ["not-a-dict", {"msg": "ok-ish"}]})
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS n FROM node_logs WHERE node_id = ?",
            ("node-a4",))
        row = await cur.fetchone()
    assert row["n"] == 1


# ── coredump reassembly ─────────────────────────────────────────

def _chunk(seq, total, data: bytes):
    return {"seq": seq, "total": total, "size": len(data),
            "b64_data": base64.b64encode(data).decode()}


async def test_coredump_reassembles_and_alerts(tmp_path, monkeypatch):
    from app.hardware import coredumps
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    sio = AsyncMock()
    blob = b"ELF-FAKE-" + bytes(range(64))
    half = len(blob) // 2
    await _handle_message(sio, "sporeprint/node-a5/coredump/chunk",
                          _chunk(0, 2, blob[:half]))
    sio.emit.assert_not_awaited()  # incomplete — no alert yet
    await _handle_message(sio, "sporeprint/node-a5/coredump/chunk",
                          _chunk(1, 2, blob[half:]))

    files = list((tmp_path / "dumps").glob("node-a5-*.elf"))
    assert len(files) == 1
    assert files[0].read_bytes() == blob
    assert sio.emit.await_args.args[0] == "alert"
    assert sio.emit.await_args.args[1]["type"] == "coredump"


async def test_coredump_rejects_garbage(tmp_path, monkeypatch):
    from app.hardware import coredumps
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    sio = AsyncMock()
    await _handle_message(sio, "sporeprint/node-a6/coredump/chunk",
                          {"seq": 0, "total": 2, "b64_data": "@@not-base64@@"})
    await _handle_message(sio, "sporeprint/node-a6/coredump/chunk",
                          {"seq": 5, "total": 2,
                           "b64_data": base64.b64encode(b"x").decode()})
    assert not (tmp_path / "dumps").exists()
    sio.emit.assert_not_awaited()


async def test_coredump_stale_assembly_abandoned(tmp_path, monkeypatch):
    from app.hardware import coredumps
    monkeypatch.setattr(coredumps, "COREDUMP_DIR", tmp_path / "dumps")

    sio = AsyncMock()
    await _handle_message(sio, "sporeprint/node-a7/coredump/chunk",
                          _chunk(0, 3, b"part0"))
    # Age the assembly past the timeout, then start a fresh one.
    coredumps._assemblies["node-a7"].started_at = time.time() - 700
    await _handle_message(sio, "sporeprint/node-a7/coredump/chunk",
                          _chunk(0, 1, b"fresh-complete"))
    files = list((tmp_path / "dumps").glob("node-a7-*.elf"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"fresh-complete"


# ── node OTA visibility ─────────────────────────────────────────

async def test_node_ota_event_emitted():
    sio = AsyncMock()
    await _handle_message(sio, "sporeprint/node-a8/ota",
                          {"event": "success", "ts": 1750000000})
    sio.emit.assert_awaited_with(
        "node_ota", {"node_id": "node-a8", "event": "success",
                     "ts": 1750000000})


# ── /api endpoints ──────────────────────────────────────────────

async def test_node_logs_endpoint(client):
    sio = AsyncMock()
    await _handle_message(
        sio, "sporeprint/node-a9/logs",
        {"entries": [{"ts_ms": 5, "level": 3, "msg": "[SAFETY] fae auto-off"}]})
    resp = client.get("/api/hardware/nodes/node-a9/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"][0]["msg"] == "[SAFETY] fae auto-off"


async def test_provision_ca_endpoint_404_without_certs(client):
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 404


async def test_provision_ca_serves_pem_and_refuses_keys(client, tmp_path,
                                                        monkeypatch):
    from app import provision
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(provision, "_CA_PATHS", (ca,))
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 200
    assert "BEGIN CERTIFICATE" in resp.text

    ca.write_text("-----BEGIN PRIVATE KEY-----\noops\n-----END PRIVATE KEY-----\n")
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 500
