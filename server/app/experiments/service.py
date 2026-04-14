import json
import time

from ..db import get_db
from ..sessions.service import get_session, get_session_stats
from .models import ExperimentCreate, ExperimentUpdate


def _parse_experiment(row: dict) -> dict:
    """Parse JSON text fields from an experiment DB row."""
    experiment = dict(row)
    experiment["dependent_variables"] = json.loads(experiment.get("dependent_variables") or "[]")
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

    async with get_db() as db:
        await db.execute(
            "UPDATE experiments SET status = ?, conclusion = ?, completed_at = ? WHERE id = ?",
            (status, conclusion, completed_at, experiment_id),
        )
        await db.commit()
    return await get_experiment(experiment_id)


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
        control_val = _extract_metric(control_stats, control_session, dep_var)
        variant_val = _extract_metric(variant_stats, variant_session, dep_var)

        pct_diff = None
        winner = None
        if control_val is not None and variant_val is not None and control_val != 0:
            pct_diff = round(((variant_val - control_val) / abs(control_val)) * 100, 1)
            if variant_val > control_val:
                winner = "variant"
            elif control_val > variant_val:
                winner = "control"
            else:
                winner = "tie"

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
    from ..config import settings

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

    import anthropic

    from ..vision.service import parse_claude_json

    client = anthropic.Anthropic(api_key=settings.claude_api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    parsed = parse_claude_json(text)
    return {"analysis": parsed or {"raw": text}, "comparison": comparison}
