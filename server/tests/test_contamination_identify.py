"""POST /api/contamination/identify — upload validation + response parsing.

- any upload content-type (image/heic from an iPhone,
  application/octet-stream) was forwarded to the Messages API,
  which only accepts jpeg/png/gif/webp → an opaque 502.
- a response truncated inside a ```json fence raised out of
  parse_claude_json → 500 instead of the documented parse_error.
"""

import pytest
from starlette.datastructures import UploadFile

import app.contamination.identify as cidentify
import app.contamination.router as crouter
from app.config import settings
from app.contamination.service import as_confidence, detection_from_identify

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
    monkeypatch.setattr(cidentify.anthropic, "AsyncAnthropic", _Client)
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


# ── The upload is bounded before it is read ─────────────────────────────


@pytest.fixture()
def reads(monkeypatch):
    """The sizes UploadFile.read was asked for."""
    sizes: list[int] = []
    real_read = UploadFile.read

    async def _read(self, size=-1):
        sizes.append(size)
        return await real_read(self, size)

    monkeypatch.setattr(UploadFile, "read", _read)
    return sizes


def test_an_oversized_declared_upload_is_refused_before_it_is_read(client, claude, reads):
    """The whole body was read into memory (then base64'd) before the 10 MB
    check; a client on the server's own port could send gigabytes."""
    r = client.post(
        "/api/contamination/identify",
        content=b"x" * 100,
        headers={
            "content-type": "multipart/form-data; boundary=b",
            "content-length": str(crouter._MAX_IMAGE_SIZE + crouter._MULTIPART_OVERHEAD_BYTES + 1),
        },
    )
    assert r.status_code == 413
    assert reads == [] and claude.calls == []


def test_an_image_over_the_cap_is_read_only_to_the_cap(client, claude, reads):
    big = JPEG + b"\0" * crouter._MAX_IMAGE_SIZE  # just over 10 MB, inside the framing room
    r = client.post("/api/contamination/identify", files={"file": ("big.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert reads == [crouter._MAX_IMAGE_SIZE + 1]
    assert claude.calls == []


def test_an_upload_without_a_length_is_refused(client, claude):
    def _chunks():
        yield b"--b\r\n"

    r = client.post(
        "/api/contamination/identify",
        content=_chunks(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 411
    assert claude.calls == []


def test_a_body_that_is_not_multipart_is_422(client, claude):
    r = client.post("/api/contamination/identify", content=JPEG,
                    headers={"content-type": "image/jpeg"})
    assert r.status_code == 422
    assert claude.calls == []


def test_without_a_key_nothing_is_read(client, monkeypatch, reads):
    monkeypatch.setattr(settings, "claude_api_key", "")
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 503
    assert reads == []


def test_unknown_session_or_chamber_is_422_before_the_paid_call(client, claude):
    for field in ("session_id", "chamber_id"):
        r = client.post(
            "/api/contamination/identify",
            files={"file": ("f.jpg", JPEG, "image/jpeg")},
            data={field: "9999"},
        )
        assert r.status_code == 422, r.text
        assert "9999" in r.json()["detail"]
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("f.jpg", JPEG, "image/jpeg")},
        data={"session_id": "abc"},
    )
    assert r.status_code == 422
    assert claude.calls == []


# ── Off-contract replies degrade instead of failing ─────────────────────


def test_a_string_contaminant_entry_is_recorded_not_a_500(client, claude):
    """A non-object `contaminants` entry raised AttributeError inside the
    route: a paid identification came back as a 500."""
    claude.reply = '{"contamination_detected": true, "contaminants": ["trichoderma"]}'
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    [event] = client.get("/api/contamination/events").json()
    assert event["source"] == "identify"
    assert event["contamination_type"] == "trichoderma"
    assert event["confidence"] is None


def test_a_percentage_confidence_is_stored_on_the_0_1_scale(client, claude):
    claude.reply = ('{"contamination_detected": true, "contaminants": '
                    '[{"classification": "cobweb", "confidence": 85}]}')
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    [event] = client.get("/api/contamination/events").json()
    assert event["confidence"] == pytest.approx(0.85)


def test_a_false_string_is_no_detection(client, claude):
    claude.reply = ('{"contamination_detected": "false", "contaminants": '
                    '[{"classification": "trichoderma", "confidence": 0.9}]}')
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert client.get("/api/contamination/events").json() == []


def test_an_identify_detection_is_linked_to_its_session_and_chamber(client, claude):
    chamber = client.post("/api/chambers", json={"name": "Closet"}).json()
    session = client.post("/api/sessions", json={
        "name": "G", "species_profile_id": "blue_oyster", "chamber_id": chamber["id"],
    }).json()
    claude.reply = ('{"contamination_detected": true, "contaminants": '
                    '[{"classification": "trichoderma", "confidence": 0.9}]}')
    r = client.post(
        "/api/contamination/identify",
        files={"file": ("f.jpg", JPEG, "image/jpeg")},
        data={"session_id": str(session["id"]), "chamber_id": str(chamber["id"])},
    )
    assert r.status_code == 200, r.text
    [event] = client.get("/api/contamination/events").json()
    assert (event["session_id"], event["chamber_id"]) == (session["id"], chamber["id"])


def test_an_api_error_is_a_502(client, monkeypatch):
    import anthropic
    import httpx

    class _Messages:
        async def create(self, **kwargs):
            raise anthropic.RateLimitError(
                "slow down", response=httpx.Response(
                    429, request=httpx.Request("POST", "https://api.anthropic.com")),
                body=None)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    monkeypatch.setattr(cidentify.anthropic, "AsyncAnthropic", _Client)
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    # The old name test ("API" in the class name) answered a rate limit with a 500.
    assert r.status_code == 502
    assert "RateLimitError" in r.json()["detail"]


@pytest.mark.parametrize("result, expected", [
    ({"contamination_detected": True,
      "contaminants": [{"classification": "trichoderma", "confidence": 0.7}]},
     {"contamination_type": "trichoderma", "confidence": 0.7}),
    ({"contamination_detected": "true", "contaminants": {"classification": "cobweb"}},
     {"contamination_type": "cobweb", "confidence": None}),
    ({"contamination_detected": True, "contaminants": "bacterial"},
     {"contamination_type": "bacterial", "confidence": None}),
    ({"contamination_detected": True, "contaminants": [42, {"classification": 7,
                                                            "confidence": "high"}]},
     {"contamination_type": None, "confidence": None}),
    ({"contamination_detected": True}, {"contamination_type": None, "confidence": None}),
    ({"contamination_detected": "false", "contaminants": [{"classification": "x"}]}, None),
    ({"contamination_detected": 1}, None),
    (["not", "a", "dict"], None),
])
def test_detection_from_identify_never_raises(result, expected):
    assert detection_from_identify(result) == expected


@pytest.mark.parametrize("value, expected", [
    (0.85, 0.85), (85, 0.85), ("85", 0.85), (1, 1.0), (250, 1.0), (-3, 0.0),
    (float("nan"), None), ("high", None), (None, None),
])
def test_as_confidence(value, expected):
    assert as_confidence(value) == (pytest.approx(expected) if expected is not None else None)
