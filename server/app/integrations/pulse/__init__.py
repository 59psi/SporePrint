"""v4.1 Pulse Grow integration — cloud-API poller (premium-tier).

Pulse Grow's environmental sensors (Pulse One / Pulse Pro / Pulse Zero)
are WiFi-only and pair to the operator's Pulse account at
``app.pulsegrow.com``. v4.1.0 ships the **cloud transport** only — the
Pi authenticates against ``api.pulsegrow.com``, polls each device's
recent-data endpoint, and publishes readings into the existing telemetry
pipeline.

Tier rationale: this transport routes through Pulse's cloud API. We
hold the operator's Pulse credentials on the Pi (encrypted at rest via
the integrations Fernet key) and refresh tokens periodically. That is
*our* infra cost, so per ``feedback_tier_model`` the toggle is gated
premium. The driver itself does not enforce the gate — phase 5's
cloud-web settings UI hides the Pulse toggle from free-tier users
because they can't have paired the Pi anyway.

A separate **local-discovery transport** (UDP scan + per-device HTTP) is
on the v4.1.x roadmap once we can verify Pulse's local-mode endpoint
shape on a paired device. Free-tier when it ships.
"""

from .driver import PulseDriver
from .router import router

driver = PulseDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["PulseDriver", "driver", "router"]
