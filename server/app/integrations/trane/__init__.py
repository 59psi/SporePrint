"""v4.1.1 Trane HVAC integration — Trane Nexia / BAS bridge (premium).

Trane's residential Nexia APIs and commercial BAS APIs are both cloud-
mediated; the operator authenticates with their Trane account and we
hold the access token on the Pi (encrypted at rest). Premium per
``feedback_tier_model``.

⚠ Live-device verification needed: Trane's API revisions vary across
account types (Nexia vs Tracer); the parsing layer is tolerant by
design and the driver records the response shape it sees.
"""

from .driver import TraneDriver

driver = TraneDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["TraneDriver", "driver"]
