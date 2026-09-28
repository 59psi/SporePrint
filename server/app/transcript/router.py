from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .service import export_json, export_markdown, analyze_with_claude

router = APIRouter()


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: int, format: str = "json"):
    try:
        if format == "markdown":
            result = await export_markdown(session_id)
        else:
            result = await export_json(session_id)
    except Exception as e:
        raise HTTPException(500, str(e))
    if result is None:
        raise HTTPException(404, "Session not found")
    if format == "markdown":
        return PlainTextResponse(result, media_type="text/markdown")
    return result


@router.post("/sessions/{session_id}/analyze")
async def analyze_session(session_id: int):
    result = await analyze_with_claude(session_id)
    if result is None:
        raise HTTPException(404, "Session not found")
    return result
