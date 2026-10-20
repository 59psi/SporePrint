import io
from urllib.parse import urlsplit

import qrcode
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..config import settings

router = APIRouter()

# Where the Pi dashboard is published by docker-compose (nginx "3001:80") and
# advertised over mDNS. Nothing listens on :80, so a bare
# http://sporeprint.local/... label is a dead link. Used only when
# SPOREPRINT_PUBLIC_UI_URL (whose default it equals) is not a usable URL.
DEFAULT_UI_ORIGIN = "http://sporeprint.local:3001"

# Real SPA routes (the UI has no /s/:id or /c/:id route); the id rides along as
# a query parameter for deep-linking.
_LABEL_PATHS = {"session": "/sessions", "culture": "/cultures"}


def _origin(url: str | None) -> str | None:
    """scheme://host[:port] of an absolute http(s) URL, else None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:  # e.g. an unbalanced "[" in a header or the setting
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def label_url(label_type: str, item_id: int, ui_origin: str | None = None) -> str:
    """The URL a printed QR label encodes for a session or culture.

    With no usable ``ui_origin`` the label points at SPOREPRINT_PUBLIC_UI_URL,
    the setting that exists for exactly this (e.g. http://<pi-ip>:3001 where
    sporeprint.local does not resolve); it used to be ignored.
    """
    origin = (_origin(ui_origin) or _origin(settings.public_ui_url)
              or DEFAULT_UI_ORIGIN)
    return f"{origin}{_LABEL_PATHS[label_type]}?id={item_id}"


@router.get("/qr")
async def generate_qr_label(
    request: Request,
    type: str = Query(..., description="Label type: session or culture"),
    id: int = Query(..., description="ID of the session or culture"),
    size: int = Query(150, ge=50, le=500, description="QR code image size in pixels"),
    base_url: str | None = Query(
        None, description="UI origin the label should open, e.g. http://192.168.1.20:3001",
    ),
):
    if type not in _LABEL_PATHS:
        raise HTTPException(400, "Invalid type — must be 'session' or 'culture'")

    # Prefer an explicit base_url, then the UI page that asked for the label
    # (its Origin / Referer — the address the operator actually reaches the
    # dashboard on), then SPOREPRINT_PUBLIC_UI_URL (label_url).
    ui_origin = (
        _origin(base_url)
        or _origin(request.headers.get("origin"))
        or _origin(request.headers.get("referer"))
    )
    url = label_url(type, id, ui_origin)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={type}-{id}-qr.png"},
    )
