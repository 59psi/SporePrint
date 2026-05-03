"""Belkin Wemo integration (free, LAN UPnP/SOAP).

Wemo plugs and switches expose a UPnP/SOAP control surface on port
49153 over the operator's LAN. Supports on/off control plus per-second
power monitoring on the Wemo Insight. Belkin sunset their cloud in
late 2024; local UPnP remains the supported control path on existing
devices.

⚠ Live-device verification needed for Insight power-monitoring
parsing — the SOAP envelope shape is documented but firmware
revisions vary.
"""

from .driver import WemoDriver

driver = WemoDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["WemoDriver", "driver"]
