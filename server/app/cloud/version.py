"""The running Pi server's version, for the cloud contract.

Reported in the pairing handshake (``/api/cloud/pair`` → ``firmware_version``)
and used by the OTA downgrade guard. Resolution order: installed package
metadata (the Docker image ``pip install``s the server), then the
``pyproject.toml`` shipped next to the ``app`` package (source checkouts),
then ``"unknown"``.
"""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

_PACKAGE = "sporeprint-server"
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
_TRIPLE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@lru_cache(maxsize=1)
def server_version() -> str:
    try:
        return _pkg_version(_PACKAGE)
    except PackageNotFoundError:
        pass
    try:
        data = tomllib.loads(_PYPROJECT.read_text())
        v = data.get("project", {}).get("version")
        if isinstance(v, str) and v:
            return v
    except (OSError, ValueError):
        pass
    return "unknown"


def version_triple(value: str) -> tuple[int, int, int] | None:
    """``"v5.0.1-beta.2"`` → ``(5, 0, 1)``; None when unparseable."""
    m = _TRIPLE_RE.match(value or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))
