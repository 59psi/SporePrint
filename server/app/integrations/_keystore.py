"""Per-Pi Fernet key for at-rest encryption of integration secrets.

The key is generated once on first use and persisted at the path configured
by `settings.integration_key_path` (default `data/db/.integration-key`).
Mode 0600 — readable only by the sporeprint server user.

There is intentionally no remote recovery for this key. If the Pi loses it,
the operator re-enters integration credentials. That tradeoff is preferable
to centralising key escrow on our infrastructure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import tempfile
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from ..config import settings


logger = logging.getLogger(__name__)

# Domain-separation label for the key that fingerprints secret previews, so
# the preview key is never the encryption key itself.
_PREVIEW_KEY_LABEL = b"sporeprint integration secret preview"


def _generate_key() -> bytes:
    # Fernet keys are 32 random bytes urlsafe-base64-encoded — `Fernet.generate_key()`
    # exists, but we use `secrets` directly to keep the import surface small
    # and the entropy source explicit.
    return base64.urlsafe_b64encode(secrets.token_bytes(32))


def _read_key(path: Path) -> bytes:
    return path.read_bytes().strip()


def _fsync_dir(path: Path) -> None:
    """Make a new name in directory `path` survive a power cut (best effort:
    not every filesystem can fsync a directory)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _create_key_file(path: Path) -> bytes:
    """Create the key file durably and return the key it holds.

    The key is written to a 0600 temp file beside it and fsynced, then
    hard-linked to its name, so a power cut leaves no key file or a complete
    one — never the empty file that creating the name before writing could
    leave behind. link() refuses an existing name: when two processes create
    the key at once, the second keeps the first one's key.
    """
    key = _generate_key()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        try:
            os.write(fd, key)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return _read_key(path)
        except OSError:
            # No hard links on this filesystem: claim the name exclusively.
            try:
                out = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return _read_key(path)
            try:
                os.write(out, key)
                os.fsync(out)
            finally:
                os.close(out)
    finally:
        os.unlink(tmp)
    _fsync_dir(path.parent)
    logger.info("integrations: generated fresh Fernet key at %s", path)
    return key


def _load_or_create(path: Path) -> bytes:
    if path.exists():
        key = _read_key(path)
        if key:
            # Validate by constructing a Fernet — raises ValueError if malformed.
            Fernet(key)
            return key
        # An empty key file is what a power cut or a full disk during its
        # first creation left behind. It holds no key, so nothing it could
        # decrypt is lost: set it aside and create a new key, instead of
        # failing every integration until the file is deleted by hand.
        aside = path.with_name(path.name + ".empty")
        try:
            os.replace(path, aside)
        except FileNotFoundError:
            pass  # another process set it aside first
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure — logs a file path only, never a key
        logger.error(
            "integrations: key file %s was empty — moved to %s and a new key "
            "generated; re-enter any integration credentials saved before",
            path, aside.name,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return _create_key_file(path)


@lru_cache(maxsize=1)
def _key() -> bytes:
    return _load_or_create(Path(settings.integration_key_path))


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Return the process-wide Fernet for integration-secret encryption.

    Memoised — the key file is read once per process. Tests that swap the
    `integration_key_path` setting must call `reset_fernet_cache()` first.
    """
    return Fernet(_key())


def preview_key() -> bytes:
    """The key that fingerprints secret previews in API responses: derived
    from this Pi's integration key, so a preview can only be computed (or
    checked against a guess) on this Pi."""
    return hmac.new(_key(), _PREVIEW_KEY_LABEL, hashlib.sha256).digest()


def reset_fernet_cache() -> None:
    """Clear the memoised key and Fernet — only used in tests."""
    _key.cache_clear()
    get_fernet.cache_clear()
