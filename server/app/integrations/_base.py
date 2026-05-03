"""Driver-side base classes + types for v4.1 third-party integrations.

Every vendor driver subclasses `IntegrationDriver` and is registered with
the `_registry` module. The registry handles persistence, encryption, and
HTTP routing uniformly — drivers only implement `configure / start / stop /
test_connection / health`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel


IntegrationState = Literal["ok", "degraded", "disabled", "error"]
IntegrationTier = Literal["free", "premium"]


class DriverConfigError(ValueError):
    """Raised by `configure()` when supplied config is invalid.

    The registry surfaces the message back through the HTTP layer as a 400.
    """


@dataclass
class IntegrationHealth:
    """Snapshot of a driver's last self-check.

    Persisted to `integration_settings.last_health_*` and surfaced to the
    settings UI via `GET /api/integrations`. `details` is free-form per
    driver — keep it short and human-readable; the UI shows it under the
    status pill.
    """

    state: IntegrationState
    last_error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class IntegrationDriver(ABC):
    """Abstract base for a vendor driver.

    Lifecycle:
      1. `configure(config)` is called every time settings are written. The
         driver validates and stores the config in memory, but does not yet
         start any I/O. May raise `DriverConfigError`.
      2. `start()` is called once on lifespan startup if the driver is
         enabled, and again whenever the user toggles enabled→true. Drivers
         may launch asyncio tasks here.
      3. `stop()` is called on lifespan shutdown and on enabled→false. Must
         be idempotent — `_registry` may call it more than once.
      4. `test_connection()` runs a single one-shot fetch without affecting
         persistent state. Used by the "Test" button in the settings UI.
      5. `health()` returns the last-known health snapshot. May refresh on
         a configurable cadence inside the driver, but does not block the
         HTTP request.

    Concrete drivers declare:

      class GrafanaDriver(IntegrationDriver):
          name: ClassVar[str] = "grafana"
          tier_required: ClassVar[IntegrationTier] = "free"
          config_schema: ClassVar[type[BaseModel]] = GrafanaConfig
          secret_fields: ClassVar[set[str]] = set()

    `secret_fields` names the keys in the config that need encryption at
    rest. The registry encrypts each one with the integrations Fernet key
    before persisting and decrypts before passing to `configure()`.
    """

    # Slug used as the primary key in `integration_settings.slug` and as
    # the URL segment under `/api/integrations/{slug}`.
    name: ClassVar[str]

    # `free` for LAN-only integrations (Grafana exporter, Aranet poll); set
    # to `premium` when the driver requires our cloud (cloud-API tokens we
    # hold, relay roundtrips, etc.) per feedback_tier_model.
    tier_required: ClassVar[IntegrationTier]

    # Pydantic model the registry uses to validate incoming config. Drivers
    # receive an instance of this type in `configure()`.
    config_schema: ClassVar[type[BaseModel]]

    # Subset of `config_schema` field names whose values are secrets. The
    # registry encrypts these per-field at rest and never logs them.
    secret_fields: ClassVar[set[str]] = set()

    @abstractmethod
    async def configure(self, config: BaseModel) -> None:
        """Validate and stage configuration. Do not start I/O here."""

    @abstractmethod
    async def start(self) -> None:
        """Begin any long-running tasks. Idempotent."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop long-running tasks. Idempotent — may be called from a
        partially-started state."""

    @abstractmethod
    async def test_connection(self) -> IntegrationHealth:
        """One-shot reachability test. Does not mutate persistent state."""

    @abstractmethod
    async def health(self) -> IntegrationHealth:
        """Return last-known health without blocking on I/O."""
