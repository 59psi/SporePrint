from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .service import export_json, export_markdown, analyze_with_claude

router = APIRouter()


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: int, format: str = "json"):
    try:
        if format == "markdown":
            md = await export_markdown(session_id)
            return PlainTextResponse(md, media_type="text/markdown")
        else:
            return await export_json(session_id)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/sessions/{session_id}/analyze")
async def analyze_session(session_id: int):
    result = await analyze_with_claude(session_id)
    return result
