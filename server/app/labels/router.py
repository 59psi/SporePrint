import io

import qrcode
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter()


@router.get("/qr")
async def generate_qr_label(
    type: str = Query(..., description="Label type: session or culture"),
    id: int = Query(..., description="ID of the session or culture"),
    size: int = Query(150, ge=50, le=500, description="QR code image size in pixels"),
):
    if type not in ("session", "culture"):
        raise HTTPException(400, "Invalid type — must be 'session' or 'culture'")

    prefix = "s" if type == "session" else "c"
    url = f"http://sporeprint.local/{prefix}/{id}"

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
