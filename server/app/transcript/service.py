import json
import time
from collections import Counter

import anthropic

from ..config import settings
from ..db import get_db
from ..sessions.service import _decode_phase_row, chamber_nodes_running, phase_params_source
from ..species.models import GrowPhase, SpeciesProfile
from ..species.service import get_profile
from ..vision.service import (
    CLAUDE_MAX_TOKENS,
    _deserialize_frame,
    claude_response_text,
    claude_stop_reason,
    parse_claude_json,
)

# Upper bound on Claude vision summaries sent with a session analysis. Auto
# analysis runs up to every 15 min (96/day), so a long grow would otherwise
# overflow the model's context window. ~150 entries is roughly 15K tokens.
_MAX_VISION_SUMMARIES = 150

# Session events the markdown export lists under "Key Events". A phase-exit
# reminder is the manual step owed on leaving a phase (shiitake browning's
# cold-water soak) — the record of when it was due belongs in the narrative,
# and so does an aborted grow's end.
_KEY_EVENT_TYPES = frozenset({
    "phase_change", "phase_exit_reminder", "harvest", "session_created", "session_completed",
    "session_aborted",
})

# The setpoints a session analysis compares each phase's telemetry against
# (PhaseParams fields): the temperature, humidity, CO2 and FAE bands, the
# light schedule and the expected duration. Prose, citations and alert
# tuning stay out to keep the request small.
_ENVIRONMENT_TARGET_FIELDS = (
    "temp_min_f", "temp_max_f", "temp_swing_required", "temp_swing_delta_f",
    "humidity_min", "humidity_max", "co2_min_ppm", "co2_max_ppm",
    "fae_mode", "fae_interval_min", "fae_duration_sec",
)
_ANALYSIS_TARGET_FIELDS = _ENVIRONMENT_TARGET_FIELDS + (
    "light_hours_on", "light_hours_off", "light_spectrum", "light_lux_target",
    "expected_duration_days",
)


def _analysis_targets(params: dict | None,
                      fields: tuple[str, ...] = _ANALYSIS_TARGET_FIELDS) -> dict | None:
    """The comparison setpoints of one phase's params, unset ones left out."""
    if not isinstance(params, dict):
        return None
    return {k: params[k] for k in fields if params.get(k) is not None}


def _phase_targets(phase_row: dict, profile: SpeciesProfile | None) -> tuple[dict | None, str | None]:
    """(targets, where they came from) for one phase_history row.

    The setpoints frozen at phase entry (params_snapshot) are what the grow
    actually ran on, so they win: a later edit to a custom profile does not
    rewrite them. A row with no snapshot (a session from before snapshots, or
    a phase its profile does not define) falls back to the profile's current
    params for that phase. A phase that runs on another phase's setpoints
    (PHASE_PARAM_FALLBACKS: rest on fruiting, say) gets only that phase's
    environment bands, named in the source: its light schedule (rest runs
    dark) and its expected duration are not this phase's.
    """
    snapshot = _analysis_targets(phase_row.get("params_snapshot"))
    if snapshot:
        return snapshot, "frozen at phase entry"
    if profile is None:
        return None, None
    phase = phase_row.get("phase")
    source = phase_params_source({p.value for p in profile.phases}, phase)
    if source is None:
        return None, None
    params = profile.phases[GrowPhase(source)].model_dump()
    if source == phase:
        return _analysis_targets(params), "species profile"
    return (_analysis_targets(params, _ENVIRONMENT_TARGET_FIELDS),
            f"species profile: {source}'s temperature, humidity, CO2 and FAE bands, "
            f"which {phase} runs on (no light or duration target)")


async def _session_node_ids(db, session: dict) -> list[str] | None:
    """Nodes whose telemetry describes this session's environment.

    The nodes that produced session-tagged readings, plus the session's
    chamber nodes, plus the nodes of every chamber the (active) session is
    the grow of (a chamberless session running a chamber with no grow of its
    own: sessions.service.chamber_nodes_running). None means "every node": a
    chamberless session whose tagged raw rows have aged out into rollups
    (which carry no session_id), i.e. the single-closet default where every
    sensor node is in the grow space.
    """
    cursor = await db.execute(
        "SELECT DISTINCT node_id FROM telemetry_readings WHERE session_id = ?",
        (session["id"],),
    )
    nodes = {r["node_id"] for r in await cursor.fetchall()}
    nodes.update(await chamber_nodes_running(session["id"]))
    if session.get("chamber_id") is not None:
        cursor = await db.execute(
            "SELECT node_ids FROM chambers WHERE id = ?", (session["chamber_id"],)
        )
        row = await cursor.fetchone()
        if row:
            try:
                nodes.update(str(n) for n in json.loads(row["node_ids"] or "[]"))
            except (json.JSONDecodeError, TypeError):
                pass
    return sorted(nodes) or None


