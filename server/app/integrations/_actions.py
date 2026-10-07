"""Unified vendor-action dispatcher (v4.1.2 write paths).

Each vendor driver advertises its writable actions through the
``VENDOR_ACTIONS`` map below. The cloud-web mirror calls
``POST /api/integrations/{slug}/actions/{action}`` with a JSON body;
this module looks up the driver, validates that the action exists,
and forwards the body to the matching driver method.

This is intentionally not part of the per-driver routers — keeping the
write surface in one place lets the cloud-side RPC proxy add a single
``vendor_action`` handler instead of N per-vendor handlers.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, get_type_hints

from fastapi import APIRouter, HTTPException
from pydantic import TypeAdapter, ValidationError

from . import _registry


logger = logging.getLogger(__name__)


# slug → {action_name: driver-method-name}. Each driver's method is
# called with kwargs from the request body. Only methods listed here
# are reachable through this dispatcher.
VENDOR_ACTIONS: dict[str, dict[str, str]] = {
    "fluence": {"set_dim": "set_dim"},
    "fohse": {"set_dim": "set_dim"},
    "bios": {"set_dim": "set_dim"},
    "trane": {"set_setpoint": "set_setpoint"},
    "agrowtek": {"set_output": "set_output"},
    "quest": {"set_setpoint": "set_setpoint"},
    "anden": {"set_setpoint": "set_setpoint"},
    "wemo": {"set_power": "set_power"},
    "kasa": {"set_power": "set_power", "set_dim": "set_dim"},
    "tapo": {"set_power": "set_power", "set_dim": "set_dim"},
}


# Lax pydantic bool: true/false, on/off, yes/no, 1/0 (int or string) map to a
# real bool; anything else is a ValidationError. Drivers do `1 if on else 0`,
# so without this a JSON string like "false"/"off"/"0" is truthy and turns a
# heater/humidifier plug ON.
_BOOL = TypeAdapter(bool)


def _coerce_bool_kwargs(method: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Coerce every kwarg whose (resolved) annotation is ``bool``.

    Driver modules use ``from __future__ import annotations``, so the
    signature holds the string ``"bool"`` — resolve hints first.
    """
    try:
        hints = get_type_hints(method)
    except Exception:  # noqa: BLE001 — unresolvable hints: leave values as-is
        return kwargs
    out = dict(kwargs)
    for name, value in kwargs.items():
        if hints.get(name) is bool:
            try:
                out[name] = _BOOL.validate_python(value)
            except ValidationError:
                raise HTTPException(
                    400, f"{name} must be a boolean (true/false), got {value!r}"
                ) from None
    return out


async def dispatch(slug: str, action: str, payload: dict[str, Any]) -> Any:
    actions = VENDOR_ACTIONS.get(slug)
    if actions is None:
        raise HTTPException(404, f"vendor {slug!r} has no writable actions")
    method_name = actions.get(action)
    if method_name is None:
        raise HTTPException(
            404, f"vendor {slug!r} does not support action {action!r}"
        )
    driver = _registry.registered_drivers().get(slug)
    if driver is None:
        raise HTTPException(503, f"vendor driver {slug!r} not registered")
    method = getattr(driver, method_name, None)
    if method is None or not inspect.iscoroutinefunction(method):
        raise HTTPException(
            500, f"vendor {slug!r}.{method_name!r} is not implemented"
        )

    # Filter payload to keyword args the method accepts so a stray
    # extra field doesn't blow up the dispatch.
    sig = inspect.signature(method)
    kwargs = {k: v for k, v in (payload or {}).items() if k in sig.parameters}
    kwargs = _coerce_bool_kwargs(method, kwargs)
    try:
        return await method(**kwargs)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001 — bubble vendor errors as 502
        logger.exception("vendor %s.%s dispatch failed", slug, action)
        raise HTTPException(502, f"vendor call failed: {exc}")


router = APIRouter()


@router.post("/{slug}/actions/{action}")
async def post_vendor_action(slug: str, action: str, payload: dict[str, Any]):
    return await dispatch(slug, action, payload)


@router.get("/{slug}/actions")
async def list_vendor_actions(slug: str):
    """List the writable actions a vendor exposes — for the cloud-web
    UI to render the right control buttons per driver.
    """
    actions = VENDOR_ACTIONS.get(slug)
    if actions is None:
        return {"slug": slug, "actions": []}
    return {"slug": slug, "actions": sorted(actions.keys())}
