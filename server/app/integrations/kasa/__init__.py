"""TP-Link Kasa integration (free, LAN encrypted JSON over TCP).

Kasa plugs and switches expose a documented local protocol on TCP/9999:
JSON commands wrapped in a 4-byte length header, payload XOR-encrypted
with a rolling key seeded at 0xAB. We implement the cipher inline so
no new pip dep is required.

Supports on/off + dim (HS220 model) + power monitoring (Insight model).
"""

from .driver import KasaDriver

driver = KasaDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["KasaDriver", "driver"]
