import json
import logging
import time
from collections.abc import Collection

from fastapi import HTTPException

from ..db import get_db
from ..species.profiles import canonical_species_id
from .models import (
    ACTION_STATES,
    PHOTOPERIOD_VALUES,
    AutomationRule,
    ConditionType,
    RuleAction,
    RuleCondition,
)
from .templates import (
    BUILTIN_RULES,
    RETIRED_BUILTIN_RULES,
    SEEDED_BEFORE_V5,
    SEEDED_V5_0_TO_V5_1,
    SUPERSEDED_BUILTIN_RULES,
)

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


# Duty-value keys a node command may carry (relay pwm 0-255, lighting level
# 0-1023 — the lighting bank also takes pwm as a level alias).
_DUTY_KEYS = ("pwm", "level")


def is_off_command(payload: dict) -> bool:
    """Does this node/plug command switch its actuator OFF?"""
    return str(payload.get("state", "")).strip().lower() == "off"


def drop_duty_from_off(payload: dict) -> dict:
    """The command to publish: an OFF loses any pwm / level, anything else is unchanged.

    Node firmware released before the hardware audit let a duty value in the
    same command win over the state, so {"state": "off", "pwm": 180} switched
    the channel ON at duty 180. Current firmware lets "off" win, but deployed
    nodes still run the old image, so an OFF must never carry a duty value on
    the wire. Returns a copy when anything is dropped; the caller's dict is
    never modified.
    """
    if not is_off_command(payload) or not any(k in payload for k in _DUTY_KEYS):
        return payload
    return {k: v for k, v in payload.items() if k not in _DUTY_KEYS}


def node_command_state(state):
    """A node command's `state` the way node firmware acts on it.

    The firmware reads a string state as ON only when it is "on" (after
    lower-casing) and as an explicit OFF otherwise: "false", "0", "" and
    "toggle" all switch a channel off. "on" in any case, with surrounding
    spaces, is ON here. Anything but a string is returned unchanged: the
    firmware ignores a state that is not a string.
    """
    if isinstance(state, str):
        return "on" if state.strip().lower() == "on" else "off"
    return state


def normalize_node_command(payload: dict) -> dict:
    """The command a node is sent: a string state spelled "on" or "off"
    (node_command_state), and an OFF without a duty value (drop_duty_from_off).

    Every node command goes through here before it is published, so the
    frame means the same to every firmware release and to the Pi's own
    bookkeeping (is_off_command clears a safety ceiling only on an OFF): a
    {"state": "false", "pwm": 200} was published as is, switching the channel
    OFF on current firmware and ON at 200 on firmware before the hardware
    audit, while the Pi counted it as an ON. Returns a copy when anything
    changes; the caller's dict is never modified. Plug commands keep their
    vendor's own reading (send_plug_command).
    """
    state = payload.get("state")
    canonical = node_command_state(state)
    if canonical != state:
        payload = {**payload, "state": canonical}
    return drop_duty_from_off(payload)


# The lighting scene with every dim channel at 0 (firmware sp_core/scene_table.h).
LIGHTS_OFF_SCENE = "colonization_dark"


def node_command_topic(target: str, channel: str | None, scene: str | None) -> str:
    """The cmd/* topic a native node command goes to.

    The firmware's cmd_router dispatches on the EXACT topic suffix (firmware
    lib/sp_core/cmd_router.h), so the suffix is the contract:
      cmd/<channel> — switch/dim a named channel
      cmd/scene     — apply a lighting scene (a node with a dim bank)
      cmd/config    — intervals and calibration; it reads no on/off state
    """
    if channel:
        return f"sporeprint/{target}/cmd/{channel}"
    if scene:
        return f"sporeprint/{target}/cmd/scene"
    return f"sporeprint/{target}/cmd/config"


def node_off_command(target: str, channel: str | None, reason: str) -> tuple[str, dict]:
    """(topic, payload) that switch a native node actuator OFF.

    A channel: {"state": "off"} on cmd/<channel>. No channel: the actuator is
    the node's lighting, driven by scene, so the OFF is the all-off scene on
    cmd/scene. One definition for every automation OFF (rule, safety ceiling,
    session end): the safety ceiling used to send a scene rule's OFF to
    cmd/config, which switched nothing while it read as sent.
    """
    if channel:
        return node_command_topic(target, channel, None), {"state": "off", "reason": reason}
    return (node_command_topic(target, None, LIGHTS_OFF_SCENE),
            {"state": "off", "scene": LIGHTS_OFF_SCENE, "reason": reason})


