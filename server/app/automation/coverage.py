"""Hardware-capability verdict for a chamber + species.

Answers a single question the UI could not previously ask honestly: *given the
hardware actually paired to this chamber, can the seeded automation for species
X run in every grow phase — and where it can't, does a fallback cover it?*

Every input already exists; this module only assembles them:

- the species profile's `phases` (species.service.get_profile),
- the enabled automation rules the engine will evaluate, filtered by the SAME
  `applies_to_phases` / `applies_to_species` predicates the engine uses,
- the chamber's node and plug resolution (`resolve_node_target()`,
  `smart_plugs.chamber_plug()`) and `validate_action_channel()` to decide,
  per rule action, whether the named actuator is really there,
- `requires_absent_target` to surface the capability-aware fallbacks
  (vent-with-fans for a missing dehumidifier, mist-pump for a missing
  humidifier) as the `fallback` on the requirement they stand in for.

No hardware state is invented — an actuator is "available" only when the paired
smart-plug row or node channel says so.
"""

import json

from ..db import get_db
from ..hardware.service import get_node
from ..integrations import _registry, _settings_store
from .models import AutomationRule
from .service import (
    resolve_node_target,
    rule_applies_to_species,
    valid_rules,
    validate_action_channel,
)
from .smart_plugs import chamber_plug, is_plug_target

# The channels each node personality exposes (firmware sp_core/personality.h),
# for a node that has not reported its channel names in a health doc yet.
_PERSONALITY_CHANNELS = {
    "relay": frozenset({"fae", "exhaust", "circulation", "aux"}),
    "lighting": frozenset({"white", "blue", "red", "far_red"}),
}

# Ids listed in any chamber's node_ids.
_CHAMBER_LISTED_SQL = (
    "SELECT 1 FROM chambers c, "
    "json_each(CASE WHEN json_valid(c.node_ids) THEN c.node_ids ELSE '[]' END) j "
    "WHERE j.value = ? LIMIT 1"
)


async def _load_enabled_rules() -> list[AutomationRule]:
    """The exact rule set the engine evaluates: enabled, priority-ordered.

    Mirrors engine.load_rules' query + deserialization so the coverage verdict
    reflects what will actually run — including any rules the user has added or
    disabled — not a static snapshot of the seed templates.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, enabled, priority, rule_data "
            "FROM automation_rules WHERE enabled = 1 ORDER BY priority DESC"
        )
        rows = await cursor.fetchall()
    return valid_rules(rows)


def _rule_applies(rule: AutomationRule, species_id: str, phase: str) -> bool:
    """Same phase/species gate the engine applies (evaluate_rules)."""
    if rule.applies_to_phases and phase not in rule.applies_to_phases:
        return False
    return rule_applies_to_species(rule.applies_to_species, species_id)


def _actuator_label(action) -> str:
    """Concise identifier for the actuator a rule action drives."""
    return f"{action.target}/{action.channel}" if action.channel else action.target


async def _vendor_present(slug: str) -> bool:
    """A vendor action's device is reachable when its driver is registered and
    its integration is enabled (it reached a get_node() lookup on its
    vendor:* key and always read unavailable)."""
    driver = _registry.registered_drivers().get(slug)
    if driver is None:
        return False
    stored = await _settings_store.load(slug, driver.secret_fields)
    return bool(stored and stored.enabled)


async def _listed_in_a_chamber(node_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(_CHAMBER_LISTED_SQL, (node_id,))
        return await cursor.fetchone() is not None


def _node_channels(node: dict) -> frozenset[str]:
    """The channels a node answers to: those its health doc reported, else
    its personality's."""
    try:
        reported = json.loads(node["channels"]) if node.get("channels") else None
    except (TypeError, ValueError):
        reported = None
    if isinstance(reported, list):
        return frozenset(reported)
    return _PERSONALITY_CHANNELS.get(node.get("node_type") or "", frozenset())


