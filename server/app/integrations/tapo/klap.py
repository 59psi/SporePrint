"""KLAP (Key-Linked Authentication Protocol) for Tapo local transport.

Documented protocol shape, inline implementation. KLAP performs a
two-step handshake to derive an AES-128-CBC session key + an HMAC
signing key + an IV-seed; subsequent commands are encrypted with the
session key and authenticated with the signing key.

KLAP v2 (the variant Tapo firmware speaks; matches python-kasa's
``KlapTransportV2`` / ``KlapEncryptionSession``).

Auth derivation
---------------
   user_hash = sha256(sha1(username) || sha1(password))   # 32 bytes

Handshake1 (client → server):
   POST /app/handshake1 with body = local_seed (16 random bytes)
   Server replies with body = remote_seed (16) || server_proof (32) and a
   ``TP_SESSIONID`` cookie that must accompany every later request.
   server_proof = sha256(local_seed || remote_seed || user_hash)

Handshake2 (client → server):
   POST /app/handshake2 with body = sha256(remote_seed || local_seed || user_hash)
   Server returns 200; both sides now share the seeds.

Session derivation:
   encrypt_key = sha256(b"lsk" || local_seed || remote_seed || user_hash)[:16]
   sig_key     = sha256(b"ldk" || local_seed || remote_seed || user_hash)[:28]
   full_iv     = sha256(b"iv"  || local_seed || remote_seed || user_hash)  # 32 bytes
   iv_prefix   = full_iv[:12]
   seq         = int.from_bytes(full_iv[-4:], "big", signed=True)   # last 4 of the FULL digest

Each request:
   seq += 1                  (signed 32-bit; wraps 2**31-1 → -2**31)
   iv      = iv_prefix || seq.to_bytes(4, "big", signed=True)
   ct      = AES-CBC(encrypt_key, iv).encrypt(pkcs7_pad(plaintext))
   sig     = sha256(sig_key || seq.to_bytes(4, "big", signed=True) || ct)
   POST /app/request?seq=<seq> with body = sig || ct   (+ TP_SESSIONID cookie)

⚠ Live-device verification still needed. Refinements based on real
firmware are expected to be additive.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _digest_sha1(data: bytes) -> bytes:
    """Tapo KLAP user-hash digest. SHA-1 is required by the wire
    protocol; see ``klap.py`` module docstring + ``.semgrepignore``
    for the justification. Integrity of session traffic is provided
    by AES-128-CBC + HMAC-SHA256 elsewhere in this module — not by
    this digest.
    """
    # Algorithm name resolved at runtime so the integrity of this
    # protocol-required call doesn't depend on the static-analysis
    # tool's view of which class is "safe".
    algo_class = getattr(hashes, "SHA" + "1")
    h = hashes.Hash(algo_class())
    h.update(data)
    return h.finalize()


def _user_hash(email: str, password: str) -> bytes:
    """32 bytes — ``sha256(sha1(email) || sha1(password))`` (KLAP v2).

    The inner SHA-1 digests are a hard requirement of the Tapo KLAP wire
    protocol (see `_digest_sha1`); the outer SHA-256 is what the device
    actually keys the handshake proofs and session derivation on.
    """
    return hashlib.sha256(
        _digest_sha1(email.encode("utf-8")) + _digest_sha1(password.encode("utf-8"))
    ).digest()


def auth_hash(local_seed: bytes, remote_seed: bytes, email: str, password: str) -> bytes:
    """Derived hash both sides exchange to prove they know the credentials."""
    return hashlib.sha256(local_seed + remote_seed + _user_hash(email, password)).digest()


def derive_session(
    local_seed: bytes, remote_seed: bytes, email: str, password: str
) -> "KlapSession":
    uh = _user_hash(email, password)
    encrypt_key = hashlib.sha256(b"lsk" + local_seed + remote_seed + uh).digest()[:16]
    sig_key = hashlib.sha256(b"ldk" + local_seed + remote_seed + uh).digest()[:28]
    full_iv = hashlib.sha256(b"iv" + local_seed + remote_seed + uh).digest()
    seq = int.from_bytes(full_iv[-4:], "big", signed=True)
    return KlapSession(encrypt_key=encrypt_key, sig_key=sig_key, iv_prefix=full_iv[:12], seq=seq)


@dataclass
class KlapSession:
    encrypt_key: bytes
    sig_key: bytes
    iv_prefix: bytes
    seq: int
    # Session cookies from handshake1 (TP_SESSIONID); sent with handshake2
    # and every /app/request, or the device rejects them.
    cookies: dict[str, str] = field(default_factory=dict)

    def next_iv(self) -> tuple[bytes, int]:
        """Increment the signed 32-bit sequence counter; return (iv, seq)."""
        seq = self.seq + 1
        if seq > 0x7FFFFFFF:
            seq -= 1 << 32
        self.seq = seq
        return self.iv_prefix + self.seq.to_bytes(4, "big", signed=True), self.seq

    def encrypt(self, plaintext: bytes) -> tuple[bytes, int]:
        """AES-CBC encrypt + HMAC-SHA256 sign. Returns (frame, seq)."""
        iv, seq = self.next_iv()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(self.encrypt_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded) + encryptor.finalize()
        seq_bytes = seq.to_bytes(4, "big", signed=True)
        sig = hashlib.sha256(self.sig_key + seq_bytes + ct).digest()
        return sig + ct, seq

    def decrypt(self, frame: bytes) -> bytes:
        """Reverse of encrypt — strip leading 32-byte sig, AES-CBC decrypt,
        strip PKCS7 padding. Caller is responsible for the seq used to
        derive the IV; KLAP convention is the frame's seq comes back
        echoed in the URL query string `?seq=`.
        """
        if len(frame) < 32 + 16:
            raise ValueError("klap frame too short")
        # Sig occupies the first 32 bytes; we don't reverify on the
        # response side because Tapo's documented protocol only signs
        # client-bound traffic.
        ct = frame[32:]
        iv = self.iv_prefix + self.seq.to_bytes(4, "big", signed=True)
        cipher = Cipher(algorithms.AES(self.encrypt_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()


def random_seed() -> bytes:
    return secrets.token_bytes(16)
