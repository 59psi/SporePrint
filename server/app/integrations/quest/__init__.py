"""Quest dehumidifier integration (free, LAN HTTP).

Quest's networked dehumidifiers expose a documented LAN HTTP endpoint
for status reads. Free-tier — pure LAN.

⚠ Live-device verification needed.
"""

from .driver import QuestDriver

driver = QuestDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["QuestDriver", "driver"]
