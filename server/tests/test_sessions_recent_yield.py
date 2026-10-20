"""GET /api/sessions?yield_since=: the grams each grow had harvested since a
time, for the dashboard's "yield in the last 30 days". It summed the total
yield of grows STARTED in the window, so a flush picked last week from a grow
started six weeks ago counted for nothing."""

import time

from app.db import get_db
from app.sessions.models import HarvestCreate, SessionCreate
from app.sessions.service import add_harvest, create_session, generate_session_report_md, list_sessions
from app.transcript.service import export_markdown

DAY = 86_400


async def _backdate_harvests(session_id: int, ts: float) -> None:
    async with get_db() as db:
        await db.execute("UPDATE harvests SET timestamp = ? WHERE session_id = ?", (ts, session_id))
        await db.commit()


async def test_rows_carry_the_grams_harvested_since_the_given_time():
    now = time.time()
    old_grow = await create_session(SessionCreate(name="Six weeks", species_profile_id="blue_oyster"))
    new_grow = await create_session(SessionCreate(name="Yesterday", species_profile_id="blue_oyster"))
    await add_harvest(old_grow["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))
    await _backdate_harvests(old_grow["id"], now - 40 * DAY)  # flush 1, outside the window
    await add_harvest(old_grow["id"], HarvestCreate(flush_number=2, wet_weight_g=100.1))
    await add_harvest(old_grow["id"], HarvestCreate(flush_number=2, wet_weight_g=200.2))

    rows = {r["name"]: r for r in await list_sessions(yield_since=now - 30 * DAY)}
    # this week's flush counts, the 40-day-old one does not; rounded to 0.1 g
    assert rows["Six weeks"]["wet_yield_since_g"] == 300.3
    assert rows["Six weeks"]["total_wet_yield_g"] > 600
    assert rows["Yesterday"]["wet_yield_since_g"] == 0
    assert new_grow["id"] in {r["id"] for r in rows.values()}


async def test_without_the_parameter_the_rows_are_unchanged():
    await create_session(SessionCreate(name="Grow", species_profile_id="blue_oyster"))
    [row] = await list_sessions()
    assert "wet_yield_since_g" not in row


async def test_the_transcript_and_report_print_yield_totals_to_a_tenth():
    s = await create_session(SessionCreate(name="Tenths", species_profile_id="blue_oyster"))
    await add_harvest(s["id"], HarvestCreate(flush_number=1, wet_weight_g=100.1))
    await add_harvest(s["id"], HarvestCreate(flush_number=2, wet_weight_g=200.2))
    transcript = await export_markdown(s["id"])
    report = await generate_session_report_md(s["id"])
    assert "- Wet: 300.3g" in transcript
    assert "| Total Wet Yield | 300.3g |" in report
    assert "300.29999" not in transcript + report


def test_the_route_takes_yield_since(client):
    s = client.post("/api/sessions", json={"name": "G", "species_profile_id": "blue_oyster"}).json()
    assert client.post(f"/api/sessions/{s['id']}/harvest", json={"flush_number": 1, "wet_weight_g": 42.5}).status_code == 200
    since = time.time() - 30 * DAY
    [row] = client.get("/api/sessions", params={"yield_since": since}).json()
    assert row["wet_yield_since_g"] == 42.5
    [row] = client.get("/api/sessions").json()
    assert "wet_yield_since_g" not in row
