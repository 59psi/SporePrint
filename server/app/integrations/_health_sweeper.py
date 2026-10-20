"""v4.1.5 — vendor-integration health sweeper + state-snapshot pusher.

The cloud's push-rules engine and escalation engine learned to recognise
``vendor_offline`` / ``vendor_health_degraded`` / ``vendor_state_change``
events in v4.1.5; this module is the producer side.

Two responsibilities:

1. **Health transitions.** Periodically poll every registered driver's
   ``health()``. When the state transitions to ``error`` or ``degraded``,
   emit ``vendor_health_degraded`` via ``cloud.service.forward_event``,
   with the driver's error as ``reason``. When a failing driver is back
   to ``ok`` — for several sweeps in a row, so a flaky device is one
   incident, not a page a minute — or is disabled, emit
   ``vendor_health_degraded`` with ``resolved=True``. The cloud relay
   forwards both to the user's push rules + escalation chain. A driver
   going between ``disabled`` and ``ok`` (boot, enable, disable) had no
   incident and sends nothing.

2. **State snapshot.** On startup and after every config save, push the
   full ``/api/integrations`` listing up to the cloud as an
   ``integrations_state`` event. The cloud relay's handler populates the
   integrations-proxy cache so ``/devices/fleet`` can show per-chamber
   driver counts without round-tripping back to the Pi.

Cloud-offline behaviour: ``forward_event`` does NOT queue (it drops
events while the socket is down and returns False). So the sweeper only
records a transition as seen once it was delivered — an undelivered
transition is re-attempted on every sweep until the cloud is back — and
the connector re-pushes the state snapshot on every (re)connect.
"""

from __future__ import annotations

import asyncio
import logging

from . import _registry
from ._base import IntegrationHealth


logger = logging.getLogger(__name__)


_SWEEP_INTERVAL_SECONDS = 60.0
# A failing driver counts as recovered only once this many sweeps in a row
# read "ok": a device that fails every other poll stays one open incident
# instead of a "degraded" page and a resolve every couple of minutes.
_RECOVERED_AFTER_SWEEPS = 3
# The states that open an incident in the cloud.
_INCIDENT_STATES = ("error", "degraded")
# Last-known state per driver, keyed by slug: the state the cloud was last
# told about. Transitions out of ``ok`` become events; recoveries clear them.
_last_state: dict[str, str] = {}
# Sweeps in a row a failing driver has read "ok" (see _RECOVERED_AFTER_SWEEPS).
_ok_streak: dict[str, int] = {}


async def push_state_snapshot() -> None:
    """Send the current driver list to the cloud relay so the fleet
    cache stays warm. Called on startup and after every config save.
    """
    from ..cloud.service import forward_event
    try:
        drivers = await _registry.list_integrations()
    except Exception:
        logger.exception("integrations health: snapshot fetch failed")
        return
    try:
        await forward_event("integrations_state", {"drivers": drivers})
    except Exception:
        # Cloud connector may be disabled — that's fine for free-tier
        # Pis. Don't spam the log.
        logger.debug("integrations health: snapshot forward skipped")


async def _emit_transition(
    slug: str, old_state: str, new_state: str, health: IntegrationHealth,
) -> bool:
    """Emit the event for a transition, if it needs one.

    Returns True when the transition is fully handled (delivered, or no
    event needed) and False when an event could not be delivered — the
    caller then keeps the old state so the next sweep retries.
    """
    from ..cloud.service import forward_event
    # Only an incident that was opened is resolved: a driver going from
    # "disabled" to "ok" (every boot, every enable) never had one, and
    # resolving it anyway paged an "integration degraded" for it. Disabling
    # a failing driver ends its incident too — otherwise the cloud
    # escalation stays open forever.
    # confirm=True: delivered means acknowledged by the relay, so an event
    # sent into a connection that died without closing is retried too.
    if old_state in _INCIDENT_STATES and new_state in ("ok", "disabled"):
        # Cleared — resolve any pending escalation in the cloud.
        return bool(await forward_event(
            "vendor_health_degraded",
            {
                "vendor": slug,
                "previous_state": old_state,
                "resolved": True,
            },
            confirm=True,
        ))
    if new_state in _INCIDENT_STATES and old_state != new_state:
        return bool(await forward_event(
            "vendor_health_degraded",
            {
                "vendor": slug,
                "state": new_state,
                # What the push says the driver reports.
                "reason": health.last_error or new_state,
                "resolved": False,
            },
            confirm=True,
        ))
    return True


async def _sweep_once() -> None:
    """One pass over every registered driver. Diff against the last
    snapshot in ``_last_state`` and emit events for transitions only.
    """
    drivers = _registry.registered_drivers()
    for slug, driver in drivers.items():
        try:
            health = await driver.health()
        except Exception:
            logger.exception("integrations health: %s.health() raised", slug)
            continue
        new_state = health.state or "disabled"
        old_state = _last_state.get(slug)
        # Skip the first observation per slug — we have no prior state
        # to diff against, so any real transition will fire on the
        # second sweep.
        if old_state is None:
            _last_state[slug] = new_state
            continue
        if new_state == "ok" and old_state in _INCIDENT_STATES:
            # A recovery has to hold for _RECOVERED_AFTER_SWEEPS sweeps
            # before it resolves the incident; a failure in between keeps
            # the same incident open (no second page).
            _ok_streak[slug] = _ok_streak.get(slug, 0) + 1
            if _ok_streak[slug] < _RECOVERED_AFTER_SWEEPS:
                continue
        else:
            _ok_streak.pop(slug, None)
        if new_state != old_state:
            if await _emit_transition(slug, old_state, new_state, health):
                _last_state[slug] = new_state
                _ok_streak.pop(slug, None)
            else:
                logger.debug(
                    "integrations health: %s %s→%s not delivered (cloud "
                    "offline) — will retry", slug, old_state, new_state,
                )


async def run_health_sweeper() -> None:
    """Long-running task. Cancellation-safe; one tick per
    ``_SWEEP_INTERVAL_SECONDS`` of vendor health diff'ing.
    """
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("integrations health: sweep crashed")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
