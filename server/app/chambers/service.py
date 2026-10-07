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
    # active_session_id is the one nullable link: an explicit `null` in the
    # request detaches the chamber from its session; omitting the field keeps it.
    if "active_session_id" in data.model_fields_set:
        active_session_id = dumped["active_session_id"]
    else:
        active_session_id = existing["active_session_id"]
    automation_rule_ids = json.dumps(dumped["automation_rule_ids"]) if dumped["automation_rule_ids"] is not None else json.dumps(existing["automation_rule_ids"])

    async with get_db() as db:
        await db.execute(
            """UPDATE chambers
               SET name = ?, description = ?, node_ids = ?, active_session_id = ?, automation_rule_ids = ?
               WHERE id = ?""",
            (name, description, node_ids, active_session_id, automation_rule_ids, chamber_id),
        )
        if active_session_id is not None:
            # Keep the two chamber↔session links in step: create_session writes
            # both, a link made here used to set only this one — so telemetry
            # tagging, chamber stats and transcripts (which read
            # sessions.chamber_id) never saw the session as this chamber's.
            # A session already bound to a chamber is never moved.
            await db.execute(
                "UPDATE sessions SET chamber_id = ? WHERE id = ? AND chamber_id IS NULL",
                (chamber_id, active_session_id),
            )
        await db.commit()
    return await get_chamber(chamber_id)


# Chambers listing a node. A chamber whose node_ids isn't valid JSON lists none.
_NODE_CHAMBERS_SQL = (
    "SELECT DISTINCT c.id, c.node_ids FROM chambers c, "
    "json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j "
    "WHERE j.value = ? ORDER BY c.id"
)


async def chambers_for_node(node_id: str) -> list[dict]:
    """Every chamber that lists `node_id`, as [{"id": int, "node_ids": [str, ...]}]."""
    async with get_db() as db:
        cursor = await db.execute(_NODE_CHAMBERS_SQL, (node_id,))
        rows = await cursor.fetchall()
    chambers = []
    for row in rows:
        try:
            nodes = [str(n) for n in json.loads(row["node_ids"] or "[]")]
        except (TypeError, ValueError):
            nodes = []
        chambers.append({"id": row["id"], "node_ids": nodes})
    return chambers


async def delete_chamber(chamber_id: int) -> bool:
    """Delete a chamber, detaching its history first (one transaction).

    sessions / contamination_events / planned_events reference chambers(id)
    with no ON DELETE action and foreign_keys=ON, so a chamber that ever hosted
    a grow could not be deleted (IntegrityError → 500). Those records outlive
    the chamber with chamber_id = NULL; its maintenance log (chamber_id NOT
    NULL, meaningless without the chamber) goes with it.
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM chambers WHERE id = ?", (chamber_id,))
        if await cursor.fetchone() is None:
            return False
        for sql in (
            "UPDATE sessions SET chamber_id = NULL WHERE chamber_id = ?",
            "UPDATE contamination_events SET chamber_id = NULL WHERE chamber_id = ?",
            "UPDATE planned_events SET chamber_id = NULL WHERE chamber_id = ?",
            "DELETE FROM chamber_maintenance WHERE chamber_id = ?",
        ):
            await db.execute(sql, (chamber_id,))
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
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query — only "?" placeholders or whitelisted column names are interpolated; every value is a bound parameter
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
