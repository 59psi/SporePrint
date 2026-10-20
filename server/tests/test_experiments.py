import anthropic
import httpx
import pytest

from app.config import settings
from app.db import get_db
from app.experiments import service as experiments_service
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
from tests._pi_c2_helpers import fake_anthropic


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


async def _pair():
    return await _make_session("Control"), await _make_session("Variant")


# ── CRUD ───────────────────────────────────────────────────────


async def test_create_stores_the_design_with_default_or_chosen_metrics():
    control, variant = await _pair()
    exp = await _make_experiment(control["id"], variant["id"])
    assert (exp["status"], exp["completed_at"]) == ("active", None)
    assert (exp["control_session_id"], exp["variant_session_id"]) == (control["id"], variant["id"])
    assert "total_wet_yield_g" in exp["dependent_variables"]
    assert await get_experiment(exp["id"]) == exp

    chosen = await _make_experiment(control["id"], variant["id"],
                                    dependent_variables=["total_wet_yield_g", "flush_count"])
    assert chosen["dependent_variables"] == ["total_wet_yield_g", "flush_count"]


async def test_list_experiments_filter_status():
    s1 = await _make_session("Control")
    s2 = await _make_session("Variant")
    s3 = await _make_session("Control 2")
    s4 = await _make_session("Variant 2")
    await _make_experiment(s1["id"], s2["id"], title="Active Exp")
    exp2 = await _make_experiment(s3["id"], s4["id"], title="Completed Exp")
    await update_experiment(exp2["id"], ExperimentUpdate(status="completed"))

    assert len(await list_experiments()) == 2
    assert [e["title"] for e in await list_experiments(status="active")] == ["Active Exp"]
    assert [e["title"] for e in await list_experiments(status="completed")] == ["Completed Exp"]


async def test_completing_stamps_completed_at_once():
    control, variant = await _pair()
    exp = await _make_experiment(control["id"], variant["id"])

    completed = await update_experiment(exp["id"], ExperimentUpdate(
        status="completed",
        conclusion="Manure substrate produced 30% higher yields",
    ))
    assert completed["status"] == "completed"
    assert completed["conclusion"] == "Manure substrate produced 30% higher yields"
    assert completed["completed_at"] is not None

    # Editing the conclusion later does not move completed_at
    updated = await update_experiment(exp["id"], ExperimentUpdate(conclusion="Updated conclusion"))
    assert updated["completed_at"] == completed["completed_at"]


def test_experiment_routes_answer_404_for_an_unknown_experiment(client):
    assert client.get("/api/experiments/9999").status_code == 404
    assert client.patch("/api/experiments/9999", json={"status": "cancelled"}).status_code == 404
    assert client.get("/api/experiments/9999/comparison").status_code == 404
    assert client.post("/api/experiments/9999/analyze").status_code == 404


# ── Comparison ─────────────────────────────────────────────────


@pytest.mark.parametrize(("control_g", "variant_g", "winner"), [
    ((200.0, 150.0), (300.0, 200.0), "variant"),
    ((100.0,), (50.0,), "control"),
], ids=["variant-yields-more", "control-yields-more"])
async def test_the_higher_yield_wins(control_g, variant_g, winner):
    control, variant = await _pair()
    for session, flushes in ((control, control_g), (variant, variant_g)):
        for flush, grams in enumerate(flushes, 1):
            await add_harvest(session["id"], HarvestCreate(flush_number=flush, wet_weight_g=grams))
    exp = await _make_experiment(control["id"], variant["id"])

    comparison = await get_comparison(exp["id"])
    assert comparison["experiment"]["id"] == exp["id"]
    assert (comparison["control_session"]["id"], comparison["variant_session"]["id"]) == (
        control["id"], variant["id"])
    y = next(m for m in comparison["metrics"] if m["metric"] == "total_wet_yield_g")
    assert (y["control_value"], y["variant_value"], y["winner"]) == (sum(control_g), sum(variant_g), winner)
    assert y["pct_difference"] == round((sum(variant_g) - sum(control_g)) / sum(control_g) * 100, 1)


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
    control, variant = await _pair()
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
    control, variant = await _pair()
    await _add_contamination(variant["id"], 2)

    exp = await _make_experiment(control["id"], variant["id"])
    comparison = await get_comparison(exp["id"])
    cc = next(m for m in comparison["metrics"] if m["metric"] == "contamination_count")
    assert (cc["control_value"], cc["variant_value"]) == (0, 2)
    # control is 0 → no % difference, but a clean control still wins.
    assert cc["pct_difference"] is None
    assert cc["winner"] == "control"


