"""Claude model id + response-shape robustness across every Claude call site.

deps-infra#1 / srv-rest#3 / docs#23 — all five call sites (vision frame
    analysis, contamination identify, transcript analysis, experiment analysis,
    Builder's Assistant) hardcoded the retired `claude-sonnet-4-20250514`, with
    no setting to change it. The id now comes from `settings.claude_model`
    (env SPOREPRINT_CLAUDE_MODEL, default `claude-sonnet-5`).
srv-rest#3 / srv-hw#13 — current models think by default, so `content[0]` can
    be a `thinking` block (no `.text`), thinking counts against a small
    `max_tokens`, and a `refusal` / `max_tokens` stop_reason was never checked.
    The Builder saved guides cut off at 4096 tokens as if they were complete.
"""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import TextBlock, ThinkingBlock

import app.builder.service as builder_service
import app.contamination.router as crouter
import app.experiments.service as experiments_service
import app.transcript.service as transcript_service
from app.config import DEFAULT_CLAUDE_MODEL, Settings, settings
from app.db import get_db
from app.experiments.models import ExperimentCreate
from app.sessions.models import SessionCreate
from app.sessions.service import create_session
from app.species.service import seed_builtins
from app.vision import service as vision_service
from app.vision.service import claude_response_text

TEST_MODEL = "claude-test-model"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"


def _thinking():
    return ThinkingBlock(type="thinking", thinking="", signature="sig")


def _text(text: str):
    return TextBlock(type="text", text=text)


