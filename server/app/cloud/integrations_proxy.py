"""Pi-side handler for cloud-originated integration requests.

The cloud relay sends `integrations_request` events to bridge cloud-web
operators to their Pi's `/api/integrations/*` surface. This module
dispatches each request to the local registry functions and emits
`integrations_response` with the result.

Wire `attach(sio_client)` into `service.py`'s connect handler so the
events are registered on the cloud connector socket.

Frame shape
-----------
Request (cloud → Pi):
  {
    "id": "<cmd_id>",                   # cloud-supplied; echoed back
    "action": "list" | "get_config" | "put_config" | "test"
              | "enable" | "disable" | "vendor_action"
              | "automation_list" | "automation_create"
              | "automation_update" | "automation_delete"
              | "chamber_automation_coverage" | "planner_propose",
    "slug": "grafana",                  # integrations actions only
    "payload": { ... }                  # action-specific
  }

Response (Pi → cloud):
  {
    "id": "<cmd_id>",
    "success": true|false,
    "body": <result>,                   # action-specific shape
    "error": "<message>"                # only when success=false
  }

v4.1.5 — the same `integrations_request` channel now also carries
automation-rule CRUD so the cloud-web operator can edit Pi-side rules
without a brand-new RPC. The dispatch table below routes
`automation_*` actions into the Pi's automation service helpers.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from ..config import settings
from ..db import get_db
from ..integrations import _registry
from ..integrations import _actions as _vendor_actions
from . import service as _cloud_service
from .signing import verify_frame


logger = logging.getLogger(__name__)


# Replay-cache namespace. Integration request ids share the command channel's
# FIFO + SQLite replay table, but are prefixed so an integrations id can never
# collide with (and falsely "replay") a command id, or vice versa.
_REPLAY_NAMESPACE = "integrations:"

# Downgrade latch. Once this Pi has verified ONE signed integrations_request,
# the cloud it is paired with provably signs this channel, so an unsigned
# frame from then on can only be a stripped/injected frame and is rejected.
# Until then unsigned frames stay accepted (backward compatibility with a
# cloud that has never signed the channel). Persisted in `user_settings` so a
# Pi restart does not reopen the window.
_SIGNED_LATCH_KEY = "cloud_integrations_signed_seen"


def _require_signed_setting() -> bool:
    """Operator opt-in to reject every unsigned integrations_request, even
    before the latch engages. Reads `settings.cloud_require_signed_integrations`
    when the config field exists; defaults to False (today's behaviour)."""
    return bool(getattr(settings, "cloud_require_signed_integrations", False))


async def _signed_frames_seen() -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT value FROM user_settings WHERE key = ?", (_SIGNED_LATCH_KEY,)
        )
        row = await cursor.fetchone()
    return bool(row) and row["value"] == "1"


async def _mark_signed_frames_seen() -> None:
    async with get_db() as db:
        await db.execute(
            """INSERT INTO user_settings (key, value) VALUES (?, '1')
               ON CONFLICT(key) DO UPDATE SET value='1', updated_at=unixepoch('now')""",
            (_SIGNED_LATCH_KEY,),
        )
        await db.commit()


async def reset_signing_latch() -> None:
    """Forget the downgrade latch — called when the Pi is (re)paired, since
    the new pairing may be a different cloud whose signing is not yet known."""
    async with get_db() as db:
        await db.execute("DELETE FROM user_settings WHERE key = ?", (_SIGNED_LATCH_KEY,))
        await db.commit()


async def _reject(sio_client, cmd_id: str, status: int, error: str) -> None:
    await sio_client.emit(
        "integrations_response",
        {"id": cmd_id, "success": False, "status": status, "error": error},
    )


async def _check_signed_frame(sio_client, cmd_id: str, data: dict[str, Any]) -> bool:
    """Verify a frame that carries a `signature`, then replay-dedup its id.

    Returns True when the frame may be dispatched; otherwise the rejection
    has already been emitted.
    """
    # A signature we cannot check fails closed — never "skip verification".
    ok, reason = verify_frame(settings.cloud_token, data)
    if not ok:
        logger.warning(
            "integrations_request signature check failed (id=%s): %s", cmd_id, reason,
        )
        await _reject(sio_client, cmd_id, 401, f"signature check failed: {reason}")
        return False

    if not isinstance(cmd_id, str):
        await _reject(sio_client, cmd_id, 400, "invalid request id")
        return False

    replay_key = f"{_REPLAY_NAMESPACE}{cmd_id}"
    already_seen = False
    async with _cloud_service._replay_lock:
        seen = _cloud_service._seen_command_ids
        if replay_key in seen:
            already_seen = True
        else:
            seen[replay_key] = None
            while len(seen) > _cloud_service._COMMAND_ID_CACHE_CAP:
                seen.popitem(last=False)
    if already_seen:
        logger.warning("integrations_request replay rejected (id=%s)", cmd_id)
        await _reject(sio_client, cmd_id, 409, "Replayed request id")
        return False
    try:
        await _cloud_service._persist_replay_id(replay_key)
    except Exception as e:  # noqa: BLE001 — in-memory cache still dedups
        logger.warning("integrations_request replay persist failed: %s", e)

    try:
        if not await _signed_frames_seen():
            await _mark_signed_frames_seen()
            logger.info(
                "Cloud signs integrations_request frames — unsigned frames "
                "are rejected from now on"
            )
    except Exception as e:  # noqa: BLE001 — latch is defence in depth
        logger.warning("integrations_request signing latch persist failed: %s", e)
    return True


