"""Anden dehumidifier integration (free, LAN HTTP).

Anden's networked grow-room dehumidifiers expose LAN status reads.
Free-tier — pure LAN.

⚠ Live-device verification needed.
"""

from .driver import AndenDriver

driver = AndenDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["AndenDriver", "driver"]
