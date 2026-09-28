"""Signature + replay gate on cloud ``integrations_request`` frames.

The integrations RPC channel reaches vendor actuation (``vendor_action``),
automation-rule CRUD and integration host rewrites (``put_config``), so it
must not be weaker than the command channel:

* a signed frame is verified and its id is replay-deduped (namespaced so it
  can never collide with a command id);
* a frame carrying a ``signature`` is never dispatched unverified, even when
  no signing key is configured;
* unsigned frames stay accepted for backward compatibility with a cloud that
  has never signed them — UNTIL this Pi has seen a validly signed
  integrations_request (proof the cloud signs this channel), after which an
  unsigned frame is a downgrade and is rejected. The latch is persisted so a
  restart does not re-open the window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

import app.cloud.service as service
from app.cloud import integrations_proxy
from app.integrations import _registry


_KEY = "unit-test-cloud-token"


def _sign(frame: dict, key: str = _KEY) -> dict:
    filtered = {k: v for k, v in frame.items() if k != "signature"}
    body = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {**frame, "signature": sig}


def _frame(req_id: str, action: str = "list", **extra) -> dict:
    return {"id": req_id, "action": action, "ts": time.time(), **extra}


class _FakeSio:
    def __init__(self) -> None:
        self.emits: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.emits.append((event, data))

    def last(self) -> dict:
        event, data = self.emits[-1]
        assert event == "integrations_response"
        return data


@pytest.fixture(autouse=True)
def _cloud_env(monkeypatch):
    monkeypatch.setattr(service.settings, "cloud_token", _KEY)
    service._seen_command_ids.clear()
    calls: list[str] = []

    async def fake_list():
        calls.append("list")
        return [{"slug": "grafana"}]

    monkeypatch.setattr(_registry, "list_integrations", fake_list)
    yield calls
    service._seen_command_ids.clear()


async def test_unsigned_frame_still_accepted_before_cloud_ever_signed(_cloud_env):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, {"id": "u1", "action": "list"})
    assert sio.last()["success"] is True
    assert _cloud_env == ["list"]


async def test_valid_signed_frame_dispatches(_cloud_env):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s1")))
    assert sio.last()["success"] is True
    assert _cloud_env == ["list"]


async def test_bad_signature_rejected_and_not_dispatched(_cloud_env):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s2"), key="wrong"))
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert _cloud_env == []


async def test_signed_frame_without_signing_key_is_not_dispatched(monkeypatch, _cloud_env):
    """A signature we cannot check must fail closed, not be skipped."""
    frame = _sign(_frame("s3"))
    monkeypatch.setattr(service.settings, "cloud_token", "")
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, frame)
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert _cloud_env == []


async def test_signed_frame_replay_rejected(_cloud_env):
    sio = _FakeSio()
    frame = _sign(_frame("s4"))
    await integrations_proxy.handle_request(sio, frame)
    await integrations_proxy.handle_request(sio, frame)  # verbatim replay
    assert sio.emits[0][1]["success"] is True
    replay = sio.last()
    assert replay["success"] is False
    assert replay["status"] == 409
    assert "replay" in replay["error"].lower()
    assert _cloud_env == ["list"], "a replayed frame must not dispatch twice"


async def test_replay_namespace_does_not_collide_with_command_ids(_cloud_env):
    """A command id already seen must not block an integrations request with
    the same id (and vice versa) — the two channels dedup independently."""
    async with service._replay_lock:
        service._seen_command_ids["shared-id"] = None
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("shared-id")))
    assert sio.last()["success"] is True


async def test_unsigned_frame_rejected_after_a_signed_one_was_seen(_cloud_env):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s5")))
    assert sio.last()["success"] is True
    # An attacker strips the signature (or injects an unsigned frame).
    await integrations_proxy.handle_request(
        sio, {"id": "evil", "action": "vendor_action", "slug": "kasa",
              "payload": {"action": "set_power", "ip": "10.0.0.20", "on": True}},
    )
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert "unsigned" in resp["error"].lower()
    assert _cloud_env == ["list"]


async def test_signed_latch_is_persisted(_cloud_env):
    """The downgrade latch lives in the DB so a Pi restart doesn't reopen it."""
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s6")))
    assert await integrations_proxy._signed_frames_seen() is True


async def test_strict_setting_rejects_unsigned_even_without_latch(monkeypatch, _cloud_env):
    monkeypatch.setattr(integrations_proxy, "_require_signed_setting", lambda: True)
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, {"id": "u2", "action": "list"})
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert _cloud_env == []


async def test_repairing_resets_the_latch(_cloud_env):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s7")))
    assert await integrations_proxy._signed_frames_seen() is True
    await integrations_proxy.reset_signing_latch()
    assert await integrations_proxy._signed_frames_seen() is False
    await integrations_proxy.handle_request(sio, {"id": "u3", "action": "list"})
    assert sio.last()["success"] is True
