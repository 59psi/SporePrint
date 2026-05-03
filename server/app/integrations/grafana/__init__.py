"""v4.1 Grafana integration — Prometheus text-format exposition.

Free-tier driver. The Pi exposes a `/metrics` endpoint that the user's own
Grafana + Prometheus (or Grafana Cloud's hosted Prometheus) scrapes on a
schedule. No data leaves the LAN unless the user themselves configures an
external scraper. Charging for this would be charging for a config flag.

Exposed at `/metrics` — outside the `/api/*` namespace, so the existing
`ApiKeyMiddleware` does not gate it. An optional bearer-token header check
inside the route handler covers Tailscale-to-Grafana-Cloud setups where
the operator wants light authentication on top of LAN scoping.
"""

from .driver import GrafanaDriver
from .router import router

driver = GrafanaDriver()

# Auto-register on import so a fresh process boots with the driver in the
# table even before the operator configures it. Configuration + lifecycle
# happens through the unified /api/integrations/grafana/* surface.
from .. import _registry as _registry_module
_registry_module.register(driver)


__all__ = ["GrafanaDriver", "driver", "router"]
