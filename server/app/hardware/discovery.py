"""LAN node discovery + claim (H2-1).

Nodes self-register into `hardware_nodes` on their first MQTT heartbeat
(mqtt.py) — that heartbeat IS the current firmware's "I'm on the LAN" signal;
there is no separate zeroconf/UDP scan for sporeprint ESP32 nodes (only the
third-party Aranet/Pulse integrations scan the LAN). So "discover" surfaces the
heartbeat-known inventory, and "claim" adopts one of the unclaimed ones.

Claiming is a net-new concept, so its state lives in a small `node_claims`
ledger created on demand here (the shared schema in db.py is not extended from
this package). A node must be heartbeat-known before it can be claimed — you
cannot adopt hardware the Pi has never heard from.
"""

from ..db import get_db


async def _ensure_claims_table(db) -> None:
    """Create the claim ledger if absent. Idempotent and cheap."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS node_claims (
               node_id TEXT PRIMARY KEY,
               claimed_at REAL DEFAULT (unixepoch('now'))
           )"""
    )


async def list_discovered_nodes() -> list[dict]:
    """Every LAN node the Pi knows about, each tagged claimed / unclaimed.

    Shape per the /api/hardware/discover contract:
    ``{node_id, mac, ip, personality, claimed}``. `personality` is the node's
    provisioned `node_type` (climate/relay/lighting); `mac` is null because no
    MAC is carried in the heartbeat or stored in `hardware_nodes`.
    """
    async with get_db() as db:
        await _ensure_claims_table(db)
        cursor = await db.execute(
            """SELECT h.node_id, h.node_type, h.ip_address,
                      (c.node_id IS NOT NULL) AS claimed
               FROM hardware_nodes h
               LEFT JOIN node_claims c ON c.node_id = h.node_id
               ORDER BY h.last_seen DESC"""
        )
        rows = await cursor.fetchall()
    return [
        {
            "node_id": r["node_id"],
            "mac": None,
            "ip": r["ip_address"],
            "personality": r["node_type"],
            "claimed": bool(r["claimed"]),
        }
        for r in rows
    ]


async def claim_node(node_id: str) -> bool:
    """Adopt a heartbeat-known node. Returns False if the node is unknown.

    Idempotent: re-claiming an already-claimed node succeeds without change.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM hardware_nodes WHERE node_id = ?", (node_id,)
        )
        if await cursor.fetchone() is None:
            return False
        await _ensure_claims_table(db)
        await db.execute(
            "INSERT INTO node_claims (node_id) VALUES (?) "
            "ON CONFLICT(node_id) DO NOTHING",
            (node_id,),
        )
        await db.commit()
    return True
