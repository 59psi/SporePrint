"""Security floors for server dependencies (pyproject.toml + uv.lock).

The Docker image installs exactly what uv.lock pins (server/Dockerfile), so the
lock is what ships; pyproject floors stop any other resolver (a bare-metal
`pip install .`, a future `uv lock`) from picking a known-vulnerable release.
If a test here fails in your local venv, re-sync it: `uv sync --extra dev`.
"""

import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packaging.requirements import Requirement
from packaging.version import Version

from app.auth import ApiKeyMiddleware
from app.config import settings

SERVER_DIR = Path(__file__).resolve().parents[1]

# dist -> (lowest fixed version, one known-vulnerable version it must exclude)
SECURITY_FLOORS = {
    "starlette": ("1.3.1", "1.0.0"),         # GHSA-86qp-5c8j-p5mr Host-header path poisoning, form-limit DoS
    "python-multipart": ("0.0.31", "0.0.26"),  # part-header / querystring DoS, param smuggling
    "python-socketio": ("5.16.2", "5.16.1"),   # binary attachment accumulation DoS
    "python-engineio": ("4.13.2", "4.13.1"),   # unbounded thread allocation / payload-size DoS
    "anyio": ("4.14.2", "4.13.0"),             # TLS IDNA host-name spoofing
    "pydantic-settings": ("2.14.2", "2.13.1"),  # secrets_dir symlink escape
    "pillow": ("12.3.0", "11.3.0"),            # PSD / paste / ImageCms OOB writes
    "cryptography": ("50.0.1", "45.0.7"),      # bundled-OpenSSL + 46.x–50.x advisories
}


def _declared() -> dict[str, Requirement]:
    data = tomllib.loads((SERVER_DIR / "pyproject.toml").read_text())
    reqs = [Requirement(r) for r in data["project"]["dependencies"]]
    return {r.name.lower(): r for r in reqs}


def _locked() -> dict[str, list[str]]:
    data = tomllib.loads((SERVER_DIR / "uv.lock").read_text())
    out: dict[str, list[str]] = {}
    for pkg in data["package"]:
        out.setdefault(pkg["name"].lower(), []).append(pkg["version"])
    return out


@pytest.mark.parametrize("dist", sorted(SECURITY_FLOORS))
def test_pyproject_floor_excludes_vulnerable_release(dist):
    fixed, vulnerable = SECURITY_FLOORS[dist]
    req = _declared().get(dist)
    assert req is not None, f"{dist} must be declared with a security floor"
    assert not req.specifier.contains(vulnerable), f"{req} still admits {vulnerable}"
    assert req.specifier.contains(fixed), f"{req} excludes the fixed {fixed}"


@pytest.mark.parametrize("dist", sorted(SECURITY_FLOORS))
def test_lock_pins_are_at_or_above_floor(dist):
    fixed, _ = SECURITY_FLOORS[dist]
    versions = _locked().get(dist)
    assert versions, f"{dist} missing from uv.lock"
    for v in versions:
        assert Version(v) >= Version(fixed), f"uv.lock pins {dist} {v} < {fixed}"


def test_lock_is_current_with_pyproject_caps():
    # Every direct requirement is satisfiable by what the lock pins, i.e. the
    # lock was regenerated after the last pyproject.toml edit.
    locked = _locked()
    for name, req in _declared().items():
        versions = locked.get(name)
        assert versions, f"{name} declared but not locked"
        assert any(req.specifier.contains(v) for v in versions), (
            f"uv.lock {name} {versions} does not satisfy {req} — run `uv lock`")


def test_crafted_host_header_cannot_skip_the_api_key_gate(monkeypatch):
    """Starlette < 1.0.1 built request.url from the raw Host header, so
    `Host: x/api/health?` made request.url.path read `/api/health` (a public
    path) while the router still dispatched the protected endpoint."""
    monkeypatch.setattr(settings, "api_key", "s3cret")
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.post("/api/hardware/nodes/{node_id}/command")
    async def command(node_id: str):
        return {"status": "sent"}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/hardware/nodes/relay-01/command",
                    headers={"host": "x/api/health?"})
    assert r.status_code != 200
    assert r.json() != {"status": "sent"}
