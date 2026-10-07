import json
import logging
import time

import anthropic

from ..config import settings
from ..db import get_db
from ..sessions.service import get_session, get_session_stats
from ..vision.service import (
    CLAUDE_MAX_TOKENS,
    claude_response_text,
    claude_stop_reason,
    parse_claude_json,
)
from .models import ExperimentCreate, ExperimentUpdate

log = logging.getLogger(__name__)


def _parse_experiment(row: dict) -> dict:
    """Parse JSON text fields from an experiment DB row."""
    experiment = dict(row)
    try:
        experiment["dependent_variables"] = json.loads(experiment.get("dependent_variables") or "[]")
    except (json.JSONDecodeError, TypeError):
        experiment["dependent_variables"] = ["total_wet_yield_g", "colonization_days", "contamination_count"]
    return experiment


async def create_experiment(data: ExperimentCreate) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO experiments
               (title, hypothesis, control_session_id, variant_session_id,
                independent_variable, control_value, variant_value, dependent_variables)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.title, data.hypothesis, data.control_session_id, data.variant_session_id,
             data.independent_variable, data.control_value, data.variant_value,
             json.dumps(data.dependent_variables)),
        )
        await db.commit()
        experiment_id = cursor.lastrowid
    return await get_experiment(experiment_id)


async def get_experiment(experiment_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return _parse_experiment(row)


async def list_experiments(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM experiments WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [_parse_experiment(r) for r in await cursor.fetchall()]


async def update_experiment(experiment_id: int, data: ExperimentUpdate) -> dict | None:
    existing = await get_experiment(experiment_id)
    if not existing:
        return None

    dumped = data.model_dump()

    status = dumped["status"] if dumped["status"] is not None else existing["status"]
    conclusion = dumped["conclusion"] if dumped["conclusion"] is not None else existing["conclusion"]

    completed_at = existing["completed_at"]
    if status == "completed" and existing["status"] != "completed":
        completed_at = time.time()

        # Auto-generate comparison report on completion
        if not conclusion:
            comparison = await get_comparison(experiment_id)
            if comparison:
                metrics_summary = "; ".join(
                    f"{m['metric']}: {'variant' if m.get('winner') == 'variant' else 'control' if m.get('winner') == 'control' else 'tie'}"
                    + (f" ({m['pct_difference']:+.1f}%)" if m.get('pct_difference') is not None else "")
                    for m in comparison.get("metrics", [])
                )
                conclusion = f"Auto-generated: {metrics_summary}"

    async with get_db() as db:
        await db.execute(
            "UPDATE experiments SET status = ?, conclusion = ?, completed_at = ? WHERE id = ?",
            (status, conclusion, completed_at, experiment_id),
        )
        await db.commit()
    return await get_experiment(experiment_id)


# Metrics where the SMALLER value is the better outcome. Everything else
# (yield, BE, flush count) is higher-is-better.
LOWER_IS_BETTER = {"colonization_days", "contamination_count"}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pick_winner(metric: str, control_val, variant_val) -> str | None:
    """'control' | 'variant' | 'tie' for numeric values; None if not comparable."""
    if not (_is_number(control_val) and _is_number(variant_val)):
        return None
    if variant_val == control_val:
        return "tie"
    variant_better = variant_val < control_val if metric in LOWER_IS_BETTER else variant_val > control_val
    return "variant" if variant_better else "control"


async def _contamination_count(session: dict | None) -> int | None:
    """Logged contamination events for a session; a session whose status is
    'contaminated' counts at least once even with no event rows."""
    if not session:
        return None
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) AS n FROM contamination_events WHERE session_id = ?",
            (session["id"],),
        )
        count = (await cursor.fetchone())["n"]
    if session.get("status") == "contaminated":
        count = max(count, 1)
    return count


