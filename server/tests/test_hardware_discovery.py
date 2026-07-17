"""LAN node discovery + claim — /api/hardware/discover + /claim (H2-1).

Discovery is backed by the heartbeat-populated `hardware_nodes` registry (the
firmware's only LAN-presence signal); claim adopts an unclaimed known node into
a small on-demand `node_claims` ledger.
"""

import time

from app.db import get_db
from app.hardware.discovery import claim_node, list_discovered_nodes


async def _register_node(node_id: str, node_type: str = "relay",
                         ip: str | None = "192.168.1.50") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, ip_address, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type, ip, time.time()),
        )
        await db.commit()


# ── discover ──────────────────────────────────────────────────────────────


def test_discover_empty_when_no_nodes(client):
    r = client.get("/api/hardware/discover")
    assert r.status_code == 200
    assert r.json() == {"nodes": []}


async def test_discover_lists_heartbeat_nodes_with_contract_shape(client):
    await _register_node("relay-01", "relay", "192.168.1.51")
    r = client.get("/api/hardware/discover")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    assert len(nodes) == 1
    node = nodes[0]
    assert set(node.keys()) == {"node_id", "mac", "ip", "personality", "claimed"}
    assert node["node_id"] == "relay-01"
    assert node["personality"] == "relay"       # provisioned node_type
    assert node["ip"] == "192.168.1.51"
    assert node["mac"] is None                   # not carried in the heartbeat
    assert node["claimed"] is False


# ── claim ─────────────────────────────────────────────────────────────────


async def test_claim_marks_node_claimed(client):
    await _register_node("light-01", "lighting", None)
    r = client.post("/api/hardware/claim", json={"node_id": "light-01"})
    assert r.status_code == 200
    assert r.json() == {"status": "claimed", "node_id": "light-01"}
    # It now reads claimed in discovery.
    nodes = client.get("/api/hardware/discover").json()["nodes"]
    assert nodes[0]["node_id"] == "light-01"
    assert nodes[0]["claimed"] is True


def test_claim_unknown_node_404(client):
    r = client.post("/api/hardware/claim", json={"node_id": "ghost-99"})
    assert r.status_code == 404


async def test_claim_is_idempotent(client):
    await _register_node("relay-01")
    assert client.post("/api/hardware/claim", json={"node_id": "relay-01"}).status_code == 200
    # Claiming again is a no-op success, not a duplicate-key error.
    assert client.post("/api/hardware/claim", json={"node_id": "relay-01"}).status_code == 200
    nodes = client.get("/api/hardware/discover").json()["nodes"]
    assert sum(1 for n in nodes if n["node_id"] == "relay-01") == 1
    assert nodes[0]["claimed"] is True


def test_claim_missing_node_id_400(client):
    assert client.post("/api/hardware/claim", json={}).status_code == 400


def test_claim_rejects_path_injection_node_id(client):
    # node_id feeds MQTT topic composition elsewhere — keep the guard tight.
    assert client.post(
        "/api/hardware/claim", json={"node_id": "relay-01/../other"}
    ).status_code == 400


# ── service layer directly ────────────────────────────────────────────────


async def test_claim_node_returns_false_for_unknown():
    assert await claim_node("never-heard-of-it") is False


async def test_list_discovered_reflects_claim_state():
    await _register_node("relay-01")
    await _register_node("light-01", "lighting", None)
    assert await claim_node("relay-01") is True
    by_id = {n["node_id"]: n for n in await list_discovered_nodes()}
    assert by_id["relay-01"]["claimed"] is True
    assert by_id["light-01"]["claimed"] is False
