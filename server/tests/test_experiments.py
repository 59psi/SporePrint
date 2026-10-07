from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx

from app.db import get_db
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
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.experiments.service.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await analyze_experiment(exp["id"])

    assert result is not None
    assert "analysis" in result
    assert result["analysis"]["hypothesis_supported"] is True
    assert result["analysis"]["confidence"] == "high"
    assert "comparison" in result


# ── srv-rest#14: lower-is-better metrics + contamination_count ─────────


async def _set_colonization(session_id, days):
    base = 1_700_000_000.0
    async with get_db() as db:
        await db.execute(
            "UPDATE phase_history SET entered_at = ?, exited_at = ? "
            "WHERE session_id = ? AND phase = 'substrate_colonization'",
            (base, base + days * 86400, session_id),
        )
        await db.commit()


async def _add_contamination(session_id, n=1):
    async with get_db() as db:
        for _ in range(n):
            await db.execute(
                "INSERT INTO contamination_events (session_id, source, contamination_type) "
                "VALUES (?, 'manual', 'trich')",
                (session_id,),
            )
        await db.commit()


async def test_slower_colonization_does_not_win():
    control = await _make_session("Control")
    variant = await _make_session("Variant")
    await advance_phase(control["id"], PhaseAdvance(phase="primordia_induction"))
    await advance_phase(variant["id"], PhaseAdvance(phase="primordia_induction"))
    await _set_colonization(control["id"], 14)
    await _set_colonization(variant["id"], 21)

    exp = await _make_experiment(control["id"], variant["id"])
    comparison = await get_comparison(exp["id"])
    col = next(m for m in comparison["metrics"] if m["metric"] == "colonization_days")
    assert (col["control_value"], col["variant_value"]) == (14.0, 21.0)
    assert col["pct_difference"] == 50.0
    assert col["winner"] == "control"

    completed = await update_experiment(exp["id"], ExperimentUpdate(status="completed"))
    assert "colonization_days: control" in completed["conclusion"]


async def test_contamination_count_is_computed_and_lower_wins():
    control = await _make_session("Control")
    variant = await _make_session("Variant")
    await _add_contamination(variant["id"], 2)

    exp = await _make_experiment(control["id"], variant["id"])
    comparison = await get_comparison(exp["id"])
    cc = next(m for m in comparison["metrics"] if m["metric"] == "contamination_count")
    assert (cc["control_value"], cc["variant_value"]) == (0, 2)
    # control is 0 → no % difference, but a clean control still wins.
    assert cc["pct_difference"] is None
    assert cc["winner"] == "control"


async def test_higher_yield_still_wins():
    control = await _make_session("Control")
    variant = await _make_session("Variant")
    await add_harvest(control["id"], HarvestCreate(flush_number=1, wet_weight_g=100.0))
    await add_harvest(variant["id"], HarvestCreate(flush_number=1, wet_weight_g=50.0))
    exp = await _make_experiment(control["id"], variant["id"])
    comparison = await get_comparison(exp["id"])
    y = next(m for m in comparison["metrics"] if m["metric"] == "total_wet_yield_g")
    assert y["winner"] == "control"


async def test_non_numeric_metric_does_not_crash_comparison():
    control = await _make_session("Control")
    variant = await _make_session("Variant")
    exp = await _make_experiment(control["id"], variant["id"],
                                 dependent_variables=["flush_decline_pct", "name"])
    comparison = await get_comparison(exp["id"])
    assert all(m["winner"] is None for m in comparison["metrics"])


# ── srv-rest#28: /analyze error handling + POST ────────────────────────


async def test_analyze_api_error_returns_error_payload(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    control = await _make_session("Control")
    variant = await _make_session("Variant")
    exp = await _make_experiment(control["id"], variant["id"])

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    ))
    with patch("app.experiments.service.anthropic.AsyncAnthropic", return_value=mock_client):
        result = await analyze_experiment(exp["id"])

    assert "error" in result
    assert "comparison" in result
    assert "analysis" not in result


def test_analyze_endpoint_accepts_post(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "claude_api_key", "")
    c = client.post("/api/sessions", json={"name": "C", "species_profile_id": "blue_oyster"}).json()
    v = client.post("/api/sessions", json={"name": "V", "species_profile_id": "blue_oyster"}).json()
    exp = client.post("/api/experiments", json={
        "title": "t", "hypothesis": "h", "control_session_id": c["id"],
        "variant_session_id": v["id"], "independent_variable": "x",
        "control_value": "a", "variant_value": "b",
    }).json()
    r = client.post(f"/api/experiments/{exp['id']}/analyze")
    assert r.status_code == 200
    assert r.json()["error"] == "Claude API not configured"
    # The shipped Pi UI still calls GET; keep it working.
    assert client.get(f"/api/experiments/{exp['id']}/analyze").status_code == 200
    assert client.post("/api/experiments/9999/analyze").status_code == 404