def hold_applies(
    hold_target: str, hold_channel: str | None, names: Collection[str], *,
    channel: str | None = None, scene: str | None = None, vendor_slug: str | None = None,
) -> bool:
    """Does a manual hold (or a safety lockout) on ``hold_target`` /
    ``hold_channel`` keep an action out of automation?

    ``names`` is every name the action's actuator goes by; ``channel``,
    ``scene`` and ``vendor_slug`` are the action's. A hold is stored under the
    name it was placed on: a seeded rule names the relay-01 / light-01
    placeholder while the chamber page pins the real node it resolves to,
    and a plug is held by its id or by ``plug-<role>``. Under any of the
    names, a hold on the action's channel or on the whole target counts (no
    channel; an empty channel is the whole target, as the override key reads
    it). A scene sets every dim channel of its node (firmware
    handle_scene_cmd), so a hold on any one channel of the node holds a
    scene action too.

    The one rule for the engine's rule evaluation (_target_holds) and for
    session-end safing (sessions.service), which cannot import the engine:
    the end of a grow used to switch off a light whose white channel the
    operator had pinned, and a plug held by its id through a rule naming
    its role.
    """
    if hold_target not in names:
        return False
    hold_channel = hold_channel or None
    channel = channel or None
    if hold_channel is None or hold_channel == channel:
        return True
    return bool(scene) and channel is None and not vendor_slug


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


# Ids of stored rules already logged as invalid (each once per process).
_invalid_rules_logged: set = set()


def valid_rules(rows) -> list[AutomationRule]:
    """The stored rules (automation_rules rows) that validate, in row order.

    A row that does not (a hand-edited, imported or downgraded database) is
    skipped and logged once. Validated in one list comprehension, it made
    every load raise: the engine ran no rule at all — the CO2 Hard Ceiling
    included — and logged an error on every frame, and the coverage endpoint
    failed.
    """
    rules: list[AutomationRule] = []
    for row in rows:
        try:
            rules.append(AutomationRule.model_validate(deserialize_rule_row(row)))
        except Exception as e:
            if row["id"] not in _invalid_rules_logged:
                _invalid_rules_logged.add(row["id"])
                log.error("Automation rule %r (id %s) is not valid and is skipped: %s",
                          row["name"], row["id"], e)
    return rules


def serialize_rule_data(rule: AutomationRule) -> str:
    """Serialize rule fields (excluding metadata columns) to JSON for storage."""
    return json.dumps(rule.model_dump(exclude=_RULE_META_FIELDS))


# user_settings key: JSON list of the built-in names this Pi was ever given.
_BUILTINS_OFFERED_KEY = "automation_builtins_offered"
# user_settings key: JSON list of the RETIRED_BUILTIN_RULES names already
# handled on this Pi (each is switched off at most once).
_BUILTINS_RETIRED_KEY = "automation_builtins_retired"


