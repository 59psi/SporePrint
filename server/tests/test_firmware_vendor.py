"""Vendored third-party firmware code (firmware/lib/sp_core/vendor/).

Monocypher verifies the Ed25519 signature on node OTA manifests, so the copy
must stay byte-identical to the upstream release its README pins (version,
tarball checksums, per-file SHA-256). These tests hold the tree to that
table — a reformat, a stray edit or a half-done upgrade fails here — and
check that every firmware ZIP the Builder serves ships the sources with
their licence (BSD-2-Clause clause 1: source redistributions keep it).
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.builder import models_router as mr

_REPO_FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"
VENDOR = _REPO_FIRMWARE / "lib" / "sp_core" / "vendor" / "monocypher"
README = (VENDOR / "README.md").read_text()
SOURCES = ("monocypher.c", "monocypher.h", "monocypher-ed25519.c", "monocypher-ed25519.h")
# README rows: | `monocypher.c` | `<sha256>` |
_PINNED = dict(re.findall(r"^\| `([^`/]+)` \| `([0-9a-f]{64})` \|$", README, re.M))


def test_readme_pins_every_vendored_file():
    assert set(_PINNED) == {*SOURCES, "LICENCE.md"}


@pytest.mark.parametrize("name", sorted({*SOURCES, "LICENCE.md"}))
def test_vendored_file_matches_the_pinned_release_hash(name):
    data = (VENDOR / name).read_bytes()
    assert b"\r" not in data, f"{name}: CRLF — the release files are LF"
    assert hashlib.sha256(data).hexdigest() == _PINNED[name], (
        f"{name} differs from the Monocypher release the README pins; "
        "vendored files are never edited — upgrade them as the README says")


def test_vendor_dir_holds_only_the_release_files():
    present = {p.name for p in VENDOR.iterdir()}
    assert present == {*SOURCES, "LICENCE.md", "README.md", ".gitattributes"}


def test_sources_carry_the_version_the_readme_names():
    version = re.search(r"^# Monocypher (\d+\.\d+\.\d+) \(vendored\)$", README, re.M)
    assert version, "README heading must name the vendored version"
    for name in SOURCES:
        first = (VENDOR / name).read_text().splitlines()[0]
        assert first == f"// Monocypher version {version.group(1)}", name
    assert f"monocypher-{version.group(1)}.tar.gz" in README


def test_licence_is_the_complete_dual_licence():
    text = (VENDOR / "LICENCE.md").read_text()
    for must in (
        "Licence 1 (2-clause BSD)",
        "Copyright (c) 2017-2023, Loup Vaillant",
        "Redistributions of source code must retain the above copyright",
        "Redistributions in binary form must reproduce the above copyright",
        'THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS\n"AS IS"',
        "Licence 2 (CC-0)",
        "### Statement of Purpose",
        "4. **Limitations and Disclaimers.**",
    ):
        assert must in text, must


# ── Builder firmware ZIPs ──────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    assert _REPO_FIRMWARE.is_dir(), _REPO_FIRMWARE
    monkeypatch.setattr(mr, "_FIRMWARE_DIR", _REPO_FIRMWARE)
    monkeypatch.setattr(mr, "_firmware_cache", {"data": [], "ts": 0})
    app = FastAPI()
    app.include_router(mr.router, prefix="/api/builder")
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("node", ["node", "cam", "sp_core", "full"])
def test_bundles_ship_monocypher_with_its_licence(api, node):
    r = api.get(f"/api/builder/firmware/bundle/{node}")
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    for name in (*SOURCES, "LICENCE.md", "README.md"):
        arc = f"firmware/lib/sp_core/vendor/monocypher/{name}"
        assert zf.read(arc) == (VENDOR / name).read_bytes(), arc
