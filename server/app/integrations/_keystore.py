"""Per-Pi Fernet key for at-rest encryption of integration secrets.

The key is generated once on first use and persisted at the path configured
by `settings.integration_key_path` (default `data/db/.integration-key`).
Mode 0600 — readable only by the sporeprint server user.

There is intentionally no remote recovery for this key. If the Pi loses it,
the operator re-enters integration credentials. That tradeoff is preferable
to centralising key escrow on our infrastructure.
"""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import settings


logger = logging.getLogger(__name__)


def _generate_key() -> bytes:
    # Fernet keys are 32 random bytes urlsafe-base64-encoded — `Fernet.generate_key()`
    # exists, but we use `secrets` directly to keep the import surface small
    # and the entropy source explicit.
    raw = secrets.token_bytes(32)
    import base64
    return base64.urlsafe_b64encode(raw)


def _load_or_create(path: Path) -> bytes:
    if path.exists():
        key = path.read_bytes().strip()
        # Validate by constructing a Fernet — raises ValueError if malformed.
        Fernet(key)
        return key

    path.parent.mkdir(parents=True, exist_ok=True)
    key = _generate_key()
    # Write with 0600 permissions atomically. We open with O_CREAT|O_EXCL so
    # two concurrent writers can't both think they created a fresh key.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    logger.info("integrations: generated fresh Fernet key at %s", path)
    return key


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Return the process-wide Fernet for integration-secret encryption.

    Memoised — the key file is read once per process. Tests that swap the
    `integration_key_path` setting must call `reset_fernet_cache()` first.
    """
    path = Path(settings.integration_key_path)
    return Fernet(_load_or_create(path))


def reset_fernet_cache() -> None:
    """Clear the memoised Fernet — only used in tests."""
    get_fernet.cache_clear()
