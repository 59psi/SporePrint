import re
import secrets
import time

from fastapi import APIRouter, HTTPException

from ..config import settings
from .integrations_proxy import reset_signing_latch
from .service import (
    apply_paired_credentials,
    cloud_url_transport_ok,
    get_cloud_status,
    request_reconnect,
    write_cloud_env,
)
from .version import server_version

router = APIRouter()

# In-memory pairing state: one pending code at a time per Pi.
_pairing_code: dict | None = None
_pairing_attempts = 0
_pairing_lockout_until: float = 0.0
_MAX_PAIRING_ATTEMPTS = 8

# Short-lived tokens issued to clients that just presented a valid pairing
# code. `/configure` requires this token, which closes the unauthenticated
# .env-rewrite attack surface.
#
# v3.4.1 (L-4): was a single `dict | None` slot — a second parallel /pair
# would overwrite the first's token and invalidate it before the first
# client could call /configure. Real scenario: admin testing on two
# mobiles against the same Pi simultaneously. Now keyed by token so N
# active sessions coexist, each TTL-expired on its own clock. Caps at
# _MAX_CONFIGURE_TOKENS so a pair-spam attacker can't blow up memory;
# expired entries are swept opportunistically on every read.
_configure_tokens: dict[str, dict] = {}
_MAX_CONFIGURE_TOKENS = 32
_CONFIGURE_TOKEN_TTL_SECONDS = 600


def _sweep_expired_configure_tokens() -> None:
    """Drop expired tokens so the dict doesn't grow without bound."""
    now = time.time()
    for tok in list(_configure_tokens.keys()):
        entry = _configure_tokens.get(tok)
        if entry and entry.get("expires_at", 0) < now:
            _configure_tokens.pop(tok, None)
    # Hard cap — if something sprays the endpoint, FIFO-evict oldest.
    while len(_configure_tokens) > _MAX_CONFIGURE_TOKENS:
        oldest_tok = min(_configure_tokens, key=lambda k: _configure_tokens[k].get("expires_at", 0))
        _configure_tokens.pop(oldest_tok, None)

_CLOUD_URL_RE = re.compile(r"^https?://[A-Za-z0-9._:/\-]+$")


@router.get("/status")
async def cloud_status():
    return get_cloud_status()


@router.post("/reconnect")
async def cloud_reconnect():
    """Retry the cloud connection now instead of waiting out the backoff.

    The retry uses the credentials pairing last saved. ``status``:
    ``reconnecting`` (retry triggered), ``connected`` (nothing to do),
    ``restart_required`` (the connector isn't running in this process —
    e.g. the Pi was unpaired at boot), or ``not_configured``.
    """
    status = get_cloud_status()
    if not status["configured"]:
        return {"status": "not_configured",
                "message": "Pair this Pi, or set SPOREPRINT_CLOUD_URL, SPOREPRINT_CLOUD_TOKEN "
                           "and SPOREPRINT_CLOUD_DEVICE_ID, to enable"}
    return {"status": request_reconnect(), "current": get_cloud_status()}


@router.post("/pairing-code")
async def generate_pairing_code():
    """Generate a 6-digit pairing code valid for 10 minutes."""
    global _pairing_code, _pairing_attempts, _pairing_lockout_until
    code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
    _pairing_code = {
        "code": code,
        "created_at": time.time(),
        "expires_at": time.time() + 600,
    }
    _pairing_attempts = 0
    _pairing_lockout_until = 0.0
    return {"code": code, "expires_in": 600}


@router.get("/pairing-code")
async def get_pairing_code():
    """Get the current pairing code (for the Pi's web UI settings page)."""
    if not _pairing_code:
        return {"code": None, "expired": True}
    if time.time() > _pairing_code["expires_at"]:
        return {"code": None, "expired": True}
    remaining = int(_pairing_code["expires_at"] - time.time())
    return {"code": _pairing_code["code"], "expires_in": remaining}


@router.post("/pair")
async def pair_device(data: dict):
    """Validate pairing code from mobile app. Returns a configure-token on success.

    The configure-token is required to call /configure — this prevents an
    unauthenticated LAN caller from rewriting .env. The pairing
    code itself is single-use and invalidated here regardless of outcome.
    """
    global _pairing_code, _pairing_attempts, _pairing_lockout_until
    now = time.time()

    if now < _pairing_lockout_until:
        raise HTTPException(429, "Too many failed pairing attempts. Try again later.")

    code = data.get("code", "")

    if not _pairing_code:
        raise HTTPException(400, "No pairing code active. Generate one from the Pi's settings page.")
    if now > _pairing_code["expires_at"]:
        _pairing_code = None
        raise HTTPException(400, "Pairing code expired. Generate a new one.")
    if code != _pairing_code["code"]:
        _pairing_attempts += 1
        if _pairing_attempts >= _MAX_PAIRING_ATTEMPTS:
            _pairing_lockout_until = now + 600
            _pairing_code = None
            raise HTTPException(429, "Too many failed attempts. Pairing locked for 10 minutes.")
        raise HTTPException(400, "Invalid pairing code.")

    _pairing_code = None  # one-time use
    _pairing_attempts = 0

    token = secrets.token_urlsafe(32)
    # The device id this session pairs: the configured one, or a fresh one
    # for a Pi that has none. It is kept with the token so /pair-verify can
    # report it and /configure accepts only it.
    cloud_device_id = settings.cloud_device_id or secrets.token_hex(16)
    _sweep_expired_configure_tokens()
    _configure_tokens[token] = {
        "expires_at": now + _CONFIGURE_TOKEN_TTL_SECONDS,
        "cloud_device_id": cloud_device_id,
    }

    return {
        "success": True,
        "configure_token": token,
        "configure_token_expires_in": _CONFIGURE_TOKEN_TTL_SECONDS,
        "device": {
            "cloud_device_id": cloud_device_id,
            "name": "SporePrint Pi",
            "firmware_version": server_version(),
        },
    }


