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
              | "enable" | "disable",
    "slug": "grafana",                  # for everything except "list"
    "payload": { ... }                  # for "put_config" only
  }

Response (Pi → cloud):
  {
    "id": "<cmd_id>",
    "success": true|false,
    "body": <result>,                   # action-specific shape
    "error": "<message>"                # only when success=false
  }
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from ..integrations import _registry
from ..integrations import _actions as _vendor_actions


logger = logging.getLogger(__name__)


_VALID_ACTIONS = {
    "list", "get_config", "put_config", "test", "enable", "disable",
    "vendor_action",
}


async def _dispatch(action: str, slug: str | None, payload: dict[str, Any] | None) -> Any:
    if action == "list":
        return await _registry.list_integrations()
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