_VALID_ACTIONS = {
    "list", "get_config", "put_config", "test", "enable", "disable",
    "vendor_action",
    # v4.1.5 — automation rule CRUD via the same proxy channel.
    "automation_list",
    "automation_create",
    "automation_update",
    "automation_delete",
    # v5.0.0 — pre-grow answers the cloud-web wizard/planner ask of the paired
    # Pi (chamber-scoped, not integration-vendor-scoped, so no slug).
    "chamber_automation_coverage",
    "planner_propose",
}


async def _dispatch_automation(
    action: str, payload: dict[str, Any] | None
) -> Any:
    """v4.1.5 automation rule dispatch — calls the Pi's automation
    service layer directly so the cloud-web caller gets the same shape
    as the Pi's own ``/api/automation/rules`` surface.

    Frames:
      - automation_list    → returns list[dict]
      - automation_create  → payload = {rule: AutomationRule dict}
                            returns the persisted rule (with id)
      - automation_update  → payload = {rule_id: int, rule: dict}
                            returns 404 string when missing
      - automation_delete  → payload = {rule_id: int}
    """
    from ..automation import service as automation_service
    from ..automation.models import AutomationRule
    from ..automation.service import normalize_rule_id

    if action == "automation_list":
        return await automation_service.list_rules_with_created_at()

    payload = payload or {}

    if action == "automation_create":
        raw = payload.get("rule")
        if not isinstance(raw, dict):
            raise ValueError("automation_create requires payload.rule")
        rule = AutomationRule(**raw)
        new_id = await automation_service.create_rule(rule)
        rule.id = new_id
        return rule.model_dump()

    if action == "automation_update":
        rule_id = normalize_rule_id(payload.get("rule_id"))
        raw = payload.get("rule")
        if rule_id is None:
            raise ValueError("automation_update requires payload.rule_id")
        if not isinstance(raw, dict):
            raise ValueError("automation_update requires payload.rule")
        rule = AutomationRule(**raw)
        ok = await automation_service.update_rule(rule_id, rule)
        if not ok:
            raise HTTPException(404, "Rule not found")
        rule.id = rule_id
        return rule.model_dump()

    if action == "automation_delete":
        rule_id = normalize_rule_id(payload.get("rule_id"))
        if rule_id is None:
            raise ValueError("automation_delete requires payload.rule_id")
        ok = await automation_service.delete_rule(rule_id)
        if not ok:
            raise HTTPException(404, "Rule not found")
        return {"status": "deleted", "id": rule_id}

    raise ValueError(f"unknown automation action {action!r}")


async def _dispatch_pregrow(action: str, payload: dict[str, Any] | None) -> Any:
    """v5.0.0 pre-grow dispatch — answers the cloud-web wizard/planner ask
    with the same shape the Pi's own REST routes return, so a cloud operator
    gets the real per-Pi verdict instead of a cloud stub.

    Frames:
      - chamber_automation_coverage → payload = {chamber_id, species}
                                    returns {"phases": [...]}  (chamber_id is
                                    the cloud device id and isn't needed for the
                                    computation — coverage reads the live
                                    hardware registries, not a local chamber)
      - planner_propose            → payload = {species, start}  (start=YYYY-MM-DD)
                                    returns the ProposedCycle dict, JSON-safe
    """
    payload = payload or {}

    if action == "chamber_automation_coverage":
        from ..species.service import get_profile
        from ..automation.coverage import compute_coverage

        species = payload.get("species")
        if not isinstance(species, str) or not species:
            raise ValueError("chamber_automation_coverage requires payload.species")
        profile = await get_profile(species)
        if profile is None:
            raise HTTPException(404, f"Unknown species profile '{species}'")
        return {"phases": await compute_coverage(profile)}

    if action == "planner_propose":
        from datetime import date

        from ..planner.service import propose_cycle_for_species

        species = payload.get("species")
        start_raw = payload.get("start")
        if not isinstance(species, str) or not species:
            raise ValueError("planner_propose requires payload.species")
        if not isinstance(start_raw, str) or not start_raw:
            raise ValueError("planner_propose requires payload.start")
        try:
            start = date.fromisoformat(start_raw)
        except ValueError:
            raise ValueError(
                f"planner_propose start must be YYYY-MM-DD, got {start_raw!r}"
            )
        cycle = await propose_cycle_for_species(species, start)
        if cycle is None:
            raise HTTPException(404, f"Unknown species profile '{species}'")
        return cycle.model_dump(mode="json")

    raise ValueError(f"unknown pre-grow action {action!r}")


