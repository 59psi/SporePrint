import json
import logging

from ..db import get_db
from ..species.profiles import canonical_species_id
from .models import AutomationRule, RuleAction
from .templates import BUILTIN_RULES, LEGACY_BUILTIN_RULES

log = logging.getLogger(__name__)

# Fields stored as top-level columns (not in rule_data JSON blob)
_RULE_META_FIELDS = {"id", "name", "description", "enabled", "priority"}

# The behaviour-defining fields compared when deciding whether a stored rule is
# still an unedited copy of a legacy built-in (see LEGACY_BUILTIN_RULES). The
# priority column is compared too (see _upgrade_legacy_builtin_rules): it
# decides which rule wins an actuator, so a changed priority is an edit.
_LEGACY_MATCH_FIELDS = {
    "applies_to_phases", "applies_to_species", "requires_absent_target",
    "condition", "action", "cooldown_seconds", "safety_max_on_seconds",
    "notification", "log_to_session",
}


def rule_applies_to_species(applies_to_species: list[str] | None, species_id: str | None) -> bool:
    """Does a rule scoped to `applies_to_species` apply to this session's species?

    Species ids drift between separators: sessions store the hyphenated UI
    spelling ("lions-mane", see species.profiles.canonical_species_id) while the
    seeded templates name the underscored table ids ("lions_mane"). An exact
    `in` check never matched, so every species-scoped rule was dead. Compare
    both sides canonicalised. An unscoped rule applies to everything; a scoped
    rule never applies when there is no species.
    """
    if not applies_to_species:
        return True
    if not species_id:
        return False
    wanted = canonical_species_id(species_id)
    return any(canonical_species_id(s) == wanted for s in applies_to_species)


