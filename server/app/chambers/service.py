import json
import time

from ..db import get_db
from .models import ChamberCreate, ChamberUpdate


def _parse_chamber(row: dict) -> dict:
    """Parse JSON text fields from a chamber DB row."""
    chamber = dict(row)
    try:
        chamber["node_ids"] = json.loads(chamber.get("node_ids") or "[]")
        chamber["automation_rule_ids"] = json.loads(chamber.get("automation_rule_ids") or "[]")
    except (json.JSONDecodeError, TypeError):
        chamber["node_ids"] = []
        chamber["automation_rule_ids"] = []
    return chamber


async def create_chamber(data: ChamberCreate) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chambers (name, description, node_ids) VALUES (?, ?, ?)",
            (data.name, data.description, json.dumps(data.node_ids)),
        )
        await db.commit()
        chamber_id = cursor.lastrowid
    return await get_chamber(chamber_id)


async def get_chamber(chamber_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM chambers WHERE id = ?", (chamber_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return _parse_chamber(row)


async def list_chambers() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM chambers ORDER BY created_at DESC, id DESC")
        return [_parse_chamber(r) for r in await cursor.fetchall()]


async def update_chamber(chamber_id: int, data: ChamberUpdate) -> dict | None:
    existing = await get_chamber(chamber_id)
    if not existing:
        return None

    dumped = data.model_dump()

    name = dumped["name"] if dumped["name"] is not None else existing["name"]
    description = dumped["description"] if dumped["description"] is not None else existing["description"]
    node_ids = json.dumps(dumped["node_ids"]) if dumped["node_ids"] is not None else json.dumps(existing["node_ids"])
    active_session_id = dumped["active_session_id"] if dumped["active_session_id"] is not None else existing["active_session_id"]
    automation_rule_ids = json.dumps(dumped["automation_rule_ids"]) if dumped["automation_rule_ids"] is not None else json.dumps(existing["automation_rule_ids"])

    async with get_db() as db:
        await db.execute(
            """UPDATE chambers
               SET name = ?, description = ?, node_ids = ?, active_session_id = ?, automation_rule_ids = ?
               WHERE id = ?""",
            (name, description, node_ids, active_session_id, automation_rule_ids, chamber_id),
        )
        await db.commit()
    return await get_chamber(chamber_id)


async def delete_chamber(chamber_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM chambers WHERE id = ?", (chamber_id,))
        await db.commit()
        return cursor.rowcount > 0


async def compare_chambers(chamber_ids: list[int]) -> list[dict]:
    """Side-by-side telemetry comparison between chambers."""
    results = []
    since = time.time() - 86400  # last 24h

    for cid in chamber_ids:
        chamber = await get_chamber(cid)
        if not chamber:
            continue
        node_ids = chamber.get("node_ids", [])
        if isinstance(node_ids, str):
            node_ids = json.loads(node_ids)

        async with get_db() as db:
            sensors = {}
            for node_id in node_ids:
                cursor = await db.execute(
                    """SELECT sensor, AVG(value) as avg_val, MIN(value) as min_val,
                       MAX(value) as max_val, COUNT(*) as readings
                       FROM telemetry_readings
                       WHERE node_id = ? AND timestamp >= ?
                       GROUP BY sensor""",
                    (node_id, since),
                )
                for row in await cursor.fetchall():
                    r = dict(row)
                    sensors[r["sensor"]] = {
                        "avg": round(r["avg_val"], 1),
                        "min": round(r["min_val"], 1),
                        "max": round(r["max_val"], 1),
                        "readings": r["readings"],
                    }

        results.append({
            "chamber_id": cid,
            "chamber_name": chamber["name"],
            "node_ids": node_ids,
            "telemetry": sensors,
        })
    return results