def _extract_metric(stats: dict | None, session: dict | None, metric: str):
    """Extract a metric value from stats or session data.

    Tries stats dict first, then session dict. Special case for
    'colonization_days' which is derived from phase_history.
    """
    if metric == "colonization_days" and session:
        phase_history = session.get("phase_history", [])
        for phase in phase_history:
            if phase["phase"] == "substrate_colonization" and phase.get("exited_at") and phase.get("entered_at"):
                return round((phase["exited_at"] - phase["entered_at"]) / 86400, 1)
        return None

    # Try stats dict first
    if stats and metric in stats:
        return stats[metric]

    # Fall back to session dict
    if session and metric in session:
        return session[metric]

    return None


async def get_comparison(experiment_id: int) -> dict | None:
    """Generate a comparison report for an experiment."""
    experiment = await get_experiment(experiment_id)
    if not experiment:
        return None

    control_stats = await get_session_stats(experiment["control_session_id"])
    variant_stats = await get_session_stats(experiment["variant_session_id"])
    control_session = await get_session(experiment["control_session_id"])
    variant_session = await get_session(experiment["variant_session_id"])

    metrics = []
    for dep_var in experiment["dependent_variables"]:
        if dep_var == "contamination_count":
            control_val = await _contamination_count(control_session)
            variant_val = await _contamination_count(variant_session)
        else:
            control_val = _extract_metric(control_stats, control_session, dep_var)
            variant_val = _extract_metric(variant_stats, variant_session, dep_var)

        winner = _pick_winner(dep_var, control_val, variant_val)
        pct_diff = None
        if winner is not None and control_val != 0:
            pct_diff = round(((variant_val - control_val) / abs(control_val)) * 100, 1)

        metrics.append({
            "metric": dep_var,
            "control_value": control_val,
            "variant_value": variant_val,
            "pct_difference": pct_diff,
            "winner": winner,
        })

    return {
        "experiment": experiment,
        "control_session": control_session,
        "variant_session": variant_session,
        "metrics": metrics,
    }


async def analyze_experiment(exp_id: int) -> dict | None:
    """Use Claude AI to analyze experiment results."""
    comparison = await get_comparison(exp_id)
    if not comparison:
        return None

    exp = comparison["experiment"]

    # Build analysis prompt
    metrics_text = "\n".join(
        f"- {c['metric']}: Control={c['control_value']}, Variant={c['variant_value']}, "
        f"Diff={c['pct_difference']}%, Winner={c['winner']}"
        for c in comparison["metrics"]
    )

    prompt = f"""Analyze this mushroom cultivation A/B experiment:

Hypothesis: {exp['hypothesis']}
Independent Variable: {exp['independent_variable']}
Control: {exp['control_value']}
Variant: {exp['variant_value']}

Results:
{metrics_text}

Provide a brief analysis in JSON format:
{{
    "summary": "2-3 sentence summary of findings",
    "hypothesis_supported": true/false,
    "confidence": "high/medium/low",
    "recommendations": ["actionable recommendation 1", "recommendation 2"]
}}"""

    if not settings.claude_api_key:
        return {"error": "Claude API not configured", "comparison": comparison}

    client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)
    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        # Rate limit / bad key / overloaded / retired model: report it with the
        # comparison instead of an unhandled 500.
        log.warning("Experiment %s analysis failed: %s", exp_id, e)
        return {"error": f"Claude analysis failed: {e.__class__.__name__}", "comparison": comparison}

    stop_reason = claude_stop_reason(response)
    if stop_reason == "refusal":
        return {"error": "Claude declined to analyze this experiment (refusal)", "comparison": comparison}
    # Text blocks only — content[0] need not be text (e.g. a thinking block).
    text = claude_response_text(response)
    parsed = parse_claude_json(text) if text else None
    if stop_reason == "max_tokens" and (parsed is None or "raw_response" in parsed):
        return {"error": "Claude analysis was cut off at max_tokens", "comparison": comparison}
    return {"analysis": parsed or {"raw": text}, "comparison": comparison}
