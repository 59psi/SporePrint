from app.sessions.models import SessionCreate, PhaseAdvance, HarvestCreate
from app.sessions.service import create_session, advance_phase, add_harvest
from app.species.service import seed_builtins
from app.transcript.service import export_json, export_markdown


async def test_export_json_structure():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Transcript Test", species_profile_id="cubensis_golden_teacher"))
    await advance_phase(s["id"], PhaseAdvance(phase="fruiting"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))

    data = await export_json(s["id"])
    assert data["version"] == "1.0"
    assert "exported_at" in data
    assert data["session"]["name"] == "Transcript Test"
    assert "species_profile" in data
    assert "phase_timeline" in data
    assert "phase_telemetry" in data
    assert "events" in data
    assert "harvests" in data
    assert "notes" in data
    assert "vision_analyses" in data
    assert "automation_summary" in data
    assert "analysis_prompt_hint" in data


async def test_export_json_has_harvest():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Harvest Test", species_profile_id="cubensis_golden_teacher"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=150.0, dry_weight_g=15.0))
    data = await export_json(s["id"])
    assert len(data["harvests"]) == 1
    assert data["harvests"][0]["wet_weight_g"] == 150.0


async def test_export_markdown_format():
    await seed_builtins()
    s = await create_session(SessionCreate(name="MD Test", species_profile_id="cubensis_golden_teacher"))
    md = await export_markdown(s["id"])
    assert md.startswith("# Session: MD Test")
    assert "## Yield" in md
    assert "## Phase Timeline" in md


async def test_export_markdown_includes_harvest():
    await seed_builtins()
    s = await create_session(SessionCreate(name="Harvest MD", species_profile_id="cubensis_golden_teacher"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    md = await export_markdown(s["id"])
    assert "## Harvests" in md
    assert "Flush #1" in md
