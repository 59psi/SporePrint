import json

from app.vision.service import parse_claude_json, _deserialize_frame, sniff_image_media_type


def test_parse_claude_json_plain():
    result = parse_claude_json('{"health": "good"}')
    assert result == {"health": "good"}


def test_parse_claude_json_markdown_block():
    text = 'Here is the analysis:\n```json\n{"health": "good"}\n```\nDone.'
    result = parse_claude_json(text)
    assert result == {"health": "good"}


def test_parse_claude_json_plain_code_block():
    text = 'Result:\n```\n{"health": "good"}\n```'
    result = parse_claude_json(text)
    assert result == {"health": "good"}


def test_parse_claude_json_unparseable():
    result = parse_claude_json("I can't generate JSON right now.")
    assert "raw_response" in result
    assert "I can't" in result["raw_response"]


def test_parse_claude_json_truncated_fenced_block_falls_back():
    """srv-rest#10: a response cut off at max_tokens inside a ```json fence used
    to raise JSONDecodeError out of the parser (500 on /contamination/identify)."""
    text = '```json\n{"a": 1, "b": [1,2'
    result = parse_claude_json(text)
    assert result == {"raw_response": text}


def test_parse_claude_json_invalid_plain_fence_falls_back():
    text = "```\nnot json at all\n```"
    assert parse_claude_json(text) == {"raw_response": text}


def test_parse_claude_json_prose_wrapped_object():
    """Unfenced JSON wrapped in prose is recovered instead of disabling every
    downstream signal (contamination, harvest, colonization)."""
    text = 'Sure! Here is my analysis: {"health_assessment": "healthy", "confidence": 0.8} Hope this helps.'
    assert parse_claude_json(text) == {"health_assessment": "healthy", "confidence": 0.8}


def test_parse_claude_json_non_object_is_raw():
    assert parse_claude_json("[1, 2, 3]") == {"raw_response": "[1, 2, 3]"}


def test_sniff_image_media_type():
    assert sniff_image_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert sniff_image_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert sniff_image_media_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_media_type(b"GIF89a....") == "image/gif"
    # HEIC (ftyp box) and arbitrary bytes are not types the Messages API accepts
    assert sniff_image_media_type(b"\x00\x00\x00\x18ftypheic") is None
    assert sniff_image_media_type(b"not an image") is None
    assert sniff_image_media_type(b"") is None


def test_deserialize_frame_with_json_analysis():
    row = {
        "id": 1,
        "node_id": "cam-01",
        "timestamp": 1000.0,
        "file_path": "/data/test.jpg",
        "analysis_local": json.dumps({"prediction": "healthy", "confidence": 0.95}),
        "analysis_claude": json.dumps({"health_assessment": "healthy", "summary": "Looks good"}),
    }
    result = _deserialize_frame(row)
    assert isinstance(result["analysis_local"], dict)
    assert result["analysis_local"]["prediction"] == "healthy"
    assert isinstance(result["analysis_claude"], dict)
    assert result["analysis_claude"]["health_assessment"] == "healthy"


def test_deserialize_frame_null_analysis():
    row = {
        "id": 1,
        "node_id": "cam-01",
        "timestamp": 1000.0,
        "file_path": "/data/test.jpg",
        "analysis_local": None,
        "analysis_claude": None,
    }
    result = _deserialize_frame(row)
    assert result["analysis_local"] is None
    assert result["analysis_claude"] is None
