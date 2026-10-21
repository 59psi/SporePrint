import json

from app.db import get_db
from app.sessions.models import SessionCreate, PhaseAdvance, HarvestCreate
from app.sessions.service import abort_session, add_harvest, advance_phase, create_session, get_session
from app.species.models import GrowPhase
from app.species.service import get_profile, seed_builtins
from app.transcript.service import export_json, export_markdown


async def test_export_json_carries_every_section_and_the_harvests():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Transcript Test", species_profile_id="blue_oyster"))
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0, dry_weight_g=15.0))

    data = await export_json(s["id"])
    assert data["version"] == "1.0"
    assert data["session"]["name"] == "Transcript Test"
    assert {"exported_at", "species_profile", "phase_timeline", "phase_telemetry", "events", "harvests",
            "notes", "vision_analyses", "automation_summary", "analysis_prompt_hint"} <= set(data)
    assert [(h["flush_number"], h["wet_weight_g"]) for h in data["harvests"]] == [(1, 150.0)]


async def test_export_markdown_header_omits_unset_fields():
    """NULL session columns are left out, never printed as Python ``None``."""
    await seed_builtins()
    s = await create_session(
        SessionCreate(name="Sparse", species_profile_id="lions_mane", substrate="masters_mix")
    )
    md = await export_markdown(s["id"])
    assert "None" not in md
    assert "- **Species**: Lion's Mane (*Hericium erinaceus*)" in md
    # substrate set, volume unset → no empty parentheses
    assert "- **Substrate**: masters_mix\n" in md
    # neither inoculation date nor method → no line at all
    assert "Inoculated" not in md
    assert "- **Status**: active" in md


async def test_export_markdown_header_keeps_set_details():
    await seed_builtins()
    s = await create_session(
        SessionCreate(
            name="Full",
            species_profile_id="blue_oyster",
            substrate="straw",
            substrate_volume="10 L",
            inoculation_date="2026-09-01",
            inoculation_method="grain spawn",
        )
    )
    md = await export_markdown(s["id"])
    assert md.startswith("# Session: Full")
    assert "- **Substrate**: straw (10 L)" in md
    assert "- **Inoculated**: 2026-09-01 (grain spawn)" in md
    assert "## Yield" in md and "## Phase Timeline" in md


async def test_export_markdown_marks_an_unweighed_harvest_with_a_question_mark():
    """The weight columns are NULL when not weighed: the lines printed
    "Noneg dry" / "Noneg wet"."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Weights", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, dry_weight_g=20.0))
    md = await export_markdown(s["id"])
    assert "None" not in md
    assert "## Harvests" in md
    assert "- Flush #1: 200.0g wet, ?g dry" in md
    assert "- Flush #2: ?g wet, 20.0g dry" in md


async def test_export_markdown_prints_unknown_for_a_null_health_assessment():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Vision", species_profile_id="blue_oyster"))
    async with get_db() as db:
        await db.execute(
            "INSERT INTO vision_frames (session_id, node_id, timestamp, file_path, analysis_claude) "
            "VALUES (?, 'cam-01', 1752300000, '/tmp/f.jpg', ?)",
            (s["id"], json.dumps({"health_assessment": None, "summary": "too dark to read"})))
        await db.commit()
    md = await export_markdown(s["id"])
    vision = md.split("## Vision Analysis", 1)[1]
    assert "— unknown" in vision and "None" not in md


async def test_export_markdown_lists_an_abort_under_key_events():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Aborted", species_profile_id="blue_oyster"))
    await abort_session(s["id"])
    md = await export_markdown(s["id"])
    key_events = md.split("## Key Events", 1)[1]
    assert "Session aborted" in key_events


async def test_export_json_decodes_the_phase_targets_snapshot():
    """phase_timeline[].params_snapshot went out as a JSON string inside the
    JSON (double-encoded), unlike the same rows from GET /api/sessions/{id}."""
    await seed_builtins()
    s = await create_session(SessionCreate(name="Snapshot", species_profile_id="blue_oyster"))
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    data = await export_json(s["id"])
    session = await get_session(s["id"])
    timeline = data["phase_timeline"]
    assert [p["phase"] for p in timeline] == ["substrate_colonization", "fruiting"]
    for exported, stored in zip(timeline, session["phase_history"], strict=True):
        assert isinstance(exported["params_snapshot"], dict)
        assert exported["params_snapshot"] == stored["params_snapshot"]
    fruiting = (await get_profile("blue_oyster")).phases[GrowPhase.FRUITING]
    assert timeline[1]["params_snapshot"]["temp_min_f"] == fruiting.temp_min_f