async def _dispatch(action: str, slug: str | None, payload: dict[str, Any] | None) -> Any:
    if action == "list":
        return await _registry.list_integrations()
    if action.startswith("automation_"):
        return await _dispatch_automation(action, payload)
    if action in ("chamber_automation_coverage", "planner_propose"):
        return await _dispatch_pregrow(action, payload)
    if slug is None:
        raise ValueError("slug is required for this action")
    if action == "get_config":
        return await _registry.get_config(slug)
    if action == "put_config":
        return await _registry.put_config(slug, payload or {})
    if action == "test":
        result = await _registry.test_connection(slug)
        # IntegrationHealth is a dataclass — serialise for the wire.
        return {
            "state": result.state,
            "last_error": result.last_error,
            "details": result.details,
        }
    if action == "enable":
        return await _registry.enable(slug)
    if action == "disable":
        return await _registry.disable(slug)
    if action == "vendor_action":
        # Frame: { action: "vendor_action", slug, payload: {action, ...} }
        # The inner action name comes from `payload.action`; everything
        # else in `payload` is forwarded as kwargs.
        inner = (payload or {}).get("action")
        if not isinstance(inner, str):
            raise ValueError("vendor_action requires payload.action")
        rest = {k: v for k, v in (payload or {}).items() if k != "action"}
        return await _vendor_actions.dispatch(slug, inner, rest)
    raise ValueError(f"unknown action {action!r}")


async def handle_request(sio_client, data: dict[str, Any]) -> None:
    """Top-level handler — call from `@_sio.on('integrations_request')`."""
    cmd_id = data.get("id") if isinstance(data, dict) else None
    if not cmd_id:
        logger.warning("integrations_request missing id; dropping")
        return

    # v4.1.4 — verify the HMAC signature on signed frames (and, since the
    # audit fix, replay-dedup their id). Unsigned frames are still accepted
    # for a cloud that has never signed this channel, but NOT once a signed
    # frame has been seen (downgrade latch) or when the operator opted into
    # strict mode — see _SIGNED_LATCH_KEY.
    if "signature" in data:
        if not await _check_signed_frame(sio_client, cmd_id, data):
            return
    elif _require_signed_setting() or await _signed_frames_seen():
        logger.warning(
            "integrations_request rejected: unsigned frame (id=%s) but this Pi "
            "requires signed integrations frames", cmd_id,
        )
        await _reject(
            sio_client, cmd_id, 401,
            "unsigned integrations_request rejected — this Pi requires signed frames",
        )
        return

    action = data.get("action")
    if action not in _VALID_ACTIONS:
        await sio_client.emit("integrations_response", {
            "id": cmd_id,
            "success": False,
            "error": f"unknown action {action!r}",
        })
        return

    slug = data.get("slug")
    payload = data.get("payload")

    try:
        body = await _dispatch(action, slug, payload)
    except HTTPException as exc:
        # Preserve the registry's existing 4xx contract (e.g. 404 unknown
        # slug, 400 bad config) so the cloud caller can map it to HTTP.
        await sio_client.emit("integrations_response", {
            "id": cmd_id,
            "success": False,
            "status": exc.status_code,
            "error": exc.detail
            if isinstance(exc.detail, str)
            else str(exc.detail),
        })
        return
    except ValueError as exc:
        await sio_client.emit("integrations_response", {
            "id": cmd_id,
            "success": False,
            "status": 400,
            "error": str(exc),
        })
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("integrations_request dispatch crashed")
        await sio_client.emit("integrations_response", {
            "id": cmd_id,
            "success": False,
            "status": 500,
            "error": f"unexpected error: {exc}",
        })
        return

    await sio_client.emit("integrations_response", {
        "id": cmd_id,
        "success": True,
        "body": body,
    })


def attach(sio_client) -> None:
    """Register the `integrations_request` handler on the connector
    socket. Called from `cloud/service.py` after the socket is created.
    """

    @sio_client.on("integrations_request")
    async def _on(data):
        await handle_request(sio_client, data)
