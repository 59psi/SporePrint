"""Fohse horticultural lighting (cloud, premium).

Fohse's high-end LED fixtures pair via WiFi to the FohseConnect cloud.
Operator authenticates with their account; we poll fixture telemetry
on a schedule.

⚠ Live-device verification needed.
"""

from .driver import FohseDriver

driver = FohseDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["FohseDriver", "driver"]