@router.get("/pair-verify")
async def pair_verify(configure_token: str = ""):
    """v3.3.10 (S-M-11): third-party proof that a `configure_token` was
    issued by THIS Pi. The cloud calls this from its own network side
    during the pairing flow so a hostile LAN host can't convince the
    mobile app that it's a Pi and trick the cloud into writing an
    attacker-chosen device_token into Supabase.

    Returns ``{"valid": true, "cloud_device_id": ..., "version": ...}`` if
    the token is the one we just issued, 401 otherwise. ``cloud_device_id``
    is the id /pair handed out with this token, which the cloud holds its
    pairing to. ``version`` is the running server version, so the cloud can
    record it at pairing. No secrets leak; the token is already in the
    mobile's possession when this is called.
    """
    _sweep_expired_configure_tokens()
    if not configure_token:
        raise HTTPException(401, "No active pairing session")
    entry = _configure_tokens.get(configure_token)
    if not entry:
        raise HTTPException(401, "Unknown configure_token")
    now = time.time()
    if now > entry["expires_at"]:
        _configure_tokens.pop(configure_token, None)
        raise HTTPException(401, "configure_token expired")
    return {
        "valid": True,
        "cloud_device_id": entry.get("cloud_device_id") or settings.cloud_device_id or "",
        "expires_in": int(entry["expires_at"] - now),
        "version": server_version(),
    }


@router.post("/configure")
async def configure_cloud(data: dict):
    """Persist cloud credentials received from a paired mobile app.

    Requires the short-lived configure_token issued by /pair — that token is
    the only thing standing between an unauthenticated LAN request and a
    `.env` rewrite.

    v3.4.1 (L-4): reads from the per-token dict so parallel /pair sessions
    don't invalidate each other.
    """
    _sweep_expired_configure_tokens()
    token = data.get("configure_token") or ""
    entry = _configure_tokens.get(token)
    if not entry:
        raise HTTPException(401, "Invalid or missing configure_token — re-pair the device.")
    if time.time() > entry["expires_at"]:
        _configure_tokens.pop(token, None)
        raise HTTPException(401, "configure_token expired — re-pair the device.")

    device_id = data.get("cloud_device_id", "")
    token_value = data.get("device_token", "")
    cloud_url = data.get("cloud_url", "")

    if not device_id or not token_value:
        raise HTTPException(400, "Missing cloud_device_id or device_token")
    issued_id = entry.get("cloud_device_id")
    if issued_id and device_id != issued_id:
        # The pairing session was opened for the id /pair handed out; another
        # id would make this Pi connect as a different device.
        raise HTTPException(400, "cloud_device_id does not match this pairing session — re-pair the device.")

    if cloud_url and not _CLOUD_URL_RE.match(cloud_url):
        raise HTTPException(400, "Invalid cloud_url")
    if cloud_url and not cloud_url_transport_ok(cloud_url):
        # The device token doubles as the command-signing HMAC key — never
        # let it be sent in plaintext across the internet.
        raise HTTPException(
            400,
            "cloud_url must use https:// (plain http:// is only allowed for a "
            "LAN/loopback development relay)",
        )

    updates = {
        "SPOREPRINT_CLOUD_DEVICE_ID": device_id,
        "SPOREPRINT_CLOUD_TOKEN": token_value,
    }
    if cloud_url:
        updates["SPOREPRINT_CLOUD_URL"] = cloud_url

    try:
        write_cloud_env(updates)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, f"Failed to persist cloud credentials: {e}")

    # One-time use — burn the token so a replay (caught webhook body) can't
    # re-configure the Pi.
    _configure_tokens.pop(token, None)

    # A (re)pairing may be a different cloud: re-learn whether it signs
    # integrations_request frames.
    await reset_signing_latch()

    # Take the new credentials into use now. A running connector (a re-pair or
    # a token rotation) drops its session and reconnects with the new token;
    # it used to keep retrying the old one, refused, until a restart.
    # `applied` is additive: false means no connector runs in this process
    # (the Pi was unpaired at boot), so a restart connects it.
    applied = await apply_paired_credentials()
    return {
        "status": "configured",
        "applied": applied,
        "message": ("Cloud credentials saved and applied — reconnecting."
                    if applied else "Cloud credentials saved. Restart to connect."),
    }
