"""BIOS Lighting integration (free, LAN HTTP).

BIOS LED fixtures expose a documented LAN REST API for telemetry +
control. Free-tier — pure LAN. Cloud-mediated control from cloud-web
flows through the relay (premium-gated separately by the cloud-web
UI; the driver itself is unaware).

⚠ Live-device verification needed.
"""

from .driver import BiosDriver

driver = BiosDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["BiosDriver", "driver"]
