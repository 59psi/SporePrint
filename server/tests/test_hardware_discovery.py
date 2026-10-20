"""LAN node discovery + claim — /api/hardware/discover + /claim (H2-1).

Discovery is backed by the heartbeat-populated `hardware_nodes` registry (the
firmware's only LAN-presence signal); claim adopts an unclaimed known node into
a small on-demand `node_claims` ledger. Every test drives the exact paths the
Pi UI's setup page (first-chamber step) calls.
"""

import time

import pytest

from app.db import get_db


async def _register_node(node_id: str, node_type: str = "relay",
                         ip: str | None = "192.168.1.50") -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO hardware_nodes (node_id, node_type, ip_address, last_seen) "
            "VALUES (?, ?, ?, ?)",
            (node_id, node_type, ip, time.time()),
        )
        await db.commit()


def _unclaimed(client) -> list[str]:
    return sorted(n["node_id"] for n in client.get("/api/hardware/discover").json()["nodes"]
                  if not n["claimed"])


async def test_discover_lists_heartbeat_nodes_with_contract_shape(client):
    assert client.get("/api/hardware/discover").json() == {"nodes": []}
    await _register_node("relay-01", "relay", "192.168.1.51")
    r = client.get("/api/hardware/discover")
    assert r.status_code == 200
    assert r.json() == {"nodes": [{
        "node_id": "relay-01",
        "mac": None,                 # not carried in the heartbeat
        "ip": "192.168.1.51",
        "personality": "relay",      # provisioned node_type
        "claimed": False,
    }]}


async def test_setup_first_chamber_flow_discover_unclaimed_then_claim(client):
    # The Pi has heard from three LAN nodes, one adopted on a prior run;
    # discover tags each by claim state; the operator claims an unclaimed
    # row; a re-scan shows it adopted.
    await _register_node("relay-01", "relay", "192.168.1.51")
    await _register_node("relay-02", "relay", "192.168.1.52")
    await _register_node("light-01", "lighting", None)
    assert client.post("/api/hardware/claim", json={"node_id": "relay-02"}).status_code == 200
    assert _unclaimed(client) == ["light-01", "relay-01"]

    r = client.post("/api/hardware/claim", json={"node_id": "relay-01"})
    assert r.status_code == 200
    assert r.json() == {"status": "claimed", "node_id": "relay-01"}
    # Claiming again is a no-op success, not a duplicate-key error.
    assert client.post("/api/hardware/claim", json={"node_id": "relay-01"}).status_code == 200

    nodes = client.get("/api/hardware/discover").json()["nodes"]
    assert sorted(n["node_id"] for n in nodes) == ["light-01", "relay-01", "relay-02"]
    assert _unclaimed(client) == ["light-01"]


async def test_a_claim_naming_a_chamber_lists_the_node_there(client):
    """A claim alone puts the node in no chamber, so chamber scoping (and the
    Fleet page) never saw it; with chamber_id the node joins that chamber."""
    await _register_node("relay-01")
    await _register_node("climate-01", "climate")
    chamber = client.post("/api/chambers", json={"name": "Closet", "node_ids": ["climate-01"]}).json()
    r = client.post("/api/hardware/claim", json={"node_id": "relay-01", "chamber_id": chamber["id"]})
    assert r.status_code == 200
    assert r.json() == {"status": "claimed", "node_id": "relay-01", "chamber_id": chamber["id"]}
    assert client.get(f"/api/chambers/{chamber['id']}").json()["node_ids"] == ["climate-01", "relay-01"]
    # Claiming into it again does not list the node twice.
    client.post("/api/hardware/claim", json={"node_id": "relay-01", "chamber_id": chamber["id"]})
    assert client.get(f"/api/chambers/{chamber['id']}").json()["node_ids"] == ["climate-01", "relay-01"]
    assert _unclaimed(client) == ["climate-01"]


@pytest.mark.parametrize("body,status", [
    ({}, 400),
    # node_id feeds MQTT topic composition elsewhere — keep the guard tight.
    ({"node_id": "relay-01/../other"}, 400),
    ({"node_id": "relay-01", "chamber_id": "1"}, 400),
    ({"node_id": "relay-01", "chamber_id": 1.5}, 400),
    ({"node_id": "relay-01", "chamber_id": True}, 400),
    # Only heartbeat-known nodes can be claimed.
    ({"node_id": "ghost-99"}, 404),
    ({"node_id": "relay-01", "chamber_id": 999}, 404),
], ids=["no-node-id", "path-injection", "chamber-id-string", "chamber-id-float",
        "chamber-id-bool", "unknown-node", "missing-chamber"])
async def test_a_refused_claim_writes_nothing(client, body, status):
    await _register_node("relay-01")
    r = client.post("/api/hardware/claim", json=body)
    assert r.status_code == status
    if body.get("chamber_id") == 999:
        assert r.json()["detail"] == "Chamber not found"
    assert _unclaimed(client) == ["relay-01"]
