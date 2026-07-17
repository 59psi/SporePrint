"""Automation hardware-coverage endpoint (V2-1).

Mounted under /api/chambers (not /api/automation) because the verdict is
scoped to a chamber + species: GET /api/chambers/{id}/automation-coverage.
The heavy lifting lives in coverage.py; the router just resolves the chamber
and species and shapes the response.
"""

from fastapi import APIRouter, HTTPException, Query

from ..chambers.service import get_chamber
from ..species.service import get_profile
from .coverage import compute_coverage

router = APIRouter()


@router.get("/{chamber_id}/automation-coverage")
async def automation_coverage(
    chamber_id: int,
    species: str = Query(..., description="species_profile_id to evaluate coverage for"),
):
    """Which automation requirements this chamber's paired hardware can satisfy,
    per grow phase of the given species — available, unavailable, or degraded
    to a fallback. Hardware presence is read from the live smart-plug + node
    registries; nothing is assumed to be present.
    """
    chamber = await get_chamber(chamber_id)
    if not chamber:
        raise HTTPException(404, "Chamber not found")
    profile = await get_profile(species)
    if not profile:
        raise HTTPException(404, f"Unknown species profile '{species}'")
    return {"phases": await compute_coverage(profile)}
