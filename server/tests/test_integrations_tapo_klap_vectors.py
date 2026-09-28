"""Tapo KLAP (v2) wire-derivation known-answer tests.

The previous implementation was only self-consistent: it derived the auth
hash as sha1(user)||sha1(pass) (40 bytes, no outer SHA-256), took the
sequence number from the TRUNCATED iv digest, masked the counter to 31 bits,
and dropped the TP_SESSIONID cookie between handshake1, handshake2 and the
encrypted requests — so no real device could ever authenticate.

The reference below is written independently from the KLAP v2 transport
used by python-kasa (``KlapTransportV2`` / ``KlapEncryptionSession``):

    auth_hash   = sha256(sha1(username) + sha1(password))
    handshake1  = sha256(local_seed + remote_seed + auth_hash)   (server proof)
    handshake2  = sha256(remote_seed + local_seed + auth_hash)   (client proof)
    key         = sha256(b"lsk" + local + remote + auth_hash)[:16]
    sig         = sha256(b"ldk" + local + remote + auth_hash)[:28]
    fulliv      = sha256(b"iv"  + local + remote + auth_hash)
    iv_prefix   = fulliv[:12];  seq = int(fulliv[-4:], big, signed)
    per request: seq += 1 ; iv = iv_prefix + seq(4, big, signed)
                 frame = sha256(sig + seq + ct) + ct
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.integrations.tapo import klap
from app.integrations.tapo.config import TapoConfig
from app.integrations.tapo.driver import TapoDriver


EMAIL = "user@example.com"
PASSWORD = "hunter2"
LOCAL = bytes(range(16))
REMOTE = bytes(range(16, 32))


def _sha1(b: bytes) -> bytes:
    return hashlib.new("sha1", b).digest()


def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


REF_AUTH = _sha256(_sha1(EMAIL.encode()) + _sha1(PASSWORD.encode()))


def _ref_session():
    key = _sha256(b"lsk" + LOCAL + REMOTE + REF_AUTH)[:16]
    sig = _sha256(b"ldk" + LOCAL + REMOTE + REF_AUTH)[:28]
    full = _sha256(b"iv" + LOCAL + REMOTE + REF_AUTH)
    return key, sig, full[:12], int.from_bytes(full[-4:], "big", signed=True)


def test_handshake_hashes_match_klap_v2_reference():
    assert klap.auth_hash(LOCAL, REMOTE, EMAIL, PASSWORD) == _sha256(LOCAL + REMOTE + REF_AUTH)
    assert klap.auth_hash(REMOTE, LOCAL, EMAIL, PASSWORD) == _sha256(REMOTE + LOCAL + REF_AUTH)


def test_session_derivation_matches_reference():
    key, sig, iv_prefix, seq = _ref_session()
    s = klap.derive_session(LOCAL, REMOTE, EMAIL, PASSWORD)
    assert s.encrypt_key == key
    assert s.sig_key == sig
    assert s.iv_prefix == iv_prefix
    assert s.seq == seq


def test_encrypted_frame_matches_reference():
    key, sig, iv_prefix, seq = _ref_session()
    plaintext = b'{"method":"get_device_info"}'
    s = klap.derive_session(LOCAL, REMOTE, EMAIL, PASSWORD)
    frame, sent_seq = s.encrypt(plaintext)

    seq += 1
    assert sent_seq == seq
    iv = iv_prefix + seq.to_bytes(4, "big", signed=True)
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(padder.update(plaintext) + padder.finalize()) + enc.finalize()
    assert frame == _sha256(sig + seq.to_bytes(4, "big", signed=True) + ct) + ct


def test_negative_sequence_increments_without_masking():
    s = klap.derive_session(LOCAL, REMOTE, EMAIL, PASSWORD)
    s.seq = -5
    _, seq = s.encrypt(b"x")
    assert seq == -4


def test_sequence_wraps_within_signed_32_bits():
    s = klap.derive_session(LOCAL, REMOTE, EMAIL, PASSWORD)
    s.seq = 2**31 - 1
    _, seq = s.encrypt(b"x")
    assert seq == -(2**31)


async def test_session_cookie_is_carried_through_handshake_and_requests(monkeypatch):
    """handshake1 sets TP_SESSIONID; handshake2 and every /app/request must
    present it, and the response must decrypt with the same session."""
    seen_cookies: dict[str, str | None] = {}
    state: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        cookie = request.headers.get("cookie")
        seen_cookies[path] = cookie
        if path == "/app/handshake1":
            local = request.content
            state["local"] = local
            server_proof = _sha256(local + REMOTE + REF_AUTH)
            return httpx.Response(
                200,
                content=REMOTE + server_proof,
                headers={"Set-Cookie": "TP_SESSIONID=abc123;TIMEOUT=86400"},
            )
        if path == "/app/handshake2":
            assert request.content == _sha256(REMOTE + state["local"] + REF_AUTH)
            return httpx.Response(200)
        if path == "/app/request":
            session = klap.derive_session(state["local"], REMOTE, EMAIL, PASSWORD)
            session.seq = int(request.url.params["seq"])
            body = json.dumps({"error_code": 0, "result": {"device_on": True}}).encode()
            # Server response is encrypted with the request's seq IV.
            iv = session.iv_prefix + session.seq.to_bytes(4, "big", signed=True)
            padder = padding.PKCS7(128).padder()
            enc = Cipher(algorithms.AES(session.encrypt_key), modes.CBC(iv)).encryptor()
            ct = enc.update(padder.update(body) + padder.finalize()) + enc.finalize()
            return httpx.Response(200, content=b"\x00" * 32 + ct)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    drv = TapoDriver()
    await drv.configure(TapoConfig(email=EMAIL, password=PASSWORD,
                                   devices=[{"ip": "10.0.0.30"}]))
    result = await drv._klap_call(drv.config, "10.0.0.30", {"method": "get_device_info"})
    assert result["result"]["device_on"] is True
    assert seen_cookies["/app/handshake1"] is None
    assert "TP_SESSIONID=abc123" in (seen_cookies["/app/handshake2"] or "")
    assert "TP_SESSIONID=abc123" in (seen_cookies["/app/request"] or "")


async def test_wrong_password_fails_handshake1(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        server_proof = _sha256(request.content + REMOTE + REF_AUTH)
        return httpx.Response(200, content=REMOTE + server_proof)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real_client(*a, **{**k, "transport": transport})
    )
    drv = TapoDriver()
    await drv.configure(TapoConfig(email=EMAIL, password="wrong",
                                   devices=[{"ip": "10.0.0.30"}]))
    with pytest.raises(Exception, match="auth_hash mismatch"):
        await drv._klap_handshake(drv.config, "10.0.0.30")
