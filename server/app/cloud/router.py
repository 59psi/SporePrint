import re
import secrets
import time

from fastapi import APIRouter, HTTPException

from .service import get_cloud_status, write_cloud_env

router = APIRouter()

# In-memory pairing state: one pending code at a time per Pi.
_pairing_code: dict | None = None
_pairing_attempts = 0
_pairing_lockout_until: float = 0.0
_MAX_PAIRING_ATTEMPTS = 8

# Short-lived tokens issued to clients that just presented a valid pairing
# code. `/configure` requires this token, which closes the unauthenticated
# .env-rewrite attack surface (sentinel S1).
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
    status = get_cloud_status()
    if not status["configured"]:
        return {"status": "not_configured", "message": "Set SPOREPRINT_CLOUD_URL and _TOKEN to enable"}
    return {"status": "reconnecting", "current": status}


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
    unauthenticated LAN caller from rewriting .env (sentinel S1). The pairing
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

    from ..config import settings
    _pairing_code = None  # one-time use
    _pairing_attempts = 0

    token = secrets.token_urlsafe(32)
    _sweep_expired_configure_tokens()
    _configure_tokens[token] = {"expires_at": now + _CONFIGURE_TOKEN_TTL_SECONDS}

    return {
        "success": True,
        "configure_token": token,
        "configure_token_expires_in": _CONFIGURE_TOKEN_TTL_SECONDS,
        "device": {
            "cloud_device_id": settings.cloud_device_id or secrets.token_hex(16),
            "name": "SporePrint Pi",
            "firmware_version": "0.3.0",
        },
    }


@router.get("/pair-verify")
async def pair_verify(configure_token: str = ""):
    """v3.3.10 (S-M-11): third-party proof that a `configure_token` was
    issued by THIS Pi. The cloud calls this from its own network side
    during the pairing flow so a hostile LAN host can't convince the
    mobile app that it's a Pi and trick the cloud into writing an
    attacker-chosen device_token into Supabase.

    Returns ``{"valid": true, "cloud_device_id": ...}`` if the token is
    the one we just issued, 401 otherwise. No secrets leak; the token
    is already in the mobile's possession when this is called.
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
    from ..config import settings
    return {
        "valid": True,
        "cloud_device_id": settings.cloud_device_id or "",
        "expires_in": int(entry["expires_at"] - now),
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

    if cloud_url and not _CLOUD_URL_RE.match(cloud_url):
        raise HTTPException(400, "Invalid cloud_url")

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

    return {"status": "configured", "message": "Cloud credentials saved. Restart to connect."}
