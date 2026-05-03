"""Tests for the v4.1.1 lighting / HVAC driver batch.

Each driver is exercised at the contract level:
  - Auto-registers on import
  - Reports the documented tier_required + secret_fields
  - test_connection returns ``error`` when creds/base_url missing
  - Lifecycle (start/stop) is idempotent
  - Tolerant parsing — unknown payload shapes degrade to empty rather
    than crashing the poll

Live-device verification of vendor API specifics is explicitly out of
scope; these tests pin the *framework* behaviour so refinements based
on real hardware are additive.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations import _registry
from app.integrations._keystore import reset_fernet_cache


# ── Common fixtures ──────────────────────────────────────────────────


@pytest.fixture
def fresh_keystore(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "integration_key_path", str(tmp_path / ".int-key"))
    reset_fernet_cache()
    yield
    reset_fernet_cache()


# ── Registry: every new driver auto-registers ────────────────────────


@pytest.mark.parametrize(
    "slug,tier,secret_keys",
    [
        ("agrowtek", "free", {"api_key"}),
        ("trane", "premium", {"password"}),
        ("fluence", "premium", {"password"}),
        ("quest", "free", set()),
        ("anden", "free", set()),
        ("fohse", "premium", {"password"}),
        ("bios", "free", {"api_key"}),
    ],
)
def test_driver_registered_with_correct_tier(slug, tier, secret_keys):
    drv = _registry.registered_drivers().get(slug)
    assert drv is not None, f"{slug!r} not registered"
    assert drv.tier_required == tier
    assert drv.secret_fields == secret_keys


# ── Empty-config test_connection returns error ────────────────────────


@pytest.mark.parametrize("slug", ["agrowtek", "quest", "anden", "bios"])
@pytest.mark.asyncio
async def test_lan_drivers_test_without_base_url_returns_error(
    slug, fresh_keystore
):
    drv = _registry.registered_drivers()[slug]
    cfg = drv.config_schema()
    await drv.configure(cfg)
    health = await drv.test_connection()
    assert health.state == "error"
    assert "base_url" in (health.last_error or "").lower() or "required" in (
        health.last_error or ""
    ).lower()


@pytest.mark.parametrize("slug", ["trane", "fluence", "fohse"])
@pytest.mark.asyncio
async def test_cloud_drivers_test_without_creds_returns_error(
    slug, fresh_keystore
):
    drv = _registry.registered_drivers()[slug]
    cfg = drv.config_schema()
    await drv.configure(cfg)
    health = await drv.test_connection()
    assert health.state == "error"


# ── Lifecycle is idempotent ──────────────────────────────────────────


@pytest.mark.parametrize(
    "slug",
    ["agrowtek", "trane", "fluence", "quest", "anden", "fohse", "bios"],
)
@pytest.mark.asyncio
async def test_start_stop_is_idempotent(slug, fresh_keystore):
    drv = _registry.registered_drivers()[slug]
    cfg = drv.config_schema()
    await drv.configure(cfg)
    await drv.stop()  # never started
    await drv.start()
    first_task = drv._task  # type: ignore[attr-defined]
    await drv.start()
    assert drv._task is first_task  # type: ignore[attr-defined]
    await drv.stop()
    await drv.stop()  # already stopped — must not raise
    assert drv._task is None  # type: ignore[attr-defined]


# ── Tolerant parsing — drivers that return list-or-dict-or-empty ─────


@pytest.mark.asyncio
async def test_agrowtek_handles_array_and_object_response(
    fresh_keystore, monkeypatch
):
    from app.integrations.agrowtek.driver import AgrowtekDriver, AgrowtekConfig

    drv = AgrowtekDriver()
    await drv.configure(
        AgrowtekConfig(base_url="http://10.0.0.30", api_key="k")
    )

    async def fake_get(self, url, headers=None):
        return httpx.Response(200, json=[{"id": "s1", "measurements": {}}])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    sensors = await drv._fetch_sensors(drv._cfg)  # type: ignore[arg-type]
    assert len(sensors) == 1


@pytest.mark.asyncio
async def test_quest_handles_non_dict_response(fresh_keystore, monkeypatch):
    from app.integrations.quest.driver import QuestDriver, QuestConfig

    drv = QuestDriver()
    await drv.configure(QuestConfig(base_url="http://10.0.0.40"))

    async def fake_get(self, url):
        return httpx.Response(200, json=[1, 2, 3])  # unexpected shape

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    data = await drv._fetch_status(drv._cfg)  # type: ignore[arg-type]
    assert data == {}


@pytest.mark.asyncio
async def test_bios_handles_object_response(fresh_keystore, monkeypatch):
    from app.integrations.bios.driver import BiosDriver, BiosConfig

    drv = BiosDriver()
    await drv.configure(BiosConfig(base_url="http://10.0.0.55"))

    async def fake_get(self, url, headers=None):
        return httpx.Response(200, json={"fixtures": [{"id": "f1"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    fixtures = await drv._fetch_fixtures(drv._cfg)  # type: ignore[arg-type]
    assert len(fixtures) == 1
    assert fixtures[0]["id"] == "f1"


# ── 5xx handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anden_5xx_raises(fresh_keystore, monkeypatch):
    from app.integrations.anden.driver import AndenDriver, AndenConfig

    drv = AndenDriver()
    await drv.configure(AndenConfig(base_url="http://10.0.0.50"))

    async def fake_get(self, url):
        return httpx.Response(503, text="overloaded")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(RuntimeError, match="Anden"):
        await drv._fetch_status(drv._cfg)  # type: ignore[arg-type]


# ── Login flow for cloud drivers (Trane / Fluence / Fohse) ──────────

# Import each driver/config pair directly (no dynamic import) so the
# parametrize values stay strict-typed and the import graph is auditable.
from app.integrations.trane.driver import TraneDriver, TraneConfig
from app.integrations.fluence.driver import FluenceDriver, FluenceConfig
from app.integrations.fohse.driver import FohseDriver, FohseConfig


@pytest.mark.parametrize(
    "driver_cls,config_cls",
    [
        (TraneDriver, TraneConfig),
        (FluenceDriver, FluenceConfig),
        (FohseDriver, FohseConfig),
    ],
)
@pytest.mark.asyncio
async def test_cloud_login_401_raises(
    driver_cls, config_cls, fresh_keystore, monkeypatch
):
    drv = driver_cls()
    await drv.configure(config_cls(email="b@example.com", password="bad"))

    async def fake_post(self, url, json=None):
        return httpx.Response(401, text="unauthorized")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    health = await drv.test_connection()
    assert health.state == "error"
    err = (health.last_error or "").lower()
    assert "401" in err or "unauthor" in err


# ── Config validators ────────────────────────────────────────────────


def test_agrowtek_config_rejects_non_http_scheme():
    from app.integrations.agrowtek.driver import AgrowtekConfig
    with pytest.raises(ValueError, match="http"):
        AgrowtekConfig(base_url="ftp://10.0.0.30")


def test_trane_config_rejects_malformed_email():
    from app.integrations.trane.driver import TraneConfig
    with pytest.raises(ValueError, match="@"):
        TraneConfig(email="not-an-email")


def test_quest_config_floors_poll_interval():
    from app.integrations.quest.driver import QuestConfig
    with pytest.raises(ValueError):
        QuestConfig(poll_seconds=10)


# ── HttpVendorDriver health transitions ──────────────────────────────


@pytest.mark.asyncio
async def test_health_transitions_disabled_to_ok_to_error(fresh_keystore):
    """Use a real registered driver to exercise the shared base."""
    drv = _registry.registered_drivers()["bios"]
    from app.integrations.bios.driver import BiosConfig
    await drv.configure(BiosConfig(base_url="http://10.0.0.55"))

    h = await drv.health()
    assert h.state == "disabled"
    await drv.start()
    h = await drv.health()
    assert h.state == "ok"
    drv._record_outcome(False, "boom")  # type: ignore[attr-defined]
    h = await drv.health()
    assert h.state == "error"
    assert h.last_error == "boom"
    await drv.stop()