# Raw rows and every rollup tier in one pass. `:nodes` is a JSON array of node
# ids, or NULL for every node.
_PHASE_SUMMARY_SQL = """
    SELECT sensor, MIN(mn) AS min_val, MAX(mx) AS max_val,
           SUM(total) / SUM(n) AS avg_val, SUM(n) AS count
    FROM (
        SELECT sensor, MIN(value) AS mn, MAX(value) AS mx,
               SUM(value) AS total, COUNT(*) AS n
          FROM telemetry_readings
         WHERE timestamp BETWEEN :start AND :end
           AND (:nodes IS NULL OR node_id IN (SELECT value FROM json_each(:nodes)))
         GROUP BY sensor
        UNION ALL
        SELECT sensor, MIN(min_value), MAX(max_value),
               SUM(avg_value * COALESCE(count, 1)), SUM(COALESCE(count, 1))
          FROM telemetry_rollups
         WHERE timestamp BETWEEN :start AND :end AND avg_value IS NOT NULL
           AND (:nodes IS NULL OR node_id IN (SELECT value FROM json_each(:nodes)))
         GROUP BY sensor
    )
    GROUP BY sensor
"""


async def _telemetry_summary(db, node_ids: list[str] | None, start: float, end: float) -> dict:
    """Per-sensor min/max/avg/count over [start, end] from raw AND rollup rows.

    Retention moves each reading from raw into exactly one rollup tier, so the
    two sources never overlap. Rollup means are weighted by their counts.
    """
    cursor = await db.execute(
        _PHASE_SUMMARY_SQL,
        {
            "start": start,
            "end": end,
            "nodes": json.dumps(node_ids) if node_ids is not None else None,
        },
    )
    return {row["sensor"]: {
        "min": round(row["min_val"], 1),
        "max": round(row["max_val"], 1),
        "avg": round(row["avg_val"], 1),
        "count": row["count"],
    } for row in await cursor.fetchall()}


def _thin_evenly(items: list[dict], keep: int) -> list[dict]:
    """`keep` items spread evenly across `items`, always including the last."""
    if keep <= 0:
        return []
    if len(items) <= keep:
        return items
    if keep == 1:
        return [items[-1]]
    step = (len(items) - 1) / (keep - 1)
    return [items[round(i * step)] for i in range(keep)]


