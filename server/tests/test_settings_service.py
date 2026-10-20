"""Settings saved from the dashboard: applied at boot, validated, and never
handed back in the clear.
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import settings_service
from app.config import settings
from app.db import get_db

_RUNTIME_ATTRS = (
    "claude_api_key", "ntfy_topic", "weather_lat", "weather_lon",
    "weather_poll_minutes", "weather_provider", "weather_api_key",
    "ota_pubkey_b64", "setup_complete",
)


@pytest.fixture(autouse=True)
def _restore_runtime_settings(monkeypatch):
    """set_setting and the boot loader write the process-wide settings object;
    put every attribute they can touch back after each test."""
    for attr in _RUNTIME_ATTRS:
        monkeypatch.setattr(settings, attr, getattr(settings, attr))


def _pubkey_b64() -> str:
    raw = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


async def _store(**values):
    async with get_db() as db:
        for key, value in values.items():
            await db.execute("INSERT INTO user_settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()


async def _stored(key: str):
    async with get_db() as db:
        cursor = await db.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
    return row["value"] if row else None


# ── saved settings survive a restart ──────────────────────────────────────


@pytest.fixture()
async def saved(monkeypatch):
    """Settings an operator saved before the restart, and a runtime that has
    only the env values (a fresh process)."""
    key = _pubkey_b64()
    await _store(claude_api_key="sk-ant-saved-1234", ntfy_topic="brandon-closet",
                 weather_lat="37.7749", weather_lon="-122.4194",
                 weather_poll_minutes="15", ota_pubkey_b64=key)
    for attr, env_value in (("claude_api_key", ""), ("ntfy_topic", "sporeprint"),
                            ("weather_lat", ""), ("weather_lon", ""),
                            ("weather_poll_minutes", 10), ("ota_pubkey_b64", "")):
        monkeypatch.setattr(settings, attr, env_value)
    return key


def test_the_lifespan_applies_saved_settings_before_anything_reads_them(saved, client):
    assert settings.claude_api_key == "sk-ant-saved-1234"
    assert settings.ntfy_topic == "brandon-closet"
    assert (settings.weather_lat, settings.weather_lon) == ("37.7749", "-122.4194")
    assert settings.weather_poll_minutes == 15
    assert settings.ota_pubkey_b64 == saved


async def test_a_saved_value_that_no_longer_validates_is_skipped(monkeypatch, caplog):
    monkeypatch.setattr(settings, "weather_poll_minutes", 10)
    monkeypatch.setattr(settings, "ntfy_topic", "sporeprint")
    await _store(weather_poll_minutes="0", ntfy_topic="", weather_lat="nan")
    assert await settings_service.apply_persisted_settings() == 0
    assert settings.weather_poll_minutes == 10
    assert settings.ntfy_topic == "sporeprint"
    assert "weather_poll_minutes not applied" in caplog.text


# ── validation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["weather_lat", "weather_lon"])
@pytest.mark.parametrize("value", ["nan", "NaN", "  nan ", "inf", "-inf", "1e400", "91.5e9"])
def test_a_coordinate_that_is_not_a_finite_in_range_number_is_a_400(client, key, value):
    r = client.put(f"/api/settings/{key}", json={"value": value})
    assert r.status_code == 400
    assert client.get("/api/settings").json()[key]["source"] != "user"


def test_a_valid_coordinate_is_saved(client):
    r = client.put("/api/settings/weather_lat", json={"value": " 45.5 "})
    assert r.status_code == 200
    assert r.json()["weather_lat"]["value"] == "45.5"
    assert settings.weather_lat == "45.5"


@pytest.mark.parametrize("value", ["grow alerts", "a/b", "x" * 65, "ümlaut"])
def test_a_topic_ntfy_would_refuse_is_a_400(client, value):
    r = client.put("/api/settings/ntfy_topic", json={"value": value})
    assert r.status_code == 400


async def test_an_empty_value_removes_the_override(client, monkeypatch):
    env_topic = settings.__class__().ntfy_topic
    assert client.put("/api/settings/ntfy_topic", json={"value": "closet-7"}).status_code == 200
    assert settings.ntfy_topic == "closet-7"
    r = client.put("/api/settings/ntfy_topic", json={"value": "  "})
    assert r.status_code == 200
    assert r.json()["ntfy_topic"]["source"] != "user"
    assert await _stored("ntfy_topic") is None
    assert settings.ntfy_topic == env_topic


def test_a_poll_interval_over_a_day_is_a_400(client):
    assert client.put("/api/settings/weather_poll_minutes",
                      json={"value": "100000"}).status_code == 400


def test_the_setup_flag_is_zero_or_one(client):
    assert client.put("/api/settings/setup_complete", json={"value": "yes"}).status_code == 400
    assert client.put("/api/settings/setup_complete", json={"value": "1"}).status_code == 200


def test_the_ota_key_is_checked_with_the_ota_parser(client):
    r = client.put("/api/settings/ota_pubkey_b64", json={"value": "bm90LWEta2V5"})
    assert r.status_code == 400
    assert "OTA pubkey" in r.json()["detail"]
    key = _pubkey_b64()
    r = client.put("/api/settings/ota_pubkey_b64", json={"value": key})
    assert r.status_code == 200
    # A public key, shown in full so it can be checked against the keypair.
    assert r.json()["ota_pubkey_b64"]["value"] == key


# ── credentials are never handed back ─────────────────────────────────────


@pytest.mark.parametrize("key", ["claude_api_key", "weather_api_key"])
def test_a_saved_credential_is_shown_only_as_a_fingerprint(client, key):
    secret = "sk-ant-api03-SECRETSECRET-wxyz"
    r = client.put(f"/api/settings/{key}", json={"value": secret})
    assert r.status_code == 200
    for body in (r.json(), client.get("/api/settings").json()):
        assert secret not in json.dumps(body)
        assert "wxyz" not in json.dumps(body)
        entry = body[key]
        assert entry["is_set"] is True and entry["source"] == "user"
        assert entry["value"] and entry["value"] == entry["display_value"]
    assert getattr(settings, key) == secret  # the runtime still has the key itself


def test_an_unset_credential_reads_as_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "")
    entry = client.get("/api/settings").json()["claude_api_key"]
    assert entry["is_set"] is False and entry["value"] == ""


def test_an_env_credential_is_not_handed_back_either(client, monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "sk-from-the-env-abcd")
    entry = client.get("/api/settings").json()["claude_api_key"]
    assert entry["is_set"] is True and entry["source"] == "env"
    assert "abcd" not in entry["value"]
