"""Tests for the v4.1 integrations scaffolding.

Covers:
  - Driver registration + duplicate-slug rejection
  - Encrypted at-rest round-trip for secret fields
  - Settings store load/save/health-update
  - Router list / get_config / put_config / test / enable / disable
  - Lifespan boot of enabled drivers
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.integrations import (
    DriverConfigError,
    IntegrationDriver,
    IntegrationHealth,
    register,
    router,
)
from app.integrations import _registry, _settings_store as store
from app.integrations._keystore import reset_fernet_cache


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fresh_registry():
    """Clear the module-level registry between tests so each test starts clean."""
    saved = dict(_registry._drivers)
    _registry._drivers.clear()
    yield
    _registry._drivers.clear()
    _registry._drivers.update(saved)


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    """Point the keystore at a temp path and reset the lru_cache."""
    from app.config import settings
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


# ── Dummy driver ──────────────────────────────────────────────────────


class DummyConfig(BaseModel):
    base_url: str = "http://localhost"
    api_key: str = ""
    poll_seconds: int = 60


class DummyDriver(IntegrationDriver):
    name = "dummy"
    tier_required = "free"
    config_schema = DummyConfig
    secret_fields = {"api_key"}

    def __init__(self) -> None:
        self.configure_calls: list[DummyConfig] = []
        self.start_calls = 0
        self.stop_calls = 0
        self.test_result = IntegrationHealth(state="ok")
        self.fail_configure: str | None = None

    async def configure(self, config: BaseModel) -> None:
        if self.fail_configure:
            raise DriverConfigError(self.fail_configure)
        assert isinstance(config, DummyConfig)
        self.configure_calls.append(config)

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def test_connection(self) -> IntegrationHealth:
        return self.test_result

    async def health(self) -> IntegrationHealth:
        return self.test_result


# ── Registration ──────────────────────────────────────────────────────


def test_register_succeeds_once(fresh_registry):
    driver = DummyDriver()
    register(driver)
    assert "dummy" in _registry.registered_drivers()


def test_register_rejects_duplicate(fresh_registry):
    register(DummyDriver())
    with pytest.raises(RuntimeError, match="already registered"):
        register(DummyDriver())


# ── Encryption round-trip ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_field_round_trips_through_save_and_load(fresh_keystore):
    plain = {"base_url": "http://10.0.0.5", "api_key": "supersecret-key-xyz"}
    await store.save("dummy", True, plain, secret_fields={"api_key"})
    loaded = await store.load("dummy", secret_fields={"api_key"})
    assert loaded is not None
    assert loaded.config["base_url"] == "http://10.0.0.5"
    assert loaded.config["api_key"] == "supersecret-key-xyz"
    assert loaded.enabled is True


@pytest.mark.asyncio
async def test_secret_field_is_encrypted_on_disk(fresh_keystore):
    plain = {"api_key": "supersecret-key-xyz"}
    await store.save("dummy", False, plain, secret_fields={"api_key"})
    from app.db import get_db
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT config FROM integration_settings WHERE slug = 'dummy'"
        )
        row = await cursor.fetchone()
    raw = json.loads(row["config"])
    # On-disk value is the Fernet sentinel, never the plaintext.
    assert raw["api_key"].startswith("fernet:")
    assert "supersecret-key-xyz" not in row["config"]


@pytest.mark.asyncio
async def test_redact_for_response_returns_last4_preview():
    redacted = store.redact_for_response(
        {"api_key": "abcdefghij", "base_url": "http://x"},
        secret_fields={"api_key"},
    )
    assert redacted["api_key"] == "••••ghij"
    assert redacted["base_url"] == "http://x"


@pytest.mark.asyncio
async def test_redact_handles_short_secret():
    redacted = store.redact_for_response(
        {"api_key": "ab"},
        secret_fields={"api_key"},
    )
    assert redacted["api_key"] == "••••ab"


@pytest.mark.asyncio
async def test_health_update_persists(fresh_keystore):
    await store.save("dummy", True, {"api_key": "x"}, secret_fields={"api_key"})
    await store.update_health(
        "dummy", IntegrationHealth(state="error", last_error="timeout")
    )
    loaded = await store.load("dummy", secret_fields={"api_key"})
    assert loaded is not None
    assert loaded.last_health_state == "error"
    assert loaded.last_error == "timeout"
    assert loaded.last_health_at is not None


# ── Router ────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/integrations")
    return app


@pytest.fixture
def driver_and_client(fresh_registry, fresh_keystore):
    driver = DummyDriver()
    register(driver)
    app = _make_app()
    with TestClient(app) as client:
        yield driver, client


def test_list_includes_unconfigured_driver(driver_and_client):
    _, client = driver_and_client
    resp = client.get("/api/integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "dummy"
    assert body[0]["enabled"] is False
    assert body[0]["tier_required"] == "free"


def test_put_config_validates_persists_and_starts(driver_and_client):
    driver, client = driver_and_client
    payload = {
        "enabled": True,
        "config": {"base_url": "http://10.0.0.5", "api_key": "topsecret"},
    }
    resp = client.put("/api/integrations/dummy/config", json=payload)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    assert len(driver.configure_calls) == 1
    assert driver.start_calls == 1
    assert driver.stop_calls == 0


def test_put_config_returns_400_on_invalid_payload(driver_and_client):
    _, client = driver_and_client
    resp = client.put(
        "/api/integrations/dummy/config",
        json={"enabled": True, "config": {"poll_seconds": "not-an-int"}},
    )
    assert resp.status_code == 400


def test_put_config_returns_400_on_driver_config_error(driver_and_client):
    driver, client = driver_and_client
    driver.fail_configure = "base_url unreachable from this Pi"
    resp = client.put(
        "/api/integrations/dummy/config",
        json={"enabled": True, "config": {"base_url": "http://10.0.0.5"}},
    )
    assert resp.status_code == 400
    assert "unreachable" in resp.text


def test_put_config_disables_calls_stop(driver_and_client):
    driver, client = driver_and_client
    client.put(
        "/api/integrations/dummy/config",
        json={"enabled": True, "config": {"base_url": "http://x"}},
    )
    resp = client.put(
        "/api/integrations/dummy/config",
        json={"enabled": False, "config": {"base_url": "http://x"}},
    )
    assert resp.status_code == 200
    assert driver.stop_calls >= 1


def test_get_config_returns_redacted_secret(driver_and_client):
    _, client = driver_and_client
    client.put(
        "/api/integrations/dummy/config",
        json={"enabled": True, "config": {"api_key": "topsecret-1234"}},
    )
    resp = client.get("/api/integrations/dummy/config")
    body = resp.json()
    assert body["config"]["api_key"] == "••••1234"
    # Schema is included for the UI to render the form.
    assert "properties" in body["schema"]


def test_test_connection_persists_health(driver_and_client):
    driver, client = driver_and_client
    client.put(
        "/api/integrations/dummy/config",
        json={"enabled": False, "config": {"api_key": "x"}},
    )
    driver.test_result = IntegrationHealth(state="degraded", last_error="slow")
    resp = client.post("/api/integrations/dummy/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "degraded"


def test_enable_without_prior_config_returns_409(driver_and_client):
    _, client = driver_and_client
    resp = client.post("/api/integrations/dummy/enable")
    assert resp.status_code == 409


def test_unknown_slug_returns_404(driver_and_client):
    _, client = driver_and_client
    assert client.get("/api/integrations/nope/config").status_code == 404
    assert (
        client.put(
            "/api/integrations/nope/config", json={"enabled": False, "config": {}}
        ).status_code
        == 404
    )
    assert client.post("/api/integrations/nope/test").status_code == 404


# ── Lifespan boot ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_enabled_drivers_skips_disabled(fresh_registry, fresh_keystore):
    driver = DummyDriver()
    register(driver)
    await store.save("dummy", False, {"api_key": "x"}, secret_fields={"api_key"})
    await _registry.start_enabled_drivers()
    assert driver.start_calls == 0


@pytest.mark.asyncio
async def test_start_enabled_drivers_starts_enabled(fresh_registry, fresh_keystore):
    driver = DummyDriver()
    register(driver)
    await store.save(
        "dummy", True, {"base_url": "http://10.0.0.5", "api_key": "x"},
        secret_fields={"api_key"},
    )
    await _registry.start_enabled_drivers()
    assert driver.start_calls == 1
    assert len(driver.configure_calls) == 1


@pytest.mark.asyncio
async def test_start_enabled_drivers_isolates_failures(
    fresh_registry, fresh_keystore
):
    """A failing driver must not block the others from starting."""

    class BoomConfig(BaseModel):
        pass

    class BoomDriver(IntegrationDriver):
        name = "boom"
        tier_required = "free"
        config_schema = BoomConfig
        secret_fields: set[str] = set()

        async def configure(self, config):
            raise RuntimeError("boom on configure")

        async def start(self):
            pass

        async def stop(self):
            pass

        async def test_connection(self):
            return IntegrationHealth(state="error")

        async def health(self):
            return IntegrationHealth(state="error")

    boom = BoomDriver()
    healthy = DummyDriver()
    register(boom)
    register(healthy)
    await store.save("boom", True, {}, secret_fields=set())
    await store.save(
        "dummy", True, {"api_key": "x"}, secret_fields={"api_key"}
    )
    # Should not raise — registry catches per-driver failures.
    await _registry.start_enabled_drivers()
    assert healthy.start_calls == 1


@pytest.mark.asyncio
async def test_stop_all_is_idempotent(fresh_registry, fresh_keystore):
    driver = DummyDriver()
    register(driver)
    await _registry.stop_all_drivers()
    await _registry.stop_all_drivers()
    # Stop is called once per stop_all invocation, not gated by start state.
    assert driver.stop_calls == 2
