import json

from app.automation.models import AutomationRule
from app.automation.service import (
    deserialize_rule_row,
    serialize_rule_data,
    seed_builtin_rules,
)
from app.automation.templates import BUILTIN_RULES
from app.db import get_db


def test_deserialize_rule_row():
    rule_data = {"condition": {"type": "threshold", "threshold": {"sensor": "temp_f", "operator": "gt", "value": 80}}, "action": {"target": "relay-01", "state": "on"}, "cooldown_seconds": 60, "log_to_session": True}
    row = {
        "id": 1,
        "name": "Test Rule",
        "description": "A test",
        "enabled": 1,
        "priority": 5,
        "rule_data": json.dumps(rule_data),
    }
    result = deserialize_rule_row(row)
    assert result["id"] == 1
    assert result["name"] == "Test Rule"
    assert result["description"] == "A test"
    assert result["enabled"] is True
    assert result["priority"] == 5
    assert result["condition"]["type"] == "threshold"


def test_serialize_rule_data():
    rule = BUILTIN_RULES[0]
    serialized = serialize_rule_data(rule)
    data = json.loads(serialized)
    assert "id" not in data
    assert "name" not in data
    assert "description" not in data
    assert "enabled" not in data
    assert "priority" not in data
    assert "condition" in data
    assert "action" in data


def test_serialize_deserialize_roundtrip():
    original = BUILTIN_RULES[0]
    serialized = serialize_rule_data(original)
    row = {
        "id": 99,
        "name": original.name,
        "description": original.description,
        "enabled": 1,
        "priority": original.priority,
        "rule_data": serialized,
    }
    reconstructed = deserialize_rule_row(row)
    rule = AutomationRule.model_validate(reconstructed)
    assert rule.name == original.name
    assert rule.condition.type == original.condition.type


async def test_seed_builtin_rules():
    await seed_builtin_rules()
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM automation_rules")
        row = await cursor.fetchone()
    assert row["cnt"] == len(BUILTIN_RULES)


async def test_seed_builtin_rules_idempotent():
    await seed_builtin_rules()
    await seed_builtin_rules()
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM automation_rules")
        row = await cursor.fetchone()
    assert row["cnt"] == len(BUILTIN_RULES)
