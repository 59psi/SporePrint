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
* A kept (omitted / masked) secret is never sent to a new destination: a PUT
  that changes a driver's secret_bound_fields must re-enter the secret.
"""

from __future__ import annotations

from typing import get_args

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.cloud import integrations_proxy
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


# ── a kept secret stays bound to where it is sent ────────────────────
#
# GET redacts api_key, and an omitted or masked secret keeps the stored value.
# Aranet, Agrowtek and BIOS send that key to a caller-controlled base_url, so
# "keep the stored key" may only hold while base_url is unchanged. Otherwise
# anyone who can PUT a config (LAN-trust, the cloud put_config RPC) could point
# the stored key at their own host without ever seeing it.

_URL_KEY_DRIVERS = ("aranet", "agrowtek", "bios")
_TRUSTED_URL = "http://10.0.0.42"
_OPERATOR_KEY = "OPERATOR-SECRET-KEY-1234"


@pytest.fixture(params=_URL_KEY_DRIVERS)
async def url_driver(request, fresh_keystore):
    drv = _registry.registered_drivers()[request.param]
    saved = drv._cfg
    await _registry.put_config(drv.name, {"enabled": False, "config": {
        "base_url": _TRUSTED_URL, "api_key": _OPERATOR_KEY}})
    yield drv
    await drv.stop()
    drv._cfg = saved


async def _stored(drv):
    return (await store.load(drv.name, drv.secret_fields)).config


@pytest.mark.parametrize("key_sent", ["omitted", "masked preview"])
async def test_new_base_url_needs_the_key_re_entered(url_driver, key_sent):
    cfg = {"base_url": "http://attacker.example:8080"}
    if key_sent == "masked preview":
        cfg["api_key"] = (await _registry.get_config(url_driver.name))["config"]["api_key"]
        assert cfg["api_key"] == "••••1234"

    with pytest.raises(HTTPException) as exc:
        await _registry.put_config(url_driver.name, {"enabled": False, "config": cfg})

    assert exc.value.status_code == 422
    assert "api_key" in exc.value.detail and "base_url" in exc.value.detail
    stored = await _stored(url_driver)
    assert stored["base_url"] == _TRUSTED_URL
    assert stored["api_key"] == _OPERATOR_KEY
    # The driver never held the new URL together with the stored key.
    assert url_driver.config.base_url == _TRUSTED_URL


async def test_new_base_url_with_the_key_re_entered_is_saved(url_driver):
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {
        "base_url": "http://10.0.0.77", "api_key": "NEW-KEY-5678"}})
    stored = await _stored(url_driver)
    assert (stored["base_url"], stored["api_key"]) == ("http://10.0.0.77", "NEW-KEY-5678")


async def test_same_base_url_keeps_the_stored_key(url_driver):
    # The settings form PUTs the whole config back with the masked key; the
    # trailing slash is normalised away by the schema, so it is the same URL.
    masked = (await _registry.get_config(url_driver.name))["config"]["api_key"]
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {
        "base_url": _TRUSTED_URL + "/", "api_key": masked, "poll_seconds": 120}})
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {
        "base_url": _TRUSTED_URL, "poll_seconds": 90}})
    stored = await _stored(url_driver)
    assert stored["api_key"] == _OPERATOR_KEY
    assert stored["poll_seconds"] == 90
    assert url_driver.config.api_key == _OPERATOR_KEY


async def test_blanking_the_url_is_not_a_new_destination(url_driver):
    """With no base_url the key goes nowhere, so a partial PUT that blanks it
    is not refused; a later new URL still needs the key re-entered."""
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {"poll_seconds": 60}})
    assert (await _stored(url_driver))["base_url"] == ""
    with pytest.raises(HTTPException) as exc:
        await _registry.put_config(url_driver.name, {"enabled": False, "config": {
            "base_url": "http://attacker.example"}})
    assert exc.value.status_code == 422
    assert (await _stored(url_driver))["api_key"] == _OPERATOR_KEY


async def test_explicit_empty_key_with_a_new_url_clears_it(url_driver):
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {
        "base_url": "http://10.0.0.99", "api_key": ""}})
    stored = await _stored(url_driver)
    assert (stored["base_url"], stored["api_key"]) == ("http://10.0.0.99", "")


async def test_legacy_unnormalised_stored_url_counts_as_unchanged(url_driver):
    # A row saved before the schema normalised base_url.
    await store.save(url_driver.name, False,
                     {"base_url": _TRUSTED_URL + "/", "api_key": _OPERATOR_KEY},
                     url_driver.secret_fields)
    await _registry.put_config(url_driver.name, {"enabled": False, "config": {
        "base_url": _TRUSTED_URL}})
    assert (await _stored(url_driver))["api_key"] == _OPERATOR_KEY


async def test_cloud_put_config_rpc_cannot_redirect_the_key(url_driver):
    with pytest.raises(HTTPException) as exc:
        await integrations_proxy._dispatch("put_config", url_driver.name, {
            "enabled": False, "config": {"base_url": "http://attacker.example"}})
    assert exc.value.status_code == 422
    assert (await _stored(url_driver))["base_url"] == _TRUSTED_URL


async def test_redirect_is_a_422_over_http(url_driver):
    app = FastAPI()
    app.include_router(_registry.router, prefix="/api/integrations")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.put(f"/api/integrations/{url_driver.name}/config", json={
            "enabled": False, "config": {"base_url": "http://attacker.example"}})
    assert resp.status_code == 422
    assert "re-enter" in resp.json()["detail"]


# Config fields that look like a network destination but never receive the
# driver's secret, each with the reason. Any other such field must be listed
# in the driver's secret_bound_fields.
_NOT_A_SECRET_DESTINATION = {
    # Local transport polls devices unauthenticated; the password only ever
    # goes to the fixed api.pulsegrow.com.
    ("pulse", "local_broadcast_addr"),
    ("pulse", "local_device_urls"),
    # A region selects one of the fixed TP-Link cloud hosts.
    ("tapo", "cloud_region"),
    # KLAP: the plug must first prove it knows sha256(sha1(email) +
    # sha1(password)) (handshake1 is verified before handshake2 is sent), so
    # an attacker-chosen ip learns nothing derived from the password.
    ("tapo", "devices[].ip"),
}
_DESTINATION_TOKENS = {"url", "urls", "host", "hosts", "ip", "ips", "addr",
                       "address", "endpoint", "server", "region"}


def _schema_field_paths(model, prefix=""):
    for name, field in model.model_fields.items():
        yield prefix + name
        for arg in (field.annotation, *get_args(field.annotation)):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                yield from _schema_field_paths(arg, f"{prefix}{name}[].")


def test_every_secret_destination_field_is_bound():
    """Audit guard for new drivers: a host/URL-like field next to a secret is
    bound to it, or is recorded above with why the secret never goes there."""
    for slug, drv in _registry.registered_drivers().items():
        if not drv.secret_fields:
            assert not drv.secret_bound_fields, slug
            continue
        for path in _schema_field_paths(drv.config_schema):
            leaf = path.rsplit(".", 1)[-1]
            if leaf in drv.secret_fields or not _DESTINATION_TOKENS & set(leaf.split("_")):
                continue
            assert path in drv.secret_bound_fields or (slug, path) in _NOT_A_SECRET_DESTINATION, (
                f"{slug}.{path} looks like where {sorted(drv.secret_fields)} is sent: add it "
                "to secret_bound_fields, or record here why the secret never goes there"
            )


def test_bound_fields_are_real_schema_fields():
    for slug, drv in _registry.registered_drivers().items():
        assert set(drv.secret_bound_fields) <= set(drv.config_schema.model_fields), slug
    for slug in _URL_KEY_DRIVERS:
        assert "base_url" in _registry.registered_drivers()[slug].secret_bound_fields, slug
