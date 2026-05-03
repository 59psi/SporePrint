"""v4.1.5 — vendor-integration health sweeper + state-snapshot pusher.

The cloud's push-rules engine and escalation engine learned to recognise
``vendor_offline`` / ``vendor_health_degraded`` / ``vendor_state_change``
events in v4.1.5; this module is the producer side.

Two responsibilities:

1. **Health transitions.** Periodically poll every registered driver's
   ``health()``. When the state transitions to ``error`` or ``degraded``,
   emit ``vendor_health_degraded`` via ``cloud.service.forward_event``.
   When the state transitions back to ``ok``, emit
   ``vendor_health_degraded`` with ``resolved=True``. The cloud relay
   forwards both to the user's push rules + escalation chain.

2. **State snapshot.** On startup and after every config save, push the
   full ``/api/integrations`` listing up to the cloud as an
   ``integrations_state`` event. The cloud relay's handler populates the
   integrations-proxy cache so ``/devices/fleet`` can show per-chamber
   driver counts without round-tripping back to the Pi.

Both flows degrade gracefully when the cloud connector is offline —
events queue inside ``cloud.service.forward_event`` and drain on
reconnect (same as telemetry).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import _registry


logger = logging.getLogger(__name__)


_SWEEP_INTERVAL_SECONDS = 60.0
# Last-known state per driver, keyed by slug. Transitions out of ``ok``
# become events; transitions back into ``ok`` clear them.
_last_state: dict[str, str] = {}


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


async def _emit_transition(slug: str, old_state: str, new_state: str) -> None:
    from ..cloud.service import forward_event
    if new_state == "ok" and old_state != "ok":
        # Cleared — resolve any pending escalation in the cloud.
        await forward_event(
            "vendor_health_degraded",
            {
                "vendor": slug,
                "previous_state": old_state,
                "resolved": True,
            },
        )
        return
    if new_state in ("error", "degraded") and old_state != new_state:
        await forward_event(
            "vendor_health_degraded",
            {
                "vendor": slug,
                "state": new_state,
                "resolved": False,
            },
        )


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
        if new_state != old_state:
            await _emit_transition(slug, old_state, new_state)
            _last_state[slug] = new_state


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
