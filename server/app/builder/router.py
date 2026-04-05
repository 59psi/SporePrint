from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .hardware_guides import TIERS
from .service import generate_guide, get_guides, get_guide

router = APIRouter()


# ─── Hardware Tiers ────────────────────────────────────────────

@router.get("/tiers")
async def list_tiers():
    """Return all 3 hardware tiers (summary: id, name, tagline, cost, features)."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "tagline": t.tagline,
            "estimated_cost": t.estimated_cost,
            "what_you_get": t.what_you_get,
            "component_count": sum(c.quantity for c in t.components),
        }
        for t in TIERS
    ]


@router.get("/tiers/{tier_id}")
async def get_tier(tier_id: str):
    """Return full tier detail: components, wiring, diagram, setup steps."""
    for t in TIERS:
        if t.id == tier_id:
            return t.model_dump()
    raise HTTPException(404, "Tier not found")


# ─── Claude Assistant (kept) ───────────────────────────────────

class GuideRequest(BaseModel):
    request: str
    constraints: str = ""


@router.post("/guide")
async def create_guide(data: GuideRequest):
    return await generate_guide(data.request, data.constraints)


@router.get("/guides")
async def list_guides():
    return await get_guides()


@router.get("/guides/{guide_id}")
async def get_guide_detail(guide_id: int):
    guide = await get_guide(guide_id)
    if not guide:
        raise HTTPException(404, "Guide not found")
    return guide
