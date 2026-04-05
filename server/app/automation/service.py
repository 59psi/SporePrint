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
