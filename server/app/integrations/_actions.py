"""Unified vendor-action dispatcher (v4.1.2 write paths).

Each vendor driver advertises its writable actions through the
``VENDOR_ACTIONS`` map below. The cloud-web mirror calls
``POST /api/integrations/{slug}/actions/{action}`` with a JSON body;
this module looks up the driver, validates that the action exists,
and forwards the body to the matching driver method.

This is intentionally not part of the per-driver routers — keeping the
write surface in one place lets the cloud-side RPC proxy add a single
``vendor_action`` handler instead of N per-vendor handlers.

A write from outside automation (the REST route, the cloud RPC) goes
through ``dispatch_manual``, which tells the vendor-write listeners about
it once it went out; rules and the safety watchdog call ``dispatch``.
"""

from __future__ import annotations

import inspect
import logging
import math
import time
import types
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any, Union, get_args, get_origin, get_type_hints

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

# The actions that switch a device on or off (rather than move a setpoint).
ON_OFF_ACTIONS = frozenset({"set_power", "set_dim", "set_output"})

# How the automation engine's safety ceiling (safety_max_on_seconds) switches a
# vendor device OFF: slug → (OFF action, the param naming the device, OFF
# params). Every vendor above with an on/off action needs a line here, or its
# rules' ceilings are silently not enforced (tests/test_vendor_safety_off.py
# holds the two tables together). Setpoint-only vendors (trane, quest, anden)
# have no OFF.
VENDOR_SAFETY_OFF: dict[str, tuple[str, str, dict]] = {
    "kasa": ("set_power", "ip", {"on": False}),
    "tapo": ("set_power", "ip", {"on": False}),
    "wemo": ("set_power", "ip", {"on": False}),
    "fluence": ("set_dim", "fixture_id", {"percent": 0}),
    "fohse": ("set_dim", "fixture_id", {"percent": 0}),
    "bios": ("set_dim", "fixture_id", {"percent": 0}),
    "agrowtek": ("set_output", "output_id", {"value": False}),
}


# Lax pydantic bool: true/false, on/off, yes/no, 1/0 (int or string) map to a
# real bool; anything else is a ValidationError. Drivers do `1 if on else 0`,
# so without this a JSON string like "false"/"off"/"0" is truthy and turns a
# heater/humidifier plug ON. The one copy: the automation engine reads a
# vendor rule's on/off with it (so its safety ceiling agrees with the device)
# and the cloud command handler a remote pause flag.
LAX_BOOL = TypeAdapter(bool)

# How a value for a parameter of each annotation is described in a 400.
_PARSED_KINDS: dict[type, str] = {
    bool: "a boolean (true/false)",
    int: "an integer",
    float: "a number",
}


def _parsed_hint(hint: Any) -> bool:
    """A bool / int / float annotation, or a union of those (None allowed)."""
    if hint in _PARSED_KINDS:
        return True
    if get_origin(hint) in (Union, types.UnionType):
        args = get_args(hint)
        return any(a in _PARSED_KINDS for a in args) and all(
            a in _PARSED_KINDS or a is type(None) for a in args
        )
    return False


@lru_cache(maxsize=None)
def _adapter(hint: Any) -> TypeAdapter:
    return LAX_BOOL if hint is bool else TypeAdapter(hint)


