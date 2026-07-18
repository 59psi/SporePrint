"""Vision auto-analysis resolves the session's species across the hyphen/underscore
id drift (same bug class as V1-1).

analyze_frame_claude used to resolve the species with a raw
`JOIN ... ON s.species_profile_id = sp.id`, which missed the ~63/74 species whose
stored id is hyphenated ("blue-oyster") while species_profiles is seeded with the
underscored builtin id ("blue_oyster"). The species context (name + colonization +
contamination notes) then silently dropped out of the Claude vision prompt, so
auto-analysis lost the species framing. The fix routes resolution through the
tolerant get_profile(). These tests drive analyze_frame_claude with a mocked
Anthropic client and assert the resolved species context lands in the system prompt.
"""

from app.config import settings
from app.db import get_db
from app.species.service import get_profile, seed_builtins
from app.vision import service
from app.vision.service import analyze_frame_claude


class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


def _fake_anthropic(capture: dict):
    """Stand-in for anthropic.AsyncAnthropic that records create() kwargs."""

    class _Messages:
        async def create(self, **kwargs):
            capture.update(kwargs)
            return _FakeMessage('{"health_assessment": "healthy", "summary": "ok"}')

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    return _Client


async def _make_active_session(species_profile_id: str,
                               phase: str = "substrate_colonization") -> int:
    # phase is deliberately non-fruiting so the harvest-alert path is a no-op.
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO sessions (name, species_profile_id, status, current_phase) "
            "VALUES (?, ?, 'active', ?)",
            ("Vision Species Test", species_profile_id, phase),
        )
        await db.commit()
        return cur.lastrowid


def _frame(tmp_path, session_id: int) -> dict:
    img = tmp_path / "cam-01.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-body")
    return {"id": 1, "session_id": session_id, "node_id": "cam-01", "file_path": str(img)}


async def test_hyphenated_session_resolves_species_in_vision_prompt(tmp_path, monkeypatch):
    """A session whose stored id is hyphenated still resolves its species profile,
    so the common name + colonization + contamination notes reach the prompt."""
    await seed_builtins()
    monkeypatch.setattr(settings, "claude_api_key", "test-key")

    capture: dict = {}
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _fake_anthropic(capture))

    # The UI stores the hyphenated id; species_profiles is seeded underscored.
    sid = await _make_active_session("blue-oyster")
    result = await analyze_frame_claude(_frame(tmp_path, sid))
    assert result == {"health_assessment": "healthy", "summary": "ok"}

    system = capture["system"]
    profile = await get_profile("blue-oyster")
    assert profile is not None

    # Species context is resolved from the profile — not the bare hyphenated id.
    assert f"Species: {profile.common_name}" in system  # "Blue Oyster"
    assert "Species: blue-oyster" not in system
    assert profile.colonization_visual_description in system
    assert profile.contamination_risk_notes in system


async def test_unknown_species_falls_back_to_id_without_error(tmp_path, monkeypatch):
    """A genuinely unresolvable species id must not crash the vision path: it
    falls back to the raw id + 'N/A' context rather than losing the analysis."""
    await seed_builtins()
    monkeypatch.setattr(settings, "claude_api_key", "test-key")

    capture: dict = {}
    monkeypatch.setattr(service.anthropic, "AsyncAnthropic", _fake_anthropic(capture))

    sid = await _make_active_session("not-a-real-species")
    result = await analyze_frame_claude(_frame(tmp_path, sid))
    assert "error" not in result
    assert "Species: not-a-real-species" in capture["system"]