async def _actuator_present(action, chamber_nodes: list[str] | None = None) -> bool:
    """Is the actuator this action drives actually paired to the Pi right now?

    Resolved the way the engine resolves it when it drives the chamber
    (``chamber_nodes``: the chamber's node ids), so another chamber's relay,
    light or plug never makes this chamber read as covered:

    - vendor action: its driver is registered and its integration enabled;
    - smart plug (plug-*, by id or role): the plug a rule for this chamber
      reaches (smart_plugs.chamber_plug);
    - node target, with or without a channel: the resolved node (a placeholder
      → the chamber's node of its role, or one in no chamber) is registered,
      is this chamber's or in no chamber, and — for a channel — answers to it
      itself (the channels it reported, else its personality's). Any node on
      the Pi reporting the channel used to be enough.
    """
    if action.vendor_slug:
        return await _vendor_present(action.vendor_slug)
    if await validate_action_channel(action, chamber_nodes):
        # Either a live node rejected this channel, or the placeholder target
        # resolves to no node of its role — both mean the actuator isn't there.
        return False
    resolved = await resolve_node_target(action.target, chamber_nodes)
    if resolved is None:
        return False
    if resolved == action.target and await is_plug_target(resolved):
        return await chamber_plug(resolved, chamber_nodes) is not None
    node = await get_node(resolved)
    if node is None:
        return False
    if chamber_nodes and resolved not in chamber_nodes and await _listed_in_a_chamber(resolved):
        return False  # another chamber's node
    return not action.channel or action.channel in _node_channels(node)


async def _resolve_fallback(target: str, fallbacks: list[AutomationRule],
                            chamber_nodes: list[str] | None = None) -> str | None:
    """Name the actuator that stands in for an absent `target`, if any.

    A fallback rule declares `requires_absent_target=<target>` and fires only
    while that target is missing (engine: evaluate_rules). It genuinely covers
    the gap only if ITS OWN actuator is present, so we check that before
    claiming the requirement degrades gracefully rather than simply fails.
    """
    for rule in fallbacks:
        if (rule.requires_absent_target == target
                and await _actuator_present(rule.action, chamber_nodes)):
            return _actuator_label(rule.action)
    return None


async def compute_coverage(profile, chamber_nodes: list[str] | None = None) -> list[dict]:
    """Per-phase hardware-capability verdict for `profile` (a SpeciesProfile).

    ``chamber_nodes`` (the chamber's node ids) scopes placeholder resolution to
    that chamber, the way the engine resolves it when it drives the chamber.

    Returns the `phases` list of the GET /api/chambers/{id}/automation-coverage
    contract: one entry per grow phase, each with a deduped list of the
    actuator requirements the applicable rules impose, and for each requirement:

    - ``available``  — the named target/channel is paired and reachable;
    - ``fallback``   — when NOT available, the substitute actuator that covers
      it (a real, present fallback), else ``null``.
    """
    # Reference-only profiles (chaga on a living birch, an endophyte in LC) have
    # no chamber setpoints to drive — the engine skips them, and so do we.
    if not getattr(profile, "chamber_cultivable", True):
        return []

    rules = await _load_enabled_rules()
    phases_out: list[dict] = []

    for phase in profile.phases:  # GrowPhase keys, in profile-definition order
        phase_val = phase.value
        applicable = [r for r in rules if _rule_applies(r, profile.id, phase_val)]
        # A fallback rule (requires_absent_target set) is not an independent
        # requirement — it's the stand-in for the target it names. Build the
        # requirement list from primary rules; use fallbacks only to fill
        # `fallback` on the requirement they cover.
        primary = [r for r in applicable if not r.requires_absent_target]
        fallbacks = [r for r in applicable if r.requires_absent_target]

        requirements: list[dict] = []
        seen: set[tuple[str, str | None]] = set()
        for rule in primary:
            key = (rule.action.target, rule.action.channel)
            if key in seen:
                continue
            seen.add(key)
            available = await _actuator_present(rule.action, chamber_nodes)
            fallback = None if available else await _resolve_fallback(
                rule.action.target, fallbacks, chamber_nodes
            )
            requirements.append({
                "target": rule.action.target,
                "channel": rule.action.channel,
                "available": available,
                "fallback": fallback,
            })

        phases_out.append({"phase": phase_val, "requirements": requirements})

    return phases_out
