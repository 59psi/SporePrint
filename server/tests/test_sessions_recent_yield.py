"""GET /api/sessions?yield_since=: the grams each grow had harvested since a
time, for the dashboard's "yield in the last 30 days". It summed the total
yield of grows STARTED in the window, so a flush picked last week from a grow
started six weeks ago counted for nothing.

Harvests are stamped by SQLite's clock (`unixepoch('now')`), not Python's, so
the windows here are anchored to stamped times, never to time.time()."""

from app.db import get_db
from app.sessions.models import HarvestCreate, SessionCreate
from app.sessions.service import add_harvest, create_session, generate_session_report_md, list_sessions
from app.transcript.service import export_markdown

DAY = 86_400
NOW = 1_800_000_000.0


async def _stamp(harvest: dict, ts: float) -> None:
    async with get_db() as db:
        await db.execute("UPDATE harvests SET timestamp = ? WHERE id = ?", (ts, harvest["id"]))
        await db.commit()


async def test_rows_carry_the_grams_harvested_since_the_given_time():
    old_grow = await create_session(SessionCreate(name="Six weeks", species_profile_id="blue_oyster"))
    new_grow = await create_session(SessionCreate(name="Yesterday", species_profile_id="blue_oyster"))
    flush_1 = await add_harvest(old_grow["id"], HarvestCreate(flush_number=1, wet_weight_g=300.0))
    on_the_edge = await add_harvest(old_grow["id"], HarvestCreate(flush_number=2, wet_weight_g=100.1))
    this_week = await add_harvest(old_grow["id"], HarvestCreate(flush_number=2, wet_weight_g=200.2))
    await _stamp(flush_1, NOW - 40 * DAY)       # outside the window
    await _stamp(on_the_edge, NOW - 30 * DAY)   # at the window's start: counts
    await _stamp(this_week, NOW - 2 * DAY)

    rows = {r["name"]: r for r in await list_sessions(yield_since=NOW - 30 * DAY)}
    # this week's flush counts, the 40-day-old one does not; rounded to 0.1 g
    assert rows["Six weeks"]["wet_yield_since_g"] == 300.3
    assert rows["Six weeks"]["total_wet_yield_g"] == 600.3
    assert rows["Yesterday"]["wet_yield_since_g"] == 0
    assert rows["Yesterday"]["id"] == new_grow["id"]


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
    harvest = client.post(f"/api/sessions/{s['id']}/harvest", json={"flush_number": 1, "wet_weight_g": 42.5})
    assert harvest.status_code == 200
    picked_at = harvest.json()["timestamp"]
    [row] = client.get("/api/sessions", params={"yield_since": picked_at - 30 * DAY}).json()
    assert row["wet_yield_since_g"] == 42.5
    [row] = client.get("/api/sessions", params={"yield_since": picked_at + 1}).json()
    assert row["wet_yield_since_g"] == 0
    [row] = client.get("/api/sessions").json()
    assert "wet_yield_since_g" not in row
