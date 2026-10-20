"""Pulse Grow integration — cloud-API and LAN poller (free).

Pulse Grow's environmental sensors (Pulse One / Pulse Pro / Pulse Zero)
are WiFi devices paired to the operator's Pulse account at
``app.pulsegrow.com``. Two transports:

- **cloud** — the Pi authenticates against ``api.pulsegrow.com`` with the
  operator's own account (credentials encrypted at rest on the Pi via the
  integrations Fernet key), polls each device's recent-data endpoint and
  stores the readings in telemetry history;
- **local** — UDP discovery plus per-device HTTP on the LAN.

Both run free on the Pi: it has no paygate, and neither touches the
SporePrint cloud.
"""

from .driver import PulseDriver
from .router import router

driver = PulseDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["PulseDriver", "driver", "router"]
