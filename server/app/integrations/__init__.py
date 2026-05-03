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
from ._actions import VENDOR_ACTIONS, dispatch as dispatch_action
from ._actions import router as actions_router

# Import every shipped vendor sub-package so its driver self-registers.
# Add new vendors here — the registry only sees what's been imported.
from . import grafana  # noqa: F401  — side-effect: registers the driver
from . import aranet   # noqa: F401  — side-effect: registers the driver
from . import pulse    # noqa: F401  — side-effect: registers the driver
# v4.1.1 lighting / HVAC drivers (skeleton — see _http_skeleton.py).
from . import agrowtek  # noqa: F401
from . import trane     # noqa: F401
from . import fluence   # noqa: F401
from . import quest     # noqa: F401
from . import anden     # noqa: F401
from . import fohse     # noqa: F401
from . import bios      # noqa: F401
# v4.1.2 LAN smart-plug drivers.
from . import wemo      # noqa: F401
from . import kasa      # noqa: F401


__all__ = [
    "DriverConfigError",
    "IntegrationDriver",
    "IntegrationHealth",
    "IntegrationState",
    "register",
    "registered_drivers",
    "router",
    "actions_router",
    "dispatch_action",
    "VENDOR_ACTIONS",
]
