"""Settings saved from the dashboard: applied at boot, validated, and never
handed back in the clear.

Validation and redaction live in app/settings_service.py and are tested
there directly; the route only maps a refusal to a 400 (one test below).
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app import settings_service
from app.config import Settings, settings
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


@pytest.mark.parametrize("key, value", [
    # NaN passes both range comparisons, so every provider then failed;
    # float() reads every spelling of it (and of inf) the same way.
    ("weather_lat", "nan"), ("weather_lon", "NaN"),
    ("weather_lon", "-inf"), ("weather_lat", "1e400"),
    ("weather_lat", "90.5"), ("weather_lon", "180.5"),
    ("weather_lat", "north"),
    # Topics ntfy itself would refuse: every page would be lost.
    ("ntfy_topic", "grow alerts"), ("ntfy_topic", "a/b"), ("ntfy_topic", "x" * 65),
    ("ntfy_topic", "ümlaut"),
    # 0 re-polled back to back; a fraction was stored but never applied.
    ("weather_poll_minutes", "0"), ("weather_poll_minutes", "1.5"),
    ("weather_poll_minutes", "100000"),           # over a day
    ("weather_provider", "darksky"),
    ("setup_complete", "yes"),
    ("ota_pubkey_b64", "bm90LWEta2V5"),           # base64, but no Ed25519 key
    ("not_a_setting", "1"),
])
async def test_a_value_the_setting_cannot_take_is_refused_and_not_saved(key, value):
    runtime = getattr(settings, key, None)
    with pytest.raises(ValueError):
        await settings_service.set_setting(key, value)
    assert await _stored(key) is None
    assert getattr(settings, key, None) == runtime


@pytest.mark.parametrize("key, value, shown, runtime", [
    ("weather_lat", " 45.5 ", "45.5", "45.5"),
    ("weather_lat", "-90", "-90", "-90"),
    ("weather_lon", "180", "180", "180"),
    ("weather_poll_minutes", "1440", "1440", 1440),
    ("setup_complete", "1", "1", "1"),
])
async def test_a_valid_value_is_saved_and_applied(key, value, shown, runtime):
    result = await settings_service.set_setting(key, value)
    assert result[key]["value"] == shown and result[key]["source"] == "user"
    assert await _stored(key) == shown
    assert getattr(settings, key) == runtime


async def test_an_empty_value_removes_the_override():
    """Stored, an empty ntfy topic replaced the env value with "" and lost
    every page."""
    env_topic = Settings().ntfy_topic
    await settings_service.set_setting("ntfy_topic", "closet-7")
    assert settings.ntfy_topic == "closet-7"
    result = await settings_service.set_setting("ntfy_topic", "  ")
    assert result["ntfy_topic"]["source"] != "user"
    assert await _stored("ntfy_topic") is None
    assert settings.ntfy_topic == env_topic
    with pytest.raises(ValueError, match="Unknown setting"):
        await settings_service.delete_setting("not_a_setting")


def test_the_route_answers_a_refused_value_with_a_400(client):
    """The OTA key is checked with the OTA paths' own parser, so a saved key
    is one they accept; a public key is shown in full so it can be checked
    against the keypair."""
    r = client.put("/api/settings/ota_pubkey_b64", json={"value": "bm90LWEta2V5"})
    assert r.status_code == 400
    assert "OTA pubkey" in r.json()["detail"]
    key = _pubkey_b64()
    r = client.put("/api/settings/ota_pubkey_b64", json={"value": key})
    assert r.status_code == 200
    assert r.json()["ota_pubkey_b64"]["value"] == key
    assert client.get("/api/settings").json()["ota_pubkey_b64"]["value"] == key


# ── credentials are never handed back ─────────────────────────────────────


@pytest.mark.parametrize("key", ["claude_api_key", "weather_api_key"])
async def test_a_saved_credential_is_shown_only_as_a_fingerprint(key):
    secret = "sk-ant-api03-SECRETSECRET-wxyz"
    saved = await settings_service.set_setting(key, secret)
    for body in (saved, await settings_service.get_all_settings()):
        assert secret not in json.dumps(body)
        assert "wxyz" not in json.dumps(body)
        entry = body[key]
        assert entry["is_set"] is True and entry["source"] == "user"
        assert entry["value"] and entry["value"] == entry["display_value"]
    assert getattr(settings, key) == secret  # the runtime still has the key itself


@pytest.mark.parametrize("env_value, is_set, source", [
    ("", False, None),
    ("sk-from-the-env-abcd", True, "env"),
], ids=["unset", "from-env"])
async def test_an_env_credential_is_not_handed_back_either(monkeypatch, env_value, is_set, source):
    monkeypatch.setattr(settings, "claude_api_key", env_value)
    entry = (await settings_service.get_all_settings())["claude_api_key"]
    assert entry["is_set"] is is_set
    if is_set:
        assert entry["source"] == source
        assert "abcd" not in entry["value"]
    else:
        assert entry["value"] == ""