def _message(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class _Recorder:
    """AsyncAnthropic stand-in serving `reply` from both create() and stream()."""

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[dict] = []
        recorder = self

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get_final_message(self):
                return recorder.reply

        class _Messages:
            async def create(self, **kwargs):
                recorder.calls.append({"method": "create", **kwargs})
                return recorder.reply

            def stream(self, **kwargs):
                recorder.calls.append({"method": "stream", **kwargs})
                return _Stream()

        class _Client:
            def __init__(self, *args, **kwargs):
                self.messages = _Messages()

        self.client_cls = _Client


@pytest.fixture()
def claude_env(monkeypatch):
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    monkeypatch.setattr(settings, "claude_model", TEST_MODEL)


def _install(monkeypatch, module, reply) -> _Recorder:
    rec = _Recorder(reply)
    monkeypatch.setattr(module.anthropic, "AsyncAnthropic", rec.client_cls)
    return rec


# ─── Config ─────────────────────────────────────────────────────────────


def test_default_model_is_current_sonnet(monkeypatch):
    monkeypatch.delenv("SPOREPRINT_CLAUDE_MODEL", raising=False)
    assert DEFAULT_CLAUDE_MODEL == "claude-sonnet-5"
    assert Settings(_env_file=None).claude_model == "claude-sonnet-5"


def test_model_is_env_overridable(monkeypatch):
    monkeypatch.setenv("SPOREPRINT_CLAUDE_MODEL", "claude-opus-5-5")
    assert Settings(_env_file=None).claude_model == "claude-opus-5-5"


def test_blank_model_env_falls_back_to_default(monkeypatch):
    # docker-compose passes `${SPOREPRINT_CLAUDE_MODEL:-}` → an empty string
    # must not become model="" (a 400 on every request).
    monkeypatch.setenv("SPOREPRINT_CLAUDE_MODEL", "  ")
    assert Settings(_env_file=None).claude_model == DEFAULT_CLAUDE_MODEL


def test_no_hardcoded_model_ids_outside_config():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"""["']claude-(?:opus|sonnet|haiku|fable|mythos|instant|[0-9])[\w.\-]*["']""")
    offenders = [
        f"{path.relative_to(app_dir)}:{lineno}"
        for path in app_dir.rglob("*.py")
        if path.name != "config.py"
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


# ─── Response text extraction ───────────────────────────────────────────


def test_response_text_skips_thinking_block():
    msg = _message(_thinking(), _text('{"ok": true}'))
    assert claude_response_text(msg) == '{"ok": true}'


def test_response_text_joins_all_text_blocks():
    msg = _message(_text("part one, "), _thinking(), _text("part two"))
    assert claude_response_text(msg) == "part one, part two"


def test_response_text_empty_when_no_text_blocks():
    assert claude_response_text(_message(_thinking(), stop_reason="refusal")) == ""
    assert claude_response_text(SimpleNamespace(content=None)) == ""


# ─── Vision frame analysis ──────────────────────────────────────────────


def _frame(tmp_path) -> dict:
    img = tmp_path / "cam-01.jpg"
    img.write_bytes(JPEG)
    return {"id": 1, "session_id": None, "node_id": "cam-01", "file_path": str(img)}


async def test_vision_uses_configured_model_and_survives_thinking_block(
    tmp_path, monkeypatch, claude_env,
):
    rec = _install(monkeypatch, vision_service, _message(
        _thinking(), _text('{"health_assessment": "healthy", "summary": "ok"}'),
    ))
    result = await vision_service.analyze_frame_claude(_frame(tmp_path))
    assert result == {"health_assessment": "healthy", "summary": "ok"}
    assert rec.calls[0]["model"] == TEST_MODEL
    # Thinking shares max_tokens with the JSON answer — 2048 truncated it.
    assert rec.calls[0]["max_tokens"] >= 16000


async def test_vision_refusal_is_an_error_not_an_analysis(tmp_path, monkeypatch, claude_env):
    alert = AsyncMock()
    monkeypatch.setattr(vision_service, "contamination_alert", alert)
    _install(monkeypatch, vision_service, _message(_thinking(), stop_reason="refusal"))
    result = await vision_service.analyze_frame_claude(_frame(tmp_path))
    assert "error" in result  # callers persist only error-free results
    alert.assert_not_awaited()


async def test_vision_truncated_unparseable_response_is_an_error(tmp_path, monkeypatch, claude_env):
    _install(monkeypatch, vision_service, _message(
        _text('```json\n{"health_assessment": "conc'), stop_reason="max_tokens",
    ))
    result = await vision_service.analyze_frame_claude(_frame(tmp_path))
    assert "error" in result
    assert "max_tokens" in result["error"]


# ─── Contamination identify ─────────────────────────────────────────────


def test_identify_uses_configured_model_and_survives_thinking_block(client, monkeypatch, claude_env):
    rec = _install(monkeypatch, crouter, _message(
        _thinking(), _text('{"contamination_detected": false, "contaminants": []}'),
    ))
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["contamination_detected"] is False
    assert rec.calls[0]["model"] == TEST_MODEL
    assert rec.calls[0]["max_tokens"] >= 16000


def test_identify_refusal_is_a_clear_502(client, monkeypatch, claude_env):
    _install(monkeypatch, crouter, _message(_thinking(), stop_reason="refusal"))
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 502
    assert "declined" in r.json()["detail"]


def test_identify_truncation_is_flagged(client, monkeypatch, claude_env):
    _install(monkeypatch, crouter, _message(
        _text('```json\n{"contamination_detected": true, "contam'), stop_reason="max_tokens",
    ))
    r = client.post("/api/contamination/identify", files={"file": ("f.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_error"] is True
    assert body["truncated"] is True


# ─── Transcript analysis ────────────────────────────────────────────────


async def _session() -> int:
    await seed_builtins()
    s = await create_session(SessionCreate(name="Run", species_profile_id="blue_oyster"))
    return s["id"]


async def test_transcript_uses_configured_model_and_survives_thinking_block(monkeypatch, claude_env):
    sid = await _session()
    rec = _install(monkeypatch, transcript_service, _message(
        _thinking(), _text('{"overall_score": 81, "summary": "fine"}'),
    ))
    result = await transcript_service.analyze_with_claude(sid)
    assert result == {"overall_score": 81, "summary": "fine"}
    assert rec.calls[0]["model"] == TEST_MODEL
    assert rec.calls[0]["max_tokens"] >= 16000


async def test_transcript_refusal_and_truncation_are_errors(monkeypatch, claude_env):
    sid = await _session()
    _install(monkeypatch, transcript_service, _message(stop_reason="refusal"))
    assert "error" in await transcript_service.analyze_with_claude(sid)

    _install(monkeypatch, transcript_service, _message(
        _text('{"overall_score": 81, "condition_anal'), stop_reason="max_tokens",
    ))
    result = await transcript_service.analyze_with_claude(sid)
    assert "max_tokens" in result["error"]


# ─── Experiment analysis ────────────────────────────────────────────────


async def _experiment() -> int:
    await seed_builtins()
    c = await create_session(SessionCreate(name="C", species_profile_id="blue_oyster"))
    v = await create_session(SessionCreate(name="V", species_profile_id="blue_oyster"))
    exp = await experiments_service.create_experiment(ExperimentCreate(
        title="t", hypothesis="h", control_session_id=c["id"], variant_session_id=v["id"],
        independent_variable="substrate", control_value="CVG", variant_value="manure",
    ))
    return exp["id"]


async def test_experiment_uses_configured_model_with_room_to_think(monkeypatch, claude_env):
    exp_id = await _experiment()
    rec = _install(monkeypatch, experiments_service, _message(
        _thinking(), _text('{"summary": "s", "hypothesis_supported": true}'),
    ))
    result = await experiments_service.analyze_experiment(exp_id)
    assert result["analysis"]["hypothesis_supported"] is True
    assert rec.calls[0]["model"] == TEST_MODEL
    assert rec.calls[0]["max_tokens"] >= 16000  # was 1000 — thinking alone overran it


async def test_experiment_refusal_and_truncation_are_errors(monkeypatch, claude_env):
    exp_id = await _experiment()
    _install(monkeypatch, experiments_service, _message(stop_reason="refusal"))
    result = await experiments_service.analyze_experiment(exp_id)
    assert "error" in result and "comparison" in result and "analysis" not in result

    _install(monkeypatch, experiments_service, _message(
        _text('{"summary": "the var'), stop_reason="max_tokens",
    ))
    result = await experiments_service.analyze_experiment(exp_id)
    assert "max_tokens" in result["error"] and "analysis" not in result


# ─── Builder's Assistant ────────────────────────────────────────────────


async def _guide_count() -> int:
    async with get_db() as db:
        row = await (await db.execute("SELECT COUNT(*) AS n FROM builder_guides")).fetchone()
    return row["n"]


async def test_builder_streams_with_configured_model_and_saves_full_guide(monkeypatch, claude_env):
    guide = "## 1. Parts List\n- solenoid\n\n## 9. Test Procedure\n1. Pulse it."
    rec = _install(monkeypatch, builder_service, _message(_thinking(), _text(guide)))
    result = await builder_service.generate_guide("Add a misting solenoid")
    assert result["guide"] == guide
    assert isinstance(result["guide_id"], int)
    call = rec.calls[0]
    assert call["method"] == "stream"  # long output: stream, not one blocking create()
    assert call["model"] == TEST_MODEL
    assert call["max_tokens"] >= 16000  # 4096 cut 9-section guides off mid-section
    assert await _guide_count() == 1


async def test_builder_truncated_guide_is_flagged_and_not_saved(monkeypatch, claude_env):
    partial = "## 1. Parts List\n- solenoid\n\n## 3. Firmware Changes\n```cpp\nvoid setup() {"
    _install(monkeypatch, builder_service, _message(_text(partial), stop_reason="max_tokens"))
    result = await builder_service.generate_guide("Add a misting solenoid")
    assert "error" in result
    assert result["truncated"] is True
    assert result["guide"] == partial  # the partial text is still shown, just not saved
    assert await _guide_count() == 0


async def test_builder_refusal_is_an_error_and_not_saved(monkeypatch, claude_env):
    _install(monkeypatch, builder_service, _message(_thinking(), stop_reason="refusal"))
    result = await builder_service.generate_guide("Add a misting solenoid")
    assert "error" in result
    assert await _guide_count() == 0