async def seed_builtin_rules():
    """Seed built-in automation rule templates into the database.

    Every built-in is offered once: a name this Pi has not been given yet is
    inserted (unless a rule by that name already exists) and recorded, so a
    built-in added in a later release reaches Pis seeded before it, and one
    the operator deleted stays deleted. A database seeded before that record
    existed (before 5.2.0) starts from the built-ins its seeding release gave
    it (_builtins_given_before_tracking), so its deleted ones stay deleted too.

    On an already-seeded database, also upgrade any built-in whose shipped
    form was superseded (SUPERSEDED_BUILTIN_RULES), and switch off any copy of
    a built-in no release ships any more (RETIRED_BUILTIN_RULES), but only a
    copy the operator never edited.
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM automation_rules")
        row = await cursor.fetchone()
        seeded_before = row["cnt"] > 0
        if seeded_before:
            await _upgrade_legacy_builtin_rules(db)
            await _retire_builtin_rules(db)

        offered = await _load_name_list(db, _BUILTINS_OFFERED_KEY)
        if offered is None:
            offered = await _builtins_given_before_tracking(db) if seeded_before else set()
        cursor = await db.execute("SELECT name FROM automation_rules")
        present = {r["name"] for r in await cursor.fetchall()}

        added = []
        for rule in BUILTIN_RULES:
            if rule.name in offered:
                continue
            offered.add(rule.name)
            if rule.name in present:
                continue
            await db.execute(
                "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
                (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
            )
            added.append(rule.name)
        await _store_name_list(db, _BUILTINS_OFFERED_KEY, offered)
        await db.commit()
    _rules_changed()
    if added and seeded_before:
        # An addition to a Pi already running its own rule set changes what
        # drives its actuators, so it is said where the operator will see it.
        log.warning(
            "Added built-in automation rule(s) this Pi did not have yet: %s. "
            "Delete any you do not want; a deleted built-in is not added again.",
            ", ".join(added),
        )


async def _load_name_list(db, key: str) -> set[str] | None:
    """A user_settings JSON list of names, or None when the key is absent."""
    cursor = await db.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return set(json.loads(row["value"])) if row else None


async def _store_name_list(db, key: str, names: set[str]) -> None:
    await db.execute(
        "INSERT INTO user_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = unixepoch('now')",
        (key, json.dumps(sorted(names))),
    )


async def _builtins_given_before_tracking(db) -> set[str]:
    """The built-ins a database seeded before 5.2.0 was given, by name.

    Those releases seeded only an empty table and recorded nothing, so a
    built-in missing now may have been deleted, or renamed, by the operator,
    and must not come back. Which release seeded the table is read off what is
    stored. 5.0.0 to 5.1.x seeded SEEDED_V5_0_TO_V5_1 — all 24 current names —
    so any of the names 5.0.0 added, or a seed batch (the rows sharing the
    first row's created_at) spanning more ids than an older release seeded,
    marks such a table. Anything else was seeded by 0.2 to 4.x
    (SEEDED_BEFORE_V5), and only the names 5.0.0 added are new to it. A table
    with no shipped built-in left at all is treated as one whose operator
    removed them all: nothing is added to it.
    """
    cursor = await db.execute("SELECT id, name, created_at FROM automation_rules ORDER BY id")
    rows = await cursor.fetchall()
    present = {r["name"] for r in rows}
    before_v5, v5 = set(SEEDED_BEFORE_V5), set(SEEDED_V5_0_TO_V5_1)
    if not present & (before_v5 | v5):
        log.warning(
            "No built-in automation rule is left on this Pi (each was deleted or renamed), "
            "so none of the newer built-ins was added either: %s. docs/automation-rules.md "
            "describes them if you want one.",
            ", ".join(sorted(v5 - before_v5)),
        )
        return before_v5 | v5
    first = rows[0]
    batch_end = max(r["id"] for r in rows if r["created_at"] == first["created_at"])
    if present & (v5 - before_v5) or batch_end - first["id"] + 1 > len(SEEDED_BEFORE_V5):
        return v5
    return before_v5


async def _retire_builtin_rules(db) -> None:
    """Switch off, once, each unedited copy of a RETIRED_BUILTIN_RULES rule.

    Runs inside seed_builtin_rules' connection, which commits. A name is
    handled once per Pi (_BUILTINS_RETIRED_KEY), so an operator who switches
    a retired rule back on keeps it on. An edited copy is the operator's own
    rule now: it is left as it is and named in the log.
    """
    done = await _load_name_list(db, _BUILTINS_RETIRED_KEY) or set()
    pending = [name for name in RETIRED_BUILTIN_RULES if name not in done]
    if not pending:
        return
    for name in pending:
        form = RETIRED_BUILTIN_RULES[name]
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
            if not _same_rule(stored, form):
                log.warning(
                    "Automation rule '%s' (id %s) is a built-in no release ships any more, "
                    "and it was edited, so it was left as it is — review it (%s)",
                    name, row["id"], form.description,
                )
            elif row["enabled"]:
                await db.execute(
                    "UPDATE automation_rules SET enabled = 0, updated_at = unixepoch('now') "
                    "WHERE id = ?",
                    (row["id"],),
                )
                log.warning(
                    "Switched off automation rule '%s' (id %s): a built-in no release ships "
                    "any more (see docs/automation-rules.md). Switch it back on if you want it.",
                    name, row["id"],
                )
        done.add(name)
    await _store_name_list(db, _BUILTINS_RETIRED_KEY, done)


def _same_rule(a: AutomationRule, b: AutomationRule) -> bool:
    """Same behaviour: priority plus the _LEGACY_MATCH_FIELDS."""
    return (a.priority == b.priority
            and a.model_dump(include=_LEGACY_MATCH_FIELDS)
            == b.model_dump(include=_LEGACY_MATCH_FIELDS))


async def _upgrade_legacy_builtin_rules(db) -> None:
    """Rewrite unedited copies of superseded built-ins to the current template.

    A stored copy matching ANY superseded shipped form of its name is upgraded.
    Runs inside seed_builtin_rules' connection; commits once if anything changed.
    """
    current = {r.name: r for r in BUILTIN_RULES}
    changed = False
    for name, forms in SUPERSEDED_BUILTIN_RULES.items():
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
            if not any(_same_rule(stored, form) for form in forms):
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


# ─── Rule CRUD ──────────────────────────────────────────────────
# The one implementation of rule storage. /api/automation/rules (router.py)
# and the cloud relay's automation_* requests (cloud/integrations_proxy.py)
# both go through these functions, so an operator's rule is checked the same
# way whichever surface saved it.

# Moves after every committed write to automation_rules. The engine's rule
# cache (engine.load_rules) reloads as soon as it changes, so a rule the
# operator just disabled, edited or deleted stops firing at once instead of
# for the rest of the cache's lifetime.
_rules_generation = 0


def rules_generation() -> int:
    """A counter that changes whenever automation_rules was written."""
    return _rules_generation


def _rules_changed() -> None:
    global _rules_generation
    _rules_generation += 1


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
# fire time (engine) and reflected in validation + coverage.
_PLACEHOLDER_NODE_TYPE = {"relay-01": "relay", "light-01": "lighting"}


# Node ids listed in any chamber (chambers.node_ids is a JSON list; an invalid
# value lists no nodes).
_CHAMBER_NODE_IDS_SQL = (
    "SELECT j.value FROM chambers c, "
    "json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j"
)


async def resolve_node_target(
    target: str, chamber_nodes: list[str] | None = None, *, grow_id: int | None = None,
) -> str | None:
    """Map a native-node target to the node_id that should actually receive it.

    - A non-placeholder target (a real node id, a `plug-*` id, a `vendor:*`
      override key) is returned unchanged — resolution is a no-op for it.
    - A seeded placeholder (`relay-01` / `light-01`) stands for a node of its
      role, chosen in the steps smart_plugs.chamber_plug takes for a plug
      role, the node seen last first within each step:
        * if a node is registered under the placeholder id itself (a real
          deployment may literally have named its node relay-01) → that id;
        * with ``chamber_nodes`` (the node ids of the chamber the rule is
          acting for): that chamber's node of the placeholder's role, else a
          node of that role listed in NO chamber — never another chamber's
          node, which would drive the wrong closet;
        * without (nodes in no chamber): a node of the role listed in no
          chamber, else one of a chamber that runs the same grow
          (``grow_id``, the grow those nodes run;
          sessions.service.chamber_nodes_running names those chambers'
          nodes), never one of a chamber that runs a grow of its own. With
          no grow given (rule validation, the coverage verdict, nodes in no
          chamber that run no grow) that last step takes the node of the
          role seen last anywhere;
        * else ``None`` — no node of that role answers, so the caller
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
        cursor = await db.execute(
            f"SELECT node_id, node_id IN ({_CHAMBER_NODE_IDS_SQL}) AS chamber_listed "
            "FROM hardware_nodes WHERE node_type = ? ORDER BY last_seen DESC, node_id",
            (node_type,),
        )
        nodes = [(r["node_id"], bool(r["chamber_listed"])) for r in await cursor.fetchall()]
    unlisted = [node for node, listed in nodes if not listed]
    if chamber_nodes:
        found = [node for node, _listed in nodes if node in chamber_nodes] or unlisted
        return found[0] if found else None
    if unlisted:
        return unlisted[0]
    if not nodes:
        return None
    if grow_id is None:
        return nodes[0][0]
    # sessions.service imports this module at its top: a module-level import
    # here would be circular.
    from ..sessions.service import chamber_nodes_running
    same_grow = set(await chamber_nodes_running(grow_id))
    return next((node for node, _listed in nodes if node in same_grow), None)


async def placeholder_nodes(target: str) -> list[str] | None:
    """Every node a seeded placeholder target (relay-01 / light-01) can land
    on, whichever chamber its rule fired for: the node registered under the
    placeholder's own id when there is one (resolve_node_target always picks
    it), else every registered node of the placeholder's role, most recently
    seen first ([] when none is paired). None for any other target, which
    only ever lands on itself.

    Session-end safing switches all of them off: resolving the placeholder
    once (to the node seen last, anywhere) sent the OFF to another chamber's
    node while the one the ON went to stayed on."""
    node_type = _PLACEHOLDER_NODE_TYPE.get(target)
    if node_type is None:
        return None
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM hardware_nodes WHERE node_id = ?", (target,))
        if await cursor.fetchone() is not None:
            return [target]
        cursor = await db.execute(
            "SELECT node_id FROM hardware_nodes WHERE node_type = ? "
            "ORDER BY last_seen DESC, node_id",
            (node_type,),
        )
        return [r["node_id"] for r in await cursor.fetchall()]


async def validate_action_channel(
    action: RuleAction, chamber_nodes: list[str] | None = None,
) -> str | None:
    """Return an error message if the action can't actually reach an actuator.

    Two silent-no-op classes are caught here — the one place we can, because
    nodes enumerate their real channel names in the health doc (see mqtt.py)
    and register their `node_type` on every heartbeat:

    - **Unregistered target node.** A seeded rule still naming a placeholder
      (`relay-01` / `light-01`) when no node of that role is paired would
      publish to a topic nothing subscribes to. Flag it so the mismatch is
      visible (rule create/update → 422, coverage → unavailable, engine → a
      logged warning) instead of a firing that reads status='sent'.

    - **Misnamed channel.** Channel names are MQTT command routing keys: the
      node dispatches ``cmd/<channel>`` by exact match and drops anything else,
      so a rule for a channel the node lacks *looks* armed while the actuator
      never moves. Validated against the RESOLVED node's reported channels.

    Follows the firmware's own posture: validate, don't discover. Vendor
    actions (routed through the integrations dispatcher, not MQTT), smart-plug /
    non-node targets, and nodes that have never reported channels all pass
    through. With ``chamber_nodes`` a placeholder resolves for that chamber,
    the way the engine resolves it when it drives the chamber; without, for
    nodes in no chamber with no grow given (resolve_node_target).
    """
    if action.vendor_slug:
        return None

    resolved = await resolve_node_target(action.target, chamber_nodes)
    if resolved is None:
        # A placeholder target that resolved to no real node — nothing of this
        # role is paired to the chamber.
        node_type = _PLACEHOLDER_NODE_TYPE[action.target]
        return (
            f"No '{node_type}' node is registered for target '{action.target}'. "
            f"Pair a {node_type} node or point the rule at a registered node id."
        )
    return await node_channel_error(resolved, action)


async def node_channel_error(node_id: str, action: RuleAction) -> str | None:
    """Why the action's channel cannot reach node `node_id` (already
    resolved), or None: no channel, a node that never reported its channels,
    or a channel it reported."""
    if not action.channel:
        return None

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT channels FROM hardware_nodes WHERE node_id = ?", (node_id,)
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


async def check_rule(rule: AutomationRule) -> None:
    """Refuse, with 422, a rule that must not be stored.

    Every check an operator's rule has to pass before it is saved belongs
    here: create_validated_rule and update_validated_rule run it for both the
    REST route and the cloud relay. Today that is rule_value_error (an on/off
    value the engine cannot read) and validate_action_channel (a target or
    channel no actuator answers to). HTTPException carries the
    status to both surfaces: FastAPI returns it, and the relay's
    integrations_proxy forwards its status code.
    """
    if error := rule_value_error(rule) or await validate_action_channel(rule.action):
        raise HTTPException(422, error)


def _photoperiods(condition: RuleCondition):
    if condition.type == ConditionType.SCHEDULE and condition.schedule is not None:
        yield condition.schedule.photoperiod
    elif condition.type == ConditionType.COMPOUND and condition.compound is not None:
        for c in condition.compound.conditions:
            yield from _photoperiods(c)


def rule_value_error(rule: AutomationRule) -> str | None:
    """Why the rule's on/off values cannot be stored, or None.

    The models normalise case and spacing but accept any string, because
    stored rules are re-validated on every load. Anything else used to be
    read as "off": a photoperiod "bogus" inverted the light cycle, and a
    native state the engine does not know was published as an OFF while the
    safety ceiling ignored it. A vendor action's state carries no meaning
    (vendor_params do), so it is not checked.
    """
    if not rule.action.vendor_slug and rule.action.state not in ACTION_STATES:
        return (f"Action state must be one of {', '.join(ACTION_STATES)}, "
                f"got {rule.action.state!r}")
    for photoperiod in _photoperiods(rule.condition):
        if photoperiod is not None and photoperiod not in PHOTOPERIOD_VALUES:
            return (f"Schedule photoperiod must be one of {', '.join(PHOTOPERIOD_VALUES)}, "
                    f"got {photoperiod!r}")
    return None


async def create_validated_rule(rule: AutomationRule) -> int:
    """Store an operator's new rule after check_rule; returns its id."""
    await check_rule(rule)
    return await create_rule(rule)


async def update_validated_rule(rule_id: int, rule: AutomationRule) -> bool:
    """Replace rule `rule_id` after check_rule; False when there is no such rule."""
    await check_rule(rule)
    return await update_rule(rule_id, rule)


async def create_rule(rule: AutomationRule) -> int:
    """Insert a rule as given, unchecked (operator input goes through
    create_validated_rule)."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO automation_rules (name, description, enabled, priority, rule_data) VALUES (?, ?, ?, ?, ?)",
            (rule.name, rule.description, int(rule.enabled), rule.priority, serialize_rule_data(rule)),
        )
        new_id = cursor.lastrowid
        await db.commit()
    _rules_changed()
    return new_id


async def update_rule(rule_id: int, rule: AutomationRule) -> bool:
    """Replace a rule as given, unchecked (operator input goes through
    update_validated_rule). False when there is no such rule."""
    async with get_db() as db:
        result = await db.execute(
            "UPDATE automation_rules SET name=?, description=?, enabled=?, priority=?, "
            "rule_data=?, updated_at=unixepoch('now') WHERE id=?",
            (rule.name, rule.description, int(rule.enabled), rule.priority,
             serialize_rule_data(rule), rule_id),
        )
        found = result.rowcount > 0
        await db.commit()
    _rules_changed()
    return found


async def delete_rule(rule_id: int) -> bool:
    async with get_db() as db:
        result = await db.execute("DELETE FROM automation_rules WHERE id = ?", (rule_id,))
        found = result.rowcount > 0
        await db.commit()
    _rules_changed()
    return found


async def toggle_rule(rule_id: int) -> bool | None:
    """Flip the `enabled` flag. Returns the new value, or None if not found.

    One statement reads and writes the flag: as a SELECT then an UPDATE, two
    toggles that overlapped (a double click, two tabs) both read the same
    value and both wrote its opposite, so two toggles made one flip."""
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE automation_rules SET enabled = CASE WHEN enabled THEN 0 ELSE 1 END, "
            "updated_at = unixepoch('now') WHERE id = ? RETURNING enabled",
            (rule_id,),
        )
        rows = await cursor.fetchall()
        await db.commit()
    if not rows:
        return None
    _rules_changed()
    return bool(rows[0]["enabled"])


# Most firings GET /api/automation/firings returns in one response. SQLite reads
# a negative LIMIT as "no limit", so an unclamped limit=-1 returned the table.
FIRINGS_LIMIT_MAX = 1000


async def list_firings(limit: int = 50, rule_id: int | None = None) -> list[dict]:
    """The newest firings, newest first, optionally only rule `rule_id`'s.
    `limit` is clamped to 1..FIRINGS_LIMIT_MAX."""
    query = "SELECT * FROM automation_firings"
    params: list = []
    if rule_id is not None:
        query += " WHERE rule_id = ?"
        params.append(rule_id)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(max(1, min(limit, FIRINGS_LIMIT_MAX)))

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]


async def firing_stats(days: float = 7) -> dict:
    """Firings per rule over the last `days` days (by the Pi's clock), with
    each rule's newest firing of all time — counted over the whole table, so
    a busy week is not cut to the newest page of GET /firings (which left
    the counts low and a rule whose last firing fell off the page "never"
    fired).

    {"since": the window's start, "fires": N, "failed": N, "rules": [{"rule_id",
    "fires", "failed", "last_fired"}, ...]}: the totals count every firing in
    the window, a safety cutoff's (logged with no rule id) included; "rules"
    has an entry for each rule id that has ever fired.
    """
    since = time.time() - max(0.0, days) * 86400
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT rule_id, "
            "COALESCE(SUM(timestamp >= ?), 0) AS fires, "
            "COALESCE(SUM(timestamp >= ? AND status = 'failed'), 0) AS failed, "
            "MAX(timestamp) AS last_fired "
            "FROM automation_firings GROUP BY rule_id",
            (since, since),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
    return {
        "since": since,
        "fires": sum(r["fires"] for r in rows),
        "failed": sum(r["failed"] for r in rows),
        "rules": [r for r in rows if r["rule_id"] is not None],
    }
