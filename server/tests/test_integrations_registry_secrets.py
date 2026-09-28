"""Registry config/secret lifecycle regressions.

* enable() must apply the STORED config to the driver before starting it —
  after a restart a disabled driver still holds its constructor defaults, so
  starting it bare served Grafana /metrics without its bearer token and left
  pollers running with an empty base_url while health said "ok".
* The redacted secret preview (``••••ABCD``) that GET returns must never be
  written back as the credential when a form PUTs the whole config back.
* A secret that can no longer be decrypted (Fernet key lost/rotated) must not
  500 the whole integrations listing — the operator has to be able to load the
  page to re-enter credentials.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.integrations import _registry, _settings_store as store
from app.integrations._keystore import reset_fernet_cache
from app.integrations.grafana.config import GrafanaConfig
from app.integrations.grafana.router import router as metrics_router


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield tmp_path
    reset_fernet_cache()


@pytest.fixture
def grafana(fresh_keystore):
    drv = _registry.registered_drivers()["grafana"]
    saved = (drv._enabled, drv._cfg)
    drv._enabled = False
    drv._cfg = GrafanaConfig()
    yield drv
    drv._enabled, drv._cfg = saved


# ── #2 enable() applies stored config ────────────────────────────────


async def test_enable_applies_stored_config_after_restart(grafana):
    # Operator configured a bearer token, then disabled the exporter.
    await store.save("grafana", False, {"bearer_token": "s3cret-token"},
                     grafana.secret_fields)
    # Simulated restart: the singleton holds constructor defaults again.
    grafana._cfg = GrafanaConfig()
    assert grafana.config.bearer_token == ""

    await _registry.enable("grafana")

    assert grafana.enabled is True
    assert grafana.config.bearer_token == "s3cret-token", (
        "enable() started the driver without its stored config — /metrics "
        "would be served unauthenticated"
    )


async def test_enable_rejects_stored_config_that_no_longer_validates(grafana):
    await store.save("grafana", False, {"include_actuator_state": "not-a-bool"},
                     grafana.secret_fields)
    with pytest.raises(HTTPException) as exc:
        await _registry.enable("grafana")
    assert exc.value.status_code == 400
    assert grafana.enabled is False


# ── #3 redacted placeholder never replaces the real secret ───────────


async def test_put_back_redacted_placeholder_keeps_real_secret(grafana):
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": "realkey-ABCD"}})
    listed = await _registry.get_config("grafana")
    placeholder = listed["config"]["bearer_token"]
    assert placeholder == "••••ABCD"

    # "Edit one field and save": the form PUTs the whole (redacted) config back.
    await _registry.put_config("grafana", {
        "enabled": False,
        "config": {"bearer_token": placeholder, "include_actuator_state": False},
    })

    row = await store.load("grafana", grafana.secret_fields)
    assert row.config["bearer_token"] == "realkey-ABCD"
    assert row.config["include_actuator_state"] is False
    assert grafana.config.bearer_token == "realkey-ABCD"


async def test_omitted_secret_keeps_stored_value(grafana):
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": "keep-me-1234"}})
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"include_actuator_state": False}})
    row = await store.load("grafana", grafana.secret_fields)
    assert row.config["bearer_token"] == "keep-me-1234"


async def test_explicit_empty_string_clears_secret(grafana):
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": "clear-me-1234"}})
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": ""}})
    row = await store.load("grafana", grafana.secret_fields)
    assert row.config["bearer_token"] == ""


async def test_stale_placeholder_for_a_different_secret_is_rejected(grafana):
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": "realkey-ABCD"}})
    with pytest.raises(HTTPException) as exc:
        await _registry.put_config("grafana", {
            "enabled": False, "config": {"bearer_token": "••••WXYZ"},
        })
    assert exc.value.status_code == 400
    row = await store.load("grafana", grafana.secret_fields)
    assert row.config["bearer_token"] == "realkey-ABCD"


async def test_placeholder_with_no_stored_secret_is_rejected(grafana):
    with pytest.raises(HTTPException) as exc:
        await _registry.put_config("grafana", {
            "enabled": False, "config": {"bearer_token": "••••ABCD"},
        })
    assert exc.value.status_code == 400


def test_metrics_bearer_compare_tolerates_non_ascii(grafana):
    """A non-ASCII token must yield 401, never a 500 from compare_digest."""
    grafana._enabled = True
    grafana._cfg = GrafanaConfig(bearer_token="tök€n")
    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


# ── #13 undecryptable secret doesn't 500 the listing ─────────────────


async def test_listing_survives_lost_fernet_key(grafana, fresh_keystore, monkeypatch):
    await store.save("grafana", True, {"bearer_token": "tok-1234"}, grafana.secret_fields)

    # Restore onto a new Pi without the key file → a fresh key is generated.
    monkeypatch.setattr(settings, "integration_key_path",
                        str(fresh_keystore / ".int-key-new"))
    reset_fernet_cache()

    rows = await _registry.list_integrations()  # must not raise InvalidToken
    graf = next(r for r in rows if r["slug"] == "grafana")
    assert graf["config"]["bearer_token"] == ""
    assert "re-enter" in (graf["health"]["last_error"] or "")

    cfg = await _registry.get_config("grafana")
    assert cfg["config"]["bearer_token"] == ""

    row = await store.load("grafana", grafana.secret_fields)
    assert row.unreadable_secrets == frozenset({"bearer_token"})

    # Re-entering the credential works and clears the condition.
    await _registry.put_config("grafana", {"enabled": False,
                                           "config": {"bearer_token": "new-tok-5678"}})
    row = await store.load("grafana", grafana.secret_fields)
    assert row.config["bearer_token"] == "new-tok-5678"
    assert row.unreadable_secrets == frozenset()
