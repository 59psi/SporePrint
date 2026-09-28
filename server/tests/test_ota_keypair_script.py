"""scripts/generate-ota-keypair.py must never leave the fleet-wide OTA
signing key readable by other users — not even for the instant between
writing it and chmod-ing it, and not when --out names an existing,
world-readable directory. Its instructions, and sign-ota-bundle.py's
signature format, must match what the Pi actually verifies."""

from __future__ import annotations

import base64
import importlib.util
import os
import stat
from pathlib import Path

import pytest

from app.cloud import ota
from app.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "generate-ota-keypair.py"
SIGN_SCRIPT = REPO_ROOT / "scripts" / "sign-ota-bundle.py"


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


def test_operator_instructions_match_the_shipped_install(keypair_mod, capsys, monkeypatch):
    """The key goes into Settings → OTA verify key (or the documented .env
    key). The old text sent operators to /opt/sporeprint/.env — a layout no
    installer creates — and never said that the Docker install refuses cloud
    self-update, so the key does nothing there."""
    monkeypatch.setattr(keypair_mod.sys, "argv", ["generate-ota-keypair.py"])
    assert keypair_mod.main() == 0
    out = capsys.readouterr().out
    text = out + (keypair_mod.__doc__ or "")
    assert "/opt/" not in text
    assert "Settings → OTA verify key" in out
    assert "SPOREPRINT_OTA_PUBKEY_B64" in out  # the key .env.example documents
    assert "Docker" in out and "install.sh" in out


def test_signed_bundle_verifies_with_the_pi_verifier(keypair_mod, tmp_path, monkeypatch):
    """sign-ota-bundle.py and cloud/ota.py must agree on the signature
    format (raw 64-byte Ed25519 over the bundle bytes)."""
    priv_raw, pub_raw = keypair_mod._gen_keypair()
    key_file = tmp_path / "ota-signing.key"
    key_file.write_text(base64.b64encode(priv_raw).decode() + "\n")
    bundle = tmp_path / "5.0.1.tar.gz"
    bundle.write_bytes(b"bundle bytes")

    spec = importlib.util.spec_from_file_location("sign_ota_bundle", SIGN_SCRIPT)
    signer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signer)
    monkeypatch.setattr(signer.sys, "argv",
                        ["sign-ota-bundle.py", "--bundle", str(bundle), "--private-key", str(key_file)])
    assert signer.main() == 0
    sig = Path(str(bundle) + ".sig")
    assert len(sig.read_bytes()) == 64

    monkeypatch.setattr(settings, "ota_pubkey_b64", base64.b64encode(pub_raw).decode())
    ota._verify_signature(bundle, sig)  # raises OTAError on mismatch
    bundle.write_bytes(b"tampered")
    with pytest.raises(ota.OTAError):
        ota._verify_signature(bundle, sig)


def test_sign_script_names_the_real_verifier_and_its_limits():
    doc = SIGN_SCRIPT.read_text()
    assert "/opt/" not in doc
    assert "server/app/cloud/ota.py" in doc
    assert (REPO_ROOT / "server" / "app" / "cloud" / "ota.py").exists()
    # The signature covers the bundle bytes only (srv-cloud-int#21): say so,
    # and that Docker Pis never self-update.
    assert "downgrade" in doc and "Docker" in doc


def test_refuses_a_non_empty_out_dir(keypair_mod, tmp_path):
    out = tmp_path / "keys"
    out.mkdir()
    (out / "ota-signing.key").write_text("production key\n")
    with pytest.raises(SystemExit):
        keypair_mod._write_keys(out, "NEW", "NEWPUB")
    assert (out / "ota-signing.key").read_text() == "production key\n"
