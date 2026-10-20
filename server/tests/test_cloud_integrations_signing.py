"""Signature + replay gate on cloud ``integrations_request`` frames.

The integrations RPC channel reaches vendor actuation (``vendor_action``),
automation-rule CRUD and integration host rewrites (``put_config``), so it
must not be weaker than the command channel:

* a signed frame is verified and its id is replay-deduped (namespaced so it
  can never collide with a command id);
* a frame carrying a ``signature`` is never dispatched unverified, even when
  no signing key is configured, and a signature or ts the check cannot even
  evaluate is answered with 401 (the cloud must not wait out its timeout);
* an unsigned frame is rejected by default (strict mode: the cloud signs
  every frame). With strict mode turned off, unsigned frames are accepted
  UNTIL this Pi has seen a validly signed integrations_request (proof the
  cloud signs this channel), after which an unsigned frame is a downgrade and
  is rejected. The latch is persisted so a restart does not re-open the
  window.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

import app.cloud.service as service
from app.cloud import integrations_proxy
from app.cloud.service import claim_replay_id, handle_cloud_command
from app.config import settings
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


@pytest.fixture
def lax(monkeypatch):
    """Strict mode off: the old migration posture (latch only)."""
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)


async def test_unsigned_frame_rejected_by_default_on_a_fresh_pi(_cloud_env):
    """No signed frame seen yet, no setting touched: an unsigned
    automation_create (actuation) is still refused."""
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, {
        "id": "u0", "action": "automation_create",
        "payload": {"rule": {"name": "x", "condition": {"type": "threshold"},
                             "action": {"target": "relay-01"}}},
    })
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert len(sio.emits) == 1
    assert await integrations_proxy._signed_frames_seen() is False


async def test_unsigned_frame_accepted_before_cloud_ever_signed_when_not_strict(_cloud_env, lax):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, {"id": "u1", "action": "list"})
    assert sio.last()["success"] is True
    assert _cloud_env == ["list"]


@pytest.mark.parametrize("field,value", [
    ("signature", "é" * 64),        # hmac.compare_digest raises TypeError
    ("ts", 10 ** 400),              # float() of the ts overflows
])
async def test_an_unevaluable_frame_gets_one_401(_cloud_env, field, value):
    sio = _FakeSio()
    frame = _sign(_frame("bad-1"))
    frame[field] = value
    await integrations_proxy.handle_request(sio, frame)
    assert len(sio.emits) == 1, sio.emits
    resp = sio.last()
    assert resp["success"] is False
    assert resp["status"] == 401
    assert _cloud_env == []


async def test_command_and_integrations_ids_share_one_replay_gate(_cloud_env, mock_mqtt):
    """The same value used as a command id and as an integrations request id
    is two different keys; a replay of either is refused through the one
    helper (claim_replay_id)."""
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("same-id")))
    assert sio.last()["success"] is True
    # The command channel's own copy of the id is still free...
    assert await claim_replay_id("same-id") is True
    # ...and now taken, as is the integrations one.
    assert await claim_replay_id("same-id") is False
    assert await claim_replay_id("integrations:same-id") is False

    cmd = _sign({"id": "same-id", "tier": "premium", "target_kind": "system",
                 "channel": "automation", "payload": {"paused": False}, "ts": time.time()})
    await handle_cloud_command(sio, cmd)
    assert sio.emits[-1] == ("command_result", {
        "id": "same-id", "success": False, "error": "Replayed command id"})
    await integrations_proxy.handle_request(sio, _sign(_frame("same-id")))
    assert sio.last()["status"] == 409


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


async def test_unsigned_frame_rejected_after_a_signed_one_was_seen(_cloud_env, lax):
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


async def test_repairing_resets_the_latch(_cloud_env, lax):
    sio = _FakeSio()
    await integrations_proxy.handle_request(sio, _sign(_frame("s7")))
    assert await integrations_proxy._signed_frames_seen() is True
    await integrations_proxy.reset_signing_latch()
    assert await integrations_proxy._signed_frames_seen() is False
    await integrations_proxy.handle_request(sio, {"id": "u3", "action": "list"})
    assert sio.last()["success"] is True
