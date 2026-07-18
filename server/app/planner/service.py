"""Seasonal grow planner — species scoring, calendar, session warnings."""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..db import get_db
from ..sessions.service import get_session
from ..species.models import GrowPhase, SpeciesProfile
from ..species.service import get_all_profiles, get_profile

log = logging.getLogger(__name__)

# ~15 deg F insulation buffer between outdoor and chamber temps
INSULATION_BUFFER_F = 15.0


async def aggregate_daily_weather():
    """Nightly cron: aggregate yesterday's weather + telemetry into weather_history.

    Idempotent — skips if date already exists.
    """
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")

    async with get_db() as db:
        # Check if already aggregated
        cursor = await db.execute(
            "SELECT id FROM weather_history WHERE date = ?", (date_str,)
        )
        if await cursor.fetchone():
            log.debug("Weather history for %s already aggregated", date_str)
            return

        # Date boundaries (unix timestamps)
        day_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400

        # Outdoor data from weather_readings
        cursor = await db.execute(
            """SELECT AVG(temp_f) as avg_temp, MIN(temp_f) as min_temp,
                      MAX(temp_f) as max_temp, AVG(humidity) as avg_humidity
               FROM weather_readings
               WHERE timestamp >= ? AND timestamp < ?""",
            (day_start, day_end),
        )
        outdoor = dict(await cursor.fetchone())

        # Chamber data from telemetry_readings
        cursor = await db.execute(
            """SELECT AVG(value) as avg_temp, MIN(value) as min_temp, MAX(value) as max_temp
               FROM telemetry_readings
               WHERE sensor = 'temperature' AND timestamp >= ? AND timestamp < ?""",
            (day_start, day_end),
        )
        chamber_temp = dict(await cursor.fetchone())

        cursor = await db.execute(
            """SELECT AVG(value) as avg_humidity
               FROM telemetry_readings
               WHERE sensor = 'humidity' AND timestamp >= ? AND timestamp < ?""",
            (day_start, day_end),
        )
        chamber_humidity = dict(await cursor.fetchone())

        # Only insert if we have at least outdoor data
        if outdoor["avg_temp"] is None and chamber_temp["avg_temp"] is None:
            log.debug("No weather/telemetry data for %s, skipping", date_str)
            return

        await db.execute(
            """INSERT INTO weather_history
               (date, outdoor_temp_avg_f, outdoor_temp_min_f, outdoor_temp_max_f,
                outdoor_humidity_avg, chamber_temp_avg_f, chamber_temp_min_f,
                chamber_temp_max_f, chamber_humidity_avg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                date_str,
                outdoor["avg_temp"], outdoor["min_temp"], outdoor["max_temp"],
                outdoor["avg_humidity"],
                chamber_temp["avg_temp"], chamber_temp["min_temp"], chamber_temp["max_temp"],
                chamber_humidity["avg_humidity"],
            ),
        )
        await db.commit()
        log.info("Aggregated weather history for %s", date_str)


def score_species_match(
    profile: SpeciesProfile,
    outdoor_temp_f: float,
    outdoor_humidity: float,
) -> dict:
    """Score 0-100 how well current outdoor conditions suit a species.

    Accounts for ~15 deg F chamber insulation buffer. Returns dict with
    total score, component scores, and any warnings.
    """
    # Use fruiting phase as the reference (most demanding)
    phase_params = profile.phases.get(GrowPhase.FRUITING)
    if not phase_params:
        # Fall back to substrate_colonization if no fruiting phase
        phase_params = profile.phases.get(GrowPhase.SUBSTRATE_COLONIZATION)
    if not phase_params:
        return {"score": 0, "temp_score": 0, "humidity_score": 0, "ease_score": 0, "warnings": ["No phase data available"]}

    # Estimated chamber temp (outdoor + insulation buffer)
    est_chamber_temp = outdoor_temp_f + INSULATION_BUFFER_F
    target_mid = (phase_params.temp_min_f + phase_params.temp_max_f) / 2
    temp_range = phase_params.temp_max_f - phase_params.temp_min_f

    # Temperature score (0-50)
    temp_diff = abs(est_chamber_temp - target_mid)
    if temp_diff <= temp_range / 2:
        # Within optimal range
        temp_score = 50
    elif temp_diff <= temp_range:
        # Within one range-width buffer
        temp_score = 30
    elif temp_diff <= temp_range * 2:
        # Manageable
        temp_score = 15
    else:
        temp_score = 0

    # Humidity score (0-30) — humidity is easier to control
    target_humidity_mid = (phase_params.humidity_min + phase_params.humidity_max) / 2
    humidity_diff = abs(outdoor_humidity - target_humidity_mid)
    if humidity_diff <= 15:
        humidity_score = 30
    elif humidity_diff <= 30:
        humidity_score = 15
    else:
        humidity_score = 5

    # Ease score (0-20) based on tags
    tags = [t.lower() for t in profile.tags]
    if "beginner" in tags:
        ease_score = 20
    elif "intermediate" in tags:
        ease_score = 10
    else:
        ease_score = 0

    total = temp_score + humidity_score + ease_score

    # Generate warnings
    warnings = []
    if est_chamber_temp > phase_params.temp_max_f + 10:
        warnings.append(
            f"Outdoor temp {outdoor_temp_f:.0f} deg F too hot — estimated chamber temp "
            f"{est_chamber_temp:.0f} deg F exceeds {profile.common_name} max "
            f"({phase_params.temp_max_f:.0f} deg F) by {est_chamber_temp - phase_params.temp_max_f:.0f} deg F. "
            f"Active cooling required."
        )
    elif est_chamber_temp > phase_params.temp_max_f:
        warnings.append(
            f"Chamber may run warm for {profile.common_name} — "
            f"consider pre-cooling or waiting for cooler weather."
        )

    if est_chamber_temp < phase_params.temp_min_f - 10:
        warnings.append(
            f"Outdoor temp {outdoor_temp_f:.0f} deg F too cold — estimated chamber temp "
            f"{est_chamber_temp:.0f} deg F below {profile.common_name} min "
            f"({phase_params.temp_min_f:.0f} deg F). Space heater recommended."
        )
    elif est_chamber_temp < phase_params.temp_min_f:
        warnings.append(
            f"Chamber may run cool for {profile.common_name} — "
            f"supplemental heating may be needed."
        )

    return {
        "species_id": profile.id,
        "common_name": profile.common_name,
        "scientific_name": profile.scientific_name,
        "category": profile.category,
        "score": total,
        "temp_score": temp_score,
        "humidity_score": humidity_score,
        "ease_score": ease_score,
        "est_chamber_temp_f": round(est_chamber_temp, 1),
        "fruiting_range_f": f"{phase_params.temp_min_f:.0f}-{phase_params.temp_max_f:.0f}",
        "warnings": warnings,
    }


async def get_recommendations(
    outdoor_temp_f: float,
    outdoor_humidity: float,
    category: str | None = None,
) -> list[dict]:
    """Rank all species by match score for given outdoor conditions.

    Returns sorted list (highest score first), with optional category filter.
    """
    profiles = await get_all_profiles()
    results = []

    for profile in profiles:
        if category and profile.category != category:
            continue
        result = score_species_match(profile, outdoor_temp_f, outdoor_humidity)
        results.append(result)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


async def get_calendar_data() -> list[dict]:
    """Group weather_history by month, score all species per month.

    Returns 12 months with top 10 species per month.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT strftime('%m', date) as month,
                      AVG(outdoor_temp_avg_f) as avg_temp,
                      AVG(outdoor_humidity_avg) as avg_humidity
               FROM weather_history
               GROUP BY strftime('%m', date)
               ORDER BY month"""
        )
        monthly_data = [dict(r) for r in await cursor.fetchall()]

    if not monthly_data:
        return []

    profiles = await get_all_profiles()
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]

    calendar = []
    for row in monthly_data:
        month_num = int(row["month"])
        avg_temp = row["avg_temp"]
        avg_humidity = row["avg_humidity"] or 50.0  # fallback if no humidity data

        # Score all species for this month's conditions
        scored = []
        for profile in profiles:
            result = score_species_match(profile, avg_temp, avg_humidity)
            scored.append(result)

        scored.sort(key=lambda r: r["score"], reverse=True)

        calendar.append({
            "month": month_num,
            "month_name": month_names[month_num - 1],
            "avg_outdoor_temp_f": round(avg_temp, 1) if avg_temp else None,
            "avg_outdoor_humidity": round(avg_humidity, 1) if avg_humidity else None,
            "top_species": scored[:10],
        })

    return calendar


async def get_session_warnings(session_id: int) -> dict:
    """Check current + forecast weather against session's species requirements.

    Returns warning level (ok/info/warning/critical), message, and forecast warnings.
    """
    from ..weather.service import get_cached_weather, get_cached_forecast

    session = await get_session(session_id)
    if not session:
        return {"level": "info", "message": "Session not found.", "forecast_warnings": []}

    profile = await get_profile(session["species_profile_id"])
    if not profile:
        return {"level": "info", "message": "Species profile not found.", "forecast_warnings": []}

    current_phase = session["current_phase"]
    try:
        phase_params = profile.phases.get(GrowPhase(current_phase))
    except (ValueError, KeyError):
        phase_params = None
    if not phase_params:
        return {"level": "info", "message": f"No parameters for phase '{current_phase}'.", "forecast_warnings": []}

    # Check current weather
    weather = get_cached_weather()
    level = "ok"
    message = f"Conditions look good for {profile.common_name} ({current_phase.replace('_', ' ')})."
    forecast_warnings = []

    if weather:
        outdoor_temp = weather.get("outdoor_temp_f")
        if outdoor_temp is not None:
            est_chamber = outdoor_temp + INSULATION_BUFFER_F
            if est_chamber > phase_params.temp_max_f + 10:
                level = "critical"
                message = (
                    f"Current outdoor temp {outdoor_temp:.0f} deg F — estimated chamber "
                    f"{est_chamber:.0f} deg F far exceeds {profile.common_name} "
                    f"{current_phase.replace('_', ' ')} max ({phase_params.temp_max_f:.0f} deg F). "
                    f"Immediate action needed."
                )
            elif est_chamber > phase_params.temp_max_f:
                level = "warning"
                message = (
                    f"Current conditions running warm for {profile.common_name} — "
                    f"estimated chamber {est_chamber:.0f} deg F above target max "
                    f"({phase_params.temp_max_f:.0f} deg F)."
                )
            elif est_chamber < phase_params.temp_min_f - 10:
                level = "critical"
                message = (
                    f"Current outdoor temp {outdoor_temp:.0f} deg F — estimated chamber "
                    f"{est_chamber:.0f} deg F far below {profile.common_name} "
                    f"{current_phase.replace('_', ' ')} min ({phase_params.temp_min_f:.0f} deg F). "
                    f"Heating urgently needed."
                )
            elif est_chamber < phase_params.temp_min_f:
                level = "warning"
                message = (
                    f"Current conditions running cool for {profile.common_name} — "
                    f"estimated chamber {est_chamber:.0f} deg F below target min "
                    f"({phase_params.temp_min_f:.0f} deg F)."
                )

    # Check 7-day forecast for sustained unfavorable conditions
    forecast = get_cached_forecast()
    if forecast:
        unfavorable_days = 0
        now = time.time()

        # Group forecast into daily buckets
        daily: dict[int, list[dict]] = defaultdict(list)
        for entry in forecast:
            ts = entry.get("timestamp", 0)
            if ts < now:
                continue
            day_key = int(ts / 86400)
            daily[day_key].append(entry)

        for day_key in sorted(daily):
            entries = daily[day_key]
            temps = [e.get("temp_f", 72) for e in entries]
            avg_temp = sum(temps) / len(temps)
            est_chamber = avg_temp + INSULATION_BUFFER_F

            day_ts = day_key * 86400
            t = time.gmtime(day_ts)
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][t.tm_wday]

            if est_chamber > phase_params.temp_max_f + 5 or est_chamber < phase_params.temp_min_f - 5:
                unfavorable_days += 1
                direction = "hot" if est_chamber > phase_params.temp_max_f else "cold"
                forecast_warnings.append({
                    "day": day_name,
                    "date": time.strftime("%Y-%m-%d", t),
                    "avg_outdoor_temp_f": round(avg_temp, 1),
                    "est_chamber_temp_f": round(est_chamber, 1),
                    "issue": direction,
                    "message": (
                        f"{day_name}: Estimated chamber {est_chamber:.0f} deg F — "
                        f"{'above' if direction == 'hot' else 'below'} "
                        f"{profile.common_name} target range "
                        f"({phase_params.temp_min_f:.0f}-{phase_params.temp_max_f:.0f} deg F)."
                    ),
                })

        # Sustained unfavorable conditions (>3 days) escalate the warning
        if unfavorable_days > 3 and level != "critical":
            level = "warning"
            message = (
                f"{unfavorable_days} of the next 7 days show unfavorable conditions "
                f"for {profile.common_name} ({current_phase.replace('_', ' ')}). "
                f"Consider timing adjustments."
            )

    return {
        "session_id": session_id,
        "species": profile.common_name,
        "phase": current_phase,
        "level": level,
        "message": message,
        "forecast_warnings": forecast_warnings,
    }


# ── Planned events (month-calendar event store) ─────────────────
#
# Distinct from the species-compatibility recommender above: this is a CRUD
# store of user-planned grow events (inoculate / transfer / harvest-window /
# maintenance / custom) shown on the planner's month calendar. `date` is an ISO
# date string; drag-reschedule is an update that changes `date`.

from .models import PlannedEventCreate, PlannedEventUpdate  # noqa: E402

_PLANNED_EVENT_COLUMNS = ("title", "kind", "date", "chamber_id", "session_id", "notes")


async def get_planned_event(event_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM planned_events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_planned_events(
    date_from: str | None = None, date_to: str | None = None
) -> list[dict]:
    """Planned events in an inclusive date range, sorted by date."""
    query = "SELECT * FROM planned_events WHERE 1=1"
    params: list = []
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    query += " ORDER BY date ASC, id ASC"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]


async def create_planned_event(data: PlannedEventCreate) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO planned_events (title, kind, date, chamber_id, session_id, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.title, data.kind, data.date, data.chamber_id, data.session_id, data.notes),
        )
        await db.commit()
        event_id = cursor.lastrowid
    return await get_planned_event(event_id)


async def update_planned_event(
    event_id: int, data: PlannedEventUpdate
) -> dict | None:
    """Partial update. None fields are left unchanged (matches the repo's
    partial-update convention); `date` change is the drag-reschedule."""
    existing = await get_planned_event(event_id)
    if not existing:
        return None

    dumped = data.model_dump()
    changed = {c: dumped[c] for c in _PLANNED_EVENT_COLUMNS if dumped[c] is not None}
    if changed:
        # Column names come from the fixed whitelist above, never user input.
        set_sql = ", ".join(f"{c} = ?" for c in changed)
        params = list(changed.values()) + [time.time(), event_id]
        async with get_db() as db:
            await db.execute(
                f"UPDATE planned_events SET {set_sql}, updated_at = ? WHERE id = ?",
                params,
            )
            await db.commit()
    return await get_planned_event(event_id)


async def delete_planned_event(event_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "DELETE FROM planned_events WHERE id = ?", (event_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


# ── Species-derived dated cycle proposer (V1-2) ─────────────────
#
# The recommender above scores species against *current* weather. This proposer
# answers a different question: given a species and an inoculation date, when
# does each grow phase start and end? It reads the species' real phases
# (temp/RH/CO2/light + expected_duration_days) and lays out concrete dates —
# inoculation -> colonization -> primordia -> fruiting -> harvest. Reused by the
# /propose endpoint and the planner iCal phase-timeline projection (planner/ical.py).

from datetime import date  # noqa: E402
from .models import ProposedCycle, ProposedPhase, ProposedPhaseSetpoints  # noqa: E402

# Active fruiting-run phases in canonical order. COLD_STORAGE is the fridge-hold
# fork (a grow bag advances to primordia instead of parking) and COMPLETE is the
# terminal marker — neither belongs on a dated inoculation -> harvest timeline.
_TIMELINE_PHASES = [
    p for p in GrowPhase if p not in (GrowPhase.COLD_STORAGE, GrowPhase.COMPLETE)
]


def _phase_span_days(duration_days: tuple[int, int]) -> int:
    """Rounded midpoint of a phase's (min, max) expected duration, floored at 1.

    Matches the average-of-range convention the session iCal projection already
    uses, so a proposed cycle and a live session's projection agree.
    """
    lo, hi = duration_days
    return max(1, round((lo + hi) / 2))


def propose_cycle(profile: SpeciesProfile, start: date) -> ProposedCycle:
    """Lay out a dated per-phase grow cycle for a species from an inoculation date.

    Walks the species' real phases in canonical order, assigning each a start and
    end date from expected_duration_days. Phases are contiguous (each begins when
    the previous ends). `harvest_date` is the end of the fruiting phase — the
    point fruit bodies are ready to pick.
    """
    cursor = start
    phases: list[ProposedPhase] = []
    harvest_date: date | None = None

    for gp in _TIMELINE_PHASES:
        params = profile.phases.get(gp)
        if params is None:
            continue
        dur = params.expected_duration_days
        if not (isinstance(dur, (list, tuple)) and len(dur) == 2):
            continue
        span = _phase_span_days(dur)
        phase_start = cursor
        phase_end = phase_start + timedelta(days=span)
        phases.append(
            ProposedPhase(
                phase=gp.value,
                label=gp.value.replace("_", " ").title(),
                start_date=phase_start,
                end_date=phase_end,
                duration_days=span,
                min_days=int(dur[0]),
                max_days=int(dur[1]),
                setpoints=ProposedPhaseSetpoints(
                    temp_min_f=params.temp_min_f,
                    temp_max_f=params.temp_max_f,
                    humidity_min=params.humidity_min,
                    humidity_max=params.humidity_max,
                    co2_max_ppm=params.co2_max_ppm,
                    co2_min_ppm=params.co2_min_ppm,
                    light_hours_on=params.light_hours_on,
                    light_hours_off=params.light_hours_off,
                    light_spectrum=params.light_spectrum,
                    fae_mode=params.fae_mode,
                ),
                notes=params.notes,
            )
        )
        cursor = phase_end
        if gp == GrowPhase.FRUITING:
            harvest_date = phase_end

    return ProposedCycle(
        species_id=profile.id,
        common_name=profile.common_name,
        scientific_name=profile.scientific_name,
        start_date=start,
        end_date=cursor,
        total_days=(cursor - start).days,
        harvest_date=harvest_date,
        phases=phases,
    )


async def propose_cycle_for_species(species_id: str, start: date) -> ProposedCycle | None:
    """Load a species profile by id and propose a dated cycle, or None if unknown."""
    profile = await get_profile(species_id)
    if profile is None:
        return None
    return propose_cycle(profile, start)
