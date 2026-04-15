from unittest.mock import MagicMock, patch

from app.experiments.models import ExperimentCreate, ExperimentUpdate
from app.experiments.service import (
    create_experiment,
    get_experiment,
    list_experiments,
    update_experiment,
    get_comparison,
    analyze_experiment,
)
from app.sessions.models import SessionCreate, HarvestCreate
from app.sessions.service import create_session, add_harvest, advance_phase
from app.sessions.models import PhaseAdvance


async def _make_session(name, species="blue_oyster"):
    return await create_session(SessionCreate(
        name=name,
        species_profile_id=species,
        substrate="CVG",
        substrate_volume="5 quarts",
    ))


async def _make_experiment(control_id, variant_id, **overrides):
    defaults = dict(
        title="CVG vs Manure Substrate Test",
        hypothesis="Manure substrate produces higher yields than CVG",
        control_session_id=control_id,
        variant_session_id=variant_id,
        independent_variable="substrate",
        control_value="CVG",
        variant_value="manure-based",
    )
    defaults.update(overrides)
    return await create_experiment(ExperimentCreate(**defaults))


# ── CRUD ───────────────────────────────────────────────────────


async def test_create_experiment():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    exp = await _make_experiment(s1["id"], s2["id"])

    assert exp["id"] is not None
    assert exp["title"] == "CVG vs Manure Substrate Test"
    assert exp["status"] == "active"
    assert exp["control_session_id"] == s1["id"]
    assert exp["variant_session_id"] == s2["id"]
    assert "total_wet_yield_g" in exp["dependent_variables"]
    assert exp["completed_at"] is None


async def test_create_experiment_custom_dependent_vars():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    exp = await _make_experiment(
        s1["id"], s2["id"],
        dependent_variables=["total_wet_yield_g", "flush_count"],
    )
    assert exp["dependent_variables"] == ["total_wet_yield_g", "flush_count"]


async def test_get_experiment():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    exp = await _make_experiment(s1["id"], s2["id"])
    fetched = await get_experiment(exp["id"])
    assert fetched["id"] == exp["id"]
    assert fetched["hypothesis"] == exp["hypothesis"]


async def test_get_experiment_not_found():
    result = await get_experiment(9999)
    assert result is None


async def test_list_experiments():
    s1 = await _make_session("Control 1")
    s2 = await _make_session("Variant 1")
    s3 = await _make_session("Control 2")
    s4 = await _make_session("Variant 2")
    await _make_experiment(s1["id"], s2["id"], title="Exp 1")
    await _make_experiment(s3["id"], s4["id"], title="Exp 2")
    exps = await list_experiments()
    assert len(exps) == 2


async def test_list_experiments_filter_status():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    s3 = await _make_session("Control 2")
    s4 = await _make_session("Variant 2")
    exp1 = await _make_experiment(s1["id"], s2["id"], title="Active Exp")
    exp2 = await _make_experiment(s3["id"], s4["id"], title="Completed Exp")
    await update_experiment(exp2["id"], ExperimentUpdate(status="completed"))

    active = await list_experiments(status="active")
    assert len(active) == 1
    assert active[0]["title"] == "Active Exp"

    completed = await list_experiments(status="completed")
    assert len(completed) == 1
    assert completed[0]["title"] == "Completed Exp"


async def test_update_experiment_status():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    exp = await _make_experiment(s1["id"], s2["id"])

    updated = await update_experiment(exp["id"], ExperimentUpdate(
        status="completed",
        conclusion="Manure substrate produced 30% higher yields",
    ))
    assert updated["status"] == "completed"
    assert updated["conclusion"] == "Manure substrate produced 30% higher yields"
    assert updated["completed_at"] is not None


async def test_update_experiment_not_found():
    result = await update_experiment(9999, ExperimentUpdate(status="cancelled"))
    assert result is None


async def test_completed_at_only_set_once():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    exp = await _make_experiment(s1["id"], s2["id"])

    completed = await update_experiment(exp["id"], ExperimentUpdate(status="completed"))
    first_ts = completed["completed_at"]

    # Updating conclusion should not change completed_at
    updated = await update_experiment(exp["id"], ExperimentUpdate(conclusion="Updated conclusion"))
    assert updated["completed_at"] == first_ts


