"""Species Selector Wizard — guided questionnaire scoring engine.

Takes 6 user-provided parameters and scores every species profile on
a 0-100 scale across six dimensions: experience, environment, temperature,
substrate, goal, and commitment.  Returns the top 5 matches with reasons.
"""

from __future__ import annotations

from .models import GrowPhase, SpeciesProfile

# ── Temperature range presets (°F) ──────────────────────────────────
TEMP_RANGES: dict[str, tuple[float, float]] = {
    "cool": (50.0, 65.0),
    "moderate": (65.0, 75.0),
    "warm": (75.0, 85.0),
}

# ── Substrate keyword mapping ───────────────────────────────────────
# Maps the wizard's coarse choices to substrings that appear in
# SpeciesProfile.substrate_types entries.
SUBSTRATE_KEYWORDS: dict[str, list[str]] = {
    "straw": ["straw"],
    "sawdust": ["sawdust", "hardwood", "masters mix", "softwood", "wood"],
    "grain": ["grain", "BRF", "brown rice", "rye", "bird seed", "rice"],
    "manure": ["manure", "compost", "dung"],
}

# ── Experience-level tag mapping ────────────────────────────────────
EXPERIENCE_TAGS: dict[str, list[str]] = {
    "first_time": ["beginner"],
    "some_experience": ["beginner", "intermediate"],
    "advanced": ["beginner", "intermediate", "advanced"],
}

# ── Commitment thresholds (total grow days) ─────────────────────────
# Maps commitment level to a maximum number of total expected grow days
# that the user is comfortable with.  Species whose total cycle exceeds
# this get a lower score.
COMMITMENT_MAX_DAYS: dict[str, int] = {
    "set_and_forget": 45,
    "daily_attention": 90,
    "dedicated_hobbyist": 999,
}


def _total_grow_days(profile: SpeciesProfile) -> int:
    """Sum of average expected_duration_days across all phases."""
    total = 0
    for params in profile.phases.values():
        lo, hi = params.expected_duration_days
        total += (lo + hi) // 2
    return total


def _fruiting_temp_range(profile: SpeciesProfile) -> tuple[float, float] | None:
    """Return (min, max) fruiting-body temperature range.

    Prefers the FRUITING phase; falls back to PRIMORDIA_INDUCTION,
    then any phase present.
    """
    for phase_key in (GrowPhase.FRUITING, GrowPhase.PRIMORDIA_INDUCTION):
        if phase_key in profile.phases:
            p = profile.phases[phase_key]
            return (p.temp_min_f, p.temp_max_f)
    # fallback: first phase
    if profile.phases:
        p = next(iter(profile.phases.values()))
        return (p.temp_min_f, p.temp_max_f)
    return None


def _overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """Return the fraction of range A that overlaps with range B (0-1)."""
    lo = max(a_lo, b_lo)
    hi = min(a_hi, b_hi)
    if hi <= lo:
        return 0.0
    a_span = a_hi - a_lo
    if a_span == 0:
        return 1.0 if b_lo <= a_lo <= b_hi else 0.0
    return (hi - lo) / a_span


