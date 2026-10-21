"""The integration key file is created durably, and an empty one is recovered.

The key used to be written with no fsync after its name was created, so a
power cut (or a full disk) during first use could leave an empty file.
Fernet(b"") then raised on every load: every integrations listing and save
was a 500, and every secret-bearing driver stayed down, until the file was
deleted by hand.
"""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.integrations import _keystore, _registry
from app.integrations import _settings_store as store
from app.integrations._keystore import reset_fernet_cache


@pytest.fixture
def key_path(tmp_path, monkeypatch):
    path = tmp_path / "db" / ".integration-key"
    monkeypatch.setattr(settings, "integration_key_path", str(path))
    reset_fernet_cache()
    yield path
    reset_fernet_cache()


def test_first_use_writes_a_complete_private_key_and_no_temp_file(key_path):
    _keystore.get_fernet()
    key = key_path.read_bytes()
    Fernet(key)  # a complete, valid key
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in key_path.parent.iterdir()] == [".integration-key"]


def test_an_existing_key_is_reused(key_path):
    key_path.parent.mkdir(parents=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key + b"\n")
    assert _keystore.get_fernet().decrypt(Fernet(key).encrypt(b"x")) == b"x"


@pytest.mark.parametrize("content", [b"", b"  \n"])
async def test_an_empty_key_file_is_set_aside_and_replaced(key_path, content):
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(content)

    fernet = _keystore.get_fernet()  # used to raise on every call
    assert fernet.decrypt(fernet.encrypt(b"x")) == b"x"
    Fernet(key_path.read_bytes())
    assert (key_path.parent / ".integration-key.empty").exists()
    # The integrations page loads again.
    assert isinstance(await _registry.list_integrations(), list)
    await store.save("grafana", False, {"bearer_token": "t-1"}, {"bearer_token"})


def test_a_concurrent_creator_keeps_the_key_that_won(key_path, monkeypatch):
    # Another process creates the key between our write and our link: link()
    # refuses the existing name and we use the winner's key, not a second one.
    key_path.parent.mkdir(parents=True)
    winner = Fernet.generate_key()
    real_link = os.link

    def racing_link(src, dst):
        with open(dst, "xb") as f:
            f.write(winner)
        return real_link(src, dst)

    monkeypatch.setattr(_keystore.os, "link", racing_link)
    assert _keystore._key() == winner
    assert [p.name for p in key_path.parent.iterdir()] == [".integration-key"]


@pytest.mark.parametrize("racing", [False, True], ids=["alone", "another-process-wins"])
def test_a_filesystem_without_hard_links_still_gets_one_key(key_path, monkeypatch, racing):
    # Without link() the name is claimed with an exclusive create; a process
    # that created it first keeps its key, the same as on a filesystem with
    # hard links.
    key_path.parent.mkdir(parents=True)
    winner = Fernet.generate_key()

    def no_links(src, dst):
        if racing:
            with open(dst, "xb") as f:
                f.write(winner)
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(_keystore.os, "link", no_links)
    key = _keystore._key()
    Fernet(key)
    assert key_path.read_bytes() == key
    if racing:
        assert key == winner
    assert [p.name for p in key_path.parent.iterdir()] == [".integration-key"]
