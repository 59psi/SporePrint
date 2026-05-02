"""User-configurable settings service.

Settings are stored in the user_settings table and override env vars.
Resolution order: DB value > env var > default.
"""

from .db import get_db
from .config import settings as env_settings

# Settings that can be overridden from the UI
# Format: key -> (env_attr, default_value, description)
CONFIGURABLE_SETTINGS = {
    "weather_lat": ("weather_lat", "", "Weather latitude (decimal degrees, e.g. 37.7749)"),
    "weather_lon": ("weather_lon", "", "Weather longitude (decimal degrees, e.g. -122.4194)"),
    "weather_provider": (
        "weather_provider",
        "openmeteo",
        "Weather provider: openmeteo, openweathermap, or nws",
    ),
    "weather_api_key": (
        "weather_api_key",
        "",
        "OpenWeatherMap API key (only needed for openweathermap provider)",
    ),
    "weather_poll_minutes": ("weather_poll_minutes", "10", "Weather poll interval in minutes"),
    "claude_api_key": ("claude_api_key", "", "Claude API key for vision analysis"),
    "ntfy_topic": ("ntfy_topic", "sporeprint", "ntfy notification topic"),
    "ota_pubkey_b64": (
        "ota_pubkey_b64",
        "",
        "OTA verify key (base64-encoded raw 32-byte Ed25519 public key). "
        "Paste the value from scripts/generate-ota-keypair.py. "
        "Empty = OTA disabled (fail-closed).",
    ),
    "setup_complete": (
        "setup_complete",
        "0",
        'First-run setup flag. "0" = wizard auto-launches; "1" = done.',
    ),
}


async def get_setting(key: str) -> str:
    """Get a setting value. DB overrides env, env overrides default."""
    async with get_db() as db:
        cursor = await db.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row:
            return row["value"]

    # Fall back to env var
    if key in CONFIGURABLE_SETTINGS:
        env_attr = CONFIGURABLE_SETTINGS[key][0]
        return str(getattr(env_settings, env_attr, CONFIGURABLE_SETTINGS[key][1]))

    return ""


async def get_all_settings() -> dict:
    """Get all configurable settings with current values and metadata."""
    result = {}
    async with get_db() as db:
        cursor = await db.execute("SELECT key, value FROM user_settings")
        db_settings = {row["key"]: row["value"] for row in await cursor.fetchall()}

    for key, (env_attr, default, description) in CONFIGURABLE_SETTINGS.items():
        if key in db_settings:
            value = db_settings[key]
            source = "user"
        else:
            value = str(getattr(env_settings, env_attr, default))
            source = "env" if value != default else "default"

        result[key] = {
            "value": value,
            "source": source,
            "description": description,
            "display_value": _mask(key, value),
        }

    return result


async def set_setting(key: str, value: str) -> dict:
    """Set a user setting (persisted to DB, overrides env). Per-key
    validators run BEFORE persisting so a malformed value never lands
    in the DB."""
    if key not in CONFIGURABLE_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")

    _validate_setting(key, value)

    async with get_db() as db:
        await db.execute(
            """INSERT INTO user_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=unixepoch('now')""",
            (key, value),
        )
        await db.commit()

    # Update runtime config so services pick up changes on next cycle
    _apply_to_runtime(key, value)

    return await get_all_settings()


async def delete_setting(key: str) -> dict:
    """Remove a user override, reverting to env/default."""
    if key not in CONFIGURABLE_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")

    async with get_db() as db:
        await db.execute("DELETE FROM user_settings WHERE key = ?", (key,))
        await db.commit()

    # Revert runtime config to env value
    env_attr, default, _ = CONFIGURABLE_SETTINGS[key]
    env_val = str(getattr(env_settings.__class__(), env_attr, default))
    _apply_to_runtime(key, env_val)

    return await get_all_settings()


def _validate_setting(key: str, value: str) -> None:
    """Per-key validators. Raises ValueError on rejection. Empty value =
    revert to default, always accepted."""
    if not value:
        return

    if key == "ota_pubkey_b64":
        # Decode AND construct the curve point so a valid-length-but-bogus
        # value is rejected here, not at OTA time.
        import base64
        try:
            decoded = base64.b64decode(value, validate=True)
        except Exception as e:
            raise ValueError(f"OTA pubkey is not valid base64: {e}") from e
        if len(decoded) != 32:
            raise ValueError(
                f"OTA pubkey must decode to exactly 32 bytes, got {len(decoded)}"
            )
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            Ed25519PublicKey.from_public_bytes(decoded)
        except Exception as e:
            raise ValueError(f"OTA pubkey rejected by Ed25519 verifier: {e}") from e

    if key == "weather_lat":
        try:
            lat = float(value)
        except ValueError as e:
            raise ValueError("weather_lat must be a decimal number") from e
        if lat < -90 or lat > 90:
            raise ValueError("weather_lat must be in [-90, 90]")

    if key == "weather_lon":
        try:
            lon = float(value)
        except ValueError as e:
            raise ValueError("weather_lon must be a decimal number") from e
        if lon < -180 or lon > 180:
            raise ValueError("weather_lon must be in [-180, 180]")


def _mask(key: str, value: str) -> str:
    """Mask sensitive values — show only last 4 chars for API keys.

    Public keys (ota_pubkey_b64) are explicitly excluded — they're not
    secrets, and operators need to see the full value to verify which
    key is loaded against the one printed by generate-ota-keypair.py.
    """
    if key == "ota_pubkey_b64":
        return value
    if "key" in key.lower() and len(value) > 4:
        return "***" + value[-4:]
    return value


def _apply_to_runtime(key: str, value: str):
    """Push a setting change into the runtime config object."""
    attr = CONFIGURABLE_SETTINGS[key][0]
    if attr == "weather_poll_minutes":
        try:
            setattr(env_settings, attr, int(value))
        except ValueError:
            pass
    else:
        setattr(env_settings, attr, value)
