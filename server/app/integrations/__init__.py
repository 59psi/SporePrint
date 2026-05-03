"""v4.1 third-party integration drivers (Grafana / Aranet / Pulse Grow / …).

Driver authors implement `IntegrationDriver` from `_base` and register the
class with the registry in `_registry`. The registry mounts a single
`/api/integrations/*` router that handles list / configure / test / enable /
disable for every driver uniformly.
"""

from ._base import (
    DriverConfigError,
    IntegrationDriver,
    IntegrationHealth,
    IntegrationState,
)
from ._registry import register, registered_drivers, router

# Import every shipped vendor sub-package so its driver self-registers.
# Add new vendors here — the registry only sees what's been imported.
from . import grafana  # noqa: F401  — side-effect: registers the driver


__all__ = [
    "DriverConfigError",
    "IntegrationDriver",
    "IntegrationHealth",
    "IntegrationState",
    "register",
    "registered_drivers",
    "router",
]
