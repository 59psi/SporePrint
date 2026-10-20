import time

from fastapi import APIRouter, HTTPException, Query

from . import service
from .models import AutomationRule, OverrideRequest
from .engine import (
    set_override, get_overrides, clear_override as clear_override_engine, note_actuator_off,
    note_actuator_on, add_held_by,
)
from .smart_plugs import get_all_plugs, paired_plug, register_plug, send_plug_command

router = APIRouter()


# ─── Rules CRUD ─────────────────────────────────────────────────

@router.get("/rules")
async def list_rules():
    """Every rule, each with `held_by`: the holds keeping the engine off its
    actuator, under any name it resolves the rule's target to."""
    return await add_held_by(await service.list_rules_with_created_at())


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: int):
    rule = await service.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    return rule


@router.post("/rules")
async def create_rule(rule: AutomationRule):
    rule.id = await service.create_validated_rule(rule)  # 422 when refused
    return rule.model_dump()


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, rule: AutomationRule):
    if not await service.update_validated_rule(rule_id, rule):  # 422 when refused
        raise HTTPException(404, "Rule not found")
    rule.id = rule_id
    return rule.model_dump()


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    if not await service.delete_rule(rule_id):
        raise HTTPException(404, "Rule not found")
    return {"status": "deleted"}


@router.patch("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int):
    enabled = await service.toggle_rule(rule_id)
    if enabled is None:
        raise HTTPException(404, "Rule not found")
    return {"id": rule_id, "enabled": enabled}


# ─── Overrides ──────────────────────────────────────────────────

@router.get("/overrides")
async def list_overrides():
    return [o.model_dump() for o in await get_overrides()]


@router.post("/overrides")
async def create_override(body: OverrideRequest):
    # The stored hold, its expiry stamped on the Pi's clock when the body
    # gives a duration_sec.
    override = body.to_override()
    await set_override(override)
    return override.model_dump()


@router.delete("/overrides/{target}")
async def clear_override_route(target: str, channel: str | None = None):
    await clear_override_engine(target, channel)
    return {"status": "cleared"}


# ─── Firing History ─────────────────────────────────────────────

@router.get("/firings")
async def list_firings(limit: int = 50, rule_id: int | None = None):
    return await service.list_firings(limit, rule_id)


@router.get("/firings/stats")
async def firing_stats(days: float = Query(7, gt=0, le=365)):
    """Firings per rule over the last `days` days and each rule's newest firing."""
    return await service.firing_stats(days)


# ─── Smart Plugs ────────────────────────────────────────────────

@router.get("/plugs")
async def list_plugs():
    return await get_all_plugs()


@router.post("/plugs")
async def add_plug(data: dict):
    try:
        await register_plug(
            plug_id=data["plug_id"],
            name=data["name"],
            plug_type=data.get("plug_type", "shelly"),
            mqtt_topic_prefix=data["mqtt_topic_prefix"],
            device_role=data.get("device_role"),
        )
    except ValueError as e:  # a plug type / prefix no command could reach
        raise HTTPException(422, str(e))
    return {"status": "registered"}


@router.post("/plugs/{plug_id}/command")
async def command_plug(plug_id: str, data: dict):
    state = data.get("state", "off")
    # Nothing switched in either failure, so neither reports success: an
    # unknown / unpaired plug is the caller's problem (409), a broker that is
    # down or refused the publish is ours (503).
    if await paired_plug(plug_id) is None:
        raise HTTPException(409, f"Plug '{plug_id}' is not paired")
    sent_at = time.time()
    published = await send_plug_command(plug_id, state)
    if not published:
        raise HTTPException(
            503, f"Command to plug '{plug_id}' not published — MQTT broker unavailable",
        )
    # Exactly what the plug is sent (send_plug_command only changes case), so a
    # state the plug won't read as OFF never clears a ceiling.
    if str(state).lower() == "off":
        # A manual OFF ends whatever automation ON a safety ceiling was timing;
        # without this the next automation ON keeps the stale deadline.
        await note_actuator_off(plug_id, None, sent_at=sent_at)
    else:
        # A manual ON (or anything but a plain OFF): a rule cutoff must
        # re-send its OFF rather than skip it as a redundant repeat.
        await note_actuator_on(plug_id, None)
    return {"status": "sent", "plug_id": plug_id, "state": state}
