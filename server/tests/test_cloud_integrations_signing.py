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

import time

import pytest

import app.cloud.service as service
from app.cloud import integrations_proxy
from app.cloud.service import handle_cloud_command
from app.config import settings
from app.integrations import _registry
from tests._fakes import RecordingSio
from tests._signing import sign

_KEY = "unit-test-cloud-token"


def _frame(req_id, action: str = "list", **extra) -> dict:
    return {"id": req_id, "action": action, "ts": time.time(), **extra}


def _signed(req_id, key: str = _KEY, **extra) -> dict:
    return sign(_frame(req_id, **extra), key)


@pytest.fixture(autouse=True)
def dispatched(monkeypatch):
    """The registry calls the gate let through."""
    monkeypatch.setattr(service.settings, "cloud_token", _KEY)
    calls: list[str] = []

    async def fake_list():
        calls.append("list")
        return [{"slug": "grafana"}]

    monkeypatch.setattr(_registry, "list_integrations", fake_list)
    return calls


@pytest.fixture
def lax(monkeypatch):
    """Strict mode off: the old migration posture (latch only)."""
    monkeypatch.setattr(settings, "cloud_require_signed_integrations", False)


async def _send(frame) -> dict:
    sio = RecordingSio()
    await integrations_proxy.handle_request(sio, frame)
    assert len(sio.events) == 1, sio.events
    return sio.last("integrations_response")


async def test_a_valid_signed_frame_dispatches_and_latches_signing_on(dispatched):
    """The latch lives in the DB so a Pi restart doesn't reopen the window."""
    resp = await _send(_signed("s1"))
    assert resp == {"id": "s1", "success": True, "body": [{"slug": "grafana"}]}
    assert dispatched == ["list"]
    assert await integrations_proxy._signed_frames_seen() is True


async def test_unsigned_frame_rejected_by_default_on_a_fresh_pi(dispatched):
    """No signed frame seen yet, no setting touched: an unsigned
    automation_create (actuation) is still refused."""
    resp = await _send({
        "id": "u0", "action": "automation_create",
        "payload": {"rule": {"name": "x", "condition": {"type": "threshold"},
                             "action": {"target": "relay-01"}}},
    })
    assert (resp["success"], resp["status"]) == (False, 401)
    assert await integrations_proxy._signed_frames_seen() is False


async def test_unsigned_frame_accepted_before_cloud_ever_signed_when_not_strict(dispatched, lax):
    assert (await _send({"id": "u1", "action": "list"}))["success"] is True
    assert dispatched == ["list"]


def _with(frame: dict, **fields) -> dict:
    return {**frame, **fields}


@pytest.mark.parametrize("frame", [
    lambda: _signed("bad-key", key="wrong"),
    # hmac.compare_digest raises TypeError on a non-ASCII str.
    lambda: _with(_signed("bad-sig"), signature="é" * 64),
    # float() of the ts overflows.
    lambda: _with(_signed("bad-ts"), ts=10 ** 400),
], ids=["wrong-key", "non-ascii-signature", "overflowing-ts"])
async def test_a_signed_frame_that_does_not_verify_gets_one_401_and_no_dispatch(dispatched, frame):
    resp = await _send(frame())
    assert (resp["success"], resp["status"]) == (False, 401)
    assert dispatched == []


async def test_signed_frame_without_signing_key_is_not_dispatched(monkeypatch, dispatched):
    """A signature we cannot check must fail closed, not be skipped."""
    frame = _signed("s3")
    monkeypatch.setattr(service.settings, "cloud_token", "")
    resp = await _send(frame)
    assert (resp["success"], resp["status"]) == (False, 401)
    assert dispatched == []


async def test_a_signed_frame_whose_id_is_not_a_string_is_refused(dispatched):
    resp = await _send(_signed(42))
    assert (resp["success"], resp["status"], resp["error"]) == (False, 400, "invalid request id")
    assert dispatched == []


async def test_signed_frame_replay_rejected(dispatched):
    frame = _signed("s4")
    assert (await _send(frame))["success"] is True
    replay = await _send(frame)  # verbatim
    assert (replay["success"], replay["status"]) == (False, 409)
    assert "replay" in replay["error"].lower()
    assert dispatched == ["list"], "a replayed frame must not dispatch twice"


async def test_command_and_integrations_ids_are_deduped_apart_through_one_gate(
        dispatched, mock_mqtt):
    """The same value used as a command id and as an integrations request id
    is two different keys of the one replay gate (claim_replay_id): neither
    channel's use of it blocks the other, and a replay of either is refused."""
    sio = RecordingSio()
    cmd = sign({"id": "same-id", "tier": "premium", "target_kind": "system",
                "channel": "automation", "payload": {"paused": False}, "ts": time.time()}, _KEY)
    await handle_cloud_command(sio, cmd)
    assert sio.last("command_result")["success"] is True

    assert (await _send(_signed("same-id")))["success"] is True

    await handle_cloud_command(sio, cmd)
    assert sio.last("command_result") == {
        "id": "same-id", "success": False, "error": "Replayed command id"}
    assert (await _send(_signed("same-id")))["status"] == 409


async def test_unsigned_frame_rejected_after_a_signed_one_was_seen(dispatched, lax):
    assert (await _send(_signed("s5")))["success"] is True
    # An attacker strips the signature (or injects an unsigned frame).
    resp = await _send({"id": "evil", "action": "vendor_action", "slug": "kasa",
                        "payload": {"action": "set_power", "ip": "10.0.0.20", "on": True}})
    assert (resp["success"], resp["status"]) == (False, 401)
    assert "unsigned" in resp["error"].lower()
    assert dispatched == ["list"]


async def test_repairing_resets_the_latch(dispatched, lax):
    await _send(_signed("s7"))
    assert await integrations_proxy._signed_frames_seen() is True
    await integrations_proxy.reset_signing_latch()
    assert await integrations_proxy._signed_frames_seen() is False
    assert (await _send({"id": "u3", "action": "list"}))["success"] is True
