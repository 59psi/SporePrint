"""v4.1.1 Agrowtek GCX integration — controller bridge (free, LAN HTTP).

The Agrowtek GCX series (Bluelab parent company) exposes a documented
local REST API on the LAN for sensor reads and setpoint commands. We
poll the read endpoints on a schedule and merge the readings into the
SporePrint telemetry pipeline. Free-tier — pure LAN.

⚠ Live-device verification needed: the GCX firmware revisions vary in
endpoint shapes; the parsing layer is tolerant by design.
"""

from .driver import AgrowtekDriver

driver = AgrowtekDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["AgrowtekDriver", "driver"]
