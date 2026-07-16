import json
import time

from ..db import get_db
from .models import ChamberCreate, ChamberUpdate, MaintenanceCreate


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


# ── Lifetime stats (DERIVED — no new table) ─────────────────────
#
# Sessions link to a chamber via the real sessions.chamber_id FK, so lifetime
# grow/yield/contamination stats are joins over sessions + harvests +
# contamination_events. A session counts as contaminated if its status is
# 'contaminated' OR it has at least one contamination_event in this chamber.


async def get_chamber_stats(chamber_id: int) -> dict | None:
    """Derive lifetime grow/yield/contamination stats for a chamber.

    Returns None if the chamber does not exist.
    """
    chamber = await get_chamber(chamber_id)
    if not chamber:
        return None

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, status FROM sessions WHERE chamber_id = ?", (chamber_id,)
        )
        sessions = [dict(r) for r in await cursor.fetchall()]
        session_ids = {s["id"] for s in sessions}
        total_grows = len(sessions)
        completed_grows = sum(1 for s in sessions if s["status"] == "completed")

        cursor = await db.execute(
            """SELECT COALESCE(SUM(h.wet_weight_g), 0) AS wet,
                      COALESCE(SUM(h.dry_weight_g), 0) AS dry
               FROM harvests h
               JOIN sessions s ON h.session_id = s.id
               WHERE s.chamber_id = ?""",
            (chamber_id,),
        )
        yrow = dict(await cursor.fetchone())

        # Sessions in this chamber with a logged contamination event.
        cursor = await db.execute(
            "SELECT DISTINCT session_id FROM contamination_events "
            "WHERE chamber_id = ? AND session_id IS NOT NULL",
            (chamber_id,),
        )
        contaminated_ids = {s["id"] for s in sessions if s["status"] == "contaminated"}
        for r in await cursor.fetchall():
            if r["session_id"] in session_ids:
                contaminated_ids.add(r["session_id"])

        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM contamination_events WHERE chamber_id = ?",
            (chamber_id,),
        )
        contamination_event_count = dict(await cursor.fetchone())["n"]

    contaminated_grows = len(contaminated_ids)
    rate = round(contaminated_grows / total_grows, 4) if total_grows else 0.0

    return {
        "chamber_id": chamber_id,
        "lifetime_grows": total_grows,
        "completed_grows": completed_grows,
        "contaminated_grows": contaminated_grows,
        "contamination_rate": rate,
        "contamination_event_count": contamination_event_count,
        "total_wet_yield_g": round(yrow["wet"] or 0.0, 1),
        "total_dry_yield_g": round(yrow["dry"] or 0.0, 1),
    }


async def get_chamber_photos(chamber_id: int, limit: int = 50) -> list[dict] | None:
    """Derive a chamber's photo gallery from vision_frames captured by its nodes.

    Returns None if the chamber does not exist, [] if it has no nodes/frames.
    """
    chamber = await get_chamber(chamber_id)
    if not chamber:
        return None

    node_ids = chamber.get("node_ids") or []
    if not node_ids:
        return []

    placeholders = ",".join("?" for _ in node_ids)
    async with get_db() as db:
        cursor = await db.execute(
            f"""SELECT id, session_id, node_id, timestamp, file_path, resolution,
                       flash_used, analysis_local, analysis_claude, created_at
                FROM vision_frames
                WHERE node_id IN ({placeholders})
                ORDER BY timestamp DESC, id DESC
                LIMIT ?""",
            (*node_ids, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]


# ── Maintenance schedule + log ──────────────────────────────────


async def get_maintenance(mid: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM chamber_maintenance WHERE id = ?", (mid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_maintenance(chamber_id: int, limit: int = 200) -> list[dict]:
    """Newest-first maintenance log, capped — it grows for the chamber's life."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM chamber_maintenance WHERE chamber_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (chamber_id, max(1, min(limit, 1000))),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def schedule_maintenance(chamber_id: int, data: MaintenanceCreate) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO chamber_maintenance (chamber_id, kind, due_at, notes) "
            "VALUES (?, ?, ?, ?)",
            (chamber_id, data.kind, data.due_at, data.notes),
        )
        await db.commit()
        mid = cursor.lastrowid
    return await get_maintenance(mid)


async def complete_maintenance(
    chamber_id: int, mid: int, notes: str | None = None
) -> dict | None:
    """Stamp completed_at on a maintenance entry. Returns None if not found for
    this chamber. Optional notes overwrite the existing note when provided."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM chamber_maintenance WHERE id = ? AND chamber_id = ?",
            (mid, chamber_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        existing = dict(row)
        new_notes = notes if notes is not None else existing["notes"]
        await db.execute(
            "UPDATE chamber_maintenance SET completed_at = ?, notes = ? WHERE id = ?",
            (time.time(), new_notes, mid),
        )
        await db.commit()
    return await get_maintenance(mid)
