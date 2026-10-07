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


# ── Built-ins added in later releases reach Pis seeded before them ───────

NEWER_BUILTINS = ("CO2 Hard Ceiling", "CO2 Floor — Restrict FAE")


async def _rule_names() -> list[str]:
    async with get_db() as db:
        cursor = await db.execute("SELECT name FROM automation_rules ORDER BY id")
        return [r["name"] for r in await cursor.fetchall()]


async def _seed_as_an_older_release() -> None:
    """A DB seeded by a release that shipped every built-in except the newer ones."""
    async with get_db() as db:
        for rule in BUILTIN_RULES:
            if rule.name in NEWER_BUILTINS:
                continue
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
                (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
            )
        await db.commit()


async def test_newer_builtins_are_added_to_an_already_seeded_pi(caplog):
    assert all(name in {r.name for r in BUILTIN_RULES} for name in NEWER_BUILTINS)
    await _seed_as_an_older_release()
    with caplog.at_level("INFO", logger="app.automation.service"):
        await seed_builtin_rules()
    # The boot log names what was added.
    assert any("CO2 Hard Ceiling" in r.getMessage() for r in caplog.records)
    names = await _rule_names()
    assert sorted(names) == sorted(r.name for r in BUILTIN_RULES)
    assert len(names) == len(set(names))


async def test_a_builtin_the_operator_deleted_stays_deleted():
    await _seed_as_an_older_release()
    await seed_builtin_rules()
    async with get_db() as db:
        await db.execute("DELETE FROM automation_rules WHERE name = ?", ("CO2 Hard Ceiling",))
        await db.commit()
    await seed_builtin_rules()
    assert "CO2 Hard Ceiling" not in await _rule_names()


async def test_a_fresh_pi_records_every_builtin_as_offered():
    await seed_builtin_rules()
    async with get_db() as db:
        await db.execute("DELETE FROM automation_rules WHERE name = ?", ("CO2 Floor — Restrict FAE",))
        await db.commit()
    await seed_builtin_rules()
    assert "CO2 Floor — Restrict FAE" not in await _rule_names()
