"""Encrypted-at-rest persistence for per-driver integration config.

`config` is stored as JSON in `integration_settings.config`. Fields named
in the driver's `secret_fields` set are encrypted individually with the
integrations Fernet key before being JSON-encoded, so the on-disk shape is
self-describing: `{"api_key": "gAAAA…", "base_url": "http://10.0.0.5"}`.

Reading round-trips through `_decrypt_secrets()` so callers receive the
plaintext config dict.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ..db import get_db
from ._base import IntegrationHealth, IntegrationState
from ._keystore import get_fernet


_SECRET_PREFIX = "fernet:"


def _encrypt_secrets(config: dict[str, Any], secret_fields: set[str]) -> dict[str, Any]:
    if not secret_fields:
        return config
    fernet = get_fernet()
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in secret_fields and v is not None and v != "":
            token = fernet.encrypt(str(v).encode("utf-8")).decode("ascii")
            out[k] = f"{_SECRET_PREFIX}{token}"
        else:
            out[k] = v
    return out


def _decrypt_secrets(config: dict[str, Any], secret_fields: set[str]) -> dict[str, Any]:
    if not secret_fields:
        return config
    fernet = get_fernet()
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in secret_fields and isinstance(v, str) and v.startswith(_SECRET_PREFIX):
            ciphertext = v[len(_SECRET_PREFIX):].encode("ascii")
            out[k] = fernet.decrypt(ciphertext).decode("utf-8")
        else:
            out[k] = v
    return out


@dataclass(frozen=True)
class StoredSettings:
    slug: str
    enabled: bool
    config: dict[str, Any]
    last_health_state: IntegrationState | None
    last_health_at: float | None
    last_error: str | None
    updated_at: float


async def load(slug: str, secret_fields: set[str]) -> StoredSettings | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT slug, enabled, config, last_health_state, last_health_at, "
            "last_error, updated_at FROM integration_settings WHERE slug = ?",
            (slug,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    raw_config = json.loads(row["config"]) if row["config"] else {}
    return StoredSettings(
        slug=row["slug"],
        enabled=bool(row["enabled"]),
        config=_decrypt_secrets(raw_config, secret_fields),
        last_health_state=row["last_health_state"],
        last_health_at=row["last_health_at"],
        last_error=row["last_error"],
        updated_at=row["updated_at"],
    )


async def save(
    slug: str,
    enabled: bool,
    config: dict[str, Any],
    secret_fields: set[str],
) -> StoredSettings:
    encrypted = _encrypt_secrets(config, secret_fields)
    payload = json.dumps(encrypted, separators=(",", ":"))
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO integration_settings (slug, enabled, config, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(slug) DO UPDATE SET "
            "  enabled = excluded.enabled, "
            "  config = excluded.config, "
            "  updated_at = excluded.updated_at",
            (slug, int(enabled), payload, now),
        )
        await db.commit()
    return StoredSettings(
        slug=slug,
        enabled=enabled,
        config=config,
        last_health_state=None,
        last_health_at=None,
        last_error=None,
        updated_at=now,
    )


async def update_health(slug: str, health: IntegrationHealth) -> None:
    now = time.time()
    async with get_db() as db:
        await db.execute(
            "UPDATE integration_settings SET "
            "  last_health_state = ?, last_health_at = ?, last_error = ? "
            "WHERE slug = ?",
            (health.state, now, health.last_error, slug),
        )
        await db.commit()


async def list_all(driver_secret_fields: dict[str, set[str]]) -> list[StoredSettings]:
    """Bulk-load every stored row.

    `driver_secret_fields` maps slug → secret field set so each row's
    secrets can be redacted/decrypted with the right configuration.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT slug, enabled, config, last_health_state, last_health_at, "
            "last_error, updated_at FROM integration_settings"
        )
        rows = await cursor.fetchall()
    out: list[StoredSettings] = []
    for row in rows:
        secret_fields = driver_secret_fields.get(row["slug"], set())
        raw_config = json.loads(row["config"]) if row["config"] else {}
        out.append(
            StoredSettings(
                slug=row["slug"],
                enabled=bool(row["enabled"]),
                config=_decrypt_secrets(raw_config, secret_fields),
                last_health_state=row["last_health_state"],
                last_health_at=row["last_health_at"],
                last_error=row["last_error"],
                updated_at=row["updated_at"],
            )
        )
    return out


def redact_for_response(config: dict[str, Any], secret_fields: set[str]) -> dict[str, Any]:
    """Return a copy of `config` with secret-field values replaced by a
    last-4 preview. The settings UI shows e.g. `••••wXyZ` so the operator
    can recognise their key without exposing it.
    """
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in secret_fields and isinstance(v, str) and v:
            tail = v[-4:] if len(v) >= 4 else v
            out[k] = f"••••{tail}"
        else:
            out[k] = v
    return out
