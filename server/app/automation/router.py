from fastapi import APIRouter, HTTPException

from ..db import get_db
from .models import AutomationRule, ManualOverride
from .engine import set_override, get_overrides, clear_override as clear_override_engine
from .service import deserialize_rule_row, serialize_rule_data
from .smart_plugs import get_all_plugs, register_plug, send_plug_command

router = APIRouter()


# ─── Rules CRUD ─────────────────────────────────────────────────

@router.get("/rules")
async def list_rules():
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data, created_at FROM automation_rules ORDER BY priority DESC"
        )
        return [deserialize_rule_row(row) for row in await cursor.fetchall()]


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int):
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data FROM automation_rules WHERE id = ?",
            (rule_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Rule not found")
        return deserialize_rule_row(row)


@router.post("/rules")
async def create_rule(rule: AutomationRule):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
            (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
        )
        await db.commit()
        rule.id = cursor.lastrowid
    return rule.model_dump()


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, rule: AutomationRule):
    async with get_db() as db:
        result = await db.execute(
            "UPDATE automation_rules SET name=?, description=?, enabled=?, priority=?, rule_data=?, updated_at=unixepoch('now') WHERE id=?",
            (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule), rule_id),
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Rule not found")
    rule.id = rule_id
    return rule.model_dump()


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    async with get_db() as db:
        result = await db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Rule not found")
    return {"status": "deleted"}


@router.patch("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int):
    async with get_db() as db:
        cursor = await db.execute("SELECT enabled FROM automation_rules WHERE id = ?", (rule_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Rule not found")
        new_state = 0 if row["enabled"] else 1
        await db.execute("UPDATE automation_rules SET enabled = ? WHERE id = ?", (new_state, rule_id))
        await db.commit()
    return {"id": rule_id, "enabled": bool(new_state)}


# ─── Overrides ──────────────────────────────────────────────────

@router.get("/overrides")
async def list_overrides():
    return [o.model_dump() for o in await get_overrides()]


@router.post("/overrides")
async def create_override(override: ManualOverride):
    await set_override(override)
    return override.model_dump()


@router.delete("/overrides/{target}")
async def clear_override_route(target: str, channel: str | None = None):
    await clear_override_engine(target, channel)
    return {"status": "cleared"}


# ─── Firing History ─────────────────────────────────────────────

@router.get("/firings")
async def list_firings(limit: int = 50, rule_id: int | None = None):
    query = "SELECT * FROM automation_firings"
    params = []
    if rule_id:
        query += " WHERE rule_id = ?"
        params.append(rule_id)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]


# ─── Smart Plugs ────────────────────────────────────────────────

@router.get("/plugs")
async def list_plugs():
    return await get_all_plugs()


@router.post("/plugs")
async def add_plug(data: dict):
    await register_plug(
        plug_id=data["plug_id"],
        name=data["name"],
        plug_type=data.get("plug_type", "shelly"),
        mqtt_topic_prefix=data["mqtt_topic_prefix"],
        device_role=data.get("device_role"),
    )
    return {"status": "registered"}


@router.post("/plugs/{plug_id}/command")
async def command_plug(plug_id: str, data: dict):
    state = data.get("state", "off")
    await send_plug_command(plug_id, state)
    return {"status": "sent", "plug_id": plug_id, "state": state}
