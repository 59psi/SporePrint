import json
import time
from collections.abc import Iterable

from ..db import get_db
from ..vision.service import _deserialize_frame
from .models import ChamberCreate, ChamberUpdate, MaintenanceCreate


class ChamberInUseError(ValueError):
    """A chamber that still runs an active grow cannot be deleted (409)."""


class SessionLinkError(ValueError):
    """A session PATCH /api/chambers cannot link: unknown or ended (422)."""


class SessionBoundElsewhereError(ValueError):
    """A session bound to another chamber cannot be linked to this one (409)."""


class ChamberBusyError(ValueError):
    """A grow cannot be bound to a chamber that already runs another active
    grow (409): a chamber runs one grow's setpoints, so the newer grow took it
    over from the one still in it."""


async def _sessions_changed(session_ids: Iterable[int]) -> None:
    """Tell the session-change listeners (the cloud sync) about sessions whose
    chamber binding or chamber name changed here: a session's snapshot names
    its chamber, so it would otherwise stay stale until the session's next
    edit."""
    # sessions.service imports this module at its top, so a module-level
    # import here would be circular.
    from ..sessions.service import _notify_session_changed
    for session_id in dict.fromkeys(session_ids):
        await _notify_session_changed(session_id)


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


async def _check_session_link(db, chamber_id: int, session_id: int) -> None:
    """Refuse a link the engine could not honour (inside the caller's
    transaction).

    The engine drives a session bound to a chamber (sessions.chamber_id) only
    in that chamber, so a link from another chamber made the dashboards show
    the grow in this chamber while this chamber's nodes ran something else;
    an ended session would show here forever (nothing ends it again to clear
    the link), and an unknown id failed on the foreign key with a bare 500. A
    grow in cold storage has left the chamber it grew in and may be linked to
    a fridge chamber (see sessions.service._CHAMBER_SESSION_SQL).
    """
    cursor = await db.execute(
        "SELECT status, chamber_id, current_phase FROM sessions WHERE id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        raise SessionLinkError(f"Session {session_id} not found")
    if row["status"] != "active":
        raise SessionLinkError(
            f"Session {session_id} is {row['status']}: only an active grow can be linked to a chamber"
        )
    bound = row["chamber_id"]
    if bound is not None and bound != chamber_id and row["current_phase"] != "cold_storage":
        raise SessionBoundElsewhereError(
            f"Session {session_id} runs in chamber {bound}: a grow runs only in the chamber "
            "it is bound to (only a grow in cold storage can be linked to another chamber)"
        )
    # sessions.service imports this module at its top, so a module-level
    # import here would be circular.
    from ..sessions.service import _busy_message, chamber_occupant
    if occupant := await chamber_occupant(db, chamber_id, besides=session_id):
        raise ChamberBusyError(_busy_message(chamber_id, occupant))


async def update_chamber(chamber_id: int, data: ChamberUpdate) -> dict | None:
    """Partial update; None for an unknown chamber.

    Linking a session (active_session_id) raises SessionLinkError for an
    unknown or ended session and SessionBoundElsewhereError for one bound to
    another chamber (_check_session_link). One transaction.
    """
    dumped = data.model_dump()
    linking = "active_session_id" in data.model_fields_set
    changed_sessions: list[int] = []

    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM chambers WHERE id = ?", (chamber_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        existing = _parse_chamber(row)

        name = dumped["name"] if dumped["name"] is not None else existing["name"]
        description = dumped["description"] if dumped["description"] is not None else existing["description"]
        node_ids = json.dumps(dumped["node_ids"]) if dumped["node_ids"] is not None else json.dumps(existing["node_ids"])
        # active_session_id is the one nullable link: an explicit `null` in the
        # request detaches the chamber from its session; omitting the field keeps it.
        active_session_id = dumped["active_session_id"] if linking else existing["active_session_id"]
        automation_rule_ids = json.dumps(dumped["automation_rule_ids"]) if dumped["automation_rule_ids"] is not None else json.dumps(existing["automation_rule_ids"])

        if linking and active_session_id is not None:
            await _check_session_link(db, chamber_id, active_session_id)

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
            # A session already bound to a chamber is never moved, and an
            # ended one keeps the chamber its history ran in.
            cursor = await db.execute(
                "UPDATE sessions SET chamber_id = ? "
                "WHERE id = ? AND chamber_id IS NULL AND status = 'active'",
                (chamber_id, active_session_id),
            )
            if cursor.rowcount:
                changed_sessions.append(active_session_id)
        if name != existing["name"]:
            # Every session bound here names the chamber in its snapshot.
            cursor = await db.execute("SELECT id FROM sessions WHERE chamber_id = ?", (chamber_id,))
            changed_sessions.extend(r["id"] for r in await cursor.fetchall())
        await db.commit()

        cursor = await db.execute("SELECT * FROM chambers WHERE id = ?", (chamber_id,))
        updated = _parse_chamber(await cursor.fetchone())
    await _sessions_changed(changed_sessions)
    return updated


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


async def chamber_contexts() -> list[tuple[list[int], list[str]]]:
    """Every (chamber ids, ids they list) a node listed in a chamber runs
    with, once per distinct set of chambers: the chambers that list the node
    (chambers_for_node) and every id they list. The automation engine runs a
    node's rules for those chambers' grow and with those ids (its
    _session_for_node); a node in no chamber has no entry."""
    listed = [(c["id"], [str(n) for n in c["node_ids"]])
              for c in await list_chambers() if isinstance(c.get("node_ids"), list)]
    contexts: dict[tuple[int, ...], list[str]] = {}
    for _chamber_id, nodes in listed:
        for node in nodes:
            ids = tuple(sorted(cid for cid, other in listed if node in other))
            if ids not in contexts:
                contexts[ids] = [n for cid, other in listed if cid in ids for n in other]
    return [(list(ids), nodes) for ids, nodes in contexts.items()]


async def add_node_to_chamber(db, chamber_id: int, node_id: str) -> bool:
    """List `node_id` in chamber `chamber_id`, inside the caller's open
    transaction (no commit). A node already listed stays listed once. False
    when there is no such chamber."""
    cursor = await db.execute("SELECT node_ids FROM chambers WHERE id = ?", (chamber_id,))
    row = await cursor.fetchone()
    if row is None:
        return False
    try:
        nodes = [str(n) for n in json.loads(row["node_ids"] or "[]")]
    except (TypeError, ValueError):
        nodes = []
    if node_id not in nodes:
        await db.execute("UPDATE chambers SET node_ids = ? WHERE id = ?",
                         (json.dumps([*nodes, node_id]), chamber_id))
    return True


async def delete_chamber(chamber_id: int) -> bool:
    """Delete a chamber, detaching its history first (one transaction).

    sessions / contamination_events / planned_events reference chambers(id)
    with no ON DELETE action and foreign_keys=ON, so a chamber that ever hosted
    a grow could not be deleted (IntegrityError → 500). Those records outlive
    the chamber with chamber_id = NULL; its maintenance log (chamber_id NOT
    NULL, meaningless without the chamber) goes with it.

    A chamber that still runs an active grow (bound to it, or linked by its
    active_session_id) raises ChamberInUseError: detaching a live grow made it
    "the newest session bound to no chamber", which every idle chamber's nodes
    and every unlisted node then ran with its setpoints. End the grow (or
    unlink it) first.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT active_session_id FROM chambers WHERE id = ?", (chamber_id,)
        )
        chamber = await cursor.fetchone()
        if chamber is None:
            return False
        cursor = await db.execute(
            "SELECT id, chamber_id FROM sessions WHERE status = 'active' "
            "AND (chamber_id = ? OR id = ?) ORDER BY id LIMIT 1",
            (chamber_id, chamber["active_session_id"]),
        )
        busy = await cursor.fetchone()
        if busy is not None:
            if busy["chamber_id"] == chamber_id:
                raise ChamberInUseError(
                    f"Chamber {chamber_id} still runs grow session {busy['id']}: "
                    "complete or abort it before deleting the chamber"
                )
            raise ChamberInUseError(
                f"Chamber {chamber_id} is linked to grow session {busy['id']}: "
                "unlink it (active_session_id null) or end the grow before deleting the chamber"
            )
        cursor = await db.execute("SELECT id FROM sessions WHERE chamber_id = ?", (chamber_id,))
        detached = [r["id"] for r in await cursor.fetchall()]
        for sql in (
            "UPDATE sessions SET chamber_id = NULL WHERE chamber_id = ?",
            "UPDATE contamination_events SET chamber_id = NULL WHERE chamber_id = ?",
            "UPDATE planned_events SET chamber_id = NULL WHERE chamber_id = ?",
            "DELETE FROM chamber_maintenance WHERE chamber_id = ?",
        ):
            await db.execute(sql, (chamber_id,))
        cursor = await db.execute("DELETE FROM chambers WHERE id = ?", (chamber_id,))
        await db.commit()
        deleted = cursor.rowcount > 0
    await _sessions_changed(detached)
    return deleted


# Last-24 h telemetry per (chamber, sensor) across ALL of each chamber's
# nodes (a node listed twice counts once). :ids is a JSON array of chamber ids.
_COMPARE_SQL = """
    SELECT cn.chamber_id, t.sensor,
           AVG(t.value) AS avg_val, MIN(t.value) AS min_val,
           MAX(t.value) AS max_val, COUNT(*) AS readings
    FROM (SELECT DISTINCT c.id AS chamber_id, j.value AS node_id
          FROM chambers c,
               json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j
          WHERE c.id IN (SELECT value FROM json_each(:ids))) cn
    JOIN telemetry_readings t ON t.node_id = cn.node_id AND t.timestamp >= :since
    GROUP BY cn.chamber_id, t.sensor
"""


async def compare_chambers(chamber_ids: list[int]) -> list[dict]:
    """Side-by-side telemetry comparison between chambers: per sensor, the
    last 24 h of every node the chamber lists (two nodes reporting temp_f are
    one series, not the last node's). Unknown ids are skipped; one query per
    request on one connection."""
    since = time.time() - 86400  # last 24h
    params = {"ids": json.dumps(chamber_ids), "since": since}
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM chambers WHERE id IN (SELECT value FROM json_each(:ids))", params
        )
        chambers = {r["id"]: _parse_chamber(r) for r in await cursor.fetchall()}
        cursor = await db.execute(_COMPARE_SQL, params)
        telemetry: dict[int, dict] = {cid: {} for cid in chambers}
        for r in await cursor.fetchall():
            telemetry[r["chamber_id"]][r["sensor"]] = {
                "avg": round(r["avg_val"], 1),
                "min": round(r["min_val"], 1),
                "max": round(r["max_val"], 1),
                "readings": r["readings"],
            }

    return [
        {
            "chamber_id": cid,
            "chamber_name": chambers[cid]["name"],
            "node_ids": chambers[cid]["node_ids"],
            "telemetry": telemetry[cid],
        }
        for cid in chamber_ids
        if cid in chambers
    ]


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
    Rows go through vision's _deserialize_frame, so the analyses are objects,
    as GET /api/vision/frames returns them.
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
        return [_deserialize_frame(r) for r in await cursor.fetchall()]


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
