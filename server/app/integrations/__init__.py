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

__all__ = [
    "DriverConfigError",
    "IntegrationDriver",
    "IntegrationHealth",
    "IntegrationState",
    "register",
    "registered_drivers",
    "router",
]
