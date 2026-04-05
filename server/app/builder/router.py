from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .service import generate_guide, get_guides, get_guide

router = APIRouter()


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