def _select_vision_summaries(
    analyses: list[dict], max_entries: int = _MAX_VISION_SUMMARIES,
) -> list[dict]:
    """Reduce Claude vision analyses to a bounded, chronological digest.

    Keeps the latest analysis per (UTC day, assessment): each day's healthy
    snapshot plus every day that saw a concern or contamination. Over the cap,
    healthy days are thinned first, then everything, evenly across the grow.
    The most recent analysis is always kept.
    """
    entries = []
    for v in analyses:
        claude = v.get("analysis_claude")
        if not isinstance(claude, dict) or claude.get("error"):
            continue
        entries.append({
            "timestamp": v["timestamp"],
            "claude_assessment": claude.get("health_assessment"),
            "claude_summary": claude.get("summary"),
        })
    if not entries:
        return []
    entries.sort(key=lambda e: e["timestamp"])

    latest_per_day: dict[tuple, dict] = {}
    for e in entries:
        latest_per_day[(int(e["timestamp"] // 86400), e["claude_assessment"])] = e
    # The newest analysis is its own day's latest, so it sorts last here.
    selected = sorted(latest_per_day.values(), key=lambda e: e["timestamp"])

    if len(selected) > max_entries:
        newest, rest = selected[-1], selected[:-1]
        budget = max_entries - 1
        flagged = [e for e in rest if e["claude_assessment"] != "healthy"]
        healthy = [e for e in rest if e["claude_assessment"] == "healthy"]
        if len(flagged) >= budget:
            keep = _thin_evenly(flagged, budget)
        else:
            keep = flagged + _thin_evenly(healthy, budget - len(flagged))
        selected = sorted(keep, key=lambda e: e["timestamp"]) + [newest]
    return selected


async def export_json(session_id: int) -> dict | None:
    """Export complete session transcript as structured JSON (None if unknown)."""
    built = await _build_transcript(session_id)
    return built[0] if built is not None else None


async def _build_transcript(session_id: int) -> tuple[dict, SpeciesProfile | None] | None:
    """(export_json's transcript, the session's species profile or None), or
    None for an unknown session."""
    async with get_db() as db:
        # Session
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        session = dict(row)

        # Phase history, params_snapshot decoded as get_session() returns it
        # (it went out double-encoded, as a JSON string inside the JSON).
        cursor = await db.execute(
            "SELECT * FROM phase_history WHERE session_id = ? ORDER BY entered_at", (session_id,)
        )
        phases = [_decode_phase_row(r) for r in await cursor.fetchall()]

        # Events
        cursor = await db.execute(
            # id breaks same-second ties (exit reminder before its phase change)
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp, id", (session_id,)
        )
        events = [dict(r) for r in await cursor.fetchall()]

        # Harvests
        cursor = await db.execute(
            "SELECT * FROM harvests WHERE session_id = ? ORDER BY timestamp", (session_id,)
        )
        harvests = [dict(r) for r in await cursor.fetchall()]

        # Notes
        cursor = await db.execute(
            "SELECT * FROM session_notes WHERE session_id = ? ORDER BY timestamp", (session_id,)
        )
        notes = [dict(r) for r in await cursor.fetchall()]

        # Vision analyses
        cursor = await db.execute(
            "SELECT id, timestamp, analysis_local, analysis_claude FROM vision_frames WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        vision = [_deserialize_frame(r) for r in await cursor.fetchall()]

        # Telemetry summary per phase: the session's node(s) over each phase
        # window, raw rows plus the rollups older data has been compressed into.
        node_ids = await _session_node_ids(db, session)
        phase_telemetry = []
        for phase in phases:
            entered = phase["entered_at"]
            exited = phase["exited_at"] or session.get("completed_at") or time.time()
            stats = await _telemetry_summary(db, node_ids, entered, exited)

            phase_telemetry.append({
                "phase": phase["phase"],
                "duration_hours": round((exited - entered) / 3600, 1),
                "telemetry_summary": stats,
            })

        # Automation firings
        cursor = await db.execute(
            "SELECT rule_name, COUNT(*) as count FROM automation_firings WHERE session_id = ? GROUP BY rule_name",
            (session_id,),
        )
        automation = [dict(r) for r in await cursor.fetchall()]

    # Species profile
    profile = await get_profile(session["species_profile_id"])
    profile_data = profile.model_dump() if profile else None

    transcript = {
        "version": "1.0",
        "exported_at": time.time(),
        "session": session,
        "species_profile": profile_data,
        "phase_timeline": phases,
        "phase_telemetry": phase_telemetry,
        "events": events,
        "harvests": harvests,
        "notes": notes,
        "vision_analyses": vision,
        "automation_summary": automation,
        "analysis_prompt_hint": (
            "Analyze this mushroom cultivation session. Compare actual conditions against "
            "species profile targets for each phase. Identify issues, assess yield, and "
            "provide recommendations for the next run."
        ),
    }
    return transcript, profile


def _md_field(label: str, value, detail=None) -> str | None:
    """One header line, ``- **Label**: value (detail)``, or None to leave it out.

    Unset session columns are NULL, so ``session.get(key, 'N/A')`` printed a
    literal ``None``; a missing value drops the line and a missing detail drops
    the parentheses. Only the detail is shown when the value is unset.
    """
    def text(v) -> str:
        return "" if v is None else str(v).strip()

    main, extra = text(value), text(detail)
    if not main and not extra:
        return None
    if main and extra:
        return f"- **{label}**: {main} ({extra})"
    return f"- **{label}**: {main or extra}"


async def export_markdown(session_id: int) -> str | None:
    """Export session transcript as human-readable markdown (None if unknown)."""
    data = await export_json(session_id)
    if data is None:
        return None
    session = data["session"]
    # A custom profile can be deleted after sessions reference it.
    profile = data.get("species_profile") or {}
    scientific = profile.get("scientific_name")

    header = [
        _md_field(
            "Species",
            profile.get("common_name") or session["species_profile_id"],
            f"*{scientific}*" if scientific else None,
        ),
        _md_field("Category", profile.get("category")),
        _md_field("Substrate", session.get("substrate"), session.get("substrate_volume")),
        _md_field("Inoculated", session.get("inoculation_date"), session.get("inoculation_method")),
        _md_field("Status", session["status"]),
    ]
    lines = [
        f"# Session: {session['name']}",
        "",
        *(line for line in header if line),
        "",
        "## Yield",
        # Rounded: the totals are float sums of 0.1 g entries (300.29999999999995).
        f"- Wet: {round(session.get('total_wet_yield_g') or 0.0, 1)}g",
        f"- Dry: {round(session.get('total_dry_yield_g') or 0.0, 1)}g",
        "",
        "## Phase Timeline",
        "",
    ]

    for pt in data["phase_telemetry"]:
        phase_name = pt["phase"].replace("_", " ").title()
        lines.append(f"### {phase_name} ({pt['duration_hours']}h)")
        if pt["telemetry_summary"]:
            for sensor, stats in pt["telemetry_summary"].items():
                lines.append(f"- {sensor}: min={stats['min']}, max={stats['max']}, avg={stats['avg']}")
        lines.append("")

    if data["harvests"]:
        lines.extend(["## Harvests", ""])
        for h in data["harvests"]:
            # The weight columns are NULL when not weighed (the key is always
            # there, so a .get() default never applied and "Noneg" printed).
            wet, dry = (("?" if h.get(k) is None else h[k])
                        for k in ("wet_weight_g", "dry_weight_g"))
            lines.append(f"- Flush #{h['flush_number']}: {wet}g wet, {dry}g dry")
        lines.append("")

    if data["notes"]:
        lines.extend(["## Notes", ""])
        for n in data["notes"]:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(n["timestamp"]))
            lines.append(f"- **{ts}**: {n['text']}")
        lines.append("")

    if data["vision_analyses"]:
        lines.extend(["## Vision Analysis", ""])
        for v in data["vision_analyses"]:
            if v.get("analysis_claude"):
                claude = v["analysis_claude"]
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(v["timestamp"]))
                lines.append(f"**{ts}** — {claude.get('health_assessment') or 'unknown'}")
                if claude.get("summary"):
                    lines.append(f"> {claude['summary']}")
                lines.append("")

    if data["events"]:
        lines.extend(["## Key Events", ""])
        for e in data["events"]:
            if e["type"] in _KEY_EVENT_TYPES:
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["timestamp"]))
                lines.append(f"- **{ts}**: {e['description']}")
        lines.append("")

    return "\n".join(lines)