def normalize_rule_id(rule_id) -> int | None:
    """Canonicalise a rule id to int (the type of AutomationRule.id and the
    SQLite PK), accepting either an int or a numeric string.

    Remote surfaces disagreed on the wire type — the cloud `system`/`rule`
    suspend path required a str while the automation_update/delete CRUD path
    required an int, so a caller sending a numeric id was accepted by one and
    rejected by the other. Both now route id through here: a numeric id in
    either form resolves to the same int, and non-numeric / empty / None
    values return None so the caller can reject them uniformly.
    """
    if isinstance(rule_id, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(rule_id, int):
        return rule_id
    if isinstance(rule_id, str) and rule_id.strip():
        try:
            return int(rule_id.strip())
        except ValueError:
            return None
    return None


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
    """Seed built-in automation rule templates into the database if empty.

    On an already-seeded database, upgrade any built-in whose shipped form was
    unsafe (LEGACY_BUILTIN_RULES) — but only a copy the operator never edited.
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM automation_rules")
        row = await cursor.fetchone()
        if row["cnt"] > 0:
            await _upgrade_legacy_builtin_rules(db)
            return

        for rule in BUILTIN_RULES:
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
                (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
            )
        await db.commit()


def _same_rule(a: AutomationRule, b: AutomationRule) -> bool:
    """Same behaviour: priority plus the _LEGACY_MATCH_FIELDS."""
    return (a.priority == b.priority
            and a.model_dump(include=_LEGACY_MATCH_FIELDS)
            == b.model_dump(include=_LEGACY_MATCH_FIELDS))


async def _upgrade_legacy_builtin_rules(db) -> None:
    """Rewrite unedited copies of unsafe legacy built-ins to the current template.

    Runs inside seed_builtin_rules' connection; commits once if anything changed.
    """
    current = {r.name: r for r in BUILTIN_RULES}
    changed = False
    for name, legacy in LEGACY_BUILTIN_RULES.items():
        replacement = current.get(name)
        if replacement is None:
            continue
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data "
            "FROM automation_rules WHERE name = ?",
            (name,),
        )
        for row in await cursor.fetchall():
            try:
                stored = AutomationRule.model_validate(deserialize_rule_row(row))
            except Exception:
                continue
            if not _same_rule(stored, legacy):
                # Operator-edited (or already upgraded) — leave it. An edited
                # copy keeps the old logic, which rule arbitration can make
                # matter (a forecast-only Pre-cool now holds the cooler ON
                # against the Cooling Cutoff), so say so at every boot.
                if not _same_rule(stored, replacement):
                    log.warning(
                        "Automation rule '%s' (id %s) was edited, so it was not upgraded "
                        "to the current built-in template — review it against the shipped "
                        "rule (%s)", name, row["id"], replacement.description,
                    )
                continue
            await db.execute(
                "UPDATE automation_rules SET description=?, priority=?, rule_data=?, "
                "updated_at=unixepoch('now') WHERE id=?",
                (replacement.description, replacement.priority,
                 serialize_rule_data(replacement), row["id"]),
            )
            changed = True
    if changed:
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


# Seeded native-node rules predate MAC-derived node ids: they still name the
# fixed placeholders `relay-01` (a relay node) and `light-01` (a lighting node)
# from a time when node ids were static. Real nodes self-register under
# MAC-derived ids (node-XXXX) with a provisioned `node_type`, so a rule left
# naming the placeholder publishes to sporeprint/relay-01/cmd/* — a topic no
# node subscribes to — and the firing logs status='sent' while nothing moves.
# The placeholder must be resolved to the chamber's actual node of that role at
# fire time (engine) and reflected in validation + coverage. (V3-2)
_PLACEHOLDER_NODE_TYPE = {"relay-01": "relay", "light-01": "lighting"}


# Node ids listed in any chamber (chambers.node_ids is a JSON list; an invalid
# value lists no nodes).
_CHAMBER_NODE_IDS_SQL = (
    "SELECT j.value FROM chambers c, "
    "json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j"
)


async def resolve_node_target(
    target: str, chamber_nodes: list[str] | None = None,
) -> str | None:
    """Map a native-node target to the node_id that should actually receive it.

    - A non-placeholder target (a real node id, a `plug-*` id, a `vendor:*`
      override key) is returned unchanged — resolution is a no-op for it.
    - A seeded placeholder (`relay-01` / `light-01`):
        * if a node is registered under the placeholder id itself (a real
          deployment may literally have named its node relay-01) → that id;
        * with ``chamber_nodes`` (the node ids of the chamber the rule is
          acting for): that chamber's most-recently-seen node of the
          placeholder's role, else a node of that role listed in NO chamber —
          never another chamber's node, which would drive the wrong closet;
        * without: the most-recently-seen node whose `node_type` matches the
          role the placeholder stands for → its node_id;
        * else ``None`` — no node of that role is paired, so the caller
          (validate_action_channel / coverage / engine) can surface the gap
          instead of publishing into the void.
    """
    node_type = _PLACEHOLDER_NODE_TYPE.get(target)
    if node_type is None:
        return target
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT 1 FROM hardware_nodes WHERE node_id = ?", (target,)
        )
        if await cursor.fetchone() is not None:
            return target
        if chamber_nodes:
            marks = ",".join("?" for _ in chamber_nodes)
            cursor = await db.execute(
                f"SELECT node_id FROM hardware_nodes WHERE node_type = ? "
                f"AND node_id IN ({marks}) ORDER BY last_seen DESC LIMIT 1",
                (node_type, *chamber_nodes),
            )
            row = await cursor.fetchone()
            if row is None:
                cursor = await db.execute(
                    f"SELECT node_id FROM hardware_nodes WHERE node_type = ? "
                    f"AND node_id NOT IN ({_CHAMBER_NODE_IDS_SQL}) "
                    f"ORDER BY last_seen DESC LIMIT 1",
                    (node_type,),
                )
                row = await cursor.fetchone()
            return row["node_id"] if row else None
        cursor = await db.execute(
            "SELECT node_id FROM hardware_nodes WHERE node_type = ? "
            "ORDER BY last_seen DESC LIMIT 1",
            (node_type,),
        )
        row = await cursor.fetchone()
    return row["node_id"] if row else None


async def validate_action_channel(action: RuleAction) -> str | None:
    """Return an error message if the action can't actually reach an actuator.

    Two silent-no-op classes are caught here — the one place we can, because
    nodes enumerate their real channel names in the health doc (see mqtt.py)
    and register their `node_type` on every heartbeat:

    - **Unregistered target node.** A seeded rule still naming a placeholder
      (`relay-01` / `light-01`) when no node of that role is paired would
      publish to a topic nothing subscribes to. Flag it so the mismatch is
      visible (rule create/update → 422, coverage → unavailable, engine → a
      logged warning) instead of a firing that reads status='sent'. (V3-2)

    - **Misnamed channel.** Channel names are MQTT command routing keys: the
      node dispatches ``cmd/<channel>`` by exact match and drops anything else,
      so a rule for a channel the node lacks *looks* armed while the actuator
      never moves. Validated against the RESOLVED node's reported channels.

    Follows the firmware's own posture: validate, don't discover. Vendor
    actions (routed through the integrations dispatcher, not MQTT), smart-plug /
    non-node targets, and nodes that have never reported channels all pass
    through.
    """
    if action.vendor_slug:
        return None

    resolved = await resolve_node_target(action.target)
    if resolved is None:
        # A placeholder target that resolved to no real node — nothing of this
        # role is paired to the chamber.
        node_type = _PLACEHOLDER_NODE_TYPE[action.target]
        return (
            f"No '{node_type}' node is registered for target '{action.target}'. "
            f"Pair a {node_type} node or point the rule at a registered node id."
        )

    if not action.channel:
        return None

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE node_id = ?", (resolved,)
        )
        row = await cursor.fetchone()

    if not row or not row["channels"]:
        return None
    known = json.loads(row["channels"])
    if not isinstance(known, list) or action.channel in known:
        return None

    return (
        f"Node '{action.target}' has no channel '{action.channel}'. "
        f"Available channels: {', '.join(known)}"
    )


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
