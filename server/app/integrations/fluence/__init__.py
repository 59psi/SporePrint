"""Fluence horticultural lighting (vendor cloud, free on the Pi).

Fluence's FluenceID cloud platform exposes per-fixture telemetry over
REST. Operator authenticates with FluenceID credentials, stored on the
Pi (encrypted at rest); the Pi holds the session token in memory.

⚠ Live-device verification needed.
"""

from .driver import FluenceDriver

driver = FluenceDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["FluenceDriver", "driver"]