async def analyze_with_claude(session_id: int) -> dict | None:
    """Send full transcript to Claude for comprehensive analysis (None if unknown)."""
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}

    built = await _build_transcript(session_id)
    if built is None:
        return None
    transcript, profile = built

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        system_prompt = """You are an expert mycologist analyzing a mushroom cultivation session transcript.
Each phase_telemetry entry carries the phase's actual sensor readings (telemetry_summary:
min/max/avg per sensor; temperatures in °F, humidity in %RH, CO2 in ppm, light in lux), its
duration_hours, and the targets the grow ran on in that phase (temperature, humidity, CO2,
light and FAE setpoints, and expected_duration_days), with targets_source saying where they
came from; a target that is absent is unknown, and targets is null when none are known.
Provide a comprehensive analysis as JSON with these fields:
- overall_score: 1-100 rating of the grow
- condition_analysis: compare each phase's actual sensor data against its targets
- issues_identified: list of problems found
- vision_concerns: any contamination or morphology issues from vision analysis
- yield_assessment: evaluation of harvest results
- phase_timing: was each phase the right duration (duration_hours against expected_duration_days)?
- recommendations: specific actionable improvements for next run
- summary: 3-5 sentence overall assessment"""

        # Trim transcript to essential data for token efficiency. Vision
        # summaries are bounded so a long grow stays inside the context window.
        claude_analyses = [
            v for v in transcript.get("vision_analyses", [])
            if isinstance(v.get("analysis_claude"), dict)
            and not v["analysis_claude"].get("error")
        ]
        vision_summaries = _select_vision_summaries(claude_analyses)
        # Each phase's readings beside the setpoints it ran on: without them
        # the model could only guess the targets from the species id (and had
        # nothing at all for a custom strain).
        phase_telemetry = []
        for row, telemetry in zip(transcript["phase_timeline"], transcript["phase_telemetry"]):
            targets, source = _phase_targets(row, profile)
            phase_telemetry.append({**telemetry, "targets": targets, "targets_source": source})
        essential = {
            "session": transcript["session"],
            "species_profile_id": transcript["session"]["species_profile_id"],
            "species": ({"common_name": profile.common_name,
                         "scientific_name": profile.scientific_name}
                        if profile is not None else None),
            "phase_telemetry": phase_telemetry,
            "harvests": transcript["harvests"],
            "automation_summary": transcript["automation_summary"],
            "vision_summaries": vision_summaries,
            "vision_summary_stats": {
                "total_analyses": len(claude_analyses),
                "by_assessment": dict(Counter(
                    str(v["analysis_claude"].get("health_assessment"))
                    for v in claude_analyses
                )),
                "included": len(vision_summaries),
                "selection": "latest per day and assessment; healthy days thinned first",
            },
        }

        message = await client.messages.create(
            model=settings.claude_model,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this session transcript:\n\n```json\n{json.dumps(essential, indent=2)}\n```",
                }
            ],
        )

        stop_reason = claude_stop_reason(message)
        if stop_reason == "refusal":
            return {"error": "Claude declined to analyze this session (refusal)"}
        text = claude_response_text(message)
        result = parse_claude_json(text)
        if stop_reason == "max_tokens" and "raw_response" in result:
            return {"error": "Claude analysis was cut off at max_tokens", "raw_response": text}
        return result

    except Exception as e:
        return {"error": str(e)}
