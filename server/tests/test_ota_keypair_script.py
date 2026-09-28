"""scripts/generate-ota-keypair.py must never leave the fleet-wide OTA
signing key readable by other users — not even for the instant between
writing it and chmod-ing it, and not when --out names an existing,
world-readable directory."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate-ota-keypair.py"


@pytest.fixture()
def keypair_mod():
    spec = importlib.util.spec_from_file_location("generate_ota_keypair", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def umask_022():
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_private_key_is_created_0600_not_chmod_after_the_fact(
        keypair_mod, umask_022, tmp_path, monkeypatch):
    """With chmod unavailable/failing, the old write_text-then-chmod left the
    key at the umask default (0644). Creating it 0600 closes both the race
    and the permanent-exposure case."""
    monkeypatch.setattr(keypair_mod.os, "chmod", lambda *a, **k: None)
    out = tmp_path / "ota"
    keypair_mod._write_keys(out, "PRIVATEKEYB64", "PUBLICKEYB64")
    priv = out / "ota-signing.key"
    assert priv.read_text().strip() == "PRIVATEKEYB64"
    assert _mode(priv) == 0o600


def test_existing_world_readable_out_dir_is_locked_down(
        keypair_mod, umask_022, tmp_path):
    out = tmp_path / "shared"
    out.mkdir(mode=0o755)
    os.chmod(out, 0o755)
    keypair_mod._write_keys(out, "PRIVATEKEYB64", "PUBLICKEYB64")
    assert _mode(out) == 0o700
    assert _mode(out / "ota-signing.key") == 0o600
    assert (out / "ota-verify.pub").read_text().strip() == "PUBLICKEYB64"


def test_refuses_a_non_empty_out_dir(keypair_mod, tmp_path):
    out = tmp_path / "keys"
    out.mkdir()
    (out / "ota-signing.key").write_text("production key\n")
    with pytest.raises(SystemExit):
        keypair_mod._write_keys(out, "NEW", "NEWPUB")
    assert (out / "ota-signing.key").read_text() == "production key\n"
