"""v4.1 Aranet integration — LAN poll of an Aranet PRO base station.

Free-tier driver. The Aranet PRO base station (≈$500) bridges Aranet4 /
Aranet RADIATION / Aranet Soil sensors over proprietary 868/915 MHz radio
to a LAN HTTP server. The Pi polls the PRO's local API on a schedule and
publishes readings into the existing telemetry pipeline so chamber UI,
automation rules, alerts, and the Grafana exporter all work unchanged.

Tier rationale: traffic stays on the LAN — operator's Pi → operator's
PRO base station. No SporePrint cloud roundtrip. Per
``feedback_tier_model``, this is free.

Requires Aranet PRO base-station firmware ≥ 2.0; older firmware was
Aranet-Cloud-only with no local API. The driver surfaces this version
requirement via ``test_connection()`` errors when the PRO returns 404 or
401 on the documented endpoint.
"""

from .driver import AranetDriver
from .router import router

driver = AranetDriver()

from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["AranetDriver", "driver", "router"]
