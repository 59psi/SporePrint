def test_qr_session_returns_png(client):
    """QR code for a session should return a valid PNG image."""
    resp = client.get("/api/labels/qr", params={"type": "session", "id": 1, "size": 150})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:4] == b"\x89PNG"


def test_qr_culture_returns_png(client):
    """QR code for a culture should return a valid PNG image."""
    resp = client.get("/api/labels/qr", params={"type": "culture", "id": 42, "size": 200})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:4] == b"\x89PNG"


def test_qr_invalid_type_returns_400(client):
    """Invalid type parameter should return 400."""
    resp = client.get("/api/labels/qr", params={"type": "invalid", "id": 1})
    assert resp.status_code == 400