# ── Full lifecycle with comparison ─────────────────────────────


async def test_full_lifecycle_with_comparison():
    """Create 2 sessions, create experiment, add harvests, get comparison, complete."""
    # Create sessions
    control = await _make_session("Control Grow")
    variant = await _make_session("Variant Grow")

    # Add harvests to control
    await add_harvest(control["id"], HarvestCreate(
        flush_number=1, wet_weight_g=200.0,
    ))
    await add_harvest(control["id"], HarvestCreate(
        flush_number=2, wet_weight_g=150.0,
    ))

    # Add harvests to variant (higher yield)
    await add_harvest(variant["id"], HarvestCreate(
        flush_number=1, wet_weight_g=300.0,
    ))
    await add_harvest(variant["id"], HarvestCreate(
        flush_number=2, wet_weight_g=200.0,
    ))

    # Create experiment
    exp = await _make_experiment(control["id"], variant["id"])

    # Get comparison
    comparison = await get_comparison(exp["id"])
    assert comparison is not None
    assert comparison["experiment"]["id"] == exp["id"]
    assert comparison["control_session"] is not None
    assert comparison["variant_session"] is not None

    # Check metrics
    metrics = comparison["metrics"]
    assert len(metrics) > 0

    # Find the total_wet_yield_g metric
    yield_metric = next(m for m in metrics if m["metric"] == "total_wet_yield_g")
    assert yield_metric["control_value"] == 350.0
    assert yield_metric["variant_value"] == 500.0
    assert yield_metric["winner"] == "variant"
    assert yield_metric["pct_difference"] is not None

    # Complete the experiment
    completed = await update_experiment(exp["id"], ExperimentUpdate(
        status="completed",
        conclusion="Variant substrate produced significantly higher yields",
    ))
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None


async def test_comparison_not_found():
    result = await get_comparison(9999)
    assert result is None


async def test_comparison_with_colonization_days():
    """Verify colonization_days metric is extracted from phase_history."""
    control = await _make_session("Control")
    variant = await _make_session("Variant")

    # Advance phases to create phase_history entries with exited_at
    await advance_phase(control["id"], PhaseAdvance(phase="primordia_induction", trigger="manual"))
    await advance_phase(variant["id"], PhaseAdvance(phase="primordia_induction", trigger="manual"))

    exp = await _make_experiment(
        control["id"], variant["id"],
        dependent_variables=["colonization_days"],
    )

    comparison = await get_comparison(exp["id"])
    assert comparison is not None
    metrics = comparison["metrics"]
    col_metric = next(m for m in metrics if m["metric"] == "colonization_days")
    # Both should have a value since phase was advanced (exited_at set)
    assert col_metric["control_value"] is not None
    assert col_metric["variant_value"] is not None


# ── AI Analysis ───────────────────────────────────────────────


async def test_analyze_experiment_no_api_key(monkeypatch):
    """Without Claude API key, returns error with comparison data."""
    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "")

    control = await _make_session("Control")
    variant = await _make_session("Variant")
    await add_harvest(control["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    await add_harvest(variant["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))

    exp = await _make_experiment(control["id"], variant["id"])
    result = await analyze_experiment(exp["id"])
    assert result is not None
    assert result["error"] == "Claude API not configured"
    assert "comparison" in result


async def test_analyze_experiment_not_found():
    result = await analyze_experiment(9999)
    assert result is None


async def test_analyze_experiment_with_mock_claude(monkeypatch):
    """With API key set, calls Claude and returns parsed analysis."""
    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "test-key")

    control = await _make_session("Control")
    variant = await _make_session("Variant")
    await add_harvest(control["id"], HarvestCreate(flush_number=1, wet_weight_g=200.0))
    await add_harvest(variant["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))

    exp = await _make_experiment(control["id"], variant["id"])

    fake_json = '{"summary": "Variant outperformed control.", "hypothesis_supported": true, "confidence": "high", "recommendations": ["Use variant substrate"]}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=fake_json)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = await analyze_experiment(exp["id"])

    assert result is not None
    assert "analysis" in result
    assert result["analysis"]["hypothesis_supported"] is True
    assert result["analysis"]["confidence"] == "high"
    assert "comparison" in result