def score_profile(
    profile: SpeciesProfile,
    *,
    experience: str,
    environment: str,
    temp_range: str,
    substrates: list[str],
    goal: str,
    commitment: str,
) -> dict:
    """Score a single species profile against user preferences.

    Returns a dict with ``score`` (int 0-100), ``reasons`` (list[str]),
    and top-level species metadata.
    """
    reasons: list[str] = []
    scores: dict[str, float] = {}

    # ── 1. Experience match (0-25) ──────────────────────────────────
    allowed_tags = EXPERIENCE_TAGS.get(experience, ["beginner", "intermediate", "advanced"])
    profile_tags_lower = [t.lower() for t in profile.tags]

    # Check if the species difficulty level is within the user's ability
    has_match = False
    for tag in allowed_tags:
        if tag in profile_tags_lower:
            has_match = True
            break
        # Handle compound tags like "beginner-intermediate"
        for pt in profile_tags_lower:
            if tag in pt:
                has_match = True
                break
        if has_match:
            break

    if has_match:
        # Bonus points if the species is exactly at the user's level
        if experience == "first_time" and "beginner" in profile_tags_lower:
            scores["experience"] = 25.0
            reasons.append("Beginner-friendly species")
        elif experience == "some_experience":
            if "intermediate" in profile_tags_lower:
                scores["experience"] = 25.0
                reasons.append("Good match for your experience level")
            elif "beginner" in profile_tags_lower:
                scores["experience"] = 20.0
                reasons.append("Easy for your experience level")
        elif experience == "advanced":
            if "advanced" in profile_tags_lower:
                scores["experience"] = 25.0
                reasons.append("Challenging species suited for advanced growers")
            else:
                scores["experience"] = 18.0
                reasons.append("Within your skill level")
        else:
            scores["experience"] = 20.0
    else:
        # Species is too advanced for user
        scores["experience"] = 5.0
        reasons.append("May be above your current experience level")

    # ── 2. Environment match (0-20) ─────────────────────────────────
    is_outdoor = environment in ("outdoor_beds", "logs")
    species_outdoor = any(
        kw in " ".join(profile.substrate_types).lower()
        for kw in ("log", "garden", "outdoor", "compost", "soil")
    ) or any(kw in profile_tags_lower for kw in ("outdoor-capable", "outdoor"))

    if is_outdoor:
        if species_outdoor:
            scores["environment"] = 20.0
            reasons.append(f"Well-suited for {environment.replace('_', ' ')}")
        else:
            scores["environment"] = 5.0
            reasons.append("Primarily an indoor species")
    else:
        # Indoor environments work for most species
        if environment == "indoor_tent":
            scores["environment"] = 20.0
            reasons.append("Grows well in a grow tent")
        elif environment == "indoor_closet":
            scores["environment"] = 18.0
            reasons.append("Suitable for closet growing")
        else:
            scores["environment"] = 15.0

    # ── 3. Temperature match (0-20) ─────────────────────────────────
    user_lo, user_hi = TEMP_RANGES.get(temp_range, (65.0, 75.0))
    species_range = _fruiting_temp_range(profile)

    if species_range:
        sp_lo, sp_hi = species_range
        frac = _overlap(sp_lo, sp_hi, user_lo, user_hi)
        scores["temperature"] = round(frac * 20.0, 1)
        if frac >= 0.8:
            reasons.append(f"Fruiting temp ({sp_lo:.0f}-{sp_hi:.0f}F) fits your range")
        elif frac >= 0.4:
            reasons.append(f"Partial temp overlap ({sp_lo:.0f}-{sp_hi:.0f}F)")
        elif frac > 0:
            reasons.append(f"Marginal temp overlap ({sp_lo:.0f}-{sp_hi:.0f}F)")
        else:
            reasons.append(f"Fruiting temp ({sp_lo:.0f}-{sp_hi:.0f}F) outside your range")
    else:
        scores["temperature"] = 10.0

    # ── 4. Substrate match (0-15) ───────────────────────────────────
    if "all" in substrates:
        scores["substrate"] = 15.0
        reasons.append("You have all substrate types available")
    else:
        species_subs_lower = [s.lower() for s in profile.substrate_types]
        matched = 0
        total = len(species_subs_lower) or 1
        for user_sub in substrates:
            keywords = SUBSTRATE_KEYWORDS.get(user_sub, [user_sub])
            for sp_sub in species_subs_lower:
                if any(kw.lower() in sp_sub for kw in keywords):
                    matched += 1
                    break
        frac = matched / total
        if frac >= 0.5:
            scores["substrate"] = round(15.0 * min(frac * 1.5, 1.0), 1)
            reasons.append(f"Compatible substrates available ({matched}/{total})")
        elif matched > 0:
            scores["substrate"] = round(15.0 * frac, 1)
            reasons.append(f"Limited substrate match ({matched}/{total})")
        else:
            scores["substrate"] = 0.0
            reasons.append("None of your substrates match this species")

    # ── 5. Goal match (0-10) ────────────────────────────────────────
    cat = profile.category.lower()
    if goal == "culinary":
        if cat == "gourmet":
            scores["goal"] = 10.0
            reasons.append("Gourmet culinary species")
        elif cat == "medicinal":
            scores["goal"] = 3.0
        else:
            scores["goal"] = 0.0
    elif goal == "medicinal":
        if cat == "medicinal":
            scores["goal"] = 10.0
            reasons.append("Medicinal species")
        elif cat == "gourmet" and "medicinal" in profile_tags_lower:
            scores["goal"] = 8.0
            reasons.append("Gourmet with medicinal properties")
        elif cat == "gourmet":
            scores["goal"] = 3.0
        else:
            scores["goal"] = 0.0
    elif goal == "both":
        if cat in ("gourmet", "medicinal"):
            scores["goal"] = 8.0
            reasons.append(f"{cat.title()} species")
        else:
            scores["goal"] = 0.0
    elif goal == "research":
        scores["goal"] = 7.0
        reasons.append("Suitable for research cultivation")
    else:
        scores["goal"] = 5.0

    # ── 6. Commitment match (0-10) ──────────────────────────────────
    total_days = _total_grow_days(profile)
    max_days = COMMITMENT_MAX_DAYS.get(commitment, 90)

    if total_days <= max_days:
        scores["commitment"] = 10.0
        reasons.append(f"~{total_days} day cycle fits your schedule")
    elif total_days <= max_days * 1.5:
        scores["commitment"] = 5.0
        reasons.append(f"~{total_days} day cycle is longer than ideal")
    else:
        scores["commitment"] = 2.0
        reasons.append(f"~{total_days} day cycle may be too long")

    total_score = int(round(sum(scores.values())))
    total_score = max(0, min(100, total_score))

    return {
        "species_id": profile.id,
        "common_name": profile.common_name,
        "scientific_name": profile.scientific_name,
        "category": profile.category,
        "score": total_score,
        "reasons": reasons,
        "tldr": profile.tldr,
    }


def recommend(
    profiles: list[SpeciesProfile],
    *,
    experience: str,
    environment: str,
    temp_range: str,
    substrates: list[str],
    goal: str,
    commitment: str,
    limit: int = 5,
) -> list[dict]:
    """Score all profiles and return the top *limit* results, sorted descending."""
    scored = [
        score_profile(
            p,
            experience=experience,
            environment=environment,
            temp_range=temp_range,
            substrates=substrates,
            goal=goal,
            commitment=commitment,
        )
        for p in profiles
    ]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]
