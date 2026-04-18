import json

from ..db import get_db
from .models import AutomationRule
from .templates import BUILTIN_RULES

# Fields stored as top-level columns (not in rule_data JSON blob)
_RULE_META_FIELDS = {"id", "name", "description", "enabled", "priority"}


def deserialize_rule_row(row) -> dict:
    """Deserialize a rule from a database row, merging rule_data JSON with metadata columns."""
    data = json.loads(row["rule_data"])
    data["id"] = row["id"]
    data["name"] = row["name"]
    data["description"] = row["description"] or ""
    data["enabled"] = bool(row["enabled"])
    data["priority"] = row["priority"]
    return data


def serialize_rule_data(rule: AutomationRule) -> str:
    """Serialize rule fields (excluding metadata columns) to JSON for storage."""
    return json.dumps(rule.model_dump(exclude=_RULE_META_FIELDS))


async def seed_builtin_rules():
    """Seed built-in automation rule templates into the database if empty."""
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM automation_rules")
        row = await cursor.fetchone()
        if row["cnt"] > 0:
            return  # Already seeded

        for rule in BUILTIN_RULES:
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
                (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
            )
        await db.commit()


# ─── CRUD for the automation router (P12 — raw SQL moved out of router) ───
# Prior to v3.3.2 automation/router.py executed raw SQL inline. The router now
# delegates to these helpers; the database shape stays here in one place.

async def list_rules_with_created_at() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data, created_at "
            "FROM automation_rules ORDER BY priority DESC"
        )
        return [deserialize_rule_row(row) for row in await cursor.fetchall()]


async def get_rule(rule_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data "
            "FROM automation_rules WHERE id = ?",
            (rule_id,),
        )
        row = await cursor.fetchone()
        return deserialize_rule_row(row) if row else None


async def create_rule(rule: AutomationRule) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
            (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
        )
        await db.commit()
        return cursor.lastrowid


async def update_rule(rule_id: int, rule: AutomationRule) -> bool:
    async with get_db() as db:
        result = await db.execute(
            "UPDATE automation_rules SET name=?, description=?, enabled=?, priority=?, "
            "rule_data=?, updated_at=unixepoch('now') WHERE id=?",
            (rule.name, rule.description, int(rule.enabled), rule.priority,
             serialize_rule_data(rule), rule_id),
        )
        await db.commit()
        return result.rowcount > 0


async def delete_rule(rule_id: int) -> bool:
    async with get_db() as db:
        result = await db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
        await db.commit()
        return result.rowcount > 0


async def toggle_rule(rule_id: int) -> bool | None:
    """Toggle the `enabled` flag. Returns the new value, or None if not found."""
    async with get_db() as db:
        cursor = await db.execute("SELECT enabled FROM automation_rules WHERE id = ?", (rule_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        new_state = 0 if row["enabled"] else 1
        await db.execute("UPDATE automation_rules SET enabled = ? WHERE id = ?", (new_state, rule_id))
        await db.commit()
        return bool(new_state)


async def list_firings(limit: int = 50, rule_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM automation_firings"
    params: list = []
    if rule_id is not None:
        query += " WHERE rule_id = ?"
        params.append(rule_id)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]
