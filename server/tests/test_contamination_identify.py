"""POST /api/contamination/identify — upload validation + response parsing.

srv-rest#31 — any upload content-type (image/heic from an iPhone,
              application/octet-stream) was forwarded to the Messages API,
              which only accepts jpeg/png/gif/webp → an opaque 502.
srv-rest#10 — a response truncated inside a ```json fence raised out of
              parse_claude_json → 500 instead of the documented parse_error.
"""

import pytest

import app.contamination.router as crouter
from app.config import settings

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
HEIC = b"\x00\x00\x00\x18ftypheic" + b"heic-body"


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_FakeBlock(text)]
        self.stop_reason = stop_reason


@pytest.fixture()
def claude(monkeypatch):
    """Fake AsyncAnthropic; set `claude.reply` / `claude.stop_reason`; read `claude.calls`."""

    class _State:
        reply = '{"contamination_detected": false, "contaminants": []}'
        stop_reason = "end_turn"
        calls: list[dict] = []

    state = _State()
    state.calls = []

    class _Messages:
        async def create(self, **kwargs):
            state.calls.append(kwargs)
            return _FakeMessage(state.reply, state.stop_reason)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    monkeypatch.setattr(crouter.anthropic, "AsyncAnthropic", _Client)
    return state


def test_heic_upload_is_rejected_with_415(client, claude):
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("IMG_0001.HEIC", HEIC, "image/heic")},
    )
    assert r.status_code == 415, r.text
    assert claude.calls == []


def test_octet_stream_png_is_sniffed_and_declared_as_png(client, claude):
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("upload", PNG, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    source = claude.calls[0]["messages"][0]["content"][0]["source"]
    assert source["media_type"] == "image/png"


def test_mislabelled_jpeg_is_declared_by_its_bytes(client, claude):
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("frame.png", JPEG, "image/png")},
    )
    assert r.status_code == 200, r.text
    source = claude.calls[0]["messages"][0]["content"][0]["source"]
    assert source["media_type"] == "image/jpeg"


def test_truncated_fenced_json_returns_parse_error_not_500(client, claude):
    claude.reply = '```json\n{"contamination_detected": true, "contaminants": [{"classific'
    claude.stop_reason = "max_tokens"
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("frame.jpg", JPEG, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_error"] is True
    assert body["raw_response"].startswith("```json")
