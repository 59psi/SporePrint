"""The ESP32-CAM posts a raw JPEG body. The endpoint must accept it.

`/api/vision/frame` declared `file: UploadFile = File(...)`, which only parses
multipart/form-data. The cam firmware POSTs the JPEG as a raw `image/jpeg` body
(esp_http_client has no multipart encoder), so FastAPI rejected every frame with
a 422 before the handler ever ran — meaning the vision pipeline had never once
ingested a frame from real hardware, and contamination detection was analysing
nothing. Both wire shapes are now accepted; these tests pin both.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.vision.router as vision_router
from app.config import settings
from app.vision import service as vision_service

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"


@pytest.fixture(autouse=True)
def _frame_storage(tmp_path, monkeypatch):
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


def _frame_row(client, frame_id: int) -> dict:
    r = client.get(f"/api/vision/frames/{frame_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_unsynced_uptime_timestamp_is_stamped_with_arrival_time(client):
    """Contract #2: a cam without NTP sends uptime seconds (e.g. 900).
    Anything < 1e9 is unsynced, so the server stamps arrival time instead of
    filing the frame in 1970."""
    before = time.time()
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01", "X-Timestamp": "900"},
    )
    assert r.status_code == 200, r.text
    row = _frame_row(client, r.json()["frame_id"])
    assert before - 1 <= row["timestamp"] <= time.time() + 1


def test_synced_timestamp_is_kept(client):
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01", "X-Timestamp": "1752300000"},
    )
    assert r.status_code == 200, r.text
    assert _frame_row(client, r.json()["frame_id"])["timestamp"] == 1752300000


def test_frames_with_the_same_timestamp_never_overwrite_each_other(client):
    """Files were named `{node}_{int(ts)}.jpg`, so uptime values that
    recur after every reboot (or two uploads in one second) overwrote an older
    frame's image while its DB row still pointed at the path."""
    first = b"\xff\xd8\xff\xe0" + b"first-frame"
    second = b"\xff\xd8\xff\xe0" + b"second-frame"
    paths = []
    for body in (first, second):
        r = client.post(
            "/api/vision/frame",
            content=body,
            headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01", "X-Timestamp": "1752300000"},
        )
        assert r.status_code == 200, r.text
        paths.append(r.json()["file_path"])
    assert paths[0] != paths[1]
    assert Path(paths[0]).read_bytes() == first
    assert Path(paths[1]).read_bytes() == second


def test_png_upload_keeps_png_extension(client):
    """PNG/WebP uploads were saved as .jpg (and later declared to
    Claude as image/jpeg, which the API rejects)."""
    r = client.post(
        "/api/vision/frame",
        files={"file": ("frame.png", PNG, "image/png")},
        headers={"X-Node-Id": "cam-01"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["file_path"].endswith(".png")


@pytest.mark.parametrize("body", [b"<html>not an image</html>", b"GIF89a" + b"gif-body"])
def test_a_body_that_is_no_accepted_image_is_refused_whatever_its_label(client, body):
    """The bytes decide, as for a contamination photo: a body labelled
    image/jpeg that is no JPEG / PNG / WebP image was stored as a frame and
    later sent to Claude as one."""
    r = client.post(
        "/api/vision/frame",
        content=body,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 415, r.text
    storage = Path(settings.vision_storage)
    assert not storage.exists() or not any(storage.iterdir())
    assert client.get("/api/vision/frames").json() == []


def test_frame_file_is_written_off_the_event_loop(client, monkeypatch):
    """Up to 20 MB of file I/O: written in a worker thread, not on the loop
    that serves MQTT and the rules."""
    offloaded = []
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(fn, *args, **kwargs):
        offloaded.append(fn)
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 200, r.text
    assert vision_service.write_frame_file in offloaded
    assert Path(r.json()["file_path"]).read_bytes() == JPEG


def test_ingest_stores_no_placeholder_local_analysis(client):
    """No local model is built: ingest stores nothing in analysis_local (it
    used to write a constant "healthy" placeholder on every frame), and an
    active-learning label still lands on the frame."""
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "local_analysis" in body and body["local_analysis"] is None
    assert _frame_row(client, body["frame_id"])["analysis_local"] is None

    labelled = client.post(f"/api/vision/frames/{body['frame_id']}/label",
                           json={"label": "trich_early", "correct": False})
    assert labelled.status_code == 200, labelled.text
    assert _frame_row(client, body["frame_id"])["analysis_local"] == {
        "user_label": "trich_early", "user_confirmed": False}


def test_frame_detail_decodes_its_analyses_like_the_list(client, monkeypatch):
    """GET /frames/{id} returned analysis_claude / analysis_local as JSON
    strings while GET /frames returned objects."""
    r = client.post(
        "/api/vision/frame",
        content=JPEG,
        headers={"Content-Type": "image/jpeg", "X-Node-Id": "cam-01"},
    )
    frame_id = r.json()["frame_id"]
    analysis = {"health_assessment": "healthy", "summary": "pins forming"}
    monkeypatch.setattr(vision_router, "analyze_frame_claude", AsyncMock(return_value=analysis))
    assert client.post(f"/api/vision/frames/{frame_id}/analyze").json() == analysis
    client.post(f"/api/vision/frames/{frame_id}/label", json={"label": "healthy"})

    detail = _frame_row(client, frame_id)
    assert detail["analysis_claude"] == analysis
    assert detail["analysis_local"] == {"user_label": "healthy", "user_confirmed": True}
    listed = next(f for f in client.get("/api/vision/frames").json() if f["id"] == frame_id)
    assert detail == listed