def _coerce_kwargs(method: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Parse every bool / number kwarg into the type its annotation names.

    JSON callers (the integrations panel's text fields, a rule's
    vendor_params) send "false", "50" or "0"; a driver doing
    ``1 if on else 0`` or ``0 <= percent <= 100`` needs the real value.
    Pydantic's lax mode does the parse, a union in its declared order:
    Agrowtek's ``value: float | bool`` reads "false"/"off" as False and
    "0"/"50" as numbers. A value the parameter cannot take is a 400.

    Driver modules use ``from __future__ import annotations``, so the
    signature holds strings like ``"bool"`` — resolve hints first.
    """
    try:
        hints = get_type_hints(method)
    except Exception:  # noqa: BLE001 — unresolvable hints: leave values as-is
        return kwargs
    out = dict(kwargs)
    for name, value in kwargs.items():
        hint = hints.get(name)
        if hint is None or not _parsed_hint(hint):
            continue
        try:
            parsed = _adapter(hint).validate_python(value)
            # "nan" / "inf" parse as floats, but no device takes one (nor
            # does strict JSON).
            valid = not (isinstance(parsed, float) and not math.isfinite(parsed))
        except ValidationError:
            valid = False
        if not valid:
            kinds = [_PARSED_KINDS[a] for a in (get_args(hint) or (hint,)) if a in _PARSED_KINDS]
            raise HTTPException(
                400, f"{name} must be {' or '.join(kinds)}, got {value!r}"
            )
        out[name] = parsed
    return out


def _resolve(
    slug: str, action: str, payload: dict[str, Any] | None,
) -> tuple[Callable[..., Awaitable[Any]], dict[str, Any]]:
    """The driver method an action calls, and the kwargs it gets: the payload
    keys the method takes (a stray extra field is ignored), bools and numbers
    parsed. A missing required parameter or an unparseable value is a 400 —
    a caller error, not a vendor failure."""
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

    sig = inspect.signature(method)
    kwargs = {k: v for k, v in (payload or {}).items() if k in sig.parameters}
    try:
        sig.bind(**kwargs)
    except TypeError as exc:
        raise HTTPException(400, f"{slug}.{action}: {exc}") from None
    return method, _coerce_kwargs(method, kwargs)


def action_params(slug: str, action: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """The kwargs ``dispatch(slug, action, payload)`` calls the driver with,
    so a reader (the automation engine's safety ceiling) interprets a payload
    exactly as the device will. Raises the HTTPException dispatch would."""
    return _resolve(slug, action, payload)[1]


def vendor_params_on(slug: str | None, vendor_action: str | None, params: dict) -> bool | None:
    """What a vendor write does to its device: True switches it on, False
    switches it off, None is neither (a setpoint change).

    The params are read exactly as the dispatcher hands them to the driver
    (action_params): set_power's ``on`` is a lax bool ("false"/"off"/"0"
    switch the device OFF), and a set_dim percent or a set_output value sent
    as a string ("true", "0", "50") is parsed the same way — read raw, a
    string ON armed no ceiling. A value the device would not accept, or whose
    meaning is unclear, is None — neither arms a ceiling nor clears one.
    """
    if not slug or vendor_action not in ON_OFF_ACTIONS:
        return None
    try:
        parsed = action_params(slug, vendor_action, params)
    except HTTPException:
        return None
    value = parsed.get({"set_power": "on", "set_dim": "percent"}.get(vendor_action, "value"))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return None


def vendor_device_key(slug: str, params: dict) -> str | None:
    """The key a vendor device is tracked by: ``vendor:<slug>:<device-id>``.

    Keyed on the DEVICE rather than a rule's free-form override target, so
    two rules driving two Kasa plugs under one ``vendor:kasa`` target each
    keep their own safety ceiling, and the OFF can be rebuilt from the key
    alone after a reboot. None when the vendor has no OFF or the device id
    is missing.
    """
    spec = VENDOR_SAFETY_OFF.get(slug)
    if spec is None:
        return None
    device = params.get(spec[1])
    if device is None or device == "":
        return None
    return f"vendor:{slug}:{device}"


def vendor_safety_off(slug: str, on_params: dict) -> tuple[str, dict] | None:
    """(action, params) that switch the vendor device `on_params` names OFF
    (VENDOR_SAFETY_OFF), or None: a vendor with no OFF, or no device id. The
    automation engine's safety ceiling and session-end safing send it."""
    spec = VENDOR_SAFETY_OFF.get(slug)
    if spec is None:
        return None
    off_action, id_param, off_params = spec
    device = on_params.get(id_param)
    if device is None or device == "":
        return None
    params = {id_param: device, **off_params}
    if slug == "agrowtek":
        # Mirror the ON value's type, read as the dispatcher reads it: an
        # output driven with true/false ("true", "on", …) is switched off with
        # false, one driven with a number ("50", 0.5, …) or an unknown value
        # with 0.
        try:
            on_value = action_params(slug, off_action, on_params).get("value")
        except HTTPException:
            on_value = on_params.get("value")
        if not isinstance(on_value, bool):
            params["value"] = 0
    return off_action, params


async def dispatch(slug: str, action: str, payload: dict[str, Any]) -> Any:
    method, kwargs = _resolve(slug, action, payload)
    try:
        return await method(**kwargs)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001 — bubble vendor errors as 502
        logger.exception("vendor %s.%s dispatch failed", slug, action)
        raise HTTPException(502, f"vendor call failed: {exc}")


# Awaited as listener(slug, action, params, sent_at=...) after a write from
# outside automation reached the device; `params` are the kwargs the driver
# got. The automation engine registers one that clears the safety ceiling
# timing a device a manual OFF switched off — the engine imports this
# module, so this module cannot import it.
VendorWriteListener = Callable[..., Awaitable[None]]
_write_listeners: list[VendorWriteListener] = []


def add_vendor_write_listener(listener: VendorWriteListener) -> None:
    """Register `listener` for manual vendor writes (idempotent)."""
    if listener not in _write_listeners:
        _write_listeners.append(listener)


async def dispatch_manual(slug: str, action: str, payload: dict[str, Any]) -> Any:
    """dispatch() for a write from outside automation: the REST route and the
    cloud ``vendor_action`` RPC.

    Once the write went out, every vendor-write listener hears about it,
    with ``sent_at`` taken before the write. Rules and the safety watchdog
    call dispatch() itself: they keep their own books, and a rule firing
    holds the actuator lock a listener takes.
    """
    params = action_params(slug, action, payload)
    sent_at = time.time()
    result = await dispatch(slug, action, payload)
    for listener in list(_write_listeners):
        try:
            await listener(slug, action, params, sent_at=sent_at)
        except Exception as exc:  # noqa: BLE001 — the write went out; never fail it
            logger.warning(
                "vendor-write listener failed for %s.%s: %s", slug, action, exc
            )
    return result


router = APIRouter()


@router.post("/{slug}/actions/{action}")
async def post_vendor_action(slug: str, action: str, payload: dict[str, Any]):
    return await dispatch_manual(slug, action, payload)


@router.get("/{slug}/actions")
async def list_vendor_actions(slug: str):
    """List the writable actions a vendor exposes — for the cloud-web
    UI to render the right control buttons per driver.
    """
    actions = VENDOR_ACTIONS.get(slug)
    if actions is None:
        return {"slug": slug, "actions": []}
    return {"slug": slug, "actions": sorted(actions.keys())}
