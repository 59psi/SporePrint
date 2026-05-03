"""Fluence horticultural lighting (cloud, premium).

Fluence's FluenceID cloud platform exposes per-fixture telemetry over
REST. Operator authenticates with FluenceID credentials; we hold the
session token on the Pi (encrypted at rest).

⚠ Live-device verification needed.
"""

from .driver import FluenceDriver

driver = FluenceDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["FluenceDriver", "driver"]