async def test_non_numeric_metric_does_not_crash_comparison():
    control, variant = await _pair()
    exp = await _make_experiment(control["id"], variant["id"],
                                 dependent_variables=["flush_decline_pct", "name"])
    comparison = await get_comparison(exp["id"])
    assert all(m["winner"] is None for m in comparison["metrics"])


# ── AI analysis ────────────────────────────────────────────────

_ANALYSIS = {"summary": "Variant outperformed control.", "hypothesis_supported": True,
             "confidence": "high", "recommendations": ["Use variant substrate"]}


@pytest.mark.parametrize(("reply", "stop_reason", "error"), [
    (_ANALYSIS, "end_turn", None),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
     "end_turn", "Claude analysis failed: APIConnectionError"),
    ("I can't help with that.", "refusal", "Claude declined to analyze this experiment (refusal)"),
    ('{"summary": "Variant outperf', "max_tokens", "Claude analysis was cut off at max_tokens"),
], ids=["parsed", "api-error", "refusal", "cut-off"])
async def test_analysis_answers_the_parsed_reply_or_says_why_not(reply, stop_reason, error, monkeypatch):
    """Whatever Claude answers (or fails to), the comparison comes back; an
    unusable answer is an error the dashboard shows, never a 500."""
    monkeypatch.setattr(settings, "claude_api_key", "test-key")
    monkeypatch.setattr(experiments_service.anthropic, "AsyncAnthropic",
                        fake_anthropic(reply, stop_reason=stop_reason))
    control, variant = await _pair()
    exp = await _make_experiment(control["id"], variant["id"])

    result = await analyze_experiment(exp["id"])
    assert result["comparison"]["experiment"]["id"] == exp["id"]
    if error is None:
        assert result["analysis"] == _ANALYSIS
    else:
        assert (result["error"], "analysis" in result) == (error, False)


def test_analyze_endpoint_accepts_post(client, monkeypatch):
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
    # No API key: the comparison still comes back, with the reason.
    assert r.json()["error"] == "Claude API not configured"
    assert r.json()["comparison"]["experiment"]["id"] == exp["id"]
    # Dashboard bundles from before the move to POST still call GET (a
    # server-only update keeps the bundle a Pi serves); keep it working.
    assert client.get(f"/api/experiments/{exp['id']}/analyze").status_code == 200
    # Only the POST is current: the API schema says so of the GET.
    paths = client.app.openapi()["paths"]
    analyze = paths["/api/experiments/{experiment_id}/analyze"]
    assert analyze["get"].get("deprecated") is True
    assert not analyze["post"].get("deprecated")


# ── Input the comparison cannot use ─────────────────────────────


_BODY = {"title": "t", "hypothesis": "h", "independent_variable": "x",
         "control_value": "a", "variant_value": "b"}


def test_a_session_compared_with_itself_is_422(client):
    """Every metric of a session against itself is a tie; the pair was
    accepted (and the paid analysis ran on it)."""
    s = client.post("/api/sessions", json={"name": "S", "species_profile_id": "blue_oyster"}).json()
    r = client.post("/api/experiments", json={
        **_BODY, "control_session_id": s["id"], "variant_session_id": s["id"]})
    assert r.status_code == 422
    assert client.get("/api/experiments").json() == []


def test_unknown_sessions_are_422_not_500(client):
    s = client.post("/api/sessions", json={"name": "S", "species_profile_id": "blue_oyster"}).json()
    r = client.post("/api/experiments", json={
        **_BODY, "control_session_id": s["id"], "variant_session_id": 9999})
    assert r.status_code == 422, r.text  # was a FOREIGN KEY 500
    assert "variant_session_id 9999" in r.json()["detail"]


async def test_status_is_one_of_the_three_states(client):
    control, variant = await _pair()
    exp = await _make_experiment(control["id"], variant["id"])
    for bad in ("Completed", "done", ""):
        r = client.patch(f"/api/experiments/{exp['id']}", json={"status": bad})
        assert r.status_code == 422, bad
    assert (await get_experiment(exp["id"]))["status"] == "active"
    r = client.patch(f"/api/experiments/{exp['id']}", json={"status": "cancelled"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
