"""v4.2 — Pi-side consumers for the firmware-v2 topics: the heartbeat
type/roles upsert, roles-aware command routing, node log batches, and the CA
the node's TLS link fetches. (Coredump chunks: test_coredumps.py; OTA events:
test_mqtt_ingest_hardening.py.)
"""

import json

import pytest

import app.mqtt
from app import provision
from app.cloud.service import _resolve_command_node
from app.db import get_db
from app.mqtt import _handle_message
from tests._builders import node_row
from tests._fakes import RecordingSio


@pytest.fixture(autouse=True)
def _mute_downstream(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.mqtt.forward_telemetry", _noop)
    monkeypatch.setattr("app.mqtt.forward_event", _noop)
    monkeypatch.setattr("app.mqtt.forward_component_health", _noop)
    monkeypatch.setattr("app.weather.service.get_current_weather", lambda: None)


# ── heartbeat: type + roles refresh ─────────────────────────────

async def test_a_heartbeat_sets_type_and_roles_and_an_older_one_keeps_them():
    """The old upsert never refreshed node_type, so rows decayed to whatever
    the first insert guessed ('unknown') and type-based routing broke. A v1
    heartbeat (no type, no roles) must not reset what a v2 one reported."""
    sio = RecordingSio()
    await _handle_message(sio, "sporeprint/node-a1/status", {"status": "online"})
    assert (await node_row("node-a1"))["node_type"] == "unknown"

    await _handle_message(sio, "sporeprint/node-a1/status/heartbeat", {
        "type": "relay", "roles": ["climate", "relay"],
        "firmware_version": "4.2.0", "ip": "10.0.0.9"})
    row = await node_row("node-a1")
    assert (row["node_type"], json.loads(row["roles"])) == ("relay", ["climate", "relay"])

    await _handle_message(sio, "sporeprint/node-a1/status/heartbeat",
                          {"firmware_version": "4.1.5"})
    row = await node_row("node-a1")
    assert (row["node_type"], json.loads(row["roles"]), row["firmware_version"]) == (
        "relay", ["climate", "relay"], "4.1.5")


# ── roles-aware command routing ─────────────────────────────────

async def test_resolve_node_by_role_matches_combined_node():
    await _handle_message(
        RecordingSio(), "sporeprint/combo-1/status/heartbeat",
        {"type": "relay", "roles": ["climate", "relay"]})

    assert await _resolve_command_node("relay", "fae") == ("combo-1", None)
    # The combined node also answers climate-targeted commands via roles.
    assert await _resolve_command_node("climate", None) == ("combo-1", None)
    assert await _resolve_command_node("camera", None) == (None, "No registered camera node")


async def test_resolve_node_null_roles_does_not_crash():
    await _handle_message(
        RecordingSio(), "sporeprint/old-1/status/heartbeat",
        {"type": "climate", "firmware_version": "4.1.5"})  # roles NULL
    assert await _resolve_command_node("climate", None) == ("old-1", None)


# ── logs consumer ───────────────────────────────────────────────

async def test_a_log_batch_is_stored_and_served_per_node(client):
    sio = RecordingSio()
    await _handle_message(sio, "sporeprint/node-a3/logs", {"entries": [
        {"ts_ms": 1000, "level": 2, "msg": "[SENSOR] SHT3x read error"},
        "not-a-dict",
        {"msg": "x" * 400},  # no ts_ms or level; longer than a row keeps
    ], "dropped": 3})
    assert sio.named("node_log") == [{"node_id": "node-a3", "count": 3}]

    resp = client.get("/api/hardware/nodes/node-a3/logs")
    assert resp.status_code == 200
    assert [(e["ts_ms"], e["level"], e["msg"]) for e in resp.json()["entries"]] == [
        (0, 1, "x" * 300),                          # newest first
        (1000, 2, "[SENSOR] SHT3x read error"),
    ]


async def _log_count(node_id: str) -> int:
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM node_logs WHERE node_id = ?", (node_id,))
        return (await cursor.fetchone())[0]


async def _log_batch(node_id: str, n: int):
    await _handle_message(RecordingSio(), f"sporeprint/{node_id}/logs",
                          {"entries": [{"ts_ms": i, "level": 1, "msg": "x"} for i in range(n)]})


async def test_node_logs_are_trimmed_every_few_hundred_rows_not_every_batch(monkeypatch):
    """Finding the trim cutoff walks the node's whole log, so it runs on a
    node's first batch after a start and then once every _NODE_LOG_TRIM_EVERY
    rows; a chatty node used to pay it on every batch. (Scaled down from
    10 000 / 500 so the test stays fast; the cadence logic is the same.)"""
    keep, every = 40, 20
    monkeypatch.setattr(app.mqtt, "_NODE_LOG_KEEP", keep)
    monkeypatch.setattr(app.mqtt, "_NODE_LOG_TRIM_EVERY", every)
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO node_logs (node_id, ts_ms, level, msg) VALUES ('node-l1', ?, 1, 'old')",
            [(i,) for i in range(keep + 30)])
        await db.commit()
    await _log_batch("node-l1", 8)  # a node's first batch since the start trims
    assert await _log_count("node-l1") == keep
    batches = (every - 1) // 8
    for _ in range(batches):  # below the cadence: no trim, rows accumulate
        await _log_batch("node-l1", 8)
    assert await _log_count("node-l1") == keep + batches * 8
    await _log_batch("node-l1", 8)  # crosses it: trimmed back to the newest
    assert await _log_count("node-l1") == keep
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM node_logs WHERE node_id = 'node-l1' AND msg = 'old'")
        assert (await cursor.fetchone())[0] == keep - (batches + 2) * 8


# ── the CA a Secure-MQTT node pins ──────────────────────────────

def test_the_ca_endpoint_never_serves_a_file_holding_a_private_key(client, tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN PRIVATE KEY-----\noops\n-----END PRIVATE KEY-----\n")
    monkeypatch.setattr(provision, "_CA_PATHS", (ca,))
    resp = client.get("/api/provision/ca")
    assert resp.status_code == 500
    assert "PRIVATE KEY" not in resp.text
