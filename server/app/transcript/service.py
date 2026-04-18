import json
import time

import anthropic

from ..config import settings
from ..db import get_db
from ..species.service import get_profile
from ..vision.service import _deserialize_frame, parse_claude_json


async def export_json(session_id: int) -> dict:
    """Export complete session transcript as structured JSON."""
    async with get_db() as db:
        # Session
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session = dict(await cursor.fetchone())

        # Phase history
        cursor = await db.execute(
            "SELECT * FROM phase_history WHERE session_id = ? ORDER BY entered_at", (session_id,)
        )
        phases = [dict(r) for r in await cursor.fetchall()]

        # Events
        cursor = await db.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp", (session_id,)
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

        # Telemetry summary per phase
        phase_telemetry = []
        for phase in phases:
            entered = phase["entered_at"]
            exited = phase["exited_at"] or time.time()
            cursor = await db.execute(
                """SELECT sensor, MIN(value) as min_val, MAX(value) as max_val,
                   AVG(value) as avg_val, COUNT(*) as count
                   FROM telemetry_readings
                   WHERE session_id = ? AND timestamp BETWEEN ? AND ?
                   GROUP BY sensor""",
                (session_id, entered, exited),
            )
            stats = {row["sensor"]: {
                "min": round(row["min_val"], 1),
                "max": round(row["max_val"], 1),
                "avg": round(row["avg_val"], 1),
                "count": row["count"],
            } for row in await cursor.fetchall()}

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

    return {
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


async def export_markdown(session_id: int) -> str:
    """Export session transcript as human-readable markdown."""
    data = await export_json(session_id)
    session = data["session"]
    profile = data.get("species_profile", {})

    lines = [
        f"# Session: {session['name']}",
        "",
        f"**Species**: {profile.get('common_name', session['species_profile_id'])} "
        f"(*{profile.get('scientific_name', '')}*)",
        f"**Category**: {profile.get('category', 'unknown')}",
        f"**Substrate**: {session.get('substrate', 'N/A')} ({session.get('substrate_volume', 'N/A')})",
        f"**Inoculated**: {session.get('inoculation_date', 'N/A')} ({session.get('inoculation_method', 'N/A')})",
        f"**Status**: {session['status']}",
        "",
        "## Yield",
        f"- Wet: {session.get('total_wet_yield_g', 0)}g",
        f"- Dry: {session.get('total_dry_yield_g', 0)}g",
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
            lines.append(
                f"- Flush #{h['flush_number']}: {h.get('wet_weight_g', '?')}g wet, "
                f"{h.get('dry_weight_g', '?')}g dry"
            )
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
                lines.append(f"**{ts}** — {claude.get('health_assessment', 'unknown')}")
                if claude.get("summary"):
                    lines.append(f"> {claude['summary']}")
                lines.append("")

    if data["events"]:
        lines.extend(["## Key Events", ""])
        for e in data["events"]:
            if e["type"] in ("phase_change", "harvest", "session_created", "session_completed"):
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["timestamp"]))
                lines.append(f"- **{ts}**: {e['description']}")
        lines.append("")

    return "\n".join(lines)


async def analyze_with_claude(session_id: int) -> dict:
    """Send full transcript to Claude for comprehensive analysis."""
    if not settings.claude_api_key:
        return {"error": "Claude API key not configured"}

    transcript = await export_json(session_id)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

        system_prompt = """You are an expert mycologist analyzing a mushroom cultivation session transcript.
Provide a comprehensive analysis as JSON with these fields:
- overall_score: 1-100 rating of the grow
- condition_analysis: compare actual sensor data vs species profile targets for each phase
- issues_identified: list of problems found
- vision_concerns: any contamination or morphology issues from vision analysis
- yield_assessment: evaluation of harvest results
- phase_timing: was each phase the right duration?
- recommendations: specific actionable improvements for next run
- summary: 3-5 sentence overall assessment"""

        # Trim transcript to essential data for token efficiency
        essential = {
            "session": transcript["session"],
            "species_profile_id": transcript["session"]["species_profile_id"],
            "phase_telemetry": transcript["phase_telemetry"],
            "harvests": transcript["harvests"],
            "automation_summary": transcript["automation_summary"],
            "vision_summaries": [
                {
                    "timestamp": v["timestamp"],
                    "claude_assessment": v.get("analysis_claude", {}).get("health_assessment"),
                    "claude_summary": v.get("analysis_claude", {}).get("summary"),
                }
                for v in transcript.get("vision_analyses", [])
                if v.get("analysis_claude")
            ],
        }

        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze this session transcript:\n\n```json\n{json.dumps(essential, indent=2)}\n```",
                }
            ],
        )

        return parse_claude_json(message.content[0].text)

    except Exception as e:
        return {"error": str(e)}
