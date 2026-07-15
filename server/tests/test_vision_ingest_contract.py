"""The ESP32-CAM posts a raw JPEG body. The endpoint must accept it.

`/api/vision/frame` declared `file: UploadFile = File(...)`, which only parses
multipart/form-data. The cam firmware POSTs the JPEG as a raw `image/jpeg` body
(esp_http_client has no multipart encoder), so FastAPI rejected every frame with
a 422 before the handler ever ran — meaning the vision pipeline had never once
ingested a frame from real hardware, and contamination detection was analysing
nothing. Both wire shapes are now accepted; these tests pin both.
"""

import pytest

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"


@pytest.fixture(autouse=True)
def _frame_storage(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "vision_storage", str(tmp_path / "frames"))


def test_raw_jpeg_body_is_accepted(client):
    """Exactly what the firmware sends: raw bytes, Content-Type: image/jpeg."""
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={
            "Content-Type": "image/jpeg",
            "X-Node-Id": "cam-01",
            "X-Timestamp": "1752300000",
            "X-Resolution": "1600x1200",
            "X-Flash-Used": "1",
        },
    )
    assert r.status_code == 200, r.text


def test_multipart_upload_still_works(client):
    """The web UI and existing tests post multipart. Don't break them."""
    r = client.post(
        "/api/vision/frame",
        files={"file": ("frame.jpg", JPEG, "image/jpeg")},
        headers={"X-Node-Id": "cam-01"},
    )
    assert r.status_code == 200, r.text


def test_non_image_raw_body_is_rejected(client):
    r = client.post(
        "/api/vision/frame",
        content=b"not an image",
        headers={"Content-Type": "application/json", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 415


def test_empty_raw_body_is_rejected(client):
    r = client.post(
        "/api/vision/frame",
        content=b"",
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 400


def test_traversal_node_id_still_rejected(client):
    """The node id drives the on-disk filename — keep the guard on both paths."""
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "../../etc/passwd"},
    )
    assert r.status_code == 400
