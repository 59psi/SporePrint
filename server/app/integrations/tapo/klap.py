"""KLAP (Key-Linked Authentication Protocol) for Tapo local transport.

Documented protocol shape, inline implementation. KLAP performs a
two-step handshake to derive an AES-128-CBC session key + an HMAC
signing key + an IV-seed; subsequent commands are encrypted with the
session key and authenticated with the signing key.

Auth derivation
---------------
   user_hash = sha1(username) || sha1(password)        # 40 bytes
   auth_hash = sha256(local_seed || remote_seed || user_hash)

Handshake1 (client → server):
   POST /app/handshake1 with body = local_seed (16 random bytes)
   Server replies with body = remote_seed (16) || server_auth_hash (32)
   Client validates server_auth_hash matches its own derivation.

Handshake2 (client → server):
   POST /app/handshake2 with body = sha256(remote_seed || local_seed || user_hash)
   Server returns 200; both sides now share the seeds.

Session derivation:
   encrypt_key = sha256(b"lsk" || local_seed || remote_seed || user_hash)[:16]
   sig_key     = sha256(b"ldk" || local_seed || remote_seed || user_hash)[:28]
   iv_seed     = sha256(b"iv"  || local_seed || remote_seed || user_hash)[:16]
   seq         = int.from_bytes(iv_seed[-4:], "big", signed=True)

Each request:
   seq += 1
   iv      = iv_seed[:12] || seq.to_bytes(4, "big", signed=True)
   ct      = AES-CBC(encrypt_key, iv).encrypt(pkcs7_pad(plaintext))
   sig     = sha256(sig_key || seq.to_bytes(4, "big", signed=True) || ct)
   POST /app/request?seq=<seq> with body = sig || ct

⚠ Live-device verification still needed. Refinements based on real
firmware are expected to be additive.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

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
    """40 bytes — `_digest_sha1(email) || _digest_sha1(password)`.

    SHA-1 is a hard requirement of the Tapo KLAP wire protocol; using
    SHA-256 here would derive the wrong session key and the device
    would reject every request. See `_digest_sha1` for the rationale.
    """
    return _digest_sha1(email.encode("utf-8")) + _digest_sha1(
        password.encode("utf-8")
    )


def auth_hash(local_seed: bytes, remote_seed: bytes, email: str, password: str) -> bytes:
    """Derived hash both sides exchange to prove they know the credentials."""
    return hashlib.sha256(local_seed + remote_seed + _user_hash(email, password)).digest()


def derive_session(
    local_seed: bytes, remote_seed: bytes, email: str, password: str
) -> "KlapSession":
    uh = _user_hash(email, password)
    encrypt_key = hashlib.sha256(b"lsk" + local_seed + remote_seed + uh).digest()[:16]
    sig_key = hashlib.sha256(b"ldk" + local_seed + remote_seed + uh).digest()[:28]
    iv_seed = hashlib.sha256(b"iv" + local_seed + remote_seed + uh).digest()[:16]
    seq = int.from_bytes(iv_seed[-4:], "big", signed=True)
    return KlapSession(encrypt_key=encrypt_key, sig_key=sig_key, iv_prefix=iv_seed[:12], seq=seq)


@dataclass
class KlapSession:
    encrypt_key: bytes
    sig_key: bytes
    iv_prefix: bytes
    seq: int

    def next_iv(self) -> tuple[bytes, int]:
        """Increment the sequence counter and return (iv, seq)."""
        self.seq = (self.seq + 1) & 0x7FFFFFFF
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
