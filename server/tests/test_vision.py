"""Vision helpers every Claude call site and frame route shares.

* parse_claude_json never raises: it finds the JSON object in a plain,
  fenced or prose-wrapped reply and otherwise hands back the raw text, so a
  reply cut off at max_tokens is a parse error, never a 500.
* sniff_image_media_type decides a frame's type by its bytes (JPEG, PNG,
  WebP, GIF) and refuses what the Messages API does not take.
* _deserialize_frame decodes a row's stored analyses.
"""

import json

import pytest

from app.vision.service import _deserialize_frame, parse_claude_json, sniff_image_media_type

_TRUNCATED_FENCE = '```json\n{"a": 1, "b": [1,2'


@pytest.mark.parametrize("text,expected", [
    ('{"health": "good"}', {"health": "good"}),
    ('Here is the analysis:\n```json\n{"health": "good"}\n```\nDone.', {"health": "good"}),
    ('Result:\n```\n{"health": "good"}\n```', {"health": "good"}),
    # Unfenced JSON wrapped in prose is recovered instead of disabling every
    # downstream signal (contamination, harvest, colonization).
    ('Sure! Here is my analysis: {"health_assessment": "healthy", "confidence": 0.8} Hope this helps.',
     {"health_assessment": "healthy", "confidence": 0.8}),
    ("I can't generate JSON right now.", {"raw_response": "I can't generate JSON right now."}),
    # Cut off at max_tokens inside a ```json fence: used to raise
    # JSONDecodeError out of the parser (a 500 on /contamination/identify).
    (_TRUNCATED_FENCE, {"raw_response": _TRUNCATED_FENCE}),
    ("```\nnot json at all\n```", {"raw_response": "```\nnot json at all\n```"}),
    ("[1, 2, 3]", {"raw_response": "[1, 2, 3]"}),
], ids=["plain", "json-fence", "plain-fence", "prose-wrapped", "no-json", "truncated-fence",
        "invalid-fence", "not-an-object"])
def test_parse_claude_json_finds_the_object_or_returns_the_raw_reply(text, expected):
    assert parse_claude_json(text) == expected


def test_sniff_image_media_type():
    assert sniff_image_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff_image_media_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_media_type(b"GIF89a....") == "image/gif"
    # HEIC (ftyp box) and arbitrary bytes are not types the Messages API accepts
    assert sniff_image_media_type(b"\x00\x00\x00\x18ftypheic") is None
    assert sniff_image_media_type(b"not an image") is None
    assert sniff_image_media_type(b"") is None


@pytest.mark.parametrize("local,claude", [
    ({"prediction": "healthy", "confidence": 0.95},
     {"health_assessment": "healthy", "summary": "Looks good"}),
    (None, None),
], ids=["stored-json", "nothing-stored"])
def test_deserialize_frame_decodes_its_stored_analyses(local, claude):
    row = {
        "id": 1,
        "node_id": "cam-01",
        "timestamp": 1000.0,
        "file_path": "/data/test.jpg",
        "analysis_local": json.dumps(local) if local else None,
        "analysis_claude": json.dumps(claude) if claude else None,
    }
    result = _deserialize_frame(row)
    assert (result["analysis_local"], result["analysis_claude"]) == (local, claude)
