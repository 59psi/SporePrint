"""The integrations scaffolding: registry, settings store and routes.

* A slug registers once; a second driver under it is refused.
* Secret fields are encrypted at rest and come back out of every response
  only as a fingerprint keyed by this Pi's integration key, never any of
  their characters.
* PUT validates (400 with the validator's message, never echoing the
  config), persists, then starts or stops the driver; an omitted field or
  flag keeps what is stored, and a failed save puts the driver back.
* The listing shows each driver's live health; a Test persists its result.
* Boot starts every enabled driver, skips the disabled ones and survives one
  that fails; shutdown stops every driver even when one fails to stop.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from app.integrations import (
    DriverConfigError,
    IntegrationDriver,
    IntegrationHealth,
    register,
    router,
)
from app.config import settings
from app.db import get_db
from app.integrations import _registry, _settings_store as store
from app.integrations._keystore import reset_fernet_cache
from tests._pi_c1_integrations import fresh_keystore_fixture  # noqa: F401 — the fresh_keystore fixture


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fresh_registry():
    """Clear the module-level registry between tests so each test starts clean."""
    saved = dict(_registry._drivers)
    _registry._drivers.clear()
    yield
    _registry._drivers.clear()
    _registry._drivers.update(saved)


# ── Dummy driver ──────────────────────────────────────────────────────


class DummyConfig(BaseModel):
    base_url: str = "http://localhost"
    api_key: str = ""
    poll_seconds: int = 60

    @field_validator("base_url")
    @classmethod
    def _needs_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


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
        self.health_result = IntegrationHealth(state="ok")
        self.fail_configure: str | None = None

    async def configure(self, config: BaseModel) -> None:
        if self.fail_configure:
            raise DriverConfigError(self.fail_configure)
        assert isinstance(config, DummyConfig)
        self.configure_calls.append(config)

    @property
    def config(self) -> DummyConfig | None:
        return self.configure_calls[-1] if self.configure_calls else None

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def test_connection(self) -> IntegrationHealth:
        return self.test_result

    async def health(self) -> IntegrationHealth:
        return self.health_result


# ── Registration ──────────────────────────────────────────────────────


def test_a_slug_registers_once(fresh_registry):
    driver = DummyDriver()
    register(driver)
    assert _registry.registered_drivers() == {"dummy": driver}
    # A second driver under the same slug must not silently shadow it.
    with pytest.raises(RuntimeError, match="already registered"):
        register(DummyDriver())
    assert _registry.registered_drivers()["dummy"] is driver


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
async def test_redact_for_response_returns_a_fingerprint_preview(fresh_keystore):
    redacted = store.redact_for_response(
        {"api_key": "abcdefghij", "base_url": "http://x"},
        secret_fields={"api_key"},
    )
    preview = redacted["api_key"]
    # A stable fingerprint keyed by this Pi's integration key: the operator
    # can tell whether the key changed, but none of its characters show
    # (the preview used to be the last four).
    assert re.fullmatch(r"••••[0-9a-f]{6}", preview)
    assert "ghij" not in preview
    assert store.redact_for_response({"api_key": "abcdefghij"}, {"api_key"})["api_key"] == preview
    assert store.secret_preview("abcdefghiJ") != preview
    assert redacted["base_url"] == "http://x"


@pytest.mark.asyncio
async def test_redact_never_returns_a_short_secret(fresh_keystore):
    redacted = store.redact_for_response(
        {"api_key": "ab"},
        secret_fields={"api_key"},
    )
    # A secret of four characters or fewer used to come back whole.
    assert redacted["api_key"] != "••••ab" and "ab" not in redacted["api_key"][4:]


@pytest.mark.asyncio
async def test_preview_depends_on_the_pis_key(tmp_path, monkeypatch):
    previews = []
    for name in ("key-a", "key-b"):
        monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / name))
        reset_fernet_cache()
        previews.append(store.secret_preview("1234"))
    reset_fernet_cache()
    # Without the Pi's key a preview cannot be checked against a guess.
    assert previews[0] != previews[1]


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


def test_get_config_and_the_listing_return_only_a_fingerprint_of_a_secret(driver_and_client):
    _, client = driver_and_client
    client.put(
        "/api/integrations/dummy/config",
        json={"enabled": True, "config": {"base_url": "http://10.0.0.5",
                                          "api_key": "topsecret-1234"}},
    )
    preview = store.secret_preview("topsecret-1234")
    assert "1234" not in preview
    body = client.get("/api/integrations/dummy/config").json()
    assert body["config"]["api_key"] == preview
    # Schema is included for the UI to render the form.
    assert "properties" in body["schema"]
    [listed] = client.get("/api/integrations").json()
    assert listed["config"] == {"base_url": "http://10.0.0.5", "api_key": preview,
                                "poll_seconds": 60}


def test_put_config_custom_validator_error_is_a_400_with_its_message(driver_and_client):
    # A field_validator's ValueError rides in the error's ctx, which the JSON
    # response could not serialize: every such rejection was a 500.
    _, client = driver_and_client
    resp = client.put(
        "/api/integrations/dummy/config",
        json={"enabled": False, "config": {"base_url": "10.0.0.40", "api_key": "s3cret"}},
    )
    assert resp.status_code == 400, resp.text
    assert "base_url must start with http://" in resp.text
    assert "s3cret" not in resp.text, "the rejected config is not echoed back"


@pytest.mark.parametrize("raw,started", [("false", False), ("off", False), ("true", True), (1, True)])
def test_put_config_reads_enabled_as_a_lax_bool(driver_and_client, raw, started):
    # bool("false") is True: the string used to enable and start the driver.
    driver, client = driver_and_client
    resp = client.put("/api/integrations/dummy/config",
                      json={"enabled": raw, "config": {"base_url": "http://x"}})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is started
    assert driver.start_calls == int(started)


def test_put_config_rejects_an_unreadable_enabled_flag(driver_and_client):
    driver, client = driver_and_client
    resp = client.put("/api/integrations/dummy/config",
                      json={"enabled": "sometimes", "config": {"base_url": "http://x"}})
    assert resp.status_code == 400
    assert driver.start_calls == 0 and driver.configure_calls == []


def test_put_config_rejects_a_secret_that_cannot_be_stored(driver_and_client):
    # JSON can carry an unpaired surrogate; it cannot be encrypted for
    # storage, so the save used to fail only after the driver had already
    # been configured with it.
    driver, client = driver_and_client
    resp = client.put(
        "/api/integrations/dummy/config",
        content='{"enabled": true, "config": {"base_url": "http://x", "api_key": "k\\ud800"}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "api_key must be plain text" in resp.text
    assert driver.configure_calls == [] and driver.start_calls == 0
    assert client.get("/api/integrations/dummy/config").json()["config"] == {}


def test_put_config_without_config_keeps_the_stored_config(driver_and_client):
    # A body with no `config` used to reset every non-secret field to its
    # default (base_url, devices, mappings) while keeping the secrets.
    driver, client = driver_and_client
    client.put("/api/integrations/dummy/config", json={
        "enabled": False,
        "config": {"base_url": "http://10.0.0.5", "api_key": "k-1", "poll_seconds": 120}})
    resp = client.put("/api/integrations/dummy/config", json={"enabled": True})
    assert resp.status_code == 200
    body = client.get("/api/integrations/dummy/config").json()
    assert body["enabled"] is True
    assert body["config"]["base_url"] == "http://10.0.0.5"
    assert body["config"]["poll_seconds"] == 120
    assert body["config"]["api_key"] == store.secret_preview("k-1")


def test_put_config_without_enabled_keeps_the_stored_flag(driver_and_client):
    driver, client = driver_and_client
    client.put("/api/integrations/dummy/config",
               json={"enabled": True, "config": {"base_url": "http://x"}})
    resp = client.put("/api/integrations/dummy/config", json={"config": {"base_url": "http://y"}})
    assert resp.json()["enabled"] is True
    assert driver.stop_calls == 0


async def test_put_config_puts_the_driver_back_when_the_save_fails(
    fresh_registry, fresh_keystore, monkeypatch,
):
    driver = DummyDriver()
    register(driver)
    await _registry.put_config("dummy", {"enabled": False, "config": {"base_url": "http://old"}})

    async def _disk_full(*args, **kwargs):
        raise RuntimeError("database or disk is full")

    monkeypatch.setattr(store, "save", _disk_full)
    with pytest.raises(RuntimeError):
        await _registry.put_config("dummy", {"enabled": False, "config": {"base_url": "http://new"}})
    # The driver must not keep running settings that were never saved (a
    # restart would silently revert them).
    assert driver.config.base_url == "http://old"


def test_listing_shows_the_drivers_live_health(driver_and_client):
    # The listing used to show only the last Test's result: a driver whose
    # polls started failing after a good Test still read "ok".
    driver, client = driver_and_client
    client.put("/api/integrations/dummy/config",
               json={"enabled": True, "config": {"base_url": "http://x"}})
    assert client.post("/api/integrations/dummy/test").json()["state"] == "ok"
    driver.health_result = IntegrationHealth(state="error", last_error="connect timeout")
    health = client.get("/api/integrations").json()[0]["health"]
    assert (health["state"], health["last_error"]) == ("error", "connect timeout")
    assert health["last_checked_at"] is not None, "still the time of the last Test"

    client.post("/api/integrations/dummy/disable")
    driver.health_result = IntegrationHealth(state="disabled")
    assert client.get("/api/integrations").json()[0]["health"]["state"] == "disabled"


def test_listing_flags_an_enabled_driver_that_is_not_running(driver_and_client):
    driver, client = driver_and_client
    client.put("/api/integrations/dummy/config",
               json={"enabled": True, "config": {"base_url": "http://x"}})
    driver.health_result = IntegrationHealth(state="disabled")  # it failed to start
    health = client.get("/api/integrations").json()[0]["health"]
    assert health["state"] == "error"
    assert "not running" in health["last_error"]


async def test_test_connection_persists_health(fresh_registry, fresh_keystore):
    driver = DummyDriver()
    register(driver)
    await _registry.put_config("dummy", {"enabled": False, "config": {"api_key": "x"}})
    driver.test_result = IntegrationHealth(state="degraded", last_error="slow")
    assert (await _registry.test_connection("dummy")).state == "degraded"
    stored = await store.load("dummy", secret_fields={"api_key"})
    assert (stored.last_health_state, stored.last_error) == ("degraded", "slow")
    assert stored.last_health_at is not None


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


class _OffDriver(DummyDriver):
    name = "dummy_off"


class BoomConfig(BaseModel):
    pass


class BoomDriver(IntegrationDriver):
    """Fails to configure at boot and to stop at shutdown."""

    name = "boom"
    tier_required = "free"
    config_schema = BoomConfig
    secret_fields: set[str] = set()

    async def configure(self, config):
        raise RuntimeError("boom on configure")

    async def start(self):
        pass

    async def stop(self):
        raise RuntimeError("boom on stop")

    async def test_connection(self):
        return IntegrationHealth(state="error")

    async def health(self):
        return IntegrationHealth(state="error")


async def test_boot_starts_each_enabled_driver_and_survives_one_that_fails(
    fresh_registry, fresh_keystore,
):
    boom, enabled, disabled = BoomDriver(), DummyDriver(), _OffDriver()
    for driver in (boom, enabled, disabled):
        register(driver)
    await store.save("boom", True, {}, secret_fields=set())
    await store.save("dummy", True, {"base_url": "http://10.0.0.5", "api_key": "x"},
                     secret_fields={"api_key"})
    await store.save("dummy_off", False, {"api_key": "x"}, secret_fields={"api_key"})

    await _registry.start_enabled_drivers()  # must not raise

    assert enabled.start_calls == 1
    assert [c.base_url for c in enabled.configure_calls] == ["http://10.0.0.5"]
    assert disabled.start_calls == 0 and disabled.configure_calls == []


async def test_shutdown_stops_every_driver_even_when_one_fails_to_stop(fresh_registry):
    boom, driver = BoomDriver(), DummyDriver()
    register(boom)
    register(driver)
    await _registry.stop_all_drivers()  # must not raise
    assert driver.stop_calls == 1
