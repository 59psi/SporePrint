"""v4.1.1 Trane HVAC integration — Trane Nexia / BAS bridge (free).

Trane's residential Nexia APIs and commercial BAS APIs are both cloud-
mediated; the operator authenticates with their Trane account, whose
password stays on the Pi (encrypted at rest), and the Pi holds the access
token in memory. Free like every driver on the Pi.

⚠ Live-device verification needed: Trane's API revisions vary across
account types (Nexia vs Tracer); the parsing layer is tolerant by
design and the driver records the response shape it sees.
"""

from .driver import TraneDriver

driver = TraneDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["TraneDriver", "driver"]
