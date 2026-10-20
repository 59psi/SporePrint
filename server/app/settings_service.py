"""User-configurable settings service.

Settings are stored in the user_settings table and override env vars.
Resolution order: DB value > env var > default. Every service reads the
runtime ``settings`` object (app.config), so a stored value is copied into it
at boot (apply_persisted_settings, which the lifespan runs before any
background task starts) and on every change (set_setting / delete_setting).
"""

import logging
import math
import re

from .cloud.ota import OTAError, parse_ota_pubkey
from .config import settings as env_settings
from .db import get_db
from .integrations._settings_store import secret_preview
from .weather.providers import PROVIDER_NAMES

log = logging.getLogger(__name__)

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

# Credentials. GET /api/settings (and every PUT / DELETE answer) shows them
# only as a fingerprint (secret_preview, as the integrations listing does)
# plus `is_set`, never the key itself: the dashboard only needs to know
# whether one is set, and in the default LAN-trust mode any device on the
# network can read this endpoint.
SECRET_SETTINGS = frozenset({"claude_api_key", "weather_api_key"})

# ntfy's own topic rule. It refuses any other topic, so a saved "" or
# "grow alerts" lost every page, critical ones included.
_NTFY_TOPIC_RE = re.compile(r"^[-_A-Za-z0-9]{1,64}$")
# A day: past that the weather is no use to the rules anyway.
_MAX_WEATHER_POLL_MINUTES = 24 * 60


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

        # A credential's value is its fingerprint (see SECRET_SETTINGS);
        # older dashboards only test `value` for being non-empty.
        shown = secret_preview(value) if key in SECRET_SETTINGS and value else value
        result[key] = {
            "value": shown,
            "source": source,
            "description": description,
            "display_value": shown,
            "is_set": bool(value),
        }

    return result


async def set_setting(key: str, value: str) -> dict:
    """Set a user setting (persisted to DB, overrides env). Per-key
    validators run BEFORE persisting so a malformed value never lands
    in the DB. Surrounding whitespace is dropped, and an empty value
    removes the override (delete_setting): stored, it replaced the env
    value with "" (an empty ntfy topic lost every page)."""
    if key not in CONFIGURABLE_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")

    value = value.strip()
    if not value:
        return await delete_setting(key)
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


async def apply_persisted_settings() -> int:
    """Copy every stored setting into the runtime config; return how many.

    set_setting applies a value to the running process only, so without this
    every restart silently reverted the Claude key (vision auto-analysis off),
    the ntfy topic (every page to the default topic), the OTA verify key and
    the weather location to their env values, while GET /api/settings went
    on reporting the saved ones. A stored value that is empty or no longer
    validates is skipped with a warning; the env value stays in force.
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT key, value FROM user_settings")
        rows = [(row["key"], row["value"]) for row in await cursor.fetchall()]
    applied = 0
    for key, value in rows:
        if key not in CONFIGURABLE_SETTINGS:
            continue
        value = (value or "").strip()
        try:
            if not value:
                raise ValueError("it is empty")
            _validate_setting(key, value)
        except ValueError as e:
            log.warning("Saved setting %s not applied (%s); using the env value", key, e)
            continue
        _apply_to_runtime(key, value)
        applied += 1
    return applied


def _validate_setting(key: str, value: str) -> None:
    """Per-key validators for a non-empty value. Raises ValueError on
    rejection."""
    if key == "ota_pubkey_b64":
        # Decode AND construct the curve point so a valid-length-but-bogus
        # value is rejected here, not at OTA time: the OTA paths' own parser.
        try:
            parse_ota_pubkey(value)
        except OTAError as e:
            raise ValueError(str(e)) from e

    if key in ("weather_lat", "weather_lon"):
        limit = 90 if key == "weather_lat" else 180
        try:
            degrees = float(value)
        except ValueError as e:
            raise ValueError(f"{key} must be a decimal number") from e
        # NaN passes both range comparisons; every provider then fails.
        if not math.isfinite(degrees) or not -limit <= degrees <= limit:
            raise ValueError(f"{key} must be in [-{limit}, {limit}]")

    if key == "weather_poll_minutes":
        # 0 or less made the poll loop re-poll back to back and judged every
        # fresh reading stale; a fraction was stored but never applied.
        try:
            minutes = int(value)
        except ValueError as e:
            raise ValueError("weather_poll_minutes must be a whole number of minutes") from e
        if minutes < 1:
            raise ValueError("weather_poll_minutes must be at least 1")
        if minutes > _MAX_WEATHER_POLL_MINUTES:
            raise ValueError(
                f"weather_poll_minutes must be at most {_MAX_WEATHER_POLL_MINUTES}")

    if key == "weather_provider" and value not in PROVIDER_NAMES:
        raise ValueError(f"weather_provider must be one of: {', '.join(PROVIDER_NAMES)}")

    if key == "ntfy_topic" and not _NTFY_TOPIC_RE.match(value):
        raise ValueError(
            "ntfy_topic must be 1-64 letters, digits, '-' or '_' (ntfy refuses "
            "any other topic)")

    if key == "setup_complete" and value not in ("0", "1"):
        raise ValueError('setup_complete must be "0" or "1"')


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
