from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .models import SessionCreate, SessionUpdate, PhaseAdvance, NoteCreate, HarvestCreate, DryingLogEntry
from . import service

router = APIRouter()


@router.post("")
async def create_session(data: SessionCreate):
    return await service.create_session(data)


@router.get("")
async def list_sessions(status: str | None = None, species: str | None = None):
    return await service.list_sessions(status, species)


@router.get("/calendar.ics")
async def session_calendar():
    ical_data = await service.generate_ical()
    return Response(
        content=ical_data,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=sporeprint.ics"},
    )


@router.get("/{session_id}")
async def get_session(session_id: int):
    session = await service.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.patch("/{session_id}")
async def update_session(session_id: int, data: SessionUpdate):
    session = await service.update_session(session_id, data)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/phase")
async def advance_phase(session_id: int, data: PhaseAdvance):
    session = await service.advance_phase(session_id, data)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/note")
async def add_note(session_id: int, data: NoteCreate):
    return await service.add_note(session_id, data)


@router.post("/{session_id}/harvest")
async def add_harvest(session_id: int, data: HarvestCreate):
    return await service.add_harvest(session_id, data)


@router.get("/{session_id}/events")
async def get_events(session_id: int):
    return await service.get_events(session_id)


@router.get("/{session_id}/telemetry")
async def session_telemetry(
    session_id: int,
    sensor: str = Query(...),
    from_ts: float | None = None,
    to_ts: float | None = None,
    resolution: str | None = None,
):
    from ..telemetry.service import get_history
    # For session telemetry, we query by session's node (for now, return all)
    return await get_history("climate-01", sensor, from_ts, to_ts, resolution)


@router.get("/{session_id}/report.pdf")
async def session_report_pdf(session_id: int):
    pdf_bytes = await service.generate_session_report(session_id)
    if not pdf_bytes:
        raise HTTPException(404, "Session not found")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=sporeprint-session-{session_id}.pdf"},
    )


@router.get("/{session_id}/stats")
async def get_session_stats(session_id: int):
    stats = await service.get_session_stats(session_id)
    if not stats:
        raise HTTPException(404, "Session not found")
    return stats


@router.post("/{session_id}/harvest/{harvest_id}/drying-log")
async def add_drying_log(session_id: int, harvest_id: int, data: DryingLogEntry):
    progress = await service.add_drying_log(session_id, harvest_id, data.weight_g)
    if not progress:
        raise HTTPException(404, "Harvest not found")
    return progress


@router.get("/{session_id}/harvest/{harvest_id}/drying")
async def get_drying_progress(session_id: int, harvest_id: int):
    progress = await service.get_drying_progress(session_id, harvest_id)
    if not progress:
        raise HTTPException(404, "Harvest not found")
    return progress


@router.post("/{session_id}/abort")
async def abort_session(session_id: int):
    session = await service.abort_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/complete")
async def complete_session(session_id: int):
    session = await service.complete_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session
