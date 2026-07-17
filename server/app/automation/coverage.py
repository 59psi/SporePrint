"""Hardware-capability verdict for a chamber + species (V2-1).

Answers a single question the UI could not previously ask honestly: *given the
hardware actually paired to this chamber, can the seeded automation for species
X run in every grow phase — and where it can't, does a fallback cover it?*

Every input already exists; this module only assembles them:

- the species profile's `phases` (species.service.get_profile),
- the enabled automation rules the engine will evaluate, filtered by the SAME
  `applies_to_phases` / `applies_to_species` predicates the engine uses,
- `target_is_present()` + `validate_action_channel()` to decide, per rule
  action, whether the named actuator is really there,
- `requires_absent_target` to surface the capability-aware fallbacks
  (vent-with-fans for a missing dehumidifier, mist-pump for a missing
  humidifier) as the `fallback` on the requirement they stand in for.

No hardware state is invented — an actuator is "available" only when the paired
smart-plug row or node channel says so.
"""

from ..db import get_db
from ..hardware.service import get_node
from .models import AutomationRule
from .service import deserialize_rule_row, validate_action_channel
from .smart_plugs import target_is_present


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
    return [AutomationRule.model_validate(deserialize_rule_row(row)) for row in rows]


def _rule_applies(rule: AutomationRule, species_id: str, phase: str) -> bool:
    """Same phase/species gate the engine applies (evaluate_rules)."""
    if rule.applies_to_phases and phase not in rule.applies_to_phases:
        return False
    if rule.applies_to_species and species_id not in rule.applies_to_species:
        return False
    return True


def _actuator_label(action) -> str:
    """Concise identifier for the actuator a rule action drives."""
    return f"{action.target}/{action.channel}" if action.channel else action.target


async def _actuator_present(action) -> bool:
    """Is the actuator this action drives actually paired to the Pi right now?

    Three action shapes, three honest checks — all reading the same registries
    `target_is_present` / `validate_action_channel` / `hardware_nodes` do:

    - node channel (target=relay-01, channel=exhaust): the node must not have
      rejected the channel AND some node must expose it;
    - smart plug (target=plug-*, no channel): a `smart_plugs` row by id or role;
    - bare node target (target=light-01, scene-driven, no channel): the node is
      registered. `target_is_present` only answers for plugs and channel names,
      so a scene-only light node is checked against the node registry directly —
      otherwise every chamber with lights would read as "no lighting".
    """
    if await validate_action_channel(action):
        # A live node has enumerated its channels and this one is not among them.
        return False
    if action.channel:
        return await target_is_present(action.channel)
    if action.target.startswith("plug-"):
        return await target_is_present(action.target)
    return await get_node(action.target) is not None


async def _resolve_fallback(target: str, fallbacks: list[AutomationRule]) -> str | None:
    """Name the actuator that stands in for an absent `target`, if any.

    A fallback rule declares `requires_absent_target=<target>` and fires only
    while that target is missing (engine: evaluate_rules). It genuinely covers
    the gap only if ITS OWN actuator is present, so we check that before
    claiming the requirement degrades gracefully rather than simply fails.
    """
    for rule in fallbacks:
        if rule.requires_absent_target == target and await _actuator_present(rule.action):
            return _actuator_label(rule.action)
    return None


async def compute_coverage(profile) -> list[dict]:
    """Per-phase hardware-capability verdict for `profile` (a SpeciesProfile).

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
            available = await _actuator_present(rule.action)
            fallback = None if available else await _resolve_fallback(
                rule.action.target, fallbacks
            )
            requirements.append({
                "target": rule.action.target,
                "channel": rule.action.channel,
                "available": available,
                "fallback": fallback,
            })

        phases_out.append({"phase": phase_val, "requirements": requirements})

    return phases_out
