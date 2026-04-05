import json

from app.vision.service import parse_claude_json, _deserialize_frame


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
